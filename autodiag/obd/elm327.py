"""ELM327 adapter session: initialization sequence, command I/O, errors."""

from __future__ import annotations

import re
import time
from collections.abc import Callable
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

# ELM327 ``ATSP`` digits ("0" = auto-search). J1939/user CAN pins use A–C.
VALID_PROTOCOLS = frozenset("0123456789ABC")
# Slow K-line protocols: doubled inter-character timeout (`AT ST 64` = 400 ms).
_KLINE_PROTOCOLS = frozenset("345")


class ElmError(Exception):
    """Adapter or vehicle responded with an error; ``kind`` names it."""

    def __init__(self, kind: str, message: str, raw: str = "") -> None:
        super().__init__(message)
        self.kind = kind
        self.raw = raw


class ElmTimeout(ElmError):
    def __init__(self, message: str, raw: str = "") -> None:
        super().__init__("timeout", message, raw)


class ElmAborted(Exception):
    """Raised when the owner asks an in-flight command to stop.

    Deliberately *not* an :class:`ElmError`: the adapter did nothing wrong, so
    ``except ElmError`` handlers (retry and fallback loops) must not swallow a
    cancellation and send the next command anyway.
    """

    def __init__(self, message: str = "Request cancelled") -> None:
        super().__init__(message)


def _never() -> bool:
    return False


@dataclass(frozen=True)
class SessionInfo:
    adapter: str
    voltage: float | None
    protocol: str | None
    protocol_number: str | None
    stn: bool = False  # STN11xx / OBDLink adapter (extended ST command set)


