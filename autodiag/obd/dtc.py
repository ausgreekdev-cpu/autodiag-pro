"""Modes $03/$07/$0A trouble codes and mode $04 clear."""

from __future__ import annotations

from autodiag.obd import framing

_LETTERS = "PCBU"


def decode_dtc(high: int, low: int) -> str | None:
    """Two raw bytes → code string (``$0143`` → ``"P0143"``); ``None`` for $0000."""
    if high == 0 and low == 0:
        return None
    letter = _LETTERS[high >> 6]
    number = ((high & 0x3F) << 8) | low
    return f"{letter}{number:04X}"


def parse_dtcs(text: str, *, can: bool | None = None) -> list[str]:
    """Decode a cleaned ``03``/``07``/``0A`` response into code strings.

    CAN (ISO 15765-4) responses carry a leading count byte and an odd total
    length; legacy (ISO 9141 / KWP / J1850) responses are fixed 3-DTC slots
    with zero padding and even length. Pass ``can=`` explicitly when the
    session knows the protocol, otherwise the length heuristic is used.
    """
    flat = framing.flatten_response(text)
    idx = flat.find("43")
    if idx < 0:
        return []
    try:
        data = framing.hex_to_bytes(flat[idx + 2:])
    except ValueError:
        return []
    if not data:
        return []
    if can is None:
        can = len(data) % 2 == 1
    body = data[1:] if can else data

    codes: list[str] = []
    for i in range(0, len(body) - 1, 2):
        code = decode_dtc(body[i], body[i + 1])
        if code is not None:
            codes.append(code)
    return codes


def parse_clear_success(text: str) -> bool:
    """True when a mode ``04`` response confirms the reset (``44``)."""
    return "44" in framing.flatten_response(text)
