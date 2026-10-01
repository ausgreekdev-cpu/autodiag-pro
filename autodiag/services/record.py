"""Accumulated scan results (fed by worker signals) for reports/export."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from autodiag.obd.elm327 import SessionInfo
from autodiag.obd.readiness import MonitorStatus


@dataclass
class ScanRecord:
    """Everything the app has learned about the vehicle this session."""

    session: SessionInfo | None = None
    vin: str | None = None
    cal_ids: list[str] = field(default_factory=list)
    cvns: list[str] = field(default_factory=list)
    monitors: MonitorStatus | None = None
    dtcs: dict[str, list[str]] = field(default_factory=dict)  # source → codes
    freeze: dict[int, float] = field(default_factory=dict)  # pid → value
    mode06: list[object] = field(default_factory=list)  # mode06.TestResult
    pids: dict[int, tuple[float, float]] = field(default_factory=dict)  # pid → (v, t)
    updated_at: datetime | None = None

    def record_event(self, kind: str, args: tuple) -> None:
        """Absorb one worker event (same dispatch the UI uses)."""
        now = datetime.now(UTC)
        if kind == "connected":
            self.session = args[0]
        elif kind == "disconnected":
            self.session = None
        elif kind == "pid_value":
            pid, value, timestamp = args
            self.pids[pid] = (value, timestamp)
        elif kind == "dtcs":
            source, codes = args
            self.dtcs[source] = list(codes)
        elif kind == "monitors":
            self.monitors = args[0]
        elif kind == "vehicle":
            info = args[0]
            self.vin = info.get("vin")
            self.cal_ids = list(info.get("cal_ids") or [])
            self.cvns = list(info.get("cvns") or [])
        elif kind == "freeze_all":
            self.freeze = dict(args[0])
        elif kind == "mode06":
            self.mode06 = list(args[0])
        else:
            return
        self.updated_at = now

    def reset(self) -> None:
        self.__dict__.update(
            ScanRecord().__dict__
        )
