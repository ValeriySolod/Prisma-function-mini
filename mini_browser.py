"""Mini-owned Playwright lifecycle for the PRISMA auction export page."""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, TypeVar

from browser import DefaultBrowserDetector, PRISMA_AUCTIONS_URL, _ensure_subprocess_output_streams
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

    def __post_init__(self) -> None:
        if self.navigation_timeout_ms <= 0 or self.readiness_timeout_ms <= 0:
            raise ValueError("Browser timeouts must be positive.")
        if self.max_attempts not in (1, 2):
            raise ValueError("Mini browser startup supports at most one retry.")


@dataclass(frozen=True)
class MiniBrowserReady:
    attempt: int
    mode: BrowserMode


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
