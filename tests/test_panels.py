"""Diagnostic panel wiring tests: worker signals → widgets (offscreen)."""

from __future__ import annotations

from datetime import UTC, datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QLineEdit, QTableWidget

from autodiag.obd import mode05 as m05
from autodiag.obd import mode06 as m06
from autodiag.obd.elm327 import SessionInfo
from autodiag.obd.mode05 import parse_tid_values
from autodiag.obd.mode06 import parse_test_results
from autodiag.obd.readiness import parse_monitor_status
from autodiag.services.alerts import AlertLog, Threshold, Watchlist
from autodiag.services.export import build_report
from autodiag.services.history import SessionStore
from autodiag.services.log_reader import LogData, LogSeries
from autodiag.services.record import ScanRecord
from autodiag.services.update_check import UpdateCheck
from autodiag.services.worker import ObdWorker
from autodiag.ui.compare_dialog import CompareDialog
from autodiag.ui.panels.alerts import AlertsPanel
from autodiag.ui.panels.explorer import PidExplorerPanel
from autodiag.ui.panels.freeze import FreezeFramePanel
from autodiag.ui.panels.history import HistoryPanel
from autodiag.ui.panels.log_viewer import LogViewerPanel, nearest_sample, status_text
from autodiag.ui.panels.mode05 import Mode05Panel
from autodiag.ui.panels.mode06 import Mode06Panel
from autodiag.ui.panels.overview import OverviewPanel
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
        {
            "vin": "1D4GP00R56B123457",
            "cal_ids": ["ECM1A2.34"],
            "cvns": ["1B2C3D4E"],
            "obd_standard": "EOBD (Europe)",
            "fuel_type": "Diesel",
        }
    )

    vin_labels = [
        lb for lb in panel.findChildren(QLabel) if "1D4GP00R56B123457" in lb.text()
    ]
    assert vin_labels
    edits = panel.findChildren(QLineEdit)
    assert edits[0].text() == "ECM1A2.34"
    assert edits[1].text() == "1B2C3D4E"
    assert panel._obd_std_value.text() == "EOBD (Europe)"
    assert panel._fuel_value.text() == "Diesel"


def test_vehicle_panel_standards_default_and_reset(qapp):
    worker = ObdWorker()
    panel = VehicleInfoPanel(worker)

    worker.vehicle.emit({"vin": None, "cal_ids": [], "cvns": []})
    assert panel._obd_std_value.text() == "Not reported"
    assert panel._fuel_value.text() == "Not reported"

    worker.disconnected.emit("bye")
    assert panel._obd_std_value.text() == "--"
    assert panel._fuel_value.text() == "--"


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


def test_mode05_panel_fills_table(qapp):
    worker = ObdWorker()
    panel = Mode05Panel(worker)

    worker.mode05.emit(parse_tid_values("45 01 01 5A", 0x01, 0x01))

    table = panel.findChildren(QTableWidget)[0]
    assert table.rowCount() == 1
    assert table.item(0, 0).text() == "Bank 1 - Sensor 1"
    assert table.item(0, 1).text() == (
        "Rich-to-lean sensor threshold voltage (constant)"
    )
    assert table.item(0, 2).text() == "0.45"
    assert table.item(0, 3).text() == "—"  # constants publish no limits
    assert table.item(0, 5).text() == "V"
    assert table.item(0, 6).text() == "NOT RUN"
    assert panel._count_label.text() == "1 test(s)"
    assert "no limits" in panel._hint.text()


def _mode05_result(value: float, low: float, high: float) -> m05.TestResult:
    return m05.TestResult(
        tid=0x05,
        sensor=0x01,
        raw_value=1,
        raw_min=0,
        raw_max=2,
        value=value,
        min_value=low,
        max_value=high,
        unit="s",
    )


