import csv
import threading
from datetime import date
from pathlib import Path

import pytest

from mini_csv import MiniCsvError
from mini_domain import MiniDateRange, SourceImportRequest
from mini_download import MiniDownloadedSource
from mini_storage import AuctionConflictError, MiniAuctionStorage, StorageOutcome
from mini_ui import MiniWorkCancelled, MiniWorkRequest
from mini_workflow import INPUT_COLUMNS, MiniIntegratedWorkflow, MiniWorkflowError
from runtime_paths import RuntimePaths


def runtime_paths(root: Path) -> RuntimePaths:
    runtime = root / "runtime"
    return RuntimePaths(
        runtime,
        runtime / "data/prisma_function_mini.db",
        runtime / "data/result/prisma_function_mini.csv",
        runtime / "state/state.json",
        runtime / "logs/app.log",
        runtime / "temporary-downloads",
    )


def row(auction_id: str, day: int, *, capacity: str = "24000") -> dict[str, str]:
    values = {name: "" for name in INPUT_COLUMNS}
    values.update(
        {
            "Auction ID": auction_id,
            "Start of Auction": f"{day:02d}.03.2026 06:00",
            "Network Point Name Exit": "Arnoldstein Exit",
            "Network Point ID Exit": f"point-{auction_id}",
            "Marketed Capacity": capacity,
            "Unit Marketed Capacity": "kWh/d",
            "Regulated Tariff Exit TSO": "2.4",
            "Unit Regulated Exit Capacity Tariff": "cent/kWh/d/Runtime",
            "Product Runtime Start": f"{day:02d}.03.2026 06:00",
            "Product Runtime End": f"{day + 1:02d}.03.2026 06:00",
            "Direction": "Exit",
        }
    )
    return values


