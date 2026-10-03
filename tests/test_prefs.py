"""Prefs: typed QSettings wrapper (port, interval, layout, auto-connect)."""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QSettings

from autodiag.ui.prefs import Prefs


def _prefs(tmp_path, name: str = "prefs.ini") -> Prefs:
    settings = QSettings(str(tmp_path / name), QSettings.Format.IniFormat)
    return Prefs(settings)


def test_defaults(tmp_path):
    prefs = _prefs(tmp_path)
    assert prefs.last_port() is None
    assert prefs.auto_connect() is False
    assert prefs.poll_interval_ms() == 250
    assert prefs.panel_index() == 0
    assert prefs.window_geometry() is None
    assert prefs.window_state() is None


def test_round_trip_through_second_instance(tmp_path):
    prefs = _prefs(tmp_path)
    prefs.set_last_port("/dev/ttyUSB0")
    prefs.set_auto_connect(True)
    prefs.set_poll_interval_ms(750)
    prefs.set_panel_index(3)
    geometry = QByteArray(b"\x01\x02binary blob")
    state = QByteArray(b"\x03\x04state blob")
    prefs.set_window_geometry(geometry)
    prefs.set_window_state(state)
    prefs.sync()

    fresh = _prefs(tmp_path)
    assert fresh.last_port() == "/dev/ttyUSB0"
    assert fresh.auto_connect() is True
    assert fresh.poll_interval_ms() == 750
    assert fresh.panel_index() == 3
    assert bytes(fresh.window_geometry() or QByteArray()) == bytes(geometry)
    assert bytes(fresh.window_state() or QByteArray()) == bytes(state)


def test_clearing_port_saves_empty_string(tmp_path):
    prefs = _prefs(tmp_path)
    prefs.set_last_port("/dev/ttyUSB0")
    prefs.set_last_port(None)
    prefs.sync()
    assert _prefs(tmp_path).last_port() is None


def test_interval_is_clamped_on_read(tmp_path):
    prefs = _prefs(tmp_path)
    prefs.set_poll_interval_ms(5)  # below the UI minimum
    prefs.set_poll_interval_ms(60_000)  # above the UI maximum
    prefs.sync()
    assert _prefs(tmp_path).poll_interval_ms() == 5000  # last write wins

    raw = _prefs(tmp_path)
    raw._s.setValue("poll_interval_ms", 10)
    assert raw.poll_interval_ms() == 50


def test_garbage_values_fall_back_to_defaults(tmp_path):
    prefs = _prefs(tmp_path)
    raw = prefs._s
    raw.setValue("poll_interval_ms", "not-a-number")
    raw.setValue("panel_index", "bogus")
    raw.setValue("auto_connect", "false")
    assert prefs.poll_interval_ms() == 250
    assert prefs.panel_index() == 0
    assert prefs.auto_connect() is False

    raw.setValue("auto_connect", "true")
    assert prefs.auto_connect() is True
