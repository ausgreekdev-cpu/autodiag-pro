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


def _o2_stft(d: bytes) -> float:
    return (d[1] - 128) * 100.0 / 128


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


def _i16(d: bytes) -> float:
    value = (d[0] << 8) | d[1]
    return float(value - 0x10000 if value & 0x8000 else value)


def _evap_vapor(d: bytes) -> float:
    return _i16(d) / 4.0


def _rail_relative(d: bytes) -> float:
    return _u16(d) * 0.079


def _rail_x10(d: bytes) -> float:
    return _u16(d) * 10.0


def _o2_wb_volts(d: bytes) -> float:
    return ((d[2] << 8) | d[3]) * 8.0 / 65536.0


def _trim_second(d: bytes) -> float:
    return d[1] / 1.28 - 100.0


def _timing(d: bytes) -> float:
    return _u16(d) / 128.0 - 210.0


def _u16_div200(d: bytes) -> float:
    return _u16(d) / 200.0


def _u16_div32(d: bytes) -> float:
    return _u16(d) / 32.0


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
    _p(0x14, "O2 sensor B1S1", "V", "o2", 2, _o2_volts, 3),
    _p(0x15, "O2 sensor B1S2", "V", "o2", 2, _o2_volts, 3),
    _p(0x16, "O2 sensor B2S1", "V", "o2", 2, _o2_volts, 3),
    _p(0x17, "O2 sensor B2S2", "V", "o2", 2, _o2_volts, 3),
    _p(0x18, "O2 sensor B3S1", "V", "o2", 2, _o2_volts, 3),
    _p(0x19, "O2 sensor B3S2", "V", "o2", 2, _o2_volts, 3),
    _p(0x1A, "O2 sensor B4S1", "V", "o2", 2, _o2_volts, 3),
    _p(0x1B, "O2 sensor B4S2", "V", "o2", 2, _o2_volts, 3),
    _p(0x1C, "OBD standard", "", "emissions", 1, _u8, 0),
    _p(0x1F, "Engine run time", "s", "engine", 2, _u16, 0),
    _p(0x21, "Distance with MIL on", "km", "emissions", 2, _u16, 0),
    _p(0x22, "Fuel rail pressure (relative)", "kPa", "fuel", 2, _rail_relative),
    _p(0x23, "Fuel rail gauge pressure", "kPa", "fuel", 2, _rail_x10, 0),
    _p(0x24, "O2 lambda B1S1", "λ", "o2", 4, _eq_ratio, 3),
    _p(0x25, "O2 lambda B1S2", "λ", "o2", 4, _eq_ratio, 3),
    _p(0x26, "O2 lambda B2S1", "λ", "o2", 4, _eq_ratio, 3),
    _p(0x27, "O2 lambda B2S2", "λ", "o2", 4, _eq_ratio, 3),
    _p(0x28, "O2 lambda B3S1", "λ", "o2", 4, _eq_ratio, 3),
    _p(0x29, "O2 lambda B3S2", "λ", "o2", 4, _eq_ratio, 3),
    _p(0x2A, "O2 lambda B4S1", "λ", "o2", 4, _eq_ratio, 3),
    _p(0x2B, "O2 lambda B4S2", "λ", "o2", 4, _eq_ratio, 3),
    _p(0x2C, "Commanded EGR", "%", "emissions", 1, _pct255),
    _p(0x2D, "EGR error", "%", "emissions", 1, _trim),
    _p(0x2E, "Commanded evaporative purge", "%", "emissions", 1, _pct255),
    _p(0x2F, "Fuel level", "%", "fuel", 1, _pct255),
    _p(0x30, "Warm-ups since codes cleared", "", "emissions", 1, _u8, 0),
    _p(0x31, "Distance since codes cleared", "km", "emissions", 2, _u16, 0),
    _p(0x32, "Evaporative vapor pressure", "Pa", "emissions", 2, _evap_vapor, 2),
    _p(0x33, "Barometric pressure", "kPa", "air", 1, _u8, 0),
    _p(0x3C, "Catalyst temperature B1S1", "°C", "temps", 2, _temp16),
    _p(0x3D, "Catalyst temperature B2S1", "°C", "temps", 2, _temp16),
    _p(0x3E, "Catalyst temperature B1S2", "°C", "temps", 2, _temp16),
    _p(0x3F, "Catalyst temperature B2S2", "°C", "temps", 2, _temp16),
    _p(0x42, "Control module voltage", "V", "electrical", 2, _module_volts, 3),
    _p(0x43, "Absolute engine load", "%", "engine", 2, _load),
    _p(0x44, "Commanded equivalence ratio", "λ", "fuel", 2, _eq_ratio, 3),
    _p(0x45, "Relative throttle position", "%", "engine", 1, _pct255),
    _p(0x46, "Ambient air temperature", "°C", "temps", 1, _temp, 0),
    _p(0x47, "Absolute throttle position B", "%", "engine", 1, _pct255),
    _p(0x48, "Absolute throttle position C", "%", "engine", 1, _pct255),
    _p(0x49, "Accelerator pedal position D", "%", "engine", 1, _pct255),
    _p(0x4A, "Accelerator pedal position E", "%", "engine", 1, _pct255),
    _p(0x4B, "Accelerator pedal position F", "%", "engine", 1, _pct255),
    _p(0x4C, "Commanded throttle actuator", "%", "engine", 1, _pct255),
    _p(0x4D, "Time with MIL on", "min", "emissions", 2, _u16, 0),
    _p(0x4E, "Time since codes cleared", "min", "emissions", 2, _u16, 0),
    _p(0x51, "Fuel type", "", "fuel", 1, _u8, 0),
    _p(0x52, "Ethanol fuel", "%", "fuel", 1, _pct255),
    _p(0x53, "Absolute evaporative vapor pressure", "kPa", "emissions", 2, _u16_div200, 3),
    _p(0x54, "Evaporative vapor pressure", "Pa", "emissions", 2, _i16, 0),
    _p(0x55, "ST secondary trim B1", "%", "o2", 2, _trim),
    _p(0x56, "LT secondary trim B1", "%", "o2", 2, _trim),
    _p(0x57, "ST secondary trim B2", "%", "o2", 2, _trim),
    _p(0x58, "LT secondary trim B2", "%", "o2", 2, _trim),
    _p(0x59, "Fuel rail absolute pressure", "kPa", "fuel", 2, _rail_x10, 0),
    _p(0x5A, "Relative accelerator pedal position", "%", "engine", 1, _pct255),
    _p(0x5B, "Hybrid battery life", "%", "electrical", 1, _pct255),
    _p(0x5C, "Oil temperature", "°C", "temps", 1, _temp, 0),
    _p(0x5D, "Fuel injection timing", "°", "engine", 2, _timing, 2),
    _p(0x5E, "Engine fuel rate", "L/h", "fuel", 2, _fuel_rate, 2),
    _p(0x61, "Driver demand torque", "%", "engine", 1, _torque, 0),
    _p(0x62, "Actual engine torque", "%", "engine", 1, _torque, 0),
    _p(0x63, "Engine reference torque", "Nm", "engine", 2, _u16, 0),
    _p(0x7C, "DPF temperature", "°C", "temps", 2, _temp16),
    _p(0x8D, "Throttle position G", "%", "engine", 1, _pct255),
    _p(0x8E, "Engine friction torque", "%", "engine", 1, _torque, 0),
    _p(0xA2, "Cylinder fuel rate", "mg/stroke", "fuel", 2, _u16_div32, 3),
)

