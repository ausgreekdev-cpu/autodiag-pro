"""Mode $06 on-board monitoring tests (9-byte records, UASID scaling)."""

import pytest

from autodiag.obd import mode06


def test_single_record_spec_example():
    # J1979 §6.6 example: O2 B1S1 test, UASID 0x0A → 0.000122 V/bit
    results = mode06.parse_test_results("46 01 01 0A 06 60 06 60 06 60")
    assert len(results) == 1
    r = results[0]
    assert r.mid == 0x01
    assert r.tid == 0x01
    assert r.uasid == 0x0A
    assert r.value == pytest.approx(0.199, abs=0.001)
    assert r.min_value == pytest.approx(0.199, abs=0.001)
    assert r.max_value == pytest.approx(0.199, abs=0.001)
    assert r.unit == "V"
    assert r.monitor_name == "Oxygen Sensor Monitor Bank 1 - Sensor 1"
    assert r.passed is True


def test_two_records():
    text = (
        "46 01 01 0A 06 60 06 60 06 60"  # 9 bytes
        "01 05 10 00 48 00 00 00 64"  # 9 bytes
    )
    results = mode06.parse_test_results(text)
    assert len(results) == 2
    assert results[1].mid == 0x01
    assert results[1].tid == 0x05
    assert results[1].value == pytest.approx(0.072, abs=0.001)
    assert results[1].unit == "s"
    assert results[1].passed is True


def test_not_completed_returns_none():
    # J1979: all-zero value/limits → test never ran yet
    results = mode06.parse_test_results("46 21 87 2E 00 00 00 00 00 00")
    assert len(results) == 1
    assert results[0].passed is None


def test_fail_outside_limits():
    # value outside [min, max]
    results = mode06.parse_test_results("46 01 01 0A 00 00 06 60 07 D0")
    assert len(results) == 1
    assert results[0].passed is False


def test_signed_scaling():
    # UASID 0x96: signed ×0.1 −40
    assert mode06.scale_value(0x96, 200) == pytest.approx(-20.0)
    assert mode06.scale_value(0x96, 0xFF9C) == pytest.approx(-50.0)  # raw = −100
    # UASID 0x9B not in table → identity fallback
    assert mode06.scale_value(0x9B, 1234) == 1234


def test_parse_supported_mids():
    supported, nxt = mode06.parse_supported_mids("4600BE3EA813")
    assert 0x01 in supported
    assert 0x02 not in supported
    assert nxt is True
    assert mode06.parse_supported_mids("") == (set(), False)


def test_mid_names():
    assert mode06.mid_name(0x01) == "Oxygen Sensor Monitor Bank 1 - Sensor 1"
    assert mode06.mid_name(0x05) == "Oxygen Sensor Monitor Bank 2 - Sensor 1"
    assert mode06.mid_name(0x45) == "Oxygen Sensor Heater Monitor Bank 2 - Sensor 1"
    assert mode06.mid_name(0x21) == "Catalyst Monitor Bank 1"
    assert mode06.mid_name(0x31) == "EGR Monitor Bank 1"
    assert mode06.mid_name(0x61) == "Heated Catalyst Monitor Bank 1"
    assert mode06.mid_name(0x81) == "Fuel System Monitor Bank 1"
    assert mode06.mid_name(0x39) == "EVAP Monitor (Cap Off)"
    assert mode06.mid_name(0xA1) == "Mis-Fire Monitor General Data"
    assert mode06.mid_name(0xA2) == "Mis-Fire Cylinder 1 Data"
    assert mode06.mid_name(0xAD) == "Mis-Fire Cylinder 12 Data"
    assert "supported" in mode06.mid_name(0x00)
    assert "Reserved" in mode06.mid_name(0x11)
    assert "manufacturer" in mode06.mid_name(0xE5).lower()


def test_empty_and_garbage():
    assert mode06.parse_test_results("") == []
    assert mode06.parse_test_results("46 01") == []  # truncated record
    assert mode06.parse_test_results("41 0C 1A F8") == []
