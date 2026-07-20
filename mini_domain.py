"""Immutable, persistence-independent contracts for Prisma Function Mini.

The values in this module are the boundary between a validated PRISMA export
and the later storage/workbook increments.  No browser, Qt, SQLite, or Excel
behavior belongs here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from pathlib import Path
from typing import Iterable


WORKSHEET_NAME = "Auctions"
OUTPUT_COLUMNS = (
    "Auction Date",
    "Exit Market / Storage",
    "Entry Market / Storage",
    "Capacity Type",
    "Network Point",
    "Product Type",
    "Flow Start",
    "Flow End",
    "Booked Capacity (kWh/h)",
    "Duration (hours)",
    "Auction Tariff (EUR/MWh/h)",
)
MIN_BOOKED_CAPACITY_KWH_H = Decimal("1000")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class CapacityType(str, Enum):
    ENTRY = "Entry"
    EXIT = "Exit"
    BUNDLE = "Bundle"


class ProductType(str, Enum):
    WITHIN_DAY = "WD"
    DAY_AHEAD = "Day Ahead"
    MONTH = "Month"
    QUARTER = "Quarter"
    YEAR = "Year"


class ProcessingStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"


class ValidationReason(str, Enum):
    INVALID_SOURCE = "invalid_source"
    INVALID_SOURCE_ROW = "invalid_source_row"
    MISSING_IDENTITY = "missing_identity"
    UNSUPPORTED_UNIT = "unsupported_unit"
    INVALID_VALUE = "invalid_value"
    UNKNOWN_REFERENCE = "unknown_reference"
    CONFLICTING_DUPLICATE = "conflicting_duplicate"


def _exact_date(value: object, field: str) -> date:
    if type(value) is not date:
        raise TypeError(f"{field} must be exactly datetime.date.")
    return value


def _text(value: object, field: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if type(value) is not str:
        raise TypeError(f"{field} must be a string.")
    normalized = " ".join(value.split())
    if not normalized:
        if optional:
            return None
        raise ValueError(f"{field} must not be blank.")
    return normalized


def _decimal(value: object, field: str, *, minimum: Decimal = Decimal("0")) -> Decimal:
    if isinstance(value, bool):
        raise TypeError(f"{field} must be a decimal-compatible number.")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{field} must be a decimal-compatible number.") from exc
    if not result.is_finite() or result < minimum:
        raise ValueError(f"{field} must be finite and at least {minimum}.")
    return result.normalize()


def _local_minute(value: object, field: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field} must be datetime.datetime.")
    if value.tzinfo is not None or value.utcoffset() is not None:
        raise ValueError(f"{field} must be timezone-naive PRISMA local time.")
    if value.second or value.microsecond:
        raise ValueError(f"{field} must have minute precision.")
    return value


def _utc(value: object, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be a timezone-aware datetime.")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class MiniDateRange:
    """Inclusive PRISMA calendar dates selected by the user."""

    start: date
    end: date

    def __post_init__(self) -> None:
        object.__setattr__(self, "start", _exact_date(self.start, "start"))
        object.__setattr__(self, "end", _exact_date(self.end, "end"))
        if self.end < self.start:
            raise ValueError("end must be on or after start.")


@dataclass(frozen=True)
class SourceImportRequest:
    requested_range: MiniDateRange
    source_name: str
    sha256: str
    size_bytes: int

    def __post_init__(self) -> None:
        if not isinstance(self.requested_range, MiniDateRange):
            raise TypeError("requested_range must be MiniDateRange.")
        name = _text(self.source_name, "source_name")
        if Path(name).name != name:
            raise ValueError("source_name must be a basename.")
        object.__setattr__(self, "source_name", name)
        if type(self.sha256) is not str or not _SHA256.fullmatch(self.sha256):
            raise ValueError("sha256 must be a lowercase hexadecimal SHA-256 digest.")
        if type(self.size_bytes) is not int or self.size_bytes <= 0:
            raise ValueError("size_bytes must be a positive integer.")


@dataclass(frozen=True, order=True)
class AuctionDuplicateKey:
    """Stable identity used by both application checks and future DB uniqueness."""

    auction_id: str
    network_point_id: str
    capacity_type: CapacityType
    flow_start: datetime
    flow_end: datetime


@dataclass(frozen=True)
class NormalizedAuctionRecord:
    auction_id: str
    network_point_id: str
    auction_date: date
    exit_market_or_storage: str | None
    entry_market_or_storage: str | None
    capacity_type: CapacityType
    network_point: str
    product_type: ProductType
    flow_start: datetime
    flow_end: datetime
    booked_capacity_kwh_h: Decimal
    duration_hours: Decimal
    auction_tariff_eur_mwh_h: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "auction_id", _text(self.auction_id, "auction_id"))
        object.__setattr__(self, "network_point_id", _text(self.network_point_id, "network_point_id"))
        object.__setattr__(self, "auction_date", _exact_date(self.auction_date, "auction_date"))
        object.__setattr__(self, "network_point", _text(self.network_point, "network_point"))
        if type(self.capacity_type) is not CapacityType:
            raise TypeError("capacity_type must be CapacityType.")
        if type(self.product_type) is not ProductType:
            raise TypeError("product_type must be ProductType.")
        exit_value = _text(self.exit_market_or_storage, "exit_market_or_storage", optional=True)
        entry_value = _text(self.entry_market_or_storage, "entry_market_or_storage", optional=True)
        object.__setattr__(self, "exit_market_or_storage", exit_value)
        object.__setattr__(self, "entry_market_or_storage", entry_value)
        required = {
            CapacityType.ENTRY: (entry_value,),
            CapacityType.EXIT: (exit_value,),
            CapacityType.BUNDLE: (exit_value, entry_value),
        }[self.capacity_type]
        if any(value is None for value in required):
            raise ValueError("Capacity type requires its authoritative Market / Storage side value.")
        start = _local_minute(self.flow_start, "flow_start")
        end = _local_minute(self.flow_end, "flow_end")
        if end <= start:
            raise ValueError("flow_end must be later than flow_start.")
        if self.auction_date > start.date():
            raise ValueError("auction_date must not be after the flow start date.")
        object.__setattr__(self, "flow_start", start)
        object.__setattr__(self, "flow_end", end)
        capacity = _decimal(self.booked_capacity_kwh_h, "booked_capacity_kwh_h", minimum=MIN_BOOKED_CAPACITY_KWH_H)
        tariff = _decimal(self.auction_tariff_eur_mwh_h, "auction_tariff_eur_mwh_h")
        duration = Decimal(str((end - start).total_seconds())) / Decimal("3600")
        supplied_duration = _decimal(self.duration_hours, "duration_hours")
        if supplied_duration != duration.normalize():
            raise ValueError("duration_hours must equal the exact Flow Start/Flow End duration.")
        object.__setattr__(self, "booked_capacity_kwh_h", capacity)
        object.__setattr__(self, "duration_hours", duration.normalize())
        object.__setattr__(self, "auction_tariff_eur_mwh_h", tariff)

    @property
    def duplicate_key(self) -> AuctionDuplicateKey:
        return AuctionDuplicateKey(
            self.auction_id, self.network_point_id, self.capacity_type,
            self.flow_start, self.flow_end,
        )


@dataclass(frozen=True)
class MiniOutputRow:
    auction_date: date
    exit_market_or_storage: str | None
    entry_market_or_storage: str | None
    capacity_type: str
    network_point: str
    product_type: str
    flow_start: datetime
    flow_end: datetime
    booked_capacity_kwh_h: Decimal
    duration_hours: Decimal
    auction_tariff_eur_mwh_h: Decimal

    @classmethod
    def from_record(cls, record: NormalizedAuctionRecord) -> "MiniOutputRow":
        if not isinstance(record, NormalizedAuctionRecord):
            raise TypeError("record must be NormalizedAuctionRecord.")
        return cls(
            record.auction_date, record.exit_market_or_storage,
            record.entry_market_or_storage, record.capacity_type.value,
            record.network_point, record.product_type.value, record.flow_start,
            record.flow_end, record.booked_capacity_kwh_h, record.duration_hours,
            record.auction_tariff_eur_mwh_h,
        )

    def values(self) -> tuple[object, ...]:
        return tuple(getattr(self, field) for field in self.__dataclass_fields__)


@dataclass(frozen=True)
class HistoryRecord:
    auction: NormalizedAuctionRecord
    source_sha256: str
    accumulated_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.auction, NormalizedAuctionRecord):
            raise TypeError("auction must be NormalizedAuctionRecord.")
        if type(self.source_sha256) is not str or not _SHA256.fullmatch(self.source_sha256):
            raise ValueError("source_sha256 must be a lowercase hexadecimal SHA-256 digest.")
        object.__setattr__(self, "accumulated_at", _utc(self.accumulated_at, "accumulated_at"))

    @property
    def duplicate_key(self) -> AuctionDuplicateKey:
        return self.auction.duplicate_key


@dataclass(frozen=True)
class ValidationFailure:
    reason: ValidationReason
    message: str
    source_row_number: int | None = None
    field_name: str | None = None

    def __post_init__(self) -> None:
        if type(self.reason) is not ValidationReason:
            raise TypeError("reason must be ValidationReason.")
        object.__setattr__(self, "message", _text(self.message, "message"))
        if self.source_row_number is not None and (
            type(self.source_row_number) is not int or self.source_row_number < 2
        ):
            raise ValueError("source_row_number must be a physical CSV data-row number (2 or greater).")
        object.__setattr__(self, "field_name", _text(self.field_name, "field_name", optional=True))


@dataclass(frozen=True)
class ProcessingResult:
    status: ProcessingStatus
    processed: int
    inserted: int
    duplicates: int
    filtered: int
    rejected: int
    failures: tuple[ValidationFailure, ...] = ()

    def __post_init__(self) -> None:
        if type(self.status) is not ProcessingStatus:
            raise TypeError("status must be ProcessingStatus.")
        counts = (self.processed, self.inserted, self.duplicates, self.filtered, self.rejected)
        if any(type(value) is not int or value < 0 for value in counts):
            raise ValueError("Processing counts must be non-negative integers.")
        if self.processed != self.inserted + self.duplicates + self.filtered + self.rejected:
            raise ValueError("processed must equal inserted + duplicates + filtered + rejected.")
        if not isinstance(self.failures, tuple) or any(not isinstance(item, ValidationFailure) for item in self.failures):
            raise TypeError("failures must be a tuple of ValidationFailure values.")
        if self.status is ProcessingStatus.COMPLETED and len(self.failures) > self.rejected:
            raise ValueError("Completed results cannot have more failures than rejected rows.")
        if self.status is ProcessingStatus.FAILED and not self.failures:
            raise ValueError("Failed results must contain at least one validation failure.")


@dataclass(frozen=True)
class ImportResult:
    request: SourceImportRequest
    evaluated_at: datetime
    processing: ProcessingResult

    def __post_init__(self) -> None:
        if not isinstance(self.request, SourceImportRequest):
            raise TypeError("request must be SourceImportRequest.")
        if not isinstance(self.processing, ProcessingResult):
            raise TypeError("processing must be ProcessingResult.")
        object.__setattr__(self, "evaluated_at", _utc(self.evaluated_at, "evaluated_at"))


def classify_duplicates(
    historical: Iterable[NormalizedAuctionRecord],
    incoming: Iterable[NormalizedAuctionRecord],
) -> tuple[tuple[NormalizedAuctionRecord, ...], tuple[NormalizedAuctionRecord, ...]]:
    """Return new and identical rows; reject conflicting rows sharing a key."""

    known: dict[AuctionDuplicateKey, NormalizedAuctionRecord] = {}
    for record in historical:
        if not isinstance(record, NormalizedAuctionRecord):
            raise TypeError("historical must contain NormalizedAuctionRecord values.")
        previous = known.setdefault(record.duplicate_key, record)
        if previous != record:
            raise ValueError("Historical records contain a conflicting duplicate key.")
    new: list[NormalizedAuctionRecord] = []
    duplicates: list[NormalizedAuctionRecord] = []
    for record in incoming:
        if not isinstance(record, NormalizedAuctionRecord):
            raise TypeError("incoming must contain NormalizedAuctionRecord values.")
        previous = known.get(record.duplicate_key)
        if previous is None:
            known[record.duplicate_key] = record
            new.append(record)
        elif previous == record:
            duplicates.append(record)
        else:
            raise ValueError("Incoming record conflicts with an existing duplicate key.")
    return tuple(new), tuple(duplicates)


def normalize_capacity(value: object, unit: str) -> Decimal:
    factors = {"kWh/h": Decimal("1"), "MWh/h": Decimal("1000"), "kWh/d": Decimal("0.04166666666666666666666666667")}
    if unit not in factors:
        raise ValueError("Unsupported capacity unit.")
    return (_decimal(value, "capacity") * factors[unit]).normalize()


def normalize_tariff(value: object, unit: str) -> Decimal:
    factors = {"EUR/MWh/h": Decimal("1"), "cent/kWh/h/Runtime": Decimal("10"), "cent/kWh/d/Runtime": Decimal("0.4166666666666666666666666667")}
    if unit not in factors:
        raise ValueError("Unsupported tariff unit.")
    return (_decimal(value, "tariff") * factors[unit]).normalize()


def normalize_product(value: str) -> ProductType:
    aliases = {
        "WD": ProductType.WITHIN_DAY,
        "Within Day": ProductType.WITHIN_DAY,
        "Day Ahead": ProductType.DAY_AHEAD,
        "Month": ProductType.MONTH,
        "Quarter": ProductType.QUARTER,
        "Year": ProductType.YEAR,
    }
    try:
        return aliases[value.strip()]
    except (AttributeError, KeyError) as exc:
        raise ValueError("Unsupported product type.") from exc
