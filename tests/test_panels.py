"""Diagnostic panel wiring tests: worker signals → widgets (offscreen)."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QLineEdit, QTableWidget

from autodiag.obd.mode06 import parse_test_results
from autodiag.obd.readiness import parse_monitor_status
from autodiag.services.record import ScanRecord
from autodiag.services.worker import ObdWorker
from autodiag.ui.panels.freeze import FreezeFramePanel
from autodiag.ui.panels.mode06 import Mode06Panel
from autodiag.ui.panels.readiness import ReadinessPanel
from autodiag.ui.panels.settings import SettingsPanel
from autodiag.ui.panels.trouble_codes import TroubleCodesPanel
from autodiag.ui.panels.vehicle import VehicleInfoPanel
from tests.test_export import make_record


def test_trouble_codes_panel_fills_trees(qapp):
    worker = ObdWorker()
    panel = TroubleCodesPanel(worker)

    worker.dtcs.emit("stored", ["P0301", "P0133"])
    worker.dtcs.emit("pending", ["P0245"])

    assert set(panel._trees) == {"stored", "pending", "permanent"}
    stored = panel._trees["stored"]
    assert stored.topLevelItemCount() == 2
    assert stored.topLevelItem(0).text(0) == "P0301"
    assert "Cylinder 1 Misfire" in stored.topLevelItem(0).text(1)
    assert panel._trees["pending"].topLevelItemCount() == 1
    assert panel._trees["permanent"].topLevelItemCount() == 0


def test_trouble_codes_clear_feedback(qapp):
    worker = ObdWorker()
    panel = TroubleCodesPanel(worker)

    worker.cleared.emit(True)
    assert "cleared" in panel._hint.text().lower()

    worker.cleared.emit(False)
    assert "did not confirm" in panel._hint.text()


def test_readiness_panel_states(qapp):
    worker = ObdWorker()
    panel = ReadinessPanel(worker)

    worker.monitors.emit(parse_monitor_status("41 01 86 07 E5 87"))

    labels = panel.findChildren(QLabel)
    banner = next(lb for lb in labels if "indicator lamp" in lb.text())
    assert "ON" in banner.text()

    states = panel._state_labels
    assert states["cat"].text() == "Not ready"  # D bit0 set
    assert states["o2s"].text() == "Ready"  # D bit5 clear
    assert states["hcat"].text() == "not supported"  # C bit1 clear
    assert states["misfire"].text() == "Ready"


def test_freeze_panel_fills_table(qapp):
    worker = ObdWorker()
    panel = FreezeFramePanel(worker)

    worker.freeze_all.emit({0x0C: 1726.0, 0x0D: 60.0})

    table = panel.findChildren(QTableWidget)[0]
    assert table.rowCount() == 2
    assert table.item(0, 1).text() == "Engine RPM"
    assert table.item(0, 2).text() == "1726"
    assert table.item(1, 1).text() == "Vehicle speed"
    assert table.item(1, 2).text() == "60"


def test_vehicle_panel_fills_fields(qapp):
    worker = ObdWorker()
    panel = VehicleInfoPanel(worker)

    worker.vehicle.emit(
        {"vin": "1D4GP00R56B123457", "cal_ids": ["ECM1A2.34"], "cvns": ["1B2C3D4E"]}
    )

    vin_labels = [
        lb for lb in panel.findChildren(QLabel) if "1D4GP00R56B123457" in lb.text()
    ]
    assert vin_labels
    edits = panel.findChildren(QLineEdit)
    assert edits[0].text() == "ECM1A2.34"
    assert edits[1].text() == "1B2C3D4E"


def test_mode06_panel_fills_table(qapp):
    worker = ObdWorker()
    panel = Mode06Panel(worker)

    worker.mode06.emit(parse_test_results("46 01 01 0A 06 60 06 60 06 60"))

    table = panel.findChildren(QTableWidget)[0]
    assert table.rowCount() == 1
    assert table.item(0, 0).text() == "Oxygen Sensor Monitor Bank 1 - Sensor 1"
    assert table.item(0, 1).text() == "Rich-to-lean sensor threshold voltage (constant)"
    assert table.item(0, 2).text() == "0.199104"
    assert table.item(0, 6).text() == "PASS"
    assert panel._count_label.text() == "1 test(s)"


def test_settings_panel_exports(qapp, tmp_path):
    messages: list[str] = []
    panel = SettingsPanel(make_record(), messages.append)

    target = panel.export_to(tmp_path / "scan.json")
    assert target.exists()
    assert '"1D4GP00R56B123457"' in target.read_text(encoding="utf-8")
    assert messages and "Report written" in messages[0]

    # bare path gets the default .json suffix
    bare = panel.export_to(tmp_path / "scan")
    assert bare.suffix == ".json"

    csv_target = panel.export_to(tmp_path / "scan.csv")
    assert csv_target.read_text(encoding="utf-8").startswith("section,")


def test_settings_panel_mentions_dictionary_size(qapp):
    panel = SettingsPanel(ScanRecord(), lambda _msg: None)
    notes = [lb.text() for lb in panel.findChildren(QLabel)]
    assert any("codes bundled" in note for note in notes)
