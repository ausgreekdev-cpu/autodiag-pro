"""Mode $01 PID $01 — MIL status, DTC count, readiness monitors.

Bit layout per SAE J1979 Appendix B, Table B2/B3:
  byte A: bit 7 = MIL, bits 6-0 = DTC count
  byte B: low nibble = continuous monitor support (misfire/fuel/CCM),
          high nibble = completion since DTCs cleared (1 = NOT complete)
  byte C: non-continuous monitor support   byte D: their completion
"""

from __future__ import annotations

from dataclasses import dataclass

from autodiag.obd import framing

_CONTINUOUS = (
    ("misfire", "Misfire", 0, 4),
    ("fuel", "Fuel system", 1, 5),
    ("ccm", "Comprehensive components", 2, 6),
)

_NON_CONTINUOUS = (
    ("cat", "Catalyst", 0),
    ("hcat", "Heated catalyst", 1),
    ("evap", "Evaporative system", 2),
    ("air", "Secondary air system", 3),
    ("acrf", "A/C refrigerant", 4),
    ("o2s", "Oxygen sensor", 5),
    ("htr", "Oxygen sensor heater", 6),
    ("egr", "EGR system", 7),
)


@dataclass(frozen=True)
class Monitor:
    key: str
    name: str
    supported: bool
    complete: bool
    continuous: bool


@dataclass(frozen=True)
class MonitorStatus:
    mil_on: bool
    dtc_count: int
    monitors: tuple[Monitor, ...]

    def monitor(self, key: str) -> Monitor:
        for m in self.monitors:
            if m.key == key:
                return m
        raise KeyError(key)

    @property
    def ready(self) -> bool:
        """True when every supported monitor has completed (smog-test ready)."""
        return all(m.complete for m in self.monitors if m.supported)


def parse_monitor_status(text: str) -> MonitorStatus | None:
    """Decode a cleaned ``0101`` response; ``None`` if malformed."""
    payload = framing.extract_payload(text, "4101")
    if payload is None:
        return None
    try:
        data = framing.hex_to_bytes(payload)
    except ValueError:
        return None
    if len(data) < 4:
        return None

    a, b, c, d = data[0], data[1], data[2], data[3]
    mil_on = bool(a & 0x80)
    dtc_count = a & 0x7F

    monitors: list[Monitor] = []
    for key, name, sup_bit, rdy_bit in _CONTINUOUS:
        monitors.append(
            Monitor(
                key=key,
                name=name,
                supported=bool(b & (1 << sup_bit)),
                complete=not bool(b & (1 << rdy_bit)),
                continuous=True,
            )
        )
    for key, name, bit in _NON_CONTINUOUS:
        monitors.append(
            Monitor(
                key=key,
                name=name,
                supported=bool(c & (1 << bit)),
                complete=not bool(d & (1 << bit)),
                continuous=False,
            )
        )
    return MonitorStatus(mil_on=mil_on, dtc_count=dtc_count, monitors=tuple(monitors))
