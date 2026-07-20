from __future__ import annotations

import csv
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


MONITORING_CSV_COLUMNS = (
    "auction_id",
    "auction_url",
    "lot_number",
    "item_name",
    "expected_status",
    "last_known_status",
    "check_interval_seconds",
    "enabled",
)

PRISMA_EXPORT_COLUMNS = (
    "Auction ID",
    "Start of Auction",
    "Network Point Name Exit",
    "Network Point EIC Exit",
    "Network Point Type Exit",
    "Network Point ID Exit",
    "Network Point Name Entry",
    "Network Point EIC Entry",
    "Network Point Type Entry",
    "Network Point ID Entry",
    "Network Point Name Exit/Entry",
    "Network Point EIC Exit/Entry",
    "Network Point ID Exit/Entry",
    "Published capacity",
    "Published capacity unit",
    "Marketable Capacity",
    "Unit Marketable Capacity",
    "Marketed Capacity",
    "Unit Marketed Capacity",
    "Regulated Tariff Exit TSO",
    "Unit Regulated Exit Capacity Tariff",
    "Regulated Tariff Entry TSO",
    "Unit Regulated Entry Capacity Tariff",
    "Surcharge",
    "Unit Surcharge",
    "Product Runtime Start",
    "Product Runtime End",
    "Capacity Category",
    "TSO Exit",
    "TSO EIC Exit",
    "TSO Entry",
    "TSO EIC Entry",
    "Direction",
    "Type of Gas",
    "State",
)


class CsvFormat(str, Enum):
    MONITORING = "monitoring"
    PRISMA_EXPORT = "prisma_export"
    UNSUPPORTED = "unsupported"
    AMBIGUOUS = "ambiguous"


class CsvFormatError(ValueError):
    """Raised when a CSV cannot be routed to exactly one supported contract."""


@dataclass(frozen=True)
class CsvDetectionResult:
    format: CsvFormat
    message: str | None = None


def _header(line: bytes, *, encoding: str, delimiter: str) -> list[str] | None:
    try:
        text = line.decode(encoding)
        return next(csv.reader([text], delimiter=delimiter, strict=True))
    except (UnicodeDecodeError, csv.Error, StopIteration):
        return None


def _duplicate(header: list[str] | None) -> str | None:
    if header is None:
        return None
    seen: set[str] = set()
    for column in header:
        if column in seen:
            return column
        seen.add(column)
    return None


def detect_csv_format(path: str | Path) -> CsvDetectionResult:
    """Detect a supported CSV contract by reading only its first physical line."""
    csv_path = Path(path)
    try:
        with csv_path.open("rb") as csv_file:
            line = csv_file.readline()
    except OSError:
        return CsvDetectionResult(CsvFormat.UNSUPPORTED, "CSV file is not readable.")

    if not line:
        return CsvDetectionResult(CsvFormat.UNSUPPORTED, "CSV file is empty.")

    monitoring = _header(line, encoding="utf-8", delimiter=",")
    prisma = _header(line, encoding="cp1252", delimiter=";")
    matches_monitoring = tuple(monitoring or ()) == MONITORING_CSV_COLUMNS
    matches_prisma = tuple(prisma or ()) == PRISMA_EXPORT_COLUMNS

    if matches_monitoring and matches_prisma:
        return CsvDetectionResult(
            CsvFormat.AMBIGUOUS,
            "CSV header matches both the Monitoring CSV and PRISMA Export CSV contracts.",
        )
    if matches_monitoring:
        return CsvDetectionResult(CsvFormat.MONITORING)
    if matches_prisma:
        return CsvDetectionResult(CsvFormat.PRISMA_EXPORT)

    for header in (monitoring, prisma):
        duplicate = _duplicate(header)
        if duplicate is not None:
            return CsvDetectionResult(
                CsvFormat.UNSUPPORTED, f"CSV header contains duplicate column: {duplicate}."
            )

    monitoring_set = set(MONITORING_CSV_COLUMNS)
    prisma_set = set(PRISMA_EXPORT_COLUMNS)
    if monitoring and set(monitoring) < monitoring_set:
        missing = [column for column in MONITORING_CSV_COLUMNS if column not in monitoring]
        return CsvDetectionResult(
            CsvFormat.UNSUPPORTED,
            f"Monitoring CSV header is incomplete; missing columns: {', '.join(missing)}.",
        )
    if prisma and set(prisma) < prisma_set:
        missing = [column for column in PRISMA_EXPORT_COLUMNS if column not in prisma]
        return CsvDetectionResult(
            CsvFormat.UNSUPPORTED,
            f"PRISMA Export CSV header is incomplete; missing columns: {', '.join(missing)}.",
        )

    return CsvDetectionResult(
        CsvFormat.UNSUPPORTED,
        "Unsupported CSV format. Expected a UTF-8 comma-delimited Monitoring CSV or "
        "a cp1252 semicolon-delimited PRISMA Export CSV.",
    )


def require_csv_format(path: str | Path, expected: CsvFormat) -> None:
    result = detect_csv_format(path)
    if result.format is expected:
        return
    if result.format is CsvFormat.AMBIGUOUS:
        raise CsvFormatError(result.message or "CSV format is ambiguous.")
    if result.format in {CsvFormat.MONITORING, CsvFormat.PRISMA_EXPORT}:
        raise CsvFormatError(
            f"Expected {expected.value}, but detected {result.format.value}."
        )
    raise CsvFormatError(result.message or "Unsupported CSV format.")
