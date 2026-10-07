"""ELM327 session tests against the scripted FakeTransport (no hardware)."""

import pytest

from autodiag.obd.elm327 import Elm327Session, ElmError, ElmTimeout
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
        "ATRV", "ATI", "ATSP0", "0100", "ATDPN", "ATDP",
    ]


def test_initialize_without_vehicle_probe_skips_bus():
    session, transport = make_session()
    info = session.initialize(probe_vehicle=False)

    assert info.adapter == "ELM327 v1.5"
    assert info.voltage == pytest.approx(12.6)
    assert info.protocol is None and info.protocol_number is None
    assert "0100" not in transport.writes
    assert "ATSP0" not in transport.writes
    assert transport.writes == ["ATZ", "ATE0", "ATL0", "ATS0", "ATH0", "ATRV", "ATI"]


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
