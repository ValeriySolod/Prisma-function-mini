from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QObject,
    QPoint,
    QSortFilterProxyModel,
    Qt,
)
from PySide6.QtGui import QColor, QPaintEvent, QPainter, QPen, QPolygon
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QLabel,
    QStyle,
    QStyleOptionComboBox,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from auction_csv import AuctionCsvRecord
from monitoring import MonitoringResult


APP_STYLE = """
QMainWindow, QWidget#workspace { background: #f4f7fb; color: #182230; font-family: "Segoe UI"; font-size: 10pt; }
QWidget#contentArea { background: #f4f7fb; color: #182230; }
QWidget#contentArea QLabel { color: #243247; }
QLabel#dashboardSubtitle { color: #66758a; }
QLabel#contentSectionLabel { color: #314157; font-weight: 600; }
QFrame#sidebar { background: #172235; border: none; }
QFrame#sidebar QLabel { color: #d8e1ee; }
QLabel#brand { color: white; font-size: 20pt; font-weight: 700; }
QLabel#subtitle { color: #9fb0c6; font-size: 9pt; }
QLabel#section { color: #7f93ad; font-size: 8pt; font-weight: 700; }
QLabel#filename { color: white; font-weight: 600; }
QPushButton { min-height: 34px; padding: 3px 12px; border-radius: 7px; border: 1px solid #ccd6e2; background: white; color: #243247; }
QPushButton:hover { border-color: #1686a5; background: #f1fbfd; }
QPushButton:focus { border: 2px solid #1593b5; }
QPushButton:disabled { color: #8e9aaa; background: #e8edf3; border-color: #e0e6ed; }
QPushButton[primary="true"] { color: white; background: #087f9d; border-color: #087f9d; font-weight: 600; }
QPushButton[sidebar="true"] { color: #e9f0f8; background: #223149; border-color: #344861; text-align: left; }
QPushButton[sidebar="true"]:hover { background: #2a405c; border-color: #3c5876; }
QPushButton[sidebar="true"]:disabled { color: #75869c; background: #1c293d; border-color: #29394f; }
QFrame#card, QFrame#panel { background: white; border: 1px solid #e1e7ef; border-radius: 10px; }
QLabel#metric { font-size: 20pt; font-weight: 700; color: #152033; }
QLabel#metricLabel { color: #66758a; font-weight: 600; }
QLabel#browserBadge, QLabel#monitorBadge { border-radius: 10px; padding: 4px 10px; font-weight: 600; }
QLabel[state="idle"] { background: #e8edf3; color: #526173; }
QLabel[state="working"] { background: #fff1cc; color: #835b00; }
QLabel[state="ready"] { background: #d9f5e8; color: #176846; }
QLabel[state="error"] { background: #fde2e2; color: #9a2d2d; }
QLineEdit, QComboBox { min-height: 32px; border: 1px solid #ccd6e2; border-radius: 7px; padding: 2px 9px; background: white; color: #243247; selection-background-color: #087f9d; selection-color: white; }
QLineEdit { placeholder-text-color: #718096; }
QLineEdit:focus, QComboBox:focus { border: 2px solid #1593b5; }
QLineEdit:disabled, QComboBox:disabled { background: #e8edf3; color: #758397; border-color: #d8e0e9; }
QComboBox { padding-right: 34px; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: top right; width: 28px; border-left: 1px solid #ccd6e2; background: #f2f5f9; border-top-right-radius: 6px; border-bottom-right-radius: 6px; }
QComboBox::drop-down:hover { background: #e6f4f7; }
QComboBox::drop-down:disabled { background: #e1e7ee; border-left-color: #d3dbe5; }
QComboBox QAbstractItemView { background: white; color: #243247; border: 1px solid #ccd6e2; selection-background-color: #dff3f8; selection-color: #172235; outline: none; }
QWidget#contentArea QTableView { border: none; background: white; color: #243247; alternate-background-color: #f8fafc; gridline-color: transparent; selection-background-color: #dff3f8; selection-color: #172235; }
QWidget#contentArea QTableView::item { color: #243247; }
QWidget#contentArea QTableView::item:hover { background: #f0f7fa; color: #172235; }
QWidget#contentArea QTableView::item:selected { background: #dff3f8; color: #172235; }
QWidget#contentArea QTableView::item:selected:hover { background: #d4edf3; color: #172235; }
QWidget#contentArea QTableView:focus { color: #243247; }
QWidget#contentArea QTableView:disabled { background: #f1f4f7; color: #758397; }
QWidget#contentArea QTableView::item:disabled { color: #758397; }
QHeaderView::section { background: #f2f5f9; color: #56657a; border: none; border-bottom: 1px solid #dce4ed; padding: 9px; font-weight: 600; }
QListWidget { border: none; background: white; color: #243247; selection-background-color: #dff3f8; selection-color: #172235; outline: none; }
QListWidget::item { color: #243247; padding: 7px 4px; border-bottom: 1px solid #edf1f5; }
QLabel#primaryStatus { color: #314157; font-weight: 600; }
"""


