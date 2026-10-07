"""Main window: connection toolbar, panel navigation, worker wiring."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QCheckBox,
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
from autodiag.obd.pids import PID_REGISTRY, describe_pid
from autodiag.services.alerts import AlertEvent, AlertLog, Threshold, Watchlist
from autodiag.services.export import build_report
from autodiag.services.history import SessionStore, record_has_data
from autodiag.services.live_log import LiveLog
from autodiag.services.record import ScanRecord
from autodiag.services.worker import ObdWorker
from autodiag.transports.serial_transport import SerialPortInfo, list_serial_ports
from autodiag.ui.icons import app_icon
from autodiag.ui.panels.alerts import AlertsPanel
from autodiag.ui.panels.dashboard import DashboardPanel
from autodiag.ui.panels.explorer import PidExplorerPanel
from autodiag.ui.panels.freeze import FreezeFramePanel
from autodiag.ui.panels.history import HistoryPanel
from autodiag.ui.panels.log_viewer import LogViewerPanel
from autodiag.ui.panels.mode06 import Mode06Panel
from autodiag.ui.panels.overview import OverviewPanel
from autodiag.ui.panels.readiness import ReadinessPanel
from autodiag.ui.panels.settings import SettingsPanel
from autodiag.ui.panels.trouble_codes import TroubleCodesPanel
from autodiag.ui.panels.vehicle import VehicleInfoPanel
from autodiag.ui.prefs import Prefs

# Stack index of the Overview panel — the launch default when the user has no
# saved panel choice. Must match its position in nav_items (asserted by tests).
OVERVIEW_PANEL = 10


class MainWindow(QMainWindow):
    """Shell around the diagnostic panels; owns the OBD worker."""

    def __init__(
        self,
        worker: ObdWorker | None = None,
        prefs: Prefs | None = None,
        store: SessionStore | None = None,
    ) -> None:
        super().__init__()
        self.worker = worker or ObdWorker()
        self.record = ScanRecord()
        self._prefs = prefs if prefs is not None else Prefs()
        self._store = store if store is not None else SessionStore()
        self._connected = False
        # logs live beside the sessions; armed from prefs (default on)
        self._live_log = LiveLog(
            Path(self._store.directory) / "logs",
            on_change=self._on_log_change,
            on_error=lambda msg: self.statusBar().showMessage(msg, 8000),
        )
        self._live_log.set_armed(self._prefs.auto_log())

        # threshold watchlist (persists across launches) + breach event history
        self._alert_log = AlertLog(
            Watchlist(
                {
                    pid: Threshold(pid, low, high)
                    for pid, (low, high) in self._prefs.watchlist().items()
                }
            ),
            on_event=self._on_alert_event,
        )

        self.setWindowTitle("AutoDiag Pro")
        self.setWindowIcon(app_icon())
        self.resize(1240, 820)
        self.setMinimumSize(960, 640)

        self._build_toolbar()
        self._build_central()
        self._build_statusbar()
        self._wire_worker()
        self._restore_prefs()

    # -- construction -----------------------------------------------------------

    def _build_toolbar(self) -> None:
        bar = QToolBar("Connection")
        bar.setObjectName("Connection")
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

        self._auto_chk = QCheckBox("Auto")
        self._auto_chk.setToolTip("Reconnect to the last port on launch")
        self._auto_chk.setChecked(self._prefs.auto_connect())
        self._auto_chk.toggled.connect(self._prefs.set_auto_connect)
        bar.addWidget(self._auto_chk)

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
        self._dashboard = DashboardPanel(self.worker, self._prefs)
        self._stack.addWidget(self._dashboard)
        self._stack.addWidget(TroubleCodesPanel(self.worker))
        self._stack.addWidget(ReadinessPanel(self.worker))
        self._stack.addWidget(FreezeFramePanel(self.worker))
        self._stack.addWidget(VehicleInfoPanel(self.worker))
        self._stack.addWidget(Mode06Panel(self.worker))
        self._stack.addWidget(
            SettingsPanel(
                self.record,
                lambda msg: self.statusBar().showMessage(msg, 8000),
                prefs=self._prefs,
                on_protocol=self.worker.set_protocol,
            )
        )
        self._history = HistoryPanel(self._store)
        self._stack.addWidget(self._history)
        self._viewer = LogViewerPanel(Path(self._store.directory) / "logs")
        self._stack.addWidget(self._viewer)
        self._explorer = PidExplorerPanel(self.worker)
        self._stack.addWidget(self._explorer)
        self._explorer.graph_pid.connect(
            lambda pid: self._dashboard.set_graphed(pid, True)
        )
        self._overview = OverviewPanel(
            self.worker, self.record, self._store, goto=self.show_panel
        )
        self._stack.addWidget(self._overview)
        self._alerts = AlertsPanel(self.worker, self.record, self._alert_log)
        self._stack.addWidget(self._alerts)
        self._alerts.thresholds_changed.connect(self._on_thresholds_changed)

        nav_items = (
            "Dashboard",
            "Trouble codes",
            "Readiness",
            "Freeze frame",
            "Vehicle info",
            "Mode $06",
            "Settings",
            "History",
            "Log viewer",
            "PID explorer",
            "Overview",
            "Alerts",
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
        self._state_label = QLabel("Ready")
        self._state_label.setObjectName("conn-state")
        status.addWidget(self._state_label)
        status.showMessage("Ready — select a port and connect.", 0)

    def _wire_worker(self) -> None:
        worker = self.worker
        worker.status.connect(lambda msg: self.statusBar().showMessage(msg, 5000))
        worker.error.connect(lambda msg: self.statusBar().showMessage(f"Error: {msg}", 8000))
        worker.connected.connect(self._on_connected)
        worker.disconnected.connect(self._on_disconnected)
        worker.reconnecting.connect(self._on_reconnecting)
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

        # time-series CSV logger (feeds itself from the same signal)
        self._dashboard.log_toggled.connect(self._on_log_armed)
        worker.pid_value.connect(self._live_log.add)

        # threshold breaches (same signal; MainWindow fans out to the UI)
        worker.pid_value.connect(self._alert_log.evaluate)

        # history → log viewer jump
        self._history.view_log.connect(self._on_view_log)

    def _on_view_log(self, name: str) -> None:
        if self._viewer.load_log(name):
            self.show_panel(8)
        else:
            self.statusBar().showMessage(f"Log {name} is no longer available.", 8000)

    # -- live log -----------------------------------------------------------------

    def _on_log_armed(self, armed: bool) -> None:
        self._live_log.set_armed(armed)
        if not armed:
            self._dashboard.set_log_status(None, 0)

    def _on_log_change(self, path: Path | None, rows: int) -> None:
        self._dashboard.set_log_status(path.name if path else None, rows)

    # -- alerts -----------------------------------------------------------------

    def _on_alert_event(self, event: AlertEvent) -> None:
        if event.kind == "breach":
            definition = PID_REGISTRY.get(event.pid)
            decimals = definition.decimals if definition else 1
            self._dashboard.set_breached(event.pid, True)
            self._alerts.append_event(event)
            sign = ">" if event.direction == "high" else "<"
            self.statusBar().showMessage(
                f"ALERT: {describe_pid(event.pid)} {event.value:.{decimals}f} "
                f"{sign} {event.limit:.{decimals}f}",
                8000,
            )
        else:
            self._dashboard.set_breached(event.pid, False)

    def _on_thresholds_changed(self) -> None:
        self._prefs.set_watchlist(self._alert_log.watchlist.as_dict())
        self._dashboard.resync_breaches(self._alert_log.watchlist.breaching)

    # -- public API --------------------------------------------------------------

    def show_panel(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        for i, button in enumerate(self._nav_buttons):
            button.setChecked(i == index)
        self._prefs.set_panel_index(index)

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

    # -- preferences -------------------------------------------------------------

    def _restore_prefs(self) -> None:
        # queue the pinned OBD protocol before any connect can start
        self.worker.set_protocol(self._prefs.protocol())

        geometry = self._prefs.window_geometry()
        if geometry is not None:
            self.restoreGeometry(geometry)
        state = self._prefs.window_state()
        if state is not None:
            self.restoreState(state)

        panel = self._prefs.panel_index()
        if panel is None:
            panel = OVERVIEW_PANEL  # first run — land on the status overview
        if 0 <= panel < self._stack.count() and panel != self._stack.currentIndex():
            self.show_panel(panel)

        saved_port = self._prefs.last_port()
        port_available = False
        if saved_port is not None:
            index = self._port_combo.findData(saved_port)
            if index >= 0:
                self._port_combo.setCurrentIndex(index)
                port_available = True

        if self._prefs.auto_connect() and port_available:
            device = self._port_combo.currentData()
            self.statusBar().showMessage(f"Auto-connecting to {device}…", 0)
            self._on_connect_clicked()

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
        self._state_label.setText("Connecting…")
        self.statusBar().showMessage(f"Connecting to {device}…", 0)
        self.worker.connect_to(device)

    def _on_connected(self, info: SessionInfo) -> None:
        self._connected = True
        self._state_label.setText("Connected")
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
        self._state_label.setText("Disconnected")
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

    def _on_reconnecting(self, attempt: int, maximum: int) -> None:
        if attempt <= 0 or maximum <= 0:
            self._state_label.setText("Reconnect failed")
        else:
            self._state_label.setText(f"Reconnecting ({attempt}/{maximum})…")

    # -- lifecycle ------------------------------------------------------------------

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 — Qt naming
        self.statusBar().showMessage("Shutting down…", 0)
        self._live_log.close()
        if self._live_log.path is not None:
            self.record.log_file = self._live_log.path.name
            self.record.log_rows = self._live_log.row_count
        if record_has_data(self.record):
            try:
                self._store.save(build_report(self.record))
            except OSError as exc:
                self.statusBar().showMessage(f"Could not save session: {exc}", 5000)
        self._prefs.set_last_port(self._port_combo.currentData())
        self._prefs.set_window_geometry(self.saveGeometry())
        self._prefs.set_window_state(self.saveState())
        self._prefs.sync()
        self.worker.shutdown(5000)
        event.accept()
