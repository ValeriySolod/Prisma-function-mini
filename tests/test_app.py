import os
import threading
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QWidget

import app
from auction_csv import AuctionCsvRecord
from browser import LaunchResult
from monitoring import MonitoringResult
from monitoring_storage import MonitoringStorage, MonitoringStorageError
from prisma_page import (
    LivePrismaStatusAdapter,
    PrismaAuctionNotFoundError,
    PrismaLookupTimeoutError,
    PrismaPageStructureError,
    PrismaPageUnavailableError,
)
from prisma_import_workflow import PrismaWorkflowResult
from prisma_source_updates import SourceUpdateStatus
from version import APP_DISPLAY_NAME, __version__
from ui_components import APP_STYLE, ArrowComboBox


@pytest.fixture(scope="session")
def qt_app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qt_app, monkeypatch, tmp_path):
    browser = Mock()
    monkeypatch.setattr(app, "BrowserController", Mock(return_value=browser))
    root = tmp_path / "runtime"
    paths = app.RuntimePaths(
        root=root, database=root / "data/test.db",
        result=root / "data/result/test.xlsx",
        state=root / "state/test.json", log=root / "logs/test.log",
    )
    widget = app.PrismaMonitorApp(paths)
    yield widget, browser
    widget._is_closing = True
    widget._monitoring_thread = None
    for worker in widget._processing_threads:
        worker.join(timeout=2)
    widget._processing_threads.clear()
    widget.close()


def record(
    auction_id: str = "A1",
    enabled: bool = True,
    item_name: str = "Item",
    status: str = "Scheduled",
) -> AuctionCsvRecord:
    return AuctionCsvRecord(
        auction_id,
        "https://example.com",
        "L1",
        item_name,
        "Open",
        status,
        30,
        enabled,
    )


def result(
    auction_id: str,
    status: str,
    result_name: str = "Changed",
) -> MonitoringResult:
    return MonitoringResult(
        auction_id,
        datetime(2026, 1, 2, 3, 4, 5),
        "Scheduled",
        status,
        True,
        result_name,
        "failure" if result_name == "Error" else "",
    )


def make_ready(widget: app.PrismaMonitorApp) -> None:
    widget._browser_ready = True
    widget._active_browser_launch = 7
    widget._update_controls()


def test_initial_dashboard_state_and_accessibility(window):
    widget, _ = window
    assert widget.windowTitle() == f"{APP_DISPLAY_NAME} v{__version__}"
    assert widget.minimumWidth() >= 1080
    assert widget.status.text() == "Ready"
    assert widget.browser_badge.text() == "Disconnected"
    assert widget.load_csv_button.text() == "Load Monitoring CSV"
    assert not widget.start_monitoring_button.isEnabled()
    assert widget.csv_table.accessibleName() == "Auctions"
    assert [
        widget.summary_cards[key].value.text()
        for key in ("total", "active", "completed", "errors")
    ] == ["0", "0", "0", "0"]


def test_light_workspace_widgets_use_explicit_contrast_styles(window):
    widget, _ = window
    content = widget.findChild(QWidget, "contentArea")
    subtitle = widget.findChild(QLabel, "dashboardSubtitle")
    section_labels = widget.findChildren(QLabel, "contentSectionLabel")

    assert content is not None
    assert subtitle is not None
    assert {label.text() for label in section_labels} == {"Recent activity", "Status:"}
    assert widget.activity_list.objectName() == "activityList"
    assert widget.status_filter.currentText() == "All statuses"

    required_rules = (
        "QWidget#contentArea QLabel { color: #243247; }",
        "QLabel#dashboardSubtitle { color: #66758a; }",
        "QLabel#contentSectionLabel { color: #314157; font-weight: 600; }",
        "placeholder-text-color: #718096;",
        "QLineEdit:disabled, QComboBox:disabled",
        "QComboBox::drop-down",
        "QComboBox QAbstractItemView",
        "QListWidget { border: none; background: white; color: #243247;",
        "QListWidget::item { color: #243247;",
    )
    for rule in required_rules:
        assert rule in APP_STYLE

    assert "QFrame#sidebar QLabel { color: #d8e1ee; }" in APP_STYLE
    assert "QLabel#browserBadge, QLabel#monitorBadge" in APP_STYLE


