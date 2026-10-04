"""CLI tests: argparse dispatch, doctor, and scan — all against scripted fakes."""

from __future__ import annotations

import json
import sys

import pytest

import autodiag.__main__ as entry
from autodiag import cli
from autodiag.obd.elm327 import Elm327Session
from autodiag.transports.base import TransportError
from autodiag.transports.serial_transport import Connection, SerialPortInfo
from tests.fakes import FakeTransport, elm_script, scripted_connector

FAST = {"reset_timeout": 0.5, "command_timeout": 0.5, "probe_timeout": 0.5}

VIN_SCRIPT = b"49 02 01 31 44 34 47 50 30 30 52 35 36 42 31 32 33 34 35 37\r\r>"

SCAN_SCRIPT = {
    "ATDPN": b"A6\r\r>",
    "0902": VIN_SCRIPT,
    "0101": b"41 01 86 07 E5 87\r\r>",
    "03": b"43 02 01 33 02 45 00\r\r>",
    "0600": b"460080000000\r\r>",
    "0601": b"46 01 01 0A 06 60 06 60 06 60\r\r>",
    "0200": b"420000000000\r\r>",
}


def make_connect(script: dict[str, bytes] | None = None):
    """A connect_elm327 double backed by an in-memory scripted transport."""
    responses = elm_script(**(script or {}))

    def connect(device, *, probe_vehicle=True, on_status=None, **_kwargs):
        assert on_status is not None
        session = Elm327Session(FakeTransport(responses), **FAST)
        info = session.initialize(probe_vehicle=probe_vehicle)
        return Connection(session=session, info=info, baudrate=38400)

    return connect


def test_help_and_version(capsys):
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--help"])
    assert excinfo.value.code == 0
    assert "doctor" in capsys.readouterr().out

    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--version"])
    assert excinfo.value.code == 0


def test_no_command_prints_help_returns_usage(capsys):
    assert cli.main([]) == 2
    assert "usage:" in capsys.readouterr().err


def test_ports_lists_device(monkeypatch, capsys):
    monkeypatch.setattr(
        cli,
        "list_serial_ports",
        lambda: [SerialPortInfo("/dev/ttyUSB0", "FTDI FT232R")],
    )
    assert cli.main(["ports"]) == 0
    out = capsys.readouterr().out
    assert "/dev/ttyUSB0" in out and "FTDI FT232R" in out


def test_ports_empty_is_still_success(monkeypatch, capsys):
    monkeypatch.setattr(cli, "list_serial_ports", lambda: [])
    assert cli.main(["ports"]) == 0
    assert "No serial ports" in capsys.readouterr().out


def test_doctor_passes_with_adapter_alone(monkeypatch, capsys):
    monkeypatch.setattr(cli, "connect_elm327", make_connect())
    assert cli.main(["doctor", "-d", "FAKE"]) == 0
    out = capsys.readouterr()
    assert "RESULT: PASS" in out.out
    assert "12.6 V" in out.out
    assert "ELM327 v1.5" in out.out


def test_doctor_auto_picks_single_port(monkeypatch, capsys):
    monkeypatch.setattr(
        cli, "list_serial_ports", lambda: [SerialPortInfo("/dev/ttyUSB1", "CP2102")]
    )
    monkeypatch.setattr(cli, "connect_elm327", make_connect())
    assert cli.main(["doctor"]) == 0
    assert "Using /dev/ttyUSB1" in capsys.readouterr().err


def test_doctor_multiple_ports_requires_device(monkeypatch, capsys):
    monkeypatch.setattr(
        cli,
        "list_serial_ports",
        lambda: [SerialPortInfo("/dev/ttyUSB0", "A"), SerialPortInfo("/dev/ttyUSB1", "B")],
    )
    assert cli.main(["doctor"]) == 1
    err = capsys.readouterr().err
    assert "--device" in err and "/dev/ttyUSB0" in err


