import threading
from pathlib import Path

import pytest

from mini_browser import (
    BrowserMode,
    MiniBrowserAuthenticationRequiredError,
    MiniBrowserCancelledError,
    MiniBrowserLifecycleError,
    MiniBrowserPolicy,
    MiniBrowserReady,
    MiniBrowserStartupError,
    MiniBrowserTimeoutError,
    MiniPrismaSession,
)
from prisma_page import PrismaAuthenticationRequiredError


class FakeEmitter:
    def __init__(self):
        self.listeners = {}
        self.closed = 0

    def on(self, event, callback):
        self.listeners.setdefault(event, []).append(callback)

    def remove_listener(self, event, callback):
        self.listeners[event].remove(callback)

    def emit(self, event):
        for callback in tuple(self.listeners.get(event, ())):
            callback()

    def close(self):
        self.closed += 1


class FakePage(FakeEmitter):
    def __init__(self, goto_error=None):
        super().__init__()
        self.goto_error = goto_error
        self.goto_calls = []

    def goto(self, url, **kwargs):
        self.goto_calls.append((url, kwargs))
        if self.goto_error:
            raise self.goto_error


class FakeContext(FakeEmitter):
    def __init__(self, page=None):
        super().__init__()
        self.page = page or FakePage()

    def new_page(self):
        return self.page


class FakeBrowser(FakeEmitter):
    def __init__(self, context=None):
        super().__init__()
        self.context = context or FakeContext()

    def new_context(self):
        return self.context


class FakeChromium:
    def __init__(self, launch):
        self._launch = launch
        self.options = []

    def launch(self, **kwargs):
        self.options.append(kwargs)
        return self._launch()


class FakePlaywright:
    def __init__(self, launch):
        self.chromium = FakeChromium(launch)
        self.stopped = 0

    def stop(self):
        self.stopped += 1


class FakeDetector:
    def detect_executable(self):
        return Path("C:/Program Files/Browser/chrome.exe")


class TimeoutError(Exception):
    pass


def make_session(launch, readiness=lambda page, timeout: None, **policy):
    playwrights = []

    def factory():
        item = FakePlaywright(launch)
        playwrights.append(item)
        return item

    session = MiniPrismaSession(
        detector=FakeDetector(),
        playwright_factory=factory,
        readiness_probe=readiness,
        policy=MiniBrowserPolicy(**policy),
    )
    return session, playwrights


def assert_clean(browser, playwright):
    assert browser.context.page.closed == 1
    assert browser.context.closed == 1
    assert browser.closed == 1
    assert playwright.stopped == 1
    assert all(not callbacks for callbacks in browser.listeners.values())
    assert all(not callbacks for callbacks in browser.context.listeners.values())
    assert all(not callbacks for callbacks in browser.context.page.listeners.values())


def test_startup_readiness_headless_strategy_and_normal_closure():
    browser = FakeBrowser()
    readiness_calls = []
    session, playwrights = make_session(
        lambda: browser,
        lambda page, timeout: readiness_calls.append((page, timeout)),
        max_attempts=1,
    )

    result = session.run(threading.Event())

    assert result == MiniBrowserReady(1, BrowserMode.HEADLESS)
    assert readiness_calls == [(browser.context.page, 10_000)]
    assert playwrights[0].chromium.options == [{
        "executable_path": "C:\\Program Files\\Browser\\chrome.exe",
        "headless": True,
    }]
    assert browser.context.page.goto_calls[0][1]["timeout"] == 20_000
    assert_clean(browser, playwrights[0])


def test_session_action_runs_only_after_readiness_and_returns_value():
    browser = FakeBrowser()
    order = []
    session, _ = make_session(
        lambda: browser,
        lambda page, timeout: order.append("ready"),
        max_attempts=1,
    )
    assert session.run(
        threading.Event(), lambda page, cancel: order.append("action") or 7
    ) == 7
    assert order == ["ready", "action"]