def test_status_filter_uses_packaging_safe_custom_arrow(window):
    widget, _ = window

    assert isinstance(widget.status_filter, ArrowComboBox)
    assert widget.status_filter.property("arrowImplementation") == "custom-paint"
    assert "QComboBox::down-arrow" not in APP_STYLE
    assert widget.status_filter.accessibleName() == "Filter by status"


def test_ordinary_table_cells_keep_model_text_and_explicit_contrast(window):
    widget, _ = window
    widget.table_model.set_records(
        [record("AUCTION-42", item_name="North Market", status="Scheduled")]
    )

    expected = ("AUCTION-42", "L1", "North Market", "Open")
    for column, text in enumerate(expected):
        index = widget.table_model.index(0, column)
        assert index.data(Qt.DisplayRole) == text
        assert index.data(Qt.AccessibleTextRole) == text

    required_rules = (
        "QWidget#contentArea QTableView { border: none; background: white; color: #243247;",
        "QWidget#contentArea QTableView::item { color: #243247; }",
        "QWidget#contentArea QTableView::item:hover",
        "QWidget#contentArea QTableView::item:selected { background: #dff3f8; color: #172235; }",
        "QWidget#contentArea QTableView::item:selected:hover",
        "QWidget#contentArea QTableView:focus { color: #243247; }",
        "QWidget#contentArea QTableView:disabled",
        "QWidget#contentArea QTableView::item:disabled",
    )
    for rule in required_rules:
        assert rule in APP_STYLE


def test_cancel_csv_dialog_preserves_state(window, monkeypatch):
    widget, _ = window
    dialog = Mock(return_value=("", ""))
    monkeypatch.setattr(app.QFileDialog, "getOpenFileName", dialog)
    load = Mock()
    monkeypatch.setattr(app, "load_auction_csv", load)

    widget.select_csv()

    assert dialog.call_args.args[1] == "Load Monitoring CSV"
    load.assert_not_called()
    assert widget.csv_path.text() == ""


def test_csv_loading_populates_model_counters_and_activity(window, monkeypatch):
    widget, _ = window
    monkeypatch.setattr(
        app.QFileDialog,
        "getOpenFileName",
        Mock(return_value=("C:/data/Auction_overview.csv", "CSV")),
    )
    monkeypatch.setattr(
        app,
        "load_auction_csv",
        Mock(return_value=[record(), record("A2", False, "Second", "Completed")]),
    )

    widget.select_csv()

    assert widget.table_model.rowCount() == 2
    assert widget.csv_filename.text() == "Auction_overview.csv"
    assert widget.summary_cards["total"].value.text() == "2"
    assert widget.summary_cards["completed"].value.text() == "0"
    assert "CSV loaded" in widget.activity_list.item(0).text()
    assert not widget.start_monitoring_button.isEnabled()


def test_summary_semantics_are_truthful_and_disjoint(window):
    widget, _ = window
    widget.table_model.set_records(
        [
            record("DISABLED-SCHEDULED", enabled=False, status="Scheduled"),
            record("DISABLED-COMPLETED", enabled=False, status="Completed"),
            record("DISABLED-ERROR", enabled=False, status="Scheduled"),
            record("ENABLED-COMPLETED", status="Completed"),
            record("ENABLED-CANCELLED", status="Cancelled"),
            record("CANCELLED-ERROR", status="Cancelled"),
            record("ENABLED-ACTIVE", status="Open"),
            record("ENABLED-ERROR", status="Error"),
        ]
    )
    widget.table_model.apply_result(
        result("DISABLED-ERROR", "Scheduled", "Error")
    )
    widget.table_model.apply_result(
        result("CANCELLED-ERROR", "Cancelled", "Error")
    )

    assert widget.table_model.counts() == {
        "total": 8,
        "active": 1,
        "completed": 1,
        "errors": 2,
    }


