import os
import threading
import time
from datetime import date
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QDate, QUrl
from PySide6.QtGui import QCloseEvent
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication, QMessageBox

import app
from mini_ui import MiniUiState, MiniUiStateModel, MiniWorkCancelled, validate_date_range
from runtime_paths import RuntimePaths
from version import APP_DISPLAY_NAME, __version__


@pytest.fixture(scope="session")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def paths(tmp_path):
    root = tmp_path / "runtime"
    return RuntimePaths(
        root=root,
        database=root / "data/test.db",
        result=root / "data/result/test.csv",
        state=root / "state/test.json",
        log=root / "logs/test.log",
        temporary_downloads=root / "temporary-downloads",
    )


@pytest.fixture
def window(qt_app, paths):
    widget = app.MiniMainWindow(paths)
    yield widget
    worker = widget._worker
    if worker is not None and worker.is_alive():
        widget.cancel_work()
        worker.join(timeout=2)
    widget.close()


def wait_until(qt_app, predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qt_app.processEvents()
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("Timed out waiting for UI state")


def test_initial_window_is_minimal_and_truthful(window):
    assert window.windowTitle() == f"{APP_DISPLAY_NAME} v{__version__}"
    assert window.state is MiniUiState.IDLE
    assert window.status_label.text() == "Ready. Select a date range."
    assert window.start_button.text() == "Start"
    assert window.cancel_button.text() == "Cancel"
    assert window.open_result_button.text() == "Open Result"
    assert window.start_date.displayFormat() == "yyyy-MM-dd"
    assert window.end_date.displayFormat() == "yyyy-MM-dd"
    assert window.start_button.isEnabled()
    assert not window.cancel_button.isEnabled()
    assert not window.open_result_button.isEnabled()
    assert not hasattr(window, "start_monitoring_button")


@pytest.mark.parametrize(
    ("start", "end", "message"),
    [
        (date(2026, 7, 2), date(2026, 7, 1), "Start date must not be later than end date."),
        (date(2026, 7, 1), date(2026, 7, 3), "Future dates are not supported."),
    ],
)
def test_date_validation_rejects_invalid_ranges_before_worker(start, end, message):
    result = validate_date_range(start, end, today=date(2026, 7, 2))
    assert result.date_range is None
    assert result.error == message


def test_invalid_dates_do_not_start_background_work(window):
    today = date.today()
    window.start_date.setDate(QDate(today.year, today.month, today.day).addDays(1))
    window.end_date.setDate(QDate(today.year, today.month, today.day).addDays(1))
    window.start_work()
    assert window.state is MiniUiState.ERROR
    assert window.status_label.text() == "Future dates are not supported."
    assert window._worker is None


def test_state_model_disables_unavailable_actions_truthfully():
    model = MiniUiStateModel()
    assert model.action_policy(False) == app.MiniUiStateModel().action_policy(False)
    model.transition(MiniUiState.PROCESSING, "Processing…")
    policy = model.action_policy(True)
    assert not policy.dates_enabled
    assert not policy.start_enabled
    assert policy.cancel_enabled
    assert not policy.open_result_enabled
    model.transition(MiniUiState.CANCELLING, "Cancelling…")
    assert not model.action_policy(True).cancel_enabled


def test_worker_progress_and_completion_arrive_through_qt_signals(qt_app, paths):
    worker_thread = []

    def runner(request, cancel_event, progress):
        worker_thread.append(threading.current_thread())
        assert request.date_range.start <= request.date_range.end
        assert not cancel_event.is_set()
        progress(MiniUiState.DOWNLOADING, "Downloading…")
        progress(MiniUiState.PROCESSING, "Processing…")
        paths.result.parent.mkdir(parents=True)
        paths.result.write_bytes(b"result")
        return paths.result

    window = app.MiniMainWindow(paths, work_runner=runner)
    progress_spy = QSignalSpy(window.signals.progress)
    finished_spy = QSignalSpy(window.signals.finished)
    window.start_work()
    assert window.state is MiniUiState.OPENING_PRISMA
    assert not window.start_button.isEnabled()
    assert window.cancel_button.isEnabled()
    wait_until(qt_app, lambda: window.state is MiniUiState.COMPLETED)
    assert len(worker_thread) == 1
    assert worker_thread[0] is not threading.current_thread()
    assert progress_spy.count() == 2
    assert finished_spy.count() == 1
    assert window.open_result_button.isEnabled()
    window.close()


def test_cancel_is_cooperative_and_restores_ready_state(qt_app, paths):
    entered = threading.Event()

    def runner(request, cancel_event, progress):
        del request
        progress(MiniUiState.PROCESSING, "Processing…")
        entered.set()
        if cancel_event.wait(2):
            raise MiniWorkCancelled
        raise AssertionError("Cancellation was not delivered")

    window = app.MiniMainWindow(paths, work_runner=runner)
    window.start_work()
    assert entered.wait(1)
    window.cancel_work()
    assert window.state is MiniUiState.CANCELLING
    assert not window.cancel_button.isEnabled()
    wait_until(qt_app, lambda: window.state is MiniUiState.IDLE)
    assert window.status_label.text() == "Cancelled. Ready to start."
    assert window.start_button.isEnabled()
    window.close()


def test_stale_worker_messages_cannot_overwrite_current_state(window):
    window._generation = 2
    window._on_progress(MiniUiState.PROCESSING, "stale", 1)
    assert window.state is MiniUiState.IDLE


def test_open_result_uses_existing_runtime_csv(window, monkeypatch, paths):
    paths.result.parent.mkdir(parents=True)
    paths.result.write_bytes(b"result")
    window._render_state()
    opened = Mock(return_value=True)
    monkeypatch.setattr(app.QDesktopServices, "openUrl", opened)
    window.open_result_button.click()
    opened.assert_called_once_with(QUrl.fromLocalFile(str(paths.result)))


def test_close_requests_cancellation_and_waits_for_worker(qt_app, paths):
    release = threading.Event()

    def runner(request, cancel_event, progress):
        del request, progress
        cancel_event.wait(1)
        release.wait(1)
        raise MiniWorkCancelled

    window = app.MiniMainWindow(paths, work_runner=runner)
    window.start_work()
    event = Mock(spec=QCloseEvent)
    window.closeEvent(event)
    event.ignore.assert_called_once()
    assert window._shutdown_requested
    assert window._cancel_event.is_set()
    release.set()
    wait_until(qt_app, lambda: window._worker is None)
    final_event = Mock(spec=QCloseEvent)
    window.closeEvent(final_event)
    final_event.accept.assert_called_once()
    window.close()


def test_default_m7_runner_reports_unavailable_without_browser_work(qt_app, window):
    window.start_work()
    wait_until(qt_app, lambda: window.state is MiniUiState.ERROR)
    assert window.status_label.text() == "Processing is not available in this version yet."


def test_main_reports_runtime_initialization_failure(qt_app, monkeypatch, paths):
    monkeypatch.setattr(app.QApplication, "instance", Mock(return_value=qt_app))
    monkeypatch.setattr(app, "runtime_paths", Mock(return_value=paths))
    monkeypatch.setattr(app, "initialize_runtime_logging", Mock(return_value=(Mock(), None)))
    prepare = Mock()
    message = Mock()
    monkeypatch.setattr(app, "prepare_runtime_directories", prepare)
    monkeypatch.setattr(QMessageBox, "critical", message)
    assert app.main() == 1
    prepare.assert_not_called()
    assert "required user-data log file could not be created" in message.call_args.args[2]
