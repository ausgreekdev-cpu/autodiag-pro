"""Unit tests for ELM327 response framing (pure functions)."""

import pytest

from autodiag.obd import framing


def test_classify_success_strips_prompt():
    kind, text = framing.classify("41 0C 1A F8\r\r>", "010C")
    assert kind is None
    assert text == "41 0C 1A F8"


def test_classify_strips_echo():
    kind, text = framing.classify("010C\r41 0C 1A F8\r>", "010C")
    assert kind is None
    assert not text.upper().startswith("010C")
    assert "41 0C 1A F8" in text


def test_classify_drops_searching_lines():
    kind, text = framing.classify("SEARCHING...\r\n4100BE3E\r\n>", "0100")
    assert kind is None
    assert "SEARCHING" not in text
    assert "4100BE3E" in text


def test_classify_empty_at_response_is_ok():
    # Most AT commands reply with only the prompt — not an error.
    kind, text = framing.classify("\r\r>", "ATE0")
    assert kind is None
    assert text == ""


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("NO DATA\r>", "no-data"),
        ("UNABLE TO CONNECT\r>", "no-vehicle"),
        ("CAN ERROR\r>", "can-error"),
        ("BUS INIT: ERROR\r>", "bus-init-error"),
        ("BUS ERROR\r>", "bus-error"),
        ("DATA ERROR\r>", "data-error"),
        ("BUFFER FULL\r>", "buffer-full"),
        ("FB ERROR\r>", "fb-error"),
        ("LV RESET\r>", "lv-reset"),
        ("STOPPED\r>", "stopped"),
        ("?\r>", "bad-command"),
        ("SEARCHING...\r\nUNABLE TO CONNECT\r\n>", "no-vehicle"),
    ],
)
def test_classify_error_markers(raw, expected):
    kind, _text = framing.classify(raw, "0100")
    assert kind == expected


def test_extract_payload_simple():
    assert framing.extract_payload("41 0C 1A F8", "410C") == "1AF8"
    assert framing.extract_payload("4100BE3EA813", "4100") == "BE3EA813"


def test_extract_payload_missing_prefix():
    assert framing.extract_payload("41 0D 3C", "410C") is None


def test_extract_payload_after_searching():
    text = "SEARCHING...\n4100BE3EA813"
    assert framing.extract_payload(text, "4100") == "BE3EA813"


def test_hex_to_bytes_tolerates_whitespace():
    assert framing.hex_to_bytes("41 0C 1A F8") == bytes.fromhex("410C1AF8")


def test_hex_to_bytes_rejects_odd_length():
    with pytest.raises(ValueError):
        framing.hex_to_bytes("410")