def test_invalid_csv_has_clear_error_and_preserves_selection(window, monkeypatch):
    widget, _ = window
    widget.csv_path.setText("existing.csv")
    monkeypatch.setattr(
        app.QFileDialog, "getOpenFileName", Mock(return_value=("bad.csv", "CSV"))
    )
    monkeypatch.setattr(
        app,
        "load_auction_csv",
        Mock(side_effect=app.CsvValidationError("bad data")),
    )
    critical = Mock()
    monkeypatch.setattr(QMessageBox, "critical", critical)

    widget.select_csv()

    critical.assert_called_once_with(widget, "CSV Error", "bad data")
    assert widget.csv_path.text() == "existing.csv"


def test_successful_browser_result_is_polled_on_gui_thread(window, monkeypatch):
    widget, browser = window
    browser.open.return_value = 7
    browser.get_launch_results.return_value = [LaunchResult(7, True)]
    monkeypatch.setattr(widget._browser_timer, "start", Mock())
    monkeypatch.setattr(widget._browser_timer, "stop", Mock())

    widget.open_prisma()
    widget._poll_browser_launch()

    assert widget._browser_ready
    assert widget.browser_badge.text() == "Ready"
    assert widget.status.text() == "PRISMA browser session is ready"
    assert not widget.open_button.isEnabled()


def test_stale_browser_result_does_not_change_dashboard(window, monkeypatch):
    widget, browser = window
    browser.open.return_value = 7
    browser.get_launch_results.return_value = [LaunchResult(6, True)]
    monkeypatch.setattr(widget._browser_timer, "start", Mock())

    widget.open_prisma()
    widget._poll_browser_launch()

    assert not widget._browser_ready
    assert widget.browser_badge.text() == "Opening"


def test_managed_browser_closure_stops_monitoring_and_restores_retry(window):
    widget, browser = window
    make_ready(widget)
    stop_event = threading.Event()
    widget._monitoring_stop_event = stop_event
    widget._monitoring_thread = Mock()
    browser.get_launch_results.return_value = [
        LaunchResult(7, False, "managed browser closed", "closed")
    ]

    widget._poll_browser_launch()

    assert stop_event.is_set()
    assert not widget._browser_ready
    assert widget.open_button.isEnabled()
    assert not widget.start_monitoring_button.isEnabled()
    assert "Open it again to retry" in widget.status.text()


def test_browser_launch_failure_recovers_retry_controls(window, monkeypatch):
    widget, browser = window
    browser.open.return_value = 7
    browser.get_launch_results.return_value = [
        LaunchResult(7, False, "diagnostic detail", "launch")
    ]
    monkeypatch.setattr(widget._browser_timer, "start", Mock())
    critical = Mock()
    monkeypatch.setattr(QMessageBox, "critical", critical)

    widget.open_prisma()
    widget._poll_browser_launch()

    assert widget.open_button.isEnabled()
    assert not widget.stop_browser_button.isEnabled()
    assert widget.browser_badge.text() == "Error"
    critical.assert_called_once()
    assert "diagnostic detail" not in critical.call_args.args[2]


def test_search_and_status_changes_refresh_visible_rows_immediately(window):
    widget, _ = window
    widget.table_model.set_records(
        [
            record("ALPHA", item_name="North"),
            record("BETA", item_name="South", status="Completed"),
        ]
    )

    widget.search_box.setText("north")
    assert widget.proxy_model.rowCount() == 1
    assert widget.proxy_model.index(0, 0).data() == "ALPHA"

    widget.search_box.clear()
    widget.status_filter.setCurrentText("Completed")
    assert widget.proxy_model.rowCount() == 1
    assert widget.proxy_model.index(0, 0).data() == "BETA"


