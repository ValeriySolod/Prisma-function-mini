from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Iterable, Protocol

from auction_csv import AuctionCsvRecord
from prisma_page import PrismaAuctionNotFoundError, PrismaPageAdapterError


class StatusChecker(Protocol):
    """Callable contract for obtaining an auction's current status."""

    def __call__(self, record: AuctionCsvRecord) -> str: ...


@dataclass(frozen=True)
class MonitoringResult:
    auction_id: str
    checked_at: datetime
    previous_status: str
    current_status: str
    status_changed: bool
    result: str
    error_message: str


class MonitoringPersistence(Protocol):
    """Persistence boundary used by the monitoring engine."""

    def persist(self, result: MonitoringResult) -> MonitoringResult | None: ...


class MonitoringEngine:
    """Check auction records without owning scheduling or threading."""

    def __init__(
        self,
        status_checker: StatusChecker,
        clock: Callable[[], datetime] | None = None,
        persistence: MonitoringPersistence | None = None,
    ) -> None:
        self._status_checker = status_checker
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._persistence = persistence

    def _result(
        self,
        record: AuctionCsvRecord,
        *,
        current_status: str,
        status_changed: bool,
        result: str,
        error_message: str = "",
        previous_status: str | None = None,
    ) -> MonitoringResult:
        return MonitoringResult(
            auction_id=record.auction_id,
            checked_at=self._clock(),
            previous_status=(
                record.last_known_status
                if previous_status is None
                else previous_status
            ),
            current_status=current_status,
            status_changed=status_changed,
            result=result,
            error_message=error_message,
        )

    def check_record(self, record: AuctionCsvRecord, stop_event=None) -> MonitoringResult:
        previous_status = record.last_known_status
        if (stop_event is not None and stop_event.is_set()) or not record.enabled:
            return self._result(
                record,
                current_status=previous_status,
                status_changed=False,
                result="Skipped",
                previous_status=previous_status,
            )

        try:
            current_status = self._status_checker(record).strip()
            if not current_status:
                raise ValueError("The status checker returned an empty status.")
        except PrismaAuctionNotFoundError as error:
            reason = str(error).strip() or error.__class__.__name__
            result = self._result(
                record,
                current_status=previous_status,
                status_changed=False,
                result="Error",
                error_message=f"Unable to check auction status: {reason}",
                previous_status=previous_status,
            )
            if self._persistence is not None:
                persisted = self._persistence.persist(result)
                if persisted is None:
                    raise RuntimeError("An actual monitoring check was not persisted.")
                return persisted
            return result
        except PrismaPageAdapterError as error:
            # Live page failures terminate the run so lifecycle recovery can
            # restore a retryable UI instead of continuing against a bad page.
            if self._persistence is not None:
                reason = str(error).strip() or error.__class__.__name__
                self._persistence.persist(
                    self._result(
                        record,
                        current_status=previous_status,
                        status_changed=False,
                        result="Error",
                        error_message=f"Unable to check auction status: {reason}",
                        previous_status=previous_status,
                    )
                )
            raise
        except Exception as error:
            reason = str(error).strip() or error.__class__.__name__
            result = self._result(
                record,
                current_status=previous_status,
                status_changed=False,
                result="Error",
                error_message=f"Unable to check auction status: {reason}",
                previous_status=previous_status,
            )
            if self._persistence is not None:
                persisted = self._persistence.persist(result)
                if persisted is None:
                    raise RuntimeError("An actual monitoring check was not persisted.")
                return persisted
            return result

        changed = previous_status.strip() != current_status
        result = self._result(
            record,
            current_status=current_status,
            status_changed=changed,
            result="Changed" if changed else "Success",
            previous_status=previous_status,
        )
        if self._persistence is not None:
            persisted = self._persistence.persist(result)
            if persisted is None:
                raise RuntimeError("An actual monitoring check was not persisted.")
            return persisted
        return result

    def check_records(
        self, records: Iterable[AuctionCsvRecord], stop_event=None
    ) -> list[MonitoringResult]:
        return [self.check_record(record, stop_event) for record in records]
