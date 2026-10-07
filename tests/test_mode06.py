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


def test_tid_names_table():
    assert mode06.tid_name(0x01) == "Rich-to-lean sensor threshold voltage (constant)"
    assert mode06.tid_name(0x05) == "Rich-to-lean sensor switch time (calculated)"
    assert mode06.tid_name(0x0B) == (
        "EWMA misfire counts for last 10 driving cycles (calculated)"
    )
    assert mode06.tid_name(0x0C) == (
        "Misfire counts for last/current driving cycles (calculated)"
    )
    # range defaults (Table 157)
    assert mode06.tid_name(0x00) == "Reserved by document"
    assert mode06.tid_name(0x42) == "Reserved for future standardisation"
    assert mode06.tid_name(0x83) == "Manufacturer defined"
    assert mode06.tid_name(0xFE) == "Manufacturer defined"
    assert mode06.tid_name(0xFF) == "Reserved by document"
    assert mode06.tid_name(0x100) == "TID $100"  # out of byte range → fallback


def test_test_result_test_name():
    results = mode06.parse_test_results("46 01 01 0A 06 60 06 60 06 60")
    assert results[0].test_name == "Rich-to-lean sensor threshold voltage (constant)"


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
    # UASID 0x96: signed ×0.1, no offset (Appendix E Table E64: $FE70 → −40.0 °C)
    assert mode06.scale_value(0x96, 200) == pytest.approx(20.0)
    assert mode06.scale_value(0x96, 0xFF9C) == pytest.approx(-10.0)  # raw = −100
    assert mode06.scale_value(0x96, 0xFE70) == pytest.approx(-40.0)
    # UASID 0x9B not in table → identity fallback
    assert mode06.scale_value(0x9B, 1234) == 1234


def test_uasid_table_is_complete():
    # 65 unsigned ($01–$41) + 27 signed forms = the full standard table
    assert len(mode06.UASIDS) == 92
    assert sorted(k for k, v in mode06.UASIDS.items() if not v[3]) == list(range(1, 0x42))
    signed = sorted(k for k, v in mode06.UASIDS.items() if v[3])
    assert signed == [
        0x81, 0x82, 0x83, 0x84, 0x85, 0x86, 0x87, 0x8A, 0x8B, 0x8C, 0x8D,
        0x8E, 0x90, 0x96, 0x99, 0x9C, 0x9D, 0xA8, 0xA9, 0xAD, 0xAE, 0xAF,
        0xB0, 0xB1, 0xFC, 0xFD, 0xFE,
    ]


def test_new_uasid_scaling():
    # fixes: $06 is 0.000305 (Table E6: max 19.988), signed $96 has no offset
    assert mode06.scale_value(0x06, 0xFFFF) == pytest.approx(19.988, abs=0.001)
    assert mode06.scale_value(0x05, 0xFFFF) == pytest.approx(1.999, abs=0.001)
    # equivalence-ratio IDs (Tables E30/E51)
    assert mode06.scale_value(0x1E, 0x8013) == pytest.approx(1.0, abs=1e-4)
    assert mode06.scale_value(0x33, 0xE5BE) == pytest.approx(14.359, abs=0.001)
    # EVAP offset percent and time/volume/scaling spot checks
    assert mode06.scale_value(0x39, 0) == pytest.approx(-327.68)
    assert mode06.scale_value(0x34, 10) == pytest.approx(10.0)
    assert mode06.scale_value(0x3F, 10000) == pytest.approx(100.0)
    assert mode06.scale_value(0x26, 10000) == pytest.approx(1.0)
    assert mode06.scale_value(0x29, 4096) == pytest.approx(1.024)
    # signed additions
    assert mode06.scale_value(0x87, 0xFFFF) == pytest.approx(-1.0)
    assert mode06.scale_value(0x99, 100) == pytest.approx(10.0)
    assert mode06.scale_value(0xFC, 0xFFF6) == pytest.approx(-0.1)
    assert mode06.uasid_unit(0x3C) == "µs"
    assert mode06.uasid_unit(0x41) == "µA"
    assert mode06.uasid_unit(0x1E) == "λ"
    assert mode06.uasid_unit(0x2D) == "mg/stroke"
    assert mode06.uasid_unit(0x0D) == "mA"


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
    assert mode06.mid_name(0xB1) == "Mis-Fire Cylinder 16 Data"
    # J1979DA-era monitors (VVT/Boost/NOx/PM)
    assert mode06.mid_name(0x35) == "VVT Monitor Bank 1"
    assert mode06.mid_name(0x38) == "VVT Monitor Bank 4"
    assert mode06.mid_name(0x85) == "Boost Pressure Control Monitor Bank 1"
    assert mode06.mid_name(0x90) == "NOx Adsorber Monitor Bank 1"
    assert mode06.mid_name(0x99) == "NOx/SCR Catalyst Monitor Bank 2"
    assert mode06.mid_name(0xB2) == "Particulate Matter Filter Monitor Bank 1"
    assert "supported" in mode06.mid_name(0x00)
    assert "Reserved" in mode06.mid_name(0x11)
    assert "Reserved" in mode06.mid_name(0x3E)
    assert "Reserved" in mode06.mid_name(0x51)
    assert "Reserved" in mode06.mid_name(0x92)
    assert "Reserved" in mode06.mid_name(0xB4)
    assert "Reserved" in mode06.mid_name(0xC1)
    assert "manufacturer" in mode06.mid_name(0xE5).lower()


def test_empty_and_garbage():
    assert mode06.parse_test_results("") == []
    assert mode06.parse_test_results("46 01") == []  # truncated record
    assert mode06.parse_test_results("41 0C 1A F8") == []
