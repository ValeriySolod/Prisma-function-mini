from datetime import datetime, timezone
from threading import Event

import pytest

from auction_csv import AuctionCsvRecord
from monitoring import MonitoringEngine
from prisma_page import PrismaAuctionNotFoundError


def record(auction_id="A-001", status="Open", enabled=True):
    return AuctionCsvRecord(
        auction_id, "https://example.com/a", "1", "Item", "Open", status, 60, enabled
    )


def test_unchanged_status():
    result = MonitoringEngine(lambda _: "Open").check_record(record())
    assert (result.result, result.status_changed, result.current_status) == ("Success", False, "Open")


def test_changed_status():
    result = MonitoringEngine(lambda _: "Completed").check_record(record())
    assert (result.result, result.status_changed, result.current_status) == ("Changed", True, "Completed")


def test_whitespace_normalization_applies_to_both_statuses():
    result = MonitoringEngine(lambda _: "  Open  ").check_record(record(status=" Open "))
    assert result.result == "Success"
    assert result.current_status == "Open"
    assert result.status_changed is False


@pytest.mark.parametrize("stopped,enabled", [(False, False), (True, True)])
def test_disabled_or_stopped_record_is_skipped_without_checker(stopped, enabled):
    calls = []
    event = Event()
    if stopped:
        event.set()
    result = MonitoringEngine(lambda item: calls.append(item) or "Open").check_record(
        record(enabled=enabled), event
    )
    assert result.result == "Skipped"
    assert result.current_status == result.previous_status
    assert result.status_changed is False
    assert result.error_message == ""
    assert calls == []


def test_checker_exception_is_converted_to_error():
    def fail(_):
        raise RuntimeError("service unavailable")

    result = MonitoringEngine(fail).check_record(record())
    assert result.result == "Error"
    assert result.current_status == "Open"
    assert result.status_changed is False
    assert "service unavailable" in result.error_message


def test_empty_checker_result_is_converted_to_error():
    result = MonitoringEngine(lambda _: "  ").check_record(record())
    assert result.result == "Error"
    assert "empty status" in result.error_message


def test_failed_record_does_not_block_later_records_and_order_is_preserved():
    def checker(item):
        if item.auction_id == "A-001":
            raise RuntimeError("failed")
        return "Completed"

    records = [record("A-001"), record("A-002")]
    results = MonitoringEngine(checker).check_records(records)
    assert [item.auction_id for item in results] == ["A-001", "A-002"]
    assert [item.result for item in results] == ["Error", "Changed"]
    assert len(results) == len(records)


def test_missing_auction_is_nonfatal_and_later_live_record_is_checked():
    def checker(item):
        if item.auction_id == "A-001":
            raise PrismaAuctionNotFoundError(
                "No live auction row matches Auction ID A-001."
            )
        return "Completed"

    results = MonitoringEngine(checker).check_records(
        [record("A-001"), record("A-002")]
    )

    assert results[0].result == "Error"
    assert "No live auction row matches Auction ID A-001" in results[0].error_message
    assert results[1].result == "Changed"
    assert results[1].current_status == "Completed"


def test_stop_during_batch_skips_all_remaining_records():
    event = Event()
    calls = []

    def checker(item):
        calls.append(item.auction_id)
        event.set()
        return "Open"

    records = [record("A-001"), record("A-002"), record("A-003", enabled=False)]
    results = MonitoringEngine(checker).check_records(records, event)
    assert calls == ["A-001"]
    assert [item.result for item in results] == ["Success", "Skipped", "Skipped"]
    assert [item.auction_id for item in results] == [item.auction_id for item in records]


def test_injected_clock_is_deterministic_and_called_once_per_result():
    times = iter(
        [datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 2, tzinfo=timezone.utc)]
    )
    calls = []

    def clock():
        calls.append(True)
        return next(times)

    results = MonitoringEngine(lambda _: "Open", clock).check_records(
        [record("A-001"), record("A-002", enabled=False)]
    )
    assert [item.checked_at.day for item in results] == [1, 2]
    assert len(calls) == 2
