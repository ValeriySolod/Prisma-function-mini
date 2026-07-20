from __future__ import annotations

import os
import logging
import queue
import re
import sys
import threading
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from runtime_logging import LOGGER_NAME, safe_log
from prisma_page import (
    PrismaAuthenticationRequiredError, PrismaInvalidSessionError,
    PrismaLookupTimeoutError, PrismaPageAdapterError, PrismaPageReader,
    PrismaPageUnavailableError,
    PrismaSessionValidator,
)

try:
    import winreg
except ImportError:  # pragma: no cover - exercised only on non-Windows hosts
    winreg = None

PRISMA_AUCTIONS_URL = (
    "https://app.prisma-capacity.eu/reporting/auctions/"
    "short-and-long-term-auctions"
)


class BrowserState(str, Enum):
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"


@dataclass(frozen=True)
class LaunchResult:
    generation: int
    success: bool
    error: str | None = None
    kind: str = "launch"


@dataclass
class _PageRequest:
    generation: int
    record: object
    completed: threading.Event
    status: str | None = None
    error: Exception | None = None
    abandoned: bool = False


class _LaunchCancelled(Exception):
    """Internal control flow for a user-cancelled browser launch."""


_NULL_STREAMS = []


def _ensure_subprocess_output_streams() -> None:
    """Give child processes valid output handles in windowed executables."""
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            stream = open(os.devnull, "w", encoding="utf-8")
            _NULL_STREAMS.append(stream)
            setattr(sys, name, stream)


class DefaultBrowserDetector:
    """Resolves the supported browser registered for HTTP URLs on Windows."""

    USER_CHOICE = (
        r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations"
        r"\http\UserChoice"
    )

    def detect_executable(self) -> Path:
        if winreg is None:
            raise RuntimeError("Default browser detection is only supported on Windows.")
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.USER_CHOICE) as key:
                prog_id = winreg.QueryValueEx(key, "ProgId")[0]
            with winreg.OpenKey(
                winreg.HKEY_CLASSES_ROOT, rf"{prog_id}\shell\open\command"
            ) as key:
                command = winreg.QueryValueEx(key, None)[0]
        except OSError as exc:
            raise RuntimeError(
                "The Windows default browser association could not be read."
            ) from exc

        match = re.match(r'^\s*"([^"]+)"|^\s*([^\s]+)', command or "")
        if not match:
            raise RuntimeError("The Windows default browser association is invalid.")
        executable = Path(match.group(1) or match.group(2))
        name = executable.name.lower()
        if name not in {"chrome.exe", "msedge.exe"}:
            raise RuntimeError(
                "The default browser is not supported. Use Google Chrome or Microsoft Edge."
            )
        if not executable.is_file():
            raise RuntimeError(f"The default browser executable was not found: {executable}")
        return executable


