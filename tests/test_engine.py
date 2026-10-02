"""ObdEngine tests: jobs, discovery, polling, error paths (no Qt, no threads)."""

from __future__ import annotations

import pytest

from autodiag.services.engine import ObdEngine
from autodiag.transports.base import TransportError
from tests.fakes import scripted_connector


def _pump(engine: ObdEngine, pred, *, limit: int = 2000) -> bool:
    for _ in range(limit):
        if pred():
            return True
        engine.step(0.0)
    return pred()


class Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, tuple]] = []

    def __call__(self, kind: str, args: tuple) -> None:
        self.events.append((kind, args))

    def of(self, kind: str) -> list[tuple]:
        return [args for k, args in self.events if k == kind]

    def last(self, kind: str) -> tuple:
        matches = self.of(kind)
        assert matches, f"no {kind!r} event in {self.events}"
        return matches[-1]


def test_connect_discover_and_emit_info():
    connector, holder = scripted_connector()
    sink = Recorder()
    engine = ObdEngine(connector=connector, on_event=sink)

    engine.submit("connect", "/dev/OBD")
    assert engine.step(0.0)

    assert sink.of("connected"), "connect must emit connected"
    info = sink.last("connected")[0]
    assert info.adapter == "ELM327 v1.5"
    assert info.voltage == pytest.approx(12.6)
    assert holder["device"] == "/dev/OBD"
    assert engine.connected

    # voltage emitted from the ATZ/ATRV banner
    assert sink.of("voltage") == [(12.6,)]

    # supported PIDs discovered from the 0100 bitmap (registry only)
    supported = sink.last("pids_supported")[0]
    assert {0x04, 0x05, 0x0C, 0x0D, 0x11} <= supported
    assert 0x02 not in supported  # bit clear in spec fixture BE3EA813
    assert 0x20 not in supported  # bitmap pseudo-PID filtered out
    assert engine.supported_pids == supported


def test_connect_failure_emits_error_and_disconnected():
    def broken(device: str):
        raise TransportError("port vanished")

    sink = Recorder()
    engine = ObdEngine(connector=broken, on_event=sink)

    engine.submit("connect", "X")
    engine.step(0.0)

    assert sink.of("error")
    assert sink.of("disconnected")
    assert not engine.connected


def test_poll_emits_pid_values():
    connector, _holder = scripted_connector()
    sink = Recorder()
    engine = ObdEngine(connector=connector, on_event=sink)
    engine.submit("connect", "X")
    engine.step(0.0)

    engine.submit("set_poll", ({0x0C, 0x0D}, 0.0))
    engine.step(0.0)
    _pump(engine, lambda: len(sink.of("pid_value")) >= 2)

    values = dict((pid, value) for pid, value, _t in sink.of("pid_value"))
    assert values[0x0C] == pytest.approx(1726.0)
    assert values[0x0D] == 60.0


def test_poll_drops_pid_after_repeated_failures():
    connector, _holder = scripted_connector()
    sink = Recorder()
    engine = ObdEngine(connector=connector, on_event=sink)
    engine.submit("connect", "X")
    engine.step(0.0)

    # PID 0x04 has no scripted response ("?") → three strikes then dropped
    engine.submit("set_poll", ({0x04, 0x0C}, 0.0))
    assert _pump(engine, lambda: any("Dropping PID 04" in m for m, in sink.of("status")))

    sink.events.clear()
    _pump(engine, lambda: len(sink.of("pid_value")) >= 2)
    polled = {pid for pid, _v, _t in sink.of("pid_value")}
    assert polled == {0x0C}


def test_supported_pids_include_stft_companions():
    connector, _holder = scripted_connector()
    sink = Recorder()
    engine = ObdEngine(connector=connector, on_event=sink)
    engine.submit("connect", "X")
    engine.step(0.0)

    supported = sink.last("pids_supported")[0]
    assert 0x15 in supported  # fixture bitmap BE3EA813 supports it
    assert 0x115 in supported  # …and therefore its STFT companion
    assert 0x14 not in supported
    assert 0x114 not in supported  # companion tracks its base PID