def test_mode05_panel_failures_only_filter(qapp):
    worker = ObdWorker()
    panel = Mode05Panel(worker)
    results = [
        _mode05_result(1.0, 0.0, 2.0),  # PASS
        _mode05_result(9.0, 0.0, 2.0),  # FAIL
        m05.TestResult(  # NOT RUN: all raw bytes zero
            tid=0x05, sensor=0x01,
            raw_value=0, raw_min=0, raw_max=0,
            value=0.0, min_value=0.0, max_value=0.0, unit="s",
        ),
        m05.TestResult(  # constant TID: no limits at all
            tid=0x01, sensor=0x01,
            raw_value=90, raw_min=None, raw_max=None,
            value=0.45, min_value=None, max_value=None, unit="V",
        ),
    ]
    worker.mode05.emit(results)
    table = panel._table
    assert table.rowCount() == 4
    assert panel._count_label.text() == "4 test(s)"
    summary = panel._hint.text()

    panel._only_failures.setChecked(True)
    assert table.rowCount() == 1
    assert table.item(0, 6).text() == "FAIL"
    assert panel._count_label.text() == "1 / 4 test(s)"
    assert panel._hint.text() == summary  # summary always covers the full set

    panel._only_failures.setChecked(False)
    assert table.rowCount() == 4

    worker.disconnected.emit("bye")
    assert table.rowCount() == 0
    assert not panel._read_btn.isEnabled()
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

    html_target = panel.export_to(tmp_path / "scan.html")
    assert html_target.read_text(encoding="utf-8").startswith("<!DOCTYPE html>")


def test_settings_panel_mentions_dictionary_size(qapp):
    panel = SettingsPanel(ScanRecord(), lambda _msg: None)
    notes = [lb.text() for lb in panel.findChildren(QLabel)]
    assert any("codes bundled" in note for note in notes)


def test_settings_panel_protocol_combo(qapp, tmp_path):
    from PySide6.QtCore import QSettings

    from autodiag.ui.prefs import PROTOCOL_CHOICES, Prefs

    prefs = Prefs(QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat))
    messages: list[str] = []
    seen: list[str] = []
    panel = SettingsPanel(
        ScanRecord(), messages.append, prefs=prefs, on_protocol=seen.append
    )

    combo = panel._protocol_combo
    assert combo.count() == len(PROTOCOL_CHOICES)
    assert combo.currentData() == "0"  # auto-search out of the box

    combo.setCurrentIndex(6)  # "6" — ISO 15765-4 CAN (11-bit, 500 kbit/s)
    assert prefs.protocol() == "6"
    assert seen == ["6"]
    assert messages and "next connect" in messages[0]

    # a fresh panel restores the pinned protocol from prefs
    restored = SettingsPanel(ScanRecord(), lambda _m: None, prefs=prefs)
    assert restored._protocol_combo.currentData() == "6"


def _wait_until(app, pred, timeout: float = 5.0) -> bool:
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if pred():
            return True
    return False


def test_settings_check_updates_reports_new_release(qapp, monkeypatch):
    import autodiag.services.update_check as update_check

    monkeypatch.setattr(
        update_check,
        "check_for_update",
        lambda _current: UpdateCheck(
            status="update", latest="v9.9.9", url="https://example.test/r"
        ),
    )
    panel = SettingsPanel(ScanRecord(), lambda _msg: None)
    assert panel._update_btn.isEnabled()

    panel._update_btn.click()
    assert not panel._update_btn.isEnabled()  # busy while the worker runs

    assert _wait_until(qapp, panel._update_btn.isEnabled), "button never re-enabled"
    assert "v9.9.9 is available" in panel._update_label.text()
    assert "https://example.test/r" in panel._update_label.text()


def test_settings_check_updates_error_and_current(qapp, monkeypatch):
    import autodiag.services.update_check as update_check

    panel = SettingsPanel(ScanRecord(), lambda _msg: None)

    monkeypatch.setattr(
        update_check,
        "check_for_update",
        lambda _current: UpdateCheck(status="error", message="HTTP 404"),
    )
    panel._update_btn.click()
    assert _wait_until(qapp, panel._update_btn.isEnabled)
    assert "failed" in panel._update_label.text()
    assert "HTTP 404" in panel._update_label.text()

    monkeypatch.setattr(
        update_check,
        "check_for_update",
        lambda _current: UpdateCheck(status="current", latest="v0.11.0"),
    )
    panel._update_btn.click()
    assert _wait_until(qapp, panel._update_btn.isEnabled)
    assert "up to date" in panel._update_label.text()


