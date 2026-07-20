from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Protocol

from auction_csv import AuctionCsvRecord
from monitoring import MonitoringEngine, MonitoringResult


class StopEvent(Protocol):
    """Minimal event contract required by the scheduler."""

    def is_set(self) -> bool: ...

    def wait(self, timeout: float | None = None) -> bool: ...


class MonitoringScheduler:
    """Run a monitoring engine immediately and at a fixed interval."""

    def __init__(
        self,
        engine: MonitoringEngine,
        records_provider: Callable[[], Iterable[AuctionCsvRecord]],
    ) -> None:
        self._engine = engine
        self._records_provider = records_provider

    def run_once(self, stop_event: StopEvent | None = None) -> list[MonitoringResult]:
        records = self._records_provider()
        return self._engine.check_records(records, stop_event)

    def run_forever(
        self,
        stop_event: StopEvent,
        interval_seconds: float,
        results_callback: Callable[[list[MonitoringResult]], None] | None = None,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be greater than zero.")

        while not stop_event.is_set():
            results = self.run_once(stop_event)
            if results_callback is not None:
                results_callback(results)
            if stop_event.wait(interval_seconds):
                return