def test_result_update_is_correct_while_proxy_is_sorted_and_filtered(window):
    widget, _ = window
    widget.table_model.set_records([record("BETA"), record("ALPHA")])
    widget.csv_table.sortByColumn(0, Qt.DescendingOrder)
    widget.status_filter.setCurrentText("Completed")
    reset = Mock()
    widget.table_model.modelReset.connect(reset)

    widget._monitoring_results([result("ALPHA", "Completed")])

    reset.assert_not_called()
    assert widget.proxy_model.rowCount() == 1
    assert widget.proxy_model.index(0, 0).data() == "ALPHA"
    source_row = widget.table_model._row_by_id["ALPHA"]
    assert widget.table_model.index(source_row, 4).data() == "Completed"
    assert widget.summary_cards["completed"].value.text() == "1"


def test_monitoring_results_add_ordered_notifications_and_one_cycle_summary(window):
    widget, _ = window
    widget.clear_activity()
    widget.table_model.set_records([record("ALPHA"), record("BETA")])

    widget._monitoring_results(
        [result("ALPHA", "Open"), result("BETA", "Completed")]
    )

    assert widget.activity_list.count() == 3
    texts = [widget.activity_list.item(index).text() for index in range(3)]
    assert "Statuses updated: 2 checked, 2 changed, 0 errors" in texts[0]
    assert "Status change — Auction ALPHA: Scheduled → Open" in texts[1]
    assert "Status change — Auction BETA: Scheduled → Completed" in texts[2]
    assert sum("Statuses updated:" in text for text in texts) == 1
    notification = widget.activity_list.item(1)
    assert notification.data(Qt.UserRole) == app.ActivityKind.STATUS_CHANGE.value
    assert notification.font().bold()
    assert notification.data(Qt.AccessibleDescriptionRole) == (
        "Status change notification. Auction ALPHA: Scheduled → Open"
    )


def test_monitoring_results_exclude_non_notifications_but_keep_summary(window):
    widget, _ = window
    widget.clear_activity()
    widget.table_model.set_records([record("A1")])
    candidates = [
        MonitoringResult("A1", datetime.now(), "Scheduled", "Scheduled", False,
                         "Success", ""),
        MonitoringResult("A1", datetime.now(), "", "Open", False,
                         "Success", ""),
        MonitoringResult("A1", datetime.now(), "Scheduled", "Scheduled", False,
                         "Skipped", ""),
        MonitoringResult("A1", datetime.now(), "Scheduled", "Scheduled", False,
                         "Error", "lookup failed"),
    ]

    widget._monitoring_results(candidates)

    assert widget.activity_list.count() == 1
    assert "Statuses updated: 4 checked, 0 changed, 1 errors" in (
        widget.activity_list.item(0).text()
    )


def test_monitoring_result_signal_delivers_notifications_on_qt_thread(window, qt_app):
    widget, _ = window
    widget.clear_activity()
    widget.table_model.set_records([record("A1")])

    widget.signals.monitoring_results.emit([result("A1", "Open")])
    qt_app.processEvents()

    assert widget.activity_list.count() == 2
    assert "Status change — Auction A1: Scheduled → Open" in (
        widget.activity_list.item(1).text()
    )


def test_activity_history_bounds_notifications_and_ordinary_entries(window):
    widget, _ = window
    widget.clear_activity()
    for index in range(49):
        widget._add_activity(f"Ordinary {index}")
    widget.table_model.set_records([record("A1")])

    widget._monitoring_results([result("A1", "Open")])

    assert widget.activity_list.count() == 50
    assert "Statuses updated:" in widget.activity_list.item(0).text()
    assert "Status change — Auction A1" in widget.activity_list.item(1).text()


def test_model_rejects_duplicate_auction_ids(window):
    widget, _ = window
    with pytest.raises(ValueError, match="unique"):
        widget.table_model.set_records([record("SAME"), record("SAME")])