class Elm327Session:
    """One command at a time over a :class:`Transport` (single worker thread)."""

    def __init__(
        self,
        transport: Transport,
        *,
        command_timeout: float = 5.0,
        reset_timeout: float = 4.0,
        probe_timeout: float = 20.0,
        should_abort: Callable[[], bool] | None = None,
    ) -> None:
        self._transport = transport
        self._command_timeout = command_timeout
        self._reset_timeout = reset_timeout
        self._probe_timeout = probe_timeout
        self._should_abort = should_abort if should_abort is not None else _never
        self.adapter_seen = False
        # set when a command ends without its prompt: late bytes may still be
        # on the wire, so the next command must not trust an empty buffer
        self._unclean = False

    def set_abort_hook(self, should_abort: Callable[[], bool] | None) -> None:
        """Install a predicate that cancels in-flight commands when it returns true.

        Checked between read slices, so a command blocked on a silent bus
        (5 s default, 20 s during the protocol probe) returns within ~30 ms
        instead of holding the worker thread to its timeout.
        """
        self._should_abort = should_abort if should_abort is not None else _never

    # -- lifecycle ----------------------------------------------------------

    def initialize(
        self, *, probe_vehicle: bool = True, protocol: str = "0"
    ) -> SessionInfo:
        """Open the link, run the AT init sequence, optionally probe the vehicle.

        With ``probe_vehicle=False`` the ``0100`` protocol probe and ``ATDP*``
        queries are skipped: the adapter is verified (banner, voltage) without
        needing a vehicle on the bus, and ``protocol`` stays ``None``.

        ``protocol`` pins the bus via ``ATSP`` (see :data:`VALID_PROTOCOLS`);
        ``"0"`` leaves auto-search on. Pinned K-line protocols 3/4/5 also get
        a doubled ``AT ST`` inter-character timeout for slow init timing.

        Raises :class:`ElmError` / :class:`ElmTimeout`. After a plausible
        ``ATZ`` banner, ``adapter_seen`` is ``True`` — callers should stop
        trying other baud rates and surface the error instead.
        """
        protocol = protocol.upper()
        if protocol not in VALID_PROTOCOLS:
            raise ValueError(f"unknown OBD protocol code: {protocol!r}")

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

        # Aggressive adaptive timing: shortens the gap between messages on
        # both ELM327 (v1.4+) and STN firmware; unknown clones answer "?"
        # and are left at their default timing.
        try:
            self._transact("ATAT2", self._command_timeout)
        except ElmError:
            pass

        stn = any(
            marker in f"{banner}\n{adapter}".upper()
            for marker in ("STN", "OBDLINK")
        )
        protocol_number: str | None = None
        protocol_description: str | None = None
        if probe_vehicle:
            self._transact(f"ATSP{protocol}", self._command_timeout)
            if protocol in _KLINE_PROTOCOLS:
                self._transact("AT ST 64", self._command_timeout)
            # ATSP0 makes this trigger auto-detection; SEARCHING... may take ~10-20 s.
            self._transact("0100", self._probe_timeout)

            try:
                protocol_number = (
                    _first_line(self._transact("ATDPN", self._command_timeout)) or None
                )
                protocol_description = (
                    _first_line(self._transact("ATDP", self._command_timeout)) or None
                )
            except ElmError:
                pass  # best-effort: not all clones implement ATDP*

        return SessionInfo(
            adapter=adapter,
            voltage=voltage,
            protocol=protocol_description,
            protocol_number=protocol_number,
            stn=stn,
        )

    def command(self, cmd: str, timeout: float | None = None) -> str:
        """Send one command; return cleaned response text (no prompt/echo)."""
        return self._transact(cmd, timeout if timeout is not None else self._command_timeout)

    def close(self) -> None:
        self._transport.close()

    # -- internals -----------------------------------------------------------

    def _transact(self, cmd: str, timeout: float) -> str:
        self._check_abort()
        self._drain()
        self._check_abort()
        self._transport.write(cmd.encode("ascii") + b"\r")
        raw = self._read_until_prompt(cmd, timeout)
        self._unclean = False  # prompt consumed: the line is clean again
        kind, cleaned = framing.classify(raw, cmd)
        if kind is not None:
            raise ElmError(kind, ERROR_MESSAGES.get(kind, kind), raw=raw)
        return cleaned

    def _read_until_prompt(self, cmd: str, timeout: float) -> str:
        deadline = time.monotonic() + timeout
        buf = bytearray()
        while time.monotonic() < deadline:
            self._check_abort()
            remaining = deadline - time.monotonic()
            chunk = self._transport.read(
                max_bytes=_CHUNK,
                timeout=max(min(_DRAIN_INTERVAL, remaining), 0.005),
            )
            if chunk:
                buf.extend(chunk)
                if _PROMPT in buf:
                    return buf.decode("ascii", errors="replace")
        self._unclean = True
        raise ElmTimeout(
            f"No response to {cmd!r} within {timeout:.1f}s",
            raw=buf.decode("ascii", errors="replace"),
        )

    def _drain(self) -> None:
        """Discard stale bytes (leftover prompts, previous partial reads).

        When the transport can report its buffer (``pending()``), an empty
        buffer costs one non-blocking check instead of a read that waits out
        ``_DRAIN_INTERVAL`` on a quiet port. Transports that cannot answer,
        and the command that follows a timeout, keep the timed drain.
        """
        if not self._unclean:  # after a timeout, wait out the quiet line once
            deadline = time.monotonic() + _DRAIN_MAX
            while True:
                self._check_abort()
                queued = self._transport.pending()
                if queued is None:
                    break  # buffer not visible: use the timed drain below
                if queued <= 0:
                    return
                chunk = self._transport.read(max_bytes=4096, timeout=0.0)
                if not chunk or time.monotonic() >= deadline:
                    return
        self._timed_drain()

    def _timed_drain(self) -> None:
        """Blocking drain until a quiet read, capped at ``_DRAIN_MAX``."""
        deadline = time.monotonic() + _DRAIN_MAX
        while time.monotonic() < deadline:
            self._check_abort()
            if not self._transport.read(max_bytes=4096, timeout=_DRAIN_INTERVAL):
                self._unclean = False
                return

    def _check_abort(self) -> None:
        if self._should_abort():
            raise ElmAborted()


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
