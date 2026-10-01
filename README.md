# AutoDiag Pro

**OBD-II scan tool** — desktop diagnostics app for ELM327 adapters (USB / Bluetooth SPP).

Dark-themed PySide6 dashboard that talks to your car's ELM327 adapter over a serial
port (USB cable or paired Bluetooth SPP dongle).

## Features (target)

- **Live data** — engine RPM, speed, coolant, load, fuel trims, O2 sensors... ~40 SAE
  J1979 PIDs discovered from the vehicle (`0100` supported-PID bitmaps), gauges +
  scrolling graphs
- **Trouble codes** — read stored (`03`), pending (`07`) and permanent (`0A`) DTCs
  with plain-English descriptions; clear codes (`04`, MIL off)
- **Freeze frame** — sensor snapshot captured when a fault was set (`02`)
- **Readiness monitors** — I/M status: check emissions readiness before a smog test
- **Vehicle info** — VIN, calibration IDs, CVN, ECU name (`09`), battery voltage
- **Mode $06** — onboard test results (MID/TID min/max/value, pass/fail)
- **Reports** — export scan results to CSV / JSON

Fully offline: no accounts, no servers — everything runs on your machine.

## Status

| Milestone | Status |
|---|---|
| 1. Project bootstrap (tooling, CI) | done |
| 2. ELM327 session + serial transport | done |
| 3. Decoders (PIDs, DTC, freeze, readiness, VIN, Mode 06) | done |
| 4. Worker thread + polling scheduler | done |
| 5. UI core (dashboard, gauges, live graph) | pending |
| 6. Diagnostic panels + settings + export | pending |
| 7. Packaging (PyInstaller) + docs | pending |

## Install & run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

autodiag            # or: python -m autodiag
```

## Development

```bash
ruff check .        # lint
pytest -q           # unit tests (no hardware needed — ELM327 fakes)
```

Tests run entirely against scripted fake adapters, so no OBD hardware is required.

## Hardware

Any ELM327-compatible adapter with a serial profile:

- **USB** — appears as `/dev/ttyUSB0` (Linux) or `COMx` (Windows)
- **Bluetooth SPP** — pair it in your OS settings first (e.g. PIN `1234` or `0000`),
  then pick the paired port in the app

Cheap ELM327 v1.5/v2.1 clones work; common baud rates (38400/57600/115200) are
auto-detected.

## Project layout

```
autodiag/
  transports/   byte-pipe Transport ABC + serial (USB/BT SPP) implementation
  obd/          ELM327 session, response framing, J1979 decoders, DTC dictionary
  services/     Qt worker thread + polling scheduler
  ui/           PySide6 windows, panels, gauges
  data/         bundled data files (DTC descriptions)
tests/          pytest suite (fake serial / fake ELM327)
```

## License

See repository for license details.
