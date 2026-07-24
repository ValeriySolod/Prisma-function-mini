from __future__ import annotations

import logging
import sys
import threading
from datetime import date
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QDate, QObject, QTimer, QUrl, Signal
from PySide6.QtGui import QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QDateEdit,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from mini_ui import (
    MiniUiState,
    MiniUiStateModel,
    MiniWorkCancelled,
    MiniWorkOutcome,
    MiniWorkRequest,
    validate_date_range,
)
from mini_workflow import MiniIntegratedWorkflow
from runtime_logging import LOGGER_NAME, initialize_runtime_logging, safe_log
from runtime_paths import RuntimePathError, RuntimePaths, prepare_runtime_directories, runtime_paths
from version import APP_DISPLAY_NAME, __version__


WorkRunner = Callable[[MiniWorkRequest, threading.Event, Callable[[MiniUiState, str], None]], Path | None]


def unavailable_workflow(
    request: MiniWorkRequest,
    cancel_event: threading.Event,
    progress: Callable[[MiniUiState, str], None],
) -> Path | None:
    """M.7 boundary for the browser/download/processing workflow added later."""
    del request, progress
    if cancel_event.is_set():
        raise MiniWorkCancelled
    raise RuntimeError("Processing is not available in this version yet.")


class WorkerSignals(QObject):
    progress = Signal(object, str, int)
    finished = Signal(object)