def test_poll_emits_o2_stft_companion():
    connector, _holder = scripted_connector({"0115": b"41 15 7A 90\r\r>"})
    sink = Recorder()
    engine = ObdEngine(connector=connector, on_event=sink)
    engine.submit("connect", "X")
    engine.step(0.0)

    engine.submit("set_poll", ({0x15}, 0.0))
    engine.step(0.0)
    assert _pump(engine, lambda: any(pid == 0x115 for pid, *_ in sink.of("pid_value")))

    values = dict((pid, value) for pid, value, _t in sink.of("pid_value"))
    assert values[0x15] == pytest.approx(0.61)  # 0x7A / 200
    assert values[0x115] == pytest.approx(12.5)  # (0x90 - 128) * 100/128


def test_set_poll_normalizes_companions_to_base_requests():
    connector, holder = scripted_connector({"0115": b"41 15 7A 90\r\r>"})
    sink = Recorder()
    engine = ObdEngine(connector=connector, on_event=sink)
    engine.submit("connect", "X")
    engine.step(0.0)

    engine.submit("set_poll", ({0x15, 0x115, 0x0C}, 0.0))
    engine.step(0.0)
    assert engine._poll_pids == [0x0C, 0x15]

    _pump(engine, lambda: len(sink.of("pid_value")) >= 4, limit=50)
    writes = holder["transport"].writes
    assert "0115" in writes
    assert not any(cmd.startswith("01115") for cmd in writes)  # synthetic id


def test_transport_error_during_poll_schedules_reconnect():
    connector, holder = scripted_connector()
    clock = {"t": 0.0}
    sink = Recorder()
    engine = ObdEngine(connector=connector, on_event=sink, clock=lambda: clock["t"])
    engine.submit("connect", "/dev/OBD")
    engine.step(0.0)
    engine.submit("set_poll", ({0x0C}, 0.0))
    engine.step(0.0)
    assert _pump(engine, lambda: sink.of("pid_value"))

    holder["transport"].close()  # cable yanked mid-session
    clock["t"] = 1.0
    assert engine.step(0.0) is not False  # must never kill the loop
    assert sink.of("disconnected")
    assert sink.of("error")
    assert engine.reconnect_pending
    assert not engine.connected
    assert any("reconnecting in 1s" in m for m, in sink.of("status"))

    clock["t"] = 2.0  # first backoff elapsed
    assert engine.step(0.0)
    assert engine.connected
    assert not engine.reconnect_pending
    assert "Reconnected" in sink.of("status")[-1][0]

    sink.events.clear()
    assert _pump(engine, lambda: sink.of("pid_value"))


def test_reconnect_backoff_gives_up_after_five_attempts():
    good, holder = scripted_connector()
    clock = {"t": 0.0}
    attempts: list[float] = []

    def flaky(device: str):
        attempts.append(clock["t"])
        if len(attempts) == 1:
            return good(device)
        raise TransportError("port busy")

    sink = Recorder()
    engine = ObdEngine(connector=flaky, on_event=sink, clock=lambda: clock["t"])
    engine.submit("connect", "/dev/OBD")
    engine.step(0.0)
    engine.submit("set_poll", ({0x0C}, 0.0))
    engine.step(0.0)
    _pump(engine, lambda: sink.of("pid_value"))

    holder["transport"].close()
    clock["t"] = 1.0
    engine.step(0.0)  # drop → schedule at t=2
    assert engine.reconnect_pending

    for t in (2.0, 4.0, 8.0, 16.0):
        clock["t"] = t
        engine.step(0.0)
        assert engine.reconnect_pending, f"still pending after attempt at {t}"

    clock["t"] = 31.0
    engine.step(0.0)
    assert not engine.reconnect_pending  # fifth failure gives up
    assert not engine.connected

    clock["t"] = 100.0
    engine.step(0.0)
    assert not engine.reconnect_pending
    assert not engine.connected

    assert attempts[1:] == [2.0, 4.0, 8.0, 16.0, 31.0]
    assert any("giving up" in m for m, in sink.of("error"))
    assert any("(1/5)" in m and "2s" in m for m, in sink.of("status"))
    assert any("(4/5)" in m and "15s" in m for m, in sink.of("status"))


