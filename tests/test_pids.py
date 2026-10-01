"""Mode $01 PID decoding tests (SAE J1979 formulas, spec fixtures)."""

import pytest

from autodiag.obd import framing, pids


def test_decode_rpm():
    # 0x1AF8 = 6904 → /4 = 1726 rpm
    assert pids.decode_pid(0x0C, bytes.fromhex("1AF8")) == pytest.approx(1726)


def test_decode_speed_coolant_load():
    assert pids.decode_pid(0x0D, bytes.fromhex("3C")) == 60
    assert pids.decode_pid(0x05, bytes.fromhex("7B")) == 83  # 123 - 40
    assert pids.decode_pid(0x04, bytes.fromhex("7F")) == pytest.approx(49.8, abs=0.1)


def test_decode_fuel_trims():
    assert pids.decode_pid(0x06, bytes.fromhex("80")) == pytest.approx(0.0, abs=0.01)
    assert pids.decode_pid(0x06, bytes.fromhex("90")) == pytest.approx(12.5, abs=0.01)
    assert pids.decode_pid(0x07, bytes.fromhex("40")) == pytest.approx(-50.0, abs=0.01)


def test_decode_maf_throttle_voltage_o2():
    assert pids.decode_pid(0x10, bytes.fromhex("01F4")) == pytest.approx(5.0)
    assert pids.decode_pid(0x11, bytes.fromhex("FF")) == pytest.approx(100.0)
    assert pids.decode_pid(0x42, bytes.fromhex("3039")) == pytest.approx(12.345)
    assert pids.decode_pid(0x14, bytes.fromhex("9C800000")) == pytest.approx(0.78)


def test_decode_unknown_and_truncated():
    assert pids.decode_pid(0xEE, b"\x01") is None
    assert pids.decode_pid(0x0C, bytes.fromhex("1A")) is None  # RPM needs 2 bytes


def test_parse_pid_value_from_response_text():
    assert pids.parse_pid_value("41 0C 1A F8", 0x0C) == pytest.approx(1726)
    assert pids.parse_pid_value("SEARCHING...\n4100BE3E", 0x0C) is None
    assert pids.parse_pid_value("41 0D 3C", 0x0C) is None


def test_parse_supported_pids_first_block():
    supported, nxt = pids.parse_supported_pids("4100BE3EA813")
    assert 0x01 in supported  # A = 1011 1110 → PID 01 supported
    assert 0x02 not in supported  # bit 6 clear
    assert 0x0C in supported  # RPM (byte B, bit 4 set)
    assert nxt is True  # PID 20 bit set → next block available
    assert 0x20 in supported


def test_parse_supported_pids_empty():
    assert pids.parse_supported_pids("") == (set(), False)


def test_registry_entries_are_sane():
    assert pids.PID_REGISTRY[0x0C].unit == "rpm"
    assert pids.PID_REGISTRY[0x05].unit == "°C"
    for definition in pids.PID_REGISTRY.values():
        assert 1 <= definition.data_bytes <= 4
        assert definition.name


def test_supported_mask_helper_direct():
    supported, nxt = framing.parse_supported_mask("4600BE3EA813", "4600", 0x00)
    assert 0x01 in supported
    assert nxt is True
