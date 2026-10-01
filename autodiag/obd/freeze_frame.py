"""Mode $02 freeze-frame data — the sensor snapshot taken when a DTC set."""

from __future__ import annotations

from dataclasses import dataclass

from autodiag.obd import framing
from autodiag.obd.pids import PID_REGISTRY, decode_pid


@dataclass(frozen=True)
class FreezeFrame:
    pid: int
    frame: int
    value: float

    @property
    def name(self) -> str:
        definition = PID_REGISTRY.get(self.pid)
        return definition.name if definition else f"PID {self.pid:02X}"

    @property
    def unit(self) -> str:
        definition = PID_REGISTRY.get(self.pid)
        return definition.unit if definition else ""


def parse_freeze_frame(text: str, pid: int, frame: int = 0) -> FreezeFrame | None:
    """Decode a cleaned ``02 <pid> <frame>`` response.

    Response layout: ``42 <pid> <frame#> <data...>`` (frame byte is optional
    in legacy responses — its presence is decided by payload length).
    """
    payload = framing.extract_payload(text, f"42{pid:02X}")
    if payload is None:
        return None
    try:
        data = framing.hex_to_bytes(payload)
    except ValueError:
        return None

    definition = PID_REGISTRY.get(pid)
    expected = definition.data_bytes if definition else 0
    if expected and len(data) > expected:
        # Drop the frame-number byte (present per spec / some ECUs).
        data = data[1:] if (data and data[0] == frame) else data
    value = decode_pid(pid, data)
    if value is None:
        return None
    return FreezeFrame(pid=pid, frame=frame, value=value)
