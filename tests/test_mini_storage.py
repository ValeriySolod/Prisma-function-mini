import sqlite3
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from mini_domain import (
    CapacityType, MiniDateRange, NormalizedAuctionRecord, ProductType,
    SourceImportRequest, ValidationFailure, ValidationReason,
)
from mini_storage import AuctionConflictError, MiniAuctionStorage, StorageOutcome
from runtime_paths import RuntimePaths


SHA_A = "a" * 64
SHA_B = "b" * 64


def paths(root):
    app_root = root / "PrismaFunctionMini"
    return RuntimePaths(
        app_root, app_root / "data" / "prisma_function_mini.db",
        app_root / "data" / "result" / "prisma_function_mini.csv",
        app_root / "state" / "prisma_function_mini_state.json",
        app_root / "logs" / "prisma-function-mini.log",
        app_root / "temporary-downloads",
    )


def request(start=1, end=2, sha=SHA_A):
    return SourceImportRequest(MiniDateRange(date(2026, 7, start), date(2026, 7, end)),
                               "Auction_overview.csv", sha, 42)


def record(number=1, **changes):
    values = dict(
        auction_id=f"A-{number}", network_point_id=f"NP-{number}",
        auction_date=date(2026, 7, number), exit_market_or_storage="Exit",
        entry_market_or_storage="Entry", capacity_type=CapacityType.BUNDLE,
        network_point=f"Point {number}", product_type=ProductType.DAY_AHEAD,
        flow_start=datetime(2026, 7, number + 1, 6),
        flow_end=datetime(2026, 7, number + 2, 6),
        booked_capacity_kwh_h=Decimal("1000"), duration_hours=Decimal("24"),
        auction_tariff_eur_mwh_h=Decimal("1.25"),
        auction_premium_eur_mwh_h=None,
    )
    values.update(changes)
    return NormalizedAuctionRecord(**values)


def test_first_insert_exact_retry_and_success_audit(tmp_path):
    storage = MiniAuctionStorage(paths=paths(tmp_path))
    first = storage.store(request(), [record()])
    retry = storage.store(request(), [record()])
    assert (first.outcome, first.inserted, first.duplicates) == (StorageOutcome.COMPLETED, 1, 0)
    assert (retry.outcome, retry.inserted, retry.duplicates) == (StorageOutcome.COMPLETED, 0, 1)
    assert len(storage.history()) == 1
    audits = storage.operations()
    assert [(item.request.requested_range, item.inserted, item.duplicates) for item in audits] == [
        (request().requested_range, 1, 0), (request().requested_range, 0, 1)
    ]
    assert all(item.started_at.tzinfo is timezone.utc and item.completed_at.tzinfo is timezone.utc
               for item in audits)


def test_overlapping_ranges_and_reopen_preserve_cumulative_history(tmp_path):
    selected = paths(tmp_path)
    MiniAuctionStorage(paths=selected).store(request(1, 2), [record(1), record(2)])
    reopened = MiniAuctionStorage(paths=selected)
    outcome = reopened.store(request(2, 3, SHA_B), [record(2), record(3)])
    assert (outcome.inserted, outcome.duplicates) == (1, 1)
    assert [item.auction.auction_id for item in reopened.history()] == ["A-1", "A-2", "A-3"]


def test_same_key_changed_payload_is_audited_and_fails_closed(tmp_path):
    storage = MiniAuctionStorage(paths=paths(tmp_path))
    storage.store(request(), [record()])
    with pytest.raises(AuctionConflictError) as caught:
        storage.store(request(sha=SHA_B), [record(auction_tariff_eur_mwh_h=Decimal("2"))])
    assert (caught.value.result.conflicts, caught.value.result.inserted) == (1, 0)
    assert storage.history()[0].auction.auction_tariff_eur_mwh_h == Decimal("1.25")
    audit = storage.operations()[-1]
    assert audit.outcome is StorageOutcome.FAILED
    assert (audit.conflicts, audit.validation_failures) == (1, 0)
    assert audit.failures[0].reason is ValidationReason.CONFLICTING_DUPLICATE


def test_same_key_changed_premium_conflicts_and_blank_premium_round_trips(tmp_path):
    storage = MiniAuctionStorage(paths=paths(tmp_path))
    storage.store(request(), [record()])
    assert storage.history()[0].auction.auction_premium_eur_mwh_h is None
    with pytest.raises(AuctionConflictError):
        storage.store(
            request(sha=SHA_B),
            [record(auction_premium_eur_mwh_h=Decimal("0.25"))],
        )


def test_batch_conflict_writes_no_new_auctions(tmp_path):
    storage = MiniAuctionStorage(paths=paths(tmp_path))
    storage.store(request(), [record()])
    with pytest.raises(AuctionConflictError):
        storage.store(request(sha=SHA_B), [record(2), record(network_point="Changed")])
    assert [item.auction.auction_id for item in storage.history()] == ["A-1"]


