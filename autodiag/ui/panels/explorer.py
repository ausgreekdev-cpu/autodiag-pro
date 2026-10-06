"""PID explorer: request any parameter on demand and inspect the response."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
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

from autodiag.obd import pids as pid_dec
from autodiag.obd.pids import PID_REGISTRY, describe_pid, request_pid
from autodiag.services.worker import ObdWorker

_MAX_ROWS = 200


class PidExplorerPanel(QWidget):
    """One-shot requests with raw response + decoded value side by side."""

    graph_pid = Signal(int)  # ask MainWindow to tick this PID in the dashboard

    def __init__(self, worker: ObdWorker, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._worker = worker
        self._connected = False
        self._supported: set[int] = set()

        self._build_ui()
        worker.connected.connect(lambda _info: self._set_connected(True))
        worker.disconnected.connect(lambda _reason: self._set_connected(False))
        worker.pids_supported.connect(self.on_pids_supported)
        worker.pid_response.connect(self.on_pid_response)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        heading = QLabel("PID explorer")
        heading.setObjectName("heading")
        layout.addWidget(heading)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self._pid_combo = QComboBox()
        self._pid_combo.setToolTip("Parameter to request")
        actions.addWidget(self._pid_combo, 1)
        self._force_chk = QCheckBox("Force")
        self._force_chk.setToolTip(
            "Send the request even if the vehicle does not report this PID as supported"
        )
        actions.addWidget(self._force_chk)
        self._request_btn = QPushButton("Request")
        self._request_btn.clicked.connect(self._on_request)
        actions.addWidget(self._request_btn)
        self._graph_btn = QPushButton("Graph this PID")
        self._graph_btn.setToolTip("Tick this parameter in the dashboard graph")
        self._graph_btn.clicked.connect(self._on_graph)
        actions.addWidget(self._graph_btn)
        layout.addLayout(actions)

        self._hint = QLabel("Connect to list the vehicle's supported parameters.")
        self._hint.setObjectName("subtle")
        layout.addWidget(self._hint)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(("Time", "PID", "Response", "Value"))
        self._table.setAlternatingRowColors(True)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(0, 76)
        self._table.setColumnWidth(1, 52)
        self._table.setColumnWidth(3, 240)
        layout.addWidget(self._table, 1)

        self._set_connected(False)

    # -- worker signal handlers ------------------------------------------------

    def on_pids_supported(self, supported: set[int]) -> None:
        previous = self._pid_combo.currentData()
        self._supported = set(supported)
        self._pid_combo.blockSignals(True)
        self._pid_combo.clear()
        for pid in sorted(self._supported):
            self._pid_combo.addItem(self._label(pid), pid)
        # unsupported, but still requestable with Force (companions excluded:
        # they only mean something when the vehicle advertises them)
        for pid in sorted(
            p for p in PID_REGISTRY if p not in self._supported and request_pid(p) == p
        ):
            self._pid_combo.addItem(f"{self._label(pid)} (unsupported)", pid)
        self._pid_combo.blockSignals(False)
        if previous is not None:
            index = self._pid_combo.findData(previous)
            if index >= 0:
                self._pid_combo.setCurrentIndex(index)
        self._hint.setText(
            f"{len(self._supported)} parameters supported by this vehicle."
        )

    def on_pid_response(self, pid: int, text: str) -> None:
        values = pid_dec.parse_pid_values(text, pid)
        rendered = "; ".join(
            f"{self._channel_name(channel)}: {value:g}"
            + (f" {getattr(PID_REGISTRY.get(channel), 'unit', '')}".rstrip())
            for channel, value in values.items()
        )
        self._table.insertRow(0)
        self._table.setItem(0, 0, QTableWidgetItem(datetime.now().strftime("%H:%M:%S")))
        self._table.setItem(0, 1, QTableWidgetItem(f"{pid:02X}"))
        self._table.setItem(0, 2, QTableWidgetItem(" ".join(text.split())))
        self._table.setItem(
            0, 3, QTableWidgetItem(rendered or "no decodable value")
        )
        while self._table.rowCount() > _MAX_ROWS:
            self._table.removeRow(self._table.rowCount() - 1)
        self._table.scrollToTop()

    # -- interactions ----------------------------------------------------------

    def _on_request(self) -> None:
        pid = self._pid_combo.currentData()
        if pid is None:
            return
        if pid not in self._supported and not self._force_chk.isChecked():
            self._hint.setText("That PID is unsupported — tick Force to send it anyway.")
            return
        self._worker.request_pid(pid)

    def _on_graph(self) -> None:
        pid = self._pid_combo.currentData()
        if pid is not None:
            self.graph_pid.emit(pid)

    def _set_connected(self, connected: bool) -> None:
        self._connected = connected
        self._request_btn.setEnabled(connected)
        self._graph_btn.setEnabled(connected)
        self._force_chk.setEnabled(connected)
        if not connected:
            self._hint.setText("Connect to list the vehicle's supported parameters.")

    @staticmethod
    def _label(pid: int) -> str:
        return describe_pid(pid)

    def _channel_name(self, channel: int) -> str:
        definition = PID_REGISTRY.get(channel)
        return getattr(definition, "name", None) or f"PID {channel:02X}"
