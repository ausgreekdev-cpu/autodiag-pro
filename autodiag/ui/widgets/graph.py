"""Scrolling live graph (pyqtgraph) for selected PIDs."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Mapping, Sequence

import pyqtgraph as pg
from pyqtgraph.exporters import ImageExporter
from PySide6.QtWidgets import QVBoxLayout, QWidget

from autodiag.obd.pids import PID_REGISTRY
from autodiag.ui import theme

_BUFFER = 2400  # points per series (10 min at the default 4 req/s)


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
        self._xs: dict[int, deque[float]] = {}
        self._ys: dict[int, deque[float]] = {}
        self._curves: dict[int, pg.PlotDataItem] = {}
        self._window: float | None = None
        self._paused = False

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
        self._render_ranges()

    @property
    def paused(self) -> bool:
        return self._paused

    def set_paused(self, paused: bool) -> None:
        """Freeze rendering (points keep recording); resume catches up now."""
        if self._paused == paused:
            return
        self._paused = paused
        if not paused:
            self._render_all()

    # -- API ------------------------------------------------------------------

    def set_active(self, pids: Iterable[int]) -> None:
        """Replace the plotted series (selection changed → history resets)."""
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
            self._xs[pid] = deque(maxlen=_BUFFER)
            self._ys[pid] = deque(maxlen=_BUFFER)

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
            xs_f = [float(x) for x in xs]
            ys_f = [float(y) for y in ys]
            curve.setData(xs_f, ys_f)
            self._plot.addItem(curve)
            self._curves[pid] = curve
            self._xs[pid] = deque(xs_f)  # unbounded: static loads show everything
            self._ys[pid] = deque(ys_f)
        self._render_ranges()

    def add_point(self, pid: int, value: float, timestamp: float) -> None:
        if pid not in self._curves:
            return
        if self._t0 is None:
            self._t0 = timestamp
        xs, ys = self._xs[pid], self._ys[pid]
        xs.append(timestamp - self._t0)
        ys.append(value)
        if self._paused:
            return
        self._curves[pid].setData(list(xs), list(ys))
        self._render_ranges()

    def clear(self) -> None:
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
        exporter = ImageExporter(self._plot.getPlotItem())
        exporter.export(str(path))

    # -- rendering -----------------------------------------------------------

    def _render_all(self) -> None:
        for pid, curve in self._curves.items():
            xs, ys = self._xs[pid], self._ys[pid]
            curve.setData(list(xs), list(ys))
        self._render_ranges()

    def _visible_bounds(self) -> tuple[float, float, float, float] | None:
        """(xmin, xmax, ymin, ymax) over the visible time slice; None if empty."""
        last = None
        for xs in self._xs.values():
            if xs and (last is None or xs[-1] > last):
                last = xs[-1]
        if last is None:
            return None
        if self._window is not None:
            xmin = last - self._window
        else:
            xmin = min(xs[0] for xs in self._xs.values() if xs)
        ymin: float | None = None
        ymax: float | None = None
        for pid in self._xs:
            xs, ys = self._xs[pid], self._ys[pid]
            for x, y in zip(reversed(xs), reversed(ys), strict=True):
                if x < xmin:
                    break
                if ymin is None or y < ymin:
                    ymin = y
                if ymax is None or y > ymax:
                    ymax = y
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
