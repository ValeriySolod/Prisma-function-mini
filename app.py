from __future__ import annotations

import logging
import sys
import threading
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

from collections.abc import Callable

from PySide6.QtCore import QDate, QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QDateEdit,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from auction_csv import AuctionCsvRecord, CsvValidationError, load_auction_csv
from browser import BrowserController
from monitoring import MonitoringEngine, MonitoringResult
from monitoring_storage import MonitoringStorage, MonitoringStorageError
from notifications import StatusChangeNotification
from prisma_page import (
    LivePrismaStatusAdapter,
    PrismaAuctionNotFoundError,
    PrismaLookupTimeoutError,
    PrismaPageStructureError,
    PrismaPageUnavailableError,
)
from prisma_import_workflow import PrismaWorkflowResult, run_prisma_import_workflow
from runtime_logging import (
    LOGGER_NAME,
    initialize_runtime_logging,
    safe_log,
)
from runtime_paths import RuntimePathError, RuntimePaths, prepare_runtime_directories, runtime_paths
from scheduler import MonitoringScheduler
from ui_components import (
    APP_STYLE,
    ArrowComboBox,
    AuctionFilterModel,
    AuctionTableModel,
    StatusDelegate,
    SummaryCard,
)
from version import APP_DISPLAY_NAME, __version__

DEFAULT_MONITORING_INTERVAL_SECONDS = 30.0


@dataclass(frozen=True)
class ProcessingOutcome:
    result: PrismaWorkflowResult | None
    error: str | None
    generation: int


class ActivityKind(Enum):
    ACTIVITY = "activity"
    STATUS_CHANGE = "status-change"


class WorkerSignals(QObject):
    processing_finished = Signal(object)
    monitoring_results = Signal(object)
    monitoring_finished = Signal(object)


