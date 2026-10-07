"""Mode $05 decoder tests — fixtures pinned to the J1979:2002 examples."""

from __future__ import annotations

import pytest

from autodiag.obd.mode05 import (
    parse_supported_tids,
    parse_tid_values,
    scaling,
    sensor_masks,
    sensor_name,
    tid_name,
)


def test_constant_tid_spec_example():
    # §5.5.4 TABLE 63: TID $01, B1S1, value $5A = "450 mV"
    results = parse_tid_values("45 01 01 5A", 0x01, 0x01)
    assert len(results) == 1
    result = results[0]
    assert result.value == pytest.approx(0.45)
    assert result.unit == "V"
    assert result.min_value is None and result.max_value is None  # constant
    assert result.passed is None  # no limits published
    assert result.sensor_label == "Bank 1 - Sensor 1"
    assert result.test_name == "Rich-to-lean sensor threshold voltage (constant)"


def test_calculated_tid_spec_example_with_limits():
    # §5.5.4 TABLE 65: TID $05, B1S1, 72 ms within 0–100 ms
    results = parse_tid_values("45 05 01 12 00 19", 0x05, 0x01)
    assert len(results) == 1
    result = results[0]
    assert result.value == pytest.approx(0.072)
    assert result.min_value == pytest.approx(0.0)
    assert result.max_value == pytest.approx(0.1)
    assert result.unit == "s"
    assert result.passed is True


def test_calculated_tid_failure_and_not_run():
    failing = parse_tid_values("45 05 01 1A 00 19", 0x05, 0x01)[0]
    assert failing.value == pytest.approx(0.104)
    assert failing.passed is False

    not_run = parse_tid_values("45 05 01 00 00 00", 0x05, 0x01)[0]
    assert not_run.passed is None


def test_multi_ecu_records_concatenated():
    flat = "4501015A" + "45010164"
    results = parse_tid_values(flat, 0x01, 0x01)
    assert [r.value for r in results] == pytest.approx([0.45, 0.5])


def test_wrong_prefix_returns_empty():
    assert parse_tid_values("45 05 01 12 00 19", 0x01, 0x01) == []
    assert parse_tid_values("45 01 02 5A", 0x01, 0x01) == []
    assert parse_tid_values("NO DATA", 0x01, 0x01) == []
    assert parse_tid_values("45 01 01", 0x01, 0x01) == []  # truncated


def test_supported_tid_bitmap_spec_example():
    # §5.5.4.1: ECU #1 supports TIDs $01–$06 (plus $70/$71/$81 later)
    text = "45 00 01 FC 00 00 00"
    supported, has_next = parse_supported_tids(text, 0x00, 0x01)
    assert supported == {0x01, 0x02, 0x03, 0x04, 0x05, 0x06}
    assert has_next is False

    next_block = "45 00 01 FC 00 00 01"  # $20 bit set → $21–$40 follow
    supported, has_next = parse_supported_tids(next_block, 0x00, 0x01)
    assert has_next is True
    assert 0x20 in supported


def test_supported_bitmap_wrong_sensor_returns_empty():
    assert parse_supported_tids("45 00 01 FC 00 00 00", 0x00, 0x02) == (set(), False)


def test_tid_names():
    assert tid_name(0x01).startswith("Rich-to-lean")
    assert tid_name(0x00) == "Supported TIDs ($01 - $20)"
    assert tid_name(0x20) == "Supported TIDs ($21 - $40)"
    assert tid_name(0x10) == "Reserved"  # $0B–$1F reserved
    assert tid_name(0x81) == "Manufacturer-defined test $81"
    assert tid_name(0x25) == "Manufacturer test $25"


def test_scaling_appendix_c():
    assert scaling(0x01) == (0.005, 0.0, "V")
    assert scaling(0x05) == (0.004, 0.0, "s")
    assert scaling(0x09) == (0.04, 0.0, "s")
    assert scaling(0x25) == (0.004, 0.0, "s")  # manufacturer $21–$2F
    assert scaling(0x35) == (0.04, 0.0, "s")
    assert scaling(0x45) == (0.005, 0.0, "V")
    assert scaling(0x55) == (0.05, 0.0, "V")
    assert scaling(0x65) == (0.1, 0.0, "Hz")
    assert scaling(0x75) == (1.0, 0.0, "count")
    assert scaling(0x99) == (1.0, 0.0, "")  # $81+ raw, manufacturer units


def test_sensor_location_masks_pid13_layout():
    # PID $13: bits B1S1..B1S4 = 0, B2S1..B2S4 = 4..7 (Appendix B TABLE B10)
    assert sensor_masks(0b0001_0001) == [0x01, 0x10]
    assert sensor_name(0x01) == "Bank 1 - Sensor 1"
    assert sensor_name(0x10) == "Bank 2 - Sensor 1"
    assert sensor_masks(0x00) == []


def test_sensor_location_masks_pid1d_layout():
    # PID $1D: B1S1, B1S2, B2S1, B2S2, B3S1, B3S2, B4S1, B4S2 (TABLE B14)
    assert sensor_masks(0b0000_0101, via_pid_1d=True) == [0x01, 0x04]
    assert sensor_name(0x04, via_pid_1d=True) == "Bank 2 - Sensor 1"
    assert sensor_name(0x80, via_pid_1d=True) == "Bank 4 - Sensor 2"
    assert sensor_name(0x99) == "O2 sensor $99"  # unknown mask


def test_result_sensor_label_uses_pid1d_layout_when_asked():
    results = parse_tid_values("45 01 04 5A", 0x01, 0x04, via_pid_1d=True)
    assert results[0].sensor_label == "Bank 2 - Sensor 1"
    # same mask under the PID $13 layout
    results = parse_tid_values("45 01 04 5A", 0x01, 0x04)
    assert results[0].sensor_label == "Bank 1 - Sensor 3"
