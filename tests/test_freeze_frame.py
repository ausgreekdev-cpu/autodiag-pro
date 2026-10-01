"""Freeze frame (mode $02) decode tests."""

from autodiag.obd import freeze_frame


def test_frame_byte_present():
    # 42 0C [frame 00] 1A F8 → 1726 rpm
    frame = freeze_frame.parse_freeze_frame("42 0C 00 1A F8", 0x0C)
    assert frame is not None
    assert frame.pid == 0x0C
    assert frame.value == 1726
    assert frame.name == "Engine RPM"
    assert frame.unit == "rpm"


def test_frame_byte_absent():
    frame = freeze_frame.parse_freeze_frame("420C1AF8", 0x0C)
    assert frame is not None
    assert frame.value == 1726


def test_single_byte_pid_frame():
    frame = freeze_frame.parse_freeze_frame("42 0D 00 3C", 0x0D)
    assert frame is not None
    assert frame.value == 60
    assert frame.name == "Vehicle speed"


def test_wrong_mode_returns_none():
    assert freeze_frame.parse_freeze_frame("41 0C 1A F8", 0x0C) is None


def test_unknown_pid_returns_none():
    assert freeze_frame.parse_freeze_frame("42 EE 01 02", 0xEE) is None


def test_named_frame_number():
    # Frame 2 requested and echoed back
    frame = freeze_frame.parse_freeze_frame("42 05 02 7B", 0x05, frame=2)
    assert frame is not None
    assert frame.frame == 2
    assert frame.value == 83
