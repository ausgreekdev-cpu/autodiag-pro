"""UI smoke tests — offscreen platform, no hardware, no worker threads."""

from __future__ import annotations

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QLabel, QPushButton, QStackedWidget

from autodiag.obd.elm327 import SessionInfo
from autodiag.services.worker import ObdWorker
from autodiag.ui.main_window import MainWindow
from autodiag.ui.panels.dashboard import DashboardPanel
from autodiag.ui.prefs import Prefs
from autodiag.ui.widgets.gauge import Gauge
from autodiag.ui.widgets.graph import LiveGraph

_INFO = SessionInfo(
    adapter="ELM327 v1.5",
    voltage=12.6,
    protocol="AUTO, ISO 15765-4 (CAN 11/500)",
    protocol_number="A7",
)


def _button(window: MainWindow, text: str) -> QPushButton:
    matches = [b for b in window.findChildren(QPushButton) if b.text() == text]
    assert matches, f"no button labelled {text!r}"
    return matches[0]


def _fresh_prefs(tmp_path, name: str = "prefs.ini") -> Prefs:
    settings = QSettings(str(tmp_path / name), QSettings.Format.IniFormat)
    return Prefs(settings)


def test_gauge_renders_value_and_empty_state(qapp):
    gauge = Gauge("Engine speed", "rpm", maximum=8000)
    gauge.set_value(1726)
    pixmap = gauge.grab()
    assert not pixmap.isNull()
    assert gauge.value == 1726

    gauge.set_value(None)
    assert gauge.value is None
    assert not gauge.grab().isNull()


def test_live_graph_records_active_series_only(qapp):
    graph = LiveGraph()
    graph.set_active([0x0C])
    graph.add_point(0x0C, 1726.0, 100.0)
    graph.add_point(0x0C, 1800.0, 100.25)
    graph.add_point(0x0D, 60.0, 100.5)  # not active → ignored
    assert graph.active_pids() == [0x0C]

    graph.set_active([0x0C, 0x0D])
    assert graph.active_pids() == [0x0C, 0x0D]
    graph.clear()
    graph.reset()
    assert graph.active_pids() == []


def test_live_graph_legend_names_series(qapp):
    graph = LiveGraph()
    graph.set_active([0x0C, 0x114])
    assert graph._curves[0x0C].opts["name"] == "Engine RPM [rpm]"
    assert graph._curves[0x114].opts["name"] == "O2 sensor B1S1 STFT [%]"


def test_live_graph_export_writes_png(qapp, tmp_path):
    graph = LiveGraph()
    graph.set_active([0x0C])
    graph.add_point(0x0C, 1726.0, 100.0)
    target = tmp_path / "graph.png"
    graph.export_to(str(target))
    assert target.exists()
    assert target.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_dashboard_save_image_dialog_writes_png(qapp, tmp_path, monkeypatch):
    from autodiag.ui.panels import dashboard as dashboard_mod

    worker = ObdWorker()
    panel = DashboardPanel(worker)
    worker.pids_supported.emit({0x0C})
    target = tmp_path / "dash.png"

    class _Dialog:
        @staticmethod
        def getSaveFileName(*_args, **_kwargs):
            return str(target), "PNG image (*.png)"

    monkeypatch.setattr(dashboard_mod, "QFileDialog", _Dialog)
    panel._export_graph()
    assert target.exists()
    assert target.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_dashboard_builds_table_and_graphs_rpm_by_default(qapp):
    worker = ObdWorker()
    panel = DashboardPanel(worker)

    worker.pids_supported.emit({0x0C, 0x0D, 0x05})
    assert panel.parameter_count() == 3
    assert panel.value_text(0x0C) == "--"
    assert panel.is_graphed(0x0C)  # RPM pre-selected
    assert not panel.is_graphed(0x0D)

    worker.pid_value.emit(0x0C, 1726.0, 1.0)
    worker.pid_value.emit(0x0D, 60.0, 1.25)
    assert panel.value_text(0x0C) == "1726"
    assert panel.value_text(0x0D) == "60"

    worker.disconnected.emit("bye")
    assert panel.value_text(0x0C) == "--"


def test_dashboard_graph_selection_follows_checkbox(qapp):
    worker = ObdWorker()
    panel = DashboardPanel(worker)
    worker.pids_supported.emit({0x0C, 0x0D})

    # default: RPM only; tick speed as well
    assert panel.is_graphed(0x0C)
    speed_item = panel._table.item(panel._rows[0x0D], 0)
    speed_item.setCheckState(Qt.CheckState.Checked)
    assert panel.is_graphed(0x0D)
    assert set(panel._graph.active_pids()) == {0x0C, 0x0D}


