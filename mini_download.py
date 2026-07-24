"""Typed, application-owned boundary for one official PRISMA CSV download."""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import threading
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable

from csv_contracts import CsvFormat, CsvFormatError, require_csv_format
from mini_domain import MiniDateRange, SourceImportRequest


OFFICIAL_FILENAME = "Auction_overview.csv"
_LIMIT_WARNING = re.compile(
    r"(?<!\S)Your download contains only ([0-9]+) of ([0-9]+) items\.(?!\S)"
)
_LIMIT_WARNING_PREFIX = "Your download contains only"


class MiniDownloadFailureKind(str, Enum):
    CHANGED_DOM = "changed-dom"
    MISSING = "missing-download"
    TIMEOUT = "download-timeout"
    CANCELLED = "cancelled"
    PAGE_CLOSED = "page-closed"
    UNEXPECTED_FILENAME = "unexpected-filename"
    EMPTY = "empty-download"
    PARTIAL = "partial-download"
    WRONG_CONTRACT = "wrong-csv-contract"
    FILESYSTEM = "filesystem"
    LIMITED = "limited-download"
    CLEANUP = "cleanup"
    DUPLICATE_SUBMISSION = "duplicate-submission"


class MiniDownloadError(RuntimeError):
    kind: MiniDownloadFailureKind


class MiniDownloadChangedDomError(MiniDownloadError):
    kind = MiniDownloadFailureKind.CHANGED_DOM


class MiniDownloadMissingError(MiniDownloadError):
    kind = MiniDownloadFailureKind.MISSING


class MiniDownloadTimeoutError(MiniDownloadError):
    kind = MiniDownloadFailureKind.TIMEOUT


class MiniDownloadCancelledError(MiniDownloadError):
    kind = MiniDownloadFailureKind.CANCELLED


class MiniDownloadPageClosedError(MiniDownloadError):
    kind = MiniDownloadFailureKind.PAGE_CLOSED


class MiniDownloadUnexpectedFilenameError(MiniDownloadError):
    kind = MiniDownloadFailureKind.UNEXPECTED_FILENAME


class MiniDownloadEmptyError(MiniDownloadError):
    kind = MiniDownloadFailureKind.EMPTY


class MiniDownloadPartialError(MiniDownloadError):
    kind = MiniDownloadFailureKind.PARTIAL


class MiniDownloadContractError(MiniDownloadError):
    kind = MiniDownloadFailureKind.WRONG_CONTRACT


class MiniDownloadFilesystemError(MiniDownloadError):
    kind = MiniDownloadFailureKind.FILESYSTEM


class MiniDownloadLimitedError(MiniDownloadError):
    kind = MiniDownloadFailureKind.LIMITED

    def __init__(self, downloaded_count: int, total_count: int) -> None:
        super().__init__(
            f"PRISMA limited the export to {downloaded_count} of {total_count} items."
        )
        self.downloaded_count = downloaded_count
        self.total_count = total_count


class MiniDownloadCleanupError(MiniDownloadError):
    kind = MiniDownloadFailureKind.CLEANUP


class MiniDownloadDuplicateSubmissionError(MiniDownloadError):
    kind = MiniDownloadFailureKind.DUPLICATE_SUBMISSION


@dataclass(frozen=True)
class MiniDownloadedSource:
    """Accepted immutable source metadata for the later M.12 audit boundary."""

    path: Path
    request: SourceImportRequest
    downloaded_count: int | None = None
    total_count: int | None = None

    def __post_init__(self) -> None:
        path = Path(self.path)
        if not path.is_absolute():
            raise ValueError("path must be absolute.")
        object.__setattr__(self, "path", path)
        if not isinstance(self.request, SourceImportRequest):
            raise TypeError("request must be SourceImportRequest.")
        counts = (self.downloaded_count, self.total_count)
        if any(value is not None and (type(value) is not int or value < 0) for value in counts):
            raise ValueError("download counts must be non-negative integers.")
        if (self.downloaded_count is None) != (self.total_count is None):
            raise ValueError("download counts must either both be present or both be absent.")

    @property
    def requested_range(self) -> MiniDateRange:
        return self.request.requested_range