@pytest.mark.parametrize(
    ("has_records", "browser_ready"), [(False, False), (True, False), (False, True)]
)
def test_monitoring_cannot_start_without_all_prerequisites(
    window, monkeypatch, has_records, browser_ready
):
    widget, _ = window
    widget._auction_records = [record()] if has_records else []
    widget._browser_ready = browser_ready
    critical = Mock()
    monkeypatch.setattr(QMessageBox, "critical", critical)

    widget.start_monitoring()

    critical.assert_called_once_with(
        widget,
        "Monitoring Error",
        "Open the browser and load a CSV with enabled auctions first.",
    )
    assert widget._monitoring_thread is None


def test_monitoring_enablement_and_duplicate_prevention(window, monkeypatch):
    widget, _ = window
    widget._auction_records = [record()]
    make_ready(widget)
    widget._update_controls()
    monkeypatch.setattr(
        widget, "create_monitoring_scheduler", Mock(return_value=Mock())
    )
    created = []

    class FakeThread:
        def __init__(self, **kwargs):
            created.append(self)

        def start(self) -> None:
            pass

        def is_alive(self) -> bool:
            return False

    monkeypatch.setattr(app.threading, "Thread", FakeThread)

    widget.start_monitoring()
    widget.start_monitoring()

    assert len(created) == 1
    assert widget.stop_monitoring_button.isEnabled()
    event = widget._monitoring_stop_event
    widget.stop_monitoring()
    assert event.is_set()


def test_monitoring_worker_delivers_completion_only_through_signals(window):
    widget, _ = window
    scheduler = Mock()
    finished = QSignalSpy(widget.signals.monitoring_finished)
    widget.signals.monitoring_finished.disconnect(widget._monitoring_finished)
    widget.signals.monitoring_results.disconnect(widget._monitoring_results)
    original_status = widget.status.text()
    stop_event = threading.Event()

    widget._monitoring_worker(scheduler, stop_event)

    scheduler.run_forever.assert_called_once_with(
        stop_event,
        app.DEFAULT_MONITORING_INTERVAL_SECONDS,
        widget.signals.monitoring_results.emit,
    )
    assert finished.count() == 1
    assert finished.at(0) == [None]
    assert widget.status.text() == original_status
    widget.signals.monitoring_finished.connect(widget._monitoring_finished)
    widget.signals.monitoring_results.connect(widget._monitoring_results)


def test_monitoring_completion_restores_idle_state(window):
    widget, _ = window
    widget._auction_records = [record()]
    make_ready(widget)
    widget._monitoring_thread = Mock()
    widget._monitoring_stop_event = threading.Event()

    widget._monitoring_finished(None)

    assert widget._monitoring_thread is None
    assert widget._monitoring_stop_event is None
    assert widget.monitor_badge.text() == "Monitoring idle"
    assert widget.start_monitoring_button.isEnabled()
    assert not widget.stop_monitoring_button.isEnabled()
    assert widget.status.text() == "Monitoring stopped"


def test_default_monitoring_engine_uses_live_browser_adapter(window):
    widget, browser = window
    engine = widget.create_monitoring_engine()
    assert isinstance(engine._status_checker, LivePrismaStatusAdapter)
    assert engine._status_checker._browser_controller is browser
    assert isinstance(engine._persistence, MonitoringStorage)
    assert engine._persistence.database_path == widget._runtime_paths.database


