"""Session history panel: browse past scans, preview, export or delete."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from autodiag.services.history import SessionStore, describe_report
from autodiag.ui.compare_dialog import CompareDialog

_COLUMNS = ("Date", "VIN", "DTCs", "Mode $06", "PIDs", "Adapter", "Log")
_JSON_FILTER = "JSON report (*.json)"
_CSV_FILTER = "CSV report (*.csv)"


class HistoryPanel(QWidget):
    """Read-only browser over the :class:`SessionStore` on disk."""

    view_log = Signal(str)  # log filename (emitted by the View log… button)

    def __init__(self, store: SessionStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store = store
        self._summaries: list[dict] = []
        self._selected: str | None = None
        self._selected_log: str | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        heading = QLabel("Session history")
        heading.setObjectName("heading")
        layout.addWidget(heading)

        actions = QHBoxLayout()
        self._compare_btn = QPushButton("Compare…")
        self._view_log_btn = QPushButton("View log…")
        self._export_json_btn = QPushButton("Export JSON…")
        self._export_csv_btn = QPushButton("Export CSV…")
        self._delete_btn = QPushButton("Delete")
        self._compare_btn.clicked.connect(self._open_compare)
        self._view_log_btn.clicked.connect(self._on_view_log)
        self._export_json_btn.clicked.connect(lambda: self._export(".json"))
        self._export_csv_btn.clicked.connect(lambda: self._export(".csv"))
        self._delete_btn.clicked.connect(self._delete)
        for button in (
            self._compare_btn,
            self._view_log_btn,
            self._export_json_btn,
            self._export_csv_btn,
            self._delete_btn,
        ):
            button.setEnabled(False)
            actions.addWidget(button)
        actions.addStretch(1)
        self._count_label = QLabel("")
        self._count_label.setObjectName("subtle")
        actions.addWidget(self._count_label)
        layout.addLayout(actions)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)

        self._table = QTableWidget(0, len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(list(_COLUMNS))
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(28)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        for column in (2, 3, 4, 6):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self._table.setColumnWidth(0, 160)
        self._table.setColumnWidth(1, 190)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        splitter.addWidget(self._table)

        self._detail = QPlainTextEdit()
        self._detail.setReadOnly(True)
        self._detail.setPlaceholderText("Select a session to preview it.")
        splitter.addWidget(self._detail)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        layout.addWidget(splitter, 1)
        self.refresh()

    # -- public API ---------------------------------------------------------------

    def refresh(self) -> None:
        """Reload the store into the table (also clears a stale selection)."""
        self._summaries = self._store.list()
        self._table.blockSignals(True)
        self._table.setRowCount(0)
        for summary in self._summaries:
            row = self._table.rowCount()
            self._table.insertRow(row)
            values = (
                _format_time(summary["generated_at"]),
                summary["vin"] or "—",
                str(summary["dtcs"]),
                str(summary["tests"]),
                str(summary["pids"]),
                summary["adapter"] or "—",
                f"{summary['log_rows']:,}" if summary.get("log_rows") else "—",
            )
            for column, text in enumerate(values):
                item = QTableWidgetItem(text)
                if column in (2, 3, 4, 6):
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                self._table.setItem(row, column, item)
        self._table.blockSignals(False)
        self._table.clearSelection()
        self._selected = None
        self._selected_log = None
        self._detail.clear()
        self._set_buttons_enabled(False)
        if self._summaries:
            self._count_label.setText(f"{len(self._summaries)} session(s)")
        else:
            self._count_label.setText("No saved sessions yet")
        # compare is selection-independent — it just needs a pair to pick from
        self._compare_btn.setEnabled(len(self._summaries) >= 2)

    def showEvent(self, event) -> None:  # noqa: N802 — Qt naming
        super().showEvent(event)
        self.refresh()

    # -- slots -------------------------------------------------------------------------

    def _on_selection_changed(self) -> None:
        rows = {index.row() for index in self._table.selectedIndexes()}
        row = rows.pop() if len(rows) == 1 else -1
        if row < 0 or row >= len(self._summaries):
            self._selected = None
            self._selected_log = None
            self._detail.clear()
            self._set_buttons_enabled(False)
            return
        self._selected = self._summaries[row]["name"]
        self._selected_log = str(self._summaries[row].get("log_file") or "") or None
        report = self._store.load(self._selected)
        self._detail.setPlainText(
            describe_report(report) if report is not None else "Session file unreadable."
        )
        self._set_buttons_enabled(report is not None)

    def _export(self, suffix: str) -> None:
        if self._selected is None:
            return
        default = f"{self._selected.removesuffix('.json')}{suffix}"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export session", default, _JSON_FILTER if suffix == ".json" else _CSV_FILTER
        )
        if path:
            self._store.export(self._selected, path)

    def _delete(self) -> None:
        if self._selected is None:
            return
        answer = QMessageBox.question(
            self,
            "Delete session",
            f"Delete {self._selected} permanently?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._store.delete(self._selected)
            self.refresh()

    def _on_view_log(self) -> None:
        if self._selected_log:
            self.view_log.emit(self._selected_log)

    def _open_compare(self) -> None:
        dialog = CompareDialog(self._store, baseline=self._selected, parent=self)
        dialog.exec()

    def _set_buttons_enabled(self, enabled: bool) -> None:
        self._view_log_btn.setEnabled(enabled and bool(self._selected_log))
        self._export_json_btn.setEnabled(enabled)
        self._export_csv_btn.setEnabled(enabled)
        self._delete_btn.setEnabled(enabled)


def _format_time(iso_text: str) -> str:
    try:
        moment = datetime.fromisoformat(iso_text)
    except ValueError:
        return iso_text or "—"
    local = moment.astimezone() if moment.tzinfo is not None else moment
    return local.strftime("%Y-%m-%d %H:%M:%S")
