"""Guidance service tests — bundled data + heuristics, no Qt, no network."""

from __future__ import annotations

from autodiag.obd.readiness import Monitor, MonitorStatus
from autodiag.services import guidance
from autodiag.services.record import ScanRecord


def _record_with_freeze(values: dict[int, float]) -> ScanRecord:
    record = ScanRecord()
    record.record_event("freeze_all", (0, values))
    return record


def _record_with_monitors(monitors: tuple[Monitor, ...]) -> ScanRecord:
    record = ScanRecord()
    record.record_event(
        "monitors", (MonitorStatus(mil_on=True, dtc_count=1, monitors=monitors),)
    )
    return record


# -- guidance_for ---------------------------------------------------------------


def test_exact_entry_wins():
    result = guidance.guidance_for("P0301")
    assert result is not None
    assert result.source == "code"
    assert result.severity == "high"
    assert result.causes
    assert result.checks


def test_code_is_normalized():
    assert guidance.guidance_for(" p0301 ") == guidance.guidance_for("P0301")


def test_family_fallback_for_unknown_p03xx():
    result = guidance.guidance_for("P0399")
    assert result is not None
    assert result.source == "family"
    assert result.severity == "high"


def test_family_fallback_for_manufacturer_code():
    result = guidance.guidance_for("P1234")
    assert result is not None
    assert result.source == "family"
    assert "OEM" in result.checks[0]


def test_generic_fallback_for_unknown_family():
    result = guidance.guidance_for("P9999")
    assert result is not None
    assert result.source == "generic"


def test_non_dtc_inputs_return_none():
    assert guidance.guidance_for("") is None
    assert guidance.guidance_for("XXXX") is None
    assert guidance.guidance_for("P030") is None  # too short


def test_as_dict_shape():
    result = guidance.guidance_for("P0420")
    assert result is not None
    payload = result.as_dict()
    assert payload["severity"] == "medium"
    assert payload["source"] == "code"
    assert isinstance(payload["causes"], list)
    assert isinstance(payload["checks"], list)


# -- freeze_hints ----------------------------------------------------------------


def test_freeze_hints_cold_and_loaded():
    record = _record_with_freeze({0x05: 50.0, 0x0C: 5000.0})
    hints = guidance.freeze_hints(record)
    assert any("50°C" in hint for hint in hints)
    assert any("5000 rpm" in hint for hint in hints)


def test_freeze_hints_idle_and_stationary():
    record = _record_with_freeze({0x0C: 700.0, 0x0D: 0.0})
    hints = guidance.freeze_hints(record)
    assert any("idle" in hint for hint in hints)
    assert any("stationary" in hint for hint in hints)


def test_freeze_hints_highway_and_throttle():
    record = _record_with_freeze({0x0D: 120.0, 0x11: 80.0})
    hints = guidance.freeze_hints(record)
    assert any("120 km/h" in hint for hint in hints)
    assert any("80% open" in hint for hint in hints)


def test_freeze_hints_empty_without_frame():
    assert guidance.freeze_hints(None) == []
    assert guidance.freeze_hints(ScanRecord()) == []
    record = ScanRecord()
    record.record_event("freeze_all", (1, {0x05: 50.0}))  # frame 1 only
    assert guidance.freeze_hints(record) == []


# -- readiness_hint ---------------------------------------------------------------


def test_readiness_hint_none_without_monitors():
    assert guidance.readiness_hint(None) is None
    assert guidance.readiness_hint(ScanRecord()) is None


def test_readiness_hint_counts_incomplete_monitors():
    monitors = (
        Monitor("MISFIRE", "Misfire", True, False, True),
        Monitor("FUEL", "Fuel system", True, True, True),
    )
    hint = guidance.readiness_hint(_record_with_monitors(monitors))
    assert hint is not None
    assert "1 readiness monitor" in hint


def test_readiness_hint_none_when_all_complete():
    monitors = (
        Monitor("MISFIRE", "Misfire", True, True, True),
        Monitor("FUEL", "Fuel system", True, True, True),
    )
    assert guidance.readiness_hint(_record_with_monitors(monitors)) is None


# -- hints_for ---------------------------------------------------------------------


def test_hints_for_combines_freeze_and_readiness():
    record = _record_with_freeze({0x0D: 0.0})
    record.record_event(
        "monitors",
        (
            MonitorStatus(
                mil_on=True,
                dtc_count=1,
                monitors=(Monitor("MISFIRE", "Misfire", True, False, True),),
            ),
        ),
    )
    hints = guidance.hints_for(record)
    assert any("stationary" in hint for hint in hints)
    assert any("readiness" in hint for hint in hints)
