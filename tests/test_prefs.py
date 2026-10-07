"""Prefs: typed QSettings wrapper (port, interval, layout, auto-connect)."""

from __future__ import annotations

import json

from PySide6.QtCore import QByteArray, QSettings

from autodiag.ui.prefs import PROTOCOL_CHOICES, Prefs


def _prefs(tmp_path, name: str = "prefs.ini") -> Prefs:
    settings = QSettings(str(tmp_path / name), QSettings.Format.IniFormat)
    return Prefs(settings)


def test_defaults(tmp_path):
    prefs = _prefs(tmp_path)
    assert prefs.last_port() is None
    assert prefs.auto_connect() is False
    assert prefs.auto_log() is True  # live logging is on out of the box
    assert prefs.poll_interval_ms() == 250
    assert prefs.graph_window() == "2 min"  # dashboard default
    assert prefs.panel_index() is None  # unset → MainWindow lands on Overview
    assert prefs.protocol() == "0"  # auto-search until the user pins one
    assert prefs.window_geometry() is None
    assert prefs.window_state() is None


def test_protocol_pin(tmp_path):
    prefs = _prefs(tmp_path)
    prefs.set_protocol("6")
    assert prefs.protocol() == "6"
    # survives a second instance (round trip through the INI file)
    assert _prefs(tmp_path).protocol() == "6"
    # invalid stored values fall back to auto-search
    prefs.set_protocol("nope")
    assert prefs.protocol() == "0"
    assert _prefs(tmp_path).protocol() == "0"


def test_protocol_choices_cover_full_atsp_range():
    codes = [code for code, _label in PROTOCOL_CHOICES]
    labels = [label for _code, label in PROTOCOL_CHOICES]
    assert codes == list("0123456789ABC")  # ELM327 ATSP digits, auto first
    assert len(set(labels)) == len(labels)  # unique UI labels


def test_round_trip_through_second_instance(tmp_path):
    prefs = _prefs(tmp_path)
    prefs.set_last_port("/dev/ttyUSB0")
    prefs.set_auto_connect(True)
    prefs.set_auto_log(False)
    prefs.set_poll_interval_ms(750)
    prefs.set_graph_window("10 min")
    prefs.set_panel_index(3)
    geometry = QByteArray(b"\x01\x02binary blob")
    state = QByteArray(b"\x03\x04state blob")
    prefs.set_window_geometry(geometry)
    prefs.set_window_state(state)
    prefs.sync()

    fresh = _prefs(tmp_path)
    assert fresh.last_port() == "/dev/ttyUSB0"
    assert fresh.auto_connect() is True
    assert fresh.auto_log() is False
    assert fresh.poll_interval_ms() == 750
    assert fresh.graph_window() == "10 min"
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
    raw.setValue("graph_window", "bogus")
    assert prefs.poll_interval_ms() == 250
    assert prefs.panel_index() is None
    assert prefs.auto_connect() is False
    assert prefs.graph_window() == "2 min"

    raw.setValue("auto_connect", "true")
    assert prefs.auto_connect() is True

    prefs.set_graph_window("bogus")  # unknown labels are never stored
    assert prefs.graph_window() == "2 min"


def test_watchlist_round_trip(tmp_path):
    prefs = _prefs(tmp_path)
    assert prefs.watchlist() == {}
    prefs.set_watchlist({0x0C: (800.0, 6000.0), 0x05: (80.0, None), 0x0D: (None, 200.0)})
    prefs.sync()
    fresh = _prefs(tmp_path)
    assert fresh.watchlist() == {
        0x0C: (800.0, 6000.0),
        0x05: (80.0, None),
        0x0D: (None, 200.0),
    }


def test_watchlist_garbage_falls_back(tmp_path):
    prefs = _prefs(tmp_path)
    raw = prefs._s
    raw.setValue("watchlist", "not json at all")
    assert prefs.watchlist() == {}
    raw.setValue("watchlist", json.dumps(["not", "a", "mapping"]))
    assert prefs.watchlist() == {}
    # malformed entries drop individually; the good one survives
    raw.setValue("watchlist", json.dumps({"zz": [1, 2], "0C": ["x", 3], "05": [80, None]}))
    assert prefs.watchlist() == {0x05: (80.0, None)}
