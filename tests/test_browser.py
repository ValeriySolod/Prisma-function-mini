import queue
import sys
import threading
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import Mock

import pytest

from browser import (
    BrowserController, BrowserState, DefaultBrowserDetector, LaunchResult,
    PrismaAuctionFilter, _PageRequest,
)
from auction_csv import AuctionCsvRecord
from prisma_page import (
    PrismaAuthenticationRequiredError, PrismaLookupTimeoutError,
    PrismaPageUnavailableError,
    PrismaSessionState, PrismaSessionValidator,
)
import browser as browser_module

ORIGINAL_DETECT_EXECUTABLE = DefaultBrowserDetector.detect_executable


@pytest.fixture(autouse=True)
def default_browser(monkeypatch):
    monkeypatch.setattr(
        DefaultBrowserDetector, "detect_executable",
        lambda self: Path("C:/Browsers/default.exe"),
    )
    monkeypatch.setattr(
        PrismaSessionValidator, "validate",
        lambda self, page: PrismaSessionState(
            "public-auctions",
            "https://app.prisma-capacity.eu/reporting/auctions/short-and-long-term-auctions",
        ),
    )


class RegistryKey:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def test_detector_resolves_registered_supported_executable(monkeypatch):
    monkeypatch.setattr(
        DefaultBrowserDetector, "detect_executable", ORIGINAL_DETECT_EXECUTABLE
    )
    values = iter(("ChromeHTML", '"C:\\Apps\\Chrome\\chrome.exe" -- "%1"'))
    registry = SimpleNamespace(
        HKEY_CURRENT_USER=object(), HKEY_CLASSES_ROOT=object(),
        OpenKey=lambda *args: RegistryKey(next(values)),
        QueryValueEx=lambda key, name: (key.value, None),
    )
    monkeypatch.setattr(browser_module, "winreg", registry)
    monkeypatch.setattr(Path, "is_file", lambda self: True)

    assert DefaultBrowserDetector().detect_executable() == Path(
        "C:/Apps/Chrome/chrome.exe"
    )


def test_detector_rejects_unsupported_default_browser(monkeypatch):
    monkeypatch.setattr(
        DefaultBrowserDetector, "detect_executable", ORIGINAL_DETECT_EXECUTABLE
    )
    values = iter(("FirefoxURL", '"C:\\Apps\\Firefox\\firefox.exe" -osint'))
    registry = SimpleNamespace(
        HKEY_CURRENT_USER=object(), HKEY_CLASSES_ROOT=object(),
        OpenKey=lambda *args: RegistryKey(next(values)),
        QueryValueEx=lambda key, name: (key.value, None),
    )
    monkeypatch.setattr(browser_module, "winreg", registry)

    with pytest.raises(RuntimeError, match="not supported"):
        DefaultBrowserDetector().detect_executable()


class FakeLocator:
    def __init__(self, *, wait_error=None, click_error=None, on_click=None):
        self.first = self
        self.wait_error = wait_error
        self.click_error = click_error
        self.on_click = on_click
        self.selected_labels = []
        self.filled_values = []
        self.clicks = 0

    def wait_for(self, *, state, timeout):
        if self.wait_error:
            raise self.wait_error

    def select_option(self, *, label, timeout):
        self.selected_labels.append(label)

    def fill(self, value, *, timeout):
        self.filled_values.append(value)

    def click(self, *, timeout):
        self.clicks += 1
        if self.on_click:
            self.on_click()
        if self.click_error:
            raise self.click_error

    def count(self):
        return 1


class FakeFilterContainer(FakeLocator):
    def __init__(self, *, apply_button=None):
        super().__init__()
        self.operator = FakeLocator()
        self.value_input = FakeLocator()
        self.apply_button = apply_button or FakeLocator()
        self.role_calls = []

    def get_by_label(self, name):
        if "operator|condition" in getattr(name, "pattern", ""):
            return self.operator
        return self.value_input

    def get_by_role(self, role, name=None):
        self.role_calls.append(role)
        if role == "combobox":
            return self.operator
        if role in ("spinbutton", "textbox"):
            return self.value_input
        if role == "button":
            return self.apply_button
        raise AssertionError(f"unexpected container role: {role}")

    def locator(self, selector):
        if selector == "select":
            return self.operator
        return self.value_input


