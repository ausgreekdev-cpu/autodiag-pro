"""Mode $05 panel: oxygen-sensor monitor test results (non-CAN buses)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from autodiag.obd.mode05 import TestResult
from autodiag.services.worker import ObdWorker
from autodiag.ui import theme

_COLUMNS = ("Sensor", "Test", "Value", "Min", "Max", "Unit", "Result")


class Mode05Panel(QWidget):
    def __init__(self, worker: ObdWorker, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._worker = worker
        self._results: list[TestResult] = []

        self._build_ui()
        worker.connected.connect(lambda _info: self._read_btn.setEnabled(True))
        worker.disconnected.connect(lambda _reason: self._reset())
        worker.mode05.connect(self.on_mode05)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        heading = QLabel("Mode $05 — O2 sensor tests")
        heading.setObjectName("heading")
        layout.addWidget(heading)

        actions = QHBoxLayout()
        self._read_btn = QPushButton("Read test results")
        self._read_btn.setEnabled(False)
        self._read_btn.clicked.connect(lambda: self._worker.read_mode05())
        actions.addWidget(self._read_btn)
        self._only_failures = QCheckBox("Only failures")
        self._only_failures.toggled.connect(lambda _on: self._render())
        actions.addWidget(self._only_failures)
        actions.addStretch(1)
        self._count_label = QLabel("")
        self._count_label.setObjectName("subtle")
        actions.addWidget(self._count_label)
        layout.addLayout(actions)

        self._hint = QLabel(
            "Oxygen-sensor monitor tests — ISO 9141 / J1850 / KWP buses only "
            "(on CAN, these tests are reported in Mode $06)."
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
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column in (0, 2, 3, 4, 5, 6):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self._table, 1)

    # -- worker handlers ---------------------------------------------------

    def on_mode05(self, results: list[TestResult]) -> None:
        self._results = list(results)
        self._render()

    def _render(self) -> None:
        results = self._results
        shown = (
            [r for r in results if r.passed is False]
            if self._only_failures.isChecked()
            else results
        )
        passed = sum(1 for r in results if r.passed is True)
        failed = sum(1 for r in results if r.passed is False)

        self._table.setRowCount(0)
        for result in shown:
            row = self._table.rowCount()
            self._table.insertRow(row)
            values = (
                result.sensor_label,
                result.test_name,
                f"{result.value:g}",
                "—" if result.min_value is None else f"{result.min_value:g}",
                "—" if result.max_value is None else f"{result.max_value:g}",
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
            if result.passed is False:
                for column in range(len(values)):
                    cell = self._table.item(row, column)
                    if cell is not None:
                        cell.setForeground(QBrush(QColor(theme.DANGER)))

        if not results:
            self._count_label.setText("")
        elif len(shown) == len(results):
            self._count_label.setText(f"{len(results)} test(s)")
        else:
            self._count_label.setText(f"{len(shown)} / {len(results)} test(s)")

        # the summary always describes the full set, filtered or not
        if failed:
            self._hint.setText(f"{failed} test(s) outside limits, {passed} passed.")
            self._hint.setStyleSheet(f"color: {theme.DANGER};")
        elif passed:
            self._hint.setText(f"All completed tests passed ({passed}).")
            self._hint.setStyleSheet(f"color: {theme.OK};")
        elif results:
            self._hint.setText(
                f"{len(results)} result(s) recorded — no limits to compare."
            )
            self._hint.setStyleSheet("")
        else:
            self._hint.setText("The vehicle reported no Mode $05 results.")
            self._hint.setStyleSheet("")

    def _reset(self) -> None:
        self._table.setRowCount(0)
        self._results = []
        self._read_btn.setEnabled(False)
        self._count_label.setText("")
        self._hint.setStyleSheet("")


def _label(passed: bool | None) -> str:
    if passed is None:
        return "NOT RUN"
    return "PASS" if passed else "FAIL"
