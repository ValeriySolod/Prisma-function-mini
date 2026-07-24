import csv
import threading
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from mini_csv import MiniCsvError, MiniCsvPublisher
from mini_domain import MiniDateRange, ProductType, SourceImportRequest, ValidationReason
from mini_download import MiniDownloadedSource
from mini_storage import AuctionConflictError, MiniAuctionStorage
from mini_ui import MiniUiState, MiniWorkCancelled, MiniWorkRequest
from mini_workflow import (
    INPUT_COLUMNS,
    MiniIntegratedWorkflow,
    MiniWorkflowError,
    classify_product,
    parse_source,
)
from runtime_paths import RuntimePaths


def paths(root: Path) -> RuntimePaths:
    runtime = root / "runtime"
    return RuntimePaths(
        runtime, runtime / "data/prisma_function_mini.db",
        runtime / "data/result/prisma_function_mini.csv",
        runtime / "state/state.json", runtime / "logs/app.log",
        runtime / "temporary-downloads",
    )


def source_request(sha: str = "a" * 64) -> SourceImportRequest:
    return SourceImportRequest(
        MiniDateRange(date(2026, 3, 1), date(2026, 3, 31)),
        "Auction_overview.csv", sha, 100,
    )


def base_row(**changes) -> dict[str, str]:
    row = {name: "" for name in INPUT_COLUMNS}
    row.update({
        "Auction ID": "auction-1",
        "Start of Auction": "01.03.2026 06:00",
        "Network Point Name Exit": "Arnoldstein Exit",
        "Network Point ID Exit": "point-1",
        "Marketed Capacity": "24000",
        "Unit Marketed Capacity": "kWh/d",
        "Regulated Tariff Exit TSO": "2.4",
        "Unit Regulated Exit Capacity Tariff": "cent/kWh/d/Runtime",
        "Regulated Tariff Entry TSO": "999",
        "Unit Regulated Entry Capacity Tariff": "unsupported",
        "Surcharge": "1.2",
        "Unit Surcharge": "cent/kWh/d/Runtime",
        "Product Runtime Start": "28.03.2026 06:00",
        "Product Runtime End": "29.03.2026 06:00",
        "Direction": "Exit",
    })
    row.update(changes)
    return row


def write_source(path: Path, rows: list[dict[str, str]], *, header=INPUT_COLUMNS) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="cp1252", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=header, delimiter=";", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


class FakeSession:
    def __init__(self, paths_: RuntimePaths, rows=None, *, error=None, hook=None):
        self.paths = paths_
        self.rows = [] if rows is None else rows
        self.error = error
        self.hook = hook
        self.calls = 0

    def download_csv(self, cancel_event, requested_range):
        self.calls += 1
        if self.hook:
            self.hook(cancel_event)
        if self.error:
            raise self.error
        operation = self.paths.temporary_downloads / f"operation-{self.calls}"
        source = operation / "Auction_overview.csv"
        write_source(source, self.rows)
        request = SourceImportRequest(requested_range, source.name, f"{self.calls:064x}", source.stat().st_size)
        return MiniDownloadedSource(source.resolve(), request)


def run(subject: MiniIntegratedWorkflow, cancel=None):
    states = []
    result = subject.run(
        MiniWorkRequest(source_request().requested_range),
        cancel or threading.Event(),
        lambda state, message: states.append((state, message)),
    )
    return result, states


@pytest.mark.parametrize(
    ("start", "end", "product", "hours"),
    [
        (datetime(2026, 7, 1, 10), datetime(2026, 7, 2, 6), ProductType.WITHIN_DAY, "20"),
        (datetime(2026, 3, 28, 6), datetime(2026, 3, 29, 6), ProductType.DAY_AHEAD, "23"),
        (datetime(2026, 3, 29, 6), datetime(2026, 3, 30, 6), ProductType.DAY_AHEAD, "24"),
        (datetime(2026, 10, 24, 6), datetime(2026, 10, 25, 6), ProductType.DAY_AHEAD, "25"),
        (datetime(2026, 3, 1, 6), datetime(2026, 4, 1, 6), ProductType.MONTH, "743"),
        (datetime(2026, 4, 1, 6), datetime(2026, 7, 1, 6), ProductType.QUARTER, "2184"),
        (datetime(2026, 10, 1, 6), datetime(2027, 10, 1, 6), ProductType.YEAR, "8760"),
    ],
)
def test_product_boundaries_and_dst_duration(start, end, product, hours):
    assert classify_product(start, end) == (product, Decimal(hours))


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (datetime(2026, 7, 1, 6), datetime(2026, 7, 3, 6)),
        (datetime(2026, 2, 2, 6), datetime(2026, 3, 2, 6)),
        (datetime(2026, 1, 1, 6), datetime(2027, 1, 1, 6)),
    ],
)
def test_unmatched_product_period_is_rejected(start, end):
    with pytest.raises(ValueError, match="approved product boundary"):
        classify_product(start, end)


