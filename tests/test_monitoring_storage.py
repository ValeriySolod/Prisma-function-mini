import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from auction_csv import AuctionCsvRecord
from monitoring import MonitoringEngine, MonitoringResult
from monitoring_storage import MonitoringStorage, MonitoringStorageError
from prisma_page import PrismaPageUnavailableError
from scheduler import MonitoringScheduler


UTC_TIME = datetime(2026, 7, 18, 9, 30, tzinfo=timezone.utc)


def result(status="Scheduled", current=None, kind="Success", *, auction_id="A-001", when=UTC_TIME):
    current = status if current is None else current
    return MonitoringResult(auction_id, when, status, current, kind == "Changed", kind,
                            "lookup failed" if kind == "Error" else "")


def record(auction_id="A-001", status="Scheduled", enabled=True):
    return AuctionCsvRecord(auction_id, "https://example.com", "L1", "Item", "Open",
                            status, 30, enabled)


def test_new_database_schema_foreign_keys_and_additive_existing_data(tmp_path):
    database = tmp_path / "runtime.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE auctions(id INTEGER PRIMARY KEY, value TEXT)")
        connection.execute("INSERT INTO auctions VALUES (1, 'preserved')")

    storage = MonitoringStorage(database)

    with sqlite3.connect(database) as connection:
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"monitoring_checks", "monitoring_status_transitions",
                "monitoring_latest_status"} <= tables
        assert connection.execute("SELECT value FROM auctions").fetchone()[0] == "preserved"
    with storage._connection() as connection:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_unchanged_changed_repeated_and_multiple_transitions(tmp_path):
    storage = MonitoringStorage(tmp_path / "runtime.db")
    storage.persist(result())
    storage.persist(result(current="Open", kind="Changed", when=UTC_TIME + timedelta(seconds=1)))
    storage.persist(result(status="Open", current="Open", when=UTC_TIME + timedelta(seconds=2)))
    storage.persist(result(status="Open", current="Closed", kind="Changed",
                           when=UTC_TIME + timedelta(seconds=3)))

    assert [item.result for item in storage.check_history()] == [
        "Success", "Changed", "Success", "Changed"]
    assert [(item.previous_status, item.current_status) for item in storage.transition_history()] == [
        ("Scheduled", "Open"), ("Open", "Closed")]
    assert storage.latest_status("A-001") == "Closed"


def test_direct_persistence_canonicalizes_inconsistent_success_forms(tmp_path):
    storage = MonitoringStorage(tmp_path / "runtime.db")

    changed = storage.persist(result(status="Scheduled", current="Open", kind="Success"))
    unchanged = storage.persist(result(status="Open", current="Open", kind="Changed",
                                       when=UTC_TIME + timedelta(seconds=1)))

    assert changed is not None
    assert (changed.previous_status, changed.current_status,
            changed.status_changed, changed.result) == (
                "Scheduled", "Open", True, "Changed")
    assert unchanged is not None
    assert (unchanged.previous_status, unchanged.current_status,
            unchanged.status_changed, unchanged.result) == (
                "Open", "Open", False, "Success")
    assert len(storage.transition_history()) == 1


def test_transaction_rechecks_durable_baseline_after_stale_earlier_read(tmp_path):
    storage = MonitoringStorage(tmp_path / "runtime.db")
    assert storage.latest_status("A-001") is None
    storage.persist(result(status="Scheduled", current="Open", kind="Changed"))

    canonical = storage.persist(result(
        status="Scheduled", current="Open", kind="Changed",
        when=UTC_TIME + timedelta(seconds=1),
    ))

    assert canonical is not None
    assert (canonical.previous_status, canonical.result,
            canonical.status_changed) == ("Open", "Success", False)
    assert len(storage.transition_history()) == 1


def test_error_audited_without_transition_or_state_advance_and_skipped_ignored(tmp_path):
    storage = MonitoringStorage(tmp_path / "runtime.db")
    storage.persist(result(current="Open", kind="Changed"))
    storage.persist(result(status="Open", current="Open", kind="Error",
                           when=UTC_TIME + timedelta(seconds=1)))
    storage.persist(result(status="Open", current="Open", kind="Skipped",
                           when=UTC_TIME + timedelta(seconds=2)))

    assert [item.result for item in storage.check_history()] == ["Changed", "Error"]
    assert len(storage.transition_history()) == 1
    assert storage.latest_status("A-001") == "Open"


