"""Headless CLI: serial-port listing, adapter smoke test, scans, update check.

Pure Python (no Qt): the OBD engine is driven synchronously with ``step()``,
so every command is deterministic and testable against the fake transports.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

from autodiag import __version__
from autodiag.obd.elm327 import ElmError
from autodiag.services.engine import Connector, ObdEngine
from autodiag.services.export import write_report
from autodiag.services.record import ScanRecord
from autodiag.services.update_check import check_for_update
from autodiag.transports.base import TransportError
from autodiag.transports.serial_transport import connect_elm327, list_serial_ports

# Poll defaults for a scan: RPM, speed, coolant temperature.
SCAN_PIDS: tuple[int, ...] = (0x0C, 0x0D, 0x05)
VEHICLE_PROBE_TIMEOUT = 5.0


def resolve_device(requested: str | None) -> str | None:
    """Explicit ``--device``, else the only port present (``None`` = failed)."""
    if requested:
        return requested
    ports = list_serial_ports()
    if len(ports) == 1:
        print(f"Using {ports[0].device} ({ports[0].description})", file=sys.stderr)
        return ports[0].device
    if not ports:
        print("No serial ports found — plug in an adapter or pass --device.", file=sys.stderr)
    else:
        print("Multiple serial ports found — pass --device:", file=sys.stderr)
        for p in ports:
            print(f"  {p.device}  {p.description}", file=sys.stderr)
    return None


def cmd_ports() -> int:
    ports = list_serial_ports()
    if not ports:
        print("No serial ports found.")
        return 0
    for p in ports:
        print(f"{p.device}  {p.description}")
    return 0


def cmd_updates(timeout: float = 5.0) -> int:
    """Compare the running version with GitHub's latest release (exit 1 on failure)."""
    result = check_for_update(__version__, timeout=timeout)
    if result.status == "update":
        print(f"{result.latest} is available — {result.url}")
        return 0
    if result.status == "current":
        print(f"You're up to date (v{__version__}).")
        return 0
    print(f"Update check failed: {result.message}", file=sys.stderr)
    return 1


