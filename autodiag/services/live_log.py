"""Time-series CSV logger for polled live data (one file per app run)."""

from __future__ import annotations

import csv
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from autodiag.obd.pids import PID_REGISTRY

KEEP = 50
_FLUSH_EVERY = 20
_HEADER = ("timestamp", "elapsed_s", "pid", "name", "unit", "value")


class LiveLog:
    """Appends every polled sample to a CSV; never lets I/O break polling.

    Armed semantics: while disarmed no file is touched at all. Arming starts
    a fresh file (named from the first sample's wall-clock time); disarming
    flushes and closes but keeps ``path``/``row_count`` for display.
    """

    def __init__(
        self,
        directory: str | Path,
        *,
        flush_every: int = _FLUSH_EVERY,
        on_change: Callable[[Path | None, int], None] | None = None,
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        self._directory = Path(directory)
        self._flush_every = max(flush_every, 1)
        self.on_change = on_change
        self.on_error = on_error
        self._armed = False
        self._disabled = False
        self._path: Path | None = None
        self._file = None
        self._writer = None
        self._rows = 0
        self._since_flush = 0
        self._first_ts: float | None = None

    # -- state -----------------------------------------------------------------

    @property
    def armed(self) -> bool:
        return self._armed

    @property
    def path(self) -> Path | None:
        return self._path

    @property
    def row_count(self) -> int:
        return self._rows

    # -- control ---------------------------------------------------------------

    def set_armed(self, armed: bool) -> None:
        if armed == self._armed:
            return
        self._armed = armed
        if armed:
            self._path = None
            self._rows = 0
            self._since_flush = 0
            self._first_ts = None
            self._disabled = False
        else:
            self.close()

    def close(self) -> None:
        """Flush and close the current file (properties are retained)."""
        if self._file is not None:
            try:
                self._file.flush()
                self._file.close()
            except OSError:
                pass  # closing must never raise
        self._file = None
        self._writer = None
        self._since_flush = 0

    # -- writing ---------------------------------------------------------------

    def add(self, pid: int, value: float, timestamp: float) -> None:
        """Append one sample; no-ops when disarmed or error-disabled."""
        if not self._armed or self._disabled:
            return
        try:
            if self._writer is None:
                self._open()
            wall = datetime.now(UTC).isoformat(timespec="milliseconds")
            elapsed = 0.0 if self._first_ts is None else timestamp - self._first_ts
            if self._first_ts is None:
                self._first_ts = timestamp
            definition = PID_REGISTRY.get(pid)
            self._writer.writerow(
                (
                    wall,
                    f"{elapsed:.3f}",
                    f"{pid:02X}",
                    definition.name if definition else f"PID {pid:02X}",
                    definition.unit if definition else "",
                    str(value),
                )
            )
            self._rows += 1
            self._since_flush += 1
            if self._since_flush >= self._flush_every:
                self._file.flush()
                self._since_flush = 0
        except OSError as exc:
            self._fail(exc)
            return
        if self.on_change is not None:
            self.on_change(self._path, self._rows)

    # -- internals -------------------------------------------------------------

    def _open(self) -> None:
        self._directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        target = self._directory / f"log-{stamp}.csv"
        suffix = 1
        while target.exists():
            target = self._directory / f"log-{stamp}-{suffix}.csv"
            suffix += 1
        self._file = target.open("a", encoding="utf-8", newline="")
        self._writer = csv.writer(self._file, lineterminator="\n")
        if target.stat().st_size == 0:
            self._writer.writerow(_HEADER)
        self._path = target
        self._since_flush = 0
        self._prune()

    def _prune(self) -> None:
        try:
            files = sorted(
                self._directory.glob("log-*.csv"), reverse=True
            )
        except OSError:
            return
        for path in files[KEEP:]:
            try:
                path.unlink()
            except OSError:
                pass  # a locked/missing file must not fail the open

    def _fail(self, exc: OSError) -> None:
        self._disabled = True
        self.close()
        if self.on_error is not None:
            self.on_error(f"Live log disabled: {exc}")