def test_manual_disconnect_cancels_reconnect():
    good, holder = scripted_connector()
    clock = {"t": 0.0}
    state = {"fail": False}
    calls = {"n": 0}

    def connector(device: str):
        calls["n"] += 1
        if state["fail"]:
            raise TransportError("port busy")
        return good(device)

    sink = Recorder()
    engine = ObdEngine(connector=connector, on_event=sink, clock=lambda: clock["t"])
    engine.submit("connect", "/dev/OBD")
    engine.step(0.0)
    engine.submit("set_poll", ({0x0C}, 0.0))
    engine.step(0.0)
    _pump(engine, lambda: sink.of("pid_value"))

    holder["transport"].close()
    state["fail"] = True
    clock["t"] = 1.0
    engine.step(0.0)
    assert engine.reconnect_pending

    engine.submit("disconnect", None)
    engine.step(0.0)
    assert not engine.reconnect_pending

    state["fail"] = False
    calls_before = calls["n"]
    clock["t"] = 100.0
    engine.step(0.0)
    assert calls["n"] == calls_before  # no zombie auto-attempt


def test_manual_connect_cancels_reconnect():
    good, holder = scripted_connector()
    clock = {"t": 0.0}
    state = {"fail": False}
    calls = {"n": 0}

    def connector(device: str):
        calls["n"] += 1
        if state["fail"]:
            raise TransportError("port busy")
        return good(device)

    sink = Recorder()
    engine = ObdEngine(connector=connector, on_event=sink, clock=lambda: clock["t"])
    engine.submit("connect", "/dev/OBD")
    engine.step(0.0)
    engine.submit("set_poll", ({0x0C}, 0.0))
    engine.step(0.0)
    _pump(engine, lambda: sink.of("pid_value"))

    holder["transport"].close()
    state["fail"] = True
    clock["t"] = 1.0
    engine.step(0.0)
    assert engine.reconnect_pending

    engine.submit("connect", "/dev/OBD2")  # user retries by hand → wins the race
    engine.step(0.0)
    assert not engine.reconnect_pending
    assert sink.of("disconnected")  # manual attempt reported its failure

    state["fail"] = False
    calls_before = calls["n"]
    clock["t"] = 100.0
    engine.step(0.0)
    assert calls["n"] == calls_before


def test_read_dtcs_uses_protocol_for_can_heuristic():
    # ATDPN "A6" → CAN; even-length padded payload still count-prefixed
    connector, _holder = scripted_connector(
        {"ATDPN": b"A6\r\r>", "03": b"43 02 01 33 02 45 00\r\r>"}
    )
    sink = Recorder()
    engine = ObdEngine(connector=connector, on_event=sink)
    engine.submit("connect", "X")
    engine.step(0.0)

    engine.submit("read_dtcs", "stored")
    engine.step(0.0)

    source, codes = sink.last("dtcs")
    assert source == "stored"
    assert codes == ["P0133", "P0245"]


def test_read_dtcs_odd_length_auto_can():
    connector, _holder = scripted_connector({"07": b"43 03 01 33 02 45 03 67\r\r>"})
    sink = Recorder()
    engine = ObdEngine(connector=connector, on_event=sink)
    engine.submit("connect", "X")
    engine.step(0.0)

    engine.submit("read_dtcs", "pending")
    engine.step(0.0)

    source, codes = sink.last("dtcs")
    assert source == "pending"
    assert codes == ["P0133", "P0245", "P0367"]


def test_clear_codes():
    connector, _holder = scripted_connector({"04": b"44\r\r>"})
    sink = Recorder()
    engine = ObdEngine(connector=connector, on_event=sink)
    engine.submit("connect", "X")
    engine.step(0.0)

    engine.submit("clear_dtcs")
    engine.step(0.0)

    assert sink.last("cleared") == (True,)


def test_read_monitors():
    connector, _holder = scripted_connector({"0101": b"41 01 86 07 E5 87\r\r>"})
    sink = Recorder()
    engine = ObdEngine(connector=connector, on_event=sink)
    engine.submit("connect", "X")
    engine.step(0.0)

    engine.submit("read_monitors")
    engine.step(0.0)

    status = sink.last("monitors")[0]
    assert status.mil_on and status.dtc_count == 6
    assert not status.ready


def test_read_vehicle_info():
    connector, _holder = scripted_connector(
        {
            "0902": b"49 02 01 31 44 34 47 50 30 30 52 35 36 42 31 32 33 34 35 37\r\r>",
            "0904": b"49 04 01 45 43 4D 31 41 32 2E 33 34 00\r\r>",
            "0906": b"49 06 01 1B 2C 3D 4E\r\r>",
        }
    )
    sink = Recorder()
    engine = ObdEngine(connector=connector, on_event=sink)
    engine.submit("connect", "X")
    engine.step(0.0)

    engine.submit("read_vehicle")
    engine.step(0.0)

    info = sink.last("vehicle")[0]
    assert info["vin"] == "1D4GP00R56B123457"
    assert info["cal_ids"] == ["ECM1A2.34"]
    assert info["cvns"] == ["1B2C3D4E"]