def run_doctor(
    device: str,
    *,
    connect: Connector | None = None,
    vehicle: bool = False,
) -> int:
    """Adapter-only smoke test: banner, voltage, optional ``0100`` bus probe."""
    connect = connect if connect is not None else connect_elm327
    try:
        conn = connect(
            device,
            probe_vehicle=False,
            on_status=lambda msg: print(f"  {msg}", file=sys.stderr),
        )
    except (TransportError, ElmError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    try:
        info = conn.info
        voltage = "unknown" if info.voltage is None else f"{info.voltage:g} V"
        print(f"port:     {device} ({conn.baudrate} baud)")
        print(f"adapter:  {info.adapter}")
        print(f"voltage:  {voltage}")
        if vehicle:
            try:
                conn.session.command("0100", timeout=VEHICLE_PROBE_TIMEOUT)
                print("vehicle:  detected")
            except TransportError as exc:
                print(f"FAIL: {exc}", file=sys.stderr)
                return 1
            except ElmError as exc:
                print(f"vehicle:  not detected ({exc})")
        print("RESULT: PASS")
        return 0
    finally:
        conn.session.close()


def run_scan(
    device: str,
    *,
    out: str | Path | None = None,
    seconds: float = 5.0,
    interval: float = 0.25,
    pids: set[int] | None = None,
    connector: Connector | None = None,
) -> int:
    """Connect, read every report section, poll live briefly, write a report."""
    record = ScanRecord()

    def sink(kind: str, args: tuple) -> None:
        record.record_event(kind, args)
        if kind == "status":
            print(args[0], file=sys.stderr)
        elif kind == "error":
            print(f"Error: {args[0]}", file=sys.stderr)
        elif kind == "disconnected" and args[0] not in {"Disconnected", "Stopped"}:
            print(f"Link lost: {args[0]}", file=sys.stderr)

    engine = ObdEngine(connector=connector, on_event=sink)
    print(f"Connecting to {device}...", file=sys.stderr)
    engine.submit("connect", device)
    engine.step(0)
    if not engine.connected:
        print("Connection failed.", file=sys.stderr)
        return 1

    for kind, payload in (
        ("read_vehicle", None),
        ("read_dtcs", "stored"),
        ("read_dtcs", "pending"),
        ("read_dtcs", "permanent"),
        ("read_monitors", None),
        ("read_mode06", None),
        ("read_freeze_all", 0),
    ):
        engine.submit(kind, payload)
        engine.step(0)

    wanted = set(pids if pids is not None else SCAN_PIDS) & engine.supported_pids
    if not wanted:
        wanted = set(sorted(engine.supported_pids)[:4])
    engine.submit("set_poll", (wanted, max(interval, 0.0)))
    engine.step(0)

    deadline = time.monotonic() + max(seconds, 0.0)
    while (remaining := deadline - time.monotonic()) > 0:
        engine.step(min(0.05, remaining))

    # Write before disconnecting: build_report snapshots record.session.
    path = Path(out) if out else Path(f"autodiag-scan-{datetime.now():%Y%m%d-%H%M%S}.json")
    write_report(record, path)

    dtc_total = sum(len(codes) for codes in record.dtcs.values())
    print(
        f"Scan complete — VIN {record.vin or 'unknown'}, {dtc_total} DTC(s), "
        f"{len(record.mode06)} Mode $06 result(s), {len(record.pids)} live PID(s)"
    )
    print(f"Report written: {path}")

    engine.submit("disconnect", None)
    engine.step(0)
    return 0


def parse_pids(text: str) -> set[int]:
    out: set[int] = set()
    for token in text.split(","):
        token = token.strip().lower().removeprefix("0x")
        if not token:
            continue
        try:
            out.add(int(token, 16))
        except ValueError:
            raise ValueError(f"invalid PID: {token!r}") from None
    if not out:
        raise ValueError("no PIDs given")
    return out


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="autodiag",
        description="AutoDiag Pro headless tools. Run with no arguments to launch the GUI.",
    )
    parser.add_argument("--version", action="version", version=f"AutoDiag Pro {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.add_parser("ports", help="list serial ports the OS knows about")
    doctor = sub.add_parser("doctor", help="smoke-test an ELM327 adapter (no vehicle needed)")
    doctor.add_argument("-d", "--device", help="serial device (default: the only port present)")
    doctor.add_argument("--vehicle", action="store_true", help="also probe the bus with 0100")
    scan = sub.add_parser("scan", help="run a headless scan and write a report")
    scan.add_argument("-d", "--device", help="serial device (default: the only port present)")
    scan.add_argument("-o", "--out", help="report path (.json or .csv)")
    scan.add_argument("--seconds", type=float, default=5.0, help="live-poll duration (default: 5)")
    scan.add_argument("--interval", type=float, default=0.25, help="poll interval in seconds")
    scan.add_argument("--pids", help="comma-separated hex PIDs to poll (default: 0C,0D,05)")
    updates = sub.add_parser("updates", help="check GitHub for a newer release")
    updates.add_argument(
        "--timeout", type=float, default=5.0, help="request timeout in seconds"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "ports":
        return cmd_ports()
    if args.command == "doctor":
        device = resolve_device(args.device)
        if device is None:
            return 1
        return run_doctor(device, vehicle=args.vehicle)
    if args.command == "scan":
        device = resolve_device(args.device)
        if device is None:
            return 1
        try:
            pids = parse_pids(args.pids) if args.pids else None
        except ValueError as exc:
            print(f"{parser.prog} scan: error: {exc}", file=sys.stderr)
            return 2
        return run_scan(
            device,
            out=args.out,
            seconds=args.seconds,
            interval=args.interval,
            pids=pids,
        )
    if args.command == "updates":
        return cmd_updates(timeout=args.timeout)
    parser.print_help(sys.stderr)
    return 2
