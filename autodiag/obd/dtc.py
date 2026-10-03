"""Modes $03/$07/$0A trouble codes and mode $04 clear."""

from __future__ import annotations

import re

from autodiag.obd import framing

_LETTERS = "PCBU"

# ISO-TP line numbering: "0: ...", "1: ..." ... "F: ..." (colons only here —
# framing._LINE_MARKER also matches mid-line markers, which we do not want).
_LINE_MARKER = re.compile(r"^\s*([0-9A-Fa-f]{1,2}):")


def decode_dtc(high: int, low: int) -> str | None:
    """Two raw bytes → code string (``$0143`` → ``"P0143"``); ``None`` for $0000."""
    if high == 0 and low == 0:
        return None
    letter = _LETTERS[high >> 6]
    number = ((high & 0x3F) << 8) | low
    return f"{letter}{number:04X}"


def parse_dtcs(text: str, *, can: bool | None = None) -> list[str]:
    """Decode cleaned ``03``/``07``/``0A`` responses into code strings.

    Multi-ECU replies carry one ``43`` message per ECU; each is parsed on its
    own (line breaks and ISO-TP numbering frame the messages) so a second
    ECU's header is never decoded as data. Within a message the CAN form has
    a DTC count byte (odd length) while legacy responses are fixed 3-DTC
    slots with zero padding (even length). Pass ``can=`` explicitly when the
    session knows the protocol, otherwise each message's length parity
    decides. Duplicates (same code from several ECUs) are collapsed.
    """
    codes: list[str] = []
    for payload in _split_messages(text):
        codes.extend(_parse_message(payload, can))
    return list(dict.fromkeys(codes))


def parse_clear_success(text: str) -> bool:
    """True when a mode ``04`` response confirms the reset (``44``)."""
    return "44" in framing.flatten_response(text)


def _split_messages(text: str) -> list[str]:
    """Split a response into per-message hex payloads (bytes after ``43``)."""
    messages: list[str] = []
    for line in text.splitlines():
        marker = _LINE_MARKER.match(line)
        index = int(marker.group(1), 16) if marker else None
        flat = framing.flatten_response(_LINE_MARKER.sub("", line, count=1))
        if not flat or any(ch not in "0123456789ABCDEF" for ch in flat):
            continue  # blank or prose line (SEARCHING..., errors) — not payload
        if flat.startswith("43") and (
            index == 0  # ISO-TP first frame / single frame
            or not messages
            or _message_complete(messages[-1])
        ):
            messages.append(flat[2:])
        elif messages:
            messages[-1] += flat  # continuation frame (or legacy extra line)
        else:
            found = flat.find("43")
            if found >= 0:
                messages.append(flat[found + 2:])
            # else: junk with no message header — ignore the line
    return messages


def _message_complete(payload_hex: str) -> bool:
    """Whether a CAN payload already holds all the DTCs its count promises."""
    try:
        data = framing.hex_to_bytes(payload_hex)
    except ValueError:
        return True  # unparseable → treat as closed rather than append
    if not data:
        return True
    if len(data) % 2 == 1:
        return len(data) >= 1 + 2 * data[0]
    return True  # legacy has no length signal; a line is one message


def _parse_message(payload_hex: str, can: bool | None) -> list[str]:
    try:
        data = framing.hex_to_bytes(payload_hex)
    except ValueError:
        return []

    codes: list[str] = []
    while data:
        use_can = (len(data) % 2 == 1) if can is None else can
        if use_can:
            count = data[0]
            end = 1 + 2 * count if len(data) >= 1 + 2 * count else len(data)
            body, data = data[1:end], data[end:].lstrip(b"\x00")
            # embedded next message (multi-ECU on one line) vs padding/junk
            data = data[1:] if data[:1] == b"\x43" else b""
        else:
            body, data = data, b""

        for i in range(0, len(body) - 1, 2):
            code = decode_dtc(body[i], body[i + 1])
            if code is not None:
                codes.append(code)
    return codes
