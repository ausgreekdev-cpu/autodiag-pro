"""ELM327 response framing: prompt handling, echo removal, error classification.

Pure functions — no I/O — so every quirk of ELM327 output can be unit-tested.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

PROMPT = ">"

# Multi-line responses are numbered per ISO-TP: "0: ...", "1: ..." ... "F: ...".
_LINE_MARKER = re.compile(r"(?m)^\s*[0-9A-F]{1,2}:")

# Ordered longest/most-specific first. Every marker contains at least one
# non-hex character, so they can never collide with a hex payload.
ERROR_MARKERS: tuple[tuple[str, str], ...] = (
    ("UNABLE TO CONNECT", "no-vehicle"),
    ("BUS INIT: ERROR", "bus-init-error"),
    ("BUFFER FULL", "buffer-full"),
    ("CAN ERROR", "can-error"),
    ("BUS ERROR", "bus-error"),
    ("DATA ERROR", "data-error"),
    ("FB ERROR", "fb-error"),
    ("LV RESET", "lv-reset"),
    ("STOPPED", "stopped"),
    ("NO DATA", "no-data"),
    ("?", "bad-command"),
)

SEARCHING = "SEARCHING..."


def strip_prompt(text: str) -> str:
    """Remove every ELM327 ``>`` prompt character."""
    return text.replace(PROMPT, "")


def strip_echo(text: str, cmd: str) -> str:
    """Drop a leading echo of ``cmd`` (adapters with echo still enabled)."""
    stripped = text.lstrip("\r\n\t ")
    if cmd and stripped.upper().startswith(cmd.upper()):
        rest = stripped[len(cmd):]
        if not rest[:1].strip() or rest[:1] in "\r\n\t":
            return rest
    return text


def drop_searching(text: str) -> str:
    """Remove transient ``SEARCHING...`` lines (protocol detection noise)."""
    lines = [line for line in text.splitlines() if SEARCHING not in line.upper()]
    return "\n".join(lines)


def classify(raw: str, cmd: str = "") -> tuple[str | None, str]:
    """Classify a raw adapter response.

    Returns ``(error_kind, cleaned_text)``. ``error_kind`` is ``None`` on
    success (including a legitimately empty response — most AT commands reply
    with only the ``>`` prompt). ``cleaned_text`` has the prompt, echo and
    ``SEARCHING...`` lines removed and is what decoders consume.
    """
    text = strip_prompt(raw)
    text = strip_echo(text, cmd)
    text = drop_searching(text).strip()

    haystack = " ".join(text.upper().split())
    for marker, kind in ERROR_MARKERS:
        if marker in haystack:
            return kind, text
    return None, text


def flatten_response(text: str) -> str:
    """Collapse a response to one uppercase hex string.

    Removes line breaks and ISO-TP line markers (``0:``, ``1:``, ...) so
    multi-frame payloads (VIN, long DTC lists, Mode $06 dumps) become a
    single continuous hex string.
    """
    return re.sub(r"\s+", "", _LINE_MARKER.sub("", text)).upper()


def extract_payload(text: str, prefix: str) -> str | None:
    """Hex bytes following a response prefix (e.g. ``"410C"``), no whitespace.

    Returns ``None`` when the prefix is absent (wrong PID / no data).
    """
    flat = flatten_response(text)
    idx = flat.find(prefix.upper())
    if idx < 0:
        return None
    return flat[idx + len(prefix):]


def split_pid_chunks(
    text: str,
    pids: Iterable[int],
    data_lengths: Mapping[int, int] | None = None,
) -> dict[int, str]:
    """Split a multi-PID ``01 xx 01 yy …`` response into per-PID chunks.

    Each chunk keeps its ``41 <pid>`` prefix so the single-PID parsers
    (``extract_payload`` / ``parse_pid_values``) work unchanged. Only
    requested ``pids`` are recognized and the first occurrence per PID wins
    (extra ECUs answering the same PID are ignored — same as single-PID
    requests).

    When ``data_lengths`` (J1979 payload size in bytes per PID) is given,
    chunk boundaries follow that structure, so payload bytes that happen to
    spell ``41 <pid>`` (e.g. RPM 4163.25 = ``41 0D`` next to a requested
    ``0D``) cannot create false markers. Without lengths the split is a
    plain byte-aligned marker scan.
    """
    flat = flatten_response(strip_prompt(text))
    wanted = {f"41{pid:02X}": pid for pid in pids}
    steps = {
        f"41{pid:02X}": 4 + 2 * data_lengths[pid]
        for pid in pids
        if data_lengths and pid in data_lengths
    }

    def next_marker(search: int) -> tuple[int, str] | None:
        for index in range(search & ~1, len(flat) - 3, 2):  # byte-aligned
            token = flat[index : index + 4]
            if token in wanted:
                return index, token
        return None

    chunks: dict[int, str] = {}
    search = 0
    while True:
        found = next_marker(search)
        if found is None:
            return chunks
        start, token = found
        pid = wanted[token]
        step = steps.get(token)
        if pid in chunks:
            search = start + (step if step else 4)  # duplicate/extra ECU
            continue
        if step:
            end = min(start + step, len(flat))
            chunks[pid] = flat[start:end]
            search = end
        else:
            following = next_marker(start + 4)
            end = following[0] if following else len(flat)
            chunks[pid] = flat[start:end]
            search = start + 4


def parse_supported_mask(
    text: str,
    prefix: str,
    base: int,
) -> tuple[set[int], bool]:
    """Decode a 32-ID support bitmap (PIDs ``0100``/``0120``..., OBDMIDs...).

    Returns ``(ids supported in this block, next block bit set)`` — query the
    next block when the second element is ``True``.
    """
    payload = extract_payload(text, prefix)
    if payload is None:
        return set(), False
    try:
        data = hex_to_bytes(payload)
    except ValueError:
        return set(), False
    if len(data) < 4:
        return set(), False
    bits = int.from_bytes(data[:4], "big")
    supported = {base + i + 1 for i in range(32) if bits & (1 << (31 - i))}
    return supported, (base + 0x20) in supported


def hex_to_bytes(hex_text: str) -> bytes:
    """Whitespace-tolerant hex decode; raises ``ValueError`` on bad input."""
    flat = re.sub(r"\s+", "", hex_text)
    return bytes.fromhex(flat)
