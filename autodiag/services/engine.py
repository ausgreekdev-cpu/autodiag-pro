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
import traceback
from collections.abc import Callable
from typing import Any

from autodiag.obd import dtc as dtc_dec
from autodiag.obd import framing, freeze_frame, mode05, mode06, readiness, uds, vehicle
from autodiag.obd import pids as pid_dec
from autodiag.obd.elm327 import VALID_PROTOCOLS, ElmAborted, ElmError, SessionInfo
from autodiag.services import sgw
from autodiag.transports.base import TransportError
from autodiag.transports.serial_transport import Connection, connect_elm327

EventSink = Callable[[str, tuple[Any, ...]], None]
Connector = Callable[[str], Connection]

DEFAULT_POLL_INTERVAL = 0.25  # seconds between PID requests (~4 req/s)
_VOLTAGE_EVERY = 40  # poll ticks between ATRV battery-voltage refreshes
_MAX_PID_FAILURES = 3  # consecutive ElmErrors before a PID is dropped
_BATCH_SIZE = 6  # PIDs per request when the bus is CAN (multi-PID command)
_RECONNECT_BACKOFF = (1.0, 2.0, 4.0, 8.0, 15.0)  # seconds before each retry
_MIN_IDLE_WAIT = 0.001  # s: keep an interval-0 poll from spinning the thread
_MAX_IDLE_WAIT = 1.0  # s: cap scheduled sleeps (huge/inf intervals, clock jumps)