def test_update_check_worker_emits_done(qapp, monkeypatch):
    import autodiag.services.update_check as update_check
    from autodiag.ui.panels.settings import UpdateCheckWorker

    monkeypatch.setattr(
        update_check,
        "check_for_update",
        lambda _current: UpdateCheck(status="current", latest="v0.11.0"),
    )
    worker = UpdateCheckWorker("0.11.0")
    received: list[object] = []
    worker.done.connect(received.append)

    worker.start()
    assert _wait_until(qapp, lambda: received), "worker never finished"
    assert not worker.isRunning()
    result = received[0]
    assert isinstance(result, UpdateCheck)
    assert result.status == "current"


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


def test_history_view_log_button_emits_filename(qapp, tmp_path):
    panel = HistoryPanel(_history_store(tmp_path))  # session has a log link
    panel._table.selectRow(0)
    assert panel._view_log_btn.isEnabled()

    emitted: list[str] = []
    panel.view_log.connect(emitted.append)
    panel._view_log_btn.click()
    assert emitted == ["log-20261003-120000.csv"]

    panel._table.clearSelection()
    assert not panel._view_log_btn.isEnabled()
    assert not panel._export_json_btn.isEnabled()


def test_history_view_log_disabled_when_session_has_no_log(qapp, tmp_path):
    store = SessionStore(tmp_path / "store")
    store.save(
        build_report(make_record(), now=datetime(2026, 10, 3, tzinfo=UTC)),
        when=datetime(2026, 10, 3, tzinfo=UTC),
    )
    panel = HistoryPanel(store)
    panel._table.selectRow(0)
    assert not panel._view_log_btn.isEnabled()
    assert panel._export_json_btn.isEnabled()  # other actions still fine


# -- log viewer ---------------------------------------------------------------------

_VIEWER_ROWS = [
    (0.00, "0C", "Engine RPM", "rpm", 812.0),
    (0.00, "0D", "Vehicle speed", "km/h", 44.0),
    (0.00, "05", "Coolant temp", "°C", 88.0),
    (0.00, "04", "Engine load", "%", 32.5),
    (0.00, "0B", "Intake pressure", "kPa", 76.0),
    (0.25, "0C", "Engine RPM", "rpm", 845.5),
    (0.25, "0D", "Vehicle speed", "km/h", 46.0),
    (0.50, "0C", "Engine RPM", "rpm", 901.0),
]


def _log_text(rows) -> str:
    lines = ["timestamp,elapsed_s,pid,name,unit,value"]
    for index, (elapsed, pid, name, unit, value) in enumerate(rows):
        lines.append(
            f"2026-10-03T12:00:{index:02d}.000+00:00,{elapsed:.3f},"
            f"{pid},{name},{unit},{value}"
        )
    return "\n".join(lines) + "\n"


def _write_viewer_log(directory, name: str = "log-20261003-120000.csv", rows=None):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(
        _log_text(_VIEWER_ROWS if rows is None else rows), encoding="utf-8"
    )
    return directory / name


def test_nearest_sample_picks_closest_point():
    xs = [0.0, 1.0, 2.0]
    ys = [10.0, 20.0, 30.0]
    assert nearest_sample(xs, ys, 0.6) == 20.0
    assert nearest_sample(xs, ys, 1.9) == 30.0
    assert nearest_sample([], [], 1.0) is None


def test_status_text_line():
    data = LogData(
        rows=12345,
        series={
            0x0C: LogSeries(0x0C, "Engine RPM", "rpm", xs=[0.0, 2070.0], ys=[1.0, 2.0])
        },
    )
    assert (
        status_text("log-20261003-120000.csv", data)
        == "log-20261003-120000.csv · 12,345 rows · 34.5 min · 1 parameter"
    )


def test_log_viewer_lists_files_and_checks_default_series(qapp, tmp_path):
    logs = tmp_path / "logs"
    _write_viewer_log(logs)
    _write_viewer_log(logs, name="log-20261002-090000.csv", rows=_VIEWER_ROWS[:2])

    panel = LogViewerPanel(logs)
    assert panel._file_combo.count() == 2
    assert panel._file_combo.currentData() == "log-20261003-120000.csv"  # newest first
    assert panel._table.rowCount() == 5  # 5 distinct PIDs
    checked = [
        pid
        for pid, row in panel._rows.items()
        if panel._table.item(row, 0).checkState() == Qt.CheckState.Checked
    ]
    assert checked == [0x0C, 0x0D, 0x05, 0x04]  # first four pre-selected
    assert panel._graph.active_pids() == [0x0C, 0x0D, 0x05, 0x04]

    status = panel._status_label.text()
    assert "log-20261003-120000.csv" in status
    assert "8 rows" in status
    assert "5 parameters" in status
    assert panel._export_btn.isEnabled()


