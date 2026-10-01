"""Readiness monitor / MIL / DTC count tests (PID $01, spec fixtures)."""

from autodiag.obd import readiness


def test_spec_example_status():
    # J1979 §5.3.4 example: A=0x86 B=0x07 C=0xE5 D=0x87
    status = readiness.parse_monitor_status("41 01 86 07 E5 87")
    assert status is not None

    # A: bit7 MIL, bits6-0 count
    assert status.mil_on is True
    assert status.dtc_count == 6

    # B low nibble: all three continuous monitors supported
    assert status.monitor("misfire").supported
    assert status.monitor("fuel").supported
    assert status.monitor("ccm").supported
    # B high nibble all zero → complete
    assert status.monitor("misfire").complete
    assert status.monitor("fuel").complete
    assert status.monitor("ccm").complete

    # C = 1110 0101 → cat, evap, o2s, htr, egr supported; hcat/air/acrf not
    assert status.monitor("cat").supported
    assert status.monitor("evap").supported
    assert status.monitor("o2s").supported
    assert status.monitor("htr").supported
    assert status.monitor("egr").supported
    assert not status.monitor("hcat").supported
    assert not status.monitor("air").supported
    assert not status.monitor("acrf").supported

    # D = 1000 0111 → bits 0,1,2,7 set → cat/hcat/evap/egr NOT complete
    assert not status.monitor("cat").complete
    assert not status.monitor("evap").complete
    assert not status.monitor("egr").complete
    # bit5 (o2s) clear → complete; bit6 (htr) clear → complete
    assert status.monitor("o2s").complete
    assert status.monitor("htr").complete

    assert status.ready is False


def test_mil_off_zero_codes_all_ready():
    # A=0x00 → MIL off, 0 codes; B/C=0 supported-none; D=0 → nothing incomplete
    status = readiness.parse_monitor_status("41 01 00 00 00 00")
    assert status is not None
    assert status.mil_on is False
    assert status.dtc_count == 0
    # No monitors supported → trivially ready
    assert status.ready is True


def test_all_non_continuous_incomplete():
    status = readiness.parse_monitor_status("41 01 00 00 FF FF")
    assert status is not None
    for key in ("cat", "hcat", "evap", "air", "acrf", "o2s", "htr", "egr"):
        assert status.monitor(key).supported
        assert not status.monitor(key).complete
    assert status.ready is False


def test_bad_payloads():
    assert readiness.parse_monitor_status("") is None
    assert readiness.parse_monitor_status("41 01 86") is None  # < 4 bytes
    assert readiness.parse_monitor_status("41 0C 1A F8") is None  # wrong PID
