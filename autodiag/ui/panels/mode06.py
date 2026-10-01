"""Mode $06 panel: on-board monitoring test results (min/value/max)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from autodiag.obd.mode06 import TestResult
from autodiag.services.worker import ObdWorker
from autodiag.ui import theme

_COLUMNS = ("Monitor", "TID", "Value", "Min", "Max", "Unit", "Result")


class Mode06Panel(QWidget):
    def __init__(self, worker: ObdWorker, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._worker = worker

        self._build_ui()
        worker.connected.connect(lambda _info: self._read_btn.setEnabled(True))
        worker.disconnected.connect(lambda _reason: self._reset())
        worker.mode06.connect(self.on_mode06)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        heading = QLabel("Mode $06 — onboard tests")
        heading.setObjectName("heading")
        layout.addWidget(heading)

        actions = QHBoxLayout()
        self._read_btn = QPushButton("Read test results")
        self._read_btn.setEnabled(False)
        self._read_btn.clicked.connect(lambda: self._worker.read_mode06())
        actions.addWidget(self._read_btn)
        actions.addStretch(1)
        self._count_label = QLabel("")
        self._count_label.setObjectName("subtle")
        actions.addWidget(self._count_label)
        layout.addLayout(actions)

        self._hint = QLabel(
            "Live test results with the limits the ECU used to judge them."
        )
        self._hint.setObjectName("subtle")
        layout.addWidget(self._hint)

        self._table = QTableWidget(0, len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(list(_COLUMNS))
        self._table.setAlternatingRowColors(True)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(28)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3, 4, 5, 6):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self._table, 1)

    # -- worker handlers ---------------------------------------------------------------

    def on_mode06(self, results: list[TestResult]) -> None:
        self._table.setRowCount(0)
        passed = failed = 0
        for result in results:
            row = self._table.rowCount()
            self._table.insertRow(row)
            values = (
                result.monitor_name,
                f"{result.tid:02X}",
                f"{result.value:g}",
                f"{result.min_value:g}",
                f"{result.max_value:g}",
                result.unit,
                _label(result.passed),
            )
            for column, text in enumerate(values):
                item = QTableWidgetItem(text)
                if column >= 2:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                self._table.setItem(row, column, item)
            if result.passed is True:
                passed += 1
            elif result.passed is False:
                failed += 1
                for column in range(len(values)):
                    cell = self._table.item(row, column)
                    if cell is not None:
                        cell.setForeground(QBrush(QColor(theme.DANGER)))
        self._count_label.setText(f"{len(results)} test(s)")
        if failed:
            self._hint.setText(f"{failed} test(s) outside limits, {passed} passed.")
            self._hint.setStyleSheet(f"color: {theme.DANGER};")
        elif results:
            self._hint.setText(f"All completed tests passed ({passed}).")
            self._hint.setStyleSheet(f"color: {theme.OK};")
        else:
            self._hint.setText("The vehicle reported no Mode $06 records.")
            self._hint.setStyleSheet("")

    def _reset(self) -> None:
        self._table.setRowCount(0)
        self._read_btn.setEnabled(False)
        self._count_label.setText("")
        self._hint.setStyleSheet("")


def _label(passed: bool | None) -> str:
    if passed is None:
        return "NOT RUN"
    return "PASS" if passed else "FAIL"