def test_log_viewer_toggle_replots(qapp, tmp_path):
    logs = tmp_path / "logs"
    _write_viewer_log(logs)
    panel = LogViewerPanel(logs)

    check = panel._table.item(panel._rows[0x0C], 0)
    check.setCheckState(Qt.CheckState.Unchecked)  # fires itemChanged
    assert 0x0C not in panel._graph.active_pids()
    assert panel._graph.active_pids() == [0x0D, 0x05, 0x04]

    check.setCheckState(Qt.CheckState.Checked)
    assert panel._graph.active_pids() == [0x0C, 0x0D, 0x05, 0x04]


def test_log_viewer_empty_dir(qapp, tmp_path):
    panel = LogViewerPanel(tmp_path / "does-not-exist")
    assert panel._file_combo.count() == 0
    assert panel._table.rowCount() == 0
    assert panel._status_label.text() == "No logs recorded yet."
    assert not panel._export_btn.isEnabled()
    assert panel._graph.active_pids() == []


def test_log_viewer_browse_loads_file_outside_dir(qapp, tmp_path, monkeypatch):
    from autodiag.ui.panels import log_viewer as viewer_mod

    external = tmp_path / "elsewhere.csv"
    external.write_text(_log_text(_VIEWER_ROWS[:3]), encoding="utf-8")
    monkeypatch.setattr(
        viewer_mod.QFileDialog,
        "getOpenFileName",
        staticmethod(lambda *args, **kwargs: (str(external), "CSV log (*.csv)")),
    )
    panel = LogViewerPanel(tmp_path / "logs")  # empty target dir
    panel._browse_btn.click()
    assert "elsewhere.csv" in panel._status_label.text()
    assert panel._table.rowCount() == 3


def test_log_viewer_load_log_rejects_traversal_and_missing(qapp, tmp_path):
    panel = LogViewerPanel(tmp_path)
    assert panel.load_log("../evil.csv") is False
    assert panel.load_log("log-20261003-120000.csv") is False  # missing → OSError
    assert "Could not read" in panel._status_label.text()


def test_log_viewer_load_log_from_name(qapp, tmp_path):
    logs = tmp_path / "logs"
    _write_viewer_log(logs)
    panel = LogViewerPanel(logs)
    assert panel.load_log("log-20261003-120000.csv") is True
    assert panel._table.rowCount() == 5


# -- session compare -----------------------------------------------------------------

def _compare_store(tmp_path) -> SessionStore:
    """Two sessions: oldest has P0301/RPM 1726, newest P0420/RPM 1801."""
    store = SessionStore(tmp_path)
    first = make_record()
    store.save(
        build_report(first, now=datetime(2026, 10, 3, tzinfo=UTC)),
        when=datetime(2026, 10, 3, tzinfo=UTC),
    )
    second = make_record()
    second.dtcs = {"stored": ["P0420"]}
    second.pids[0x0C] = (1801.0, 2.0)
    store.save(
        build_report(second, now=datetime(2026, 10, 4, tzinfo=UTC)),
        when=datetime(2026, 10, 4, tzinfo=UTC),
    )
    return store


def test_compare_dialog_diffs_two_sessions(qapp, tmp_path):
    store = _compare_store(tmp_path)
    names = [summary["name"] for summary in store.list()]  # newest first
    dialog = CompareDialog(store, baseline=names[1])

    assert dialog._combo_a.currentData() == names[1]
    assert dialog._combo_b.currentData() == names[0]
    text = dialog._body.toPlainText()
    assert f"Comparing {names[1]} → {names[0]}" in text
    assert "New trouble codes:" in text and "P0420" in text
    assert "Resolved trouble codes:" in text and "P0301" in text
    assert "Engine RPM: 1726 → 1801 rpm" in text


def test_compare_dialog_defaults_to_newest_pair(qapp, tmp_path):
    store = _compare_store(tmp_path)
    names = [summary["name"] for summary in store.list()]
    dialog = CompareDialog(store)  # no baseline given
    assert dialog._combo_a.currentData() == names[0]
    assert dialog._combo_b.currentData() == names[1]


