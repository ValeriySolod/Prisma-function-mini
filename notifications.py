from __future__ import annotations

from dataclasses import dataclass

from monitoring import MonitoringResult


@dataclass(frozen=True)
class StatusChangeNotification:
    """A user-visible notification for one persisted status transition."""

    auction_id: str
    previous_status: str
    current_status: str

    @classmethod
    def from_result(
        cls, result: MonitoringResult
    ) -> StatusChangeNotification | None:
        previous_status = result.previous_status.strip()
        current_status = result.current_status.strip()
        if not (
            result.status_changed
            and result.result == "Changed"
            and previous_status
            and current_status
            and previous_status != current_status
        ):
            return None
        return cls(result.auction_id, previous_status, current_status)

    def message(self) -> str:
        return (
            f"Auction {self.auction_id}: {self.previous_status} "
            f"→ {self.current_status}"
        )