class FakePageFilter:
    def __init__(self, error=None, block=None):
        self.error = error
        self.block = block
        self.pages = []

    def apply(self, page, cancel_event):
        self.pages.append(page)
        if self.block:
            self.block(cancel_event)
        if self.error:
            raise self.error


class SignallingQueue:
    def __init__(self):
        self._queue = queue.SimpleQueue()
        self.ready = threading.Event()

    def put(self, item):
        self._queue.put(item)
        self.ready.set()

    def get_nowait(self):
        return self._queue.get_nowait()


class FakePage:
    def __init__(self, navigation_error=None):
        self.navigation_error = navigation_error

    def goto(self, *args, **kwargs):
        if self.navigation_error:
            raise self.navigation_error


class FakeFilterPage(FakePage):
    def __init__(self, container):
        super().__init__()
        self.container = container
        self.other_filter_dropdown = FakeLocator()
        self.global_role_calls = []

    def wait_for_load_state(self, state, *, timeout):
        pass

    def get_by_role(self, role, name=None):
        self.global_role_calls.append(role)
        if role == "group":
            return self.container
        if role == "option":
            return FakeLocator()
        if role == "combobox":
            return self.other_filter_dropdown
        raise AssertionError(f"unexpected page role: {role}")

    def get_by_text(self, text):
        raise AssertionError("group strategy should find the container first")


class CurrentFilterPage(FakePage):
    def __init__(self):
        super().__init__()
        self.active_filter = FakeLocator()
        self.marketed = FakeLocator()
        self.filter_button = FakeLocator()

    def wait_for_load_state(self, state, *, timeout):
        pass

    def get_by_role(self, role, name=None):
        pattern = getattr(name, "pattern", "")
        if role == "button" and pattern.startswith("^Active"):
            return self.active_filter
        if role == "spinbutton" and pattern == "^Marketed$":
            return self.marketed
        if role == "button" and pattern == "^Filter$":
            return self.filter_button
        raise AssertionError((role, pattern))


class FakeBrowser:
    def __init__(self, page=None, *, new_page_error=None, new_page_block=None):
        self.page = page or FakePage()
        self.new_page_error = new_page_error
        self.new_page_block = new_page_block
        self.closed = threading.Event()
        self.new_page_calls = 0
        self.new_page_options = []

    def new_page(self, **kwargs):
        self.new_page_calls += 1
        self.new_page_options.append(kwargs)
        if self.new_page_block:
            self.new_page_block()
        if self.new_page_error:
            raise self.new_page_error
        return self.page

    def close(self):
        self.closed.set()


class FakePlaywright:
    def __init__(self, launch):
        self.chromium = SimpleNamespace(launch=launch)
        self.stopped = threading.Event()

    def stop(self):
        self.stopped.set()


class EventEmitter:
    def __init__(self):
        self.listeners = {}

    def on(self, event, callback):
        self.listeners.setdefault(event, []).append(callback)

    def remove_listener(self, event, callback):
        self.listeners[event].remove(callback)

    def emit(self, event):
        for callback in self.listeners.get(event, [])[:]:
            callback()


class EventPage(FakePage, EventEmitter):
    def __init__(self):
        FakePage.__init__(self)
        EventEmitter.__init__(self)
        self.context = EventEmitter()


class EventBrowser(FakeBrowser, EventEmitter):
    def __init__(self, page):
        FakeBrowser.__init__(self, page)
        EventEmitter.__init__(self)

    def close(self):
        self.page.emit("close")
        self.page.context.emit("close")
        self.emit("disconnected")
        super().close()


class ListLogger:
    def __init__(self, fail=False):
        self.messages = []
        self.fail = fail

    def log(self, level, message, *args, **kwargs):
        if self.fail:
            raise OSError("logging unavailable")
        self.messages.append(message % args if args else message)


def install_fake_playwright(monkeypatch, launch):
    playwright = FakePlaywright(launch)
    api = SimpleNamespace(
        sync_playwright=lambda: SimpleNamespace(start=lambda: playwright)
    )
    monkeypatch.setitem(sys.modules, "playwright.sync_api", api)
    return playwright


def join_worker(controller):
    controller._thread.join(timeout=2)
    assert not controller._thread.is_alive()


def monitoring_record(auction_id="A-001"):
    return AuctionCsvRecord(
        auction_id, "https://example.com", "1", "Item", "Open", "Open", 60, True
    )


