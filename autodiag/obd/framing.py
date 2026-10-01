"""ELM327 response framing: prompt handling, echo removal, error classification.

Pure functions — no I/O — so every quirk of ELM327 output can be unit-tested.
"""

from __future__ import annotations

import re

PROMPT = ">"

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


def extract_payload(text: str, prefix: str) -> str | None:
    """Hex bytes following a response prefix (e.g. ``"410C"``), no whitespace.

    Returns ``None`` when the prefix is absent (wrong PID / no data).
    """
    flat = re.sub(r"\s+", "", text).upper()
    idx = flat.find(prefix.upper())
    if idx < 0:
        return None
    return flat[idx + len(prefix):]


def hex_to_bytes(hex_text: str) -> bytes:
    """Whitespace-tolerant hex decode; raises ``ValueError`` on bad input."""
    flat = re.sub(r"\s+", "", hex_text)
    return bytes.fromhex(flat)
