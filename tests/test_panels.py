"""Diagnostic panel wiring tests: worker signals → widgets (offscreen)."""

from __future__ import annotations

from datetime import UTC, datetime

from PySide6.QtWidgets import QLabel, QLineEdit, QTableWidget

from autodiag.obd import mode06 as m06
from autodiag.obd.mode06 import parse_test_results
from autodiag.obd.readiness import parse_monitor_status
from autodiag.services.export import build_report
from autodiag.services.history import SessionStore
from autodiag.services.record import ScanRecord
from autodiag.services.worker import ObdWorker
from autodiag.ui.panels.freeze import FreezeFramePanel
from autodiag.ui.panels.history import HistoryPanel
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

    worker.freeze_all.emit(0, {0x0C: 1726.0, 0x0D: 60.0})

    table = panel.findChildren(QTableWidget)[0]
    assert table.rowCount() == 2
    assert table.item(0, 1).text() == "Engine RPM"
    assert table.item(0, 2).text() == "1726"
    assert table.item(1, 1).text() == "Vehicle speed"
    assert table.item(1, 2).text() == "60"
    assert "Frame 0" in panel._hint.text()


def test_freeze_panel_frame_picker_switches_cache(qapp):
    worker = ObdWorker()
    panel = FreezeFramePanel(worker)
    table = panel.findChildren(QTableWidget)[0]
    combo = panel._frame_combo

    assert combo.count() == 3
    worker.freeze_all.emit(0, {0x0C: 1726.0})
    worker.freeze_all.emit(1, {0x0C: 999.0})

    # reading frame 1 switches the combo to it
    assert combo.currentIndex() == 1
    assert table.item(0, 2).text() == "999"
    assert "Frame 1" in panel._hint.text()

    # switching back shows the cached frame 0 without another request
    combo.setCurrentIndex(0)
    assert table.item(0, 2).text() == "1726"
    assert "Frame 0" in panel._hint.text()

    # frame 2 was never read
    combo.setCurrentIndex(2)
    assert table.rowCount() == 0
    assert "not been read" in panel._hint.text()


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


def _mode06_result(value: float, low: float, high: float) -> m06.TestResult:
    return m06.TestResult(
        mid=0x01,
        tid=0x01,
        uasid=0,
        raw_value=1,
        raw_min=0,
        raw_max=2,
        value=value,
        min_value=low,
        max_value=high,
        unit="v",
    )


def test_mode06_panel_failures_only_filter(qapp):
    worker = ObdWorker()
    panel = Mode06Panel(worker)
    results = [
        _mode06_result(1.0, 0.0, 2.0),  # PASS
        _mode06_result(9.0, 0.0, 2.0),  # FAIL
        m06.TestResult(  # NOT RUN: all raw bytes zero
            mid=0x01, tid=0x01, uasid=0,
            raw_value=0, raw_min=0, raw_max=0,
            value=0.0, min_value=0.0, max_value=0.0, unit="v",
        ),
    ]
    worker.mode06.emit(results)
    table = panel._table
    assert table.rowCount() == 3
    assert panel._count_label.text() == "3 test(s)"
    summary = panel._hint.text()

    panel._only_failures.setChecked(True)
    assert table.rowCount() == 1
    assert table.item(0, 6).text() == "FAIL"
    assert panel._count_label.text() == "1 / 3 test(s)"
    assert panel._hint.text() == summary  # summary always covers the full set

    panel._only_failures.setChecked(False)
    assert table.rowCount() == 3
    assert panel._count_label.text() == "3 test(s)"

    worker.disconnected.emit("bye")  # results dropped with the session
    assert table.rowCount() == 0
    assert panel._count_label.text() == ""


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


# -- session history ---------------------------------------------------------------

def _history_store(tmp_path) -> SessionStore:
    store = SessionStore(tmp_path)
    record = make_record()
    record.log_file = "log-20261003-120000.csv"
    record.log_rows = 1234
    report = build_report(record, now=datetime(2026, 10, 3, 12, 30, tzinfo=UTC))
    store.save(report, when=datetime(2026, 10, 3, 12, 30, tzinfo=UTC))
    return store