# Intentionally not registered: bit-encoded status PIDs ($12/$13/$1D/$1E/$5F),
# multi-field "max value" PIDs ($4F/$50), support-bit-gated multi-sensor PIDs
# ($66-$68, $78/$79), and PIDs without a freely available normative formula
# ($7A/$7B) — each needs support-bit gating or J1979-DA data to decode safely.

_BASE_REGISTRY: dict[int, PidDef] = {d.pid: d for d in _DEFS}

# Companion channels: some responses carry a second measurement in extra bytes
# (SAE J1979). Synthetic ids $114-$12B / $155-$158 ride along with their base
# PID's single wire request; see request_pid(). Byte B == $FF marks an O2 trim
# channel as unused (checked against _o2_stft in parse_pid_values).
_SECONDARY_TRIM_COMPANIONS: dict[int, str] = {
    0x55: "ST secondary trim B3",
    0x56: "LT secondary trim B3",
    0x57: "ST secondary trim B4",
    0x58: "LT secondary trim B4",
}


def _build_companions() -> dict[int, PidDef]:
    out: dict[int, PidDef] = {}
    for base, definition in _BASE_REGISTRY.items():
        if 0x14 <= base <= 0x1B:
            out[base + 0x100] = PidDef(
                pid=base + 0x100,
                name=f"{definition.name} STFT",
                unit="%",
                category="o2",
                data_bytes=2,
                scale=_o2_stft,
                decimals=1,
            )
        elif 0x24 <= base <= 0x2B:
            out[base + 0x100] = PidDef(
                pid=base + 0x100,
                name=f"{definition.name} voltage",
                unit="V",
                category="o2",
                data_bytes=4,
                scale=_o2_wb_volts,
                decimals=3,
            )
        elif base in _SECONDARY_TRIM_COMPANIONS:
            out[base + 0x100] = PidDef(
                pid=base + 0x100,
                name=_SECONDARY_TRIM_COMPANIONS[base],
                unit="%",
                category="o2",
                data_bytes=2,
                scale=_trim_second,
                decimals=1,
            )
    return out


COMPANION_PIDS: dict[int, PidDef] = _build_companions()

PID_REGISTRY: dict[int, PidDef] = {**_BASE_REGISTRY, **COMPANION_PIDS}

# Block-bitmap pseudo-PIDs a vehicle can report as supported.
SUPPORTED_PIDS: tuple[int, ...] = (0x00, 0x20, 0x40, 0x60, 0x80, 0xA0, 0xC0)