def test_operator_dropdown_is_resolved_only_inside_marketed_capacity_container():
    container = FakeFilterContainer()
    page = FakeFilterPage(container)

    PrismaAuctionFilter().apply(page, threading.Event())

    assert container.operator.selected_labels == ["Greater than or equal"]
    assert "combobox" not in page.global_role_calls
    assert page.other_filter_dropdown.selected_labels == []


def test_current_design_expands_filters_and_sets_marketed_lower_bound():
    page = CurrentFilterPage()

    PrismaAuctionFilter().apply(page, threading.Event())

    assert page.active_filter.clicks == 1
    assert page.marketed.filled_values == ["1000"]
    assert page.filter_button.clicks == 1


def test_value_input_is_resolved_only_inside_marketed_capacity_container():
    container = FakeFilterContainer()
    page = FakeFilterPage(container)

    PrismaAuctionFilter().apply(page, threading.Event())

    assert container.value_input.filled_values == ["1000"]
    assert not any(role in ("spinbutton", "textbox") for role in page.global_role_calls)


def test_missing_apply_is_not_treated_as_unverified_auto_apply():
    missing_apply = FakeLocator(wait_error=RuntimeError("not found"))
    container = FakeFilterContainer(apply_button=missing_apply)

    with pytest.raises(RuntimeError, match="Apply"):
        PrismaAuctionFilter().apply(FakeFilterPage(container), threading.Event())

    assert container.operator.selected_labels
    assert container.value_input.filled_values == ["1000"]


def test_apply_click_error_reports_failure_and_cleans_resources(monkeypatch):
    apply_button = FakeLocator(click_error=RuntimeError("click intercepted"))
    page = FakeFilterPage(FakeFilterContainer(apply_button=apply_button))
    browser = FakeBrowser(page)
    controller = BrowserController()
    playwright = install_fake_playwright(monkeypatch, lambda **kwargs: browser)

    controller.open()
    join_worker(controller)

    result = controller.get_launch_results()[0]
    assert not result.success
    assert "Apply" in result.error
    assert controller.state is BrowserState.IDLE
    assert browser.closed.is_set()
    assert playwright.stopped.is_set()


def test_cancellation_during_apply_does_not_report_failure(monkeypatch):
    controller = BrowserController()
    apply_button = FakeLocator(
        click_error=RuntimeError("cancelled click"), on_click=controller.stop
    )
    browser = FakeBrowser(FakeFilterPage(FakeFilterContainer(apply_button=apply_button)))
    playwright = install_fake_playwright(monkeypatch, lambda **kwargs: browser)

    controller.open()
    join_worker(controller)

    assert controller.get_launch_results() == []
    assert controller.last_error is None
    assert controller.state is BrowserState.IDLE
    assert browser.closed.is_set()
    assert playwright.stopped.is_set()


def test_successful_start_uses_system_default_browser_executable(monkeypatch):
    page_filter = FakePageFilter()
    controller = BrowserController(page_filter)
    controller._results = SignallingQueue()
    browser = FakeBrowser()
    launches = []
    playwright = install_fake_playwright(
        monkeypatch,
        lambda **kwargs: launches.append(kwargs) or browser,
    )

    generation = controller.open()
    assert controller._results.ready.wait(2)

    assert controller.state is BrowserState.RUNNING
    assert controller.is_running
    result = controller.get_launch_results()[0]
    assert result.generation == generation
    assert result.success
    assert launches == [{
        "executable_path": "C:\\Browsers\\default.exe",
        "headless": False,
        "args": ["--start-maximized"],
    }]
    assert browser.new_page_options == [{"no_viewport": True}]
    assert page_filter.pages == [browser.page]

    controller.stop()
    assert controller.state is BrowserState.STOPPING
    join_worker(controller)
    assert controller.state is BrowserState.IDLE
    assert not controller.is_running
    assert browser.closed.is_set()
    assert playwright.stopped.is_set()


