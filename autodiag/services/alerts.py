"""Threshold watchlist: breach detection + timestamped alert events.

Pure Python (no Qt). Evaluation is transition-based: an event fires when a
reading moves from inside to outside its bounds, clears when it returns, and
re-arms for the next excursion — one event per excursion instead of one per
poll tick. Bounds are inclusive (value exactly on a limit counts as inside).
"""

from __future__ import annotations

import csv
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from autodiag.obd.pids import PID_REGISTRY, describe_pid

MAX_EVENTS = 200


@dataclass(frozen=True)
class Threshold:
    pid: int
    low: float | None = None
    high: float | None = None

    def contains(self, value: float) -> bool:
        if self.low is not None and value < self.low:
            return False
        if self.high is not None and value > self.high:
            return False
        return True


@dataclass(frozen=True)
class AlertEvent:
    pid: int
    value: float
    kind: str  # "breach" | "clear"
    limit: float | None  # bound crossed (None on clear)
    direction: str  # "low" | "high" ("" on clear)
    at: datetime  # wall clock when the event fired (local time)
    timestamp: float  # engine monotonic seconds (for log correlation)


class Watchlist:
    """pid → Threshold with per-pid breach state."""

    def __init__(self, thresholds: dict[int, Threshold] | None = None) -> None:
        self._thresholds: dict[int, Threshold] = dict(thresholds or {})
        self._breaching: set[int] = set()

    # -- registry ---------------------------------------------------------------

    def thresholds(self) -> list[Threshold]:
        return [self._thresholds[pid] for pid in sorted(self._thresholds)]

    def get(self, pid: int) -> Threshold | None:
        return self._thresholds.get(pid)

    def set(self, threshold: Threshold) -> None:
        self._thresholds[threshold.pid] = threshold
        # Stale breach state self-heals on the next evaluate() (a "clear" fires
        # if the new bounds contain the current reading).
        if threshold.low is None and threshold.high is None:
            self.remove(threshold.pid)

    def remove(self, pid: int) -> None:
        self._thresholds.pop(pid, None)
        self._breaching.discard(pid)

    @property
    def breaching(self) -> frozenset[int]:
        return frozenset(self._breaching)

    # -- persistence round-trip (see Prefs.watchlist) ---------------------------

    def as_dict(self) -> dict[int, tuple[float | None, float | None]]:
        return {pid: (t.low, t.high) for pid, t in sorted(self._thresholds.items())}

    # -- evaluation -------------------------------------------------------------

    def evaluate(self, pid: int, value: float, timestamp: float) -> AlertEvent | None:
        """Fold one reading in; return the transition it caused, if any."""
        threshold = self._thresholds.get(pid)
        if threshold is None:
            return None
        if threshold.contains(value):
            if pid in self._breaching:
                self._breaching.discard(pid)
                return AlertEvent(pid, value, "clear", None, "", datetime.now(), timestamp)
            return None
        if pid in self._breaching:
            return None  # still inside the same excursion
        self._breaching.add(pid)
        if threshold.high is not None and value > threshold.high:
            limit, direction = threshold.high, "high"
        else:
            limit, direction = threshold.low, "low"
        return AlertEvent(pid, value, "breach", limit, direction, datetime.now(), timestamp)


class AlertLog:
    """Breach event history (newest first, capped) + callback fan-out."""

    def __init__(
        self,
        watchlist: Watchlist,
        on_event: Callable[[AlertEvent], None] | None = None,
    ) -> None:
        self.watchlist = watchlist
        self._on_event = on_event
        self.events: list[AlertEvent] = []  # breaches only, newest first

    def evaluate(self, pid: int, value: float, timestamp: float) -> AlertEvent | None:
        event = self.watchlist.evaluate(pid, value, timestamp)
        if event is None:
            return None
        if event.kind == "breach":
            self.events.insert(0, event)
            del self.events[MAX_EVENTS:]
        if self._on_event is not None:
            self._on_event(event)
        return event

    def clear(self) -> None:
        self.events.clear()

    def export_csv(self, path: str | Path) -> Path:
        target = Path(path)
        if target.suffix == "":
            target = target.with_suffix(".csv")
        with target.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(("time", "pid", "parameter", "value", "limit", "direction"))
            for event in reversed(self.events):  # oldest first in the file
                definition = PID_REGISTRY.get(event.pid)
                decimals = definition.decimals if definition else 1
                writer.writerow(
                    (
                        event.at.strftime("%H:%M:%S"),
                        f"{event.pid:02X}",
                        describe_pid(event.pid),
                        f"{event.value:.{decimals}f}",
                        f"{event.limit:.{decimals}f}" if event.limit is not None else "",
                        event.direction,
                    )
                )
        return target
