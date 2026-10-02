"""Freeze-frame panel: sensor snapshot captured when a fault was set."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from autodiag.obd.pids import PID_REGISTRY
from autodiag.services.worker import ObdWorker


class FreezeFramePanel(QWidget):
    def __init__(self, worker: ObdWorker, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._worker = worker
        self._frames: dict[int, dict[int, float]] = {}

        self._build_ui()
        worker.connected.connect(lambda _info: self._read_btn.setEnabled(True))
        worker.disconnected.connect(lambda _reason: self._reset())
        worker.freeze_all.connect(self.on_freeze_all)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        heading = QLabel("Freeze frame")
        heading.setObjectName("heading")
        layout.addWidget(heading)

        actions = QHBoxLayout()
        actions.addWidget(QLabel("Frame"))
        self._frame_combo = QComboBox()
        self._frame_combo.addItems(["0", "1", "2"])
        self._frame_combo.currentIndexChanged.connect(lambda _index: self._show_frame())
        actions.addWidget(self._frame_combo)
        self._read_btn = QPushButton("Read freeze frame")
        self._read_btn.setEnabled(False)
        self._read_btn.clicked.connect(
            lambda: self._worker.read_freeze_all(self._frame_combo.currentIndex())
        )
        actions.addWidget(self._read_btn)
        actions.addStretch(1)
        layout.addLayout(actions)

        self._hint = QLabel(
            "The freeze frame is the sensor snapshot recorded when a fault was set."
        )
        self._hint.setObjectName("subtle")
        layout.addWidget(self._hint)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["PID", "Parameter", "Value", "Unit"])
        self._table.setAlternatingRowColors(True)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(28)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(0, 54)
        self._table.setColumnWidth(2, 110)
        self._table.setColumnWidth(3, 70)
        layout.addWidget(self._table, 1)

    # -- worker handlers ------------------------------------------------------------

    def on_freeze_all(self, frame: int, values: dict[int, float]) -> None:
        self._frames[frame] = values
        self._frame_combo.setCurrentIndex(frame)
        self._show_frame()

    def _show_frame(self) -> None:
        frame = self._frame_combo.currentIndex()
        values = self._frames.get(frame, {})
        self._table.setRowCount(0)
        for pid in sorted(values):
            definition = PID_REGISTRY.get(pid)
            if definition is None:
                continue
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(f"{pid:02X}"))
            self._table.setItem(row, 1, QTableWidgetItem(definition.name))
            value_item = QTableWidgetItem(f"{values[pid]:.{definition.decimals}f}")
            value_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            self._table.setItem(row, 2, value_item)
            self._table.setItem(row, 3, QTableWidgetItem(definition.unit))
        if values:
            self._hint.setText(
                f"Frame {frame} — snapshot with {len(values)} parameter(s)."
            )
        elif frame in self._frames:
            self._hint.setText("No freeze frame is stored (or the vehicle reported none).")
        else:
            self._hint.setText(
                f"Frame {frame} has not been read yet — press Read freeze frame."
            )

    def _reset(self) -> None:
        self._frames.clear()
        self._frame_combo.setCurrentIndex(0)
        self._table.setRowCount(0)
        self._read_btn.setEnabled(False)
        self._hint.setText(
            "The freeze frame is the sensor snapshot recorded when a fault was set."
        )
