"""UDS panel: ISO 14229 read requests against a physical CAN ID."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from autodiag.obd import framing, uds
from autodiag.obd.uds import KNOWN_DIDS, UdsError, UdsResponse, validate_request
from autodiag.services.worker import ObdWorker

_MAX_ROWS = 100


class UdsPanel(QWidget):
    """Read-only UDS requests with decoded results and raw responses."""

    def __init__(self, worker: ObdWorker, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._worker = worker
        self._connected = False

        self._build_ui()
        worker.connected.connect(lambda _info: self._set_connected(True))
        worker.disconnected.connect(lambda _reason: self._set_connected(False))
        worker.uds.connect(self.on_uds)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        heading = QLabel("UDS (ISO 14229)")
        heading.setObjectName("heading")
        layout.addWidget(heading)

        hint = QLabel(
            "Read-only services — session ($10), DTCs ($19), read DID ($22),\n"
            "tester present ($3E). Writes and actuation are not allowed here."
        )
        hint.setObjectName("subtle")
        layout.addWidget(hint)

        addressing = QHBoxLayout()
        addressing.setSpacing(8)
        addressing.addWidget(QLabel("ECU header:"))
        self._tx_edit = QLineEdit(uds.DEFAULT_TX_HEADER)
        self._tx_edit.setFixedWidth(64)
        self._tx_edit.setValidator(
            QRegularExpressionValidator(QRegularExpression("[0-9A-Fa-f]{1,3}"), self)
        )
        self._tx_edit.setToolTip("Physical transmit ID (7E0 = ECM, 7E1 = TCM, …)")
        self._tx_edit.textChanged.connect(self._on_tx_changed)
        addressing.addWidget(self._tx_edit)
        self._rx_label = QLabel(f"→ {uds.response_header(uds.DEFAULT_TX_HEADER)}")
        self._rx_label.setObjectName("subtle")
        addressing.addWidget(self._rx_label)
        addressing.addStretch(1)
        layout.addLayout(addressing)

        presets = QHBoxLayout()
        presets.setSpacing(8)
        self._session_btn = QPushButton("Extended session ($10 03)")
        self._session_btn.clicked.connect(lambda: self._send(uds.session_control(0x03)))
        presets.addWidget(self._session_btn)
        self._present_btn = QPushButton("Tester present ($3E)")
        self._present_btn.clicked.connect(lambda: self._send(uds.tester_present()))
        presets.addWidget(self._present_btn)
        self._dtc_btn = QPushButton("Read DTCs ($19 02 FF)")
        self._dtc_btn.clicked.connect(
            lambda: self._send(uds.read_dtc_by_status_mask())
        )
        presets.addWidget(self._dtc_btn)
        presets.addStretch(1)
        layout.addLayout(presets)

        did_row = QHBoxLayout()
        did_row.setSpacing(8)
        did_row.addWidget(QLabel("Read DID:"))
        self._did_combo = QComboBox()
        for did, name in KNOWN_DIDS.items():
            self._did_combo.addItem(f"{did:04X} — {name}", did)
        did_row.addWidget(self._did_combo, 1)
        self._did_edit = QLineEdit()
        self._did_edit.setPlaceholderText("custom: F190")
        self._did_edit.setFixedWidth(110)
        self._did_edit.setValidator(
            QRegularExpressionValidator(QRegularExpression("[0-9A-Fa-f]{4}"), self)
        )
        did_row.addWidget(self._did_edit)
        self._did_btn = QPushButton("Read")
        self._did_btn.clicked.connect(self._on_read_did)
        did_row.addWidget(self._did_btn)
        layout.addLayout(did_row)

        raw_row = QHBoxLayout()
        raw_row.setSpacing(8)
        raw_row.addWidget(QLabel("Raw request:"))
        self._raw_edit = QLineEdit()
        self._raw_edit.setPlaceholderText("hex bytes, e.g. 1003 or 22F190")
        self._raw_edit.returnPressed.connect(self._on_send_raw)
        raw_row.addWidget(self._raw_edit, 1)
        self._raw_btn = QPushButton("Send")
        self._raw_btn.clicked.connect(self._on_send_raw)
        raw_row.addWidget(self._raw_btn)
        layout.addLayout(raw_row)

        self._status = QLabel("Connect to send UDS requests.")
        self._status.setObjectName("subtle")
        layout.addWidget(self._status)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(("Time", "Request", "Result", "Raw"))
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
        self._table.setColumnWidth(1, 88)
        self._table.setColumnWidth(3, 170)
        layout.addWidget(self._table, 1)

        self._set_connected(False)

    # -- worker signal handlers ------------------------------------------------

    def on_uds(self, payload: object) -> None:
        request, result = payload  # type: ignore[misc]
        raw = str(getattr(result, "raw", "") or "")
        flat = framing.flatten_response(raw)
        if isinstance(result, UdsError):
            text = str(result)  # "requestOutOfRange (NRC 0x31 for service $22)"
        else:
            text = self._decode(str(request), result)
        self._table.insertRow(0)
        self._table.setItem(0, 0, QTableWidgetItem(datetime.now().strftime("%H:%M:%S")))
        self._table.setItem(0, 1, QTableWidgetItem(str(request).upper()))
        self._table.setItem(0, 2, QTableWidgetItem(text))
        self._table.setItem(0, 3, QTableWidgetItem(flat[:80]))
        while self._table.rowCount() > _MAX_ROWS:
            self._table.removeRow(self._table.rowCount() - 1)
        self._table.scrollToTop()
        self._status.setText(text)

    # -- interactions ----------------------------------------------------------

    def _send(self, hex_request: str) -> None:
        message = validate_request(hex_request)
        if message is not None:
            self._status.setText(message)
            return
        tx = (self._tx_edit.text().strip() or uds.DEFAULT_TX_HEADER).upper()
        try:
            int(tx, 16)
        except ValueError:
            self._status.setText("ECU header must be 1–3 hex digits (e.g. 7E0).")
            return
        normalized = "".join(hex_request.split()).upper()
        self._status.setText(f"Sending ${normalized[:2]} to {tx}…")
        self._worker.uds_request(normalized, tx=tx)

    def _on_read_did(self) -> None:
        custom = self._did_edit.text().strip()
        if custom:
            did = int(custom, 16)
        else:
            did = int(self._did_combo.currentData())
        self._send(uds.read_data_by_identifier([did]))

    def _on_send_raw(self) -> None:
        self._send(self._raw_edit.text())

    def _on_tx_changed(self, text: str) -> None:
        try:
            rx = uds.response_header(text or uds.DEFAULT_TX_HEADER)
        except ValueError:
            return
        self._rx_label.setText(f"→ {rx}")

    def _set_connected(self, connected: bool) -> None:
        self._connected = connected
        for widget in (
            self._tx_edit,
            self._session_btn,
            self._present_btn,
            self._dtc_btn,
            self._did_combo,
            self._did_edit,
            self._did_btn,
            self._raw_edit,
            self._raw_btn,
        ):
            widget.setEnabled(connected)
        if not connected:
            self._status.setText("Connect to send UDS requests.")

    @staticmethod
    def _decode(request: str, response: UdsResponse) -> str:
        if response.sid == 0x62 and request.startswith("22") and len(request) >= 6:
            # positive response echoes the 16-bit DID before the value
            data = response.payload[2:] if len(response.payload) >= 2 else b""
            return uds.decode_did(int(request[2:6], 16), data)
        if response.sid == 0x50:
            session = response.payload[0] if response.payload else 0
            return f"session {session:#04x} active"
        if response.sid == 0x7E:
            return "tester present acknowledged"
        if response.sid == 0x59:
            return f"DTC info: {response.payload.hex(' ').upper()}".rstrip()
        if response.payload and all(0x20 <= b <= 0x7E for b in response.payload):
            return response.payload.decode("ascii")
        return response.payload.hex(" ").upper() or "positive, no data"
