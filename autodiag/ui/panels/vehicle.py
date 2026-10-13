"""Vehicle info panel: VIN, calibration IDs, CVN (mode $09), OBD standard + fuel.

Plus the opt-in NHTSA lookup (VIN decode + open recalls) — press-triggered
only, never automatic, so the offline/privacy claim stays honest.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from autodiag.services import nhtsa
from autodiag.services.record import ScanRecord
from autodiag.services.worker import ObdWorker

_DETAIL_ROWS = (
    ("make", "Make:"),
    ("model", "Model:"),
    ("year", "Model year:"),
    ("body_class", "Body class:"),
    ("engine_text", "Engine:"),
    ("trim", "Trim:"),
)


class _LookupWorker(QThread):
    """Runs the two NHTSA calls off the UI thread; emits a payload dict."""

    done = Signal(object)  # {"gen": int, "payload": dict}

    def __init__(self, vin: str, generation: int) -> None:
        super().__init__()
        self._vin = vin
        self._generation = generation

    def run(self) -> None:
        decoded, recalls = nhtsa.lookup(self._vin)
        payload: dict[str, Any] = {
            **decoded.spec,
            "status": decoded.status,
            "message": decoded.message,
            "warning": decoded.warning,
            "engine_text": decoded.engine_text,
        }
        if decoded.ok:
            payload["recalls"] = [asdict(item) for item in recalls.recalls]
            payload["recall_status"] = recalls.status
            payload["recall_message"] = recalls.message
        else:
            payload["recalls"] = []
            payload["recall_status"] = "skipped"
            payload["recall_message"] = "decode failed"
        self.done.emit({"gen": self._generation, "payload": payload})


class VehicleInfoPanel(QWidget):
    def __init__(
        self,
        worker: ObdWorker,
        parent: QWidget | None = None,
        *,
        record: ScanRecord | None = None,
    ) -> None:
        super().__init__(parent)
        self._worker = worker
        self._record = record

        self._vin: str | None = None
        self._nhtsa_vin: str | None = None
        self._lookup_running = False
        self._generation = 0
        self._lookup: _LookupWorker | None = None

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

        lookup_group = QGroupBox("NHTSA vehicle details")
        lookup_layout = QVBoxLayout(lookup_group)
        lookup_actions = QHBoxLayout()
        self._lookup_btn = QPushButton("Look up VIN (NHTSA)")
        self._lookup_btn.setEnabled(False)
        self._lookup_btn.clicked.connect(self._start_lookup)
        self._lookup_status = QLabel("")
        self._lookup_status.setWordWrap(True)
        lookup_actions.addWidget(self._lookup_btn)
        lookup_actions.addWidget(self._lookup_status, stretch=1)
        lookup_layout.addLayout(lookup_actions)
        detail_form = QFormLayout()
        self._detail_values: dict[str, QLabel] = {}
        for key, label in _DETAIL_ROWS:
            value = QLabel("--")
            value.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            self._detail_values[key] = value
            detail_form.addRow(label, value)
        lookup_layout.addLayout(detail_form)
        layout.addWidget(lookup_group)

        recalls_group = QGroupBox("Open safety recalls (NHTSA)")
        recalls_layout = QVBoxLayout(recalls_group)
        self._recalls_edit = QPlainTextEdit()
        self._recalls_edit.setReadOnly(True)
        self._recalls_edit.setPlaceholderText(
            "Not looked up yet — press \u201cLook up VIN (NHTSA)\u201d above."
        )
        recalls_layout.addWidget(self._recalls_edit)
        layout.addWidget(recalls_group)

        layout.addStretch(1)

    # -- worker handlers -------------------------------------------------------------

    def on_vehicle(self, info: dict) -> None:
        vin = info.get("vin")
        self._vin = vin
        self._vin_label.setText(vin if vin else "Not reported by the vehicle")
        self._cal_edit.setText(", ".join(info.get("cal_ids") or []) or "Not reported")
        self._cvn_edit.setText(", ".join(info.get("cvns") or []) or "Not reported")
        self._obd_std_value.setText(info.get("obd_standard") or "Not reported")
        self._fuel_value.setText(info.get("fuel_type") or "Not reported")
        if vin != self._nhtsa_vin:
            self._clear_nhtsa(clear_record=True)
            self._nhtsa_vin = vin
        self._lookup_btn.setEnabled(bool(vin) and not self._lookup_running)

    # -- NHTSA lookup ------------------------------------------------------------------

    def _start_lookup(self) -> None:
        if self._lookup_running or not self._vin:
            return
        self._lookup_running = True
        self._lookup_btn.setEnabled(False)
        self._lookup_status.setText("Contacting NHTSA\u2026")
        worker = _LookupWorker(self._vin, self._generation)
        worker.done.connect(self._on_lookup_done)
        worker.finished.connect(worker.deleteLater)
        self._lookup = worker
        worker.start()

    def _on_lookup_done(self, result: dict) -> None:
        self._lookup_running = False
        self._lookup_btn.setEnabled(bool(self._vin))
        if result.get("gen") != self._generation:
            return  # stale VIN / disconnect — drop it
        payload = result.get("payload") or {}
        if payload.get("status") != "ok":
            message = payload.get("message") or "unknown error"
            self._lookup_status.setText(f"Lookup failed: {message}")
            self._remember(payload)
            return
        for key, label in self._detail_values.items():
            label.setText(payload.get(key) or "--")
        parts = ["Decoded via NHTSA vPIC"]
        if payload.get("warning"):
            parts.append(str(payload["warning"]))
        recalls = payload.get("recalls") or []
        if payload.get("recall_status") == "ok":
            if recalls:
                parts.append(f"{len(recalls)} open recall(s)")
            else:
                parts.append("no open recalls")
        elif payload.get("recall_status") == "error":
            parts.append(f"recalls: {payload.get('recall_message') or 'lookup failed'}")
        self._lookup_status.setText(" \u00b7 ".join(parts))
        self._recalls_edit.setPlainText(self._format_recalls(recalls))
        self._remember(payload)

    def _remember(self, payload: dict) -> None:
        if self._record is not None:
            self._record.record_event("nhtsa", (payload,))

    @staticmethod
    def _format_recalls(recalls: list[dict]) -> str:
        blocks = []
        for recall in recalls:
            header = " \u2014 ".join(
                part
                for part in (
                    recall.get("campaign"),
                    recall.get("component"),
                )
                if part
            )
            if recall.get("received"):
                header += f" (reported {recall['received']})"
            lines = [header]
            if recall.get("remedy"):
                lines.append(f"Remedy: {recall['remedy']}")
            blocks.append("\n".join(lines))
        return "\n\n".join(blocks)

    def _clear_nhtsa(self, *, clear_record: bool) -> None:
        self._generation += 1
        self._lookup_running = False
        for label in self._detail_values.values():
            label.setText("--")
        self._lookup_status.clear()
        self._recalls_edit.clear()
        if clear_record and self._record is not None:
            self._record.record_event("nhtsa", (None,))

    def _reset(self) -> None:
        self._vin_label.setText("--")
        self._cal_edit.clear()
        self._cvn_edit.clear()
        self._obd_std_value.setText("--")
        self._fuel_value.setText("--")
        self._read_btn.setEnabled(False)
        self._vin = None
        self._nhtsa_vin = None
        self._clear_nhtsa(clear_record=True)
        self._lookup_btn.setEnabled(False)