def test_success_uses_required_side_tariff_exact_mapping_and_premium(tmp_path):
    p = paths(tmp_path)
    session = FakeSession(p, [base_row()])
    workflow = MiniIntegratedWorkflow(p, session=session)
    result, states = run(workflow)
    history = workflow.storage.history()
    assert result == p.result
    assert [state for state, _ in states] == [
        MiniUiState.DOWNLOADING, MiniUiState.PROCESSING, MiniUiState.PUBLISHING
    ]
    assert len(history) == 1
    record = history[0].auction
    assert record.booked_capacity_kwh_h == Decimal("1000")
    assert record.auction_tariff_eur_mwh_h == Decimal("2.4") * Decimal("240") / Decimal("23")
    assert record.auction_premium_eur_mwh_h == Decimal("12.52173913043478260869565218")
    assert record.exit_market_or_storage == "CEGH"
    assert record.entry_market_or_storage == "PSV"
    assert not list(p.temporary_downloads.iterdir())


def test_empty_input_publishes_header_and_audits_zero_counts(tmp_path):
    p = paths(tmp_path)
    workflow = MiniIntegratedWorkflow(p, session=FakeSession(p))
    run(workflow)
    audit = workflow.storage.operations()[0]
    assert (audit.inserted, audit.duplicates, audit.validation_failures) == (0, 0, 0)
    assert p.result.read_text(encoding="utf-8").splitlines()[0].startswith("Auction Date;")


def test_mixed_inserted_duplicate_filtered_and_rejected_rows_are_accounted(tmp_path):
    p = paths(tmp_path)
    storage = MiniAuctionStorage(paths=p)
    first = MiniIntegratedWorkflow(p, session=FakeSession(p, [base_row()]), storage=storage)
    run(first)
    rows = [
        base_row(),
        base_row(**{"Auction ID": "auction-2", "Network Point ID Exit": "point-2"}),
        base_row(**{"Auction ID": "filtered", "Marketed Capacity": "23999"}),
        base_row(**{"Auction ID": "", "Network Point ID Exit": "missing-id"}),
    ]
    second = MiniIntegratedWorkflow(p, session=FakeSession(p, rows), storage=storage)
    run(second)
    audit = storage.operations()[-1]
    assert (audit.inserted, audit.duplicates, audit.validation_failures) == (1, 1, 1)
    assert audit.failures[0].reason is ValidationReason.MISSING_IDENTITY
    assert len(storage.history()) == 2


def test_exact_retry_and_overlapping_identity_are_idempotent(tmp_path):
    p = paths(tmp_path)
    storage = MiniAuctionStorage(paths=p)
    row = base_row()
    run(MiniIntegratedWorkflow(p, session=FakeSession(p, [row]), storage=storage))
    before = p.result.read_bytes()
    run(MiniIntegratedWorkflow(p, session=FakeSession(p, [row]), storage=storage))
    assert len(storage.history()) == 1
    assert storage.operations()[-1].duplicates == 1
    assert p.result.read_bytes() == before


def test_conflicting_duplicate_rolls_back_and_preserves_csv(tmp_path):
    p = paths(tmp_path)
    storage = MiniAuctionStorage(paths=p)
    run(MiniIntegratedWorkflow(p, session=FakeSession(p, [base_row()]), storage=storage))
    before = p.result.read_bytes()
    changed = base_row(**{"Regulated Tariff Exit TSO": "3.6"})
    with pytest.raises(AuctionConflictError):
        run(MiniIntegratedWorkflow(p, session=FakeSession(p, [changed]), storage=storage))
    assert len(storage.history()) == 1
    assert p.result.read_bytes() == before


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"Unit Marketed Capacity": "MWh/h"}, ValidationReason.UNSUPPORTED_UNIT),
        ({"Auction ID": ""}, ValidationReason.MISSING_IDENTITY),
        ({"Product Runtime End": "30.03.2026 12:00"}, ValidationReason.PRODUCT_TYPE_UNRESOLVED),
        ({"Regulated Tariff Exit TSO": ""}, ValidationReason.MISSING_REQUIRED_TARIFF),
        ({"Direction": "Exit/Entry", "Network Point ID Exit/Entry": "bundle",
          "Network Point Name Exit/Entry": "Arnoldstein Exit"}, ValidationReason.MISSING_REQUIRED_TARIFF),
    ],
)
def test_row_rejection_reasons(tmp_path, changes, reason):
    source = tmp_path / "source.csv"
    write_source(source, [base_row(**changes)])
    parsed = parse_source(source, threading.Event())
    assert parsed.total == parsed.failures.__len__() == 1
    assert parsed.failures[0].reason is reason