def test_doctor_connect_failure_fails(monkeypatch, capsys):
    def bad_connect(device, **_kwargs):
        raise TransportError(f"No ELM327 response on {device}")

    monkeypatch.setattr(cli, "connect_elm327", bad_connect)
    assert cli.main(["doctor", "-d", "FAKE"]) == 1
    assert "FAIL:" in capsys.readouterr().err


def test_doctor_vehicle_probe_detects(monkeypatch, capsys):
    monkeypatch.setattr(cli, "connect_elm327", make_connect())
    assert cli.main(["doctor", "-d", "FAKE", "--vehicle"]) == 0
    assert "vehicle:  detected" in capsys.readouterr().out


def test_doctor_vehicle_probe_tolerates_dead_bus(monkeypatch, capsys):
    script = {"0100": b"UNABLE TO CONNECT\r\r>"}
    monkeypatch.setattr(cli, "connect_elm327", make_connect(script))
    assert cli.main(["doctor", "-d", "FAKE", "--vehicle"]) == 0
    out = capsys.readouterr().out
    assert "not detected" in out
    assert "RESULT: PASS" in out


def test_scan_writes_report(tmp_path, capsys):
    connector, _holder = scripted_connector(SCAN_SCRIPT)
    out_file = tmp_path / "scan.json"
    rc = cli.run_scan("FAKE", out=out_file, seconds=0.3, interval=0.05, connector=connector)
    assert rc == 0

    data = json.loads(out_file.read_text())
    assert data["vehicle"]["vin"] == "1D4GP00R56B123457"
    assert [d["code"] for d in data["dtcs"]["stored"]] == ["P0133", "P0245"]
    assert data["readiness"]["mil_on"] is True
    assert len(data["mode06"]) == 1
    assert {d["pid"] for d in data["live_data"]} == {"05", "0C", "0D"}

    out = capsys.readouterr().out
    assert "1D4GP00R56B123457" in out and "Report written" in out


def test_scan_connect_failure_returns_1(tmp_path, capsys):
    def bad_connect(device, **_kwargs):
        raise TransportError(f"No ELM327 response on {device}")

    out_file = tmp_path / "scan.json"
    rc = cli.run_scan("FAKE", out=out_file, connector=bad_connect)
    assert rc == 1
    assert not out_file.exists()
    assert "Connection failed" in capsys.readouterr().err


def test_scan_dispatch_parses_arguments(monkeypatch, capsys):
    recorded: dict = {}

    def fake_scan(device, **kwargs):
        recorded["device"] = device
        recorded.update(kwargs)
        return 0

    monkeypatch.setattr(cli, "run_scan", fake_scan)
    rc = cli.main(
        [
            "scan", "-d", "FAKE", "-o", "r.json", "--seconds", "1.5",
            "--interval", "0.1", "--pids", "0c,0x0D",
        ]
    )
    assert rc == 0
    assert recorded["device"] == "FAKE"
    assert recorded["out"] == "r.json"
    assert recorded["seconds"] == 1.5
    assert recorded["interval"] == 0.1
    assert recorded["pids"] == {0x0C, 0x0D}


def test_scan_rejects_bad_pids(monkeypatch, capsys):
    assert cli.main(["scan", "-d", "FAKE", "--pids", "zz"]) == 2
    assert "invalid PID" in capsys.readouterr().err


def test_entry_dispatches_cli(monkeypatch):
    called: dict = {}

    def fake_cli_main(argv):
        called["argv"] = argv
        return 0

    monkeypatch.setattr(cli, "main", fake_cli_main)
    monkeypatch.setattr(sys, "argv", ["autodiag", "ports", "--x"])
    with pytest.raises(SystemExit) as excinfo:
        entry.main()
    assert excinfo.value.code == 0
    assert called["argv"] == ["ports", "--x"]


def test_entry_without_args_launches_gui(monkeypatch):
    monkeypatch.setattr(cli, "main", lambda argv: pytest.fail("CLI must not run"))
    monkeypatch.setattr(sys, "argv", ["autodiag"])
    from autodiag.ui import app as ui_app

    monkeypatch.setattr(ui_app, "main", lambda: 7)
    with pytest.raises(SystemExit) as excinfo:
        entry.main()
    assert excinfo.value.code == 7