class PrismaAuctionFilter:
    """Locates and applies the Marketed Capacity filter on the PRISMA page."""

    TIMEOUT_MS = 10_000
    FIELD_NAME = re.compile(r"Marketed\s+Capacity", re.IGNORECASE)
    GREATER_OR_EQUAL = re.compile(
        r"greater\s+than\s+or\s+equal|more\s+than\s+or\s+equal|>=|≥",
        re.IGNORECASE,
    )
    ACTIVE_FILTER = re.compile(r"^Active\s+Filter:", re.IGNORECASE)
    MARKETED = re.compile(r"^Marketed$", re.IGNORECASE)

    def apply(self, page, cancel_event: threading.Event) -> None:
        self._check_cancelled(cancel_event)
        page.wait_for_load_state("domcontentloaded", timeout=self.TIMEOUT_MS)
        if self._apply_current_design(page, cancel_event):
            return
        container = self._find_marketed_capacity_container(page)
        self._check_cancelled(cancel_event)
        operator = self._find_operator_dropdown(container)
        self._set_operator(page, operator, cancel_event)
        input_element = self._find_value_input(container)
        self._check_cancelled(cancel_event)
        try:
            input_element.fill("1000", timeout=self.TIMEOUT_MS)
        except Exception as exc:
            self._check_cancelled(cancel_event)
            raise RuntimeError("Failed to set the value to 1000") from exc
        self._click_apply(container, cancel_event)

    def _apply_current_design(self, page, cancel_event: threading.Event) -> bool:
        """Apply the lower Marketed bound in PRISMA's current filter panel."""
        try:
            toggle = page.get_by_role("button", name=self.ACTIVE_FILTER).first
            toggle.wait_for(state="visible", timeout=self.TIMEOUT_MS)
        except Exception:
            return False

        self._check_cancelled(cancel_event)
        try:
            toggle.click(timeout=self.TIMEOUT_MS)
            marketed = page.get_by_role(
                "spinbutton", name=self.MARKETED
            ).first
            marketed.wait_for(state="visible", timeout=self.TIMEOUT_MS)
            marketed.fill("1000", timeout=self.TIMEOUT_MS)
            filter_button = page.get_by_role(
                "button", name=re.compile(r"^Filter$", re.IGNORECASE)
            ).first
            filter_button.wait_for(state="visible", timeout=self.TIMEOUT_MS)
            filter_button.click(timeout=self.TIMEOUT_MS)
        except Exception as exc:
            self._check_cancelled(cancel_event)
            raise RuntimeError(
                "Failed to set the current PRISMA Marketed lower bound to 1000"
            ) from exc
        self._check_cancelled(cancel_event)
        return True

    def _find_marketed_capacity_container(self, page):
        return self._first_visible(
            (
                lambda: page.get_by_role("group", name=self.FIELD_NAME).first,
                lambda: page.get_by_text(self.FIELD_NAME).first.locator(
                    "xpath=ancestor::*[self::fieldset or @role='group' "
                    "or contains(@data-testid, 'filter') "
                    "or contains(@aria-label, 'Marketed Capacity')][1]"
                ),
            ),
            "Marketed Capacity filter container was not found",
        )

    def _find_operator_dropdown(self, container):
        return self._first_visible(
            (
                lambda: container.get_by_label(
                    re.compile(r"operator|condition", re.IGNORECASE)
                ).first,
                lambda: container.get_by_role("combobox").first,
                lambda: container.locator("select").first,
            ),
            "Operator dropdown was not found in the Marketed Capacity filter",
        )

    def _find_value_input(self, container):
        return self._first_visible(
            (
                lambda: container.get_by_label(self.FIELD_NAME).first,
                lambda: container.get_by_role(
                    "spinbutton", name=self.FIELD_NAME
                ).first,
                lambda: container.get_by_role("textbox", name=self.FIELD_NAME).first,
                lambda: container.locator(
                    "input[type='number'], input[inputmode='numeric']"
                ).first,
            ),
            "Value field was not found in the Marketed Capacity filter",
        )

    def _first_visible(self, factories, error_message: str):
        for factory in factories:
            try:
                locator = factory()
                locator.wait_for(state="visible", timeout=self.TIMEOUT_MS)
                return locator
            except Exception:
                continue
        raise RuntimeError(error_message)

    def _set_operator(self, page, operator, cancel_event: threading.Event) -> None:
        for label in (
            "Greater than or equal",
            "Greater than or equal to",
            "Is greater than or equal to",
            "More than or equal",
            ">=",
            "≥",
        ):
            try:
                operator.select_option(label=label, timeout=self.TIMEOUT_MS)
                return
            except Exception:
                self._check_cancelled(cancel_event)
                continue
        try:
            operator.click(timeout=self.TIMEOUT_MS)
            options = page.get_by_role("option", name=self.GREATER_OR_EQUAL)
            if options.count() != 1:
                raise RuntimeError("operator option is not unique")
            options.first.click(timeout=self.TIMEOUT_MS)
        except Exception as exc:
            self._check_cancelled(cancel_event)
            raise RuntimeError(
                "No supported 'greater than or equal to' operator option was found"
            ) from exc

    def _click_apply(self, container, cancel_event: threading.Event) -> None:
        self._check_cancelled(cancel_event)
        try:
            button = container.get_by_role(
                "button", name=re.compile(r"apply", re.IGNORECASE)
            ).first
            button.wait_for(state="visible", timeout=self.TIMEOUT_MS)
            button.click(timeout=self.TIMEOUT_MS)
        except Exception as exc:
            self._check_cancelled(cancel_event)
            raise RuntimeError(
                "Apply was not found or could not be clicked in the "
                "Marketed Capacity filter"
            ) from exc
        self._check_cancelled(cancel_event)

    @staticmethod
    def _check_cancelled(cancel_event: threading.Event) -> None:
        if cancel_event.is_set():
            raise _LaunchCancelled()