class MiniMainWindow(QMainWindow):
    def __init__(self, paths: RuntimePaths, *, work_runner: WorkRunner | None = None) -> None:
        super().__init__()
        self._runtime_paths = paths
        self._work_runner = work_runner or (
            lambda request, cancel_event, progress:
            MiniIntegratedWorkflow(paths).run(request, cancel_event, progress)
        )
        self._logger = logging.getLogger(LOGGER_NAME)
        self._state_model = MiniUiStateModel()
        self._generation = 0
        self._worker: threading.Thread | None = None
        self._cancel_event: threading.Event | None = None
        self._shutdown_requested = False
        self.signals = WorkerSignals(self)
        self.signals.progress.connect(self._on_progress)
        self.signals.finished.connect(self._on_finished)
        self._shutdown_timer = QTimer(self)
        self._shutdown_timer.setInterval(50)
        self._shutdown_timer.timeout.connect(self.close)
        self._build_ui()
        self._render_state()

    @property
    def state(self) -> MiniUiState:
        return self._state_model.state

    def _build_ui(self) -> None:
        self.setWindowTitle(f"{APP_DISPLAY_NAME} v{__version__}")
        self.setMinimumSize(620, 360)
        self.resize(720, 420)

        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(20)

        title = QLabel(APP_DISPLAY_NAME)
        title.setObjectName("title")
        subtitle = QLabel("Retrieve PRISMA auctions for a selected date range.")
        subtitle.setObjectName("subtitle")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        dates = QFrame()
        dates.setObjectName("panel")
        date_layout = QGridLayout(dates)
        date_layout.setContentsMargins(20, 18, 20, 18)
        date_layout.setHorizontalSpacing(16)
        date_layout.setVerticalSpacing(8)
        today = QDate.currentDate()
        self.start_date = self._date_edit(today)
        self.end_date = self._date_edit(today)
        date_layout.addWidget(QLabel("Start date"), 0, 0)
        date_layout.addWidget(QLabel("End date"), 0, 1)
        date_layout.addWidget(self.start_date, 1, 0)
        date_layout.addWidget(self.end_date, 1, 1)
        layout.addWidget(dates)

        actions = QHBoxLayout()
        self.start_button = QPushButton("Start")
        self.start_button.setObjectName("primaryButton")
        self.cancel_button = QPushButton("Cancel")
        self.open_result_button = QPushButton("Open Result")
        for button in (self.start_button, self.cancel_button, self.open_result_button):
            button.setAccessibleName(button.text())
        self.start_button.clicked.connect(self.start_work)
        self.cancel_button.clicked.connect(self.cancel_work)
        self.open_result_button.clicked.connect(self.open_result)
        actions.addWidget(self.start_button)
        actions.addWidget(self.cancel_button)
        actions.addStretch()
        actions.addWidget(self.open_result_button)
        layout.addLayout(actions)

        status_caption = QLabel("Status")
        status_caption.setObjectName("statusCaption")
        self.status_label = QLabel()
        self.status_label.setObjectName("status")
        self.status_label.setWordWrap(True)
        self.status_label.setAccessibleName("Processing status")
        layout.addWidget(status_caption)
        layout.addWidget(self.status_label)
        layout.addStretch()
        self.setCentralWidget(root)
        self.setStyleSheet(
            "QMainWindow, QWidget { background: #f4f7fb; color: #1f2937; font-size: 10pt; }"
            "QLabel#title { font-size: 22pt; font-weight: 700; color: #12233f; }"
            "QLabel#subtitle { color: #5b6b82; }"
            "QFrame#panel { background: white; border: 1px solid #d9e1ec; border-radius: 8px; }"
            "QDateEdit { background: white; border: 1px solid #9eacbf; border-radius: 4px; padding: 7px; }"
            "QPushButton { padding: 8px 16px; border: 1px solid #9eacbf; border-radius: 4px; background: white; }"
            "QPushButton#primaryButton { background: #176b87; color: white; border-color: #176b87; font-weight: 600; }"
            "QPushButton:disabled { color: #8a96a8; background: #e8edf3; border-color: #d4dbe5; }"
            "QLabel#statusCaption { color: #5b6b82; font-weight: 600; }"
            "QLabel#status { background: white; border: 1px solid #d9e1ec; border-radius: 6px; padding: 12px; }"
        )

    @staticmethod
    def _date_edit(value: QDate) -> QDateEdit:
        control = QDateEdit(value)
        control.setCalendarPopup(True)
        control.setDisplayFormat("yyyy-MM-dd")
        return control

    def _render_state(self) -> None:
        policy = self._state_model.action_policy(self._runtime_paths.result.exists())
        self.start_date.setEnabled(policy.dates_enabled)
        self.end_date.setEnabled(policy.dates_enabled)
        self.start_button.setEnabled(policy.start_enabled)
        self.cancel_button.setEnabled(policy.cancel_enabled)
        self.open_result_button.setEnabled(policy.open_result_enabled)
        self.status_label.setText(self._state_model.message)

    def _set_state(self, state: MiniUiState, message: str) -> None:
        self._state_model.transition(state, message)
        self._render_state()

    def start_work(self) -> None:
        if self._state_model.is_active:
            return
        self._set_state(MiniUiState.VALIDATING, "Validating date range…")
        validation = validate_date_range(
            self.start_date.date().toPython(), self.end_date.date().toPython(), today=date.today()
        )
        if validation.error is not None:
            self._set_state(MiniUiState.ERROR, validation.error)
            return

        self._generation += 1
        generation = self._generation
        request = MiniWorkRequest(validation.date_range)
        cancel_event = threading.Event()
        worker = threading.Thread(
            target=self._run_worker,
            args=(request, cancel_event, generation),
            name="mini-workflow",
            daemon=False,
        )
        self._cancel_event = cancel_event
        self._worker = worker
        self._set_state(MiniUiState.OPENING_PRISMA, "Opening PRISMA…")
        try:
            worker.start()
        except Exception as exc:
            self._worker = None
            self._cancel_event = None
            safe_log(self._logger, logging.ERROR, "Worker startup failed: %s", type(exc).__name__)
            self._set_state(MiniUiState.ERROR, "Processing could not be started.")

    def _run_worker(self, request: MiniWorkRequest, cancel_event: threading.Event, generation: int) -> None:
        def progress(state: MiniUiState, message: str) -> None:
            if state not in MiniUiState.worker_progress_states():
                raise ValueError("Worker reported an unsupported UI state.")
            self.signals.progress.emit(state, message, generation)

        try:
            result_path = self._work_runner(request, cancel_event, progress)
            if cancel_event.is_set():
                outcome = MiniWorkOutcome.cancelled(generation)
            else:
                outcome = MiniWorkOutcome.completed(generation, result_path)
        except MiniWorkCancelled:
            outcome = MiniWorkOutcome.cancelled(generation)
        except Exception as exc:
            safe_log(self._logger, logging.ERROR, "Mini workflow failed: %s", type(exc).__name__)
            outcome = MiniWorkOutcome.failed(generation, str(exc))
        self.signals.finished.emit(outcome)

    def _on_progress(self, state: MiniUiState, message: str, generation: int) -> None:
        if generation != self._generation or self._shutdown_requested or self.state is MiniUiState.CANCELLING:
            return
        self._set_state(state, message)

    def _on_finished(self, outcome: MiniWorkOutcome) -> None:
        if outcome.generation != self._generation:
            return
        worker = self._worker
        if worker is not None and worker.is_alive():
            QTimer.singleShot(10, lambda: self._on_finished(outcome))
            return
        if worker is not None:
            worker.join(timeout=0)
        self._worker = None
        self._cancel_event = None
        if self._shutdown_requested:
            self.close()
            return
        if outcome.was_cancelled:
            self._set_state(MiniUiState.IDLE, "Cancelled. Ready to start.")
        elif outcome.error is not None:
            self._set_state(MiniUiState.ERROR, outcome.public_error)
        elif not self._runtime_paths.result.exists():
            self._set_state(MiniUiState.ERROR, "Processing completed without a result file.")
        else:
            self._set_state(MiniUiState.COMPLETED, "Completed. The result is ready.")

    def cancel_work(self) -> None:
        if not self._state_model.is_active or self.state is MiniUiState.CANCELLING:
            return
        if self._cancel_event is not None:
            self._cancel_event.set()
        self._set_state(MiniUiState.CANCELLING, "Cancelling…")

    def open_result(self) -> None:
        result = self._runtime_paths.result
        if not result.exists():
            self._set_state(MiniUiState.ERROR, "The result file does not exist yet.")
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(result))):
            self._set_state(MiniUiState.ERROR, "The result file could not be opened.")

    def closeEvent(self, event: QCloseEvent) -> None:
        worker = self._worker
        if worker is not None and worker.is_alive():
            self._shutdown_requested = True
            if self._cancel_event is not None:
                self._cancel_event.set()
            self._set_state(MiniUiState.CANCELLING, "Cancelling before closing…")
            self._shutdown_timer.start()
            event.ignore()
            return
        self._shutdown_timer.stop()
        event.accept()


# Compatibility alias for the packaged entry point and older integrations.
PrismaMonitorApp = MiniMainWindow


def main() -> int:
    application = QApplication.instance() or QApplication(sys.argv)
    application.setApplicationName(APP_DISPLAY_NAME)
    application.setApplicationVersion(__version__)
    try:
        paths = runtime_paths()
        _, log_path = initialize_runtime_logging(paths.log)
        if log_path is None:
            raise RuntimePathError(
                "The required user-data log file could not be created. "
                "Check LOCALAPPDATA and folder permissions, then retry."
            )
        prepare_runtime_directories(paths=paths)
    except Exception as exc:
        QMessageBox.critical(
            None,
            f"{APP_DISPLAY_NAME} Data Error",
            f"{APP_DISPLAY_NAME} could not prepare its user-data directory. "
            f"No historical data was modified. {exc}",
        )
        return 1
    window = MiniMainWindow(paths)
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
