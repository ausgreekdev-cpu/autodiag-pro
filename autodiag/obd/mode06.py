"""Mode $06 — on-board monitoring test results (MID/TID, UASID scaling).

Record layout per SAE J1979 §6.6 (9 bytes after the ``46`` SID echo):
``[OBDMID][TID][UASID][value hi/lo][min hi/lo][max hi/lo]``.
MID names: Appendix D. Unit/scaling: Appendix E.
"""

from __future__ import annotations

from dataclasses import dataclass

from autodiag.obd import framing

# -- OBDMID names (Appendix D, Table D1) --------------------------------------

def _mid_table() -> dict[int, str]:
    table: dict[int, str] = {}
    for bank in range(1, 5):
        for sensor in range(1, 5):
            offset = (bank - 1) * 4 + (sensor - 1)
            table[0x01 + offset] = f"Oxygen Sensor Monitor Bank {bank} - Sensor {sensor}"
            table[0x41 + offset] = (
                f"Oxygen Sensor Heater Monitor Bank {bank} - Sensor {sensor}"
            )
    for bank in range(1, 5):
        table[0x20 + bank] = f"Catalyst Monitor Bank {bank}"
        table[0x30 + bank] = f"EGR Monitor Bank {bank}"
        table[0x60 + bank] = f"Heated Catalyst Monitor Bank {bank}"
        table[0x80 + bank] = f"Fuel System Monitor Bank {bank}"
    table.update(
        {
            0x39: "EVAP Monitor (Cap Off)",
            0x3A: "EVAP Monitor (0.090\")",
            0x3B: "EVAP Monitor (0.040\")",
            0x3C: "EVAP Monitor (0.020\")",
            0x3D: "Purge Flow Monitor",
            0x71: "Secondary Air Monitor 1",
            0x72: "Secondary Air Monitor 2",
            0x73: "Secondary Air Monitor 3",
            0x74: "Secondary Air Monitor 4",
            0xA1: "Mis-Fire Monitor General Data",
        }
    )
    for cyl in range(1, 13):
        table[0xA1 + cyl] = f"Mis-Fire Cylinder {cyl} Data"
    return table


MID_NAMES: dict[int, str] = _mid_table()


def mid_name(mid: int) -> str:
    """Human name for an OBDMID, including range defaults (Appendix D)."""
    if mid in MID_NAMES:
        return MID_NAMES[mid]
    if mid in (0x00, 0x20, 0x40, 0x60, 0x80, 0xA0, 0xC0, 0xE0):
        nxt = mid + 0x20
        return f"OBD Monitor IDs supported (${mid + 1:02X} - ${min(nxt, 0xFF):02X})"
    if 0x11 <= mid <= 0x1F or 0x25 <= mid <= 0x30 or 0x35 <= mid <= 0x38:
        return "Reserved"
    if 0xE1 <= mid <= 0xFF:
        return "Vehicle manufacturer defined"
    return f"Monitor ${mid:02X}"


# -- Unit And Scaling IDs (Appendix E) ---------------------------------------
# id: (factor, offset, unit, signed)