def test_error_is_canonicalized_to_durable_baseline_without_advancing(tmp_path):
    storage = MonitoringStorage(tmp_path / "runtime.db")
    storage.persist(result(status="Scheduled", current="Open", kind="Changed"))

    canonical = storage.persist(result(
        status="stale CSV", current="untrusted fallback", kind="Error",
        when=UTC_TIME + timedelta(seconds=1),
    ))

    assert canonical is not None
    assert (canonical.previous_status, canonical.current_status,
            canonical.status_changed, canonical.result) == (
                "Open", "Open", False, "Error")
    assert storage.latest_status("A-001") == "Open"
    assert len(storage.transition_history()) == 1


def test_engine_restores_baseline_after_reopen_and_overrides_stale_csv(tmp_path):
    database = tmp_path / "runtime.db"
    first = MonitoringStorage(database)
    engine = MonitoringEngine(lambda _: "Open", clock=lambda: UTC_TIME, persistence=first)
    initial = engine.check_record(record(status="Scheduled"))
    assert (initial.previous_status, initial.result) == ("Scheduled", "Changed")

    reopened = MonitoringStorage(database)
    second = MonitoringEngine(lambda _: "Open", clock=lambda: UTC_TIME + timedelta(seconds=1),
                              persistence=reopened).check_record(record(status="Scheduled"))
    assert (second.previous_status, second.result, second.status_changed) == (
        "Open", "Success", False)
    assert len(reopened.transition_history()) == 1


def test_scheduler_next_cycle_uses_newly_persisted_status(tmp_path):
    storage = MonitoringStorage(tmp_path / "runtime.db")
    statuses = iter(("Open", "Open"))
    scheduler = MonitoringScheduler(
        MonitoringEngine(lambda _: next(statuses), clock=lambda: UTC_TIME,
                         persistence=storage),
        lambda: [record(status="Scheduled")],
    )
    first = scheduler.run_once()[0]
    second = scheduler.run_once()[0]
    assert (first.previous_status, first.result) == ("Scheduled", "Changed")
    assert (second.previous_status, second.result) == ("Open", "Success")
    assert len(storage.transition_history()) == 1


def test_csv_baseline_errors_independent_ids_ordering_and_timezone(tmp_path):
    storage = MonitoringStorage(tmp_path / "runtime.db")
    engine = MonitoringEngine(lambda row: "Open" if row.auction_id == "A" else "Closed",
                              clock=lambda: datetime(2026, 7, 18, 12, 30,
                                                     tzinfo=timezone(timedelta(hours=3))),
                              persistence=storage)
    a = engine.check_record(record("A", "Open"))
    b = engine.check_record(record("B", "Scheduled"))
    assert a.previous_status == "Open"
    assert b.previous_status == "Scheduled"
    assert storage.latest_statuses(["B", "A", "missing"]) == {"A": "Open", "B": "Closed"}
    assert [item.auction_id for item in storage.check_history()] == ["A", "B"]
    assert all(item.checked_at == datetime(2026, 7, 18, 9, 30, tzinfo=timezone.utc)
               for item in storage.check_history())


def test_naive_timestamp_is_rejected_without_writing(tmp_path):
    storage = MonitoringStorage(tmp_path / "runtime.db")
    with pytest.raises(MonitoringStorageError, match="timezone"):
        storage.persist(result(when=datetime(2026, 7, 18, 9, 30)))
    assert storage.check_history() == ()


