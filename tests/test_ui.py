"""UI smoke tests — offscreen platform, no hardware, no worker threads."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QLabel, QPushButton, QStackedWidget

from autodiag.obd.elm327 import SessionInfo
from autodiag.services.alerts import Threshold
from autodiag.services.history import SessionStore
from autodiag.services.worker import ObdWorker
from autodiag.ui.icons import app_icon
from autodiag.ui.main_window import MainWindow
from autodiag.ui.panels.dashboard import DashboardPanel
from autodiag.ui.prefs import Prefs
from autodiag.ui.theme import BREACH_BG
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


def _fresh_store(tmp_path) -> SessionStore:
    return SessionStore(tmp_path)


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


def test_live_graph_bulk_set_series(qapp, tmp_path):
    graph = LiveGraph()
    graph.set_series(
        {
            0x0C: ([0.0, 0.5, 1.0], [812.0, 845.5, 901.0], "Engine RPM [rpm]"),
            0x99: ([0.0, 1.0], [1.5, 2.5], "Mystery [value]"),
        }
    )
    assert graph.active_pids() == [0x0C, 0x99]
    xs, ys = graph._curves[0x0C].getData()
    assert list(xs) == [0.0, 0.5, 1.0]
    assert list(ys) == [812.0, 845.5, 901.0]
    assert graph._curves[0x99].opts["name"] == "Mystery [value]"

    target = tmp_path / "loaded.png"
    graph.export_to(str(target))
    assert target.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"

    graph.set_series({0x0D: ([0.0], [60.0], "Vehicle speed [km/h]")})
    assert graph.active_pids() == [0x0D]  # full replacement


def test_live_graph_time_window_limits_x_range(qapp):
    graph = LiveGraph()
    graph.set_active([0x0C])
    for i in range(41):  # t = 1000.0 … 1040.0 → x 0 … 40
        graph.add_point(0x0C, 100.0 + i, 1000.0 + i)

    graph.set_window(30.0)
    (xmin, xmax), _ = graph.plot_widget.viewRange()
    assert xmax == pytest.approx(40.0)
    assert xmax - xmin == pytest.approx(30.0, abs=0.01)

    graph.set_window(None)  # All → whole buffer
    (xmin, xmax), _ = graph.plot_widget.viewRange()
    assert xmin == pytest.approx(0.0)
    assert xmax == pytest.approx(40.0)


def test_live_graph_y_range_uses_visible_window_only(qapp):
    graph = LiveGraph()
    graph.set_active([0x0C])
    for i in range(51):  # warm-up cluster, y = 100 for t 0 … 50
        graph.add_point(0x0C, 100.0, float(i))
    for i in range(51, 56):  # settled values, y = 5
        graph.add_point(0x0C, 5.0, float(i))

    graph.set_window(4.0)  # visible: t 51 … 55 only
    _, (ymin, ymax) = graph.plot_widget.viewRange()
    assert ymax < 50.0  # stale warm-up value must not squash the live line
    assert ymin <= 5.0 <= ymax


def test_live_graph_pause_freezes_then_resume_catches_up(qapp):
    graph = LiveGraph()
    graph.set_active([0x0C])
    graph.add_point(0x0C, 1.0, 0.0)

    graph.set_paused(True)
    graph.add_point(0x0C, 2.0, 1.0)
    graph.add_point(0x0C, 3.0, 2.0)
    xs, _ys = graph._curves[0x0C].getData()
    assert len(xs) == 1  # rendering frozen …
    assert len(graph._xs[0x0C]) == 3  # … but data keeps recording

    graph.set_paused(False)
    xs, _ys = graph._curves[0x0C].getData()
    assert len(xs) == 3  # resume renders the accumulated points at once
    assert not graph.paused


def test_live_graph_clear_empties_curves_and_rebases_time(qapp):
    graph = LiveGraph()
    graph.set_active([0x0C])
    graph.add_point(0x0C, 1726.0, 100.0)
    graph.add_point(0x0C, 1800.0, 100.25)

    graph.clear()
    xs, ys = graph._curves[0x0C].getData()
    # pyqtgraph reports cleared data as (None, None)
    assert not xs and not ys  # no stale curve left on screen

    graph.add_point(0x0C, 900.0, 500.0)  # new origin → x starts over
    xs, _ys = graph._curves[0x0C].getData()
    assert list(xs) == [0.0]


def test_live_graph_set_series_applies_full_ranges(qapp):
    graph = LiveGraph()
    graph.set_series({0x0C: ([0.0, 1.0, 2.0], [10.0, 20.0, 30.0], "RPM [rpm]")})
    (xmin, xmax), (ymin, ymax) = graph.plot_widget.viewRange()
    assert xmin == pytest.approx(0.0)
    assert xmax == pytest.approx(2.0)
    assert ymin <= 10.0 and ymax >= 30.0


def test_dashboard_set_graphed_toggles_checkbox(qapp):
    worker = ObdWorker()
    panel = DashboardPanel(worker)
    worker.pids_supported.emit({0x0C, 0x0D})

    assert panel.is_graphed(0x0C)  # RPM pre-selected
    panel.set_graphed(0x0D, True)
    assert panel.is_graphed(0x0D)
    assert 0x0D in panel._graph.active_pids()
    panel.set_graphed(0x0D, False)
    assert not panel.is_graphed(0x0D)
    panel.set_graphed(0x99, True)  # unknown pid → no-op


def _value_cell(panel: DashboardPanel, pid: int):
    return panel._table.item(panel._rows[pid], 3)  # _COL_VALUE


def test_dashboard_breach_highlight_and_rebuild(qapp):
    worker = ObdWorker()
    panel = DashboardPanel(worker)
    worker.pids_supported.emit({0x0C, 0x0D})

    panel.set_breached(0x0C, True)
    assert _value_cell(panel, 0x0C).background().color().name() == BREACH_BG
    assert _value_cell(panel, 0x0D).background().style() == Qt.BrushStyle.NoBrush

    # a table rebuild (reconnect) must restore the highlight
    worker.pids_supported.emit({0x0C, 0x0D})
    assert _value_cell(panel, 0x0C).background().color().name() == BREACH_BG

    panel.set_breached(0x0C, False)
    assert _value_cell(panel, 0x0C).background().style() == Qt.BrushStyle.NoBrush

    panel.set_breached(0x99, True)  # unknown pid → remembered, no crash
    panel.resync_breaches(frozenset())
    assert panel._breached == set()
    panel.set_breached(0x99, True)
    panel.resync_breaches(frozenset({0x99}))  # kept / re-lit
    assert panel._breached == {0x99}


def test_main_window_explorer_graph_pin(qapp, tmp_path):
    window = MainWindow(prefs=_fresh_prefs(tmp_path))
    window.worker.pids_supported.emit({0x0C, 0x0D})
    window._explorer.graph_pid.emit(0x0D)
    assert window._dashboard.is_graphed(0x0D)
    window.close()


def test_main_window_pins_protocol_pref_on_worker(qapp, tmp_path):
    from autodiag.ui.panels.settings import SettingsPanel

    prefs = _fresh_prefs(tmp_path)
    prefs.set_protocol("6")
    window = MainWindow(prefs=prefs)

    engine = window.worker._engine
    while not engine._jobs.empty():  # drain startup jobs (set_poll, set_protocol)
        assert engine.step(0.0)
    assert engine._protocol == "6"

    panel = next(
        widget
        for widget in (window._stack.widget(i) for i in range(window._stack.count()))
        if isinstance(widget, SettingsPanel)
    )
    assert panel._protocol_combo.currentData() == "6"
    window.close()


def test_app_icon_and_main_window_icon(qapp, tmp_path):
    icon = app_icon()
    assert not icon.pixmap(32, 32).isNull()

    window = MainWindow(prefs=_fresh_prefs(tmp_path))
    assert not window.windowIcon().pixmap(32, 32).isNull()
    window.close()


def test_dashboard_graph_window_combo_drives_graph(qapp, tmp_path):
    prefs = Prefs(QSettings(str(tmp_path / "p.ini"), QSettings.Format.IniFormat))
    worker = ObdWorker()
    panel = DashboardPanel(worker, prefs)

    assert panel._graph.window == 120.0  # default label "2 min"
    panel._window_combo.setCurrentText("30 s")
    assert panel._graph.window == 30.0
    assert prefs.graph_window() == "30 s"
    panel._window_combo.setCurrentText("All")
    assert panel._graph.window is None

    # the choice survives a new panel instance
    again = DashboardPanel(ObdWorker(), prefs)
    assert again._window_combo.currentText() == "All"
    assert again._graph.window is None


def test_dashboard_pause_and_clear_buttons(qapp):
    worker = ObdWorker()
    panel = DashboardPanel(worker)
    worker.pids_supported.emit({0x0C})
    worker.pid_value.emit(0x0C, 1726.0, 1.0)
    xs, _ys = panel._graph._curves[0x0C].getData()
    assert len(xs) == 1

    panel._pause_btn.click()
    assert panel._graph.paused is True
    assert panel._pause_btn.text() == "Resume"
    worker.pid_value.emit(0x0C, 1800.0, 1.25)  # values keep arriving …
    xs, _ys = panel._graph._curves[0x0C].getData()
    assert len(xs) == 1  # … but the plot stays frozen

    panel._pause_btn.click()
    assert panel._graph.paused is False
    xs, _ys = panel._graph._curves[0x0C].getData()
    assert len(xs) == 2  # resume catches up immediately

    panel._clear_btn.click()
    xs, _ys = panel._graph._curves[0x0C].getData()
    assert not xs and not _ys


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
    assert stack.count() == 14

    window.show_panel(2)
    assert stack.currentIndex() == 2
    assert _button(window, "Readiness").isChecked()
    assert not _button(window, "Dashboard").isChecked()

    window.show_panel(6)
    assert stack.currentIndex() == 6
    assert _button(window, "Settings").isChecked()

    window.show_panel(8)
    assert stack.currentIndex() == 8
    assert _button(window, "Log viewer").isChecked()

    window.show_panel(9)
    assert stack.currentIndex() == 9
    assert _button(window, "PID explorer").isChecked()

    window.show_panel(10)
    assert stack.currentIndex() == 10
    assert _button(window, "Overview").isChecked()

    window.show_panel(11)
    assert stack.currentIndex() == 11
    assert _button(window, "Alerts").isChecked()

    window.show_panel(12)
    assert stack.currentIndex() == 12
    assert _button(window, "Mode $05").isChecked()

    window.show_panel(13)
    assert stack.currentIndex() == 13
    assert _button(window, "UDS").isChecked()

    window.show_panel(0)
    assert stack.currentIndex() == 0
    window.close()


def test_main_window_alert_flow(qapp, tmp_path):
    prefs = _fresh_prefs(tmp_path)
    window = MainWindow(prefs=prefs)
    worker = window.worker
    worker.pids_supported.emit({0x0C, 0x05})
    window._alert_log.watchlist.set(Threshold(0x0C, high=6000.0))

    # a crossing flags the dashboard, logs an event and flashes the status bar
    worker.pid_value.emit(0x0C, 6510.0, 1.0)
    assert 0x0C in window._dashboard._breached
    assert _value_cell(window._dashboard, 0x0C).background().color().name() == BREACH_BG
    assert window._alerts._events_table.rowCount() == 1
    message = window.statusBar().currentMessage()
    assert message.startswith("ALERT:") and "6510" in message and "6000" in message

    # back inside → highlight clears, but the event stays in the history
    worker.pid_value.emit(0x0C, 2000.0, 2.0)
    assert 0x0C not in window._dashboard._breached
    assert window._alerts._events_table.rowCount() == 1
    assert len(window._alert_log.events) == 1

    # threshold edits go through the panel and persist to prefs
    panel = window._alerts
    panel._pid_combo.setCurrentIndex(panel._pid_combo.findData(0x05))
    panel._high_chk.setChecked(True)
    panel._high_spin.setValue(110.0)
    panel._set_btn.click()
    assert panel._watchlist.get(0x05) is not None
    saved = prefs.watchlist()
    assert saved[0x0C] == (None, 6000.0)
    assert saved[0x05] == (None, 110.0)

    # removing a threshold while it is breaching drops the highlight
    worker.pid_value.emit(0x0C, 6500.0, 3.0)
    assert 0x0C in window._dashboard._breached
    table = panel._thresholds_table
    for row in range(table.rowCount()):
        if int(table.item(row, 0).data(Qt.ItemDataRole.UserRole)) == 0x0C:
            table.selectRow(row)
    panel._remove_btn.click()
    assert panel._watchlist.get(0x0C) is None
    assert 0x0C not in window._dashboard._breached
    assert 0x0C not in prefs.watchlist()
    window.close()


def test_main_window_restores_watchlist_from_prefs(qapp, tmp_path):
    prefs = _fresh_prefs(tmp_path)
    prefs.set_watchlist({0x0C: (800.0, 6000.0)})
    window = MainWindow(prefs=prefs)
    threshold = window._alert_log.watchlist.get(0x0C)
    assert threshold == Threshold(0x0C, low=800.0, high=6000.0)
    assert window._alerts._thresholds_table.rowCount() == 1
    window.close()


def test_main_window_lands_on_overview_for_fresh_prefs(qapp, tmp_path):
    from autodiag.ui.main_window import OVERVIEW_PANEL

    window = MainWindow(prefs=_fresh_prefs(tmp_path))
    stack = window.findChildren(QStackedWidget)[0]
    assert stack.currentIndex() == OVERVIEW_PANEL
    assert _button(window, "Overview").isChecked()
    window.close()


def test_main_window_lands_on_saved_panel(qapp, tmp_path):
    prefs = _fresh_prefs(tmp_path)
    prefs.set_panel_index(3)
    window = MainWindow(prefs=prefs)
    stack = window.findChildren(QStackedWidget)[0]
    assert stack.currentIndex() == 3
    window.close()


def test_main_window_quick_actions_navigate(qapp, tmp_path):
    window = MainWindow(prefs=_fresh_prefs(tmp_path))
    stack = window.findChildren(QStackedWidget)[0]
    window._overview._action_buttons[0].click()  # Trouble codes
    assert stack.currentIndex() == 1
    window._overview._history_btn.click()
    assert stack.currentIndex() == 7
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


def test_dashboard_log_toggle_drives_label_and_prefs(qapp, tmp_path):
    prefs = _fresh_prefs(tmp_path)
    window = MainWindow(prefs=prefs, store=_fresh_store(tmp_path))

    checkbox = window._dashboard._log_chk
    label = window._dashboard._log_label
    assert checkbox.isChecked()  # default on
    assert label.text() == ""

    checkbox.setChecked(False)
    assert prefs.auto_log() is False
    assert not window._live_log.armed
    assert label.text() == ""  # cleared on disarm

    checkbox.setChecked(True)
    assert prefs.auto_log() is True
    assert window._live_log.armed
    window._dashboard.set_log_status("log-20261003-120000.csv", 1234)
    assert label.text() == "log-20261003-120000.csv · 1,234 rows"
    window.close()


def test_main_window_writes_live_log_and_links_session(qapp, tmp_path):
    store = _fresh_store(tmp_path)
    window = MainWindow(prefs=_fresh_prefs(tmp_path), store=store)

    window.worker.pid_value.emit(0x0C, 812.0, 1.0)
    label = window._dashboard._log_label
    assert "log-" in label.text() and "1 row" in label.text()
    assert window._live_log.row_count == 1

    window.close()

    logs = sorted((tmp_path / "logs").glob("log-*.csv"))
    assert len(logs) == 1
    content = logs[0].read_text(encoding="utf-8")
    assert content.startswith("timestamp,elapsed_s,pid,name,unit,value")
    assert "0C,Engine RPM,rpm,812.0" in content

    summaries = store.list()
    assert len(summaries) == 1
    assert summaries[0]["log_rows"] == 1
    report = store.load(summaries[0]["name"])
    assert report is not None
    assert report["live_log"] == {"file": logs[0].name, "rows": 1}


def test_main_window_disarm_stops_logging(qapp, tmp_path):
    store = _fresh_store(tmp_path)
    window = MainWindow(prefs=_fresh_prefs(tmp_path), store=store)
    window.worker.pid_value.emit(0x0C, 812.0, 1.0)

    window._dashboard._log_chk.setChecked(False)
    assert not window._live_log.armed
    assert window._dashboard._log_label.text() == ""
    window.worker.pid_value.emit(0x0C, 900.0, 2.0)
    assert window._live_log.row_count == 1  # ignored while disarmed

    window.close()
    report = store.load(store.list()[0]["name"])
    assert report is not None
    assert report["live_log"]["rows"] == 1  # log from before disarming still linked


def test_main_window_view_log_from_history(qapp, tmp_path):
    from datetime import UTC, datetime

    from autodiag.services.export import build_report
    from tests.test_export import make_record

    store = _fresh_store(tmp_path)
    logs = tmp_path / "logs"
    logs.mkdir()
    log_name = "log-20261003-120000.csv"
    (logs / log_name).write_text(
        "timestamp,elapsed_s,pid,name,unit,value\n"
        "2026-10-03T12:00:00.000+00:00,0.000,0C,Engine RPM,rpm,812.0\n",
        encoding="utf-8",
    )
    record = make_record()
    record.log_file = log_name
    record.log_rows = 1
    store.save(build_report(record, now=datetime(2026, 10, 3, tzinfo=UTC)))

    window = MainWindow(prefs=_fresh_prefs(tmp_path), store=store)
    window.show_panel(7)
    window._history._table.selectRow(0)
    window._history._view_log_btn.click()

    assert window._stack.currentIndex() == 8  # switched to the log viewer
    assert log_name in window._viewer._status_label.text()
    assert window._viewer._table.rowCount() == 1
    window.close()


def test_main_window_view_log_missing_file_stays_put(qapp, tmp_path):
    from datetime import UTC, datetime

    from autodiag.services.export import build_report
    from tests.test_export import make_record

    store = _fresh_store(tmp_path)
    record = make_record()
    record.log_file = "log-20200101-000000.csv"  # pruned away
    record.log_rows = 99
    store.save(build_report(record, now=datetime(2026, 10, 3, tzinfo=UTC)))

    window = MainWindow(prefs=_fresh_prefs(tmp_path), store=store)
    window.show_panel(7)
    window._history._table.selectRow(0)
    window._history._view_log_btn.click()

    assert window._stack.currentIndex() == 7  # did not switch
    assert "no longer available" in window.statusBar().currentMessage()
    window.close()
