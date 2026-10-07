"""Mode $05 — oxygen sensor monitoring test results (non-CAN buses).

Message format per SAE J1979:2002 §5.5 (Appendix C "only applies to
ISO 9141-2, SAE J1850, and ISO 14230-4"; §6.5 moves this functionality
into service $06 on CAN). Request: ``05 <TID> <O2SNO>``. Response:
``45 <TID> <O2SNO> <TestValue> [Minimum Limit Maximum Limit]`` — the
limit bytes are omitted for the constant Test IDs $01–$04 (TABLE 58),
so record length is 4 bytes for those and 6 bytes otherwise.

Scaling: Appendix C TABLE C1 — constants $01–$04 and calculated
voltages at 0.005 V/bit, switch times $05/$06 at 0.004 s/bit,
transitions/period $09/$0A at 0.04 s/bit, manufacturer ranges $21–$7F
each with a fixed unit, $81+ manufacturer-specific (raw display).
Test ID $00 ($20, ...) carries the supported-TID bitmap, the same
concept as PID support in Appendix A.

O2 Sensor # is a single-bit location mask as defined by PID $13 or
$1D (§5.5.3.3, TABLE 59 / Appendix B) — a vehicle supports one of the
two PIDs, never both.

Tables verified against the CFR-incorporated SAE J1979-2002 text
(Appendix C read directly) and cross-checked against an independent
encoding of the same facts. The spec's message examples pin the
scaling: ``4501015A`` = 450 mV and ``450501120019`` = 72 ms within
0–100 ms.
"""

from __future__ import annotations

from dataclasses import dataclass

from autodiag.obd import framing

# Test IDs whose responses omit the conditional min/max limit bytes
# (TABLE 58: "if the supported Test ID is a constant ($01 - $04) ...").
CONSTANT_TIDS = frozenset({0x01, 0x02, 0x03, 0x04})

# Standardized Test IDs (Appendix C TABLE C1).
TID_NAMES: dict[int, str] = {
    0x01: "Rich-to-lean sensor threshold voltage (constant)",
    0x02: "Lean-to-rich sensor threshold voltage (constant)",
    0x03: "Low sensor voltage for switch-time calculation (constant)",
    0x04: "High sensor voltage for switch-time calculation (constant)",
    0x05: "Rich-to-lean sensor switch time (calculated)",
    0x06: "Lean-to-rich sensor switch time (calculated)",
    0x07: "Minimum sensor voltage for test cycle (calculated)",
    0x08: "Maximum sensor voltage for test cycle (calculated)",
    0x09: "Time between sensor transitions (calculated)",
    0x0A: "Sensor period (calculated)",
}

# Fixed scaling by TID / manufacturer range (Appendix C TABLE C1).
# (factor, offset, unit) — $81+ and unknown TIDs stay raw.
_TID_SCALING: dict[int, tuple[float, float, str]] = {}
for _tid in (0x01, 0x02, 0x03, 0x04, 0x07, 0x08):
    _TID_SCALING[_tid] = (0.005, 0.0, "V")
for _tid in (0x05, 0x06):
    _TID_SCALING[_tid] = (0.004, 0.0, "s")
for _tid in (0x09, 0x0A):
    _TID_SCALING[_tid] = (0.04, 0.0, "s")
for _lo, _hi, _scale in (
    (0x21, 0x2F, (0.004, 0.0, "s")),
    (0x30, 0x3F, (0.04, 0.0, "s")),
    (0x41, 0x4F, (0.005, 0.0, "V")),
    (0x50, 0x5F, (0.05, 0.0, "V")),
    (0x61, 0x6F, (0.1, 0.0, "Hz")),
    (0x70, 0x7F, (1.0, 0.0, "count")),
):
    for _tid in range(_lo, _hi + 1):
        _TID_SCALING[_tid] = _scale
del _tid, _lo, _hi, _scale

# O2 sensor location masks: TABLE 59 — PID $13 layout (B1S1..B2S4) and
# the PID $1D alternative (B1S1, B1S2, B2S1, B2S2, B3S1..B4S2).
_SENSOR_NAMES_13: dict[int, str] = {
    0x01: "Bank 1 - Sensor 1",
    0x02: "Bank 1 - Sensor 2",
    0x04: "Bank 1 - Sensor 3",
    0x08: "Bank 1 - Sensor 4",
    0x10: "Bank 2 - Sensor 1",
    0x20: "Bank 2 - Sensor 2",
    0x40: "Bank 2 - Sensor 3",
    0x80: "Bank 2 - Sensor 4",
}
_SENSOR_NAMES_1D: dict[int, str] = {
    0x01: "Bank 1 - Sensor 1",
    0x02: "Bank 1 - Sensor 2",
    0x04: "Bank 2 - Sensor 1",
    0x08: "Bank 2 - Sensor 2",
    0x10: "Bank 3 - Sensor 1",
    0x20: "Bank 3 - Sensor 2",
    0x40: "Bank 4 - Sensor 1",
    0x80: "Bank 4 - Sensor 2",
}