def test_dashboard_filters_by_text_and_category(qapp):
    worker = ObdWorker()
    panel = DashboardPanel(worker)
    worker.pids_supported.emit({0x0C, 0x0D, 0x05, 0x04, 0x06, 0x07})
    assert panel.visible_count() == 6
    assert panel._pid_count_label.text() == "6 parameters"

    panel._filter_edit.setText("trim")
    assert panel.visible_count() == 2  # short + long term fuel trim
    assert panel._pid_count_label.text() == "2 / 6 parameters"

    rows_before = dict(panel._rows)
    panel._filter_edit.setText("0D")  # hex PID match, case-insensitive
    assert panel.visible_count() == 1
    assert panel._rows == rows_before  # hiding never reorders rows

    panel._filter_edit.clear()
    fuel = panel._category_combo.findData("fuel")
    assert fuel >= 0
    panel._category_combo.setCurrentIndex(fuel)
    assert panel.visible_count() == 2  # 0x06, 0x07

    panel._filter_edit.setText("speed")  # + fuel → no overlap
    assert panel.visible_count() == 0
    assert panel._pid_count_label.text() == "0 / 6 parameters"


def test_dashboard_filter_survives_reconnect_and_keeps_check_state(qapp):
    worker = ObdWorker()
    panel = DashboardPanel(worker)
    worker.pids_supported.emit({0x0C, 0x0D, 0x05})
    panel._filter_edit.setText("vehicle")
    assert panel.visible_count() == 1  # only 0x0D "Vehicle speed"

    assert panel.is_graphed(0x0C)  # hidden row stays checked
    assert set(panel._graph.active_pids()) == {0x0C}

    worker.pids_supported.emit({0x0C, 0x0D, 0x05})  # reconnect rebuilds rows
    assert panel.visible_count() == 1  # filter re-applied
    assert panel._pid_count_label.text() == "1 / 3 parameters"

    panel._filter_edit.clear()
    assert panel.visible_count() == 3


def test_main_window_navigation(qapp, tmp_path):
    window = MainWindow(prefs=_fresh_prefs(tmp_path))
    stack = window.findChildren(QStackedWidget)[0]
    assert stack.count() == 8

    window.show_panel(2)
    assert stack.currentIndex() == 2
    assert _button(window, "Readiness").isChecked()
    assert not _button(window, "Dashboard").isChecked()

    window.show_panel(6)
    assert stack.currentIndex() == 6
    assert _button(window, "Settings").isChecked()

    window.show_panel(0)
    assert stack.currentIndex() == 0
    window.close()


def test_main_window_connect_button_and_voltage_flow(qapp, tmp_path):
    window = MainWindow(prefs=_fresh_prefs(tmp_path))
    worker = window.worker

    assert _button(window, "Connect").text() == "Connect"
    assert window.findChildren(QLabel, "chip")[0].text() == "--"

    worker.connected.emit(_INFO)
    assert _button(window, "Disconnect").text() == "Disconnect"
    assert "ELM327 v1.5" in window.findChildren(QLabel, "chip")[0].text()

    worker.voltage.emit(12.6)
    labels = [lb.text() for lb in window.findChildren(QLabel) if lb.text().endswith(" V")]
    assert "12.6 V" in labels

    worker.disconnected.emit("Adapter unplugged")
    assert _button(window, "Connect").text() == "Connect"
    window.close()


def test_main_window_close_shuts_down_worker(qapp, tmp_path):
    window = MainWindow(prefs=_fresh_prefs(tmp_path))
    window.worker.start()
    window.close()
    assert not window.worker.isRunning()


def test_main_window_restores_port_panel_and_interval(qapp, tmp_path, monkeypatch):
    from autodiag.transports.serial_transport import SerialPortInfo

    monkeypatch.setattr(
        "autodiag.ui.main_window.list_serial_ports",
        lambda: [SerialPortInfo("/dev/ttyUSB7", "FTDI")],
    )
    prefs = _fresh_prefs(tmp_path)
    prefs.set_last_port("/dev/ttyUSB7")
    prefs.set_panel_index(2)
    prefs.set_poll_interval_ms(600)
    prefs.sync()

    window = MainWindow(prefs=prefs)
    stack = window.findChildren(QStackedWidget)[0]
    assert stack.currentIndex() == 2
    assert _button(window, "Readiness").isChecked()
    assert window._port_combo.currentData() == "/dev/ttyUSB7"
    assert window._dashboard._interval_spin.value() == 600

    # the restored interval must have been queued to the engine at startup
    jobs = []
    while not window.worker.engine._jobs.empty():
        jobs.append(window.worker.engine._jobs.get_nowait())
    assert ("set_poll", (None, 0.6)) in jobs
    window.close()


