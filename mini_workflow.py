"""Integrated, row-accounted Prisma Function Mini transformation workflow."""

from __future__ import annotations

import csv
import os
import re
import shutil
import threading
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from mini_browser import MiniBrowserCancelledError, MiniPrismaSession
from mini_csv import MiniCsvPublisher
from mini_domain import (
    CapacityType,
    MIN_BOOKED_CAPACITY_KWH_H,
    MiniDateRange,
    MiniOutputRow,
    NormalizedAuctionRecord,
    ProductType,
    SourceImportRequest,
    ValidationFailure,
    ValidationReason,
    normalize_capacity,
    normalize_tariff,
)
from mini_download import MiniDownloadCancelledError, MiniDownloadedSource
from mini_storage import MiniAuctionStorage, StorageResult
from mini_ui import MiniUiState, MiniWorkCancelled, MiniWorkRequest
from runtime_paths import RuntimePaths


INPUT_COLUMNS = (
    "Auction ID", "Start of Auction",
    "Network Point Name Exit", "Network Point EIC Exit", "Network Point Type Exit",
    "Network Point ID Exit", "Network Point Name Entry", "Network Point EIC Entry",
    "Network Point Type Entry", "Network Point ID Entry",
    "Network Point Name Exit/Entry", "Network Point EIC Exit/Entry",
    "Network Point ID Exit/Entry", "Published capacity", "Published capacity unit",
    "Marketable Capacity", "Unit Marketable Capacity", "Marketed Capacity",
    "Unit Marketed Capacity", "Regulated Tariff Exit TSO",
    "Unit Regulated Exit Capacity Tariff", "Regulated Tariff Entry TSO",
    "Unit Regulated Entry Capacity Tariff", "Surcharge", "Unit Surcharge",
    "Product Runtime Start", "Product Runtime End", "Capacity Category", "TSO Exit",
    "TSO EIC Exit", "TSO Entry", "TSO EIC Entry", "Direction", "Type of Gas", "State",
)
PRISMA_TIMEZONE = ZoneInfo("Europe/Berlin")
MAPPINGS = {
    "Kulata (BG)/Sidirokastron (GR)": ("BG", "HTP"),
    "Kireevo (BG) / Zaychar (RS)": ("BG", "RS"),
    "Mosonmagyarovar (AT) / Mosonmagyaróvár (HU)": ("CEGH", "MGP"),
    "Arnoldstein Exit": ("CEGH", "PSV"),
    "Baumgarten WAG AT->SK": ("CEGH", "SK"),
    "Arnoldstein importazione (35718301)": (None, "PSV"),
    "VIP DK-THE (H646) (H646)": ("THE", None),
}


class MiniWorkflowError(RuntimeError):
    """A stable integrated-workflow failure."""


@dataclass(frozen=True)
class ParsedSource:
    records: tuple[NormalizedAuctionRecord, ...]
    failures: tuple[ValidationFailure, ...]
    filtered: int
    total: int


@dataclass(frozen=True)
class MiniWorkflowResult:
    storage: StorageResult
    total: int
    inserted: int
    duplicates: int
    filtered: int
    rejected: int
    result_path: Path


@dataclass(frozen=True)
class MiniRecoveryResult:
    removed_publication_artifacts: int
    removed_download_operations: int
    reconciled_output: bool


class _Rejected(ValueError):
    def __init__(self, reason: ValidationReason, message: str, field: str | None = None):
        super().__init__(message)
        self.reason = reason
        self.field = field


def _parse_local(value: str, field: str) -> datetime:
    try:
        parsed = datetime.strptime(value, "%d.%m.%Y %H:%M")
    except (TypeError, ValueError) as exc:
        raise _Rejected(ValidationReason.INVALID_VALUE, f"{field} is invalid.", field) from exc
    aware0 = parsed.replace(tzinfo=PRISMA_TIMEZONE, fold=0)
    aware1 = parsed.replace(tzinfo=PRISMA_TIMEZONE, fold=1)
    if aware0.utcoffset() != aware1.utcoffset():
        raise _Rejected(ValidationReason.INVALID_VALUE, f"{field} is ambiguous.", field)
    round_trip = aware0.astimezone(timezone.utc).astimezone(PRISMA_TIMEZONE).replace(tzinfo=None)
    if round_trip != parsed:
        raise _Rejected(ValidationReason.INVALID_VALUE, f"{field} does not exist.", field)
    return parsed