def test_compare_dialog_same_session_and_live_update(qapp, tmp_path):
    store = _compare_store(tmp_path)
    names = [summary["name"] for summary in store.list()]
    dialog = CompareDialog(store, baseline=names[1])

    dialog._combo_b.setCurrentIndex(1)  # same session as the baseline
    assert dialog._body.toPlainText() == "Pick two different sessions."

    dialog._combo_b.setCurrentIndex(0)  # switch back → live recompute
    assert "New trouble codes:" in dialog._body.toPlainText()


def test_compare_dialog_empty_store(qapp, tmp_path):
    dialog = CompareDialog(SessionStore(tmp_path / "does-not-exist"))
    assert dialog._body.toPlainText() == "No sessions to compare."


def test_compare_dialog_warns_on_vehicle_mismatch(qapp, tmp_path):
    store = SessionStore(tmp_path)
    store.save(
        build_report(make_record(), now=datetime(2026, 10, 3, tzinfo=UTC)),
        when=datetime(2026, 10, 3, tzinfo=UTC),
    )
    other = make_record()
    other.vin = "5YJSA1E14HF000000"
    store.save(
        build_report(other, now=datetime(2026, 10, 4, tzinfo=UTC)),
        when=datetime(2026, 10, 4, tzinfo=UTC),
    )
    names = [summary["name"] for summary in store.list()]
    dialog = CompareDialog(store, baseline=names[1])
    assert "WARNING: different vehicles" in dialog._body.toPlainText()


def test_history_compare_button_gates_on_pair(qapp, tmp_path):
    store = SessionStore(tmp_path)
    store.save(
        build_report(make_record(), now=datetime(2026, 10, 3, tzinfo=UTC)),
        when=datetime(2026, 10, 3, tzinfo=UTC),
    )
    panel = HistoryPanel(store)
    assert not panel._compare_btn.isEnabled()

    store.save(
        build_report(make_record(), now=datetime(2026, 10, 4, tzinfo=UTC)),
        when=datetime(2026, 10, 4, tzinfo=UTC),
    )
    panel.refresh()
    assert panel._compare_btn.isEnabled()


def test_history_compare_button_opens_dialog_with_selection(qapp, tmp_path, monkeypatch):
    from autodiag.ui.panels import history as history_mod

    store = _compare_store(tmp_path)
    names = [summary["name"] for summary in store.list()]
    captured: dict = {}

    class _StubDialog:
        def __init__(self, _store, *, baseline=None, parent=None):
            captured["baseline"] = baseline

        @staticmethod
        def exec():
            captured["exec"] = True

    monkeypatch.setattr(history_mod, "CompareDialog", _StubDialog)
    panel = HistoryPanel(store)
    panel._table.selectRow(1)  # the older session
    panel._compare_btn.click()
    assert captured == {"baseline": names[1], "exec": True}


def test_pid_explorer_lists_supported_then_unsupported(qapp):
    worker = ObdWorker()
    panel = PidExplorerPanel(worker)
    worker.pids_supported.emit({0x0C, 0x0D})

    labels = [panel._pid_combo.itemText(i) for i in range(panel._pid_combo.count())]
    assert labels[0].startswith("0C") and "Engine RPM" in labels[0]
    assert labels[1].startswith("0D") and "Vehicle speed" in labels[1]
    assert "2 parameters supported" in panel._hint.text()

    # everything else from the registry follows, marked unsupported
    unsupported = [label for label in labels if label.endswith("(unsupported)")]
    assert unsupported, "unsupported registry PIDs must still be pickable"
    assert not any("(unsupported)" in label for label in labels[:2])


def test_pid_explorer_requests_supported_pid(qapp, monkeypatch):
    worker = ObdWorker()
    panel = PidExplorerPanel(worker)
    worker.connected.emit(None)
    worker.pids_supported.emit({0x0C, 0x0D})
    requested: list[int] = []
    monkeypatch.setattr(worker, "request_pid", requested.append)

    panel._request_btn.click()  # first combo entry = 0x0C
    assert requested == [0x0C]


