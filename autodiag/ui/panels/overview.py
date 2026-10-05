"""Overview: at-a-glance session health — the landing panel.

Six cards fed by the worker signals (live while visible) with a
:meth:`showEvent` sync from the scan record + session store, following the
History panel's refresh-on-show pattern.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from autodiag.obd.elm327 import SessionInfo
from autodiag.obd.readiness import MonitorStatus
from autodiag.services.history import SessionStore
from autodiag.services.record import ScanRecord
from autodiag.services.worker import ObdWorker
from autodiag.ui.theme import DANGER, MUTED, OK

# Quick-action targets — MainWindow stack indices (append-only nav; the test
# suite asserts these line up with the nav labels).
PANEL_TROUBLE_CODES = 1
PANEL_READINESS = 2
PANEL_VEHICLE = 4
PANEL_HISTORY = 7
PANEL_EXPLORER = 9

_SOURCES = ("stored", "pending", "permanent")


class OverviewPanel(QWidget):
    def __init__(
        self,
        worker: ObdWorker,
        record: ScanRecord,
        store: SessionStore,
        goto: Callable[[int], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._record = record
        self._store = store
        self._goto = goto

        self._session: SessionInfo | None = None
        self._vin: str | None = None
        self._supported: set[int] | None = None
        self._dtcs: dict[str, list[str]] = {}
        self._monitors: MonitorStatus | None = None

        self._build_ui()

        worker.connected.connect(self.on_connected)
        worker.disconnected.connect(lambda _reason: self.on_disconnected())
        worker.voltage.connect(self.on_voltage)
        worker.vehicle.connect(self.on_vehicle)
        worker.pids_supported.connect(self.on_pids_supported)
        worker.dtcs.connect(self.on_dtcs)
        worker.monitors.connect(self.on_monitors)

        self._render_all()

    # -- layout -----------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        heading = QLabel("Overview")
        heading.setObjectName("heading")
        layout.addWidget(heading)

        grid = QGridLayout()
        grid.setSpacing(12)

        connection = QGroupBox("Connection")
        connection_layout = QVBoxLayout(connection)
        self._conn_state = QLabel("Not connected")
        self._conn_state.setObjectName("value")
        connection_layout.addWidget(self._conn_state)
        self._conn_protocol = QLabel("Protocol —")
        connection_layout.addWidget(self._conn_protocol)
        self._conn_adapter = QLabel("Adapter —")
        self._conn_adapter.setObjectName("subtle")
        connection_layout.addWidget(self._conn_adapter)
        self._conn_voltage = QLabel("Voltage —")
        self._conn_voltage.setObjectName("subtle")
        connection_layout.addWidget(self._conn_voltage)
        grid.addWidget(connection, 0, 0)

        vehicle = QGroupBox("Vehicle")
        vehicle_layout = QVBoxLayout(vehicle)
        self._vin_value = QLabel("—")
        mono = QFont("monospace")
        mono.setPointSizeF(13)
        mono.setBold(True)
        self._vin_value.setFont(mono)
        vehicle_layout.addWidget(self._vin_value)
        self._pids_value = QLabel("— parameters supported")
        self._pids_value.setObjectName("subtle")
        vehicle_layout.addWidget(self._pids_value)
        grid.addWidget(vehicle, 0, 1)

        dtcs = QGroupBox("Trouble codes")
        dtcs_layout = QVBoxLayout(dtcs)
        self._dtcs_value = QLabel("0 stored · 0 pending · 0 permanent")
        self._dtcs_value.setObjectName("value")
        dtcs_layout.addWidget(self._dtcs_value)
        self._dtcs_note = QLabel("No codes reported yet")
        self._dtcs_note.setObjectName("subtle")
        dtcs_layout.addWidget(self._dtcs_note)
        grid.addWidget(dtcs, 1, 0)

        readiness = QGroupBox("Emissions readiness")
        readiness_layout = QVBoxLayout(readiness)
        self._ready_value = QLabel("—")
        self._ready_value.setObjectName("value")
        readiness_layout.addWidget(self._ready_value)
        self._monitors_value = QLabel("No monitor status yet")
        readiness_layout.addWidget(self._monitors_value)
        self._mil_value = QLabel("MIL —")
        self._mil_value.setObjectName("subtle")
        readiness_layout.addWidget(self._mil_value)
        grid.addWidget(readiness, 1, 1)

        last = QGroupBox("Last session")
        last_layout = QVBoxLayout(last)
        self._session_value = QLabel("No sessions yet")
        self._session_value.setObjectName("value")
        last_layout.addWidget(self._session_value)
        self._session_note = QLabel("Save a scan to see it here")
        self._session_note.setObjectName("subtle")
        last_layout.addWidget(self._session_note)
        self._history_btn = QPushButton("Open History")
        self._history_btn.clicked.connect(lambda: self._goto(PANEL_HISTORY))
        last_layout.addWidget(self._history_btn)
        grid.addWidget(last, 2, 0)

        actions = QGroupBox("Quick actions")
        actions_layout = QGridLayout(actions)
        self._action_buttons: list[QPushButton] = []
        for position, (label, target) in enumerate(
            (
                ("Trouble codes", PANEL_TROUBLE_CODES),
                ("Readiness", PANEL_READINESS),
                ("Vehicle info", PANEL_VEHICLE),
                ("PID explorer", PANEL_EXPLORER),
            )
        ):
            button = QPushButton(label)
            button.clicked.connect(
                lambda _checked=False, t=target: self._goto(t)
            )
            self._action_buttons.append(button)
            actions_layout.addWidget(button, position // 2, position % 2)
        grid.addWidget(actions, 2, 1)

        layout.addLayout(grid)
        layout.addStretch(1)

    # -- rendering ---------------------------------------------------------------

    def _render_all(self) -> None:
        self._render_connection()
        self._render_vehicle()
        self._render_dtcs()
        self._render_readiness()

    def _render_connection(self) -> None:
        session = self._session
        if session is None:
            self._conn_state.setText("Not connected")
            self._conn_protocol.setText("Protocol —")
            self._conn_adapter.setText("Adapter —")
            self._conn_voltage.setText("Voltage —")
            return
        self._conn_state.setText("Connected")
        self._conn_protocol.setText(f"Protocol {session.protocol or '—'}")
        self._conn_adapter.setText(f"Adapter {session.adapter}")
        volts = f"{session.voltage:.1f} V" if session.voltage is not None else "—"
        self._conn_voltage.setText(f"Voltage {volts}")

    def _render_vehicle(self) -> None:
        self._vin_value.setText(self._vin or "Not reported yet")
        if self._supported is None:
            self._pids_value.setText("— parameters supported")
        else:
            self._pids_value.setText(f"{len(self._supported)} parameters supported")

    def _render_dtcs(self) -> None:
        counts = {source: len(self._dtcs.get(source, [])) for source in _SOURCES}
        self._dtcs_value.setText(
            f"{counts['stored']} stored · "
            f"{counts['pending']} pending · "
            f"{counts['permanent']} permanent"
        )
        total = sum(counts.values())
        if total == 0:
            self._dtcs_note.setText("No codes reported yet")
            self._dtcs_note.setStyleSheet(f"color: {MUTED};")
        else:
            self._dtcs_note.setText(f"{total} code{'s' if total != 1 else ''} found")
            self._dtcs_note.setStyleSheet(f"color: {DANGER};")

    def _render_readiness(self) -> None:
        monitors = self._monitors
        if monitors is None:
            self._ready_value.setText("—")
            self._monitors_value.setText("No monitor status yet")
            self._mil_value.setText("MIL —")
            return
        supported = [m for m in monitors.monitors if m.supported]
        complete = [m for m in supported if m.complete]
        if monitors.ready:
            self._ready_value.setText("Ready for inspection")
            self._ready_value.setStyleSheet(f"color: {OK};")
        else:
            self._ready_value.setText("Not ready")
            self._ready_value.setStyleSheet(f"color: {DANGER};")
        self._monitors_value.setText(
            f"{len(complete)}/{len(supported)} monitors complete"
        )
        if monitors.mil_on:
            self._mil_value.setText(f"MIL on ({monitors.dtc_count} codes)")
            self._mil_value.setStyleSheet(f"color: {DANGER};")
        else:
            self._mil_value.setText("MIL off")
            self._mil_value.setStyleSheet(f"color: {OK};")

    def _render_last_session(self) -> None:
        summaries = self._store.list()
        if not summaries:
            self._session_value.setText("No sessions yet")
            self._session_note.setText("Save a scan to see it here")
            return
        newest = summaries[0]
        stamp = str(newest.get("generated_at") or "")[:16].replace("T", " ")
        self._session_value.setText(stamp or "Session saved")
        codes = int(newest.get("dtcs") or 0)
        vin = str(newest.get("vin") or "")
        detail = f"{codes} DTC{'s' if codes != 1 else ''}"
        if vin:
            detail += f" · VIN {vin}"
        self._session_note.setText(detail)

    # -- worker signal handlers ---------------------------------------------------

    def on_connected(self, info: object) -> None:
        if isinstance(info, SessionInfo):
            self._session = info
            self._render_connection()

    def on_disconnected(self) -> None:
        self._session = None
        self._render_connection()

    def on_voltage(self, volts: float) -> None:
        session = self._session
        if session is not None:
            self._session = SessionInfo(
                adapter=session.adapter,
                voltage=volts,
                protocol=session.protocol,
                protocol_number=session.protocol_number,
            )
            self._render_connection()

    def on_vehicle(self, info: object) -> None:
        if isinstance(info, dict):
            self._vin = info.get("vin")
            self._render_vehicle()

    def on_pids_supported(self, supported: set[int]) -> None:
        self._supported = set(supported)
        self._render_vehicle()

    def on_dtcs(self, source: str, codes: object) -> None:
        if isinstance(codes, list):
            self._dtcs[source] = list(codes)
            self._render_dtcs()

    def on_monitors(self, status: object) -> None:
        if isinstance(status, MonitorStatus):
            self._monitors = status
            self._render_readiness()

    # -- refresh on show ------------------------------------------------------------

    def showEvent(self, event) -> None:  # noqa: N802 — Qt naming
        super().showEvent(event)
        self._sync_from_record()
        self._render_last_session()

    def _sync_from_record(self) -> None:
        """Pull anything learned while this panel was hidden (record is authoritative)."""
        session = self._record.session
        if session is not None:
            self._session = session
        vin = self._record.vin
        if vin:
            self._vin = vin
        if self._record.dtcs:
            self._dtcs = dict(self._record.dtcs)
        if self._record.monitors is not None:
            self._monitors = self._record.monitors
        self._render_all()