def _next_month(value: datetime, months: int) -> datetime:
    index = value.year * 12 + value.month - 1 + months
    return value.replace(year=index // 12, month=index % 12 + 1)


def classify_product(flow_start: datetime, flow_end: datetime) -> tuple[ProductType, Decimal]:
    """Classify exact gas-day/calendar delivery periods and calculate DST-aware hours."""

    start_aware = flow_start.replace(tzinfo=PRISMA_TIMEZONE)
    end_aware = flow_end.replace(tzinfo=PRISMA_TIMEZONE)
    seconds = (
        end_aware.astimezone(timezone.utc) - start_aware.astimezone(timezone.utc)
    ).total_seconds()
    if seconds <= 0:
        raise _Rejected(ValidationReason.PRODUCT_TYPE_UNRESOLVED, "Delivery period is invalid.")
    duration = (Decimal(str(seconds)) / Decimal("3600")).normalize()
    boundary = time(6, 0)
    if flow_start.time() == boundary and flow_end.time() == boundary:
        if flow_end.date() == flow_start.date() + timedelta(days=1):
            return ProductType.DAY_AHEAD, duration
        if flow_start.day == 1 and flow_end == _next_month(flow_start, 1):
            return ProductType.MONTH, duration
        if (
            flow_start.day == 1
            and flow_start.month in (1, 4, 7, 10)
            and flow_end == _next_month(flow_start, 3)
        ):
            return ProductType.QUARTER, duration
        if (
            flow_start.month == 10 and flow_start.day == 1
            and flow_end == flow_start.replace(year=flow_start.year + 1)
        ):
            return ProductType.YEAR, duration
    gas_day_start = datetime.combine(flow_start.date(), boundary)
    if flow_start < gas_day_start:
        gas_day_start -= timedelta(days=1)
    if gas_day_start < flow_start and flow_end == gas_day_start + timedelta(days=1):
        return ProductType.WITHIN_DAY, duration
    raise _Rejected(
        ValidationReason.PRODUCT_TYPE_UNRESOLVED,
        "Delivery period does not match an approved product boundary.",
        "Product Runtime Start",
    )


def _required(row: dict[str, str], field: str) -> str:
    value = row.get(field, "").strip()
    if not value:
        reason = (
            ValidationReason.MISSING_IDENTITY
            if field in {"Auction ID", "Network Point ID Entry", "Network Point ID Exit",
                         "Network Point ID Exit/Entry"}
            else ValidationReason.INVALID_VALUE
        )
        raise _Rejected(reason, f"{field} is required.", field)
    return value


def _row(
    row: dict[str, str], requested_range: MiniDateRange | None = None
) -> NormalizedAuctionRecord | None:
    direction = _required(row, "Direction")
    sides = {
        "Exit": (CapacityType.EXIT, "Exit"),
        "Entry": (CapacityType.ENTRY, "Entry"),
        "Exit/Entry": (CapacityType.BUNDLE, "Exit/Entry"),
    }
    if direction not in sides:
        raise _Rejected(ValidationReason.INVALID_VALUE, "Direction is unsupported.", "Direction")
    capacity_type, suffix = sides[direction]
    auction_id = _required(row, "Auction ID")
    point_id = _required(row, f"Network Point ID {suffix}")
    point_name = _required(row, f"Network Point Name {suffix}")
    auction_at = _parse_local(_required(row, "Start of Auction"), "Start of Auction")
    if requested_range is not None and not (
        requested_range.start <= auction_at.date() <= requested_range.end
    ):
        raise _Rejected(
            ValidationReason.INVALID_VALUE,
            "Start of Auction is outside the requested date range.",
            "Start of Auction",
        )
    start = _parse_local(_required(row, "Product Runtime Start"), "Product Runtime Start")
    end = _parse_local(_required(row, "Product Runtime End"), "Product Runtime End")
    product, duration = classify_product(start, end)
    try:
        capacity = normalize_capacity(
            _required(row, "Marketed Capacity"), _required(row, "Unit Marketed Capacity")
        )
    except ValueError as exc:
        reason = ValidationReason.UNSUPPORTED_UNIT if "Unsupported" in str(exc) else ValidationReason.INVALID_VALUE
        raise _Rejected(reason, str(exc), "Unit Marketed Capacity") from exc
    if capacity < MIN_BOOKED_CAPACITY_KWH_H:
        return None
    if capacity_type is CapacityType.BUNDLE:
        raise _Rejected(
            ValidationReason.MISSING_REQUIRED_TARIFF,
            "Bundled rows have no approved single side-specific tariff.",
        )
    tariff_prefix = "Exit" if capacity_type is CapacityType.EXIT else "Entry"
    tariff_field = f"Regulated Tariff {tariff_prefix} TSO"
    unit_field = f"Unit Regulated {tariff_prefix} Capacity Tariff"
    try:
        tariff = normalize_tariff(_required(row, tariff_field), _required(row, unit_field), duration)
    except ValueError as exc:
        reason = ValidationReason.UNSUPPORTED_UNIT if "Unsupported" in str(exc) else ValidationReason.MISSING_REQUIRED_TARIFF
        raise _Rejected(reason, str(exc), tariff_field) from exc
    premium_text = row.get("Surcharge", "").strip()
    if premium_text:
        try:
            premium = normalize_tariff(
                premium_text, _required(row, "Unit Surcharge"), duration
            )
        except ValueError as exc:
            reason = ValidationReason.UNSUPPORTED_UNIT if "Unsupported" in str(exc) else ValidationReason.INVALID_VALUE
            raise _Rejected(reason, str(exc), "Surcharge") from exc
    else:
        premium = None
    exit_market, entry_market = MAPPINGS.get(point_name, (None, None))
    return NormalizedAuctionRecord(
        auction_id=auction_id,
        network_point_id=point_id,
        auction_date=auction_at.date(),
        exit_market_or_storage=exit_market,
        entry_market_or_storage=entry_market,
        capacity_type=capacity_type,
        network_point=point_name,
        product_type=product,
        flow_start=start,
        flow_end=end,
        booked_capacity_kwh_h=capacity,
        duration_hours=duration,
        auction_tariff_eur_mwh_h=tariff,
        auction_premium_eur_mwh_h=premium,
    )


def parse_source(
    path: Path,
    cancel_event: threading.Event,
    requested_range: MiniDateRange | None = None,
) -> ParsedSource:
    records: list[NormalizedAuctionRecord] = []
    failures: list[ValidationFailure] = []
    filtered = 0
    try:
        with path.open("r", encoding="cp1252", newline="") as handle:
            reader = csv.reader(handle, delimiter=";")
            header = next(reader, None)
            if tuple(header or ()) != INPUT_COLUMNS:
                raise MiniWorkflowError("The PRISMA CSV header contract is invalid.")
            for row_number, values in enumerate(reader, 2):
                if cancel_event.is_set():
                    raise MiniWorkCancelled
                if len(values) != len(INPUT_COLUMNS):
                    failures.append(ValidationFailure(
                        ValidationReason.INVALID_SOURCE_ROW,
                        "The source row width is invalid.", row_number,
                    ))
                    continue
                try:
                    record = _row(
                        dict(zip(INPUT_COLUMNS, values, strict=True)), requested_range
                    )
                    if record is None:
                        filtered += 1
                    else:
                        records.append(record)
                except _Rejected as exc:
                    failures.append(ValidationFailure(exc.reason, str(exc), row_number, exc.field))
    except MiniWorkCancelled:
        raise
    except MiniWorkflowError:
        raise
    except (OSError, UnicodeError, csv.Error) as exc:
        raise MiniWorkflowError("The PRISMA CSV could not be validated.") from exc
    return ParsedSource(tuple(records), tuple(failures), filtered, len(records) + filtered + len(failures))


class MiniIntegratedWorkflow:
    _DOWNLOAD_OPERATION = re.compile(r"^[0-9a-f]{32}$")
    _PUBLICATION_ARTIFACT = re.compile(
        r"^\.prisma_function_mini-(?:restore-)?[^\\/]+\.csv$"
    )

    def __init__(
        self,
        paths: RuntimePaths,
        *,
        session: MiniPrismaSession | None = None,
        storage: MiniAuctionStorage | None = None,
        publisher: MiniCsvPublisher | None = None,
    ) -> None:
        self.paths = paths
        self.session = session or MiniPrismaSession()
        self.storage = storage or MiniAuctionStorage(paths=paths)
        self.publisher = publisher or MiniCsvPublisher(self.storage)

    def recover(self) -> MiniRecoveryResult:
        """Remove abandoned owned artifacts and reconcile CSV from SQLite history."""

        removed_publication = 0
        result_parent = self.publisher.output_path.parent
        if result_parent.exists():
            for artifact in result_parent.iterdir():
                if (
                    artifact.is_file()
                    and self._PUBLICATION_ARTIFACT.fullmatch(artifact.name)
                ):
                    try:
                        artifact.unlink()
                    except OSError as exc:
                        raise MiniWorkflowError(
                            "An abandoned publication artifact could not be cleaned up."
                        ) from exc
                    removed_publication += 1

        removed_downloads = 0
        temporary_root = self.paths.temporary_downloads
        if temporary_root.exists():
            for operation in temporary_root.iterdir():
                if (
                    operation.is_dir()
                    and self._DOWNLOAD_OPERATION.fullmatch(operation.name)
                ):
                    try:
                        shutil.rmtree(operation)
                    except OSError as exc:
                        raise MiniWorkflowError(
                            "An abandoned download operation could not be cleaned up."
                        ) from exc
                    removed_downloads += 1

        history = self.storage.history()
        expected = MiniCsvPublisher._content(
            MiniOutputRow.from_record(item.auction).values() for item in history
        )
        current: bytes | None
        try:
            current = (
                self.publisher.output_path.read_bytes()
                if self.publisher.output_path.exists()
                else None
            )
        except OSError as exc:
            raise MiniWorkflowError(
                "The cumulative CSV could not be inspected during recovery."
            ) from exc
        reconciled = current is not None and current != expected
        if history and current != expected:
            self.publisher.publish()
            reconciled = True
        return MiniRecoveryResult(
            removed_publication, removed_downloads, reconciled
        )

    def run(
        self,
        request: MiniWorkRequest,
        cancel_event: threading.Event,
        progress: Callable[[MiniUiState, str], None],
    ) -> Path:
        source: MiniDownloadedSource | None = None

        def cleanup_download(downloaded: MiniDownloadedSource) -> None:
            operation = downloaded.path.parent.resolve()
            owned_root = self.paths.temporary_downloads.resolve()
            if operation.parent != owned_root:
                raise MiniWorkflowError("The downloaded source is outside the operation directory.")
            try:
                shutil.rmtree(operation)
            except OSError as exc:
                raise MiniWorkflowError("The operation download could not be cleaned up.") from exc

        try:
            if cancel_event.is_set():
                raise MiniWorkCancelled
            self.recover()
            if cancel_event.is_set():
                raise MiniWorkCancelled
            progress(MiniUiState.DOWNLOADING, "Applying date filter and downloading CSV...")
            source = self.session.download_csv(cancel_event, request.date_range)
            if source.request.requested_range != request.date_range:
                raise MiniWorkflowError("The downloaded source range does not match the request.")
            if cancel_event.is_set():
                raise MiniWorkCancelled
            progress(MiniUiState.PROCESSING, "Validating and transforming auctions...")
            parsed = parse_source(source.path, cancel_event, request.date_range)
            import_request = source.request
            cleanup_download(source)
            source = None
            if cancel_event.is_set():
                raise MiniWorkCancelled
            progress(MiniUiState.PUBLISHING, "Saving history and publishing cumulative CSV...")
            if cancel_event.is_set():
                raise MiniWorkCancelled
            previous = (
                self.publisher.output_path.read_bytes()
                if self.publisher.output_path.exists() else None
            )
            try:
                self.storage.store_and_publish(
                    import_request,
                    parsed.records,
                    validation_failures=parsed.failures,
                    filtered=parsed.filtered,
                    source_rows=parsed.total,
                    publish=self.publisher.publish_records,
                )
            except BaseException:
                self._restore_previous_result(previous)
                raise
            return self.publisher.output_path
        except (MiniBrowserCancelledError, MiniDownloadCancelledError) as exc:
            raise MiniWorkCancelled from exc
        finally:
            if source is not None and source.path.parent.exists():
                cleanup_download(source)

    def _restore_previous_result(self, previous: bytes | None) -> None:
        output = self.publisher.output_path
        try:
            if previous is None:
                output.unlink(missing_ok=True)
                return
            output.parent.mkdir(parents=True, exist_ok=True)
            descriptor, name = tempfile.mkstemp(
                prefix=f".{output.stem}-restore-", suffix=".csv", dir=output.parent
            )
            staged = Path(name)
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(previous)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(staged, output)
            finally:
                staged.unlink(missing_ok=True)
        except OSError as exc:
            raise MiniWorkflowError(
                "The previous cumulative CSV could not be restored after failure."
            ) from exc
