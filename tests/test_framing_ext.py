"""DTC dictionary and framing helper tests."""

from autodiag.obd import dictionary, framing


def test_dictionary_lookup():
    assert dictionary.describe("P0301") == "Cylinder 1 Misfire Detected"
    assert dictionary.describe("p0301") == "Cylinder 1 Misfire Detected"
    assert dictionary.describe("Z0000") is None
    assert dictionary.describe("") is None


def test_dictionary_is_cached():
    assert dictionary.load_dictionary() is dictionary.load_dictionary()


def test_flatten_response_strips_isotp_markers():
    text = "0: 49 02 01 31 44\n1: 34 47 50"
    assert framing.flatten_response(text) == "4902013144344750"
    # All whitespace (incl. CR/LF) collapses
    assert framing.flatten_response("SEARCHING...\r4100BE3E\r\r>") == (
        "SEARCHING...4100BE3E>"
    )


def test_flatten_response_uppercases():
    assert framing.flatten_response("41 0c 1a f8") == "410C1AF8"


def test_extract_payload_uses_flatten():
    text = "0: 41 0C 1A\n1: F8"
    assert framing.extract_payload(text, "410C") == "1AF8"


def test_extract_payload_missing():
    assert framing.extract_payload("41 0D 3C", "410C") is None
