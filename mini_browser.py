"""Mini-owned Playwright lifecycle for the PRISMA auction export page."""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Callable, TypeVar

from browser import DefaultBrowserDetector, PRISMA_AUCTIONS_URL, _ensure_subprocess_output_streams
from mini_domain import MiniDateRange
from prisma_page import (
    PrismaAuthenticationRequiredError,
    PrismaInvalidSessionError,
    PrismaSessionValidator,
)
from runtime_logging import LOGGER_NAME, safe_log


class MiniBrowserFailureKind(str, Enum):
    STARTUP = "startup"
    AUTHENTICATION_REQUIRED = "authentication-required"
    TIMEOUT = "timeout"
    LIFECYCLE = "lifecycle"
    CANCELLED = "cancelled"
    FILTER_SELECTOR = "filter-selector"
    FILTER_VALUE = "filter-value"
    FILTER_TIMESTAMP = "filter-timestamp"
    FILTER_APPLY_TIMEOUT = "filter-apply-timeout"
    FILTER_REFRESH = "filter-refresh"


class MiniBrowserError(RuntimeError):
    kind: MiniBrowserFailureKind

    def __init__(self, message: str, *, attempts: int = 1) -> None:
        super().__init__(message)
        self.attempts = attempts


class MiniBrowserStartupError(MiniBrowserError):
    kind = MiniBrowserFailureKind.STARTUP


class MiniBrowserAuthenticationRequiredError(MiniBrowserError):
    kind = MiniBrowserFailureKind.AUTHENTICATION_REQUIRED


class MiniBrowserTimeoutError(MiniBrowserError):
    kind = MiniBrowserFailureKind.TIMEOUT


class MiniBrowserLifecycleError(MiniBrowserError):
    kind = MiniBrowserFailureKind.LIFECYCLE


class MiniBrowserCancelledError(MiniBrowserError):
    kind = MiniBrowserFailureKind.CANCELLED


class MiniDateFilterError(MiniBrowserError):
    """Base for typed failures in the confirmed M.10 DOM contract."""


class MiniDateFilterSelectorError(MiniDateFilterError):
    kind = MiniBrowserFailureKind.FILTER_SELECTOR


class MiniDateFilterValueError(MiniDateFilterError):
    kind = MiniBrowserFailureKind.FILTER_VALUE


class MiniDateFilterTimestampError(MiniDateFilterError):
    kind = MiniBrowserFailureKind.FILTER_TIMESTAMP


class MiniDateFilterApplyTimeoutError(MiniDateFilterError):
    kind = MiniBrowserFailureKind.FILTER_APPLY_TIMEOUT


class MiniDateFilterRefreshError(MiniDateFilterError):
    kind = MiniBrowserFailureKind.FILTER_REFRESH


class BrowserMode(str, Enum):
    HEADLESS = "headless"
    VISIBLE = "visible"


@dataclass(frozen=True)
class MiniBrowserPolicy:
    """Explicit M.8 launch policy; no automatic visible-browser fallback."""

    mode: BrowserMode = BrowserMode.HEADLESS
    navigation_timeout_ms: int = 20_000
    readiness_timeout_ms: int = 10_000
    max_attempts: int = 2
    filter_timeout_ms: int = 10_000
    refresh_timeout_ms: int = 20_000
    cancellation_poll_ms: int = 100

    def __post_init__(self) -> None:
        if (
            self.navigation_timeout_ms <= 0
            or self.readiness_timeout_ms <= 0
            or self.filter_timeout_ms <= 0
            or self.refresh_timeout_ms <= 0
            or self.cancellation_poll_ms <= 0
        ):
            raise ValueError("Browser timeouts must be positive.")
        if self.max_attempts not in (1, 2):
            raise ValueError("Mini browser startup supports at most one retry.")


@dataclass(frozen=True)
class MiniBrowserReady:
    attempt: int
    mode: BrowserMode


@dataclass(frozen=True)
class MiniDateFilterResult:
    requested_range: MiniDateRange
    start_value: str
    end_value: str


