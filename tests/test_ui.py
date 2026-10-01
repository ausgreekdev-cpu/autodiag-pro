"""UI smoke tests — offscreen platform, no hardware, no worker threads."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton, QStackedWidget

from autodiag.obd.elm327 import SessionInfo
from autodiag.services.worker import ObdWorker
from autodiag.ui.main_window import MainWindow
from autodiag.ui.panels.dashboard import DashboardPanel
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


def test_main_window_navigation(qapp):
    window = MainWindow()
    stack = window.findChildren(QStackedWidget)[0]
    assert stack.count() == 7

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


def test_main_window_connect_button_and_voltage_flow(qapp):
    window = MainWindow()
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


def test_main_window_close_shuts_down_worker(qapp):
    window = MainWindow()
    window.worker.start()
    window.close()
    assert not window.worker.isRunning()
