"""Main window: connection toolbar, panel navigation, worker wiring."""

from __future__ import annotations

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QStatusBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from autodiag.obd.elm327 import SessionInfo
from autodiag.services.record import ScanRecord
from autodiag.services.worker import ObdWorker
from autodiag.transports.serial_transport import SerialPortInfo, list_serial_ports
from autodiag.ui.panels.dashboard import DashboardPanel
from autodiag.ui.panels.freeze import FreezeFramePanel
from autodiag.ui.panels.mode06 import Mode06Panel
from autodiag.ui.panels.readiness import ReadinessPanel
from autodiag.ui.panels.settings import SettingsPanel
from autodiag.ui.panels.trouble_codes import TroubleCodesPanel
from autodiag.ui.panels.vehicle import VehicleInfoPanel


class MainWindow(QMainWindow):
    """Shell around the diagnostic panels; owns the OBD worker."""

    def __init__(self, worker: ObdWorker | None = None) -> None:
        super().__init__()
        self.worker = worker or ObdWorker()
        self.record = ScanRecord()
        self._connected = False

        self.setWindowTitle("AutoDiag Pro")
        self.resize(1240, 820)
        self.setMinimumSize(960, 640)

        self._build_toolbar()
        self._build_central()
        self._build_statusbar()
        self._wire_worker()

    # -- construction -----------------------------------------------------------

    def _build_toolbar(self) -> None:
        bar = QToolBar("Connection")
        bar.setMovable(False)
        bar.setFloatable(False)
        self.addToolBar(bar)

        bar.addWidget(QLabel("Port "))
        self._port_combo = QComboBox()
        self._port_combo.setMinimumWidth(250)
        bar.addWidget(self._port_combo)

        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.clicked.connect(self.refresh_ports)
        bar.addWidget(self._refresh_btn)

        self._connect_btn = QPushButton("Connect")
        self._connect_btn.setObjectName("primary")
        self._connect_btn.clicked.connect(self._on_connect_clicked)
        bar.addWidget(self._connect_btn)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        bar.addWidget(spacer)

        self._chip = QLabel("--")
        self._chip.setObjectName("chip")
        bar.addWidget(self._chip)

        self._voltage_label = QLabel("-- V")
        self._voltage_label.setObjectName("chip")
        bar.addWidget(self._voltage_label)

        self.refresh_ports()

    def _build_central(self) -> None:
        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._stack = QStackedWidget()
        self._dashboard = DashboardPanel(self.worker)
        self._stack.addWidget(self._dashboard)
        self._stack.addWidget(TroubleCodesPanel(self.worker))
        self._stack.addWidget(ReadinessPanel(self.worker))
        self._stack.addWidget(FreezeFramePanel(self.worker))
        self._stack.addWidget(VehicleInfoPanel(self.worker))
        self._stack.addWidget(Mode06Panel(self.worker))
        self._stack.addWidget(
            SettingsPanel(self.record, lambda msg: self.statusBar().showMessage(msg, 8000))
        )

        nav_items = (
            "Dashboard",
            "Trouble codes",
            "Readiness",
            "Freeze frame",
            "Vehicle info",
            "Mode $06",
            "Settings",
        )
        nav = QWidget()
        nav.setFixedWidth(184)
        nav_layout = QVBoxLayout(nav)
        nav_layout.setContentsMargins(8, 12, 8, 12)
        nav_layout.setSpacing(2)
        self._nav_buttons: list[QPushButton] = []
        for index, name in enumerate(nav_items):
            button = QPushButton(name)
            button.setObjectName("nav")
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, i=index: self.show_panel(i))
            nav_layout.addWidget(button)
            self._nav_buttons.append(button)
        nav_layout.addStretch(1)
        self._nav_buttons[0].setChecked(True)

        layout.addWidget(nav)
        layout.addWidget(self._stack, 1)
        self.setCentralWidget(central)

    def _build_statusbar(self) -> None:
        status = QStatusBar()
        status.setSizeGripEnabled(False)
        self.setStatusBar(status)
        status.showMessage("Ready — select a port and connect.", 0)

    def _wire_worker(self) -> None:
        worker = self.worker
        worker.status.connect(lambda msg: self.statusBar().showMessage(msg, 5000))
        worker.error.connect(lambda msg: self.statusBar().showMessage(f"Error: {msg}", 8000))
        worker.connected.connect(self._on_connected)
        worker.disconnected.connect(self._on_disconnected)
        worker.voltage.connect(self._on_voltage)

        # feed the exportable scan record (same events the panels consume)
        record = self.record.record_event
        worker.connected.connect(lambda info: record("connected", (info,)))
        worker.disconnected.connect(lambda reason: record("disconnected", (reason,)))
        worker.pid_value.connect(lambda pid, value, ts: record("pid_value", (pid, value, ts)))
        worker.dtcs.connect(lambda source, codes: record("dtcs", (source, codes)))
        worker.monitors.connect(lambda status: record("monitors", (status,)))
        worker.vehicle.connect(lambda info: record("vehicle", (info,)))
        worker.freeze_all.connect(
            lambda frame, values: record("freeze_all", (frame, values))
        )
        worker.mode06.connect(lambda results: record("mode06", (results,)))

    # -- public API --------------------------------------------------------------

    def show_panel(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        for i, button in enumerate(self._nav_buttons):
            button.setChecked(i == index)

    def refresh_ports(self) -> None:
        current = self._port_combo.currentData()
        self._port_combo.clear()
        ports: list[SerialPortInfo] = list_serial_ports()
        for port in ports:
            self._port_combo.addItem(str(port), port.device)
        if not ports:
            self._port_combo.addItem("No serial ports found", None)
        if current is not None:
            index = self._port_combo.findData(current)
            if index >= 0:
                self._port_combo.setCurrentIndex(index)

    # -- slots --------------------------------------------------------------------

    def _on_connect_clicked(self) -> None:
        if self._connected:
            self.worker.disconnect_from()
            return
        device = self._port_combo.currentData()
        if not device:
            self.statusBar().showMessage(
                "No serial port selected — plug in the adapter and press Refresh.", 8000
            )
            return
        self._connect_btn.setEnabled(False)
        self._connect_btn.setText("Connecting…")
        self.statusBar().showMessage(f"Connecting to {device}…", 0)
        self.worker.connect_to(device)

    def _on_connected(self, info: SessionInfo) -> None:
        self._connected = True
        self._connect_btn.setEnabled(True)
        self._connect_btn.setText("Disconnect")
        self._port_combo.setEnabled(False)
        self._refresh_btn.setEnabled(False)
        detail = info.protocol or "protocol unknown"
        self._chip.setText(f"{info.adapter} · {detail}")
        self._chip.setProperty("data-live", "1")
        self._chip.style().unpolish(self._chip)
        self._chip.style().polish(self._chip)
        self.statusBar().showMessage("Connected.", 5000)

    def _on_disconnected(self, reason: str) -> None:
        self._connected = False
        self._connect_btn.setEnabled(True)
        self._connect_btn.setText("Connect")
        self._port_combo.setEnabled(True)
        self._refresh_btn.setEnabled(True)
        self._chip.setText("--")
        self._chip.setProperty("data-live", "0")
        self._chip.style().unpolish(self._chip)
        self._chip.style().polish(self._chip)
        self._voltage_label.setText("-- V")
        self.statusBar().showMessage(reason, 8000)

    def _on_voltage(self, volts: float) -> None:
        self._voltage_label.setText(f"{volts:.1f} V")

    # -- lifecycle ------------------------------------------------------------------

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 — Qt naming
        self.statusBar().showMessage("Shutting down…", 0)
        self.worker.shutdown(5000)
        event.accept()
