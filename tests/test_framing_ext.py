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


def test_split_pid_chunks_flat_batch():
    chunks = framing.split_pid_chunks("410C1AF8410D3C", [0x0C, 0x0D])
    assert chunks == {0x0C: "410C1AF8", 0x0D: "410D3C"}


def test_split_pid_chunks_handles_spacing_and_isotp():
    text = "SEARCHING...\r\n0: 41 0C 1A\n1: F8 41 0D 3C\r\r>"
    chunks = framing.split_pid_chunks(text, [0x0C, 0x0D])
    assert chunks == {0x0C: "410C1AF8", 0x0D: "410D3C"}


def test_split_pid_chunks_first_occurrence_wins():
    chunks = framing.split_pid_chunks("410C1AF8410C1B00410D3C", [0x0C, 0x0D])
    assert chunks[0x0C] == "410C1AF8"
    assert chunks[0x0D] == "410D3C"


def test_split_pid_chunks_skips_unrequested_pids():
    chunks = framing.split_pid_chunks("41057B410C1AF8", [0x0C])
    assert chunks == {0x0C: "410C1AF8"}


def test_split_pid_chunks_missing_pid_absent():
    chunks = framing.split_pid_chunks("410C1AF8", [0x0C, 0x0D])
    assert 0x0D not in chunks


def test_split_pid_chunks_empty_and_garbage():
    assert framing.split_pid_chunks("", [0x0C]) == {}
    assert framing.split_pid_chunks("NO DATA", [0x0C]) == {}


def test_split_pid_chunks_length_chain_beats_payload_collision():
    # RPM 4163.25 encodes as data 41 0D — byte-aligned but NOT a marker.
    chunks = framing.split_pid_chunks(
        "410C410D410D3C", [0x0C, 0x0D], {0x0C: 2, 0x0D: 1}
    )
    assert chunks == {0x0C: "410C410D", 0x0D: "410D3C"}


def test_split_pid_chunks_marker_scan_without_lengths():
    chunks = framing.split_pid_chunks("410C1AF8410D3C", [0x0C, 0x0D])
    assert chunks[0x0C] == "410C1AF8"


def test_split_pid_chunks_truncated_response():
    chunks = framing.split_pid_chunks(
        "410C1AF", [0x0C, 0x0D], {0x0C: 2, 0x0D: 1}
    )
    assert chunks[0x0C] == "410C1AF"  # clamped, decoder will reject it
    assert 0x0D not in chunks