def test_live_status_read_runs_on_browser_lifecycle_thread(monkeypatch):
    lifecycle_thread = []
    reader = Mock()
    reader.read_status.side_effect = lambda page, item: (
        lifecycle_thread.append(threading.current_thread()) or "Completed"
    )
    controller = BrowserController(FakePageFilter(), page_reader=reader)
    controller._results = SignallingQueue()
    browser = FakeBrowser()
    install_fake_playwright(monkeypatch, lambda **kwargs: browser)

    controller.open()
    assert controller._results.ready.wait(2)
    caller_thread = threading.current_thread()
    assert controller.read_live_auction_status(monitoring_record()) == "Completed"

    reader.read_status.assert_called_once_with(browser.page, monitoring_record())
    assert lifecycle_thread == [controller._thread]
    assert lifecycle_thread[0] is not caller_thread
    controller.stop()
    join_worker(controller)


def test_authentication_failure_is_typed_stoppable_and_uses_one_page(monkeypatch):
    logger = ListLogger()
    validator = Mock()
    validator.validate.side_effect = PrismaAuthenticationRequiredError(
        "PRISMA authentication is required; automatic monitoring cannot continue in the public session."
    )
    controller = BrowserController(
        FakePageFilter(), logger=logger, session_validator=validator
    )
    browser = FakeBrowser()
    install_fake_playwright(monkeypatch, lambda **kwargs: browser)

    generation = controller.open()
    join_worker(controller)

    result = controller.get_launch_results()[0]
    assert result.generation == generation and not result.success
    assert "authentication is required" in result.error
    assert controller.state is BrowserState.IDLE
    controller.stop()
    assert controller.state is BrowserState.IDLE
    assert browser.new_page_calls == 1
    assert browser.closed.is_set()
    assert any(
        f"generation={generation}" in message
        and "classification=authentication-required" in message
        for message in logger.messages
    )


def test_session_diagnostics_do_not_expose_sensitive_url_values(monkeypatch):
    logger = ListLogger()
    validator = Mock()
    validator.validate.return_value = PrismaSessionState(
        "public-auctions",
        "https://app.prisma-capacity.eu/reporting/auctions/short-and-long-term-auctions",
    )
    controller = BrowserController(
        FakePageFilter(), logger=logger, session_validator=validator
    )
    controller._results = SignallingQueue()
    browser = FakeBrowser()
    install_fake_playwright(monkeypatch, lambda **kwargs: browser)

    controller.open()
    assert controller._results.ready.wait(2)
    controller.stop()
    join_worker(controller)

    diagnostics = "\n".join(logger.messages).casefold()
    assert "classification=public-auctions" in diagnostics
    assert all(
        secret not in diagnostics
        for secret in ("password=representative", "token=representative", "cookie=representative")
    )


def test_live_status_read_requires_active_browser():
    controller = BrowserController(FakePageFilter())
    with pytest.raises(PrismaPageUnavailableError, match="not available"):
        controller.read_live_auction_status(monitoring_record())


def test_live_lookup_timeout_is_typed_stops_generation_and_allows_new_attempt():
    reader = Mock()
    reader.read_status.return_value = "Completed"
    controller = BrowserController(FakePageFilter(), page_reader=reader)
    controller._generation = 1
    controller._state = BrowserState.RUNNING
    controller._cancel_event = threading.Event()
    controller._page_requests = {1: queue.Queue()}

    with pytest.raises(PrismaLookupTimeoutError, match="timed out"):
        controller.read_live_auction_status(monitoring_record(), timeout_seconds=0.01)

    assert controller.state is BrowserState.STOPPING
    assert controller._cancel_event.is_set()
    timed_out_request = controller._page_requests[1].get_nowait()
    assert timed_out_request.abandoned

    controller._generation = 2
    controller._state = BrowserState.RUNNING
    controller._cancel_event = threading.Event()
    controller._page_requests[2] = queue.Queue()
    result = []
    worker = threading.Thread(target=lambda: result.append(
        controller.read_live_auction_status(monitoring_record("new"), 1)
    ))
    worker.start()
    while controller._page_requests[2].empty():
        threading.Event().wait(0.001)
    controller._process_page_requests(FakePage(), 2)
    worker.join(timeout=1)

    assert result == ["Completed"]
    assert controller.state is BrowserState.RUNNING


def test_page_already_closed_before_lookup_is_typed_and_stops_generation():
    page = FakePage()
    page.is_closed = lambda: True
    controller = BrowserController(FakePageFilter())
    controller._generation = 1
    controller._state = BrowserState.RUNNING
    controller._cancel_event = threading.Event()
    request = _PageRequest(1, monitoring_record(), threading.Event())
    requests = queue.Queue()
    requests.put(request)
    controller._page_requests = {1: requests}

    controller._process_page_requests(page, 1)

    assert isinstance(request.error, PrismaPageUnavailableError)
    assert request.completed.is_set()
    assert controller.state is BrowserState.STOPPING
    assert controller._cancel_event.is_set()