def tid_name(tid: int) -> str:
    """Human name for a Test ID (Appendix C, plus bitmap/reserved ranges)."""
    if tid in TID_NAMES:
        return TID_NAMES[tid]
    if tid in (0x00, 0x20, 0x40, 0x60, 0x80, 0xA0, 0xC0, 0xE0):
        upper = min(tid + 0x20, 0xFF)
        return f"Supported TIDs (${tid + 1:02X} - ${upper:02X})"
    if 0x0B <= tid <= 0x1F:
        return "Reserved"
    if tid >= 0x81:
        return f"Manufacturer-defined test ${tid:02X}"
    return f"Manufacturer test ${tid:02X}"


def scaling(tid: int) -> tuple[float, float, str]:
    """``(factor, offset, unit)`` for a Test ID; raw display when unknown."""
    return _TID_SCALING.get(tid, (1.0, 0.0, ""))


def sensor_masks(pid_byte: int, *, via_pid_1d: bool = False) -> list[int]:
    """O2SNO masks for each set bit of a PID $13 / $1D location byte."""
    table = _SENSOR_NAMES_1D if via_pid_1d else _SENSOR_NAMES_13
    return [mask for mask in table if pid_byte & mask]


def sensor_name(mask: int, *, via_pid_1d: bool = False) -> str:
    table = _SENSOR_NAMES_1D if via_pid_1d else _SENSOR_NAMES_13
    return table.get(mask, f"O2 sensor ${mask:02X}")


@dataclass(frozen=True)
class TestResult:
    tid: int
    sensor: int  # O2SNO single-bit location mask
    raw_value: int
    raw_min: int | None  # None when the response omits limits
    raw_max: int | None
    value: float
    min_value: float | None
    max_value: float | None
    unit: str
    via_pid_1d: bool = False  # location-byte layout used for sensor_label

    @property
    def test_name(self) -> str:
        return tid_name(self.tid)

    @property
    def sensor_label(self) -> str:
        return sensor_name(self.sensor, via_pid_1d=self.via_pid_1d)

    @property
    def passed(self) -> bool | None:
        """Pass/fail vs limits; ``None`` without limits (constant TIDs) or
        when the test never completed (all-zero value and limits)."""
        if self.min_value is None or self.max_value is None:
            return None
        if self.raw_value == 0 and self.raw_min == 0 and self.raw_max == 0:
            return None
        return self.min_value <= self.value <= self.max_value


def parse_supported_tids(text: str, base: int, sensor: int) -> tuple[set[int], bool]:
    """Decode a ``05 <base> <O2SNO>`` supported-TID bitmap (Appendix A)."""
    prefix = f"45{base:02X}{sensor:02X}"
    return framing.parse_supported_mask(text, prefix, base)


def parse_tid_values(
    text: str, tid: int, sensor: int, *, via_pid_1d: bool = False
) -> list[TestResult]:
    """Decode a cleaned ``05 <tid> <O2SNO>`` response into results.

    One record per responding ECU; constants ($01–$04) carry value only.
    """
    flat = framing.flatten_response(text)
    prefix = f"45{tid:02X}{sensor:02X}"
    record = 4 if tid in CONSTANT_TIDS else 6
    value_bytes = record - 3  # payload after SID+TID+O2SNO
    factor, offset, unit = scaling(tid)

    results: list[TestResult] = []
    start = 0
    while True:
        idx = flat.find(prefix, start)
        if idx < 0:
            break
        start = idx + len(prefix)
        chunk = flat[start : start + value_bytes * 2]
        if len(chunk) < value_bytes * 2:
            break  # trailing fragment: not a complete record
        try:
            data = framing.hex_to_bytes(chunk)
        except ValueError:
            break
        raw_value = data[0]
        if value_bytes == 3:  # calculated TIDs: value + min + max
            raw_min, raw_max = data[1], data[2]
            results.append(
                TestResult(
                    tid=tid,
                    sensor=sensor,
                    raw_value=raw_value,
                    raw_min=raw_min,
                    raw_max=raw_max,
                    value=raw_value * factor + offset,
                    min_value=raw_min * factor + offset,
                    max_value=raw_max * factor + offset,
                    unit=unit,
                    via_pid_1d=via_pid_1d,
                )
            )
        else:
            results.append(
                TestResult(
                    tid=tid,
                    sensor=sensor,
                    raw_value=raw_value,
                    raw_min=None,
                    raw_max=None,
                    value=raw_value * factor + offset,
                    min_value=None,
                    max_value=None,
                    unit=unit,
                    via_pid_1d=via_pid_1d,
                )
            )
    return results