class ArrowComboBox(QComboBox):
    """Combo box with a palette-independent, scale-aware arrow indicator."""

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        rect = self.style().subControlRect(
            QStyle.CC_ComboBox,
            option,
            QStyle.SC_ComboBoxArrow,
            self,
        )
        if rect.isEmpty():
            rect = self.rect()
            rect.setLeft(max(rect.left(), rect.right() - 27))
        half_width = max(4, min(6, rect.height() // 6))
        arrow_height = max(3, half_width // 2)
        center = rect.center()
        points = QPolygon(
            [
                QPoint(center.x() - half_width, center.y() - arrow_height // 2),
                QPoint(center.x() + half_width, center.y() - arrow_height // 2),
                QPoint(center.x(), center.y() + arrow_height),
            ]
        )
        color = QColor("#243247")
        if not self.isEnabled():
            color = QColor("#758397")

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        painter.drawPolygon(points)


@dataclass
class AuctionRow:
    record: AuctionCsvRecord
    current_status: str
    result: str = "Pending"
    checked_at: str = "—"


class AuctionTableModel(QAbstractTableModel):
    HEADERS = ("Auction ID", "Lot", "Item / Market", "Expected", "Current status", "Result", "Last checked")

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.rows: list[AuctionRow] = []
        self._row_by_id: dict[str, int] = {}

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.HEADERS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        values = (row.record.auction_id, row.record.lot_number, row.record.item_name,
                  row.record.expected_status, row.current_status, row.result, row.checked_at)
        if role in (Qt.DisplayRole, Qt.AccessibleTextRole):
            return str(values[index.column()])
        if role == Qt.UserRole:
            return row.result if index.column() == 5 else row.current_status
        if role == Qt.ToolTipRole and index.column() == 0:
            return row.record.auction_url
        if role == Qt.TextAlignmentRole and index.column() in (1, 6):
            return Qt.AlignCenter
        return None

    def set_records(self, records: list[AuctionCsvRecord]) -> None:
        identifiers = [record.auction_id for record in records]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Auction IDs must be unique.")
        self.beginResetModel()
        self.rows = [
            AuctionRow(
                record,
                record.last_known_status,
                "Pending" if record.enabled else "Disabled",
            )
            for record in records
        ]
        self._row_by_id = {row.record.auction_id: i for i, row in enumerate(self.rows)}
        self.endResetModel()

    def apply_result(self, result: MonitoringResult) -> bool:
        row_number = self._row_by_id.get(result.auction_id)
        if row_number is None:
            return False
        row = self.rows[row_number]
        row.current_status = result.current_status
        row.result = result.result
        row.checked_at = result.checked_at.strftime("%Y-%m-%d %H:%M:%S")
        self.dataChanged.emit(self.index(row_number, 4), self.index(row_number, 6))
        return True

    def counts(self) -> dict[str, int]:
        """Return total plus disjoint actionable state counts.

        Total includes every row. Disabled rows contribute only to Total.
        Among enabled rows, Active contains non-terminal, non-error rows;
        Completed requires an exact current status of Completed and a latest
        result other than Error; and Errors contains rows whose current status
        or latest result is Error. Error takes precedence over Active and
        Completed. An enabled Cancelled row contributes only to Total unless
        its latest result is Error, in which case it contributes to Errors.
        """
        return {
            "total": len(self.rows),
            "active": sum(
                row.record.enabled
                and row.current_status not in {"Completed", "Cancelled", "Error"}
                and row.result != "Error"
                for row in self.rows
            ),
            "completed": sum(
                row.record.enabled
                and row.current_status == "Completed"
                and row.result != "Error"
                for row in self.rows
            ),
            "errors": sum(
                row.record.enabled
                and (row.result == "Error" or row.current_status == "Error")
                for row in self.rows
            ),
        }


class AuctionFilterModel(QSortFilterProxyModel):
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._search = ""
        self._status = "All statuses"
        self.setDynamicSortFilter(True)

    def set_search(self, text: str) -> None:
        self.beginFilterChange()
        self._search = text.casefold().strip()
        self.endFilterChange(QSortFilterProxyModel.Direction.Rows)

    def set_status(self, text: str) -> None:
        self.beginFilterChange()
        self._status = text
        self.endFilterChange(QSortFilterProxyModel.Direction.Rows)

    def filterAcceptsRow(
        self, source_row: int, source_parent: QModelIndex
    ) -> bool:
        model = self.sourceModel()
        visible = " ".join(
            str(model.data(model.index(source_row, column)) or "")
            for column in range(model.columnCount())
        ).casefold()
        if self._search and self._search not in visible:
            return False
        if self._status != "All statuses":
            status = str(model.data(model.index(source_row, 4)) or "")
            result = str(model.data(model.index(source_row, 5)) or "")
            return self._status in {status, result}
        return True


class StatusDelegate(QStyledItemDelegate):
    COLORS = {
        "Completed": ("#d9f5e8", "#176846"),
        "Success": ("#d9f5e8", "#176846"),
        "Error": ("#fde2e2", "#9a2d2d"),
        "Pending": ("#fff1cc", "#835b00"),
        "Changed": ("#dff3f8", "#08667d"),
        "Disabled": ("#e8edf3", "#526173"),
    }

    def paint(
        self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex
    ) -> None:
        text = str(index.data() or "")
        bg, fg = self.COLORS.get(text, ("#e8edf3", "#526173"))
        painter.save()
        rect = option.rect.adjusted(8, 7, -8, -7)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(bg))
        painter.drawRoundedRect(rect, 8, 8)
        painter.setPen(QPen(QColor(fg)))
        painter.drawText(rect, Qt.AlignCenter, text)
        painter.restore()


class SummaryCard(QFrame):
    def __init__(self, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        self.value = QLabel("0")
        self.value.setObjectName("metric")
        caption = QLabel(label)
        caption.setObjectName("metricLabel")
        layout.addWidget(self.value)
        layout.addWidget(caption)
