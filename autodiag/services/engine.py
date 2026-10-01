"""Background OBD engine: queued jobs + PID polling loop.

Pure Python (no Qt) so it can be unit-tested deterministically: callers
:meth:`submit` jobs from any thread, then drive :meth:`step` (tests) or
:meth:`run_forever` (the Qt worker thread). Results flow out through a
single ``on_event(kind, args)`` callback.
"""

from __future__ import annotations

import queue
import re
import time
from collections.abc import Callable
from typing import Any

from autodiag.obd import dtc as dtc_dec
from autodiag.obd import framing, freeze_frame, mode06, readiness, vehicle
from autodiag.obd import pids as pid_dec
from autodiag.obd.elm327 import ElmError, SessionInfo
from autodiag.transports.base import TransportError
from autodiag.transports.serial_transport import Connection, connect_elm327

EventSink = Callable[[str, tuple[Any, ...]], None]
Connector = Callable[[str], Connection]

DEFAULT_POLL_INTERVAL = 0.25  # seconds between PID requests (~4 req/s)
_VOLTAGE_EVERY = 40  # poll ticks between ATRV battery-voltage refreshes
_MAX_PID_FAILURES = 3  # consecutive ElmErrors before a PID is dropped

_CAN_PROTOCOLS = {"6", "7", "8", "9"}  # ATDPN digits for ISO 15765-4