def test_read_vehicle_tolerates_missing_optional_types():
    # No 0904/0906 in the script → "?" errors; VIN still returned
    connector, _holder = scripted_connector(
        {"0902": b"49 02 01 31 44 34 47 50 30 30 52 35 36 42 31 32 33 34 35 37\r\r>"}
    )
    sink = Recorder()
    engine = ObdEngine(connector=connector, on_event=sink)
    engine.submit("connect", "X")
    engine.step(0.0)

    engine.submit("read_vehicle")
    engine.step(0.0)

    info = sink.last("vehicle")[0]
    assert info["vin"] == "1D4GP00R56B123457"
    assert info["cal_ids"] == []


def test_read_mode06():
    connector, _holder = scripted_connector(
        {
            "0600": b"460080000000\r\r>",
            "0601": b"46 01 01 0A 06 60 06 60 06 60\r\r>",
        }
    )
    sink = Recorder()
    engine = ObdEngine(connector=connector, on_event=sink)
    engine.submit("connect", "X")
    engine.step(0.0)

    engine.submit("read_mode06")
    engine.step(0.0)
    engine.step(0.0)

    assert sink.last("mids_supported")[0] == {0x01}
    results = sink.last("mode06")[0]
    assert len(results) == 1
    assert results[0].mid == 0x01
    assert results[0].passed is True


def test_transport_failure_drops_connection():
    connector, holder = scripted_connector()
    sink = Recorder()
    engine = ObdEngine(connector=connector, on_event=sink)
    engine.submit("connect", "X")
    engine.step(0.0)
    assert engine.connected

    holder["transport"].close()  # cable yanked mid-session
    engine.submit("read_dtcs", "stored")
    engine.step(0.0)

    assert not engine.connected
    assert sink.of("error")
    assert sink.of("disconnected")


def test_disconnect_and_stop():
    connector, _holder = scripted_connector()
    sink = Recorder()
    engine = ObdEngine(connector=connector, on_event=sink)
    engine.submit("connect", "X")
    engine.step(0.0)

    engine.submit("disconnect")
    engine.step(0.0)
    assert not engine.connected
    assert sink.last("disconnected") == ("Disconnected",)

    engine.stop()
    assert engine.step(0.0) is False
    assert engine.run_forever() is None  # returns immediately after stop


def test_unknown_job_kind_is_ignored():
    sink = Recorder()
    engine = ObdEngine(on_event=sink)
    engine.submit("no_such_job")
    assert engine.step(0.0) is True
    assert sink.events == []


def test_read_voltage_job():
    connector, _holder = scripted_connector()
    sink = Recorder()
    engine = ObdEngine(connector=connector, on_event=sink)
    engine.submit("connect", "X")
    engine.step(0.0)

    engine.submit("read_voltage")
    engine.step(0.0)
    assert sink.of("voltage")[-1] == (12.6,)


def test_read_freeze_all():
    connector, _holder = scripted_connector(
        {
            "0200": b"420000100000\r\r>",  # bitmap → PID 0x0C supported
            "020C00": b"42 0C 00 1A F8\r\r>",
        }
    )
    sink = Recorder()
    engine = ObdEngine(connector=connector, on_event=sink)
    engine.submit("connect", "X")
    engine.step(0.0)

    engine.submit("read_freeze_all")
    engine.step(0.0)

    assert sink.last("freeze_supported")[0] == {0x0C}
    assert sink.last("freeze_all")[0] == {0x0C: 1726.0}


def test_elm_error_from_job_does_not_disconnect():
    # "?" response for 0101 → ElmError surfaces as error, link stays up
    connector, _holder = scripted_connector({"0101": b"?\r\r>"})
    sink = Recorder()
    engine = ObdEngine(connector=connector, on_event=sink)
    engine.submit("connect", "X")
    engine.step(0.0)

    engine.submit("read_monitors")
    engine.step(0.0)

    assert sink.of("error")
    assert engine.connected
