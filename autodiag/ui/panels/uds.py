"""UDS panel: ISO 14229 requests — reads (Pro), writes (Workshop + waiver)."""

from __future__ import annotations

from datetime import UTC, datetime

from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from autodiag.obd import framing, uds
from autodiag.obd.uds import KNOWN_DIDS, UdsError, validate_request
from autodiag.services.license import LicenseManager, get_license
from autodiag.services.uds_presets import load_presets, preset_by_name
from autodiag.services.worker import ObdWorker
from autodiag.ui.license import try_unlock

_MAX_ROWS = 100

#: Public SAE J1979-DA Mode $08 test IDs (bi-directional controls). Anything
#: beyond this set is OEM-specific — the panel offers a custom ID for those.
MODE08_TESTS: tuple[tuple[int, str, str], ...] = (
    (
        0x01,
        "EVAP system leak test",
        "The EVAP system is pressurized and the purge/vent valves are cycled.",
    ),    (0x02, "Oxygen sensor B1S1 test", "The O2 sensor heater and signal are exercised."),
    (0x03, "Oxygen sensor B1S2 test", "The O2 sensor heater and signal are exercised."),
    (0x04, "Oxygen sensor B2S1 test", "The O2 sensor heater and signal are exercised."),
    (0x05, "Oxygen sensor B2S2 test", "The O2 sensor heater and signal are exercised."),
    (0x06, "EGR system test", "The EGR valve is cycled."),
)