@pytest.mark.parametrize(
    "invalid",
    [
        MonitoringResult(" ", UTC_TIME, "Scheduled", "Open", True, "Changed", ""),
        MonitoringResult("A", UTC_TIME, " ", "Open", True, "Changed", ""),
        MonitoringResult("A", UTC_TIME, "Scheduled", " ", False, "Success", ""),
        MonitoringResult("A", UTC_TIME, "Scheduled", "Open", False, "Success", "error"),
        MonitoringResult("A", UTC_TIME, "Scheduled", "Scheduled", False, "Error", " "),
        MonitoringResult("A", UTC_TIME, "Scheduled", "Scheduled", True, "Error", "error"),
        MonitoringResult("A", UTC_TIME, "Scheduled", "Scheduled", False, "Unknown", ""),
    ],
)
def test_structurally_invalid_observations_are_rejected(tmp_path, invalid):
    storage = MonitoringStorage(tmp_path / "runtime.db")
    with pytest.raises(MonitoringStorageError):
        storage.persist(invalid)
    assert storage.check_history() == ()


def test_transaction_rolls_back_check_when_transition_insert_fails(tmp_path, monkeypatch):
    storage = MonitoringStorage(tmp_path / "runtime.db")

    class FailingConnection:
        def __init__(self, connection):
            self.connection = connection
        def execute(self, sql, parameters=()):
            if "INSERT INTO monitoring_status_transitions" in sql:
                raise sqlite3.IntegrityError("forced transition failure")
            return self.connection.execute(sql, parameters)
        def commit(self): self.connection.commit()
        def rollback(self): self.connection.rollback()
        def close(self): self.connection.close()

    original = storage._connect
    monkeypatch.setattr(storage, "_connect", lambda: FailingConnection(original()))
    with pytest.raises(MonitoringStorageError, match="could not be persisted"):
        storage.persist(result(current="Open", kind="Changed"))
    monkeypatch.setattr(storage, "_connect", original)
    assert storage.check_history() == ()


def test_rollback_and_close_failures_do_not_replace_primary_error(tmp_path, monkeypatch):
    storage = MonitoringStorage(tmp_path / "runtime.db")
    primary = ValueError("primary")

    class BrokenConnection:
        def execute(self, *_): return None
        def rollback(self): raise RuntimeError("rollback failed")
        def close(self): raise RuntimeError("close failed")

    connection = BrokenConnection()
    with pytest.raises(ValueError) as transaction_error:
        with storage._transaction(connection):
            raise primary
    assert transaction_error.value is primary
    assert "rollback failed" in " ".join(getattr(primary, "__notes__", ()))

    monkeypatch.setattr(storage, "_connect", lambda: connection)
    second_primary = ValueError("second primary")
    with pytest.raises(ValueError) as connection_error:
        with storage._connection():
            raise second_primary
    assert connection_error.value is second_primary
    assert "close failed" in " ".join(getattr(second_primary, "__notes__", ()))


def test_persistence_occurs_before_engine_returns_result(tmp_path):
    storage = MonitoringStorage(tmp_path / "runtime.db")
    engine = MonitoringEngine(lambda _: "Open", clock=lambda: UTC_TIME, persistence=storage)
    observed = engine.check_records([record()])
    assert storage.check_history()[0].current_status == observed[0].current_status


def test_engine_returns_storage_canonical_result(tmp_path):
    storage = MonitoringStorage(tmp_path / "runtime.db")
    storage.persist(result(status="Scheduled", current="Open", kind="Changed"))
    engine = MonitoringEngine(lambda _: "Open", clock=lambda: UTC_TIME + timedelta(seconds=1),
                              persistence=storage)

    observed = engine.check_record(record(status="stale CSV"))

    assert (observed.previous_status, observed.current_status,
            observed.status_changed, observed.result) == (
                "Open", "Open", False, "Success")
    persisted = storage.check_history()[-1]
    assert (persisted.previous_status, persisted.current_status,
            persisted.status_changed, persisted.result) == (
                observed.previous_status, observed.current_status,
                observed.status_changed, observed.result)


def test_typed_live_failure_is_audited_then_preserved(tmp_path):
    storage = MonitoringStorage(tmp_path / "runtime.db")
    failure = PrismaPageUnavailableError("page closed")
    engine = MonitoringEngine(lambda _: (_ for _ in ()).throw(failure),
                              clock=lambda: UTC_TIME, persistence=storage)
    with pytest.raises(PrismaPageUnavailableError) as raised:
        engine.check_record(record())
    assert raised.value is failure
    assert [item.result for item in storage.check_history()] == ["Error"]
    assert storage.latest_status("A-001") is None