class MiniPrismaCsvDownloader:
    """Submits one export and accepts only a complete official PRISMA CSV."""

    DIALOG_SELECTOR = '[role="dialog"][data-dialog][data-open="true"]'
    MAIN_ACTION_SELECTOR = (
        'button:has(svg[data-icon="file-csv"])'
        ':not([role="dialog"][data-dialog][data-open="true"] *)'
    )
    CONFIRM_ACTION_SELECTOR = (
        '[role="dialog"][data-dialog][data-open="true"] '
        'button[data-sentry-component="MonolithDownload"]'
        ':has(svg[data-icon="file-csv"])'
    )

    def __init__(
        self,
        temporary_root: Path,
        *,
        timeout_ms: int = 20_000,
        poll_ms: int = 100,
        operation_id_factory: Callable[[], str] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if timeout_ms <= 0 or poll_ms <= 0:
            raise ValueError("Download timeouts must be positive.")
        self.temporary_root = Path(temporary_root).resolve()
        self.timeout_ms = timeout_ms
        self.poll_ms = poll_ms
        self._operation_id_factory = operation_id_factory or (lambda: uuid.uuid4().hex)
        self._clock = clock
        self._submission_lock = threading.Lock()
        self._submitted = False

    def download(
        self, page: object, requested_range: MiniDateRange, cancel_event: threading.Event
    ) -> MiniDownloadedSource:
        if not isinstance(requested_range, MiniDateRange):
            raise TypeError("requested_range must be MiniDateRange.")
        if not isinstance(cancel_event, threading.Event):
            raise TypeError("cancel_event must be a threading.Event.")
        self._check_cancelled(cancel_event)
        operation = self._create_operation_directory()
        captured: list[object] = []

        def on_download(download: object) -> None:
            if not captured:
                captured.append(download)

        listener_attached = False
        accepted = False
        try:
            try:
                page.on("download", on_download)
                listener_attached = True
            except Exception as exc:
                raise MiniDownloadChangedDomError(
                    "The PRISMA download event boundary is unavailable."
                ) from exc
            main = self._required_visible(
                page, self.MAIN_ACTION_SELECTOR, "main CSV action", cancel_event
            )
            self._submit_once(main, page, cancel_event)
            counts = self._await_download_or_dialog(page, captured, cancel_event)
            if counts is not None:
                confirmation = self._required_visible(
                    page, self.CONFIRM_ACTION_SELECTOR,
                    "limit-dialog CSV confirmation", cancel_event,
                )
                self._click(confirmation, page, "limit-dialog CSV confirmation")
                download = self._await_download(page, captured, cancel_event)
            else:
                download = captured[0]
            result = self._accept_download(
                download, operation, requested_range, counts, cancel_event
            )
            if counts is not None and counts[1] > counts[0]:
                raise MiniDownloadLimitedError(*counts)
            accepted = True
            return result
        finally:
            if not accepted and cancel_event.is_set() and captured:
                try:
                    captured[0].cancel()
                except Exception:
                    pass
            if listener_attached:
                try:
                    page.remove_listener("download", on_download)
                except Exception as exc:
                    if accepted:
                        self._cleanup(operation)
                        raise MiniDownloadCleanupError(
                            "PRISMA download listener cleanup failed."
                        ) from exc
            if not accepted:
                self._cleanup(operation)

    def _submit_once(self, locator, page, cancel_event) -> None:
        self._check_cancelled(cancel_event)
        with self._submission_lock:
            if self._submitted:
                raise MiniDownloadDuplicateSubmissionError(
                    "Duplicate PRISMA export submission was prevented."
                )
            self._submitted = True
            self._click(locator, page, "main CSV action")

    def _click(self, locator, page, label: str) -> None:
        try:
            locator.click(timeout=self.poll_ms)
        except Exception as exc:
            self._raise_if_closed(page, exc)
            raise MiniDownloadChangedDomError(
                f"The confirmed PRISMA {label} could not be activated."
            ) from exc

    def _required_visible(self, page, selector, label, cancel_event):
        try:
            locator = page.locator(selector)
        except Exception as exc:
            self._raise_if_closed(page, exc)
            raise MiniDownloadChangedDomError(
                f"The confirmed PRISMA {label} is unavailable."
            ) from exc
        deadline = self._clock() + self.timeout_ms / 1000
        while self._clock() < deadline:
            self._check_cancelled(cancel_event)
            try:
                locator.wait_for(state="visible", timeout=self.poll_ms)
                return locator
            except Exception as exc:
                self._raise_if_closed(page, exc)
                if not self._is_timeout(exc):
                    raise MiniDownloadChangedDomError(
                        f"The confirmed PRISMA {label} is unavailable."
                    ) from exc
        raise MiniDownloadChangedDomError(
            f"The confirmed PRISMA {label} did not appear in time."
        )

    def _await_download_or_dialog(self, page, captured, cancel_event):
        deadline = self._clock() + self.timeout_ms / 1000
        dialog = page.locator(self.DIALOG_SELECTOR)
        while self._clock() < deadline:
            self._check_cancelled(cancel_event)
            if captured:
                return None
            try:
                observed = page.wait_for_event("download", timeout=self.poll_ms)
                if not captured:
                    captured.append(observed)
                return None
            except Exception as exc:
                self._raise_if_closed(page, exc)
                if not self._is_timeout(exc):
                    raise MiniDownloadMissingError(
                        "The PRISMA CSV download event could not be observed."
                    ) from exc
            try:
                if dialog.is_visible(timeout=self.poll_ms):
                    return self._parse_warning(dialog, page)
            except Exception as exc:
                self._raise_if_closed(page, exc)
                if not self._is_timeout(exc):
                    raise MiniDownloadChangedDomError(
                        "The PRISMA limit-dialog state could not be inspected."
                    ) from exc
        raise MiniDownloadTimeoutError(
            "PRISMA did not start a CSV download or show its limit dialog in time."
        )

    def _await_download(self, page, captured, cancel_event):
        deadline = self._clock() + self.timeout_ms / 1000
        while self._clock() < deadline:
            self._check_cancelled(cancel_event)
            if captured:
                return captured[0]
            try:
                observed = page.wait_for_event("download", timeout=self.poll_ms)
                if not captured:
                    captured.append(observed)
                return captured[0]
            except Exception as exc:
                self._raise_if_closed(page, exc)
                if not self._is_timeout(exc):
                    raise MiniDownloadMissingError(
                        "The confirmed PRISMA CSV action did not start a download."
                    ) from exc
        raise MiniDownloadTimeoutError(
            "PRISMA did not start the confirmed CSV download in time."
        )

    def _parse_warning(self, dialog, page) -> tuple[int, int]:
        try:
            text = dialog.inner_text(timeout=self.poll_ms)
        except Exception as exc:
            self._raise_if_closed(page, exc)
            raise MiniDownloadChangedDomError(
                "The PRISMA limit-warning text is unavailable."
            ) from exc
        matches = list(_LIMIT_WARNING.finditer(text))
        if text.count(_LIMIT_WARNING_PREFIX) != 1 or len(matches) != 1:
            raise MiniDownloadChangedDomError(
                "The PRISMA limit-warning text does not match the confirmed contract."
            )
        match = matches[0]
        downloaded, total = (int(value) for value in match.groups())
        if downloaded > total:
            raise MiniDownloadChangedDomError(
                "The PRISMA limit-warning counts are inconsistent."
            )
        return downloaded, total

    def _accept_download(self, download, operation, requested_range, counts, cancel_event):
        try:
            suggested = download.suggested_filename
        except Exception as exc:
            raise MiniDownloadMissingError(
                "PRISMA did not provide completed download metadata."
            ) from exc
        if suggested != OFFICIAL_FILENAME:
            raise MiniDownloadUnexpectedFilenameError(
                "PRISMA returned an unexpected CSV filename."
            )
        try:
            failure = download.failure()
        except Exception as exc:
            raise MiniDownloadMissingError(
                "PRISMA download completion could not be verified."
            ) from exc
        if failure:
            raise MiniDownloadPartialError("PRISMA reported an incomplete CSV download.")
        staging = operation / f"{OFFICIAL_FILENAME}.part"
        final = operation / OFFICIAL_FILENAME
        try:
            download.save_as(str(staging))
        except Exception as exc:
            self._check_cancelled(cancel_event)
            raise MiniDownloadFilesystemError(
                "The PRISMA CSV could not be saved to the application temporary boundary."
            ) from exc
        self._check_cancelled(cancel_event)
        if any(path != staging for path in operation.iterdir()):
            raise MiniDownloadPartialError(
                "Unexpected partial artifacts were found in the owned download operation."
            )
        try:
            if not staging.is_file():
                raise MiniDownloadPartialError(
                    "The completed PRISMA CSV staging file is missing."
                )
            size = staging.stat().st_size
            if size <= 0:
                raise MiniDownloadEmptyError("The downloaded PRISMA CSV is empty.")
            digest = self._sha256(staging)
            if staging.stat().st_size != size or self._sha256(staging) != digest:
                raise MiniDownloadPartialError(
                    "The downloaded PRISMA CSV changed during validation."
                )
            require_csv_format(staging, CsvFormat.PRISMA_EXPORT)
            os.replace(staging, final)
            if (
                not final.is_file()
                or final.stat().st_size != size
                or self._sha256(final) != digest
            ):
                raise MiniDownloadPartialError(
                    "The finalized PRISMA CSV does not match its validated metadata."
                )
        except MiniDownloadError:
            raise
        except CsvFormatError as exc:
            raise MiniDownloadContractError(
                "The downloaded file is not the authoritative PRISMA CSV contract."
            ) from exc
        except OSError as exc:
            raise MiniDownloadFilesystemError(
                "The PRISMA CSV temporary file could not be finalized."
            ) from exc
        request = SourceImportRequest(
            requested_range=requested_range, source_name=OFFICIAL_FILENAME,
            sha256=digest, size_bytes=size,
        )
        downloaded_count, total_count = counts or (None, None)
        return MiniDownloadedSource(
            final.resolve(), request, downloaded_count, total_count
        )

    def _create_operation_directory(self) -> Path:
        operation_id = self._operation_id_factory()
        if not operation_id or Path(operation_id).name != operation_id:
            raise MiniDownloadFilesystemError(
                "A safe temporary download operation identifier could not be created."
            )
        operation = self.temporary_root / operation_id
        try:
            self.temporary_root.mkdir(parents=True, exist_ok=True)
            operation.mkdir(exist_ok=False)
        except OSError as exc:
            raise MiniDownloadFilesystemError(
                "The application temporary download operation could not be created."
            ) from exc
        return operation

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _is_timeout(exc: Exception) -> bool:
        return exc.__class__.__name__ == "TimeoutError"

    @staticmethod
    def _check_cancelled(cancel_event: threading.Event) -> None:
        if cancel_event.is_set():
            raise MiniDownloadCancelledError("PRISMA CSV download was cancelled.")

    @staticmethod
    def _raise_if_closed(page, cause: Exception) -> None:
        try:
            closed = page.is_closed()
        except Exception:
            closed = False
        if closed:
            raise MiniDownloadPageClosedError(
                "The managed PRISMA page closed during CSV download."
            ) from cause

    @staticmethod
    def _cleanup(operation: Path) -> None:
        try:
            if operation.exists():
                shutil.rmtree(operation)
        except OSError as exc:
            raise MiniDownloadCleanupError(
                "Owned temporary download artifacts could not be removed."
            ) from exc