def write_source(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="cp1252", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=INPUT_COLUMNS, delimiter=";", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


class FakeSession:
    def __init__(self, paths: RuntimePaths, batches, *, error: Exception | None = None):
        self.paths = paths
        self.batches = iter(batches)
        self.error = error
        self.calls = 0

    def download_csv(self, cancel_event, requested_range):
        self.calls += 1
        if self.error is not None:
            raise self.error
        operation = self.paths.temporary_downloads / f"{self.calls:032x}"
        source = operation / "Auction_overview.csv"
        write_source(source, next(self.batches))
        request = SourceImportRequest(
            requested_range, source.name, f"{self.calls:064x}", source.stat().st_size
        )
        return MiniDownloadedSource(source.resolve(), request)


def execute(workflow: MiniIntegratedWorkflow, start: int, end: int) -> Path:
    return workflow.run(
        MiniWorkRequest(MiniDateRange(date(2026, 3, start), date(2026, 3, end))),
        threading.Event(),
        lambda _state, _message: None,
    )


def test_consecutive_overlap_exact_retry_and_restart_are_cumulative(tmp_path):
    paths = runtime_paths(tmp_path)
    first = MiniIntegratedWorkflow(
        paths, session=FakeSession(paths, [[row("a", 1)]])
    )
    execute(first, 1, 1)
    first_csv = paths.result.read_bytes()

    second = MiniIntegratedWorkflow(
        paths,
        session=FakeSession(
            paths,
            [[
                row("a", 1),
                row("b", 2),
                row("filtered", 2, capacity="23999"),
                {**row("rejected", 2), "Auction ID": ""},
            ]],
        ),
    )
    execute(second, 1, 2)
    assert paths.result.read_bytes() != first_csv

    retry = MiniIntegratedWorkflow(
        paths, session=FakeSession(paths, [[row("a", 1), row("b", 2)]])
    )
    before_retry = paths.result.read_bytes()
    execute(retry, 1, 2)

    reopened = MiniAuctionStorage(paths=paths)
    audits = reopened.operations()
    assert [item.outcome for item in audits] == [StorageOutcome.COMPLETED] * 3
    assert [(item.inserted, item.duplicates) for item in audits] == [
        (1, 0),
        (1, 1),
        (0, 2),
    ]
    assert [
        (item.filtered, item.validation_failures, item.source_rows)
        for item in audits
    ] == [(0, 0, 1), (1, 1, 4), (0, 0, 2)]
    assert len(reopened.history()) == 2
    assert paths.result.read_bytes() == before_retry


def test_restart_cleans_only_owned_artifacts_and_reconciles_from_sqlite(tmp_path):
    paths = runtime_paths(tmp_path)
    workflow = MiniIntegratedWorkflow(
        paths, session=FakeSession(paths, [[row("a", 1)]])
    )
    execute(workflow, 1, 1)
    expected = paths.result.read_bytes()

    paths.result.write_bytes(b"interrupted publication")
    owned_stage = paths.result.parent / ".prisma_function_mini-deadbeef.csv"
    owned_restore = paths.result.parent / ".prisma_function_mini-restore-deadbeef.csv"
    unrelated_result = paths.result.parent / "keep.csv"
    for artifact in (owned_stage, owned_restore, unrelated_result):
        artifact.write_text("keep", encoding="utf-8")
    abandoned_download = paths.temporary_downloads / ("a" * 32)
    abandoned_download.mkdir(parents=True)
    (abandoned_download / "Auction_overview.csv.part").write_text(
        "partial", encoding="utf-8"
    )
    unrelated_download = paths.temporary_downloads / "user-files"
    unrelated_download.mkdir()
    (unrelated_download / "keep.txt").write_text("keep", encoding="utf-8")

    recovered = MiniIntegratedWorkflow(paths).recover()

    assert recovered.removed_publication_artifacts == 2
    assert recovered.removed_download_operations == 1
    assert recovered.reconciled_output
    assert paths.result.read_bytes() == expected
    assert unrelated_result.read_text(encoding="utf-8") == "keep"
    assert (unrelated_download / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_failed_operations_preserve_last_valid_state_and_restart_retry_succeeds(
    tmp_path, monkeypatch
):
    paths = runtime_paths(tmp_path)
    execute(
        MiniIntegratedWorkflow(paths, session=FakeSession(paths, [[row("a", 1)]])),
        1,
        1,
    )
    before = paths.result.read_bytes()

    failed_download = MiniIntegratedWorkflow(
        paths,
        session=FakeSession(paths, [], error=MiniWorkflowError("download failed")),
    )
    with pytest.raises(MiniWorkflowError, match="download failed"):
        execute(failed_download, 2, 2)
    assert paths.result.read_bytes() == before

    failed_publish = MiniIntegratedWorkflow(
        paths, session=FakeSession(paths, [[row("b", 2)]])
    )
    monkeypatch.setattr(
        failed_publish.publisher,
        "publish_records",
        lambda _records: (_ for _ in ()).throw(MiniCsvError("publish failed")),
    )
    with pytest.raises(MiniCsvError, match="publish failed"):
        execute(failed_publish, 2, 2)
    assert paths.result.read_bytes() == before
    assert len(MiniAuctionStorage(paths=paths).history()) == 1
    assert len(MiniAuctionStorage(paths=paths).operations()) == 1

    execute(
        MiniIntegratedWorkflow(paths, session=FakeSession(paths, [[row("b", 2)]])),
        2,
        2,
    )
    reopened = MiniAuctionStorage(paths=paths)
    assert len(reopened.history()) == 2
    assert [(item.inserted, item.duplicates) for item in reopened.operations()] == [
        (1, 0),
        (1, 0),
    ]


def test_conflict_failure_and_recovered_exact_retry_have_stable_audits(tmp_path):
    paths = runtime_paths(tmp_path)
    execute(
        MiniIntegratedWorkflow(paths, session=FakeSession(paths, [[row("a", 1)]])),
        1,
        1,
    )
    conflicting = row("a", 1)
    conflicting["Regulated Tariff Exit TSO"] = "3.6"

    with pytest.raises(AuctionConflictError):
        execute(
            MiniIntegratedWorkflow(
                paths, session=FakeSession(paths, [[conflicting]])
            ),
            1,
            1,
        )
    execute(
        MiniIntegratedWorkflow(paths, session=FakeSession(paths, [[row("a", 1)]])),
        1,
        1,
    )

    audits = MiniAuctionStorage(paths=paths).operations()
    assert [item.outcome for item in audits] == [
        StorageOutcome.COMPLETED,
        StorageOutcome.FAILED,
        StorageOutcome.COMPLETED,
    ]
    assert [
        (item.inserted, item.duplicates, item.conflicts) for item in audits
    ] == [(1, 0, 0), (0, 0, 1), (0, 1, 0)]


def test_cancel_before_work_preserves_history_audit_csv_and_unrelated_files(tmp_path):
    paths = runtime_paths(tmp_path)
    execute(
        MiniIntegratedWorkflow(paths, session=FakeSession(paths, [[row("a", 1)]])),
        1,
        1,
    )
    before_csv = paths.result.read_bytes()
    before_audits = MiniAuctionStorage(paths=paths).operations()
    unrelated = paths.temporary_downloads / "keep.txt"
    unrelated.write_text("keep", encoding="utf-8")
    cancelled = threading.Event()
    cancelled.set()

    with pytest.raises(MiniWorkCancelled):
        MiniIntegratedWorkflow(
            paths, session=FakeSession(paths, [[row("b", 2)]])
        ).run(
            MiniWorkRequest(MiniDateRange(date(2026, 3, 2), date(2026, 3, 2))),
            cancelled,
            lambda _state, _message: None,
        )

    reopened = MiniAuctionStorage(paths=paths)
    assert len(reopened.history()) == 1
    assert reopened.operations() == before_audits
    assert paths.result.read_bytes() == before_csv
    assert unrelated.read_text(encoding="utf-8") == "keep"
