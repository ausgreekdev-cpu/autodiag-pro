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


def test_parse_multi_ecu_legacy_separate_lines():
    # Two ECUs each answer with their own `43` message (CR-separated on ELM)
    text = "43 01 33 02 45 00 00\r43 03 67 00 00 00 00"
    assert dtc.parse_dtcs(text) == ["P0133", "P0245", "P0367"]


def test_parse_multi_ecu_can_numbering_restarts():
    # Each ISO-TP message numbers its frames from 0 again
    text = "0: 43 01 01 33\n1: 00 00 00 00\n0: 43 01 03 67\n1: 00 00 00 00"
    assert dtc.parse_dtcs(text) == ["P0133", "P0367"]


def test_parse_can_count_splits_embedded_second_message():
    # Two CAN messages concatenated on one line: the count byte of the first
    # ends it exactly, so the second `43` is recognized as a new header
    text = "43 01 01 33 43 01 03 67"
    assert dtc.parse_dtcs(text) == ["P0133", "P0367"]


def test_parse_truncated_can_frame_continuation():
    # C-class DTCs: a continuation line can start with `43` (high byte of a
    # C0xxx code) — completeness of the count byte disambiguates
    text = "0: 43 03 43 13 43 14\n1: 43 15"
    assert dtc.parse_dtcs(text) == ["C0313", "C0314", "C0315"]


def test_parse_deduplicates_codes_across_ecus():
    text = "43 01 33 00 00 00 00\r43 01 33 00 00 00 00"
    assert dtc.parse_dtcs(text) == ["P0133"]


def test_parse_junk_lines_around_response_ignored():
    text = "SEARCHING...\rNO DATA\r43 01 33 00 00 00 00\rgarbage!"
    assert dtc.parse_dtcs(text) == ["P0133"]


def test_clear_success():
    assert dtc.parse_clear_success("44") is True
    assert dtc.parse_clear_success("44\r\r>") is True
    assert dtc.parse_clear_success("41 0C 1A F8") is False
