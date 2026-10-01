"""ELM327 adapter session: initialization sequence, command I/O, errors."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

from autodiag.obd import framing
from autodiag.transports.base import Transport

_PROMPT = b">"
_CHUNK = 512
_DRAIN_INTERVAL = 0.03
_DRAIN_MAX = 0.5

ERROR_MESSAGES: dict[str, str] = {
    "no-vehicle": (
        "Vehicle did not respond — is the ignition ON (engine may be off)? "
        "Check the adapter is fully seated in the OBD-II port."
    ),
    "no-data": "The vehicle returned no data for this request.",
    "bad-command": "The adapter did not understand the command.",
    "can-error": "CAN bus error — try again or cycle the ignition.",
    "bus-error": "OBD bus error — try again or cycle the ignition.",
    "bus-init-error": "Bus initialization failed — ignition off or unsupported protocol.",
    "stopped": "The adapter stopped the request.",
    "data-error": "The adapter reported a data error.",
    "buffer-full": "Adapter buffer full — polling too fast; retry.",
    "fb-error": "Bus feedback error.",
    "lv-reset": "Adapter reset (low voltage) — check battery and connection.",
    "no-adapter": "Adapter sent garbage — wrong baud rate or not an ELM327 device.",
    "timeout": "No response from the adapter.",
}


class ElmError(Exception):
    """Adapter or vehicle responded with an error; ``kind`` names it."""

    def __init__(self, kind: str, message: str, raw: str = "") -> None:
        super().__init__(message)
        self.kind = kind
        self.raw = raw


class ElmTimeout(ElmError):
    def __init__(self, message: str, raw: str = "") -> None:
        super().__init__("timeout", message, raw)


@dataclass(frozen=True)
class SessionInfo:
    adapter: str
    voltage: float | None
    protocol: str | None
    protocol_number: str | None


class Elm327Session:
    """One command at a time over a :class:`Transport` (single worker thread)."""

    def __init__(
        self,
        transport: Transport,
        *,
        command_timeout: float = 5.0,
        reset_timeout: float = 4.0,
        probe_timeout: float = 20.0,
    ) -> None:
        self._transport = transport
        self._command_timeout = command_timeout
        self._reset_timeout = reset_timeout
        self._probe_timeout = probe_timeout
        self.adapter_seen = False

    # -- lifecycle ----------------------------------------------------------

    def initialize(self) -> SessionInfo:
        """Open the link, run the AT init sequence, probe the vehicle.

        Raises :class:`ElmError` / :class:`ElmTimeout`. After a plausible
        ``ATZ`` banner, ``adapter_seen`` is ``True`` — callers should stop
        trying other baud rates and surface the error instead.
        """
        if not self._transport.is_open:
            self._transport.open()

        banner = self._transact("ATZ", self._reset_timeout)
        if not _is_plausible(banner):
            raise ElmError(
                "no-adapter",
                ERROR_MESSAGES["no-adapter"],
                raw=banner,
            )
        adapter = _first_line(banner) or "ELM327"
        self.adapter_seen = True

        for cmd in ("ATE0", "ATL0", "ATS0", "ATH0"):
            self._transact(cmd, self._command_timeout)

        voltage = _parse_voltage(self._transact("ATRV", self._command_timeout))

        try:
            adapter = _first_line(self._transact("ATI", self._command_timeout)) or adapter
        except ElmError:
            pass  # some clones dislike ATI; the ATZ banner is good enough

        self._transact("ATSP0", self._command_timeout)
        # Triggers protocol auto-detection; SEARCHING... may take ~10-20 s.
        self._transact("0100", self._probe_timeout)

        protocol_number: str | None = None
        protocol: str | None = None
        try:
            protocol_number = _first_line(self._transact("ATDPN", self._command_timeout)) or None
            protocol = _first_line(self._transact("ATDP", self._command_timeout)) or None
        except ElmError:
            pass  # best-effort: not all clones implement ATDP*

        return SessionInfo(
            adapter=adapter,
            voltage=voltage,
            protocol=protocol,
            protocol_number=protocol_number,
        )

    def command(self, cmd: str, timeout: float | None = None) -> str:
        """Send one command; return cleaned response text (no prompt/echo)."""
        return self._transact(cmd, timeout if timeout is not None else self._command_timeout)

    def close(self) -> None:
        self._transport.close()

    # -- internals -----------------------------------------------------------

    def _transact(self, cmd: str, timeout: float) -> str:
        self._drain()
        self._transport.write(cmd.encode("ascii") + b"\r")
        raw = self._read_until_prompt(cmd, timeout)
        kind, cleaned = framing.classify(raw, cmd)
        if kind is not None:
            raise ElmError(kind, ERROR_MESSAGES.get(kind, kind), raw=raw)
        return cleaned

    def _read_until_prompt(self, cmd: str, timeout: float) -> str:
        deadline = time.monotonic() + timeout
        buf = bytearray()
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            chunk = self._transport.read(
                max_bytes=_CHUNK,
                timeout=max(min(_DRAIN_INTERVAL, remaining), 0.005),
            )
            if chunk:
                buf.extend(chunk)
                if _PROMPT in buf:
                    return buf.decode("ascii", errors="replace")
        raise ElmTimeout(
            f"No response to {cmd!r} within {timeout:.1f}s",
            raw=buf.decode("ascii", errors="replace"),
        )

    def _drain(self) -> None:
        """Discard stale bytes (leftover prompts, previous partial reads)."""
        deadline = time.monotonic() + _DRAIN_MAX
        while time.monotonic() < deadline:
            if not self._transport.read(max_bytes=4096, timeout=_DRAIN_INTERVAL):
                return


def _is_plausible(text: str) -> bool:
    """True when ``text`` looks like an ELM327 banner, not baud-rate garbage."""
    sample = text[:200]
    if not sample.strip():
        return False
    printable = sum(1 for c in sample if c.isprintable() or c in "\r\n\t")
    return printable / len(sample) >= 0.9


def _first_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ""


def _parse_voltage(text: str) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*V", text, re.IGNORECASE)
    return float(match.group(1)) if match else None