class BrowserController:
    """Opens PRISMA in the supported Windows default browser."""

    def __init__(
        self, page_filter: PrismaAuctionFilter | None = None, detector=None, logger=None,
        page_reader: PrismaPageReader | None = None,
        session_validator: PrismaSessionValidator | None = None,
    ) -> None:
        self._playwright = None
        self._browser = None
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._state = BrowserState.IDLE
        self._generation = 0
        self._cancel_event: threading.Event | None = None
        self._results: queue.SimpleQueue[LaunchResult] = queue.SimpleQueue()
        self._page_requests: dict[int, queue.Queue[_PageRequest]] = {}
        self.last_error: str | None = None
        self._page_filter = page_filter or PrismaAuctionFilter()
        self._detector = detector or DefaultBrowserDetector()
        self._logger = logger or logging.getLogger(LOGGER_NAME)
        self._page_reader = page_reader or PrismaPageReader()
        self._session_validator = session_validator or PrismaSessionValidator()

    def _log(self, level: int, message: str, *args, **kwargs) -> None:
        safe_log(self._logger, level, message, *args, **kwargs)

    @property
    def state(self) -> BrowserState:
        with self._lock:
            return self._state

    @property
    def is_running(self) -> bool:
        return self.state is BrowserState.RUNNING

    def open(self) -> int:
        with self._lock:
            if self._state is not BrowserState.IDLE:
                raise RuntimeError("The browser session is already running or stopping.")

            self._generation += 1
            generation = self._generation
            self._page_requests[generation] = queue.Queue()
            cancel_event = threading.Event()
            self._cancel_event = cancel_event
            self.last_error = None
            self._state = BrowserState.STARTING
            self._log(logging.INFO, "Browser launch requested: generation=%s state=%s", generation, self._state.value)
            thread = threading.Thread(
                target=self._run,
                args=(generation, cancel_event),
                daemon=True,
            )
            self._thread = thread
            thread.start()
            return generation

    def get_launch_results(self) -> list[LaunchResult]:
        results = []
        while True:
            try:
                results.append(self._results.get_nowait())
            except queue.Empty:
                return results

    def _is_current(self, generation: int) -> bool:
        return generation == self._generation

    def read_live_auction_status(self, record, timeout_seconds: float = 15.0) -> str:
        with self._lock:
            if self._state is not BrowserState.RUNNING:
                raise PrismaPageUnavailableError(
                    "The active PRISMA browser page is not available."
                )
            generation = self._generation
            request_queue = self._page_requests.get(generation)
            if request_queue is None:
                raise PrismaPageUnavailableError(
                    "The active PRISMA browser request queue is not available."
                )
            request = _PageRequest(generation, record, threading.Event())
            request_queue.put(request)
        self._log(
            logging.INFO,
            "Live status request queued: generation=%s auction_id=%s",
            generation, record.auction_id,
        )
        if not request.completed.wait(timeout_seconds):
            request.abandoned = True
            self._log(
                logging.WARNING,
                "Live status lookup timed out: generation=%s auction_id=%s timeout_seconds=%s",
                generation, record.auction_id, timeout_seconds,
            )
            self._stop_generation(generation, "lookup-timeout")
            raise PrismaLookupTimeoutError(
                "The live PRISMA status lookup timed out. Reopen the browser and retry."
            )
        if request.error is not None:
            raise request.error
        if request.status is None:
            raise PrismaPageUnavailableError(
                "The active PRISMA page returned no auction status."
            )
        return request.status

    def _process_page_requests(self, page, generation: int) -> None:
        with self._lock:
            request_queue = self._page_requests.get(generation)
        if request_queue is None:
            return
        while True:
            try:
                request = request_queue.get_nowait()
            except queue.Empty:
                return
            try:
                if request.abandoned:
                    continue
                if request.generation != generation:
                    raise PrismaPageUnavailableError(
                        "The PRISMA browser generation changed before the status request ran."
                    )
                is_closed = getattr(page, "is_closed", None)
                if callable(is_closed) and is_closed():
                    raise PrismaPageUnavailableError(
                        "The managed PRISMA page is closed."
                    )
                state = self._session_validator.validate(page)
                self._log(logging.INFO, "Public session validated: generation=%s classification=%s location=%s", generation, state.classification, state.location)
                request.status = self._page_reader.read_status(page, request.record)
                self._log(
                    logging.INFO,
                    "Live status request completed: generation=%s auction_id=%s status=%s",
                    generation, request.record.auction_id, request.status,
                )
            except PrismaAuthenticationRequiredError as exc:
                request.error = exc
                self._log(logging.WARNING, "Session validation failed: generation=%s classification=authentication-required", generation)
            except PrismaInvalidSessionError as exc:
                request.error = exc
                self._log(logging.WARNING, "Session validation failed: generation=%s classification=invalid-or-unavailable", generation)
            except PrismaPageUnavailableError as exc:
                request.error = exc
                self._log(
                    logging.WARNING,
                    "Live page unavailable: generation=%s auction_id=%s",
                    generation, request.record.auction_id,
                )
                self._stop_generation(generation, "live-page-unavailable")
            except PrismaPageAdapterError as exc:
                request.error = exc
                self._log(
                    logging.WARNING,
                    "Live status request failed: generation=%s auction_id=%s reason=%s",
                    generation, request.record.auction_id, exc,
                )
            except Exception as exc:
                request.error = PrismaPageUnavailableError(
                    "The active PRISMA page failed while reading auction status."
                )
                self._stop_generation(generation, "unexpected-live-page-failure")
                self._log(
                    logging.ERROR,
                    "Unexpected live status exception: generation=%s auction_id=%s",
                    generation, request.record.auction_id, exc_info=True,
                )
            finally:
                request.completed.set()

    def _stop_generation(self, generation: int, classification: str) -> bool:
        """Stop only the generation that reported a lifecycle failure."""
        with self._lock:
            if not self._is_current(generation) or self._state is BrowserState.IDLE:
                return False
            previous_state = self._state
            self._state = BrowserState.STOPPING
            cancel_event = self._cancel_event
            if cancel_event is not None:
                cancel_event.set()
        self._log(
            logging.INFO,
            "Generation stop requested: generation=%s state_before=%s classification=%s",
            generation, previous_state.value, classification,
        )
        return True

    def _fail_pending_page_requests(self, generation: int) -> None:
        with self._lock:
            request_queue = self._page_requests.pop(generation, None)
        if request_queue is None:
            return
        while True:
            try:
                request = request_queue.get_nowait()
            except queue.Empty:
                return
            request.error = PrismaPageUnavailableError(
                "The active PRISMA page closed before the status request completed."
            )
            request.completed.set()

    def _run(
        self,
        generation: int,
        cancel_event: threading.Event,
    ) -> None:
        playwright = None
        browser = None
        launch_error: str | None = None
        announced_success = False
        cleanup_started = threading.Event()
        lifecycle_failure = threading.Event()
        listeners = []
        state_before_cleanup = BrowserState.IDLE

        def lifecycle_reason() -> str:
            if cleanup_started.is_set():
                return "controller cleanup"
            if lifecycle_failure.is_set():
                return "unexpected"
            if cancel_event.is_set():
                return "user-requested shutdown"
            return "unexpected"

        def attach(emitter, event: str, label: str) -> None:
            if emitter is None or not callable(getattr(emitter, "on", None)):
                return
            def callback(*_args) -> None:
                classification = lifecycle_reason()
                self._log(
                    logging.INFO if classification != "unexpected" else logging.WARNING,
                    "%s event: generation=%s classification=%s state=%s",
                    label, generation, classification, self.state.value,
                )
                if classification == "unexpected" and not lifecycle_failure.is_set():
                    lifecycle_failure.set()
                    self._stop_generation(generation, "managed-browser-unavailable")
            try:
                emitter.on(event, callback)
                listeners.append((emitter, event, callback))
            except Exception:
                self._log(logging.WARNING, "Could not attach %s handler: generation=%s", label, generation, exc_info=True)

        try:
            _ensure_subprocess_output_streams()
            from playwright.sync_api import sync_playwright

            executable = self._detector.detect_executable()
            self._log(logging.INFO, "Default browser detected: generation=%s browser=%s executable=%s", generation, executable.name, executable)
            playwright = sync_playwright().start()
            if cancel_event.is_set():
                return

            launch_options = {
                "executable_path": str(executable),
                "headless": False,
                "args": ["--start-maximized"],
            }
            self._log(logging.INFO, "Playwright launch options: generation=%s options=%s", generation, launch_options)
            browser = playwright.chromium.launch(**launch_options)
            self._log(logging.INFO, "Browser created: generation=%s", generation)
            attach(browser, "disconnected", "Browser disconnected")
            with self._lock:
                if self._is_current(generation):
                    self._playwright = playwright
                    self._browser = browser
            if cancel_event.is_set():
                return

            page = browser.new_page(no_viewport=True)
            context = getattr(page, "context", None)
            self._log(logging.INFO, "Browser context created: generation=%s", generation)
            self._log(logging.INFO, "Page created: generation=%s", generation)
            attach(page, "crash", "Page crash")
            attach(page, "close", "Page close")
            attach(context, "close", "Context close")
            page.goto(PRISMA_AUCTIONS_URL, wait_until="domcontentloaded")
            self._log(logging.INFO, "Navigation completed: generation=%s url=%s", generation, PRISMA_AUCTIONS_URL)
            try:
                session_state = self._session_validator.validate(page)
            except PrismaAuthenticationRequiredError:
                self._log(logging.WARNING, "Session validation failed: generation=%s classification=authentication-required", generation)
                raise
            except PrismaInvalidSessionError:
                self._log(logging.WARNING, "Session validation failed: generation=%s classification=invalid-or-unavailable", generation)
                raise
            self._log(logging.INFO, "Public session validated: generation=%s classification=%s location=%s", generation, session_state.classification, session_state.location)
            try:
                self._page_filter.apply(page, cancel_event)
            except _LaunchCancelled:
                return
            except Exception as exc:
                reason = str(exc).strip() or exc.__class__.__name__
                raise RuntimeError(
                    "Failed to set the filter "
                    f"Marketed >= 1000: {reason}"
                ) from exc
            self._log(logging.INFO, "Filter completed: generation=%s filter=Marketed >= 1000", generation)

            with self._lock:
                if (
                    self._is_current(generation)
                    and self._state is BrowserState.STARTING
                    and not cancel_event.is_set()
                ):
                    self._state = BrowserState.RUNNING
                    announced_success = True
                    self._results.put(LaunchResult(generation, True))

            if not announced_success:
                return

            while not cancel_event.wait(0.05):
                self._process_page_requests(page, generation)
        except _LaunchCancelled:
            self._log(logging.INFO, "Browser launch cancelled: generation=%s", generation)
        except Exception as exc:
            launch_error = str(exc).strip() or exc.__class__.__name__
            self._log(logging.ERROR, "Unexpected browser exception: generation=%s", generation, exc_info=True)
        finally:
            state_before_cleanup = self.state
            cleanup_started.set()
            self._fail_pending_page_requests(generation)
            self._log(logging.INFO, "Cleanup starting: generation=%s state=%s cancelled=%s", generation, self.state.value, cancel_event.is_set())
            if browser is not None:
                try:
                    browser.close()
                except Exception:
                    self._log(logging.WARNING, "Browser cleanup failed: generation=%s", generation, exc_info=True)
            if playwright is not None:
                try:
                    playwright.stop()
                except Exception:
                    self._log(logging.WARNING, "Playwright cleanup failed: generation=%s", generation, exc_info=True)

            for emitter, event, callback in listeners:
                try:
                    remove = getattr(emitter, "remove_listener", None)
                    if callable(remove):
                        remove(event, callback)
                except Exception:
                    self._log(logging.WARNING, "Could not remove lifecycle handler: generation=%s event=%s", generation, event, exc_info=True)

            with self._lock:
                is_current = self._is_current(generation)
                was_cancelled = cancel_event.is_set() or (
                    is_current and self._state is BrowserState.STOPPING
                )
                if is_current:
                    self._browser = None
                    self._playwright = None
                    self._cancel_event = None
                    self._state = BrowserState.IDLE
                    if launch_error and not was_cancelled and not announced_success:
                        self.last_error = launch_error
                        self._results.put(
                            LaunchResult(generation, False, launch_error)
                        )
                    elif lifecycle_failure.is_set() and announced_success:
                        self.last_error = "The managed PRISMA page or browser was closed."
                        self._results.put(LaunchResult(
                            generation, False, self.last_error, "closed"
                        ))
                final_state = self._state.value
            self._log(logging.INFO, "Cleanup completed: generation=%s state_before=%s state_after=%s cancelled=%s", generation, state_before_cleanup.value, final_state, was_cancelled)

    def stop(self) -> None:
        with self._lock:
            if self._state is BrowserState.IDLE:
                self._log(logging.INFO, "Stop requested: generation=%s state=%s no_action=true", self._generation, self._state.value)
                return
            previous_state = self._state
            self._state = BrowserState.STOPPING
            self._log(logging.INFO, "Stop requested: generation=%s state_before=%s state_after=%s classification=user-requested shutdown", self._generation, previous_state.value, self._state.value)
            if self._cancel_event is not None:
                self._cancel_event.set()