def test_pid_explorer_force_gates_unsupported_pids(qapp, monkeypatch):
    worker = ObdWorker()
    panel = PidExplorerPanel(worker)
    worker.connected.emit(None)
    worker.pids_supported.emit({0x0C})
    requested: list[int] = []
    monkeypatch.setattr(worker, "request_pid", requested.append)

    panel._pid_combo.setCurrentIndex(panel._pid_combo.count() - 1)  # unsupported
    assert "(unsupported)" in panel._pid_combo.currentText()
    panel._request_btn.click()
    assert requested == []  # blocked …
    assert "Force" in panel._hint.text()

    panel._force_chk.setChecked(True)
    panel._request_btn.click()
    assert len(requested) == 1  # … until Force is ticked


def test_pid_explorer_shows_response_row_and_graph_signal(qapp):
    worker = ObdWorker()
    panel = PidExplorerPanel(worker)
    worker.pids_supported.emit({0x0C})
    worker.connected.emit(None)

    worker.pid_response.emit(0x0C, "41 0C 1A F8")
    assert panel._table.rowCount() == 1
    assert panel._table.item(0, 1).text() == "0C"
    assert panel._table.item(0, 2).text() == "41 0C 1A F8"
    value_text = panel._table.item(0, 3).text()
    assert "Engine RPM" in value_text and "1726" in value_text

    pids: list[int] = []
    panel.graph_pid.connect(pids.append)
    panel._graph_btn.click()
    assert pids == [0x0C]

    worker.disconnected.emit("bye")
    assert not panel._request_btn.isEnabled()
    assert "Connect" in panel._hint.text()


# -- overview -----------------------------------------------------------------

_INFO = SessionInfo(
    adapter="ELM327 v1.5",
    voltage=12.6,
    protocol="AUTO, ISO 15765-4 (CAN 11/500)",
    protocol_number="A7",
)


def _overview(tmp_path, worker, goto=None):
    return OverviewPanel(
        worker,
        ScanRecord(),
        SessionStore(tmp_path),
        goto if goto is not None else (lambda _index: None),
    )


def test_overview_connection_card(qapp, tmp_path):
    worker = ObdWorker()
    panel = _overview(tmp_path, worker)
    assert panel._conn_state.text() == "Not connected"

    worker.connected.emit(_INFO)
    assert panel._conn_state.text() == "Connected"
    assert "ELM327 v1.5" in panel._conn_adapter.text()
    assert "ISO 15765-4" in panel._conn_protocol.text()
    assert "12.6 V" in panel._conn_voltage.text()

    worker.voltage.emit(14.2)
    assert "14.2 V" in panel._conn_voltage.text()

    worker.disconnected.emit("bye")
    assert panel._conn_state.text() == "Not connected"
    assert panel._conn_voltage.text() == "Voltage —"


def test_overview_vehicle_dtcs_readiness(qapp, tmp_path):
    worker = ObdWorker()
    panel = _overview(tmp_path, worker)

    worker.vehicle.emit({"vin": "1D4GP00R56B123457", "cal_ids": [], "cvns": []})
    assert panel._vin_value.text() == "1D4GP00R56B123457"

    worker.pids_supported.emit({0x05, 0x0C, 0x0D})
    assert panel._pids_value.text() == "3 parameters supported"

    worker.dtcs.emit("stored", ["P0301"])
    worker.dtcs.emit("pending", [])
    assert panel._dtcs_value.text() == "1 stored · 0 pending · 0 permanent"
    assert "1 code found" in panel._dtcs_note.text()

    status = parse_monitor_status("41 01 86 07 E5 87")
    worker.monitors.emit(status)
    assert "MIL on" in panel._mil_value.text()
    assert panel._ready_value.text() in ("Ready for inspection", "Not ready")
    assert "monitors complete" in panel._monitors_value.text()


def test_overview_last_session_and_quick_actions(qapp, tmp_path):
    from tests.test_history import _report

    store = SessionStore(tmp_path)
    store.save(_report(), when=datetime(2026, 10, 3, 12, 30, 45, tzinfo=UTC))
    goto: list[int] = []
    worker = ObdWorker()
    panel = OverviewPanel(worker, ScanRecord(), store, goto.append)

    panel.show()  # offscreen → showEvent → refresh from the store
    assert "2026-10-03 00:00" in panel._session_value.text()  # report generated_at
    assert "1D4GP00R56B123457" in panel._session_note.text()
    assert "1 DTC" in panel._session_note.text()

    for button in panel._action_buttons:
        button.click()
    assert goto == [1, 2, 4, 9]

    panel._history_btn.click()
    assert goto[-1] == 7