class MiniPrismaDateFilter:
    """Applies one validated Mini range through the confirmed PRISMA selectors."""

    START_SELECTOR = '[data-testid="startOfAuctionFrom"]'
    END_SELECTOR = '[data-testid="startOfAuctionTo"]'
    APPLY_SELECTOR = '[data-testid="submit-filters"]'
    CONFIRMATION_SELECTOR = '[data-testid="filter-startOfAuctionFrom"]'
    BOUNDARY_TIME = "06:00"

    def __init__(
        self,
        *,
        timeout_ms: int = 10_000,
        refresh_timeout_ms: int = 20_000,
        poll_ms: int = 100,
        authentication_probe: Callable[[object], None] | None = None,
    ) -> None:
        if timeout_ms <= 0 or refresh_timeout_ms <= 0 or poll_ms <= 0:
            raise ValueError("Date-filter timeouts must be positive.")
        self.timeout_ms = timeout_ms
        self.refresh_timeout_ms = refresh_timeout_ms
        self.poll_ms = poll_ms
        self._authentication_probe = authentication_probe or PrismaSessionValidator().validate
        self._submission_lock = threading.Lock()
        self._submitted = False

    def apply(
        self, page: object, requested_range: MiniDateRange, cancel_event: threading.Event
    ) -> MiniDateFilterResult:
        if not isinstance(requested_range, MiniDateRange):
            raise TypeError("requested_range must be MiniDateRange.")
        if requested_range.end < requested_range.start:
            raise ValueError("end must be on or after start.")
        self._check_cancelled(cancel_event)
        start_value = self._format(requested_range.start)
        end_value = self._format(requested_range.end)
        start = self._required_locator(page, self.START_SELECTOR, "From", cancel_event)
        self._fill_and_verify(start, start_value, "From", page, cancel_event)
        self._check_cancelled(cancel_event)
        end = self._required_locator(page, self.END_SELECTOR, "To", cancel_event)
        self._fill_and_verify(end, end_value, "To", page, cancel_event)
        self._check_cancelled(cancel_event)
        apply_button = self._required_locator(
            page, self.APPLY_SELECTOR, "Apply", cancel_event
        )
        self._check_cancelled(cancel_event)
        with self._submission_lock:
            if self._submitted:
                raise MiniDateFilterRefreshError(
                    "The PRISMA date filter was already submitted; duplicate submission was prevented."
                )
            # A click timeout is an uncertain outcome: mark the submission before
            # dispatch so neither a retry nor a concurrent caller can click again.
            self._submitted = True
            try:
                apply_button.click(timeout=self.poll_ms)
            except Exception as exc:
                self._translate_authentication(page, exc)
                if self._is_timeout(exc):
                    raise MiniDateFilterApplyTimeoutError(
                        "The PRISMA date-filter Apply action timed out."
                    ) from exc
                raise MiniDateFilterSelectorError(
                    "The confirmed PRISMA Apply element could not be activated."
                ) from exc
        confirmation = self._required_locator(
            page,
            self.CONFIRMATION_SELECTOR,
            "applied-filter confirmation",
            cancel_event,
            timeout_error=MiniDateFilterApplyTimeoutError,
        )
        self._wait_for_refresh(page, cancel_event)
        if confirmation is None:  # pragma: no cover - required locator always returns
            raise AssertionError("confirmation locator missing")
        return MiniDateFilterResult(requested_range, start_value, end_value)

    def _required_locator(
        self,
        page,
        selector: str,
        label: str,
        cancel_event: threading.Event,
        *,
        timeout_error: type[MiniDateFilterError] = MiniDateFilterSelectorError,
    ):
        locator = page.locator(selector)
        elapsed = 0
        while elapsed < self.timeout_ms:
            self._check_cancelled(cancel_event)
            try:
                locator.wait_for(state="visible", timeout=min(self.poll_ms, self.timeout_ms - elapsed))
                return locator
            except Exception as exc:
                self._translate_authentication(page, exc)
                if not self._is_timeout(exc):
                    raise MiniDateFilterSelectorError(
                        f"The confirmed PRISMA {label} element is unavailable."
                    ) from exc
            elapsed += min(self.poll_ms, self.timeout_ms - elapsed)
        raise timeout_error(f"The confirmed PRISMA {label} element did not appear in time.")

    def _fill_and_verify(self, locator, intended: str, label: str, page, cancel_event) -> None:
        self._check_cancelled(cancel_event)
        try:
            locator.fill(intended, timeout=self.poll_ms)
        except Exception as exc:
            self._translate_authentication(page, exc)
            raise MiniDateFilterValueError(
                f"PRISMA rejected the intended {label} date-filter value."
            ) from exc
        self._check_cancelled(cancel_event)
        try:
            actual = locator.input_value(timeout=self.poll_ms)
            interpreted = locator.get_attribute(
                "data-test-iso-value", timeout=self.poll_ms
            )
        except Exception as exc:
            self._translate_authentication(page, exc)
            if self._is_timeout(exc):
                raise MiniDateFilterValueError(
                    f"PRISMA did not expose the accepted {label} value in time."
                ) from exc
            raise MiniDateFilterTimestampError(
                f"PRISMA did not expose a usable interpreted {label} timestamp."
            ) from exc
        if actual != intended:
            raise MiniDateFilterValueError(
                f"PRISMA normalized or rejected the intended {label} date-filter value."
            )
        if not interpreted:
            raise MiniDateFilterTimestampError(
                f"PRISMA did not expose an interpreted {label} timestamp."
            )
        try:
            parsed = datetime.fromisoformat(interpreted.replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise MiniDateFilterTimestampError(
                f"PRISMA exposed an invalid interpreted {label} timestamp."
            ) from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise MiniDateFilterTimestampError(
                f"PRISMA exposed a timezone-free interpreted {label} timestamp."
            )

    def _wait_for_refresh(self, page, cancel_event) -> None:
        elapsed = 0
        while elapsed < self.refresh_timeout_ms:
            self._check_cancelled(cancel_event)
            try:
                page.wait_for_load_state(
                    "networkidle",
                    timeout=min(self.poll_ms, self.refresh_timeout_ms - elapsed),
                )
                return
            except Exception as exc:
                self._translate_authentication(page, exc)
                if not self._is_timeout(exc):
                    raise MiniDateFilterRefreshError(
                        "PRISMA auction results failed to refresh."
                    ) from exc
            elapsed += min(self.poll_ms, self.refresh_timeout_ms - elapsed)
        raise MiniDateFilterRefreshError("PRISMA auction results did not refresh in time.")

    def _translate_authentication(self, page, cause: Exception) -> None:
        try:
            self._authentication_probe(page)
        except PrismaAuthenticationRequiredError as exc:
            raise MiniBrowserAuthenticationRequiredError(
                "PRISMA authentication was lost while applying the date filter."
            ) from exc
        except PrismaInvalidSessionError:
            return

    @staticmethod
    def _format(value) -> str:
        return f"{value:%d.%m.%Y}      {MiniPrismaDateFilter.BOUNDARY_TIME}"

    @staticmethod
    def _is_timeout(exc: Exception) -> bool:
        return exc.__class__.__name__ == "TimeoutError"

    @staticmethod
    def _check_cancelled(cancel_event: threading.Event) -> None:
        if cancel_event.is_set():
            raise MiniBrowserCancelledError(
                "PRISMA date filtering was cancelled."
            )


T = TypeVar("T")
ReadinessProbe = Callable[[object, int], None]
SessionAction = Callable[[object, threading.Event], T]


class MiniPrismaSession:
    """Starts, validates, uses, and deterministically closes one PRISMA session."""

    def __init__(
        self,
        *,
        policy: MiniBrowserPolicy | None = None,
        detector=None,
        playwright_factory: Callable[[], object] | None = None,
        readiness_probe: ReadinessProbe | None = None,
        logger=None,
    ) -> None:
        self.policy = policy or MiniBrowserPolicy()
        self._detector = detector or DefaultBrowserDetector()
        self._playwright_factory = playwright_factory
        self._readiness_probe = readiness_probe or self._default_readiness_probe
        self._logger = logger or logging.getLogger(LOGGER_NAME)

    def run(
        self,
        cancel_event: threading.Event,
        action: SessionAction[T] | None = None,
    ) -> MiniBrowserReady | T:
        if not isinstance(cancel_event, threading.Event):
            raise TypeError("cancel_event must be a threading.Event")
        last_error: MiniBrowserError | None = None
        for attempt in range(1, self.policy.max_attempts + 1):
            self._check_cancelled(cancel_event, attempt)
            try:
                return self._run_attempt(cancel_event, attempt, action)
            except MiniBrowserCancelledError:
                raise
            except (MiniBrowserAuthenticationRequiredError, MiniBrowserLifecycleError):
                raise
            except (MiniBrowserStartupError, MiniBrowserTimeoutError) as exc:
                last_error = exc
                if attempt >= self.policy.max_attempts:
                    exc.attempts = attempt
                    raise
                safe_log(
                    self._logger,
                    logging.WARNING,
                    "Mini PRISMA session retry: attempt=%s kind=%s",
                    attempt,
                    exc.kind.value,
                )
        assert last_error is not None
        raise last_error

    def apply_date_filter(
        self, cancel_event: threading.Event, requested_range: MiniDateRange
    ) -> MiniDateFilterResult:
        """Open the managed session and apply one validated date range."""
        adapter = MiniPrismaDateFilter(
            timeout_ms=self.policy.filter_timeout_ms,
            refresh_timeout_ms=self.policy.refresh_timeout_ms,
            poll_ms=self.policy.cancellation_poll_ms,
        )
        return self.run(
            cancel_event,
            lambda page, event: adapter.apply(page, requested_range, event),
        )

    def _run_attempt(self, cancel_event, attempt, action):
        playwright = None
        browser = None
        context = None
        page = None
        unexpectedly_closed = threading.Event()
        cleanup = threading.Event()
        listeners: list[tuple[object, str, object]] = []

        def attach(emitter, event: str) -> None:
            if emitter is None or not callable(getattr(emitter, "on", None)):
                return

            def on_closed(*_args) -> None:
                if not cleanup.is_set() and not cancel_event.is_set():
                    unexpectedly_closed.set()

            emitter.on(event, on_closed)
            listeners.append((emitter, event, on_closed))

        try:
            _ensure_subprocess_output_streams()
            executable = Path(self._detector.detect_executable())
            self._check_cancelled(cancel_event, attempt)
            playwright = self._start_playwright()
            launch_options = {
                "executable_path": str(executable),
                "headless": self.policy.mode is BrowserMode.HEADLESS,
            }
            browser = playwright.chromium.launch(**launch_options)
            attach(browser, "disconnected")
            self._check_cancelled(cancel_event, attempt)
            context = browser.new_context()
            attach(context, "close")
            page = context.new_page()
            attach(page, "close")
            attach(page, "crash")
            page.goto(
                PRISMA_AUCTIONS_URL,
                wait_until="domcontentloaded",
                timeout=self.policy.navigation_timeout_ms,
            )
            self._check_lifecycle(cancel_event, unexpectedly_closed, attempt)
            self._readiness_probe(page, self.policy.readiness_timeout_ms)
            self._check_lifecycle(cancel_event, unexpectedly_closed, attempt)
            safe_log(
                self._logger,
                logging.INFO,
                "Mini PRISMA session ready: attempt=%s mode=%s",
                attempt,
                self.policy.mode.value,
            )
            if action is None:
                return MiniBrowserReady(attempt, self.policy.mode)
            result = action(page, cancel_event)
            self._check_lifecycle(cancel_event, unexpectedly_closed, attempt)
            return result
        except MiniBrowserError:
            raise
        except PrismaAuthenticationRequiredError as exc:
            raise MiniBrowserAuthenticationRequiredError(
                "PRISMA authentication is required. Sign in through an approved session and retry.",
                attempts=attempt,
            ) from exc
        except PrismaInvalidSessionError as exc:
            raise MiniBrowserStartupError(
                "The PRISMA page is unavailable or did not become ready.", attempts=attempt
            ) from exc
        except Exception as exc:
            if cancel_event.is_set():
                raise MiniBrowserCancelledError("PRISMA session opening was cancelled.", attempts=attempt) from exc
            if self._is_timeout(exc):
                raise MiniBrowserTimeoutError(
                    "The PRISMA session timed out before it became ready.", attempts=attempt
                ) from exc
            if unexpectedly_closed.is_set():
                raise MiniBrowserLifecycleError(
                    "The managed PRISMA browser closed unexpectedly.", attempts=attempt
                ) from exc
            raise MiniBrowserStartupError(
                "The managed PRISMA browser could not be started.", attempts=attempt
            ) from exc
        finally:
            cleanup.set()
            for emitter, event, callback in reversed(listeners):
                try:
                    remove = getattr(emitter, "remove_listener", None)
                    if callable(remove):
                        remove(event, callback)
                except Exception:
                    safe_log(self._logger, logging.WARNING, "Mini browser listener cleanup failed.")
            for resource in (page, context, browser):
                if resource is not None:
                    try:
                        resource.close()
                    except Exception:
                        safe_log(self._logger, logging.WARNING, "Mini browser resource cleanup failed.")
            if playwright is not None:
                try:
                    playwright.stop()
                except Exception:
                    safe_log(self._logger, logging.WARNING, "Mini Playwright cleanup failed.")

    def _start_playwright(self):
        if self._playwright_factory is not None:
            return self._playwright_factory()
        from playwright.sync_api import sync_playwright

        return sync_playwright().start()

    @staticmethod
    def _default_readiness_probe(page, timeout_ms: int) -> None:
        page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
        PrismaSessionValidator().validate(page)

    @staticmethod
    def _is_timeout(exc: Exception) -> bool:
        return exc.__class__.__name__ == "TimeoutError"

    @staticmethod
    def _check_cancelled(cancel_event: threading.Event, attempt: int) -> None:
        if cancel_event.is_set():
            raise MiniBrowserCancelledError("PRISMA session opening was cancelled.", attempts=attempt)

    @classmethod
    def _check_lifecycle(cls, cancel_event, unexpectedly_closed, attempt) -> None:
        cls._check_cancelled(cancel_event, attempt)
        if unexpectedly_closed.is_set():
            raise MiniBrowserLifecycleError(
                "The managed PRISMA browser closed unexpectedly.", attempts=attempt
            )
