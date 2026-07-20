"""Deterministic lifecycle policy for locally supplied PRISMA exports."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, time
from enum import Enum
from pathlib import Path
from typing import Callable

from processor import PrismaImportResult, import_prisma_export


class SourceUpdateStatus(str, Enum):
    APPLIED = "applied"
    UNCHANGED = "unchanged"
    REJECTED = "rejected"


class SourceUpdateReason(str, Enum):
    APPLIED = "applied"
    IDENTICAL_SOURCE = "identical_source"
    STALE_SOURCE_DATE = "stale_source_date"
    CONFLICTING_SOURCE = "conflicting_source"
    FUTURE_SOURCE_DATE = "future_source_date"
    INVALID_SOURCE = "invalid_source"


_MESSAGES = {
    SourceUpdateReason.APPLIED: "The PRISMA source was validated and accepted.",
    SourceUpdateReason.IDENTICAL_SOURCE: "This exact PRISMA source was already accepted.",
    SourceUpdateReason.STALE_SOURCE_DATE: "The source date is older than the latest accepted source date.",
    SourceUpdateReason.CONFLICTING_SOURCE: "A different PRISMA source was already accepted for this source date.",
    SourceUpdateReason.FUTURE_SOURCE_DATE: "The source date is later than the evaluation date.",
    SourceUpdateReason.INVALID_SOURCE: "The PRISMA source did not pass authoritative import validation.",
}


def _require_exact_date(value: object, label: str = "source_date") -> date:
    if type(value) is not date:
        raise TypeError(f"{label} must be exactly datetime.date.")
    return value


def _require_aware(value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("evaluated_at must be a timezone-aware datetime.")
    return value


def _require_digest(value: object) -> None:
    if type(value) is not str or len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("Accepted source SHA-256 values must be lowercase hexadecimal digests.")


def _require_basename(value: object, label: str) -> str:
    if type(value) is not str or not value or Path(value).name != value:
        raise ValueError(f"{label} must be a non-empty basename.")
    return value


@dataclass(frozen=True)
class AcceptedPrismaSource:
    source_date: date
    source_name: str
    sha256: str

    def __post_init__(self) -> None:
        _require_exact_date(self.source_date, "accepted source_date")
        _require_basename(self.source_name, "Accepted source_name")
        _require_digest(self.sha256)


@dataclass(frozen=True)
class PrismaSourceState:
    accepted_sources: tuple[AcceptedPrismaSource, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.accepted_sources, tuple):
            raise TypeError("accepted_sources must be a tuple.")
        if any(not isinstance(item, AcceptedPrismaSource) for item in self.accepted_sources):
            raise TypeError("accepted_sources must contain only AcceptedPrismaSource values.")
        dates = tuple(item.source_date for item in self.accepted_sources)
        if dates != tuple(sorted(dates)) or len(dates) != len(set(dates)):
            raise ValueError("Accepted sources must have unique source dates in ascending order.")

    @property
    def latest_source_date(self) -> date | None:
        return self.accepted_sources[-1].source_date if self.accepted_sources else None

    def source_for(self, source_date: date) -> AcceptedPrismaSource | None:
        return next((item for item in self.accepted_sources if item.source_date == source_date), None)


@dataclass(frozen=True)
class PrismaSourceUpdateResult:
    source_date: date
    source_name: str
    sha256: str
    evaluated_at: datetime
    status: SourceUpdateStatus
    reason: SourceUpdateReason
    message: str
    accepted_state: PrismaSourceState
    total_count: int | None = None
    imported_count: int | None = None
    filtered_count: int | None = None
    rejected_count: int | None = None

    def __post_init__(self) -> None:
        _require_exact_date(self.source_date)
        _require_basename(self.source_name, "source_name")
        _require_digest(self.sha256)
        _require_aware(self.evaluated_at)
        if type(self.status) is not SourceUpdateStatus:
            raise TypeError("status must be SourceUpdateStatus.")
        if type(self.reason) is not SourceUpdateReason:
            raise TypeError("reason must be SourceUpdateReason.")
        if type(self.accepted_state) is not PrismaSourceState:
            raise TypeError("accepted_state must be PrismaSourceState.")
        expected_reasons = {
            SourceUpdateStatus.APPLIED: {SourceUpdateReason.APPLIED},
            SourceUpdateStatus.UNCHANGED: {SourceUpdateReason.IDENTICAL_SOURCE},
            SourceUpdateStatus.REJECTED: {
                SourceUpdateReason.STALE_SOURCE_DATE,
                SourceUpdateReason.CONFLICTING_SOURCE,
                SourceUpdateReason.FUTURE_SOURCE_DATE,
                SourceUpdateReason.INVALID_SOURCE,
            },
        }
        if self.reason not in expected_reasons[self.status]:
            raise ValueError("status and reason are inconsistent.")
        if type(self.message) is not str or self.message != _MESSAGES[self.reason]:
            raise ValueError("message must match the stable message for reason.")

        counts = (self.total_count, self.imported_count, self.filtered_count, self.rejected_count)
        present = tuple(value is not None for value in counts)
        if any(present) and not all(present):
            raise ValueError("Import counts must be either all present or all None.")
        if all(present):
            if any(type(value) is not int or value < 0 for value in counts):
                raise ValueError("Import counts must be exact non-negative integers.")
            if self.total_count != self.imported_count + self.filtered_count + self.rejected_count:
                raise ValueError("Import counts are inconsistent.")
            if self.status is not SourceUpdateStatus.APPLIED:
                raise ValueError("Import counts are permitted only for applied results.")
        elif self.status is SourceUpdateStatus.APPLIED:
            raise ValueError("Applied results must include import counts.")

        accepted = self.accepted_state.source_for(self.source_date)
        matches = accepted is not None and accepted.source_name == self.source_name and accepted.sha256 == self.sha256
        if self.status is SourceUpdateStatus.APPLIED and not matches:
            raise ValueError("accepted_state does not contain the matching accepted source.")
        if self.status is SourceUpdateStatus.UNCHANGED and (accepted is None or accepted.sha256 != self.sha256):
            raise ValueError("accepted_state does not contain the matching accepted digest.")
        if self.reason is SourceUpdateReason.CONFLICTING_SOURCE:
            if accepted is None or accepted.sha256 == self.sha256:
                raise ValueError("A conflicting result requires a different accepted digest for the source date.")
        elif self.reason is SourceUpdateReason.STALE_SOURCE_DATE:
            if accepted is not None or self.accepted_state.latest_source_date is None or self.accepted_state.latest_source_date <= self.source_date:
                raise ValueError("A stale result requires a later accepted source date.")
        elif self.reason is SourceUpdateReason.INVALID_SOURCE and matches:
            raise ValueError("A rejected result cannot advance the matching source.")


Importer = Callable[[str | Path], PrismaImportResult]


def evaluate_prisma_source_update(
    source_path: str | Path,
    *,
    source_date: date,
    evaluated_at: datetime,
    prior_state: PrismaSourceState | None = None,
    importer: Importer = import_prisma_export,
) -> PrismaSourceUpdateResult:
    """Evaluate one local export without mutating files, storage, or global state."""
    source_date = _require_exact_date(source_date)
    evaluated_at = _require_aware(evaluated_at)
    state = PrismaSourceState() if prior_state is None else prior_state
    if not isinstance(state, PrismaSourceState):
        raise TypeError("prior_state must be PrismaSourceState or None.")
    if not callable(importer):
        raise TypeError("importer must be callable.")
    try:
        path = Path(source_path).resolve(strict=True)
    except (TypeError, ValueError, OSError) as exc:
        raise ValueError("source_path must identify an existing regular file.") from exc
    if not path.is_file():
        raise ValueError("source_path must identify an existing regular file.")
    source_name = path.name
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ValueError("source_path must identify a readable regular file.") from exc

    def result(status: SourceUpdateStatus, reason: SourceUpdateReason, **counts: int) -> PrismaSourceUpdateResult:
        return PrismaSourceUpdateResult(
            source_date, source_name, digest, evaluated_at, status, reason,
            _MESSAGES[reason], state, **counts,
        )

    if source_date > evaluated_at.date():
        return result(SourceUpdateStatus.REJECTED, SourceUpdateReason.FUTURE_SOURCE_DATE)
    accepted = state.source_for(source_date)
    if accepted is not None:
        if accepted.sha256 == digest:
            return result(SourceUpdateStatus.UNCHANGED, SourceUpdateReason.IDENTICAL_SOURCE)
        return result(SourceUpdateStatus.REJECTED, SourceUpdateReason.CONFLICTING_SOURCE)
    if state.latest_source_date is not None and source_date < state.latest_source_date:
        return result(SourceUpdateStatus.REJECTED, SourceUpdateReason.STALE_SOURCE_DATE)

    try:
        imported = importer(path)
        counts = {
            "total_count": imported.total_source_rows,
            "imported_count": imported.imported_count,
            "filtered_count": imported.filtered_count,
            "rejected_count": imported.rejected_count,
        }
        if any(type(value) is not int or value < 0 for value in counts.values()):
            raise ValueError("Invalid import counts")
        if imported.total_source_rows != (
            imported.imported_count + imported.filtered_count + imported.rejected_count
        ):
            raise ValueError("Inconsistent import counts")
        verified_digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if verified_digest != digest:
            raise ValueError("Source changed during validation")
    except Exception:
        return result(SourceUpdateStatus.REJECTED, SourceUpdateReason.INVALID_SOURCE)

    digest = verified_digest
    accepted_source = AcceptedPrismaSource(source_date, source_name, digest)
    new_state = PrismaSourceState(state.accepted_sources + (accepted_source,))
    return PrismaSourceUpdateResult(
        source_date, source_name, digest, evaluated_at, SourceUpdateStatus.APPLIED,
        SourceUpdateReason.APPLIED, _MESSAGES[SourceUpdateReason.APPLIED], new_state, **counts,
    )


def is_daily_source_update_due(
    source_date: date,
    *,
    evaluated_at: datetime,
    scheduled_local_time: time,
    accepted_state: PrismaSourceState | None = None,
) -> bool:
    """Return whether a dated source is due in ``evaluated_at``'s local timezone."""
    source_date = _require_exact_date(source_date)
    evaluated_at = _require_aware(evaluated_at)
    if not isinstance(scheduled_local_time, time) or scheduled_local_time.tzinfo is not None:
        raise ValueError("scheduled_local_time must be a timezone-naive datetime.time.")
    state = PrismaSourceState() if accepted_state is None else accepted_state
    if not isinstance(state, PrismaSourceState):
        raise TypeError("accepted_state must be PrismaSourceState or None.")
    if state.source_for(source_date) is not None:
        return False
    if state.latest_source_date is not None and state.latest_source_date > source_date:
        return False
    local_scheduled_at = datetime.combine(source_date, scheduled_local_time, evaluated_at.tzinfo)
    return evaluated_at >= local_scheduled_at
