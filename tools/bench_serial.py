"""Benchmark: cost of the pre-command drain through ``Elm327Session``.

Run from the repository root::

    python tools/bench_serial.py

The transport models pyserial on a quiet port: a read with an empty buffer
blocks for the whole timeout. ``reported`` answers ``pending()`` from its
buffer (the new path, one ``in_waiting`` check); ``timed`` returns ``None``,
which is exactly what the session did before — a 30 ms read before every
command. The ECU model adds a 20 ms response delay so the sustainable
request rate is realistic rather than bus-bound on the fake.
"""

from __future__ import annotations

import statistics
import time

from autodiag.obd.elm327 import Elm327Session
from tests.fakes import FakeTransport, elm_script

SCRIPT = elm_script(
    **{
        "AT SH 7E0": b"OK\r\r>",
        "AT CRA 7E8": b"OK\r\r>",
        "AT SH": b"OK\r\r>",
        "AT CRA": b"OK\r\r>",
    }
)
EXCHANGE = ("AT SH 7E0", "AT CRA 7E8", "010C", "AT SH", "AT CRA")
ECU_LATENCY = 0.02
COMMANDS = 100
EXCHANGES = 20


class BlockingPort(FakeTransport):
    """pyserial semantics: an empty read costs the requested timeout."""

    def read(self, max_bytes: int = 1024, timeout: float = 0.1) -> bytes:
        if not self._buf:
            time.sleep(max(timeout, 0.0))
            return b""
        return super().read(max_bytes, timeout)


class EcuPort(BlockingPort):
    """Adapter plus a 20 ms ECU turnaround before the answer is readable."""

    def __init__(self, responses: dict[str, bytes]) -> None:
        super().__init__(responses)
        self._ready_at = 0.0

    def write(self, payload: bytes) -> None:
        super().write(payload)
        self._ready_at = time.perf_counter() + ECU_LATENCY

    def read(self, max_bytes: int = 1024, timeout: float = 0.1) -> bytes:
        wait = self._ready_at - time.perf_counter()
        if wait > 0:
            time.sleep(min(wait, timeout))
            if time.perf_counter() < self._ready_at:
                return b""
        return super().read(max_bytes, timeout)


class TimedDrain(EcuPort):
    """The old behaviour: the transport cannot report its buffer."""

    def pending(self) -> int | None:
        return None


def measure(transport_cls: type[EcuPort]) -> tuple[float, float, float]:
    transport = transport_cls(SCRIPT)
    session = Elm327Session(transport, command_timeout=5.0)
    session.initialize()
    session.command("010C")  # warm

    single: list[float] = []
    for _ in range(COMMANDS):
        started = time.perf_counter()
        session.command("010C")
        single.append(time.perf_counter() - started)

    exchanges: list[float] = []
    for _ in range(EXCHANGES):
        started = time.perf_counter()
        for cmd in EXCHANGE:
            session.command(cmd)
        exchanges.append(time.perf_counter() - started)

    per_command = statistics.median(single)
    per_exchange = statistics.median(exchanges)
    return per_command, per_exchange, 1.0 / per_command


def main() -> None:
    print(f"{'drain':>18} {'per command':>12} {'5-cmd exchange':>15} {'requests/s':>11}")
    for label, cls in (("reported buffer", EcuPort), ("timed read (old)", TimedDrain)):
        per_command, per_exchange, rate = measure(cls)
        print(
            f"{label:>18} {per_command * 1e3:>9.3f} ms "
            f"{per_exchange * 1e3:>12.2f} ms {rate:>11.1f}"
        )
    print(
        f"\nECU turnaround {ECU_LATENCY * 1e3:g} ms; poll budget 250 ms "
        "(6-PID batch at 4 Hz = 1 request/s)"
    )


if __name__ == "__main__":
    main()