def test_stale_lifecycle_failure_cannot_stop_new_generation():
    controller = BrowserController(FakePageFilter())
    controller._generation = 2
    controller._state = BrowserState.RUNNING
    current_cancel = threading.Event()
    controller._cancel_event = current_cancel

    assert not controller._stop_generation(1, "stale-page-close")
    assert controller.state is BrowserState.RUNNING
    assert not current_cancel.is_set()


def test_old_generation_cleanup_does_not_affect_new_generation_requests():
    reader = Mock()
    reader.read_status.return_value = "Completed"
    controller = BrowserController(FakePageFilter(), page_reader=reader)
    old_queue = queue.Queue()
    new_queue = queue.Queue()
    old_request = _PageRequest(1, monitoring_record("old"), threading.Event())
    new_request = _PageRequest(2, monitoring_record("new"), threading.Event())
    old_queue.put(old_request)
    new_queue.put(new_request)
    controller._page_requests = {1: old_queue, 2: new_queue}

    controller._fail_pending_page_requests(1)

    assert old_request.completed.is_set()
    assert isinstance(old_request.error, PrismaPageUnavailableError)
    assert 1 not in controller._page_requests
    assert not new_request.completed.is_set()
    assert new_request.error is None
    assert controller._page_requests[2] is new_queue
    assert new_queue.qsize() == 1

    page = FakePage()
    controller._process_page_requests(page, 2)

    assert new_request.completed.is_set()
    assert new_request.error is None
    assert new_request.status == "Completed"
    assert new_queue.empty()
    reader.read_status.assert_called_once_with(page, new_request.record)


def test_windowed_runtime_supplies_output_handles_before_playwright_start(monkeypatch):
    controller = BrowserController(FakePageFilter())
    browser = FakeBrowser()
    streams_at_start = []
    playwright = FakePlaywright(lambda **kwargs: browser)

    def start():
        streams_at_start.append((sys.stdout, sys.stderr))
        return playwright

    monkeypatch.setitem(
        sys.modules,
        "playwright.sync_api",
        SimpleNamespace(sync_playwright=lambda: SimpleNamespace(start=start)),
    )
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)

    controller.open()
    while controller.state is BrowserState.STARTING:
        threading.Event().wait(0.01)

    assert len(streams_at_start) == 1
    assert all(stream is not None for stream in streams_at_start[0])
    assert all(stream.fileno() >= 0 for stream in streams_at_start[0])

    controller.stop()
    join_worker(controller)


def test_browser_creation_error_reports_failure_and_cleans_resources(monkeypatch):
    controller = BrowserController(FakePageFilter())

    def fail_launch(**kwargs):
        raise RuntimeError("driver missing")

    playwright = install_fake_playwright(monkeypatch, fail_launch)
    controller.open()
    join_worker(controller)

    result = controller.get_launch_results()[0]
    assert not result.success
    assert result.error == "driver missing"
    assert controller.last_error == "driver missing"
    assert controller.state is BrowserState.IDLE
    assert not controller.is_running
    assert playwright.stopped.is_set()