def test_unexpected_mid_write_failure_rolls_back_auction_and_audit(tmp_path, monkeypatch):
    storage = MiniAuctionStorage(paths=paths(tmp_path))
    def fail(_record, position):
        if position == 1:
            raise sqlite3.OperationalError("injected write failure")
    monkeypatch.setattr(storage, "_before_insert", fail)
    with pytest.raises(sqlite3.OperationalError, match="injected"):
        storage.store(request(), [record(1), record(2)])
    assert storage.history() == ()
    assert storage.operations() == ()


def test_validation_failure_is_audited_without_history_mutation(tmp_path):
    storage = MiniAuctionStorage(paths=paths(tmp_path))
    failure = ValidationFailure(ValidationReason.INVALID_SOURCE_ROW, "Bad source row", 2, "Capacity")
    result = storage.store(request(), [], validation_failures=[failure])
    assert (result.outcome, result.validation_failures) == (StorageOutcome.FAILED, 1)
    assert storage.history() == ()
    assert storage.operations()[0].failures == (failure,)


def test_history_and_audit_read_order_is_deterministic(tmp_path):
    moments = iter([
        datetime(2026, 7, 20, 12, tzinfo=timezone(timedelta(hours=2))),
        datetime(2026, 7, 20, 10, 1, tzinfo=timezone.utc),
        datetime(2026, 7, 20, 10, 2, tzinfo=timezone.utc),
    ])
    storage = MiniAuctionStorage(paths=paths(tmp_path), clock=lambda: next(moments))
    storage.store(request(), [record(3), record(1), record(2)])
    assert [item.auction.auction_id for item in storage.history()] == ["A-1", "A-2", "A-3"]
    audit = storage.operations()[0]
    assert audit.started_at == datetime(2026, 7, 20, 10, tzinfo=timezone.utc)
    assert audit.completed_at == datetime(2026, 7, 20, 10, 2, tzinfo=timezone.utc)


def test_schema_initialization_is_repeatable_and_preserves_unrelated_table(tmp_path):
    selected = paths(tmp_path)
    first = MiniAuctionStorage(paths=selected)
    with sqlite3.connect(first.database_path) as connection:
        connection.execute("CREATE TABLE unrelated (value TEXT)")
        connection.execute("INSERT INTO unrelated VALUES ('kept')")
    first.initialize_schema()
    MiniAuctionStorage(paths=selected)
    with sqlite3.connect(first.database_path) as connection:
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert connection.execute("SELECT value FROM unrelated").fetchone()[0] == "kept"
    assert {"mini_auctions", "mini_operations", "mini_operation_failures"} <= tables


def test_m5_database_is_upgraded_without_losing_history(tmp_path):
    selected = paths(tmp_path)
    selected.database.parent.mkdir(parents=True)
    with sqlite3.connect(selected.database) as connection:
        connection.executescript("""
            CREATE TABLE mini_auctions (
                id INTEGER PRIMARY KEY,
                auction_id TEXT NOT NULL, network_point_id TEXT NOT NULL,
                auction_date TEXT NOT NULL, exit_market_or_storage TEXT,
                entry_market_or_storage TEXT, capacity_type TEXT NOT NULL,
                network_point TEXT NOT NULL, product_type TEXT NOT NULL,
                flow_start TEXT NOT NULL, flow_end TEXT NOT NULL,
                booked_capacity_kwh_h TEXT NOT NULL, duration_hours TEXT NOT NULL,
                auction_tariff_eur_mwh_h TEXT NOT NULL, source_sha256 TEXT NOT NULL,
                accumulated_at_utc TEXT NOT NULL,
                UNIQUE(auction_id, network_point_id, capacity_type, flow_start, flow_end)
            );
            INSERT INTO mini_auctions VALUES (
                1, 'A-old', 'NP-old', '2026-07-01', NULL, NULL, 'Exit',
                'Old Point', 'Day Ahead', '2026-07-02T06:00:00',
                '2026-07-03T06:00:00', '1000', '24', '1.25',
                'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
                '2026-07-01T00:00:00+00:00'
            );
        """)
    history = MiniAuctionStorage(paths=selected).history()
    assert len(history) == 1
    assert history[0].auction.auction_id == "A-old"
    assert history[0].auction.auction_premium_eur_mwh_h is None


def test_database_location_is_approved_runtime_path(tmp_path):
    storage = MiniAuctionStorage(environ={"LOCALAPPDATA": str(tmp_path)})
    assert storage.database_path == (
        tmp_path / "PrismaFunctionMini" / "data" / "prisma_function_mini.db"
    )
    bad = paths(tmp_path)
    bad = RuntimePaths(bad.root, bad.root / "wrong.db", bad.result, bad.state,
                       bad.log, bad.temporary_downloads)
    with pytest.raises(ValueError, match="approved runtime path"):
        MiniAuctionStorage(paths=bad)