def test_persistence_failure_stops_worker_before_result_emission(window):
    widget, _ = window
    failure = MonitoringStorageError("diagnostic detail")
    scheduler = Mock()
    scheduler.run_forever.side_effect = failure
    results = QSignalSpy(widget.signals.monitoring_results)
    finished = QSignalSpy(widget.signals.monitoring_finished)
    widget.signals.monitoring_results.disconnect(widget._monitoring_results)
    widget.signals.monitoring_finished.disconnect(widget._monitoring_finished)

    widget._monitoring_worker(scheduler, threading.Event())

    assert results.count() == 0
    assert finished.at(0) == [failure]
    assert widget._monitoring_failure_message(failure) == (
        "Monitoring history could not be saved. Please retry."
    )
    widget.signals.monitoring_results.connect(widget._monitoring_results)
    widget.signals.monitoring_finished.connect(widget._monitoring_finished)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (PrismaLookupTimeoutError("raw timeout"), "timed out"),
        (PrismaPageUnavailableError("raw page"), "unavailable or closed"),
        (PrismaPageStructureError("raw selector"), "structure could not be read"),
        (PrismaAuctionNotFoundError("Auction A1 was not found."), "not found"),
    ],
)
def test_known_monitoring_failure_messages_are_actionable(error, expected):
    message = app.PrismaMonitorApp._monitoring_failure_message(error)
    assert expected in message
    assert "raw" not in message


def test_processing_success_preserves_full_statistics(window, monkeypatch):
    widget, _ = window
    workflow_result = PrismaWorkflowResult(
        4, 1, 2, 1, 0, 0, (), Path("result.xlsx"),
        SourceUpdateStatus.APPLIED, "accepted",
    )
    monkeypatch.setattr(
        app, "run_prisma_import_workflow", Mock(return_value=workflow_result)
    )
    monkeypatch.setattr(
        app.QFileDialog, "getOpenFileName", Mock(return_value=("input.csv", "CSV"))
    )

    finished = QSignalSpy(widget.signals.processing_finished)
    widget.start_processing()
    assert finished.count() == 1 or finished.wait(2000)
    QApplication.processEvents()

    assert finished.count() == 1
    outcome = finished.at(0)[0]
    assert outcome.result is workflow_result
    assert outcome.error is None
    assert widget.status.text() == (
        "accepted Processed: 4; inserted: 1; updated: 2; unchanged: 1; "
        "filtered: 0; rejected: 0; audit issues: 0. Output: result.xlsx"
    )
    assert "PRISMA import completed" in widget.activity_list.item(0).text()
    assert not widget._processing_active
    assert widget._active_processing_thread is None
    assert not widget._processing_threads
    assert widget.process_button.isEnabled()

    widget._processing_finished(app.ProcessingOutcome(workflow_result, None, 0))
    assert widget.status.text().startswith("accepted Processed: 4")


def test_import_processing_success_and_error_restore_controls(window, monkeypatch):
    widget, _ = window
    monkeypatch.setattr(QMessageBox, "critical", Mock())
    monkeypatch.setattr(
        app.QFileDialog, "getOpenFileName", Mock(return_value=("export.csv", "CSV"))
    )

    class FakeThread:
        def __init__(self, **kwargs): self.kwargs = kwargs
        def start(self): pass
        def is_alive(self): return False

    monkeypatch.setattr(app.threading, "Thread", FakeThread)
    widget.start_processing()
    assert widget._processing_active
    assert not widget.process_button.isEnabled()
    assert "Importing" in widget.status.text()

    widget._processing_failed("Unsupported CSV format.", None)
    assert not widget._processing_active
    assert widget.process_button.isEnabled()
    assert "Unsupported CSV format" in widget.status.text()


def test_monitoring_load_remains_independent_from_prisma_import(window, monkeypatch):
    widget, _ = window
    monkeypatch.setattr(
        app.QFileDialog, "getOpenFileName", Mock(return_value=("monitoring.csv", "CSV"))
    )
    loader = Mock(return_value=[record()])
    monkeypatch.setattr(app, "load_auction_csv", loader)
    workflow = Mock()
    monkeypatch.setattr(app, "run_prisma_import_workflow", workflow)

    widget.select_csv()

    loader.assert_called_once_with("monitoring.csv")
    workflow.assert_not_called()
    assert widget.table_model.rowCount() == 1


def test_clear_activity_does_not_touch_logs(window):
    widget, _ = window
    widget._add_activity("Something")
    widget.clear_activity()
    assert widget.activity_list.count() == 0