def test_history_panel_lists_sessions(qapp, tmp_path):
    store = _history_store(tmp_path)
    store.save(
        build_report(make_record(), now=datetime(2026, 10, 4, 8, 0, tzinfo=UTC)),
        when=datetime(2026, 10, 4, 8, 0, tzinfo=UTC),
    )
    panel = HistoryPanel(store)

    assert panel._table.rowCount() == 2
    # newest first
    assert panel._table.item(0, 1).text() == "1D4GP00R56B123457"
    assert panel._table.item(0, 2).text() == "1"  # DTCs
    assert panel._table.item(0, 3).text() == "1"  # Mode $06
    assert panel._table.item(0, 5).text() == "ELM327 v1.5"
    assert panel._table.item(0, 6).text() == "—"  # newest session has no log
    assert panel._table.item(1, 6).text() == "1,234"  # Log column rows
    assert panel._count_label.text() == "2 session(s)"
    assert not panel._export_json_btn.isEnabled()  # nothing selected yet


def test_history_panel_empty_state(qapp, tmp_path):
    panel = HistoryPanel(SessionStore(tmp_path))
    assert panel._table.rowCount() == 0
    assert panel._count_label.text() == "No saved sessions yet"
    assert not panel._delete_btn.isEnabled()


def test_history_panel_selection_previews_and_enables_actions(qapp, tmp_path):
    panel = HistoryPanel(_history_store(tmp_path))
    panel._table.selectRow(0)

    assert panel._selected is not None
    assert panel._export_json_btn.isEnabled()
    assert panel._export_csv_btn.isEnabled()
    assert panel._delete_btn.isEnabled()
    detail = panel._detail.toPlainText()
    assert "VIN: 1D4GP00R56B123457" in detail
    assert "P0301" in detail
    assert "Log: log-20261003-120000.csv (1,234 rows)" in detail

    panel._table.clearSelection()
    assert panel._selected is None
    assert not panel._export_csv_btn.isEnabled()


def test_history_panel_export_writes_file(qapp, tmp_path, monkeypatch):
    from autodiag.ui.panels import history as history_mod

    panel = HistoryPanel(_history_store(tmp_path))
    panel._table.selectRow(0)
    target = tmp_path / "copy.csv"
    monkeypatch.setattr(
        history_mod.QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *args, **kwargs: (str(target), "CSV report (*.csv)")),
    )
    panel._export_csv_btn.click()
    assert target.exists()
    assert target.read_text(encoding="utf-8").startswith("section,key,name,value")


def test_history_panel_delete_confirmed_removes_session(qapp, tmp_path, monkeypatch):
    from autodiag.ui.panels import history as history_mod

    store = _history_store(tmp_path)
    panel = HistoryPanel(store)
    panel._table.selectRow(0)

    answer = history_mod.QMessageBox.StandardButton
    monkeypatch.setattr(
        history_mod.QMessageBox,
        "question",
        staticmethod(lambda *args, **kwargs: answer.No),
    )
    panel._delete()
    assert len(store.list()) == 1  # declined → kept

    monkeypatch.setattr(
        history_mod.QMessageBox,
        "question",
        staticmethod(lambda *args, **kwargs: answer.Yes),
    )
    panel._delete()
    assert store.list() == []
    assert panel._table.rowCount() == 0
    assert panel._count_label.text() == "No saved sessions yet"


def test_history_panel_refreshes_when_shown(qapp, tmp_path):
    store = SessionStore(tmp_path)
    panel = HistoryPanel(store)
    assert panel._table.rowCount() == 0

    store.save(
        build_report(make_record(), now=datetime(2026, 10, 3, tzinfo=UTC)),
        when=datetime(2026, 10, 3, tzinfo=UTC),
    )
    panel.show()  # showEvent → refresh
    assert panel._table.rowCount() == 1
    panel.close()
