"""Scripted test doubles: a byte-pipe Transport and a serial.Serial stand-in.

Responses mimic real ELM327 output: CR-framed lines, ``>`` prompt, command
echo while echo is on (turned off by ``ATE0``), ``ATZ`` answered with a banner
and no echo.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from autodiag.obd.elm327 import Elm327Session
from autodiag.transports.base import Transport, TransportError
from autodiag.transports.serial_transport import Connection

UNKNOWN = b"?\r\r>"


def elm_script(**overrides: bytes) -> dict[str, bytes]:
    """A healthy adapter script; pass e.g. ``0100=b"UNABLE..."`` to break it."""
    script: dict[str, bytes] = {
        "ATZ": b"\r\rELM327 v1.5\r\r>",
        "ATE0": b"\r\r>",
        "ATL0": b"\r\r>",
        "ATS0": b"\r\r>",
        "ATH0": b"\r\r>",
        "ATRV": b"12.6V\r\r>",
        "ATI": b"\r\rELM327 v1.5\r\r>",
        "ATSP0": b"\r\r>",
        "0100": b"SEARCHING...\r\n4100BE3EA813\r\n>",
        "ATDPN": b"A\r\r>",
        "ATDP": b"AUTO, ISO 15765-4 (CAN 11/500)\r\r>",
        "010C": b"41 0C 1A F8\r\r>",
        "010D": b"41 0D 3C\r\r>",
        "0105": b"41 05 7B\r\r>",
    }
    script.update({k.upper(): v for k, v in overrides.items()})
    return script


class _ScriptedOutput:
    """Shared write→buffer logic for FakeTransport and FakeSerial."""

    def __init__(self, responses: dict[str, bytes] | None, *, silent: bool, echo: bool) -> None:
        self._responses = {k.upper(): v for k, v in (responses or {}).items()}
        self._silent = silent
        self._echo = echo
        self._buf = bytearray()
        self.writes: list[str] = []

    def _on_write(self, data: bytes) -> None:
        if self._silent:
            return
        cmd = data.decode("ascii", errors="replace").strip().upper()
        self.writes.append(cmd)
        body = self._responses.get(cmd, UNKNOWN)
        if body is UNKNOWN and (
            cmd.startswith("ATSP") or cmd.replace(" ", "").startswith("ATST")
        ):
            body = b"\r\r>"  # protocol pin / timeout setters: healthy adapters answer OK
        if cmd == "ATZ":
            out = body  # adapter resets: banner, no echo
        elif self._echo:
            out = cmd.encode("ascii") + b"\r" + body
        else:
            out = body
        self._buf.extend(out)
        if cmd == "ATE0":
            self._echo = False

    def _on_read(self, size: int, timeout: float) -> bytes:
        if not self._buf:
            # Emulate a blocking read without hot-spinning the test loop.
            time.sleep(min(max(timeout, 0), 0.01))
            return b""
        n = min(size, len(self._buf))
        chunk = bytes(self._buf[:n])
        del self._buf[:n]
        return chunk

    def inject(self, data: bytes) -> None:
        """Preload bytes (simulates stale output the session must drain)."""
        self._buf.extend(data)


class FakeTransport(Transport, _ScriptedOutput):
    """In-memory Transport that answers commands from a script."""

    def __init__(
        self,
        responses: dict[str, bytes] | None = None,
        *,
        silent: bool = False,
        echo: bool = True,
    ) -> None:
        _ScriptedOutput.__init__(self, responses, silent=silent, echo=echo)
        self._open = False

    def open(self) -> None:
        self._open = True

    def close(self) -> None:
        self._open = False

    def write(self, payload: bytes) -> None:
        if not self._open:
            raise TransportError("fake transport is not open")
        self._on_write(payload)

    def read(self, max_bytes: int = 1024, timeout: float = 0.1) -> bytes:
        if not self._open:
            return b""
        return self._on_read(max_bytes, timeout)

    @property
    def is_open(self) -> bool:
        return self._open


class FakeSerial(_ScriptedOutput):
    """Mimics the subset of ``serial.Serial`` used by SerialTransport."""

    def __init__(
        self,
        responses: dict[str, bytes] | None = None,
        *,
        silent: bool = False,
        echo: bool = True,
    ) -> None:
        _ScriptedOutput.__init__(self, responses, silent=silent, echo=echo)
        self.timeout = 0.0
        self.is_open = True

    def write(self, data: bytes) -> int:
        if not self.is_open:
            raise OSError("port closed")
        self._on_write(data)
        return len(data)

    def read(self, size: int = 1) -> bytes:
        return self._on_read(size, self.timeout)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        self.is_open = False


class RecordingFactory:
    """serial_factory double: scripted FakeSerial per baud, records attempts."""

    def __init__(self, per_baud: dict[int, FakeSerial]) -> None:
        self.per_baud = per_baud
        self.attempts: list[tuple[str, int]] = []

    def __call__(self, device: str, baud: int) -> FakeSerial:
        self.attempts.append((device, baud))
        ser = self.per_baud.get(baud)
        return ser if ser is not None else FakeSerial(silent=True)


def scripted_connector(
    responses: dict[str, bytes] | None = None,
) -> tuple[Callable[[str], Any], dict[str, Any]]:
    """Engine-level connector double: returns ``(connector, holder)``.

    ``holder["transport"]`` / ``holder["session"]`` are populated on each
    successful connect so tests can reach in (e.g. to close the transport).
    """
    script = elm_script(**(responses or {}))
    holder: dict[str, Any] = {}

    def connector(device: str) -> Any:
        transport = FakeTransport(script)
        session = Elm327Session(transport)
        info = session.initialize()
        holder["transport"] = transport
        holder["session"] = session
        holder["device"] = device
        return Connection(session=session, info=info, baudrate=38400)

    return connector, holder