def test_close_defers_without_blocking_until_live_workers_finish(window, monkeypatch):
    widget, browser = window
    widget._is_closing = True
    stop_event = threading.Event()
    monitoring_worker = Mock()
    monitoring_worker.is_alive.return_value = True
    processing_worker = Mock()
    processing_worker.is_alive.return_value = True
    widget._monitoring_stop_event = stop_event
    widget._monitoring_thread = monitoring_worker
    widget._processing_threads = {processing_worker}
    close_event = Mock()
    retry_close = Mock()
    monkeypatch.setattr(QMessageBox, "question", Mock(return_value=QMessageBox.Yes))
    monkeypatch.setattr(app.QTimer, "singleShot", Mock(side_effect=lambda _, callback: retry_close(callback)))

    widget.closeEvent(close_event)

    assert stop_event.is_set()
    browser.stop.assert_called_once_with()
    monitoring_worker.join.assert_not_called()
    processing_worker.join.assert_not_called()
    assert widget.status.text() == "Closing; a background import is finishing safely."
    close_event.ignore.assert_called_once_with()
    assert retry_close.call_count == 1

    monitoring_worker.is_alive.return_value = False
    processing_worker.is_alive.return_value = False
    finished_event = Mock()
    widget.closeEvent(finished_event)
    browser.stop.assert_called_once_with()
    finished_event.accept.assert_called_once_with()


def test_close_does_not_block_on_a_genuinely_running_import(window, monkeypatch):
    widget, _ = window
    release = threading.Event()
    worker = threading.Thread(target=release.wait, name="blocked-import")
    worker.start()
    widget._processing_threads = {worker}
    widget._active_processing_thread = worker
    widget._processing_active = True
    monkeypatch.setattr(app.QTimer, "singleShot", Mock())
    event = Mock()
    try:
        started = time.monotonic()
        widget.closeEvent(event)
        assert time.monotonic() - started < 0.5
        event.ignore.assert_called_once_with()
        assert widget.status.text() == "Closing; a background import is finishing safely."
    finally:
        release.set()
        worker.join(timeout=2)
    final_event = Mock()
    widget.closeEvent(final_event)
    final_event.accept.assert_called_once_with()


def test_startup_shows_path_error_after_qapplication_exists(monkeypatch):
    application = Mock()
    monkeypatch.setattr(app.QApplication, "instance", Mock(return_value=application))
    monkeypatch.setattr(app, "runtime_paths", Mock(side_effect=app.RuntimePathError("LOCALAPPDATA must be absolute")))
    logging_init = Mock()
    migration = Mock()
    message = Mock()
    monkeypatch.setattr(app, "initialize_runtime_logging", logging_init)
    monkeypatch.setattr(app, "migrate_legacy_runtime_data", migration)
    monkeypatch.setattr(app.QMessageBox, "critical", message)

    assert app.main() == 1

    logging_init.assert_not_called()
    migration.assert_not_called()
    message.assert_called_once()
    assert "LOCALAPPDATA must be absolute" in message.call_args.args[2]


def test_startup_does_not_migrate_when_required_logging_fails(tmp_path, monkeypatch):
    application = Mock()
    paths = app.RuntimePaths(
        root=tmp_path, database=tmp_path / "data/db.sqlite",
        result=tmp_path / "data/result/result.xlsx",
        state=tmp_path / "state/state.json", log=tmp_path / "logs/app.log",
    )
    monkeypatch.setattr(app.QApplication, "instance", Mock(return_value=application))
    monkeypatch.setattr(app, "runtime_paths", Mock(return_value=paths))
    monkeypatch.setattr(app, "initialize_runtime_logging", Mock(return_value=(Mock(), None)))
    migration = Mock()
    message = Mock()
    monkeypatch.setattr(app, "migrate_legacy_runtime_data", migration)
    monkeypatch.setattr(app.QMessageBox, "critical", message)

    assert app.main() == 1

    migration.assert_not_called()
    assert "required user-data log file could not be created" in message.call_args.args[2]
