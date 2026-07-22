"""PySide6-independent contracts for the minimal Mini user interface."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from pathlib import Path

from mini_domain import MiniDateRange


class MiniUiState(Enum):
    IDLE = "Idle"
    VALIDATING = "Validating"
    OPENING_PRISMA = "Opening PRISMA"
    DOWNLOADING = "Downloading"
    PROCESSING = "Processing"
    PUBLISHING = "Publishing"
    COMPLETED = "Completed"
    CANCELLING = "Cancelling"
    ERROR = "Error"

    @classmethod
    def worker_progress_states(cls) -> frozenset[MiniUiState]:
        return frozenset({cls.OPENING_PRISMA, cls.DOWNLOADING, cls.PROCESSING, cls.PUBLISHING})


ACTIVE_STATES = frozenset(
    {
        MiniUiState.VALIDATING,
        MiniUiState.OPENING_PRISMA,
        MiniUiState.DOWNLOADING,
        MiniUiState.PROCESSING,
        MiniUiState.PUBLISHING,
        MiniUiState.CANCELLING,
    }
)


@dataclass(frozen=True)
class UiActionPolicy:
    dates_enabled: bool
    start_enabled: bool
    cancel_enabled: bool
    open_result_enabled: bool


class MiniUiStateModel:
    def __init__(self) -> None:
        self.state = MiniUiState.IDLE
        self.message = "Ready. Select a date range."

    @property
    def is_active(self) -> bool:
        return self.state in ACTIVE_STATES

    def transition(self, state: MiniUiState, message: str) -> None:
        if not isinstance(state, MiniUiState):
            raise TypeError("state must be a MiniUiState")
        cleaned = message.strip()
        if not cleaned:
            raise ValueError("A truthful status message is required.")
        self.state = state
        self.message = cleaned

    def action_policy(self, result_exists: bool) -> UiActionPolicy:
        active = self.is_active
        return UiActionPolicy(
            dates_enabled=not active,
            start_enabled=not active,
            cancel_enabled=active and self.state is not MiniUiState.CANCELLING,
            open_result_enabled=not active and result_exists,
        )


@dataclass(frozen=True)
class DateValidationResult:
    date_range: MiniDateRange | None
    error: str | None


def validate_date_range(start: date, end: date, *, today: date | None = None) -> DateValidationResult:
    current = today or date.today()
    if type(start) is not date or type(end) is not date:
        raise TypeError("Start and end must be dates.")
    if start > end:
        return DateValidationResult(None, "Start date must not be later than end date.")
    if start > current or end > current:
        return DateValidationResult(None, "Future dates are not supported.")
    return DateValidationResult(MiniDateRange(start, end), None)


@dataclass(frozen=True)
class MiniWorkRequest:
    date_range: MiniDateRange


class MiniWorkCancelled(Exception):
    """Expected cooperative cancellation from a future workflow runner."""


@dataclass(frozen=True)
class MiniWorkOutcome:
    generation: int
    result_path: Path | None = None
    error: str | None = None
    was_cancelled: bool = False

    @classmethod
    def completed(cls, generation: int, result_path: Path | None) -> MiniWorkOutcome:
        return cls(generation, result_path=result_path)

    @classmethod
    def failed(cls, generation: int, error: str) -> MiniWorkOutcome:
        return cls(generation, error=error)

    @classmethod
    def cancelled(cls, generation: int) -> MiniWorkOutcome:
        return cls(generation, was_cancelled=True)

    @property
    def public_error(self) -> str:
        if self.error == "Processing is not available in this version yet.":
            return self.error
        return "Processing failed. Please try again."
