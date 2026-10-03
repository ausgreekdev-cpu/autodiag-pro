"""Dashboard: live gauges, PID value table and scrolling graph."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from autodiag.obd.pids import PID_REGISTRY, request_pid
from autodiag.services.worker import ObdWorker
from autodiag.ui.prefs import Prefs
from autodiag.ui.widgets.gauge import Gauge
from autodiag.ui.widgets.graph import LiveGraph

# preferred parameters for the four headline gauges (by PID)
_GAUGE_PIDS = (0x0C, 0x0D, 0x05, 0x04)
_GAUGE_LABELS = ("Engine speed", "Vehicle speed", "Coolant temp", "Engine load")
_GAUGE_RANGES = {0x0C: (0.0, 8000.0), 0x0D: (0.0, 240.0), 0x05: (0.0, 130.0), 0x04: (0.0, 100.0)}

_COL_GRAPH, _COL_PID, _COL_NAME, _COL_VALUE, _COL_UNIT = range(5)


class DashboardPanel(QWidget):
    """Live-data hub: subscribes to the worker's PID signals itself."""

    def __init__(
        self,
        worker: ObdWorker,
        prefs: Prefs | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._worker = worker
        self._prefs = prefs if prefs is not None else Prefs()
        self._connected = False
        self._rows: dict[int, int] = {}  # pid → table row
        self._gauge_for_pid: dict[int, Gauge] = {}

        self._build_ui()
        # the restored interval must reach the engine even if untouched later
        self._worker.set_poll(None, self._interval_spin.value() / 1000.0)
        worker.connected.connect(self.on_connected)
        worker.disconnected.connect(self.on_disconnected)
        worker.pids_supported.connect(self.on_pids_supported)
        worker.pid_value.connect(self.on_pid_value)

    # -- construction -----------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(12)

        heading = QLabel("Live data")
        heading.setObjectName("heading")
        root.addWidget(heading)

        # gauges -------------------------------------------------------------
        gauge_row = QHBoxLayout()
        gauge_row.setSpacing(12)
        self._gauges: list[Gauge] = []
        for label, pid in zip(_GAUGE_LABELS, _GAUGE_PIDS, strict=True):
            definition = PID_REGISTRY.get(pid)
            minimum, maximum = _GAUGE_RANGES[pid]
            gauge = Gauge(
                label,
                definition.unit if definition else "",
                minimum=minimum,
                maximum=maximum,
                decimals=definition.decimals if definition else 0,
            )
            self._gauges.append(gauge)
            gauge_row.addWidget(gauge, 1)
        root.addLayout(gauge_row)

        # table + graph -------------------------------------------------------
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        table_box = QWidget()
        table_layout = QVBoxLayout(table_box)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setSpacing(8)

        controls = QHBoxLayout()
        self._interval_spin = QSpinBox()
        self._interval_spin.setRange(50, 5000)
        self._interval_spin.setSingleStep(50)
        self._interval_spin.setValue(self._prefs.poll_interval_ms())
        self._interval_spin.setSuffix(" ms")
        self._interval_spin.setToolTip("Delay between PID requests")
        self._interval_spin.valueChanged.connect(self._on_interval_changed)
        interval_label = QLabel("Poll interval")
        interval_label.setObjectName("subtle")
        controls.addWidget(interval_label)
        controls.addWidget(self._interval_spin)
        controls.addStretch(1)
        self._pid_count_label = QLabel("")
        self._pid_count_label.setObjectName("subtle")
        controls.addWidget(self._pid_count_label)
        table_layout.addLayout(controls)

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(["", "PID", "Parameter", "Value", "Unit"])
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(28)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(_COL_GRAPH, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(_COL_PID, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(_COL_NAME, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(_COL_VALUE, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(_COL_UNIT, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(_COL_GRAPH, 34)
        self._table.setColumnWidth(_COL_PID, 54)
        self._table.setColumnWidth(_COL_VALUE, 92)
        self._table.setColumnWidth(_COL_UNIT, 64)
        self._table.itemChanged.connect(self._on_item_changed)
        table_layout.addWidget(self._table)

        graph_box = QWidget()
        graph_layout = QVBoxLayout(graph_box)
        graph_layout.setContentsMargins(0, 0, 0, 0)
        graph_layout.setSpacing(8)
        graph_hint = QLabel("Tick parameters to graph them")
        graph_hint.setObjectName("subtle")
        graph_layout.addWidget(graph_hint)
        self._graph = LiveGraph()
        graph_layout.addWidget(self._graph, 1)

        splitter.addWidget(table_box)
        splitter.addWidget(graph_box)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        root.addWidget(splitter, 1)

        self._set_connected(False)

    # -- worker signal handlers ---------------------------------------------------

    def on_connected(self, info: object) -> None:
        self._connected = True
        self._graph.reset()
        self._set_connected(True)

    def on_disconnected(self, reason: str) -> None:
        self._connected = False
        self._clear_values()
        self._graph.reset()
        self._set_connected(False)

    def on_pids_supported(self, supported: set[int]) -> None:
        self._table.blockSignals(True)
        self._table.setRowCount(0)
        self._rows.clear()
        self._gauge_for_pid.clear()

        for pid in sorted(supported):
            definition = PID_REGISTRY[pid]
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._rows[pid] = row

            check = QTableWidgetItem()
            check.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsUserCheckable
            )
            check.setCheckState(Qt.CheckState.Unchecked)
            self._table.setItem(row, _COL_GRAPH, check)

            self._table.setItem(row, _COL_PID, QTableWidgetItem(f"{request_pid(pid):02X}"))
            self._table.setItem(row, _COL_NAME, QTableWidgetItem(definition.name))
            value_item = QTableWidgetItem("--")
            value_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            self._table.setItem(row, _COL_VALUE, value_item)
            self._table.setItem(row, _COL_UNIT, QTableWidgetItem(definition.unit))

            for gauge, gauge_pid in zip(self._gauges, _GAUGE_PIDS, strict=True):
                if pid == gauge_pid:
                    self._gauge_for_pid[pid] = gauge

        self._pid_count_label.setText(f"{len(supported)} parameters")
        self._table.blockSignals(False)

        # default graph selection: engine speed (when present)
        if 0x0C in self._rows:
            check_item = self._table.item(self._rows[0x0C], _COL_GRAPH)
            check_item.setCheckState(Qt.CheckState.Checked)  # fires itemChanged

    def on_pid_value(self, pid: int, value: float, timestamp: float) -> None:
        gauge = self._gauge_for_pid.get(pid)
        if gauge is not None:
            gauge.set_value(value)
        row = self._rows.get(pid)
        if row is not None:
            definition = PID_REGISTRY.get(pid)
            decimals = definition.decimals if definition else 1
            item = self._table.item(row, _COL_VALUE)
            if item is not None:
                item.setText(f"{value:.{decimals}f}")
        self._graph.add_point(pid, value, timestamp)

    # -- interactions --------------------------------------------------------------

    def parameter_count(self) -> int:
        return self._table.rowCount()

    def value_text(self, pid: int) -> str | None:
        row = self._rows.get(pid)
        if row is None:
            return None
        item = self._table.item(row, _COL_VALUE)
        return item.text() if item is not None else None

    def is_graphed(self, pid: int) -> bool:
        row = self._rows.get(pid)
        if row is None:
            return False
        item = self._table.item(row, _COL_GRAPH)
        return item is not None and item.checkState() == Qt.CheckState.Checked

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != _COL_GRAPH:
            return
        selected = [
            pid
            for pid, row in self._rows.items()
            if (check := self._table.item(row, _COL_GRAPH)) is not None
            and check.checkState() == Qt.CheckState.Checked
        ]
        self._graph.set_active(sorted(selected))

    def _on_interval_changed(self, value_ms: int) -> None:
        self._prefs.set_poll_interval_ms(value_ms)
        # safe while disconnected too: the engine just parks the new interval
        self._worker.set_poll(None, value_ms / 1000.0)

    # -- helpers ---------------------------------------------------------------------

    def _set_connected(self, connected: bool) -> None:
        self._interval_spin.setEnabled(connected)
        self._table.setEnabled(connected)

    def _clear_values(self) -> None:
        for row in self._rows.values():
            value_item = self._table.item(row, _COL_VALUE)
            if value_item is not None:
                value_item.setText("--")
        for gauge in self._gauges:
            gauge.set_value(None)
