"""Reader for LiveLog CSV files: parse back into per-PID series."""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

_REQUIRED = ("timestamp", "elapsed_s", "pid", "name", "unit", "value")


@dataclass
class LogSeries:
    pid: int
    name: str
    unit: str
    xs: list[float] = field(default_factory=list)  # elapsed seconds
    ys: list[float] = field(default_factory=list)  # values


@dataclass
class LogData:
    series: dict[int, LogSeries] = field(default_factory=dict)  # first-seen order
    rows: int = 0
    skipped: int = 0
    started_at: str | None = None


def read_log(path: str | Path) -> LogData:
    """Parse one ``log-*.csv`` file.

    Raises ``ValueError`` for empty/foreign files and ``OSError`` when the
    file cannot be read — callers surface either in the status bar.
    """
    data = LogData()
    with Path(path).open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        header = reader.fieldnames
        if not header:
            raise ValueError("empty log")
        missing = [name for name in _REQUIRED if name not in header]
        if missing:
            raise ValueError("not an AutoDiag log (missing columns)")
        for row in reader:
            try:
                elapsed = float(row["elapsed_s"])
                value = float(row["value"])
                pid = int(row["pid"], 16)
            except (TypeError, ValueError):
                data.skipped += 1
                continue
            series = data.series.get(pid)
            if series is None:
                series = LogSeries(
                    pid=pid,
                    name=str(row.get("name") or f"PID {pid:02X}"),
                    unit=str(row.get("unit") or ""),
                )
                data.series[pid] = series
            series.xs.append(elapsed)
            series.ys.append(value)
            data.rows += 1
            if data.started_at is None:
                data.started_at = str(row.get("timestamp") or "") or None
    if not data.series and data.rows == 0 and data.skipped == 0:
        raise ValueError("empty log")
    return data
