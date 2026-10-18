"""UDS preset library tests."""

from __future__ import annotations

from autodiag.services import uds_presets


def test_load_presets_non_empty():
    presets = uds_presets.load_presets()
    assert len(presets) >= 10


def test_presets_for_service():
    io = uds_presets.presets_for("2F")
    routine = uds_presets.presets_for("31")
    assert all(p.service == "2F" for p in io)
    assert all(p.service == "31" for p in routine)
    assert len(io) >= 5
    assert len(routine) >= 5


def test_preset_by_name():
    preset = uds_presets.preset_by_name("EVAP leak test")
    assert preset is not None
    assert preset.service == "31"
    assert preset.request == "31010200"
    assert preset.tier == "workshop"


def test_preset_by_name_missing():
    assert uds_presets.preset_by_name("Nonexistent") is None


def test_preset_names():
    names = uds_presets.preset_names()
    assert "EVAP leak test" in names
    assert "Throttle body relearn" in names
    io_names = uds_presets.preset_names("2F")
    assert "Throttle body relearn" in io_names
    assert "EVAP leak test" not in io_names


def test_as_dict_shape():
    preset = uds_presets.preset_by_name("Cooling fan on")
    assert preset is not None
    payload = preset.as_dict()
    assert payload["name"] == "Cooling fan on"
    assert payload["service"] == "2F"
    assert payload["tier"] == "workshop"
    assert isinstance(payload["request"], str)
