"""Mode $01 live-data PIDs: registry, formulas, supported-bitmap decoding.

Formulas follow SAE J1979 Appendix B (scaling per the normative tables).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from autodiag.obd import framing

# -- raw-byte scalars (each raises IndexError on truncated input) -------------

def _u8(d: bytes) -> float:
    return float(d[0])


def _u16(d: bytes) -> float:
    return float((d[0] << 8) | d[1])


def _pct255(d: bytes) -> float:
    return d[0] * 100.0 / 255


def _temp(d: bytes) -> float:
    return d[0] - 40.0


def _temp16(d: bytes) -> float:
    return _u16(d) / 10.0 - 40.0


def _trim(d: bytes) -> float:
    return d[0] / 1.28 - 100.0


def _rpm(d: bytes) -> float:
    return _u16(d) / 4.0


def _advance(d: bytes) -> float:
    return d[0] / 2.0 - 64.0


def _maf(d: bytes) -> float:
    return _u16(d) / 100.0


def _o2_volts(d: bytes) -> float:
    return d[0] / 200.0


def _load(d: bytes) -> float:
    return _u16(d) * 100.0 / 255


def _module_volts(d: bytes) -> float:
    return _u16(d) / 1000.0


def _eq_ratio(d: bytes) -> float:
    return _u16(d) / 32768.0


def _fuel_rate(d: bytes) -> float:
    return _u16(d) / 20.0


def _torque(d: bytes) -> float:
    return d[0] - 125.0


@dataclass(frozen=True)
class PidDef:
    pid: int
    name: str
    unit: str
    category: str
    data_bytes: int
    scale: Callable[[bytes], float]
    decimals: int = 1

    @property
    def hex_pid(self) -> str:
        return f"{self.pid:02X}"


def _p(
    pid: int,
    name: str,
    unit: str,
    category: str,
    data_bytes: int,
    scale: Callable[[bytes], float],
    decimals: int = 1,
) -> PidDef:
    return PidDef(pid, name, unit, category, data_bytes, scale, decimals)


_DEFS: tuple[PidDef, ...] = (
    _p(0x04, "Engine load", "%", "engine", 1, _pct255),
    _p(0x05, "Coolant temperature", "°C", "temps", 1, _temp, 0),
    _p(0x06, "Short term fuel trim B1", "%", "fuel", 1, _trim),
    _p(0x07, "Long term fuel trim B1", "%", "fuel", 1, _trim),
    _p(0x08, "Short term fuel trim B2", "%", "fuel", 1, _trim),
    _p(0x09, "Long term fuel trim B2", "%", "fuel", 1, _trim),
    _p(0x0A, "Fuel pressure (gauge)", "kPa", "fuel", 1, lambda d: d[0] * 3.0, 0),
    _p(0x0B, "Intake manifold pressure", "kPa", "air", 1, _u8, 0),
    _p(0x0C, "Engine RPM", "rpm", "engine", 2, _rpm, 0),
    _p(0x0D, "Vehicle speed", "km/h", "engine", 1, _u8, 0),
    _p(0x0E, "Ignition timing advance", "°", "engine", 1, _advance),
    _p(0x0F, "Intake air temperature", "°C", "temps", 1, _temp, 0),
    _p(0x10, "Mass air flow", "g/s", "air", 2, _maf, 2),
    _p(0x11, "Throttle position", "%", "engine", 1, _pct255),
    _p(0x14, "O2 sensor B1S1", "V", "o2", 4, _o2_volts, 3),
    _p(0x15, "O2 sensor B1S2", "V", "o2", 4, _o2_volts, 3),
    _p(0x16, "O2 sensor B2S1", "V", "o2", 4, _o2_volts, 3),
    _p(0x17, "O2 sensor B2S2", "V", "o2", 4, _o2_volts, 3),
    _p(0x18, "O2 sensor B3S1", "V", "o2", 4, _o2_volts, 3),
    _p(0x19, "O2 sensor B3S2", "V", "o2", 4, _o2_volts, 3),
    _p(0x1A, "O2 sensor B4S1", "V", "o2", 4, _o2_volts, 3),
    _p(0x1B, "O2 sensor B4S2", "V", "o2", 4, _o2_volts, 3),
    _p(0x1F, "Engine run time", "s", "engine", 2, _u16, 0),
    _p(0x21, "Distance with MIL on", "km", "emissions", 2, _u16, 0),
    _p(0x2F, "Fuel level", "%", "fuel", 1, _pct255),
    _p(0x31, "Distance since codes cleared", "km", "emissions", 2, _u16, 0),
    _p(0x33, "Barometric pressure", "kPa", "air", 1, _u8, 0),
    _p(0x3C, "Catalyst temperature B1S1", "°C", "temps", 2, _temp16),
    _p(0x3D, "Catalyst temperature B1S2", "°C", "temps", 2, _temp16),
    _p(0x42, "Control module voltage", "V", "electrical", 2, _module_volts, 3),
    _p(0x43, "Absolute engine load", "%", "engine", 2, _load),
    _p(0x44, "Commanded equivalence ratio", "λ", "fuel", 2, _eq_ratio, 3),
    _p(0x45, "Relative throttle position", "%", "engine", 1, _pct255),
    _p(0x46, "Ambient air temperature", "°C", "temps", 1, _temp, 0),
    _p(0x47, "Absolute throttle position B", "%", "engine", 1, _pct255),
    _p(0x5C, "Oil temperature", "°C", "temps", 1, _temp, 0),
    _p(0x5E, "Engine fuel rate", "L/h", "fuel", 2, _fuel_rate, 2),
    _p(0x62, "Actual engine torque", "%", "engine", 1, _torque, 0),
)

PID_REGISTRY: dict[int, PidDef] = {d.pid: d for d in _DEFS}

# Block-bitmap pseudo-PIDs a vehicle can report as supported.
SUPPORTED_PIDS: tuple[int, ...] = (0x00, 0x20, 0x40, 0x60, 0x80, 0xA0, 0xC0)


def pid_def(pid: int) -> PidDef | None:
    return PID_REGISTRY.get(pid)


def decode_pid(pid: int, data: bytes) -> float | None:
    """Scale raw data bytes for ``pid``; ``None`` if unknown PID or bad length."""
    definition = PID_REGISTRY.get(pid)
    if definition is None:
        return None
    try:
        return definition.scale(data)
    except (IndexError, ValueError, ZeroDivisionError):
        return None


def parse_pid_value(text: str, pid: int) -> float | None:
    """Decode a cleaned ``01 <pid>`` response text (``41 <pid> <data...>``)."""
    payload = framing.extract_payload(text, f"41{pid:02X}")
    if payload is None:
        return None
    try:
        data = framing.hex_to_bytes(payload)
    except ValueError:
        return None
    return decode_pid(pid, data)


def parse_supported_pids(text: str, base: int = 0x00) -> tuple[set[int], bool]:
    """Decode a ``01 <base>`` supported-PID bitmap.

    Returns (supported PIDs in ``base+1 .. base+0x20``, next-block bit).
    """
    return framing.parse_supported_mask(text, f"41{base:02X}", base)