class ObdEngine:
    """Executes OBD jobs serially and round-robins live-PID polling."""

    def __init__(
        self,
        connector: Connector | None = None,
        on_event: EventSink | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._connector = connector
        self._on_event = on_event
        self._clock = clock
        self._jobs: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._stop = False

        self._session = None
        self._info: SessionInfo | None = None
        self._can: bool | None = None
        self._supported: set[int] = set()
        self._poll_pids: list[int] = []
        self._poll_interval = DEFAULT_POLL_INTERVAL
        self._polling = False
        self._next_poll_at = 0.0
        self._cursor = 0
        self._ticks = 0
        self._failures: dict[int, int] = {}

    # -- public API ----------------------------------------------------------

    def submit(self, kind: str, payload: Any = None) -> None:
        """Queue a job (thread-safe). See the ``_HANDLERS`` map for kinds."""
        self._jobs.put((kind, payload))

    def stop(self) -> None:
        self._stop = True
        self._jobs.put(("stop", None))

    @property
    def connected(self) -> bool:
        return self._session is not None

    @property
    def supported_pids(self) -> set[int]:
        return set(self._supported)

    @property
    def session_info(self) -> SessionInfo | None:
        return self._info

    # -- loop ----------------------------------------------------------------

    def run_forever(self) -> None:
        while not self._stop:
            self.step()

    def step(self, timeout: float = 0.05) -> bool:
        """Run one job (waiting up to ``timeout``) or one due poll.

        Returns ``False`` once the engine has been stopped.
        """
        if self._stop:
            return False
        job: tuple[str, Any] | None
        try:
            job = self._jobs.get(timeout=timeout)
        except queue.Empty:
            job = None
        if job is not None:
            kind, payload = job
            if kind == "stop":
                self._drop_connection("Stopped")
                return False
            self._execute(kind, payload)
            return True
        self._maybe_poll()
        return True

    # -- job execution -------------------------------------------------------

    def _execute(self, kind: str, payload: Any) -> None:
        handler = getattr(self, f"_job_{kind}", None)
        if handler is None:
            return
        try:
            handler(payload)
        except TransportError as exc:
            self._drop_connection(str(exc), error=True)
        except ElmError as exc:
            self._emit("error", str(exc))

    def _job_connect(self, device: str) -> None:
        if self._session is not None:
            self._drop_connection("Reconnecting")
        connector = self._connector or self._default_connector
        try:
            conn = connector(device)
        except (TransportError, ElmError) as exc:
            self._emit("error", str(exc))
            self._emit("disconnected", str(exc))
            return
        self._session = conn.session
        self._info = conn.info
        pn = (conn.info.protocol_number or "").upper().lstrip("A")
        self._can = pn in _CAN_PROTOCOLS if pn else None
        self._failures.clear()
        self._cursor = 0
        self._ticks = 0
        self._emit("connected", conn.info)
        if conn.info.voltage is not None:
            self._emit("voltage", float(conn.info.voltage))
        self._discover_supported()
        if not self._poll_pids:
            self._poll_pids = sorted(self._supported)
            self._polling = bool(self._poll_pids)
            if self._polling:
                self._emit(
                    "status",
                    f"Polling {len(self._poll_pids)} PIDs every "
                    f"{self._poll_interval:g}s",
                )

    def _job_disconnect(self, _payload: Any) -> None:
        self._drop_connection("Disconnected")

    def _job_set_poll(self, payload: Any) -> None:
        pids, interval = payload if payload is not None else (None, None)
        if interval is not None:
            self._poll_interval = max(float(interval), 0.0)
        if pids is not None:
            self._poll_pids = sorted(p for p in pids if p in pid_dec.PID_REGISTRY)
            self._failures.clear()
            self._cursor = 0
        elif not self._poll_pids:
            self._poll_pids = sorted(self._supported)
        self._polling = bool(self._poll_pids) and self._session is not None
        if self._polling:
            self._emit(
                "status",
                f"Polling {len(self._poll_pids)} PIDs every {self._poll_interval:g}s",
            )

    def _job_read_dtcs(self, source: Any) -> None:
        text = self._req({"stored": "03", "pending": "07", "permanent": "0A"}[source])
        codes = dtc_dec.parse_dtcs(text, can=self._can)
        self._emit("dtcs", source, codes)

    def _job_clear_dtcs(self, _payload: Any) -> None:
        ok = dtc_dec.parse_clear_success(self._req("04"))
        self._emit("cleared", ok)
        if ok:
            self._emit("status", "Codes cleared — MIL is off")

    def _job_read_monitors(self, _payload: Any) -> None:
        status = readiness.parse_monitor_status(self._req("0101"))
        if status is None:
            raise ElmError("no-data", "Monitor status response was malformed")
        self._emit("monitors", status)

    def _job_read_freeze(self, payload: Any) -> None:
        pid, frame = payload if payload is not None else (0x0C, 0)
        text = self._req(f"02{pid:02X}{frame:02X}")
        result = freeze_frame.parse_freeze_frame(text, pid, frame)
        if result is None:
            raise ElmError("no-data", f"No freeze-frame data for PID {pid:02X}")
        self._emit("freeze", result)

    def _job_read_freeze_support(self, _payload: Any) -> None:
        text = self._req("0200")
        supported, _nxt = framing.parse_supported_mask(text, "4200", 0x00)
        self._emit("freeze_supported", supported)

    def _job_read_vehicle(self, _payload: Any) -> None:
        out: dict[str, Any] = {"vin": None, "cal_ids": [], "cvns": []}
        for key, cmd, parser in (
            ("vin", "0902", vehicle.parse_vin),
            ("cal_ids", "0904", vehicle.parse_cal_ids),
            ("cvns", "0906", vehicle.parse_cvns),
        ):
            try:
                out[key] = parser(self._req(cmd))
            except ElmError:
                continue  # some ECUs omit optional info types
        self._emit("vehicle", out)

    def _job_read_mode06(self, _payload: Any) -> None:
        mids: set[int] = set()
        base = 0x00
        while base <= 0xE0:
            try:
                sup, nxt = mode06.parse_supported_mids(self._req(f"06{base:02X}"), base)
            except ElmError:
                break
            mids |= sup
            if not nxt:
                break
            base += 0x20
        self._emit("mids_supported", mids)

        results: list[Any] = []
        for mid in sorted(mids):
            if mid % 0x20 == 0:
                continue  # bitmap pseudo-MIDs, not test results
            try:
                results.extend(mode06.parse_test_results(self._req(f"06{mid:02X}")))
            except ElmError:
                continue
        self._emit("mode06", results)

    def _job_read_voltage(self, _payload: Any) -> None:
        self._emit("voltage", self._read_voltage())

    # -- polling -------------------------------------------------------------

    def _maybe_poll(self) -> None:
        if self._session is None or not self._polling or not self._poll_pids:
            return
        now = self._clock()
        if now < self._next_poll_at:
            return
        pid = self._poll_pids[self._cursor % len(self._poll_pids)]
        self._cursor += 1
        self._next_poll_at = now + self._poll_interval
        try:
            text = self._req(f"01{pid:02X}")
        except ElmError as exc:
            self._failures[pid] = self._failures.get(pid, 0) + 1
            if self._failures[pid] >= _MAX_PID_FAILURES:
                self._poll_pids = [p for p in self._poll_pids if p != pid]
                self._emit("status", f"Dropping PID {pid:02X} — no response")
                if not self._poll_pids:
                    self._polling = False
            else:
                self._emit("error", str(exc))
            return
        self._failures[pid] = 0
        value = pid_dec.parse_pid_value(text, pid)
        if value is not None:
            self._emit("pid_value", pid, value, self._clock())
        self._ticks += 1
        if self._ticks % _VOLTAGE_EVERY == 0:
            try:
                self._emit("voltage", self._read_voltage())
            except ElmError:
                pass

    # -- helpers -------------------------------------------------------------

    def _discover_supported(self) -> None:
        supported: set[int] = set()
        base = 0x00
        while base <= 0xC0:
            try:
                text = self._req(f"01{base:02X}")
            except ElmError:
                break
            sup, nxt = pid_dec.parse_supported_pids(text, base)
            supported |= sup
            if not nxt:
                break
            base += 0x20
        self._supported = {p for p in supported if p in pid_dec.PID_REGISTRY}
        self._emit("pids_supported", set(self._supported))

    def _read_voltage(self) -> float:
        match = re.search(r"(\d+(?:\.\d+)?)\s*V", self._req("ATRV"), re.IGNORECASE)
        if match is None:
            raise ElmError("no-data", "Voltage response was malformed")
        return float(match.group(1))

    def _req(self, cmd: str, timeout: float | None = None) -> str:
        if self._session is None:
            raise ElmError("no-adapter", "Not connected")
        return self._session.command(cmd, timeout)

    def _drop_connection(self, reason: str, *, error: bool = False) -> None:
        session, self._session = self._session, None
        if session is not None:
            try:
                session.close()
            except Exception:
                pass  # closing a dead link must never raise
        self._info = None
        self._polling = False
        self._poll_pids = []
        self._failures.clear()
        if error:
            self._emit("error", reason)
        self._emit("disconnected", reason)

    def _default_connector(self, device: str) -> Connection:
        return connect_elm327(device, on_status=lambda msg: self._emit("status", msg))

    def _emit(self, kind: str, *args: Any) -> None:
        if self._on_event is not None:
            self._on_event(kind, args)
