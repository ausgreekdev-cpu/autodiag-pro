"""Serial transport + auto-baud connect tests (scripted fake serial)."""

import pytest

from autodiag.obd.elm327 import ElmError
from autodiag.transports.base import TransportError
from autodiag.transports.serial_transport import (
    BAUD_CANDIDATES,
    SerialPortInfo,
    SerialTransport,
    connect_elm327,
    list_serial_ports,
)
from tests.fakes import FakeSerial, RecordingFactory, elm_script

FAST = {"reset_timeout": 0.1, "command_timeout": 0.2, "probe_timeout": 0.3}


def test_list_serial_ports_returns_port_infos():
    ports = list_serial_ports()
    assert isinstance(ports, list)
    assert all(isinstance(p, SerialPortInfo) and p.device for p in ports)


def test_baud_candidates_cover_common_clones():
    assert BAUD_CANDIDATES[0] == 38400
    assert 115200 in BAUD_CANDIDATES


def test_serial_transport_roundtrip():
    fake = FakeSerial(responses=elm_script())
    transport = SerialTransport("/dev/fake", 38400, serial_factory=lambda _d, _b: fake)
    transport.open()
    assert transport.is_open
    transport.write(b"010C\r")
    data = transport.read(timeout=0.05)
    assert b"41 0C" in data
    transport.close()
    assert not transport.is_open


def test_serial_transport_read_requires_open():
    transport = SerialTransport("/dev/fake", 38400, serial_factory=lambda _d, _b: FakeSerial())
    with pytest.raises(TransportError):
        transport.write(b"0100\r")
    with pytest.raises(TransportError):
        transport.read()


def test_serial_transport_wraps_open_failure():
    def bad_factory(_device, _baud):
        raise OSError("permission denied")

    transport = SerialTransport("/dev/fake", 38400, serial_factory=bad_factory)
    with pytest.raises(TransportError, match="permission denied"):
        transport.open()


def test_connect_autobaud_skips_silent_baud():
    factory = RecordingFactory({
        38400: FakeSerial(silent=True),
        115200: FakeSerial(responses=elm_script()),
    })
    connection = connect_elm327(
        "/dev/fake",
        bauds=(38400, 115200),
        serial_factory=factory,
        session_options=FAST,
    )
    assert connection.baudrate == 115200
    assert factory.attempts == [("/dev/fake", 38400), ("/dev/fake", 115200)]
    assert connection.info.voltage == pytest.approx(12.6)
    connection.session.close()


def test_connect_no_adapter_raises_transport_error():
    factory = RecordingFactory({})
    with pytest.raises(TransportError, match="No ELM327 response"):
        connect_elm327(
            "/dev/fake",
            bauds=(38400, 115200),
            serial_factory=factory,
            session_options=FAST,
        )
    assert factory.attempts == [("/dev/fake", 38400), ("/dev/fake", 115200)]


def test_connect_vehicle_error_stops_baud_churn():
    # Adapter answered ATZ (right baud) but the car doesn't respond —
    # must raise immediately instead of trying the remaining baud rates.
    no_vehicle = elm_script(**{"0100": b"UNABLE TO CONNECT\r\r>"})
    factory = RecordingFactory({38400: FakeSerial(responses=no_vehicle)})
    with pytest.raises(ElmError) as excinfo:
        connect_elm327(
            "/dev/fake",
            bauds=(38400, 115200),
            serial_factory=factory,
            session_options=FAST,
        )
    assert excinfo.value.kind == "no-vehicle"
    assert factory.attempts == [("/dev/fake", 38400)]


def test_connect_port_failure_raises_immediately():
    # Port-level problems are baud-independent — stop after the first try.

    def bad_factory(_device, _baud):
        raise OSError("permission denied")

    with pytest.raises(TransportError, match="permission denied"):
        connect_elm327(
            "/dev/fake",
            bauds=(38400, 115200),
            serial_factory=bad_factory,
            session_options=FAST,
        )