def test_authentication_required_is_typed_not_retried_and_cleans_up():
    browser = FakeBrowser()

    def authentication_required(page, timeout):
        raise PrismaAuthenticationRequiredError("login page")

    session, playwrights = make_session(lambda: browser, authentication_required)
    with pytest.raises(MiniBrowserAuthenticationRequiredError) as caught:
        session.run(threading.Event())
    assert caught.value.attempts == 1
    assert len(playwrights) == 1
    assert_clean(browser, playwrights[0])


def test_timeout_is_typed_and_retried_once_with_cleanup():
    browsers = [FakeBrowser(FakeContext(FakePage(TimeoutError("slow")))) for _ in range(2)]
    session, playwrights = make_session(lambda: browsers.pop(0))
    with pytest.raises(MiniBrowserTimeoutError) as caught:
        session.run(threading.Event())
    assert caught.value.attempts == 2
    assert len(playwrights) == 2
    for playwright in playwrights:
        assert playwright.stopped == 1


def test_transient_startup_failure_retries_then_succeeds():
    browser = FakeBrowser()
    attempts = iter((RuntimeError("driver unavailable"), browser))

    def launch():
        value = next(attempts)
        if isinstance(value, Exception):
            raise value
        return value

    session, playwrights = make_session(launch)
    assert session.run(threading.Event()) == MiniBrowserReady(2, BrowserMode.HEADLESS)
    assert len(playwrights) == 2
    assert playwrights[0].stopped == 1
    assert_clean(browser, playwrights[1])


def test_startup_failure_after_bound_is_typed_and_all_attempts_cleanup():
    session, playwrights = make_session(lambda: (_ for _ in ()).throw(RuntimeError("no driver")))
    with pytest.raises(MiniBrowserStartupError) as caught:
        session.run(threading.Event())
    assert caught.value.attempts == 2
    assert len(playwrights) == 2
    assert all(item.stopped == 1 for item in playwrights)


def test_pre_start_cancellation_does_not_create_playwright():
    cancel = threading.Event()
    cancel.set()
    session, playwrights = make_session(lambda: FakeBrowser())
    with pytest.raises(MiniBrowserCancelledError):
        session.run(cancel)
    assert playwrights == []


def test_cooperative_cancellation_after_navigation_is_typed_and_cleans_up():
    cancel = threading.Event()
    browser = FakeBrowser()

    def readiness(page, timeout):
        cancel.set()

    session, playwrights = make_session(lambda: browser, readiness, max_attempts=1)
    with pytest.raises(MiniBrowserCancelledError):
        session.run(cancel)
    assert_clean(browser, playwrights[0])


def test_unexpected_manual_closure_is_typed_not_retried():
    browser = FakeBrowser()

    def readiness(page, timeout):
        page.emit("close")

    session, playwrights = make_session(lambda: browser, readiness)
    with pytest.raises(MiniBrowserLifecycleError) as caught:
        session.run(threading.Event())
    assert caught.value.attempts == 1
    assert len(playwrights) == 1
    assert_clean(browser, playwrights[0])


def test_cleanup_continues_when_one_close_fails():
    browser = FakeBrowser()

    def fail_page_close():
        browser.context.page.closed += 1
        raise RuntimeError("page close failed")

    browser.context.page.close = fail_page_close
    session, playwrights = make_session(lambda: browser, max_attempts=1)
    assert session.run(threading.Event()) == MiniBrowserReady(1, BrowserMode.HEADLESS)
    assert browser.context.closed == 1
    assert browser.closed == 1
    assert playwrights[0].stopped == 1


def test_visible_strategy_is_explicit_and_never_an_automatic_fallback():
    browser = FakeBrowser()
    session, playwrights = make_session(
        lambda: browser, mode=BrowserMode.VISIBLE, max_attempts=1
    )
    assert session.run(threading.Event()).mode is BrowserMode.VISIBLE
    assert playwrights[0].chromium.options[0]["headless"] is False


@pytest.mark.parametrize("max_attempts", [0, 3])
def test_retry_policy_is_bounded(max_attempts):
    with pytest.raises(ValueError):
        MiniBrowserPolicy(max_attempts=max_attempts)
