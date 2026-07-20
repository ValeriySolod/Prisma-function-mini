from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from csv_contracts import MONITORING_CSV_COLUMNS


CSV_COLUMNS = MONITORING_CSV_COLUMNS

ALLOWED_STATUSES = frozenset(
    {"Scheduled", "Open", "In Progress", "Completed", "Cancelled", "Unknown", "Error"}
)


class CsvValidationError(ValueError):
    """Raised when an auction CSV cannot be read or does not satisfy its contract."""


@dataclass(frozen=True)
class AuctionCsvRecord:
    auction_id: str
    auction_url: str
    lot_number: str
    item_name: str
    expected_status: str
    last_known_status: str
    check_interval_seconds: int
    enabled: bool


def _validate_header(header: list[str]) -> None:
    if len(header) != len(set(header)):
        duplicate = next(column for column in header if header.count(column) > 1)
        raise CsvValidationError(f"Duplicate column: {duplicate}.")

    for column in CSV_COLUMNS:
        if column not in header:
            raise CsvValidationError(f"Missing required column: {column}.")
    for column in header:
        if column not in CSV_COLUMNS:
            raise CsvValidationError(f"Unexpected column: {column}.")
    if tuple(header) != CSV_COLUMNS:
        raise CsvValidationError("CSV columns are in an invalid order.")


def _valid_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.hostname)
    except ValueError:
        return False


def _parse_row(row: list[str], row_number: int) -> AuctionCsvRecord:
    if len(row) != len(CSV_COLUMNS):
        raise CsvValidationError(f"Malformed CSV data in row {row_number}.")

    values = dict(zip(CSV_COLUMNS, (value.strip() for value in row), strict=True))
    for field, value in values.items():
        if not value:
            raise CsvValidationError(f"Required field {field} is empty in row {row_number}.")

    if not _valid_url(values["auction_url"]):
        raise CsvValidationError(f"Invalid URL in row {row_number}.")

    interval_text = values["check_interval_seconds"]
    if not interval_text.isdecimal():
        raise CsvValidationError(f"Invalid check_interval_seconds in row {row_number}.")
    interval = int(interval_text)
    if interval <= 0:
        raise CsvValidationError(f"Invalid check_interval_seconds in row {row_number}.")

    enabled_text = values["enabled"]
    if enabled_text not in {"true", "false"}:
        raise CsvValidationError(f"Invalid enabled value in row {row_number}.")

    for field in ("expected_status", "last_known_status"):
        if values[field] not in ALLOWED_STATUSES:
            raise CsvValidationError(f"Invalid {field} in row {row_number}.")

    return AuctionCsvRecord(
        auction_id=values["auction_id"],
        auction_url=values["auction_url"],
        lot_number=values["lot_number"],
        item_name=values["item_name"],
        expected_status=values["expected_status"],
        last_known_status=values["last_known_status"],
        check_interval_seconds=interval,
        enabled=enabled_text == "true",
    )


def load_auction_csv(path: str | Path) -> list[AuctionCsvRecord]:
    """Read and validate an auction CSV, returning typed records atomically."""
    csv_path = Path(path)
    if csv_path.suffix.lower() != ".csv":
        raise CsvValidationError("Selected file must have a .csv extension.")
    if not csv_path.is_file():
        raise CsvValidationError("CSV file does not exist.")

    try:
        with csv_path.open("r", encoding="utf-8", newline="") as csv_file:
            if csv_file.read(1) == "":
                raise CsvValidationError("CSV file is empty.")
            csv_file.seek(0)
            reader = csv.reader(csv_file, strict=True)
            try:
                header = next(reader)
            except StopIteration:
                raise CsvValidationError("CSV header is missing.") from None
            if not header or all(not value.strip() for value in header):
                raise CsvValidationError("CSV header is missing.")
            _validate_header(header)

            records: list[AuctionCsvRecord] = []
            seen_ids: set[str] = set()
            for row in reader:
                row_number = reader.line_num
                record = _parse_row(row, row_number)
                if record.auction_id in seen_ids:
                    raise CsvValidationError(
                        f"Duplicate auction_id in row {row_number}: {record.auction_id}."
                    )
                seen_ids.add(record.auction_id)
                records.append(record)
    except UnicodeDecodeError:
        raise CsvValidationError("CSV file is not valid UTF-8.") from None
    except csv.Error as error:
        row_number = reader.line_num if "reader" in locals() else 1
        raise CsvValidationError(f"Malformed CSV data in row {row_number}.") from None
    except OSError:
        raise CsvValidationError("CSV file is not readable.") from None

    if not records:
        raise CsvValidationError("CSV contains no data rows.")
    return records
