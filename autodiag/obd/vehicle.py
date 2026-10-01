"""Mode $09 vehicle information: VIN, calibration IDs, CVN."""

from __future__ import annotations

import re

from autodiag.obd import framing

_VIN_RE = re.compile(r"[A-HJ-NPR-Z0-9]{17}")
_ASCII_RUN_RE = re.compile(r"[ -~]{4,}")


def _payload(text: str, prefix: str) -> bytes | None:
    flat = framing.extract_payload(text, prefix)
    if flat is None:
        return None
    try:
        return framing.hex_to_bytes(flat)
    except ValueError:
        return None


def parse_vin(text: str) -> str | None:
    """Extract the 17-char VIN from a cleaned ``0902`` response.

    Handles ISO-TP line numbering and the leading message-count byte
    (non-printable, filtered with the padding NULs).
    """
    data = _payload(text, "4902")
    if not data:
        return None
    ascii_text = "".join(chr(b) for b in data if 0x20 <= b < 0x7F)
    match = _VIN_RE.search(ascii_text)
    return match.group(0) if match else None


def parse_cal_ids(text: str) -> list[str]:
    """Calibration IDs (ASCII runs ≥ 4 chars) from a ``0904`` response."""
    data = _payload(text, "4904")
    if not data:
        return []
    ascii_text = "".join(chr(b) if 0x20 <= b < 0x7F else "\n" for b in data)
    return _ASCII_RUN_RE.findall(ascii_text)


def parse_cvns(text: str) -> list[str]:
    """Calibration verification numbers (8-hex-char) from a ``0906`` response."""
    data = _payload(text, "4906")
    if not data:
        return []
    # Layout: [msg count] [4-byte CVN] ... — count byte is ≤ 4, CVNs never
    # start with a value that small in practice for the count position.
    if data[0] <= 4 and len(data) >= 5:
        data = data[1:]
    cvns = []
    for i in range(0, len(data) - 3, 4):
        chunk = data[i:i + 4]
        if chunk == b"\x00" * 4:
            continue
        cvns.append(chunk.hex().upper())
    return cvns