# -- threshold alerts ---------------------------------------------------------

def _alerts_panel():
    worker = ObdWorker()
    log = AlertLog(Watchlist())
    panel = AlertsPanel(worker, ScanRecord(), log)
    return worker, log, panel


def test_alerts_panel_validates_and_edits_thresholds(qapp):
    _worker, log, panel = _alerts_panel()
    changed: list[bool] = []
    panel.thresholds_changed.connect(lambda: changed.append(True))

    # the whole registry is pickable before any connection
    index = panel._pid_combo.findData(0x0C)
    assert index >= 0
    panel._pid_combo.setCurrentIndex(index)

    panel._set_btn.click()  # no bounds ticked
    assert "Min and/or Max" in panel._hint.text()
    assert panel._watchlist.get(0x0C) is None

    panel._low_chk.setChecked(True)
    panel._low_spin.setValue(800.0)
    panel._high_chk.setChecked(True)
    panel._high_spin.setValue(600.0)
    panel._set_btn.click()  # low >= high
    assert "Min must be below Max" in panel._hint.text()
    assert panel._watchlist.get(0x0C) is None
    assert changed == []

    panel._high_spin.setValue(6000.0)
    panel._set_btn.click()
    assert panel._watchlist.get(0x0C) == Threshold(0x0C, low=800.0, high=6000.0)
    assert changed == [True]
    assert panel._thresholds_table.rowCount() == 1
    assert panel._thresholds_table.item(0, 0).text() == "0C"

    panel._thresholds_table.selectRow(0)
    panel._remove_btn.click()
    assert panel._watchlist.get(0x0C) is None
    assert panel._thresholds_table.rowCount() == 0
    assert changed == [True, True]


def test_alerts_panel_reorders_combo_when_supported_arrives(qapp):
    _worker, _log, panel = _alerts_panel()
    panel.on_pids_supported({0x0C})
    labels = [
        panel._pid_combo.itemText(i) for i in range(panel._pid_combo.count())
    ]
    assert "Engine RPM" in labels[0] and not labels[0].endswith("(unsupported)")
    assert any(label.endswith("(unsupported)") for label in labels)


def test_alerts_panel_seeds_breach_from_last_recorded_value(qapp):
    record = ScanRecord()
    record.record_event("pid_value", (0x0C, 6510.0, 9.0))
    log = AlertLog(Watchlist())
    panel = AlertsPanel(ObdWorker(), record, log)
    panel._pid_combo.setCurrentIndex(panel._pid_combo.findData(0x0C))
    panel._high_chk.setChecked(True)
    panel._high_spin.setValue(6000.0)
    panel._set_btn.click()

    # the stored reading is already outside → flagged without waiting for a poll
    assert log.watchlist.breaching == frozenset({0x0C})
    assert len(log.events) == 1
    assert panel._thresholds_table.rowCount() == 1


def test_alerts_panel_clear_and_export_events(qapp, tmp_path, monkeypatch):
    log = AlertLog(Watchlist({0x0C: Threshold(0x0C, high=6000.0)}))
    panel = AlertsPanel(ObdWorker(), ScanRecord(), log)
    log.evaluate(0x0C, 6510.0, 1.0)
    panel.append_event(log.events[0])
    assert panel._events_table.rowCount() == 1

    target = tmp_path / "out.csv"
    monkeypatch.setattr(
        "autodiag.ui.panels.alerts.QFileDialog.getSaveFileName",
        lambda *args, **kwargs: (str(target), ""),
    )
    panel._export_btn.click()
    assert target.exists()
    assert "Written to" in panel._hint.text()

    panel._clear_btn.click()
    assert panel._events_table.rowCount() == 0
    assert log.events == []


def test_alerts_panel_display_is_capped(qapp):
    _worker, log, panel = _alerts_panel()
    from autodiag.services.alerts import MAX_EVENTS

    log.watchlist.set(Threshold(0x0C, high=6000.0))
    for i in range(MAX_EVENTS + 5):
        log.evaluate(0x0C, 5000.0, float(i))
        event = log.evaluate(0x0C, 6500.0 + i, float(i))
        panel.append_event(event)
    assert panel._events_table.rowCount() == MAX_EVENTS