UASIDS: dict[int, tuple[float, float, str, bool]] = {
    0x01: (1.0, 0.0, "", False),
    0x02: (0.1, 0.0, "", False),
    0x03: (0.01, 0.0, "", False),
    0x04: (0.001, 0.0, "", False),
    0x05: (0.0000305, 0.0, "", False),
    0x06: (0.0000305, 0.0, "", False),
    0x07: (0.25, 0.0, "rpm", False),
    0x08: (0.01, 0.0, "km/h", False),
    0x09: (1.0, 0.0, "km/h", False),
    0x0A: (0.000122, 0.0, "V", False),
    0x0B: (0.001, 0.0, "V", False),
    0x0C: (0.01, 0.0, "V", False),
    0x0E: (0.001, 0.0, "A", False),
    0x0F: (0.01, 0.0, "A", False),
    0x10: (0.001, 0.0, "s", False),
    0x11: (0.1, 0.0, "s", False),
    0x12: (1.0, 0.0, "s", False),
    0x13: (0.001, 0.0, "Ω", False),
    0x14: (1.0, 0.0, "Ω", False),
    0x15: (1000.0, 0.0, "Ω", False),
    0x16: (0.1, -40.0, "°C", False),
    0x17: (0.01, 0.0, "kPa", False),
    0x18: (0.0117, 0.0, "kPa", False),
    0x19: (0.079, 0.0, "kPa", False),
    0x1A: (1.0, 0.0, "kPa", False),
    0x1B: (10.0, 0.0, "kPa", False),
    0x1C: (0.01, 0.0, "°", False),
    0x1D: (0.5, 0.0, "°", False),
    0x1F: (0.05, 0.0, "A/F", False),
    0x20: (0.0039062, 0.0, "", False),
    0x21: (0.001, 0.0, "Hz", False),
    0x22: (1.0, 0.0, "Hz", False),
    0x23: (1000.0, 0.0, "Hz", False),
    0x24: (1.0, 0.0, "counts", False),
    0x25: (1.0, 0.0, "km", False),
    0x27: (0.01, 0.0, "g/s", False),
    0x28: (1.0, 0.0, "g/s", False),
    0x2A: (0.001, 0.0, "kg/h", False),
    0x2B: (1.0, 0.0, "switches", False),
    0x2C: (0.01, 0.0, "g/cyl", False),
    0x2E: (1.0, 0.0, "", False),  # true/false
    0x2F: (0.01, 0.0, "%", False),
    0x30: (0.001526, 0.0, "%", False),
    0x31: (0.001, 0.0, "L", False),
    # signed range
    0x81: (1.0, 0.0, "", True),
    0x82: (0.1, 0.0, "", True),
    0x83: (0.01, 0.0, "", True),
    0x84: (0.001, 0.0, "", True),
    0x85: (0.0000305, 0.0, "", True),
    0x86: (0.000305, 0.0, "", True),
    0x8A: (0.000122, 0.0, "V", True),
    0x8B: (0.001, 0.0, "V", True),
    0x8C: (0.01, 0.0, "V", True),
    0x8E: (0.001, 0.0, "A", True),
    0x90: (0.001, 0.0, "s", True),
    0x96: (0.1, -40.0, "°C", True),
    0x9C: (0.01, 0.0, "°", True),
    0x9D: (0.5, 0.0, "°", True),
    0xA8: (1.0, 0.0, "g/s", True),
    0xAF: (0.01, 0.0, "%", True),
    0xB0: (0.003052, 0.0, "%", True),
    0xFD: (0.001, 0.0, "kPa", True),
    0xFE: (0.25, 0.0, "Pa", True),
}


def scale_value(uasid: int, raw: int) -> float:
    """Apply the Appendix E scaling for ``uasid`` to a 16-bit raw value."""
    factor, offset, _unit, signed = UASIDS.get(uasid, (1.0, 0.0, "", False))
    value = raw - 0x10000 if (signed and raw & 0x8000) else raw
    return value * factor + offset


def uasid_unit(uasid: int) -> str:
    return UASIDS.get(uasid, (1.0, 0.0, "", False))[2]


@dataclass(frozen=True)
class TestResult:
    mid: int
    tid: int
    uasid: int
    raw_value: int
    raw_min: int
    raw_max: int
    value: float
    min_value: float
    max_value: float
    unit: str

    @property
    def monitor_name(self) -> str:
        return mid_name(self.mid)

    @property
    def passed(self) -> bool | None:
        """Pass/fail vs limits; ``None`` when the monitor never completed
        (J1979 zeroes value and limits until the test has run once)."""
        if self.raw_value == 0 and self.raw_min == 0 and self.raw_max == 0:
            return None
        return self.min_value <= self.value <= self.max_value


def parse_supported_mids(text: str, base: int = 0x00) -> tuple[set[int], bool]:
    """Decode a ``06 <base>`` supported-OBDMID bitmap (same layout as PIDs)."""
    return framing.parse_supported_mask(text, f"46{base:02X}", base)


def parse_test_results(text: str) -> list[TestResult]:
    """Decode a cleaned ``06 <mid>`` response into test-result records."""
    flat = framing.flatten_response(text)
    idx = flat.find("46")
    if idx < 0:
        return []
    try:
        data = framing.hex_to_bytes(flat[idx + 2:])
    except ValueError:
        return []

    record_len = 9
    if len(data) >= 9 and len(data) % 9 == 0:
        pass
    elif len(data) >= 8 and len(data) % 8 == 0:
        record_len = 8  # pre-CAN variant without UASID: raw, unscaled
    else:
        return []

    results: list[TestResult] = []
    for i in range(0, len(data), record_len):
        record = data[i:i + record_len]
        mid, tid = record[0], record[1]
        uasid = record[2] if record_len == 9 else 0
        off = 3 if record_len == 9 else 2
        raw_value = (record[off] << 8) | record[off + 1]
        raw_min = (record[off + 2] << 8) | record[off + 3]
        raw_max = (record[off + 4] << 8) | record[off + 5]
        results.append(
            TestResult(
                mid=mid,
                tid=tid,
                uasid=uasid,
                raw_value=raw_value,
                raw_min=raw_min,
                raw_max=raw_max,
                value=scale_value(uasid, raw_value),
                min_value=scale_value(uasid, raw_min),
                max_value=scale_value(uasid, raw_max),
                unit=uasid_unit(uasid),
            )
        )
    return results
