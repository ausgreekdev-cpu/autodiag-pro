"""Threshold alerts: per-PID limits, breach events, CSV export."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from autodiag.obd.pids import PID_REGISTRY, describe_pid, request_pid
from autodiag.services.alerts import MAX_EVENTS, AlertEvent, AlertLog, Threshold
from autodiag.services.record import ScanRecord
from autodiag.services.worker import ObdWorker

_CSV_FILTER = "CSV files (*.csv);;All files (*)"
_TCOL_PID, _TCOL_NAME, _TCOL_LOW, _TCOL_HIGH = range(4)
_ECOL_TIME, _ECOL_PID, _ECOL_NAME, _ECOL_VALUE, _ECOL_LIMIT = range(5)


class AlertsPanel(QWidget):
    """Edit watch thresholds and review the breach event history."""

    thresholds_changed = Signal()  # watchlist edited (MainWindow persists it)

    def __init__(
        self,
        worker: ObdWorker,
        record: ScanRecord,
        alert_log: AlertLog,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._record = record
        self._log = alert_log
        self._watchlist = alert_log.watchlist
        self._supported: set[int] = set()

        self._build_ui()
        self._rebuild_combo()
        self._refresh_thresholds()
        worker.pids_supported.connect(self.on_pids_supported)

    # -- construction -----------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(12)

        heading = QLabel("Threshold alerts")
        heading.setObjectName("heading")
        root.addWidget(heading)

        hint = QLabel(
            "Watch live values against a limit — crossings are flagged on the "
            "dashboard and logged here."
        )
        hint.setObjectName("subtle")
        hint.setWordWrap(True)
        root.addWidget(hint)
        self._hint = QLabel("")
        self._hint.setObjectName("subtle")
        root.addWidget(self._hint)

        # threshold editor ----------------------------------------------------
        editor = QHBoxLayout()
        editor.setSpacing(8)
        self._pid_combo = QComboBox()
        self._pid_combo.setMinimumWidth(240)
        editor.addWidget(self._pid_combo, 1)
        self._low_chk = QCheckBox("Min")
        editor.addWidget(self._low_chk)
        self._low_spin = QDoubleSpinBox()
        self._low_spin.setRange(-10000.0, 1000000.0)
        self._low_spin.setDecimals(1)
        editor.addWidget(self._low_spin)
        self._high_chk = QCheckBox("Max")
        editor.addWidget(self._high_chk)
        self._high_spin = QDoubleSpinBox()
        self._high_spin.setRange(-10000.0, 1000000.0)
        self._high_spin.setDecimals(1)
        editor.addWidget(self._high_spin)
        self._set_btn = QPushButton("Set")
        self._set_btn.setObjectName("primary")
        self._set_btn.clicked.connect(self._on_set)
        editor.addWidget(self._set_btn)
        root.addLayout(editor)

        # active thresholds ---------------------------------------------------
        self._thresholds_table = QTableWidget(0, 4)
        self._thresholds_table.setHorizontalHeaderLabels(
            ("PID", "Parameter", "Min", "Max")
        )
        self._thresholds_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self._thresholds_table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection
        )
        self._thresholds_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self._thresholds_table.verticalHeader().setVisible(False)
        header = self._thresholds_table.horizontalHeader()
        header.setSectionResizeMode(_TCOL_NAME, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(_TCOL_PID, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(_TCOL_LOW, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(_TCOL_HIGH, QHeaderView.ResizeMode.Fixed)
        self._thresholds_table.setColumnWidth(_TCOL_PID, 54)
        self._thresholds_table.setColumnWidth(_TCOL_LOW, 90)
        self._thresholds_table.setColumnWidth(_TCOL_HIGH, 90)
        self._thresholds_table.itemSelectionChanged.connect(
            lambda: self._remove_btn.setEnabled(
                self._thresholds_table.currentRow() >= 0
            )
        )
        root.addWidget(self._thresholds_table, 1)

        threshold_buttons = QHBoxLayout()
        self._remove_btn = QPushButton("Remove")
        self._remove_btn.setEnabled(False)
        self._remove_btn.clicked.connect(self._on_remove)
        threshold_buttons.addWidget(self._remove_btn)
        threshold_buttons.addStretch(1)
        root.addLayout(threshold_buttons)

        # events ---------------------------------------------------------------
        events_heading = QLabel("Events")
        events_heading.setObjectName("subtle")
        root.addWidget(events_heading)

        self._events_table = QTableWidget(0, 5)
        self._events_table.setHorizontalHeaderLabels(
            ("Time", "PID", "Parameter", "Value", "Limit")
        )
        self._events_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self._events_table.verticalHeader().setVisible(False)
        header = self._events_table.horizontalHeader()
        header.setSectionResizeMode(_ECOL_NAME, QHeaderView.ResizeMode.Stretch)
        for column in (_ECOL_TIME, _ECOL_PID, _ECOL_VALUE, _ECOL_LIMIT):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        root.addWidget(self._events_table, 2)

        event_buttons = QHBoxLayout()
        self._clear_btn = QPushButton("Clear")
        self._clear_btn.clicked.connect(self._on_clear)
        event_buttons.addWidget(self._clear_btn)
        self._export_btn = QPushButton("Export CSV…")
        self._export_btn.clicked.connect(self._on_export)
        event_buttons.addWidget(self._export_btn)
        event_buttons.addStretch(1)
        root.addLayout(event_buttons)

    # -- worker signal handlers ------------------------------------------------

    def on_pids_supported(self, supported: set[int]) -> None:
        self._supported = set(supported)
        self._rebuild_combo()

    def _rebuild_combo(self) -> None:
        previous = self._pid_combo.currentData()
        self._pid_combo.blockSignals(True)
        self._pid_combo.clear()
        if self._supported:
            for pid in sorted(self._supported):
                self._pid_combo.addItem(describe_pid(pid), pid)
            for pid in sorted(
                p for p in PID_REGISTRY if p not in self._supported and request_pid(p) == p
            ):
                self._pid_combo.addItem(f"{describe_pid(pid)} (unsupported)", pid)
        else:
            # before connecting: the whole registry, pre-configuration friendly
            for pid in sorted(PID_REGISTRY):
                self._pid_combo.addItem(describe_pid(pid), pid)
        self._pid_combo.blockSignals(False)
        if previous is not None:
            index = self._pid_combo.findData(previous)
            if index >= 0:
                self._pid_combo.setCurrentIndex(index)

    # -- events (called by MainWindow on every breach) -------------------------

    def append_event(self, event: AlertEvent) -> None:
        definition = PID_REGISTRY.get(event.pid)
        decimals = definition.decimals if definition else 1
        self._events_table.insertRow(0)
        self._events_table.setItem(0, _ECOL_TIME, QTableWidgetItem(event.at.strftime("%H:%M:%S")))
        self._events_table.setItem(0, _ECOL_PID, QTableWidgetItem(f"{event.pid:02X}"))
        self._events_table.setItem(
            0, _ECOL_NAME, QTableWidgetItem(describe_pid(event.pid))
        )
        self._events_table.setItem(
            0, _ECOL_VALUE, QTableWidgetItem(f"{event.value:.{decimals}f}")
        )
        limit = (
            f"{event.limit:.{decimals}f}" if event.limit is not None else ""
        )
        self._events_table.setItem(0, _ECOL_LIMIT, QTableWidgetItem(limit))
        while self._events_table.rowCount() > MAX_EVENTS:
            self._events_table.removeRow(self._events_table.rowCount() - 1)
        self._events_table.scrollToTop()

    # -- interactions ----------------------------------------------------------

    def _on_set(self) -> None:
        pid = self._pid_combo.currentData()
        if pid is None:
            return
        low = self._low_spin.value() if self._low_chk.isChecked() else None
        high = self._high_spin.value() if self._high_chk.isChecked() else None
        if low is None and high is None:
            self._hint.setText("Tick Min and/or Max to define a limit.")
            return
        if low is not None and high is not None and low >= high:
            self._hint.setText("Min must be below Max.")
            return
        self._watchlist.set(Threshold(pid, low, high))
        # seed from the last known reading so an already-breaching value flags now
        latest = self._record.pids.get(pid)
        if latest is not None:
            self._log.evaluate(pid, latest[0], latest[1])
        self._refresh_thresholds(select=pid)
        self.thresholds_changed.emit()
        self._hint.setText(f"Watching {describe_pid(pid)}.")

    def _on_remove(self) -> None:
        row = self._thresholds_table.currentRow()
        if row < 0:
            return
        item = self._thresholds_table.item(row, _TCOL_PID)
        if item is None:
            return
        pid = int(item.data(Qt.ItemDataRole.UserRole))
        self._watchlist.remove(pid)
        self._refresh_thresholds()
        self.thresholds_changed.emit()
        self._hint.setText(f"Stopped watching {describe_pid(pid)}.")

    def _on_clear(self) -> None:
        self._log.clear()
        self._events_table.setRowCount(0)
        self._hint.setText("Event history cleared.")

    def _on_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export alert events", "autodiag-alerts.csv", _CSV_FILTER
        )
        if path:
            target = self._log.export_csv(path)
            self._hint.setText(f"Written to {target}")

    # -- helpers ---------------------------------------------------------------

    def _refresh_thresholds(self, select: int | None = None) -> None:
        self._thresholds_table.setRowCount(0)
        for threshold in self._watchlist.thresholds():
            row = self._thresholds_table.rowCount()
            self._thresholds_table.insertRow(row)
            pid_item = QTableWidgetItem(f"{threshold.pid:02X}")
            pid_item.setData(Qt.ItemDataRole.UserRole, threshold.pid)
            self._thresholds_table.setItem(row, _TCOL_PID, pid_item)
            definition = PID_REGISTRY.get(threshold.pid)
            name = definition.name if definition else describe_pid(threshold.pid)
            self._thresholds_table.setItem(row, _TCOL_NAME, QTableWidgetItem(name))
            low = "" if threshold.low is None else f"{threshold.low:g}"
            high = "" if threshold.high is None else f"{threshold.high:g}"
            self._thresholds_table.setItem(row, _TCOL_LOW, QTableWidgetItem(low))
            self._thresholds_table.setItem(row, _TCOL_HIGH, QTableWidgetItem(high))
            if select is not None and threshold.pid == select:
                self._thresholds_table.selectRow(row)
        if self._thresholds_table.currentRow() < 0:
            self._remove_btn.setEnabled(False)