def test_main_window_saves_and_restores_layout(qapp, tmp_path, monkeypatch):
    from autodiag.transports.serial_transport import SerialPortInfo

    monkeypatch.setattr(
        "autodiag.ui.main_window.list_serial_ports",
        lambda: [SerialPortInfo("/dev/ttyUSB9", "FTDI")],
    )
    prefs = _fresh_prefs(tmp_path)

    window = MainWindow(prefs=prefs)
    index = window._port_combo.findData("/dev/ttyUSB9")
    assert index >= 0
    window._port_combo.setCurrentIndex(index)
    window.show_panel(3)
    window.resize(1100, 700)
    window.close()

    assert prefs.last_port() == "/dev/ttyUSB9"
    assert prefs.panel_index() == 3
    assert prefs.window_geometry() is not None

    reopened = MainWindow(prefs=prefs)
    assert reopened._port_combo.currentData() == "/dev/ttyUSB9"
    assert reopened._stack.currentIndex() == 3
    # geometry round-trip: height must come back; offscreen's 800px screen
    # clamps the restored width down to the 960 minimum
    assert reopened.size().height() == 700
    reopened.close()


def test_main_window_auto_connect_only_with_saved_port(qapp, tmp_path, monkeypatch):
    from autodiag.transports.serial_transport import SerialPortInfo

    monkeypatch.setattr(
        "autodiag.ui.main_window.list_serial_ports",
        lambda: [SerialPortInfo("/dev/ttyUSB7", "FTDI")],
    )
    prefs = _fresh_prefs(tmp_path)
    prefs.set_last_port("/dev/ttyUSB7")
    prefs.set_auto_connect(True)
    prefs.sync()

    window = MainWindow(prefs=prefs)
    assert window._auto_chk.isChecked()
    assert window._connect_btn.text() == "Connecting…"
    assert not window._connect_btn.isEnabled()
    window.close()

    # auto-connect armed but the saved port is gone → stays idle
    prefs2 = _fresh_prefs(tmp_path, "second.ini")
    prefs2.set_last_port("/dev/gone")
    prefs2.set_auto_connect(True)
    prefs2.sync()
    idle = MainWindow(prefs=prefs2)
    assert idle._connect_btn.text() == "Connect"
    idle.close()


def test_main_window_connection_state_label(qapp, tmp_path, monkeypatch):
    from autodiag.transports.serial_transport import SerialPortInfo

    monkeypatch.setattr(
        "autodiag.ui.main_window.list_serial_ports",
        lambda: [SerialPortInfo("/dev/ttyUSB7", "FTDI")],
    )
    window = MainWindow(prefs=_fresh_prefs(tmp_path))
    label = window.findChildren(QLabel, "conn-state")[0]
    assert label.text() == "Ready"

    window._on_connect_clicked()
    assert label.text() == "Connecting…"

    window.worker.connected.emit(_INFO)
    assert label.text() == "Connected"

    window.worker.disconnected.emit("Adapter unplugged")
    assert label.text() == "Disconnected"

    window.worker.reconnecting.emit(2, 5)
    assert label.text() == "Reconnecting (2/5)…"

    window.worker.reconnecting.emit(0, 0)
    assert label.text() == "Reconnect failed"
    window.close()


def test_main_window_saves_session_on_close(qapp, tmp_path):
    from autodiag.services.history import SessionStore

    store = SessionStore(tmp_path)
    window = MainWindow(prefs=_fresh_prefs(tmp_path), store=store)
    window.record.record_event("pid_value", (0x0C, 1726.0, 1.0))
    window.close()

    summaries = store.list()
    assert len(summaries) == 1
    assert summaries[0]["pids"] == 1


def test_main_window_close_skips_session_without_data(qapp, tmp_path):
    from autodiag.services.history import SessionStore

    store = SessionStore(tmp_path)
    window = MainWindow(prefs=_fresh_prefs(tmp_path), store=store)
    window.record.record_event("connected", (_INFO,))  # adapter info alone
    window.close()
    assert store.list() == []