class UdsPanel(QWidget):
    """UDS requests with decoded results; write services need the waiver."""

    def __init__(
        self,
        worker: ObdWorker,
        parent: QWidget | None = None,
        *,
        license_manager: LicenseManager | None = None,
    ) -> None:
        super().__init__(parent)
        self._worker = worker
        self._license = (
            license_manager if license_manager is not None else get_license()
        )
        self._connected = False

        self._build_ui()
        worker.connected.connect(lambda _info: self._set_connected(True))
        worker.disconnected.connect(lambda _reason: self._set_connected(False))
        worker.uds.connect(self.on_uds)
        worker.mode08.connect(self.on_mode08)
        worker.sgw_probe.connect(self.on_sgw_probe)
        worker.sgw_seed.connect(self.on_sgw_seed)
        worker.sgw_key.connect(self.on_sgw_key)
        self._sgw_challenge = None
        self._sgw_state = None
        self._sgw_probed = False

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        heading = QLabel("UDS (ISO 14229)")
        heading.setObjectName("heading")
        layout.addWidget(heading)

        hint = QLabel(
            "Read services — session ($10), DTCs ($19), read DID ($22),\n"
            "tester present ($3E). Writes and active tests need the waiver below."
        )
        hint.setObjectName("subtle")
        layout.addWidget(hint)

        addressing = QHBoxLayout()
        addressing.setSpacing(8)
        addressing.addWidget(QLabel("ECU:"))
        self._ecu_combo = QComboBox()
        self._ecu_combo.setToolTip(
            "Common physical request IDs — picks fill the header field"
        )
        for header, label in (
            ("7E0", "7E0 (ECM)"),
            ("7E1", "7E1 (TCM)"),
            ("7E2", "7E2"),
            ("7E4", "7E4"),
        ):
            self._ecu_combo.addItem(label, header)
        self._ecu_combo.currentIndexChanged.connect(self._on_ecu_preset)
        addressing.addWidget(self._ecu_combo)
        addressing.addWidget(QLabel("Header:"))
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
        self._supported_btn = QPushButton("Supported DTCs ($19 0A)")
        self._supported_btn.clicked.connect(
            lambda: self._send(uds.report_supported_dtc())
        )
        presets.addWidget(self._supported_btn)
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

        write_heading = QLabel("Write services — change ECU state")
        write_heading.setObjectName("heading")
        layout.addWidget(write_heading)

        self._waiver_chk = QCheckBox(
            "I understand writes and active tests can reprogram or disable ECUs — "
            "enable write services"
        )
        self._waiver_chk.toggled.connect(self._on_waiver_toggled)
        layout.addWidget(self._waiver_chk)

        write_row = QHBoxLayout()
        write_row.setSpacing(8)
        write_row.addWidget(QLabel("Write DID:"))
        self._write_did_edit = QLineEdit()
        self._write_did_edit.setPlaceholderText("F190")
        self._write_did_edit.setFixedWidth(90)
        self._write_did_edit.setValidator(
            QRegularExpressionValidator(QRegularExpression("[0-9A-Fa-f]{4}"), self)
        )
        write_row.addWidget(self._write_did_edit)
        self._write_data_edit = QLineEdit()
        self._write_data_edit.setPlaceholderText("value bytes: e.g. 414243")
        write_row.addWidget(self._write_data_edit, 1)
        self._write_btn = QPushButton("Write $2E")
        self._write_btn.clicked.connect(self._on_write_did)
        write_row.addWidget(self._write_btn)
        layout.addLayout(write_row)

        routine_row = QHBoxLayout()
        routine_row.setSpacing(8)
        routine_row.addWidget(QLabel("Routine $31:"))
        self._routine_type_combo = QComboBox()
        for label, control_type in (
            ("Start (01)", 0x01),
            ("Stop (02)", 0x02),
            ("Results (03)", 0x03),
        ):
            self._routine_type_combo.addItem(label, control_type)
        routine_row.addWidget(self._routine_type_combo)
        self._routine_id_edit = QLineEdit()
        self._routine_id_edit.setPlaceholderText("id: 0001")
        self._routine_id_edit.setFixedWidth(90)
        self._routine_id_edit.setValidator(
            QRegularExpressionValidator(QRegularExpression("[0-9A-Fa-f]{4}"), self)
        )
        routine_row.addWidget(self._routine_id_edit)
        self._routine_params_edit = QLineEdit()
        self._routine_params_edit.setPlaceholderText("params (optional hex)")
        routine_row.addWidget(self._routine_params_edit, 1)
        self._routine_btn = QPushButton("Send")
        self._routine_btn.clicked.connect(self._on_routine)
        routine_row.addWidget(self._routine_btn)
        layout.addLayout(routine_row)

        io_row = QHBoxLayout()
        io_row.setSpacing(8)
        io_row.addWidget(QLabel("IO control $2F:"))
        self._io_did_edit = QLineEdit()
        self._io_did_edit.setPlaceholderText("DID")
        self._io_did_edit.setFixedWidth(90)
        self._io_did_edit.setValidator(
            QRegularExpressionValidator(QRegularExpression("[0-9A-Fa-f]{4}"), self)
        )
        io_row.addWidget(self._io_did_edit)
        self._io_param_edit = QLineEdit("03")
        self._io_param_edit.setPlaceholderText("param")
        self._io_param_edit.setFixedWidth(56)
        self._io_param_edit.setValidator(
            QRegularExpressionValidator(QRegularExpression("[0-9A-Fa-f]{2}"), self)
        )
        io_row.addWidget(self._io_param_edit)
        self._io_data_edit = QLineEdit()
        self._io_data_edit.setPlaceholderText("data (optional hex)")
        io_row.addWidget(self._io_data_edit, 1)
        self._io_btn = QPushButton("Send")
        self._io_btn.clicked.connect(self._on_io_control)
        io_row.addWidget(self._io_btn)
        layout.addLayout(io_row)

        preset_heading = QLabel("Preset library — $2F / $31")
        preset_heading.setObjectName("heading")
        layout.addWidget(preset_heading)

        preset_row = QHBoxLayout()
        preset_row.setSpacing(8)
        self._preset_combo = QComboBox()
        self._preset_combo.addItem("Select a preset…", None)
        for preset in load_presets():
            self._preset_combo.addItem(
                f"{preset.name} ({preset.service})", preset.name
            )
        preset_row.addWidget(self._preset_combo, 1)
        self._preset_btn = QPushButton("Run preset")
        self._preset_btn.clicked.connect(self._on_run_preset)
        preset_row.addWidget(self._preset_btn)
        layout.addLayout(preset_row)

        self._preset_detail = QLabel("")
        self._preset_detail.setObjectName("subtle")
        self._preset_detail.setWordWrap(True)
        layout.addWidget(self._preset_detail)
        self._preset_combo.currentIndexChanged.connect(self._on_preset_changed)

        active_heading = QLabel("Active tests — mode $08 (bi-directional)")
        active_heading.setObjectName("heading")
        layout.addWidget(active_heading)

        active_row = QHBoxLayout()
        active_row.setSpacing(8)
        active_row.addWidget(QLabel("Test:"))
        self._test_combo = QComboBox()
        for test_id, name, _note in MODE08_TESTS:
            self._test_combo.addItem(f"$08 {test_id:02X} — {name}", test_id)
        self._test_combo.addItem("Custom test ID…", None)
        self._test_combo.currentIndexChanged.connect(self._on_test_changed)
        active_row.addWidget(self._test_combo, 1)
        self._custom_test_edit = QLineEdit()
        self._custom_test_edit.setPlaceholderText("hex 01–FF")
        self._custom_test_edit.setFixedWidth(80)
        self._custom_test_edit.setValidator(
            QRegularExpressionValidator(QRegularExpression("[0-9A-Fa-f]{1,2}"), self)
        )
        self._custom_test_edit.setVisible(False)
        active_row.addWidget(self._custom_test_edit)
        self._test_btn = QPushButton("Run test")
        self._test_btn.clicked.connect(self._on_run_test)
        active_row.addWidget(self._test_btn)
        layout.addLayout(active_row)

        sgw_heading = QLabel("Security gateway (SGW) — $27 unlock")
        sgw_heading.setObjectName("heading")
        layout.addWidget(sgw_heading)

        sgw_row = QHBoxLayout()
        sgw_row.setSpacing(8)
        sgw_row.addWidget(QLabel("Gateway:"))
        self._sgw_header_edit = QLineEdit("7E2")
        self._sgw_header_edit.setFixedWidth(56)
        self._sgw_header_edit.setValidator(
            QRegularExpressionValidator(QRegularExpression("[0-9A-Fa-f]{1,3}"), self)
        )
        sgw_row.addWidget(self._sgw_header_edit)
        self._sgw_probe_btn = QPushButton("Probe gateway")
        self._sgw_probe_btn.clicked.connect(self._on_sgw_probe)
        sgw_row.addWidget(self._sgw_probe_btn)
        self._sgw_status = QLabel("No gateway probed yet.")
        self._sgw_status.setObjectName("subtle")
        sgw_row.addWidget(self._sgw_status, 1)
        layout.addLayout(sgw_row)

        seed_row = QHBoxLayout()
        seed_row.setSpacing(8)
        self._sgw_seed_btn = QPushButton("Request seed")
        self._sgw_seed_btn.setEnabled(False)
        self._sgw_seed_btn.clicked.connect(self._on_sgw_seed)
        seed_row.addWidget(self._sgw_seed_btn)
        self._sgw_seed_label = QLabel("Seed: —")
        seed_row.addWidget(self._sgw_seed_label, 1)
        layout.addLayout(seed_row)

        key_row = QHBoxLayout()
        key_row.setSpacing(8)
        key_row.addWidget(QLabel("Key:"))
        self._sgw_key_edit = QLineEdit()
        self._sgw_key_edit.setPlaceholderText("computed by an authorized tool")
        self._sgw_key_edit.setFixedWidth(140)
        self._sgw_key_edit.setValidator(
            QRegularExpressionValidator(QRegularExpression("[0-9A-Fa-f]*"), self)
        )
        key_row.addWidget(self._sgw_key_edit)
        self._sgw_key_btn = QPushButton("Send key")
        self._sgw_key_btn.setEnabled(False)
        self._sgw_key_btn.clicked.connect(self._on_sgw_key)
        key_row.addWidget(self._sgw_key_btn)
        self._sgw_unlock_label = QLabel("Unlock: —")
        self._sgw_unlock_label.setObjectName("subtle")
        key_row.addWidget(self._sgw_unlock_label, 1)
        layout.addLayout(key_row)

        sgw_note = QLabel(
            "Unlock lasts ~30 minutes. Compute the seed's key with an "
            "authorized tool (FORScan, AutoAuth-certified software)."
        )
        sgw_note.setObjectName("subtle")
        layout.addWidget(sgw_note)

        self._on_preset_changed(self._preset_combo.currentIndex())
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
        if isinstance(result, UdsError):
            text = str(result)  # "requestOutOfRange (NRC 0x31 for service $22)"
        else:
            text = uds.describe_response(str(request), result)
        self._append_row(str(request).upper(), text, raw)
        self._status.setText(text)

    def on_mode08(self, payload: object) -> None:
        request, outcome = payload  # type: ignore[misc]
        self._append_row(request, outcome, "")
        self._status.setText(f"{request}: {outcome}")

    def on_sgw_probe(self, payload: object) -> None:
        header, info = payload  # type: ignore[misc]
        self._sgw_probed = info is not None
        if info is None:
            self._sgw_status.setText(f"No gateway answered on {header}.")
        else:
            identity = info.ecu_serial or info.software or "identity unknown"
            self._sgw_status.setText(f"Gateway found on {header} — {identity}.")
        self._refresh_sgw_buttons()

    def on_sgw_seed(self, payload: object) -> None:
        _header, challenge = payload  # type: ignore[misc]
        self._sgw_challenge = challenge
        if challenge is None:
            self._sgw_seed_label.setText("Seed: request denied (NRC).")
        else:
            self._sgw_seed_label.setText(f"Seed: {challenge.seed.hex().upper()}")
        self._refresh_sgw_buttons()

    def on_sgw_key(self, payload: object) -> None:
        _header, ok, detail = payload  # type: ignore[misc]
        if ok:
            from autodiag.services.sgw import UNLOCK_DURATION, UnlockState

            moment = datetime.now(UTC)
            self._sgw_state = UnlockState(
                header=_header, unlocked_at=moment, expires_at=moment + UNLOCK_DURATION
            )
            self._sgw_unlock_label.setText(
                f"Unlocked until {self._sgw_state.expires_at:%H:%M} — keep the ignition on."
            )
        else:
            self._sgw_state = None
            self._sgw_unlock_label.setText(f"Key rejected ({detail}).")

    def _refresh_sgw_buttons(self) -> None:
        waiver = self._waiver_chk.isChecked()
        self._sgw_seed_btn.setEnabled(waiver and self._sgw_probed)
        self._sgw_key_btn.setEnabled(waiver and self._sgw_challenge is not None)

    def _append_row(self, request: str, text: str, raw: str) -> None:
        flat = framing.flatten_response(raw)[:80]
        self._table.insertRow(0)
        self._table.setItem(0, 0, QTableWidgetItem(datetime.now().strftime("%H:%M:%S")))
        self._table.setItem(0, 1, QTableWidgetItem(request))
        self._table.setItem(0, 2, QTableWidgetItem(text))
        self._table.setItem(0, 3, QTableWidgetItem(flat))
        while self._table.rowCount() > _MAX_ROWS:
            self._table.removeRow(self._table.rowCount() - 1)
        self._table.scrollToTop()

    # -- interactions ----------------------------------------------------------

    def _send(self, hex_request: str) -> None:
        message = validate_request(
            hex_request, allow_writes=self._waiver_chk.isChecked()
        )
        if message is not None:
            self._status.setText(message)
            return
        normalized = "".join(hex_request.split()).upper()
        try:
            is_write = int(normalized[:2], 16) in uds.WRITE_SERVICES
        except ValueError:
            is_write = False
        if is_write:
            if not try_unlock(self, self._license, "uds.write"):
                self._status.setText(
                    "UDS write services are a Workshop feature — see Settings."
                )
                return
        elif not try_unlock(self, self._license, "uds.read"):
            self._status.setText("UDS module reads are a Pro feature — see Settings.")
            return
        tx = (self._tx_edit.text().strip() or uds.DEFAULT_TX_HEADER).upper()
        try:
            int(tx, 16)
        except ValueError:
            self._status.setText("ECU header must be 1–3 hex digits (e.g. 7E0).")
            return
        if is_write:
            answer = QMessageBox.warning(
                self,
                "Confirm write",
                f"Send ${normalized} to {tx}?\n\n"
                "Write services can reprogram or disable ECUs. Only continue "
                "with values verified against factory documentation.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                self._status.setText("Write cancelled.")
                return
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

    def _on_write_did(self) -> None:
        did_text = self._write_did_edit.text().strip()
        if len(did_text) != 4:
            self._status.setText("Write DID must be 4 hex digits (e.g. F190).")
            return
        data = self._hex_bytes(self._write_data_edit.text(), "Write value")
        if data is None:
            return
        if not data:
            self._status.setText("Write value needs at least one data byte.")
            return
        self._send(uds.write_data_by_identifier(int(did_text, 16), data))

    def _on_routine(self) -> None:
        routine_text = self._routine_id_edit.text().strip()
        if len(routine_text) != 4:
            self._status.setText("Routine ID must be 4 hex digits (e.g. 0001).")
            return
        params = self._hex_bytes(self._routine_params_edit.text(), "Routine params")
        if params is None:
            return
        control_type = int(self._routine_type_combo.currentData())
        self._send(uds.routine_control(control_type, int(routine_text, 16), params))

    def _on_io_control(self) -> None:
        did_text = self._io_did_edit.text().strip()
        if len(did_text) != 4:
            self._status.setText("IO DID must be 4 hex digits.")
            return
        param_text = self._io_param_edit.text().strip()
        if len(param_text) != 2:
            self._status.setText("IO control parameter must be 2 hex digits.")
            return
        data = self._hex_bytes(self._io_data_edit.text(), "IO data")
        if data is None:
            return
        self._send(
            uds.io_control_by_identifier(int(did_text, 16), int(param_text, 16), data)
        )

    def _on_test_changed(self, _index: int) -> None:
        self._custom_test_edit.setVisible(self._test_combo.currentData() is None)

    def _confirm_write(self, what: str) -> bool:
        """Shared gate for bi-directional features: waiver + Workshop tier."""
        if not self._waiver_chk.isChecked():
            self._status.setText(
                f"Tick the waiver first — {what} command the ECU to actuate components."
            )
            return False
        if not try_unlock(self, self._license, "uds.write"):
            self._status.setText(f"{what.capitalize()} is a Workshop feature — see Settings.")
            return False
        return True

    def _sgw_header(self) -> str | None:
        header = self._sgw_header_edit.text().strip().upper()
        try:
            int(header, 16)
        except ValueError:
            self._status.setText("Gateway header must be 1–3 hex digits (e.g. 7E2).")
            return None
        return header

    def _on_sgw_probe(self) -> None:
        header = self._sgw_header()
        if header is None:
            return
        self._sgw_status.setText(f"Probing {header}…")
        self._worker.run_sgw_probe(header)

    def _on_sgw_seed(self) -> None:
        if not self._confirm_write("SGW unlock"):
            return
        header = self._sgw_header()
        if header is None:
            return
        self._worker.run_sgw_seed(header)

    def _on_sgw_key(self) -> None:
        if not self._confirm_write("SGW unlock"):
            return
        header = self._sgw_header()
        if header is None:
            return
        key_text = "".join(self._sgw_key_edit.text().split())
        try:
            bytes.fromhex(key_text)
        except ValueError:
            self._status.setText("Key must be hex bytes (e.g. A1B2C3D4).")
            return
        self._worker.run_sgw_key(header, key_text)

    def _on_run_test(self) -> None:
        if not self._confirm_write("active tests"):
            return
        test_id = self._test_combo.currentData()
        if test_id is None:
            text = self._custom_test_edit.text().strip()
            try:
                test_id = int(text, 16)
            except ValueError:
                self._status.setText("Custom test ID must be hex (01–FF).")
                return
            if not 0x01 <= test_id <= 0xFF:
                self._status.setText("Custom test ID must be 01–FF.")
                return
            name = f"custom test ${test_id:02X}"
            note = "OEM-specific test — verify the meaning before running."
        else:
            name, note = next(
                (name, note) for tid, name, note in MODE08_TESTS if tid == test_id
            )
        answer = QMessageBox.question(
            self,
            "Run active test",
            f"Send $08 {test_id:02X} ({name})?\n\n"
            f"{note}\n\n"
            "The ECU will actuate components. Keep the engine idling and do "
            "not touch vehicle controls during the test.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._worker.run_mode08(test_id, f"$08 {test_id:02X} {name}")

    def _hex_bytes(self, text: str, label: str) -> bytes | None:
        cleaned = "".join(text.split()).upper()
        if len(cleaned) % 2 or any(c not in "0123456789ABCDEF" for c in cleaned):
            self._status.setText(f"{label} must be whole hex bytes (e.g. 01A2FF).")
            return None
        return bytes.fromhex(cleaned) if cleaned else b""

    def _on_tx_changed(self, text: str) -> None:
        try:
            rx = uds.response_header(text or uds.DEFAULT_TX_HEADER)
        except ValueError:
            return
        self._rx_label.setText(f"→ {rx}")

    def _on_preset_changed(self, _index: int) -> None:
        name = self._preset_combo.currentData()
        preset = preset_by_name(name) if name else None
        if preset is None:
            self._preset_detail.setText("")
            return
        self._preset_detail.setText(f"{preset.description} — {preset.oem}")

    def _on_run_preset(self) -> None:
        name = self._preset_combo.currentData()
        preset = preset_by_name(name) if name else None
        if preset is None:
            self._status.setText("Select a preset first.")
            return
        if not self._confirm_write("preset"):
            return
        if not try_unlock(self, self._license, "uds.write"):
            self._status.setText("Presets are a Workshop feature — see Settings.")
            return
        answer = QMessageBox.question(
            self,
            "Run preset",
            f"Send {preset.request} ({preset.name})?\n\n"
            f"{preset.description}\n\n"
            "The ECU will actuate components. Keep the engine idling and do "
            "not touch vehicle controls during the test.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._send(preset.request)

    def _on_ecu_preset(self, index: int) -> None:
        header = self._ecu_combo.itemData(index)
        if header:
            self._tx_edit.setText(str(header))

    def _on_waiver_toggled(self, checked: bool) -> None:
        if checked and not self._license.current().allows("uds.write"):
            self._waiver_chk.blockSignals(True)
            self._waiver_chk.setChecked(False)
            self._waiver_chk.blockSignals(False)
            self._status.setText(
                "UDS write services are a Workshop feature — see Settings."
            )
            try_unlock(self, self._license, "uds.write")
            checked = False
        write_enabled = self._connected and checked
        for widget in (
            self._write_did_edit,
            self._write_data_edit,
            self._write_btn,
            self._routine_type_combo,
            self._routine_id_edit,
            self._routine_params_edit,
            self._routine_btn,
            self._io_did_edit,
            self._io_param_edit,
            self._io_data_edit,
            self._io_btn,
        ):
            widget.setEnabled(write_enabled)
        self._refresh_sgw_buttons()

    def _set_connected(self, connected: bool) -> None:
        self._connected = connected
        for widget in (
            self._ecu_combo,
            self._tx_edit,
            self._session_btn,
            self._present_btn,
            self._dtc_btn,
            self._supported_btn,
            self._did_combo,
            self._did_edit,
            self._did_btn,
            self._raw_edit,
            self._raw_btn,
            self._waiver_chk,
        ):
            widget.setEnabled(connected)
        self._on_waiver_toggled(self._waiver_chk.isChecked())
        if not connected:
            self._status.setText("Connect to send UDS requests.")
