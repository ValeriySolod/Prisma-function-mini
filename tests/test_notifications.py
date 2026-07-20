from datetime import datetime

import pytest

from monitoring import MonitoringResult
from notifications import StatusChangeNotification


def result(
    *,
    auction_id: str = "A-17",
    previous_status: str = "Scheduled",
    current_status: str = "Open",
    status_changed: bool = True,
    result_name: str = "Changed",
    error_message: str = "",
) -> MonitoringResult:
    return MonitoringResult(
        auction_id,
        datetime(2026, 1, 2, 3, 4, 5),
        previous_status,
        current_status,
        status_changed,
        result_name,
        error_message,
    )


def test_changed_persisted_transition_has_exact_notification_message():
    notification = StatusChangeNotification.from_result(result())

    assert notification is not None
    assert notification.message() == "Auction A-17: Scheduled → Open"


@pytest.mark.parametrize(
    "candidate",
    [
        result(status_changed=False, result_name="Success"),
        result(status_changed=False, result_name="Changed"),
        result(status_changed=True, result_name="Success"),
        result(previous_status="Open", current_status="Open", status_changed=False,
               result_name="Success"),
        result(previous_status="", current_status="Open"),
        result(previous_status="Scheduled", current_status=""),
        result(previous_status="Open", current_status="Open"),
        result(result_name="Skipped", status_changed=False),
        result(result_name="Error", status_changed=False, error_message="lookup failed"),
        result(result_name="Error", error_message="persistence failed"),
    ],
)
def test_non_transitions_and_malformed_results_are_not_eligible(candidate):
    assert StatusChangeNotification.from_result(candidate) is None
