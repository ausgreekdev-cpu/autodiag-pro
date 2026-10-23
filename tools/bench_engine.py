"""Benchmark: achievable poll rate of the engine loop.

Run from the repository root::

    python tools/bench_engine.py

Each run connects to a 20 ms-latency fake ECU through a pyserial-like port,
polls one PID at the requested interval for two seconds, and reports the
samples per second the UI would actually receive. ``LegacyEngine`` reproduces
the old loop: ``step()`` with its default 50 ms queue wait on every iteration,
which rounded every interval up to at least 50 ms plus command time.
"""

from __future__ import annotations

import statistics
import threading
import time

from bench_serial import SCRIPT, EcuPort

from autodiag.obd.elm327 import Elm327Session
from autodiag.services.engine import ObdEngine
from autodiag.transports.serial_transport import Connection

INTERVALS = (0.0, 0.05, 0.25)
SECONDS = 2.0
STOP_RUNS = 20


class LegacyEngine(ObdEngine):
    """The old loop: a fixed queue poll between iterations."""

    def _idle_wait(self, timeout: float | None) -> float | None:
        return timeout

    def run_forever(self) -> None:
        while not self._stop:
            self.step()


def samples_per_second(engine_cls: type[ObdEngine], interval: float) -> float:
    transport = EcuPort(SCRIPT)

    def connector(device: str) -> Connection:
        session = Elm327Session(transport)
        return Connection(session=session, info=session.initialize(), baudrate=38400)

    values: list[float] = []
    engine = engine_cls(
        connector=connector,
        on_event=lambda kind, args: values.append(args[2]) if kind == "pid_value" else None,
    )
    engine.submit("connect", "X")
    engine.step(0.0)
    engine.submit("set_poll", ({0x0C}, interval))
    engine.step(0.0)

    thread = threading.Thread(target=engine.run_forever, daemon=True)
    thread.start()
    time.sleep(SECONDS)
    engine.stop()
    thread.join(2.0)
    return len(values) / SECONDS


def stop_latency(engine_cls: type[ObdEngine]) -> float:
    """Seconds from ``stop()`` to the loop exiting, while idle."""
    runs = []
    for _ in range(STOP_RUNS):
        engine = engine_cls(on_event=lambda _kind, _args: None)
        thread = threading.Thread(target=engine.run_forever, daemon=True)
        thread.start()
        time.sleep(0.02)
        started = time.perf_counter()
        engine.stop()
        thread.join(2.0)
        runs.append(time.perf_counter() - started)
    return statistics.median(runs)


def main() -> None:
    print(f"fake ECU latency 20 ms; {SECONDS:g}s per interval\n")
    print(f"{'interval':>9} {'legacy/s':>10} {'new/s':>8} {'gain':>6}")
    for interval in INTERVALS:
        old = samples_per_second(LegacyEngine, interval)
        new = samples_per_second(ObdEngine, interval)
        print(f"{interval:>9.2f} {old:>10.1f} {new:>8.1f} {new / old:>5.1f}x")
    print(
        f"\nidle stop→exit: legacy {stop_latency(LegacyEngine) * 1e3:.2f} ms, "
        f"new {stop_latency(ObdEngine) * 1e3:.2f} ms"
    )


if __name__ == "__main__":
    main()