def test_browser_can_be_started_again_after_launch_error(monkeypatch):
    controller = BrowserController(FakePageFilter())
    successful_browser = FakeBrowser()
    attempts = 0

    def launch(**kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("driver missing")
        return successful_browser

    install_fake_playwright(monkeypatch, launch)

    first_generation = controller.open()
    join_worker(controller)
    first_result = controller.get_launch_results()[0]

    assert first_result == LaunchResult(first_generation, False, "driver missing")
    assert controller.state is BrowserState.IDLE

    controller._results = SignallingQueue()
    second_generation = controller.open()
    assert controller._results.ready.wait(2)
    second_result = controller.get_launch_results()[0]

    assert second_generation > first_generation
    assert second_result == LaunchResult(second_generation, True)
    assert controller.state is BrowserState.RUNNING
    assert controller.last_error is None

    controller.stop()
    join_worker(controller)


def test_navigation_error_reports_failure_and_closes_all_resources(monkeypatch):
    controller = BrowserController(FakePageFilter())
    browser = FakeBrowser(FakePage(RuntimeError("navigation failed")))
    playwright = install_fake_playwright(monkeypatch, lambda **kwargs: browser)

    controller.open()
    join_worker(controller)

    result = controller.get_launch_results()[0]
    assert not result.success
    assert result.error == "navigation failed"
    assert browser.closed.is_set()
    assert playwright.stopped.is_set()
    assert controller.state is BrowserState.IDLE


def test_page_creation_error_reports_failure_and_closes_all_resources(monkeypatch):
    controller = BrowserController(FakePageFilter())
    browser = FakeBrowser(new_page_error=RuntimeError("page creation failed"))
    playwright = install_fake_playwright(monkeypatch, lambda **kwargs: browser)

    generation = controller.open()
    join_worker(controller)

    assert controller.get_launch_results() == [
        LaunchResult(generation, False, "page creation failed")
    ]
    assert controller.last_error == "page creation failed"
    assert controller.state is BrowserState.IDLE
    assert not controller.is_running
    assert controller._browser is None
    assert controller._playwright is None
    assert controller._cancel_event is None
    assert browser.closed.is_set()
    assert playwright.stopped.is_set()


def test_stale_generation_completion_does_not_disturb_active_generation(monkeypatch):
    old_page_entered = threading.Event()
    release_old_page = threading.Event()
    new_page_entered = threading.Event()
    release_new_page = threading.Event()

    def block_old_page():
        old_page_entered.set()
        assert release_old_page.wait(2)

    def block_new_page():
        new_page_entered.set()
        assert release_new_page.wait(2)

    old_browser = FakeBrowser(
        new_page_error=RuntimeError("old failure"), new_page_block=block_old_page
    )
    new_browser = FakeBrowser(
        new_page_error=RuntimeError("new failure"), new_page_block=block_new_page
    )
    playwrights = iter(
        (
            FakePlaywright(lambda **kwargs: old_browser),
            FakePlaywright(lambda **kwargs: new_browser),
        )
    )
    api = SimpleNamespace(
        sync_playwright=lambda: SimpleNamespace(start=lambda: next(playwrights))
    )
    monkeypatch.setitem(sys.modules, "playwright.sync_api", api)
    controller = BrowserController(FakePageFilter())
    old_cancel = threading.Event()
    new_cancel = threading.Event()

    controller._generation = 1
    controller._state = BrowserState.STARTING
    old_thread = threading.Thread(
        target=controller._run, args=(1, old_cancel), daemon=True
    )
    old_thread.start()
    assert old_page_entered.wait(2)

    controller._generation = 2
    controller._cancel_event = new_cancel
    new_thread = threading.Thread(
        target=controller._run, args=(2, new_cancel), daemon=True
    )
    controller._thread = new_thread
    new_thread.start()
    assert new_page_entered.wait(2)

    release_old_page.set()
    old_thread.join(timeout=2)
    assert not old_thread.is_alive()
    assert controller.state is BrowserState.STARTING
    assert controller._generation == 2
    assert controller._browser is new_browser
    assert controller._cancel_event is new_cancel
    assert controller.get_launch_results() == []

    release_new_page.set()
    new_thread.join(timeout=2)
    assert not new_thread.is_alive()
    assert controller.get_launch_results() == [
        LaunchResult(2, False, "new failure")
    ]
    assert controller.last_error == "new failure"
    assert controller.state is BrowserState.IDLE
    assert old_browser.closed.is_set()
    assert new_browser.closed.is_set()


def test_open_twice_is_rejected_while_starting(monkeypatch):
    controller = BrowserController(FakePageFilter())
    launch_entered = threading.Event()
    release_launch = threading.Event()

    def blocked_launch(**kwargs):
        launch_entered.set()
        assert release_launch.wait(2)
        return FakeBrowser()

    install_fake_playwright(monkeypatch, blocked_launch)
    controller.open()
    assert launch_entered.wait(2)
    assert controller.state is BrowserState.STARTING

    with pytest.raises(RuntimeError):
        controller.open()

    controller.stop()
    release_launch.set()
    join_worker(controller)


def test_stop_during_startup_suppresses_success_and_cleans_resources(monkeypatch):
    controller = BrowserController(FakePageFilter())
    launch_entered = threading.Event()
    release_launch = threading.Event()
    browser = FakeBrowser()

    def blocked_launch(**kwargs):
        launch_entered.set()
        assert release_launch.wait(2)
        return browser

    playwright = install_fake_playwright(monkeypatch, blocked_launch)
    controller.open()
    assert launch_entered.wait(2)

    controller.stop()
    assert controller.state is BrowserState.STOPPING
    release_launch.set()
    join_worker(controller)

    assert controller.get_launch_results() == []
    assert controller.state is BrowserState.IDLE
    assert not controller.is_running
    assert browser.closed.is_set()
    assert playwright.stopped.is_set()


def test_filter_error_reports_clear_failure_and_returns_to_idle(monkeypatch):
    page_filter = FakePageFilter(RuntimeError("input field not found"))
    controller = BrowserController(page_filter)
    browser = FakeBrowser()
    install_fake_playwright(monkeypatch, lambda **kwargs: browser)

    controller.open()
    join_worker(controller)

    result = controller.get_launch_results()[0]
    assert not result.success
    assert "Marketed >= 1000" in result.error
    assert "input field not found" in result.error
    assert controller.last_error == result.error
    assert controller.state is BrowserState.IDLE
    assert browser.closed.is_set()


def test_stop_while_filter_is_configured_does_not_report_filter_failure(monkeypatch):
    filter_entered = threading.Event()
    release_filter = threading.Event()

    def blocked_filter(cancel_event):
        filter_entered.set()
        assert release_filter.wait(2)
        assert cancel_event.is_set()

    controller = BrowserController(FakePageFilter(block=blocked_filter))
    browser = FakeBrowser()
    install_fake_playwright(monkeypatch, lambda **kwargs: browser)

    controller.open()
    assert filter_entered.wait(2)
    assert controller.state is BrowserState.STARTING
    controller.stop()
    release_filter.set()
    join_worker(controller)

    assert controller.get_launch_results() == []
    assert controller.last_error is None
    assert controller.state is BrowserState.IDLE


def test_lifecycle_events_distinguish_unexpected_and_requested_shutdown(monkeypatch):
    logger = ListLogger()
    page = EventPage()
    browser = EventBrowser(page)
    controller = BrowserController(FakePageFilter(), logger=logger)
    controller._results = SignallingQueue()
    install_fake_playwright(monkeypatch, lambda **kwargs: browser)

    controller.open()
    assert controller._results.ready.wait(2)
    page.emit("crash")
    browser.emit("disconnected")
    assert any("Page crash event" in message and "classification=unexpected" in message for message in logger.messages)
    assert any("Browser disconnected event" in message and "classification=unexpected" in message for message in logger.messages)

    join_worker(controller)
    results = controller.get_launch_results()
    assert results[-1] == LaunchResult(
        1, False, "The managed PRISMA page or browser was closed.", "closed"
    )

    controller.stop()
    assert any("Page close event" in message for message in logger.messages)
    assert any("Context close event" in message for message in logger.messages)


def test_repeated_launches_remove_handlers_and_do_not_duplicate_events(monkeypatch):
    logger = ListLogger()
    page = EventPage()
    browser = EventBrowser(page)
    controller = BrowserController(FakePageFilter(), logger=logger)
    install_fake_playwright(monkeypatch, lambda **kwargs: browser)

    for _ in range(2):
        controller._results = SignallingQueue()
        controller.open()
        assert controller._results.ready.wait(2)
        page.emit("crash")
        controller.stop()
        join_worker(controller)
        assert all(not callbacks for callbacks in browser.listeners.values())
        assert all(not callbacks for callbacks in page.listeners.values())
        assert all(not callbacks for callbacks in page.context.listeners.values())

    crashes = [message for message in logger.messages if "Page crash event" in message]
    assert len(crashes) == 2
    assert "generation=1" in crashes[0]
    assert "generation=2" in crashes[1]


def test_logging_failure_does_not_break_startup_or_cleanup(monkeypatch):
    browser = FakeBrowser()
    controller = BrowserController(FakePageFilter(), logger=ListLogger(fail=True))
    controller._results = SignallingQueue()
    playwright = install_fake_playwright(monkeypatch, lambda **kwargs: browser)

    controller.open()
    assert controller._results.ready.wait(2)
    controller.stop()
    join_worker(controller)

    assert controller.state is BrowserState.IDLE
    assert browser.closed.is_set()
    assert playwright.stopped.is_set()
