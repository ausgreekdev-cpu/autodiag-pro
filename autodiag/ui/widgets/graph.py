"""Scrolling live graph (pyqtgraph) for selected PIDs.

Cost model: samples land in fixed-capacity numpy columns (O(1) append, no
Python-object churn) and are drawn at most once per event-loop turn, so a
poll burst that delivers six PIDs costs one redraw rather than six. Only the
visible time slice is handed to pyqtgraph, so redraw cost is bounded by the
chart window — not by how long the session has been running.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

import numpy as np
import pyqtgraph as pg
from pyqtgraph.exporters import ImageExporter
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QVBoxLayout, QWidget

from autodiag.obd.pids import PID_REGISTRY
from autodiag.ui import theme

_BUFFER = 2400  # points per series (10 min at the default 4 req/s)


class _Series:
    """One x (or y) column: contiguous oldest→newest float64 storage.

    Bounded columns keep the newest ``capacity`` samples with an amortised
    O(1) append (a compaction every ``capacity`` points), so the hot path
    never copies the whole history. Unbounded columns back static loads.
    """

    __slots__ = ("_cap", "_data", "_start", "_end")

    def __init__(self, capacity: int | None) -> None:
        self._cap = capacity
        self._data = np.empty(capacity * 2 if capacity else 1024, dtype=np.float64)
        self._start = self._end = 0

    @classmethod
    def from_values(cls, values: Sequence[float]) -> _Series:
        series = cls(None)
        series._data = np.asarray(values, dtype=np.float64).copy()
        series._end = len(series._data)
        return series

    def append(self, value: float) -> None:
        if self._end == self._data.size:
            if self._cap is None:  # static/unbounded: grow in place
                grown = np.empty(max(self._data.size * 2, 8), dtype=np.float64)
                grown[: self._end - self._start] = self._data[self._start : self._end]
                self._end -= self._start
                self._start = 0
                self._data = grown
            else:  # ring: keep the last `capacity` points at the front
                keep = self._data[self._end - self._cap : self._end].copy()
                self._data[: self._cap] = keep
                self._start, self._end = 0, self._cap
        self._data[self._end] = value
        self._end += 1
        if self._cap is not None and self._end - self._start > self._cap:
            self._start += 1

    def __len__(self) -> int:
        return self._end - self._start

    def view(self) -> np.ndarray:
        """Contiguous view (oldest first) — no copy."""
        return self._data[self._start : self._end]

    def first(self) -> float:
        return float(self._data[self._start])

    def last(self) -> float:
        return float(self._data[self._end - 1])

    def clear(self) -> None:
        self._start = self._end = 0


class LiveGraph(QWidget):
    """Time-series strip chart; only *active* PIDs are recorded."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._plot = pg.PlotWidget()
        self._plot.showGrid(x=True, y=True, alpha=0.15)
        self._plot.setLabel("bottom", "Time", units="s")
        self._plot.addLegend(offset=(10, 10))
        self._plot.getPlotItem().setMenuEnabled(False)
        # ranges are managed explicitly: time window + visible-only y scale
        self._plot.disableAutoRange()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._plot)

        self._t0: float | None = None
        self._xs: dict[int, _Series] = {}
        self._ys: dict[int, _Series] = {}
        self._curves: dict[int, pg.PlotDataItem] = {}
        self._window: float | None = None
        self._paused = False
        self._dirty = False
        # A burst of pid_value signals (one poll = up to six samples) renders
        # once, on the next event-loop turn, instead of once per sample.
        self._redraw = QTimer(self)
        self._redraw.setSingleShot(True)
        self._redraw.setInterval(0)
        self._redraw.timeout.connect(self.flush)

    @property
    def plot_widget(self) -> pg.PlotWidget:
        """The underlying pyqtgraph widget (cursor overlays, custom axes)."""
        return self._plot

    @property
    def window(self) -> float | None:
        """Visible time window in seconds (``None`` = whole buffer)."""
        return self._window

    def set_window(self, seconds: float | None) -> None:
        """Show only the last ``seconds`` of data (None = everything)."""
        self._window = seconds
        self._render_all()  # re-slice every series to the new window

    @property
    def paused(self) -> bool:
        return self._paused

    def set_paused(self, paused: bool) -> None:
        """Freeze rendering (points keep recording); resume catches up now."""
        if self._paused == paused:
            return
        if paused:
            self.flush()  # freeze what is on screen, not one redraw behind
        self._paused = paused
        if not paused:
            self._render_all()

    # -- API ------------------------------------------------------------------

    def set_active(self, pids: Iterable[int]) -> None:
        """Replace the plotted series (selection changed → history resets)."""
        self._redraw.stop()
        self._dirty = False
        for curve in self._curves.values():
            self._plot.removeItem(curve)
        self._curves.clear()
        self._xs.clear()
        self._ys.clear()
        self._t0 = None

        for index, pid in enumerate(pids):
            color = theme.SERIES_COLORS[index % len(theme.SERIES_COLORS)]
            definition = PID_REGISTRY.get(pid)
            curve = pg.PlotDataItem(
                pen=pg.mkPen(color, width=2), name=_series_label(pid, definition)
            )
            self._plot.addItem(curve)
            self._curves[pid] = curve
            self._xs[pid] = _Series(_BUFFER)
            self._ys[pid] = _Series(_BUFFER)

    def active_pids(self) -> list[int]:
        return list(self._curves)

    def set_series(
        self, series: Mapping[int, tuple[Sequence[float], Sequence[float], str]]
    ) -> None:
        """Bulk-load static data (log viewer): pid → (xs, ys, legend label).

        Unlike :meth:`set_active` + :meth:`add_point` this replaces
        everything in one shot and does not ring-buffer — plotting a saved
        file must show every point.
        """
        self.set_active([])
        for index, (pid, (xs, ys, label)) in enumerate(series.items()):
            color = theme.SERIES_COLORS[index % len(theme.SERIES_COLORS)]
            curve = pg.PlotDataItem(pen=pg.mkPen(color, width=2), name=label)
            self._plot.addItem(curve)
            self._curves[pid] = curve
            self._xs[pid] = _Series.from_values(xs)
            self._ys[pid] = _Series.from_values(ys)
            self._set_curve_data(pid)
        self._render_ranges()

    def add_point(self, pid: int, value: float, timestamp: float) -> None:
        if pid not in self._curves:
            return
        if self._t0 is None:
            self._t0 = timestamp
        self._xs[pid].append(timestamp - self._t0)
        self._ys[pid].append(value)
        if self._paused:
            return
        self._dirty = True
        if not self._redraw.isActive():
            self._redraw.start()

    def flush(self) -> None:
        """Draw pending samples now (they are normally coalesced per burst)."""
        self._redraw.stop()
        if not self._dirty:
            return
        self._dirty = False
        self._render_all()

    def clear(self) -> None:
        self._redraw.stop()
        self._dirty = False
        for pid in self._curves:
            self._xs[pid].clear()
            self._ys[pid].clear()
            self._curves[pid].setData([], [])
        self._t0 = None

    def reset(self) -> None:
        """Disconnect: drop all series and history."""
        self.set_active([])

    def export_to(self, path: str) -> None:
        """Save the current plot (axes, grid, legend, curves) as an image."""
        self.flush()
        exporter = ImageExporter(self._plot.getPlotItem())
        exporter.export(str(path))

    # -- rendering ------------------------------------------------------------

    def _slice_start(self, xs: np.ndarray) -> int:
        """Index of the oldest point inside the visible window."""
        if self._window is None or len(xs) == 0:
            return 0
        return int(np.searchsorted(xs, float(xs[-1]) - self._window, side="left"))

    def _set_curve_data(self, pid: int) -> None:
        """Hand pyqtgraph only the visible slice, as an immutable snapshot."""
        xs, ys = self._xs[pid].view(), self._ys[pid].view()
        start = self._slice_start(xs)
        self._curves[pid].setData(
            xs[start:].copy(), ys[start:].copy(), skipFiniteCheck=True
        )

    def _render_all(self) -> None:
        self._redraw.stop()
        self._dirty = False
        for pid in self._curves:
            self._set_curve_data(pid)
        self._render_ranges()

    def _visible_bounds(self) -> tuple[float, float, float, float] | None:
        """(xmin, xmax, ymin, ymax) over the visible time slice; None if empty."""
        last: float | None = None
        for xs in self._xs.values():
            if len(xs) and (last is None or xs.last() > last):
                last = xs.last()
        if last is None:
            return None
        if self._window is not None:
            xmin = last - self._window
        else:
            xmin = min(xs.first() for xs in self._xs.values() if len(xs))
        ymin: float | None = None
        ymax: float | None = None
        for pid in self._xs:
            xs, ys = self._xs[pid].view(), self._ys[pid].view()
            start = 0 if self._window is None else self._slice_start(xs)
            if start >= len(xs):
                continue
            visible = ys[start:]
            lo, hi = float(np.min(visible)), float(np.max(visible))
            ymin = lo if ymin is None else min(ymin, lo)
            ymax = hi if ymax is None else max(ymax, hi)
        if ymin is None or ymax is None:
            return None
        return xmin, last, ymin, ymax

    def _render_ranges(self) -> None:
        bounds = self._visible_bounds()
        if bounds is None:
            return
        xmin, xmax, ymin, ymax = bounds
        if xmax - xmin < 1e-9:
            xmin, xmax = xmin - 0.5, xmax + 0.5
        if ymax - ymin < 1e-9:
            pad = max(abs(ymax) * 0.05, 1.0)
            ymin, ymax = ymin - pad, ymax + pad
        self._plot.setXRange(xmin, xmax, padding=0.0)
        self._plot.setYRange(ymin, ymax, padding=0.05)


def _series_label(pid: int, definition: object) -> str:
    name = getattr(definition, "name", None) or f"PID {pid:02X}"
    unit = getattr(definition, "unit", "")
    return f"{name} [{unit}]" if unit else name