# Enumerated decode tables (J1979: PID $1C OBD standard, PID $51 fuel type).
OBD_STANDARD_NAMES: dict[int, str] = {
    1: "OBD-II (CARB)",
    2: "OBD (EPA)",
    3: "OBD and OBD-II",
    4: "OBD-I",
    5: "Not OBD compliant",
    6: "EOBD (Europe)",
    7: "EOBD and OBD-II",
    8: "EOBD and OBD",
    9: "EOBD, OBD and OBD II",
    10: "JOBD (Japan)",
    11: "JOBD and OBD II",
    12: "JOBD and EOBD",
    13: "JOBD, EOBD, and OBD II",
    14: "OBD, EOBD, and KOBD",
    15: "OBD, OBD II, EOBD, and KOBD",
    16: "Reserved",
    17: "Engine Manufacturer Diagnostics (EMD)",
    18: "Engine Manufacturer Diagnostics Enhanced (EMD+)",
    19: "Heavy Duty OBD Child/Partial (HD OBD-C)",
    20: "Heavy Duty OBD (HD OBD)",
    21: "World Wide Harmonized OBD (WWH OBD)",
    22: "Reserved",
    23: "HD EOBD-I",
    24: "HD EOBD-I with NOx control",
    25: "HD EOBD-II",
    26: "HD EOBD-II with NOx control",
    27: "Heavy Duty ZEV",
    28: "Brazil OBD Phase 1 (OBDBr-1)",
    29: "Brazil OBD Phase 2 (OBDBr-2)",
    30: "Korean OBD (KOBD)",
    31: "India OBD I (IOBD I)",
    32: "India OBD II (IOBD II)",
    33: "HD Euro OBD Stage VI (HD EOBD-IV)",
    34: "OBD, OBD-II, and HD OBD",
    35: "Brazil OBD Phase 3 (OBDBr-3)",
}

FUEL_TYPE_NAMES: dict[int, str] = {
    0: "Not available",
    1: "Gasoline",
    2: "Methanol",
    3: "Ethanol",
    4: "Diesel",
    5: "LPG",
    6: "CNG",
    7: "Propane",
    8: "Electric",
    9: "Bifuel (Gasoline)",
    10: "Bifuel (Methanol)",
    11: "Bifuel (Ethanol)",
    12: "Bifuel (LPG)",
    13: "Bifuel (CNG)",
    14: "Bifuel (Propane)",
    15: "Bifuel (Electricity)",
    16: "Bifuel (electric + combustion)",
    17: "Hybrid gasoline",
    18: "Hybrid ethanol",
    19: "Hybrid diesel",
    20: "Hybrid electric",
    21: "Hybrid (electric + combustion)",
    22: "Hybrid regenerative",
    23: "Bifuel (Diesel)",
}


def obd_standard_name(value: float | int) -> str:
    return OBD_STANDARD_NAMES.get(int(value), f"OBD standard {int(value)}")


def fuel_type_name(value: float | int) -> str:
    return FUEL_TYPE_NAMES.get(int(value), f"Fuel type {int(value)}")


def pid_def(pid: int) -> PidDef | None:
    return PID_REGISTRY.get(pid)


def request_pid(pid: int) -> int:
    """The PID to put on the wire (companions share their base request)."""
    return pid - 0x100 if pid in COMPANION_PIDS else pid


def describe_pid(pid: int) -> str:
    """Human label for a parameter: ``0C — Engine RPM [rpm]`` (unit optional)."""
    definition = PID_REGISTRY.get(pid)
    name = definition.name if definition else f"PID {pid:02X}"
    suffix = f" [{definition.unit}]" if definition and definition.unit else ""
    return f"{request_pid(pid):02X} — {name}{suffix}"


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


def parse_pid_values(text: str, pid: int) -> dict[int, float]:
    """Decode every channel carried by a ``01 <pid>`` response.

    Returns the base PID plus any companion channels (``pid`` must be the
    on-the-wire PID, i.e. :func:`request_pid` output). O2 STFT companions
    whose sentinel byte marks them unused (``$FF``) are omitted.
    """
    payload = framing.extract_payload(text, f"41{pid:02X}")
    if payload is None:
        return {}
    try:
        data = framing.hex_to_bytes(payload)
    except ValueError:
        return {}
    values: dict[int, float] = {}
    value = decode_pid(pid, data)
    if value is not None:
        values[pid] = value
    for companion, definition in COMPANION_PIDS.items():
        if request_pid(companion) != pid:
            continue
        try:
            if definition.scale is _o2_stft and data[1] == 0xFF:
                continue  # J1979: O2 trim channel not used in calculation
            values[companion] = definition.scale(data)
        except (IndexError, ValueError):
            continue
    return values


def parse_supported_pids(text: str, base: int = 0x00) -> tuple[set[int], bool]:
    """Decode a ``01 <base>`` supported-PID bitmap.

    Returns (supported PIDs in ``base+1 .. base+0x20``, next-block bit).
    """
    return framing.parse_supported_mask(text, f"41{base:02X}", base)