def test_entry_uses_only_entry_tariff_and_unresolved_mapping_stays_blank(tmp_path):
    source = tmp_path / "source.csv"
    row = base_row(**{
        "Direction": "Entry", "Network Point Name Entry": "Unknown exact alias",
        "Network Point ID Entry": "entry-id", "Regulated Tariff Entry TSO": "4.8",
        "Unit Regulated Entry Capacity Tariff": "cent/kWh/d/Runtime",
        "Regulated Tariff Exit TSO": "", "Unit Regulated Exit Capacity Tariff": "",
    })
    write_source(source, [row])
    record = parse_source(source, threading.Event()).records[0]
    assert record.auction_tariff_eur_mwh_h == Decimal("4.8") * Decimal("240") / Decimal("23")
    assert record.exit_market_or_storage is None
    assert record.entry_market_or_storage is None


def test_malformed_header_and_row_width(tmp_path):
    malformed = tmp_path / "bad-header.csv"
    write_source(malformed, [], header=INPUT_COLUMNS[:-1])
    with pytest.raises(MiniWorkflowError, match="header contract"):
        parse_source(malformed, threading.Event())
    width = tmp_path / "bad-width.csv"
    width.write_text(";".join(INPUT_COLUMNS) + "\nshort;row\n", encoding="cp1252")
    parsed = parse_source(width, threading.Event())
    assert parsed.failures[0].reason is ValidationReason.INVALID_SOURCE_ROW


def test_cancellation_before_parse_and_during_rows_cleans_download(tmp_path):
    p = paths(tmp_path)
    cancel = threading.Event()
    session = FakeSession(p, [base_row()], hook=lambda event: event.set())
    with pytest.raises(MiniWorkCancelled):
        run(MiniIntegratedWorkflow(p, session=session), cancel)
    assert not list(p.temporary_downloads.iterdir())

    source = tmp_path / "many.csv"
    write_source(source, [base_row()])
    cancel.set()
    with pytest.raises(MiniWorkCancelled):
        parse_source(source, cancel)


def test_cancellation_before_storage_leaves_database_and_csv_unchanged(tmp_path):
    p = paths(tmp_path)
    workflow = MiniIntegratedWorkflow(p, session=FakeSession(p, [base_row()]))
    cancel = threading.Event()

    def progress(state, _message):
        if state is MiniUiState.PUBLISHING:
            cancel.set()

    with pytest.raises(MiniWorkCancelled):
        workflow.run(
            MiniWorkRequest(source_request().requested_range), cancel, progress
        )
    assert not workflow.storage.history()
    assert not workflow.storage.operations()
    assert not p.result.exists()


def test_browser_failure_is_propagated_without_storage_or_output(tmp_path):
    p = paths(tmp_path)
    workflow = MiniIntegratedWorkflow(
        p, session=FakeSession(p, error=MiniWorkflowError("download failed"))
    )
    with pytest.raises(MiniWorkflowError, match="download failed"):
        run(workflow)
    assert not workflow.storage.history()
    assert not p.result.exists()


def test_storage_failure_rolls_back_and_preserves_previous_csv(tmp_path, monkeypatch):
    p = paths(tmp_path)
    storage = MiniAuctionStorage(paths=p)
    run(MiniIntegratedWorkflow(p, session=FakeSession(p, [base_row()]), storage=storage))
    before = p.result.read_bytes()
    monkeypatch.setattr(storage, "_before_insert", lambda *_args: (_ for _ in ()).throw(OSError("db")))
    row = base_row(**{"Auction ID": "new", "Network Point ID Exit": "new-point"})
    with pytest.raises(OSError):
        run(MiniIntegratedWorkflow(p, session=FakeSession(p, [row]), storage=storage))
    assert len(storage.history()) == 1
    assert p.result.read_bytes() == before


def test_publication_failure_rolls_back_database_and_preserves_csv(tmp_path, monkeypatch):
    p = paths(tmp_path)
    storage = MiniAuctionStorage(paths=p)
    workflow = MiniIntegratedWorkflow(p, session=FakeSession(p, [base_row()]), storage=storage)
    p.result.parent.mkdir(parents=True, exist_ok=True)
    p.result.write_bytes(b"previous")
    monkeypatch.setattr(
        workflow.publisher, "publish_records",
        lambda _records: (_ for _ in ()).throw(MiniCsvError("publish")),
    )
    with pytest.raises(MiniCsvError):
        run(workflow)
    assert not storage.history()
    assert not storage.operations()
    assert p.result.read_bytes() == b"previous"


def test_cleanup_failure_prevents_persistence(tmp_path, monkeypatch):
    p = paths(tmp_path)
    workflow = MiniIntegratedWorkflow(p, session=FakeSession(p, [base_row()]))
    monkeypatch.setattr(
        "mini_workflow.shutil.rmtree",
        lambda _path: (_ for _ in ()).throw(OSError("locked")),
    )
    with pytest.raises(MiniWorkflowError, match="could not be cleaned"):
        run(workflow)
    assert not workflow.storage.history()
