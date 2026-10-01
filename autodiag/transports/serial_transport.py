"""Serial transport (USB / Bluetooth SPP) and auto-baud ELM327 connect."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

import serial
from serial.tools import list_ports

from autodiag.obd.elm327 import Elm327Session, ElmError, SessionInfo
from autodiag.transports.base import Transport, TransportError

# Cheap ELM327 clones ship at different defaults; probe the common ones.
BAUD_CANDIDATES: tuple[int, ...] = (38400, 115200, 57600, 9600)

SerialFactory = Callable[[str, int], "serial.Serial"]


@dataclass(frozen=True)
class SerialPortInfo:
    device: str
    description: str

    def __str__(self) -> str:
        return f"{self.device} — {self.description}"


def list_serial_ports() -> list[SerialPortInfo]:
    """All serial ports the OS knows about (USB serial + paired BT SPP)."""
    return [SerialPortInfo(p.device, p.description or p.device) for p in list_ports.comports()]


class SerialTransport(Transport):
    """pyserial-backed byte pipe on a named device (``COM5``, ``/dev/ttyUSB0``)."""

    def __init__(
        self,
        device: str,
        baudrate: int,
        *,
        serial_factory: SerialFactory | None = None,
    ) -> None:
        self.device = device
        self.baudrate = baudrate
        self._factory = serial_factory or _open_serial
        self._ser: serial.Serial | None = None

    def open(self) -> None:
        if self._ser is not None and self._ser.is_open:
            return
        try:
            self._ser = self._factory(self.device, self.baudrate)
        except TransportError:
            raise
        except Exception as exc:
            raise TransportError(f"Cannot open {self.device}: {exc}") from exc

    def close(self) -> None:
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass  # closing a dead port must never raise
            self._ser = None

    def write(self, payload: bytes) -> None:
        ser = self._require()
        try:
            ser.write(payload)
            ser.flush()
        except Exception as exc:
            raise TransportError(f"Write to {self.device} failed: {exc}") from exc

    def read(self, max_bytes: int = 1024, timeout: float = 0.1) -> bytes:
        ser = self._require()
        try:
            ser.timeout = timeout
            data = ser.read(max_bytes)
        except Exception as exc:
            raise TransportError(f"Read from {self.device} failed: {exc}") from exc
        return data or b""

    @property
    def is_open(self) -> bool:
        return self._ser is not None and self._ser.is_open

    def _require(self) -> serial.Serial:
        if self._ser is None or not self._ser.is_open:
            raise TransportError(f"{self.device} is not open")
        return self._ser


def _open_serial(device: str, baud: int) -> serial.Serial:
    return serial.Serial(device, baudrate=baud, timeout=0, write_timeout=2)


@dataclass(frozen=True)
class Connection:
    """A successfully initialized ELM327 link."""

    session: Elm327Session
    info: SessionInfo
    baudrate: int


def connect_elm327(
    device: str,
    *,
    bauds: Sequence[int] = BAUD_CANDIDATES,
    serial_factory: SerialFactory | None = None,
    session_options: dict[str, float] | None = None,
    on_status: Callable[[str], None] | None = None,
) -> Connection:
    """Open ``device``, auto-detect baud rate, run the ELM327 init sequence.

    Each baud is tried until the adapter answers ``ATZ`` with a plausible
    banner. Once an adapter is found, vehicle-side errors (ignition off, no
    data) surface immediately instead of churning through more baud rates.
    Port-level failures (permissions, unplugged) also stop immediately.
    """
    status = on_status if on_status is not None else (lambda _msg: None)
    last_error: Exception | None = None

    for baud in bauds:
        status(f"Trying {device} at {baud} baud...")
        session = Elm327Session(
            SerialTransport(device, baud, serial_factory=serial_factory),
            **(session_options or {}),
        )
        try:
            info = session.initialize()
        except TransportError:
            session.close()
            raise
        except ElmError as exc:
            session.close()
            if session.adapter_seen:
                raise
            last_error = exc
            continue
        status(f"Connected to {device} at {baud} baud")
        return Connection(session=session, info=info, baudrate=baud)

    raise TransportError(
        f"No ELM327 response on {device} (tried {', '.join(str(b) for b in bauds)}): {last_error}"
    )
