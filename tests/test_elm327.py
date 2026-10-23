"""ELM327 session tests against the scripted FakeTransport (no hardware)."""

import threading
import time

import pytest

from autodiag.obd.elm327 import Elm327Session, ElmAborted, ElmError, ElmTimeout
from tests.fakes import FakeTransport, elm_script

FAST = {"reset_timeout": 0.5, "command_timeout": 0.5, "probe_timeout": 0.5}


def make_session(
    script: dict[str, bytes] | None = None,
    **overrides,
) -> tuple[Elm327Session, FakeTransport]:
    transport = FakeTransport(script if script is not None else elm_script())
    options = {**FAST, **overrides}
    return Elm327Session(transport, **options), transport


def test_initialize_happy_path():
    session, transport = make_session()
    info = session.initialize()

    assert info.adapter == "ELM327 v1.5"
    assert info.voltage == pytest.approx(12.6)
    assert info.protocol_number == "A"
    assert info.protocol is not None and info.protocol.startswith("AUTO")
    assert session.adapter_seen
    assert transport.is_open
    assert transport.writes == [
        "ATZ", "ATE0", "ATL0", "ATS0", "ATH0",
        "ATRV", "ATI", "ATAT2", "ATSP0", "0100", "ATDPN", "ATDP",
    ]


def test_initialize_without_vehicle_probe_skips_bus():
    session, transport = make_session()
    info = session.initialize(probe_vehicle=False)

    assert info.adapter == "ELM327 v1.5"
    assert info.voltage == pytest.approx(12.6)
    assert info.protocol is None and info.protocol_number is None
    assert "0100" not in transport.writes
    assert "ATSP0" not in transport.writes
    assert transport.writes == [
        "ATZ", "ATE0", "ATL0", "ATS0", "ATH0", "ATRV", "ATI", "ATAT2"
    ]


def test_initialize_pins_protocol():
    session, transport = make_session()
    info = session.initialize(protocol="6")

    assert transport.writes.index("ATSP6") < transport.writes.index("0100")
    assert info.protocol is not None  # ATDP still reports the bus description


def test_initialize_kline_protocol_raises_intercharacter_timeout():
    session, transport = make_session()
    session.initialize(protocol="3")

    writes = transport.writes
    assert writes.index("ATSP3") < writes.index("AT ST 64") < writes.index("0100")


def test_initialize_protocol_code_is_case_insensitive():
    session, transport = make_session()
    session.initialize(protocol="a")
    assert "ATSPA" in transport.writes


def test_initialize_rejects_unknown_protocol_before_io():
    session, transport = make_session()
    with pytest.raises(ValueError, match="protocol"):
        session.initialize(protocol="Z")
    assert transport.writes == []
    assert not session.adapter_seen


def test_command_returns_cleaned_payload():
    session, _transport = make_session()
    session.initialize()
    assert session.command("010C") == "41 0C 1A F8"
    assert session.command("010D") == "41 0D 3C"


def test_no_vehicle_raises_but_adapter_seen():
    no_vehicle = elm_script(**{"0100": b"SEARCHING...\r\nUNABLE TO CONNECT\r\r>"})
    session, _transport = make_session(no_vehicle)
    with pytest.raises(ElmError) as excinfo:
        session.initialize()
    assert excinfo.value.kind == "no-vehicle"
    assert session.adapter_seen  # baud is right — callers must not churn bauds


def test_timeout_before_banner():
    session, _transport = make_session({"ATZ": b"\r\rgarbage without prompt"}, reset_timeout=0.05)
    with pytest.raises(ElmTimeout) as excinfo:
        session.initialize()
    assert "ATZ" in str(excinfo.value)
    assert not session.adapter_seen


def test_garbage_banner_rejected():
    session, _transport = make_session({"ATZ": b"\x81\xfe\x03\x1f\r\r>"}, reset_timeout=0.5)
    with pytest.raises(ElmError) as excinfo:
        session.initialize()
    assert excinfo.value.kind == "no-adapter"
    assert not session.adapter_seen


def test_stale_bytes_are_drained():
    session, transport = make_session()
    session.initialize()
    transport.inject(b"stale partial>")
    assert session.command("010C") == "41 0C 1A F8"


def test_command_error_no_data():
    session, _transport = make_session(elm_script(**{"010C": b"NO DATA\r\r>"}))
    session.initialize()
    with pytest.raises(ElmError) as excinfo:
        session.command("010C")
    assert excinfo.value.kind == "no-data"


def test_command_error_unknown_pid_query():
    # Unscripted commands fall back to the adapter's `?` response.
    session, _transport = make_session()
    session.initialize()
    with pytest.raises(ElmError) as excinfo:
        session.command("01FF")
    assert excinfo.value.kind == "bad-command"


def test_best_effort_protocol_queries_tolerated():
    # Clones that don't know ATDPN answer `?` — init must still succeed.
    session, _transport = make_session(elm_script(**{"ATDPN": b"?\r\r>", "ATDP": b"?\r\r>"}))
    info = session.initialize()
    assert info.protocol_number is None
    assert info.protocol is None