_CAN_PROTOCOLS = {"6", "7", "8", "9"}  # ATDPN digits for ISO 15765-4
# ATDPN digits for any CAN-based bus — service $05 is non-CAN only (§6.5).
_MODE05_UNSUPPORTED = frozenset("6789ABCDEF")


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
        self._device: str | None = None
        self._protocol = "0"  # ATSP digit for the next (re)connect; "0" = auto
        self._reconnect_device: str | None = None
        self._reconnect_attempts = 0
        self._reconnect_at = 0.0
        self._supported: set[int] = set()
        self._poll_pids: list[int] = []
        self._poll_interval = DEFAULT_POLL_INTERVAL
        self._polling = False
        self._next_poll_at = 0.0
        self._cursor = 0
        self._ticks = 0
        self._failures: dict[int, int] = {}
        self._batch_size = 1  # raised to _BATCH_SIZE on a confirmed CAN bus

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
        """Serve jobs and polls until :meth:`stop` (owns its worker thread).

        Sleeps until a job arrives or the next poll/reconnect is due, so the
        configured poll interval is honoured instead of being rounded up to
        an arbitrary queue poll period.
        """
        while not self._stop:
            self.step(None)

    def step(self, timeout: float | None = 0.05) -> bool:
        """Run one job (waiting up to ``timeout``) or one due poll.

        ``timeout=None`` waits until a job arrives or scheduled work is due
        (next poll, reconnect attempt) — the worker thread's mode. A finite
        timeout only bounds the wait; the call still wakes early for due work.

        Returns ``False`` once the engine has been stopped.
        """
        if self._stop:
            return False
        job: tuple[str, Any] | None
        try:
            job = self._jobs.get(timeout=self._idle_wait(timeout))
        except queue.Empty:
            job = None
        if job is not None:
            kind, payload = job
            if kind == "stop":
                self._cancel_reconnect()
                self._drop_connection("Stopped")
                return False
            self._execute(kind, payload)
            return True
        try:
            self._maybe_reconnect()
            self._maybe_poll()
        except ElmAborted:
            return not self._stop
        except TransportError as exc:
            # a vanished link must never escape the loop (it would kill the
            # worker thread): drop once, then schedule auto-reconnect
            self._drop_connection(str(exc), error=True)
            self._schedule_reconnect()
        except Exception as exc:
            # Last-resort boundary: nothing a poll or reconnect step raises may
            # end the worker thread, or the UI keeps claiming "Connected"
            # while the dashboard silently freezes.
            self._report_unexpected("Polling", exc)
        return True

    def _idle_wait(self, timeout: float | None) -> float | None:
        """How long the loop may sleep before it has work to do.

        Bounded by ``timeout`` (``None`` = until a job arrives) and by the
        next scheduled poll or reconnect attempt. A due deadline floors the
        wait at ``_MIN_IDLE_WAIT`` so an interval-0 poll cannot spin the CPU
        (except for an explicit zero timeout) and scheduled sleeps are capped
        at ``_MAX_IDLE_WAIT``. ``None`` means there is nothing scheduled, so
        the loop can park until a job arrives.
        """
        wait = timeout
        now = self._clock()
        for due in (self._poll_due_at(), self._reconnect_due_at()):
            if due is None:
                continue
            remaining = max(due - now, 0.0)
            wait = remaining if wait is None else min(wait, remaining)
        if wait is None:
            return None  # nothing scheduled: sleep until a job arrives
        wait = min(wait, _MAX_IDLE_WAIT)
        if wait <= 0.0 and timeout != 0.0:
            return _MIN_IDLE_WAIT
        return wait

    def _poll_due_at(self) -> float | None:
        """Clock time of the next PID poll, or ``None`` when not polling."""
        if self._session is None or not self._polling or not self._poll_pids:
            return None
        return self._next_poll_at

    def _reconnect_due_at(self) -> float | None:
        """Clock time of the next reconnect attempt, or ``None``."""
        if self._reconnect_device is None or self._session is not None:
            return None
        return self._reconnect_at

    # -- job execution -------------------------------------------------------

    def _execute(self, kind: str, payload: Any) -> None:
        handler = getattr(self, f"_job_{kind}", None)
        if handler is None:
            return
        try:
            handler(payload)
        except ElmAborted:
            return  # stop() interrupted the job; shutdown drops the link
        except TransportError as exc:
            self._drop_connection(str(exc), error=True)
            self._schedule_reconnect()
        except ElmError as exc:
            self._emit("error", str(exc))
        except Exception as exc:
            # A decoder tripping over one unusual OEM payload must cost that
            # job, not the whole polling thread. Keep the link and say so.
            self._report_unexpected(f"Job {kind!r}", exc)

    def _job_connect(self, device: str) -> None:
        self._cancel_reconnect()
        if self._session is not None:
            self._drop_connection("Reconnecting")
        try:
            self._establish(device)
        except (TransportError, ElmError) as exc:
            self._emit("error", str(exc))
            self._emit("disconnected", str(exc))

    def _establish(self, device: str) -> None:
        """Open the adapter session for ``device`` (raises on failure)."""
        connector = self._connector or self._default_connector
        conn = connector(device)
        self._device = device
        self._session = conn.session
        hook = getattr(self._session, "set_abort_hook", None)
        if hook is not None:  # alternate sessions may not support cancellation
            hook(self._is_stopping)
        self._info = conn.info
        pn = (conn.info.protocol_number or "").upper().lstrip("A")
        self._can = pn in _CAN_PROTOCOLS if pn else None
        self._batch_size = _BATCH_SIZE if self._can is True else 1
        self._failures.clear()
        self._cursor = 0
        self._ticks = 0
        self._emit("connected", conn.info)
        if conn.info.voltage is not None:
            self._emit("voltage", float(conn.info.voltage))
        if conn.info.stn:
            self._emit("status", "STN adapter detected — optimized polling profile")
        self._discover_supported()
        if not self._poll_pids:
            self._poll_pids = sorted(
                {pid_dec.request_pid(p) for p in self._supported}
            )
        self._polling = bool(self._poll_pids)
        if self._polling:
            self._emit("status", self._poll_status())

    def _job_disconnect(self, _payload: Any) -> None:
        self._cancel_reconnect()
        self._drop_connection("Disconnected")

    def _job_set_protocol(self, code: Any) -> None:
        """Pin the OBD protocol for the next (re)connect (``ATSP`` digit)."""
        text = str(code).strip().upper()
        self._protocol = text if text in VALID_PROTOCOLS else "0"

    def _job_set_poll(self, payload: Any) -> None:
        pids, interval = payload if payload is not None else (None, None)
        if interval is not None:
            self._poll_interval = max(float(interval), 0.0)
        if pids is not None:
            self._poll_pids = sorted(
                {
                    pid_dec.request_pid(p)
                    for p in pids
                    if p in pid_dec.PID_REGISTRY
                }
            )
            self._failures.clear()
            self._cursor = 0
        elif not self._poll_pids:
            self._poll_pids = sorted(
                {pid_dec.request_pid(p) for p in self._supported}
            )
        self._polling = bool(self._poll_pids) and self._session is not None
        if self._polling:
            self._emit("status", self._poll_status())

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

    def _job_read_freeze_all(self, payload: Any) -> None:
        frame = int(payload) if payload is not None else 0
        text = self._req("0200")
        supported, _nxt = framing.parse_supported_mask(text, "4200", 0x00)
        pids = sorted(p for p in supported if p in pid_dec.PID_REGISTRY)
        self._emit("freeze_supported", set(pids))
        values: dict[int, float] = {}
        for index, pid in enumerate(pids, start=1):
            self._emit(
                "status",
                f"Freeze frame {frame}: {index}/{len(pids)} — PID {pid:02X}",
            )
            try:
                frame_text = self._req(f"02{pid:02X}{frame:02X}")
            except ElmError:
                continue
            parsed = freeze_frame.parse_freeze_frame(frame_text, pid, frame)
            if parsed is not None:
                values[pid] = parsed.value
        self._emit("freeze_all", frame, values)

    def _job_read_vehicle(self, _payload: Any) -> None:
        out: dict[str, Any] = {
            "vin": None,
            "cal_ids": [],
            "cvns": [],
            "obd_standard": None,
            "fuel_type": None,
        }
        for key, cmd, parser in (
            ("vin", "0902", vehicle.parse_vin),
            ("cal_ids", "0904", vehicle.parse_cal_ids),
            ("cvns", "0906", vehicle.parse_cvns),
        ):
            try:
                out[key] = parser(self._req(cmd))
            except ElmError:
                continue  # some ECUs omit optional info types
        for key, pid, name in (
            ("obd_standard", 0x1C, pid_dec.obd_standard_name),
            ("fuel_type", 0x51, pid_dec.fuel_type_name),
        ):
            try:
                value = pid_dec.parse_pid_value(self._req(f"01{pid:02X}"), pid)
            except ElmError:
                continue  # informational PIDs: not reported by every vehicle
            if value is not None:
                out[key] = name(value)
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

    def _job_read_mode05(self, _payload: Any) -> None:
        results: list[mode05.TestResult] = []
        if self._bus_is_can():
            self._emit("status", "Service $05 is non-CAN only — see Mode $06")
            self._emit("mode05", results)
            return
        sensors, via_pid_1d = self._discover_o2_sensors()
        for sensor in sensors:
            for tid in self._mode05_tids(sensor):
                try:
                    text = self._req(f"05{tid:02X}{sensor:02X}")
                except ElmError:
                    continue  # test not reported for this sensor/ECU
                results.extend(
                    mode05.parse_tid_values(text, tid, sensor, via_pid_1d=via_pid_1d)
                )
        if not results:
            self._emit("status", "No oxygen-sensor test results reported")
        self._emit("mode05", results)

    def _bus_is_can(self) -> bool:
        """Whether ATDPN reports a CAN bus (service $05 is non-CAN only).

        Unknown/absent protocol numbers return ``False``: probe and let
        ``NO DATA`` decide, so adapters that omit ATDPN still work.
        """
        info_number = self._info.protocol_number if self._info else None
        code = (info_number or "").strip().upper().lstrip("A")[:1]
        return bool(code) and code in _MODE05_UNSUPPORTED

    def _read_location_byte(self, pid: int) -> int | None:
        """Byte A of PID $13 / $1D (O2 sensor location bitmask), or None."""
        try:
            text = self._req(f"01{pid:02X}")
        except ElmError:
            return None
        payload = framing.extract_payload(text, f"41{pid:02X}")
        if not payload or len(payload) < 2:
            return None
        try:
            return framing.hex_to_bytes(payload[:2])[0]
        except ValueError:
            return None

    def _discover_o2_sensors(self) -> tuple[list[int], bool]:
        """O2SNO masks + which layout applies (J1979: PID $13 xor $1D)."""
        for pid in (0x13, 0x1D):
            location = self._read_location_byte(pid)
            if location:
                via_pid_1d = pid == 0x1D
                return (
                    mode05.sensor_masks(location, via_pid_1d=via_pid_1d),
                    via_pid_1d,
                )
        # Neither PID answered: probe the four primary masks (PID $13 labels).
        return mode05.sensor_masks(0x0F), False

    def _mode05_tids(self, sensor: int) -> list[int]:
        """Supported Test IDs for ``sensor`` via the §5.5.1 bitmap walk."""
        tids: set[int] = set()
        base = 0x00
        while base <= 0xE0:
            try:
                text = self._req(f"05{base:02X}{sensor:02X}")
            except ElmError:
                # Feature unused by this ECU (§5.5.1): probe the
                # standardized Appendix C set instead.
                return list(mode05.STANDARD_TIDS)
            sup, nxt = mode05.parse_supported_tids(text, base, sensor)
            tids |= sup
            if not nxt:
                break
            base += 0x20
        return sorted(tids)

    def _job_read_voltage(self, _payload: Any) -> None:
        self._emit("voltage", self._read_voltage())

    def _job_request_pid(self, payload: Any) -> None:
        pid = pid_dec.request_pid(int(payload))
        text = self._req(f"01{pid:02X}")
        self._emit("pid_response", pid, text)
        for channel, value in pid_dec.parse_pid_values(text, pid).items():
            self._emit("pid_value", channel, value, self._clock())

    def _job_uds(self, payload: tuple[str, str, str, float | None]) -> None:
        """One UDS exchange with physical addressing; headers restored after.

        Negative responses are emitted on the ``uds`` channel as
        :class:`UdsError` so the panel can render the NRC; adapter-level
        failures keep flowing through the existing ``error`` path.
        """
        tx, rx, hex_request, timeout = payload
        self._emit("status", f"UDS {hex_request} → {tx}")
        try:
            self._req(f"AT SH {tx}")
            self._req(f"AT CRA {rx}")
            try:
                text = self._req(hex_request, timeout)
                result: object = uds.parse_response(text)
            except uds.UdsError as exc:
                result = exc
            self._emit("uds", (hex_request, result))
        finally:
            # Functional default restored so later OBD polls (0100, ...) are
            # not accidentally sent physically to this one ECU.
            for cmd in ("AT SH", "AT CRA"):
                try:
                    self._req(cmd)
                except ElmError:
                    pass  # best-effort restore; a dead link surfaces elsewhere

    def _job_mode08(self, payload: tuple[int, str]) -> None:
        """One Mode $08 onboard-control request (bi-directional actuator test)."""
        test_id, label = payload
        request = f"08{test_id:02X}"
        self._emit("status", f"Mode $08 {label} → {request}")
        try:
            text = self._req(request)
        except ElmError as exc:
            self._emit("error", str(exc))
            return
        flat = text.upper().replace(" ", "")
        if flat.startswith(f"48{test_id:02X}"):
            outcome = "accepted"
        elif flat.startswith("7F08") and len(flat) >= 6:
            outcome = f"rejected (NRC 0x{flat[4:6]})"
        else:
            outcome = text or "no response"
        self._emit("mode08", (request, outcome))

    # -- security gateway (SGW) ---------------------------------------------------

    def _sgw_exchange(self, request: str, header: str) -> str | None:
        """One exchange against the gateway module; headers restored after."""
        try:
            self._req(f"AT SH {header}")
            self._req(f"AT CRA {uds.response_header(header)}")
            try:
                return self._req(request)
            finally:
                for cmd in ("AT SH", "AT CRA"):
                    try:
                        self._req(cmd)
                    except ElmError:
                        pass  # best-effort restore; a dead link surfaces elsewhere
        except ElmError:
            return None

    def _job_sgw_probe(self, payload: str) -> None:
        header = payload
        self._emit("status", f"Probing SGW on {header}…")
        info = sgw.probe_gateway(self._sgw_exchange, header)
        self._emit("sgw_probe", (header, info))

    def _job_sgw_seed(self, payload: str) -> None:
        header = payload
        self._emit("status", f"Requesting SGW seed on {header}…")
        challenge = sgw.request_seed(self._sgw_exchange, header)
        self._emit("sgw_seed", (header, challenge))

    def _job_sgw_key(self, payload: tuple[str, str]) -> None:
        header, key_hex = payload
        try:
            key = bytes.fromhex(key_hex)
        except ValueError:
            self._emit("sgw_key", (header, False, "key must be hex bytes"))
            return
        ok = sgw.send_key(self._sgw_exchange, header, key)
        self._emit("sgw_key", (header, ok, "accepted" if ok else "rejected"))

    # -- polling -------------------------------------------------------------

    def _poll_status(self) -> str:
        suffix = " (batched)" if self._batch_size > 1 else ""
        return (
            f"Polling {len(self._poll_pids)} PIDs every "
            f"{self._poll_interval:g}s{suffix}"
        )

    def _next_batch(self) -> list[int]:
        """Round-robin slice of ``_poll_pids`` (size 1 = legacy single mode)."""
        start = self._cursor % len(self._poll_pids)
        batch = self._poll_pids[start : start + self._batch_size]
        self._cursor += len(batch)
        return batch

    def _note_pid_failure(self, pid: int, reason: str | None = None) -> None:
        """Count one missed sample for ``pid``; drop it after the budget."""
        failures = self._failures.get(pid, 0) + 1
        self._failures[pid] = failures
        if failures >= _MAX_PID_FAILURES:
            self._drop_pid(pid)
        elif reason is not None:
            self._emit("error", reason)

    def _emit_values(self, text: str, pid: int) -> None:
        """Decode one response; a decoder bug counts as a missed sample."""
        try:
            values = pid_dec.parse_pid_values(text, pid)
        except Exception as exc:  # payload shape the decoder did not expect
            self._note_pid_failure(pid, f"PID {pid:02X} decode error: {exc}")
            return
        self._failures[pid] = 0  # a good sample clears the strike count
        for channel, value in values.items():
            self._emit("pid_value", channel, value, self._clock())

    def _drop_pid(self, pid: int) -> None:
        self._poll_pids = [p for p in self._poll_pids if p != pid]
        self._emit("status", f"Dropping PID {pid:02X} — no response")
        if not self._poll_pids:
            self._polling = False

    def _maybe_poll(self) -> None:
        if self._session is None or not self._polling or not self._poll_pids:
            return
        now = self._clock()
        if now < self._next_poll_at:
            return
        batch = self._next_batch()
        self._next_poll_at = now + self._poll_interval
        try:
            text = self._req("".join(f"01{pid:02X}" for pid in batch))
        except (ElmAborted, TransportError):
            # cancelled, or the link itself vanished: the caller must handle
            # these (abort the job / drop + reconnect), never count them
            # against a single PID's failure budget.
            raise
        except Exception as exc:
            # ElmError (bus said no) or an unexpected transport/session bug:
            # both are one missed sample, never a dead engine.
            if len(batch) > 1:
                # Either a transient bus error or this vehicle dislikes
                # combined requests: isolate PIDs by reverting to singles.
                self._batch_size = 1
                self._emit(
                    "status",
                    "Batched polling unavailable — "
                    "falling back to single-PID requests",
                )
                return
            self._note_pid_failure(batch[0], str(exc))
            return
        self._ticks += 1
        if len(batch) == 1:
            self._emit_values(text, batch[0])
        else:
            lengths = {
                pid: pid_dec.PID_REGISTRY[pid].data_bytes
                for pid in batch
                if pid in pid_dec.PID_REGISTRY
            }
            chunks = framing.split_pid_chunks(text, batch, lengths)
            for pid in batch:
                if pid in chunks:
                    self._emit_values(chunks[pid], pid)
                else:
                    self._note_pid_failure(pid)
        if self._ticks % _VOLTAGE_EVERY == 0:
            try:
                self._emit("voltage", self._read_voltage())
            except ElmError:
                pass

    # -- reconnect -----------------------------------------------------------

    def _schedule_reconnect(self) -> None:
        if self._reconnect_device is not None or self._device is None:
            return  # already pending, or never connected (manual retry only)
        self._reconnect_device = self._device
        self._reconnect_attempts = 0
        delay = _RECONNECT_BACKOFF[0]
        self._reconnect_at = self._clock() + delay
        self._emit("status", f"Connection lost — reconnecting in {delay:g}s")
        self._emit("reconnecting", 1, len(_RECONNECT_BACKOFF))

    def _cancel_reconnect(self) -> None:
        self._reconnect_device = None
        self._reconnect_attempts = 0
        self._reconnect_at = 0.0

    @property
    def reconnect_pending(self) -> bool:
        return self._reconnect_device is not None

    def _maybe_reconnect(self) -> None:
        if self._reconnect_device is None or self._session is not None:
            return
        if self._clock() < self._reconnect_at:
            return
        device = self._reconnect_device
        attempt = self._reconnect_attempts
        try:
            self._establish(device)
        except (TransportError, ElmError) as exc:
            if self._session is not None:  # opened, then died during discovery
                self._drop_connection(str(exc), error=True)
            self._reconnect_attempts = attempt + 1
            if self._reconnect_attempts >= len(_RECONNECT_BACKOFF):
                self._emit("error", f"Reconnect failed: {exc} — giving up")
                self._emit("reconnecting", 0, 0)
                self._cancel_reconnect()
                return
            delay = _RECONNECT_BACKOFF[self._reconnect_attempts]
            self._reconnect_at = self._clock() + delay
            self._emit(
                "status",
                f"Reconnect failed ({self._reconnect_attempts}/"
                f"{len(_RECONNECT_BACKOFF)}) — retrying in {delay:g}s",
            )
            self._emit(
                "reconnecting",
                self._reconnect_attempts + 1,
                len(_RECONNECT_BACKOFF),
            )
            return
        self._emit(
            "status",
            "Reconnected" if attempt == 0 else f"Reconnected (attempt {attempt + 1})",
        )
        self._cancel_reconnect()

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
        self._supported |= {
            companion
            for companion in pid_dec.COMPANION_PIDS
            if pid_dec.request_pid(companion) in self._supported
        }
        self._emit("pids_supported", set(self._supported))

    def _read_voltage(self) -> float:
        match = re.search(r"(\d+(?:\.\d+)?)\s*V", self._req("ATRV"), re.IGNORECASE)
        if match is None:
            raise ElmError("no-data", "Voltage response was malformed")
        return float(match.group(1))

    def _req(self, cmd: str, timeout: float | None = None) -> str:
        # Multi-command jobs (Mode $06, freeze-frame, $05 walks, discovery)
        # issue dozens of requests; stopping between them keeps shutdown
        # prompt even when every one of them would time out on a dead bus.
        if self._stop:
            raise ElmAborted()
        if self._session is None:
            raise ElmError("no-adapter", "Not connected")
        return self._session.command(cmd, timeout)

    def _is_stopping(self) -> bool:
        return self._stop

    def _report_unexpected(self, where: str, exc: Exception) -> None:
        """Surface an internal failure without ending the engine loop."""
        detail = traceback.format_exception_only(type(exc), exc)[-1].strip()
        frames = traceback.extract_tb(exc.__traceback__)
        origin = f" at {frames[-1].name}:{frames[-1].lineno}" if frames else ""
        try:
            self._emit("error", f"{where} hit an internal error{origin}: {detail}")
        except Exception:
            pass  # the sink itself failed; no way left to report it

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
        return connect_elm327(
            device,
            protocol=self._protocol,
            on_status=lambda msg: self._emit("status", msg),
            should_abort=self._is_stopping,
        )

    def _emit(self, kind: str, *args: Any) -> None:
        if self._on_event is not None:
            self._on_event(kind, args)