class PrismaMonitorApp(QMainWindow):
    def __init__(self, paths: RuntimePaths) -> None:
        super().__init__()
        self._runtime_paths = paths
        self.setWindowTitle(f"{APP_DISPLAY_NAME} v{__version__}")
        self.setMinimumSize(1080, 680)
        self.resize(1280, 800)
        self.browser = BrowserController()
        self._logger = logging.getLogger(LOGGER_NAME)
        self._is_closing = False
        self._browser_ready = False
        self._active_browser_launch: int | None = None
        self._auction_records: list[AuctionCsvRecord] = []
        self._monitoring_thread: threading.Thread | None = None
        self._monitoring_stop_event: threading.Event | None = None
        self._processing_threads: set[threading.Thread] = set()
        self._active_processing_thread: threading.Thread | None = None
        self._processing_active = False
        self._processing_generation = 0
        self._shutdown_started = False
        self.signals = WorkerSignals(self)
        self.signals.processing_finished.connect(self._processing_finished)
        self.signals.monitoring_results.connect(self._monitoring_results)
        self.signals.monitoring_finished.connect(self._monitoring_finished)
        self._browser_timer = QTimer(self)
        self._browser_timer.setInterval(50)
        self._browser_timer.timeout.connect(self._poll_browser_launch)
        self._build_ui()
        self._update_controls()
        self._add_activity("Application ready")

    def _button(
        self,
        text: str,
        handler: Callable[[], None],
        *,
        primary: bool = False,
        sidebar: bool = True,
        tooltip: str = "",
    ) -> QPushButton:
        button = QPushButton(text)
        button.clicked.connect(handler)
        button.setProperty("primary", primary)
        button.setProperty("sidebar", sidebar)
        button.setToolTip(tooltip)
        button.setAccessibleName(text)
        return button

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("workspace")
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(260)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(22, 24, 22, 22)
        side.setSpacing(9)
        brand = QLabel(APP_DISPLAY_NAME)
        brand.setObjectName("brand")
        subtitle = QLabel("PRISMA auction monitoring")
        subtitle.setObjectName("subtitle")
        side.addWidget(brand)
        side.addWidget(subtitle)
        side.addSpacing(20)
        self.open_button = self._button("Open Browser", self.open_prisma, primary=True,
            tooltip="Open a Prisma Function Mini-managed PRISMA browser session")
        self.stop_browser_button = self._button("Stop Browser", self.stop_work)
        self._side_group(side, "BROWSER", self.open_button, self.stop_browser_button)
        self.load_csv_button = self._button("Load Monitoring CSV", self.select_csv, primary=True)
        self.csv_filename = QLabel("No CSV selected")
        self.csv_filename.setObjectName("filename")
        self.csv_count = QLabel("0 records loaded")
        self._side_group(side, "DATA SOURCE", self.load_csv_button, self.csv_filename, self.csv_count)
        self.start_monitoring_button = self._button("Start Monitoring", self.start_monitoring, primary=True)
        self.stop_monitoring_button = self._button("Stop Monitoring", self.stop_monitoring)
        self._side_group(side, "MONITORING", self.start_monitoring_button, self.stop_monitoring_button)
        side.addStretch()
        self.import_date = QDateEdit(QDate.currentDate())
        self.import_date.setCalendarPopup(True)
        self.import_date.setDisplayFormat("yyyy-MM-dd")
        self.import_date.setAccessibleName("PRISMA export source date")
        self.import_date_label = QLabel("PRISMA EXPORT DATE")
        self.import_date_label.setObjectName("subtitle")
        source_date_help = (
            "Identifies the daily PRISMA source and is used for controlled "
            "update and exact-retry validation."
        )
        self.import_date_label.setToolTip(source_date_help)
        self.import_date.setToolTip(source_date_help)
        self.process_button = self._button(
            "Import PRISMA Export", self.start_processing, sidebar=True,
            tooltip="Import a complete original PRISMA Export CSV"
        )
        side.addWidget(self.import_date_label)
        side.addWidget(self.import_date)
        self.open_result_button = self._button("Open Result", self.open_result, sidebar=True)
        side.addWidget(self.process_button)
        side.addWidget(self.open_result_button)
        version = QLabel(f"Version {__version__}")
        version.setObjectName("subtitle")
        side.addWidget(version)

        content = QWidget()
        content.setObjectName("contentArea")
        main = QVBoxLayout(content)
        main.setContentsMargins(28, 22, 28, 20)
        main.setSpacing(16)
        header = QHBoxLayout()
        titles = QVBoxLayout()
        title = QLabel("Monitoring dashboard")
        title.setStyleSheet("font-size: 19pt; font-weight: 700; color: #152033")
        titles.addWidget(title)
        dashboard_subtitle = QLabel(
            "Track PRISMA auction states from your validated CSV data."
        )
        dashboard_subtitle.setObjectName("dashboardSubtitle")
        titles.addWidget(dashboard_subtitle)
        header.addLayout(titles)
        header.addStretch()
        self.browser_badge = QLabel("Disconnected")
        self.browser_badge.setObjectName("browserBadge")
        self.monitor_badge = QLabel("Monitoring idle")
        self.monitor_badge.setObjectName("monitorBadge")
        header.addWidget(self.browser_badge)
        header.addWidget(self.monitor_badge)
        main.addLayout(header)
        cards = QHBoxLayout()
        self.summary_cards: dict[str, SummaryCard] = {}
        for key, caption in (("total", "Total"), ("active", "Pending / active"),
                             ("completed", "Completed"), ("errors", "Errors")):
            card = SummaryCard(caption)
            self.summary_cards[key] = card
            cards.addWidget(card)
        main.addLayout(cards)
        panel = QFrame()
        panel.setObjectName("panel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(16, 14, 16, 10)
        tools = QHBoxLayout()
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search Auction ID, lot, or market…")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.setAccessibleName("Search auctions")
        self.status_filter = ArrowComboBox()
        self.status_filter.setProperty("arrowImplementation", "custom-paint")
        self.status_filter.addItems(
            ["All statuses", "Pending", "Scheduled", "Open", "In Progress", "Completed", "Cancelled", "Error", "Disabled"])
        self.status_filter.setAccessibleName("Filter by status")
        tools.addWidget(self.search_box, 1)
        tools.addWidget(self.status_filter)
        panel_layout.addLayout(tools)
        self.table_model = AuctionTableModel(self)
        self.proxy_model = AuctionFilterModel(self)
        self.proxy_model.setSourceModel(self.table_model)
        self.csv_table = QTableView()
        self.csv_table.setModel(self.proxy_model)
        self.csv_table.setAlternatingRowColors(True)
        self.csv_table.setSortingEnabled(True)
        self.csv_table.setSelectionBehavior(QTableView.SelectRows)
        self.csv_table.setAccessibleName("Auctions")
        self.csv_table.verticalHeader().hide()
        self.csv_table.setItemDelegateForColumn(4, StatusDelegate(self.csv_table))
        self.csv_table.setItemDelegateForColumn(5, StatusDelegate(self.csv_table))
        hdr = self.csv_table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.Stretch)
        panel_layout.addWidget(self.csv_table, 1)
        self.empty_label = QLabel("Load a CSV file to begin monitoring auctions.")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setStyleSheet("color:#718096; padding:18px")
        panel_layout.addWidget(self.empty_label)
        main.addWidget(panel, 1)
        activity_panel = QFrame()
        activity_panel.setObjectName("panel")
        activity_layout = QVBoxLayout(activity_panel)
        activity_header = QHBoxLayout()
        activity_title = QLabel("Recent activity")
        activity_title.setObjectName("contentSectionLabel")
        activity_header.addWidget(activity_title)
        activity_header.addStretch()
        self.open_logs_button = self._button("Open log folder", self.open_log_directory, sidebar=False)
        self.clear_activity_button = self._button("Clear", self.clear_activity, sidebar=False)
        activity_header.addWidget(self.open_logs_button)
        activity_header.addWidget(self.clear_activity_button)
        self.activity_list = QListWidget()
        self.activity_list.setObjectName("activityList")
        self.activity_list.setMaximumHeight(105)
        activity_layout.addLayout(activity_header)
        activity_layout.addWidget(self.activity_list)
        main.addWidget(activity_panel)
        status_row = QHBoxLayout()
        status_caption = QLabel("Status:")
        status_caption.setObjectName("contentSectionLabel")
        status_row.addWidget(status_caption)
        self.status = QLabel("Ready")
        self.status.setObjectName("primaryStatus")
        self.status.setWordWrap(True)
        status_row.addWidget(self.status, 1)
        main.addLayout(status_row)
        self.csv_path = QLineEdit()
        self.csv_path.hide()  # compatibility/state holder, not user-editable
        outer.addWidget(sidebar)
        outer.addWidget(content, 1)
        self.setCentralWidget(root)
        self.setStyleSheet(APP_STYLE)
        self.search_box.textChanged.connect(self.proxy_model.set_search)
        self.status_filter.currentTextChanged.connect(self.proxy_model.set_status)
        self._set_badge(self.browser_badge, "Disconnected", "idle")
        self._set_badge(self.monitor_badge, "Monitoring idle", "idle")

    @staticmethod
    def _side_group(layout: QLayout, label: str, *widgets: QWidget) -> None:
        heading = QLabel(label)
        heading.setObjectName("section")
        layout.addWidget(heading)
        for widget in widgets:
            layout.addWidget(widget)
        layout.addSpacing(13)

    def _set_badge(self, badge: QLabel, text: str, state: str) -> None:
        badge.setText(text)
        badge.setProperty("state", state)
        badge.style().unpolish(badge)
        badge.style().polish(badge)

    def _add_activity(
        self, message: str, kind: ActivityKind = ActivityKind.ACTIVITY
    ) -> None:
        label = "Status change — " if kind is ActivityKind.STATUS_CHANGE else ""
        item = QListWidgetItem(f"{datetime.now():%H:%M:%S}  {label}{message}")
        item.setData(Qt.UserRole, kind.value)
        if kind is ActivityKind.STATUS_CHANGE:
            font = item.font()
            font.setBold(True)
            item.setFont(font)
            item.setForeground(QColor("#075985"))
            item.setData(
                Qt.AccessibleDescriptionRole,
                f"Status change notification. {message}",
            )
        self.activity_list.insertItem(0, item)
        while self.activity_list.count() > 50:
            self.activity_list.takeItem(self.activity_list.count() - 1)

    def clear_activity(self) -> None:
        self.activity_list.clear()

    def _update_controls(self) -> None:
        launching = self._active_browser_launch is not None and not self._browser_ready
        monitoring = self._monitoring_thread is not None
        has_records = any(record.enabled for record in self._auction_records)
        self.open_button.setEnabled(not launching and not self._browser_ready)
        self.stop_browser_button.setEnabled(launching or self._browser_ready)
        self.load_csv_button.setEnabled(not monitoring)
        self.start_monitoring_button.setEnabled(self._browser_ready and has_records and not monitoring)
        self.stop_monitoring_button.setEnabled(monitoring)
        self.process_button.setEnabled(not self._processing_active)
        self.import_date.setEnabled(not self._processing_active)

    def select_csv(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(self, "Load Monitoring CSV", "", "CSV files (*.csv)")
        if not selected:
            return
        try:
            records = load_auction_csv(selected)
        except CsvValidationError as exc:
            self._show_error("CSV Error", str(exc))
            return
        except Exception as exc:
            safe_log(self._logger, logging.ERROR, "CSV load failed: %s", exc)
            self._show_error(
                "CSV Error",
                "The CSV file could not be loaded. Check the file and try again.",
            )
            return
        self._auction_records = records
        self.csv_path.setText(selected)
        self.table_model.set_records(records)
        self.csv_filename.setText(Path(selected).name)
        self.csv_count.setText(f"{len(records)} records loaded")
        self.empty_label.hide()
        self._update_summary()
        self._update_controls()
        self.status.setText(f"Loaded {Path(selected).name}: {len(records)} records")
        self._add_activity(f"CSV loaded: {Path(selected).name} ({len(records)} records)")

    def _display_csv_records(self, records: list[AuctionCsvRecord]) -> None:
        self.table_model.set_records(records)
        self.empty_label.setVisible(not records)
        self._update_summary()

    def _update_summary(self) -> None:
        for key, count in self.table_model.counts().items():
            self.summary_cards[key].value.setText(str(count))

    def open_prisma(self) -> None:
        if self._active_browser_launch is not None or self._browser_ready:
            return
        try:
            self.status.setText("Opening the managed PRISMA browser…")
            self._set_badge(self.browser_badge, "Opening", "working")
            self._active_browser_launch = self.browser.open()
            self._browser_timer.start()
            self._update_controls()
        except Exception as exc:
            self._browser_start_failed(exc)

    def _poll_browser_launch(self) -> None:
        if self._is_closing or self._active_browser_launch is None:
            self._browser_timer.stop()
            return
        for result in self.browser.get_launch_results():
            if result.generation != self._active_browser_launch:
                continue
            if result.success:
                self._browser_ready = True
                self._set_badge(self.browser_badge, "Ready", "ready")
                self.status.setText("PRISMA browser session is ready")
                self._add_activity("Browser opened")
            elif result.kind == "launch":
                self._browser_start_failed(result.error or "Unknown error")
                return
            else:
                self._active_browser_launch = None
                self._browser_ready = False
                self._browser_timer.stop()
                if self._monitoring_stop_event is not None: self._monitoring_stop_event.set()
                self._set_badge(self.browser_badge, "Disconnected", "error")
                self.status.setText("The managed PRISMA page or browser was closed. Open it again to retry.")
                self._add_activity("Browser session closed")
            self._update_controls()
            return

    def _browser_start_failed(self, exc: Exception | str) -> None:
        if self._is_closing:
            return
        self._active_browser_launch = None
        self._browser_ready = False
        self._browser_timer.stop()
        safe_log(self._logger, logging.ERROR, "Browser launch failed: %s", exc)
        self._set_badge(self.browser_badge, "Error", "error")
        self._update_controls()
        self._show_error(
            "Browser Error",
            "The browser could not be opened. Check Chrome or Edge and try again.",
        )
        self.status.setText("Failed to open the browser")
        self._add_activity("Browser error")

    def create_monitoring_engine(self) -> MonitoringEngine:
        return MonitoringEngine(
            LivePrismaStatusAdapter(self.browser),
            persistence=MonitoringStorage(self._runtime_paths.database),
        )

    def create_monitoring_scheduler(
        self, records: list[AuctionCsvRecord]
    ) -> MonitoringScheduler:
        return MonitoringScheduler(self.create_monitoring_engine(), lambda: records)

    def start_monitoring(self) -> None:
        if self._monitoring_thread is not None:
            return
        records = [record for record in self._auction_records if record.enabled]
        if not records or not self._browser_ready:
            self._show_error(
                "Monitoring Error",
                "Open the browser and load a CSV with enabled auctions first.",
            )
            return
        stop_event = threading.Event()
        scheduler = self.create_monitoring_scheduler(records)
        thread = threading.Thread(
            target=self._monitoring_worker,
            args=(scheduler, stop_event),
            daemon=False,
            name="prisma-monitoring",
        )
        self._monitoring_stop_event, self._monitoring_thread = stop_event, thread
        self._set_badge(self.monitor_badge, "Monitoring active", "ready")
        self.status.setText("Monitoring started")
        self._add_activity("Monitoring started")
        self._update_controls()
        try:
            thread.start()
        except Exception as exc:
            self._set_monitoring_idle()
            safe_log(
                self._logger, logging.ERROR, "Monitoring start failed: %s", exc
            )
            self._show_error(
                "Monitoring Error", "Monitoring could not be started. Please try again."
            )

    def stop_monitoring(self) -> None:
        if self._monitoring_stop_event is not None:
            self._monitoring_stop_event.set()
            self.status.setText("Stopping monitoring…")
            self._set_badge(self.monitor_badge, "Stopping", "working")

    def _monitoring_worker(
        self, scheduler: MonitoringScheduler, stop_event: threading.Event
    ) -> None:
        error = None
        try:
            scheduler.run_forever(
                stop_event,
                DEFAULT_MONITORING_INTERVAL_SECONDS,
                self.signals.monitoring_results.emit,
            )
        except Exception as exc:
            error = exc
        self.signals.monitoring_finished.emit(error)

    def _monitoring_results(self, results: list[MonitoringResult]) -> None:
        changed = errors = 0
        notifications: list[StatusChangeNotification] = []
        for result in results:
            self.table_model.apply_result(result)
            changed += bool(result.status_changed)
            errors += result.result == "Error"
            notification = StatusChangeNotification.from_result(result)
            if notification is not None:
                notifications.append(notification)
        self._update_summary()
        # The list is newest-first. Reverse insertion preserves the scheduler's
        # deterministic result order directly below the cycle summary.
        for notification in reversed(notifications):
            self._add_activity(
                notification.message(), ActivityKind.STATUS_CHANGE
            )
        self._add_activity(
            f"Statuses updated: {len(results)} checked, "
            f"{changed} changed, {errors} errors"
        )

    @staticmethod
    def _monitoring_failure_message(error: object) -> str:
        if isinstance(error, PrismaLookupTimeoutError):
            return (
                "The live PRISMA status lookup timed out. "
                "Reopen the browser and retry."
            )
        if isinstance(error, PrismaPageUnavailableError):
            return (
                "The PRISMA page is unavailable or closed. "
                "Reopen the browser and retry."
            )
        if isinstance(error, PrismaPageStructureError):
            return (
                "The PRISMA page structure could not be read. "
                "Reopen the browser or retry."
            )
        if isinstance(error, PrismaAuctionNotFoundError):
            return str(error)
        if isinstance(error, MonitoringStorageError):
            return "Monitoring history could not be saved. Please retry."
        return "Monitoring stopped because of an unexpected error. Please retry."

    def _monitoring_finished(self, error: object = None) -> None:
        if self._is_closing:
            return
        self._set_monitoring_idle()
        if error is not None:
            message = self._monitoring_failure_message(error)
            safe_log(
                self._logger, logging.WARNING, "Monitoring terminated: %s", error
            )
            self.status.setText(message)
            self._show_error("Monitoring Error", message)
            self._add_activity("Monitoring error")
        else:
            self.status.setText("Monitoring stopped")
            self._add_activity("Monitoring stopped")

    def _set_monitoring_idle(self) -> None:
        self._monitoring_thread = None
        self._monitoring_stop_event = None
        self._set_badge(self.monitor_badge, "Monitoring idle", "idle")
        self._update_controls()

    def stop_work(self) -> None:
        if self._monitoring_thread is not None:
            answer = QMessageBox.question(
                self,
                "Stop Browser",
                "Monitoring is active. Stop monitoring and close the managed browser?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
            self.stop_monitoring()
        self.browser.stop()
        self._active_browser_launch = None
        self._browser_ready = False
        self._browser_timer.stop()
        self._set_badge(self.browser_badge, "Disconnected", "idle")
        self._update_controls()
        self.status.setText("Managed browser closed")
        self._add_activity("Browser stopped")

    def start_processing(self) -> None:
        if self._processing_active:
            return
        selected, _ = QFileDialog.getOpenFileName(
            self, "Import PRISMA Export CSV", "", "CSV files (*.csv)"
        )
        if not selected:
            return
        source = Path(selected)
        self._processing_active = True
        self.status.setText("Importing PRISMA Export CSV…")
        self._add_activity(f"PRISMA import started: {source.name}")
        self._update_controls()
        selected_date = self.import_date.date().toPython()
        self._processing_generation += 1
        generation = self._processing_generation
        thread = threading.Thread(
            target=self._process_worker,
            args=(source, selected_date, generation),
            daemon=False,
            name="prisma-processing",
        )
        self._processing_threads.add(thread)
        self._active_processing_thread = thread
        try:
            thread.start()
        except Exception as exc:
            self._processing_threads.discard(thread)
            self._processing_active = False
            self._update_controls()
            self._processing_finished(ProcessingOutcome(None, str(exc), generation))

    def _process_worker(self, source: Path, source_date=None, generation: int = 0) -> None:
        try:
            result = run_prisma_import_workflow(
                source,
                source_date=source_date or datetime.now().date(),
                evaluated_at=datetime.now().astimezone(),
                database_path=self._runtime_paths.database,
                state_path=self._runtime_paths.state,
                output_path=self._runtime_paths.result,
            )
            self.signals.processing_finished.emit(
                ProcessingOutcome(result, None, generation)
            )
        except Exception as exc:
            self.signals.processing_finished.emit(
                ProcessingOutcome(None, str(exc), generation)
            )

    def _processing_finished(self, outcome: ProcessingOutcome) -> None:
        if outcome.generation != self._processing_generation:
            return
        if outcome.error is not None:
            self._processing_failed(outcome.error, None)
        elif outcome.result is not None:
            self._processing_succeeded(outcome.result, None)

    def _finish_processing(self, thread: threading.Thread | None) -> bool:
        if thread is None:
            thread = self._active_processing_thread
        if thread is not None and thread is not self._active_processing_thread:
            return False
        if thread is not None and thread.is_alive():
            thread.join(timeout=0.1)
        if thread is not None and not thread.is_alive():
            self._processing_threads.discard(thread)
        self._active_processing_thread = None
        self._processing_active = False
        self._update_controls()
        return True

    def _processing_succeeded(
        self, result: PrismaWorkflowResult, thread: threading.Thread | None
    ) -> None:
        if not self._is_closing and self._finish_processing(thread):
            self.status.setText(result.summary())
            self._add_activity(
                f"PRISMA import completed: {result.processed} processed, "
                f"{len(result.issues)} audit issues"
            )
            for issue in result.issues[:5]:
                self._add_activity(
                    f"Row {issue.source_row_number}: {issue.status.value} — {issue.message}"
                )

    def _processing_failed(
        self, error: str, thread: threading.Thread | None
    ) -> None:
        if not self._is_closing and self._finish_processing(thread):
            safe_log(self._logger, logging.ERROR, "Processing failed: %s", error)
            self._show_error(
                "Processing Error",
                f"PRISMA import failed: {error}",
            )
            self.status.setText(f"PRISMA import failed: {error}")

    def open_result(self) -> None:
        result = self._runtime_paths.result
        if not result.exists():
            QMessageBox.information(
                self, "Result Not Found", "Process a CSV file first."
            )
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(result)))

    def open_log_directory(self) -> None:
        path = self._runtime_paths.log.parent
        path.mkdir(parents=True, exist_ok=True)
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            self._show_error("Log Folder", "The log folder could not be opened.")

    def _show_error(self, title: str, message: str) -> None:
        QMessageBox.critical(self, title, message)

    def closeEvent(self, event) -> None:
        if not self._shutdown_started and self._monitoring_thread is not None:
            answer = QMessageBox.question(
                self,
                f"Close {APP_DISPLAY_NAME}",
                f"Monitoring is active. Stop monitoring and close {APP_DISPLAY_NAME}?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
        if not self._shutdown_started:
            self._shutdown_started = True
            self._is_closing = True
            self._browser_timer.stop()
            self._active_browser_launch = None
            if self._monitoring_stop_event is not None:
                self._monitoring_stop_event.set()
            self.browser.stop()
        threads = (
            [self._monitoring_thread] if self._monitoring_thread else []
        ) + list(self._processing_threads)
        if any(
            thread is not threading.current_thread() and thread.is_alive()
            for thread in threads
        ):
            self.status.setText("Closing; a background import is finishing safely.")
            event.ignore()
            QTimer.singleShot(100, self.close)
            return
        event.accept()


def main() -> int:
    application = QApplication.instance() or QApplication(sys.argv)
    application.setApplicationName(APP_DISPLAY_NAME)
    application.setApplicationVersion(__version__)
    initialization_error = None
    paths = None
    try:
        paths = runtime_paths()
        logger, log_path = initialize_runtime_logging(paths.log)
        if log_path is None:
            raise RuntimePathError(
                "The required user-data log file could not be created. "
                "Check LOCALAPPDATA and folder permissions, then retry."
            )
        prepare_runtime_directories(paths=paths)
    except Exception as exc:
        initialization_error = str(exc)
        if any(getattr(handler, "baseFilename", None) for handler in logging.getLogger(LOGGER_NAME).handlers):
            logging.getLogger(LOGGER_NAME).exception("Runtime-data initialization failed")
    if initialization_error is not None:
        QMessageBox.critical(
            None,
            f"{APP_DISPLAY_NAME} Data Error",
            f"{APP_DISPLAY_NAME} could not prepare its user-data directory. "
            f"No historical data was modified. {initialization_error}",
        )
        return 1
    window = PrismaMonitorApp(paths)
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
