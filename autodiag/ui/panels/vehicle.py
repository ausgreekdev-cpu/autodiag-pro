"""Vehicle info panel: VIN, calibration IDs, CVN (mode $09), OBD standard + fuel."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from autodiag.services.worker import ObdWorker


class VehicleInfoPanel(QWidget):
    def __init__(self, worker: ObdWorker, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._worker = worker

        self._build_ui()
        worker.connected.connect(lambda _info: self._read_btn.setEnabled(True))
        worker.disconnected.connect(lambda _reason: self._reset())
        worker.vehicle.connect(self.on_vehicle)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        heading = QLabel("Vehicle info")
        heading.setObjectName("heading")
        layout.addWidget(heading)

        actions = QHBoxLayout()
        self._read_btn = QPushButton("Read vehicle info")
        self._read_btn.setEnabled(False)
        self._read_btn.clicked.connect(lambda: self._worker.read_vehicle())
        actions.addWidget(self._read_btn)
        actions.addStretch(1)
        layout.addLayout(actions)

        vin_group = QGroupBox("Vehicle identification number")
        vin_layout = QVBoxLayout(vin_group)
        self._vin_label = QLabel("--")
        mono = QFont("monospace")
        mono.setPointSizeF(16)
        mono.setBold(True)
        self._vin_label.setFont(mono)
        self._vin_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        vin_layout.addWidget(self._vin_label)
        layout.addWidget(vin_group)

        cal_group = QGroupBox("Calibration IDs")
        cal_layout = QVBoxLayout(cal_group)
        self._cal_edit = QLineEdit()
        self._cal_edit.setReadOnly(True)
        self._cal_edit.setPlaceholderText("Not read yet")
        cal_layout.addWidget(self._cal_edit)
        layout.addWidget(cal_group)

        cvn_group = QGroupBox("Calibration verification numbers (CVN)")
        cvn_layout = QVBoxLayout(cvn_group)
        self._cvn_edit = QLineEdit()
        self._cvn_edit.setReadOnly(True)
        self._cvn_edit.setPlaceholderText("Not read yet")
        cvn_layout.addWidget(self._cvn_edit)
        layout.addWidget(cvn_group)

        spec_group = QGroupBox("Emissions standard & fuel")
        spec_layout = QFormLayout(spec_group)
        self._obd_std_value = QLabel("--")
        self._fuel_value = QLabel("--")
        spec_layout.addRow("OBD standard:", self._obd_std_value)
        spec_layout.addRow("Fuel type:", self._fuel_value)
        layout.addWidget(spec_group)

        layout.addStretch(1)

    # -- worker handlers -------------------------------------------------------------

    def on_vehicle(self, info: dict) -> None:
        vin = info.get("vin")
        self._vin_label.setText(vin if vin else "Not reported by the vehicle")
        self._cal_edit.setText(", ".join(info.get("cal_ids") or []) or "Not reported")
        self._cvn_edit.setText(", ".join(info.get("cvns") or []) or "Not reported")
        self._obd_std_value.setText(info.get("obd_standard") or "Not reported")
        self._fuel_value.setText(info.get("fuel_type") or "Not reported")

    def _reset(self) -> None:
        self._vin_label.setText("--")
        self._cal_edit.clear()
        self._cvn_edit.clear()
        self._obd_std_value.setText("--")
        self._fuel_value.setText("--")
        self._read_btn.setEnabled(False)
