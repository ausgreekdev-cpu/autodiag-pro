"""Readiness monitor panel: MIL status + I/M monitor states."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from autodiag.obd.readiness import MonitorStatus
from autodiag.services.worker import ObdWorker
from autodiag.ui import theme

_CONTINUOUS = ("misfire", "fuel", "ccm")
_NON_CONTINUOUS = ("cat", "hcat", "evap", "air", "acrf", "o2s", "htr", "egr")


class ReadinessPanel(QWidget):
    def __init__(self, worker: ObdWorker, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._worker = worker
        self._connected = False
        self._state_labels: dict[str, QLabel] = {}

        self._build_ui()
        worker.connected.connect(lambda _info: self._set_connected(True))
        worker.disconnected.connect(lambda _reason: self._set_connected(False))
        worker.monitors.connect(self.on_monitors)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        heading = QLabel("Readiness monitors")
        heading.setObjectName("heading")
        layout.addWidget(heading)

        actions = QHBoxLayout()
        self._read_btn = QPushButton("Read status")
        self._read_btn.clicked.connect(lambda: self._worker.read_monitors())
        actions.addWidget(self._read_btn)
        actions.addStretch(1)
        layout.addLayout(actions)

        self._banner = QLabel("Connect and read the vehicle status.")
        self._banner.setObjectName("subtle")
        layout.addWidget(self._banner)

        layout.addWidget(self._monitor_group("Continuous monitors", _CONTINUOUS))
        layout.addWidget(self._monitor_group("Non-continuous monitors", _NON_CONTINUOUS))
        layout.addStretch(1)
        self._set_connected(False)

    def _monitor_group(self, title: str, keys: tuple[str, ...]) -> QGroupBox:
        group = QGroupBox(title)
        grid = QVBoxLayout(group)
        grid.setSpacing(6)
        for key in keys:
            row = QHBoxLayout()
            name_label = QLabel(key)  # replaced with proper name on first read
            name_label.setObjectName(f"mon-name-{key}")
            name_label.setProperty("key", key)
            row.addWidget(name_label, 1)
            state = QLabel("—")
            state.setObjectName("subtle")
            row.addWidget(state)
            grid.addLayout(row)
            self._state_labels[key] = state
        return group

    # -- worker handlers -------------------------------------------------------

    def on_monitors(self, status: MonitorStatus) -> None:
        if status.mil_on:
            self._banner.setText(
                f"Malfunction indicator lamp is ON — {status.dtc_count} stored code(s)."
            )
            self._banner.setStyleSheet(f"color: {theme.DANGER}; font-weight: 600;")
        else:
            self._banner.setText(
                f"MIL is off — {status.dtc_count} stored code(s)."
            )
            self._banner.setStyleSheet(f"color: {theme.OK}; font-weight: 600;")

        for monitor in status.monitors:
            name = self.findChild(QLabel, f"mon-name-{monitor.key}")
            if name is not None:
                name.setText(monitor.name)
            label = self._state_labels.get(monitor.key)
            if label is None:
                continue
            if not monitor.supported:
                label.setText("not supported")
                label.setStyleSheet(f"color: {theme.MUTED};")
            elif monitor.complete:
                label.setText("Ready")
                label.setStyleSheet(f"color: {theme.OK}; font-weight: 600;")
            else:
                label.setText("Not ready")
                label.setStyleSheet(f"color: {theme.WARN}; font-weight: 600;")

    # -- connected state ------------------------------------------------------------

    def _set_connected(self, connected: bool) -> None:
        self._connected = connected
        self._read_btn.setEnabled(connected)
