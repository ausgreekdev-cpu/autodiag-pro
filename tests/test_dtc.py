"""DTC decode (modes $03/$07/$0A) and clear ($04) tests."""

from autodiag.obd import dtc


def test_decode_dtc_spec_example():
    # J1979 §5.3.4 example: $0143 displays as P0143
    assert dtc.decode_dtc(0x01, 0x43) == "P0143"


def test_decode_dtc_all_letter_classes():
    assert dtc.decode_dtc(0x01, 0x33) == "P0133"
    assert dtc.decode_dtc(0x41, 0x43) == "C0143"  # 01b → chassis
    assert dtc.decode_dtc(0x81, 0x43) == "B0143"  # 10b → body
    assert dtc.decode_dtc(0xC1, 0x43) == "U0143"  # 11b → network


def test_decode_dtc_zero_is_empty_slot():
    assert dtc.decode_dtc(0x00, 0x00) is None


def test_parse_can_response_with_count_byte():
    # ISO-15765-4: count byte first → odd length (ELM prints the exact payload)
    text = "43 03 01 33 02 45 03 67"
    assert dtc.parse_dtcs(text) == ["P0133", "P0245", "P0367"]


def test_parse_can_response_padded_explicit():
    # Same payload after ISO-TP padding; caller knows protocol is CAN
    text = "43 03 01 33 02 45 03 67 00 00 00"
    assert dtc.parse_dtcs(text, can=True) == ["P0133", "P0245", "P0367"]


def test_parse_legacy_response_no_count():
    # Even length → legacy fixed slots, no count byte
    text = "43 01 33 02 45 00 00"
    assert dtc.parse_dtcs(text) == ["P0133", "P0245"]


def test_parse_legacy_all_zero():
    assert dtc.parse_dtcs("43 00 00 00 00 00 00") == []


def test_parse_multiline_isotp_response():
    text = "0: 43 02 01 33 02 45\n1: 00 00 00 00"
    codes = dtc.parse_dtcs(text, can=True)
    assert codes == ["P0133", "P0245"]


def test_parse_explicit_can_flag_strips_count():
    # Even-length payload but caller knows it's CAN → count is stripped
    text = "43 01 01 33"  # count=1, one DTC
    assert dtc.parse_dtcs(text, can=True) == ["P0133"]


def test_parse_no_response():
    assert dtc.parse_dtcs("") == []


def test_clear_success():
    assert dtc.parse_clear_success("44") is True
    assert dtc.parse_clear_success("44\r\r>") is True
    assert dtc.parse_clear_success("41 0C 1A F8") is False