def test_close_closes_transport():
    session, transport = make_session()
    session.initialize()
    session.close()
    assert not transport.is_open


def test_initialize_detects_stn_adapter():
    session, _transport = make_session(elm_script(ATZ=b"\r\rSTN1110 v4.1\r\r>"))
    info = session.initialize()
    assert info.stn is True


def test_initialize_detects_obdlink_via_ati():
    session, _transport = make_session(elm_script(ATI=b"\r\rOBDLink MX+ 5.3\r\r>"))
    info = session.initialize()
    assert info.stn is True


def test_initialize_plain_elm_is_not_stn():
    session, _transport = make_session()
    info = session.initialize()
    assert info.stn is False


def test_initialize_unknown_clone_still_sends_atat2():
    # The adaptive-timing command is best-effort: clones that do not know it
    # answer "?" and initialization carries on.
    session, transport = make_session()
    info = session.initialize()
    assert "ATAT2" in transport.writes
    assert info.adapter == "ELM327 v1.5"


# -- cancellation ----------------------------------------------------------------


class _DeadBus(FakeTransport):
    """Accepts writes but never answers — an adapter with no vehicle talking."""

    def read(self, max_bytes: int = 1024, timeout: float = 0.1) -> bytes:
        time.sleep(min(max(timeout, 0.0), 0.01))
        return b""


def test_abort_is_not_an_elm_error():
    # Retry/fallback loops catch ElmError; an abort must not be mistaken for a
    # request that failed and may simply be re-sent.
    assert not issubclass(ElmAborted, ElmError)


def test_command_aborts_within_one_read_slice():
    stop = threading.Event()
    transport = _DeadBus({})
    transport.open()
    session = Elm327Session(transport, command_timeout=5.0)
    session.set_abort_hook(stop.is_set)
    threading.Timer(0.05, stop.set).start()

    started = time.monotonic()
    with pytest.raises(ElmAborted):
        session.command("0100")
    elapsed = time.monotonic() - started

    assert elapsed < 1.0, f"abort took {elapsed:.2f}s of a 5s timeout"


def test_abort_before_write_skips_the_command():
    session, transport = make_session()
    session.set_abort_hook(lambda: True)
    with pytest.raises(ElmAborted):
        session.command("010C")
    assert "010C" not in transport.writes


def test_abort_hook_can_be_removed():
    session, transport = make_session()
    session.initialize()
    session.set_abort_hook(lambda: True)
    session.set_abort_hook(None)
    assert "41 0C" in session.command("010C")
    assert transport.writes[-1] == "010C"


# -- pre-command drain ---------------------------------------------------------


class _BlockingPort(FakeTransport):
    """Models pyserial: a read with an empty buffer blocks for the timeout."""

    def __init__(self, responses: dict[str, bytes] | None = None) -> None:
        super().__init__(responses)
        self.empty_reads = 0

    def read(self, max_bytes: int = 1024, timeout: float = 0.1) -> bytes:
        if not self._buf:
            self.empty_reads += 1
            time.sleep(min(max(timeout, 0.0), 0.2))
            return b""
        return super().read(max_bytes, timeout)


class _UnknownBuffer(FakeTransport):
    """A byte pipe that cannot report its buffer (the pre-pending() path)."""

    def pending(self) -> int | None:
        return None


def test_command_does_not_block_draining_an_empty_port():
    transport = _BlockingPort(elm_script())
    session = Elm327Session(transport, **FAST)
    session.initialize()
    transport.empty_reads = 0

    started = time.monotonic()
    for _ in range(5):
        assert session.command("010C") == "41 0C 1A F8"
    elapsed = time.monotonic() - started

    assert transport.empty_reads == 0  # no speculative read before the write
    assert elapsed < 0.05, f"five commands took {elapsed:.2f}s"


def test_stale_bytes_drain_without_waiting_out_a_timeout():
    transport = _BlockingPort(elm_script())
    session = Elm327Session(transport, **FAST)
    session.initialize()
    transport.inject(b"stale partial>")

    started = time.monotonic()
    assert session.command("010C") == "41 0C 1A F8"
    assert time.monotonic() - started < 0.05
    assert transport.empty_reads == 0


def test_drain_falls_back_to_a_timed_read_when_pending_is_unknown():
    transport = _UnknownBuffer(elm_script())
    session = Elm327Session(transport, **FAST)
    session.initialize()
    transport.inject(b"stale partial>")
    assert session.command("010C") == "41 0C 1A F8"


def test_first_command_after_a_timeout_resyncs_the_line():
    transport = _BlockingPort(elm_script(**{"010C": b""}))  # no answer
    session = Elm327Session(transport, command_timeout=0.02)
    session.initialize(probe_vehicle=False)

    with pytest.raises(ElmTimeout):
        session.command("010C")
    assert session._unclean

    transport.empty_reads = 0
    assert "41 0D" in session.command("010D")
    # late bytes may still be on the wire: one timed drain before the write
    assert transport.empty_reads >= 1
    assert not session._unclean
