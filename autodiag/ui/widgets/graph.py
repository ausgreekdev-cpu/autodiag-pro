"""Scrolling live graph (pyqtgraph) for selected PIDs."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Mapping, Sequence

import pyqtgraph as pg
from pyqtgraph.exporters import ImageExporter
from PySide6.QtWidgets import QVBoxLayout, QWidget

from autodiag.obd.pids import PID_REGISTRY
from autodiag.ui import theme

_BUFFER = 900  # points per series (~3.7 min at 4 req/s)


class LiveGraph(QWidget):
    """Time-series strip chart; only *active* PIDs are recorded."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._plot = pg.PlotWidget()
        self._plot.showGrid(x=True, y=True, alpha=0.15)
        self._plot.setLabel("bottom", "Time", units="s")
        self._plot.addLegend(offset=(10, 10))
        self._plot.getPlotItem().setMenuEnabled(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._plot)

        self._t0: float | None = None
        self._xs: dict[int, deque[float]] = {}
        self._ys: dict[int, deque[float]] = {}
        self._curves: dict[int, pg.PlotDataItem] = {}

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
            curve.setData([float(x) for x in xs], [float(y) for y in ys])
            self._plot.addItem(curve)
            self._curves[pid] = curve

    def add_point(self, pid: int, value: float, timestamp: float) -> None:
        if pid not in self._curves:
            return
        if self._t0 is None:
            self._t0 = timestamp
        xs, ys = self._xs[pid], self._ys[pid]
        xs.append(timestamp - self._t0)
        ys.append(value)
        self._curves[pid].setData(list(xs), list(ys))

    def clear(self) -> None:
        for pid in self._curves:
            self._xs[pid].clear()
            self._ys[pid].clear()
        self._t0 = None

    def reset(self) -> None:
        """Disconnect: drop all series and history."""
        self.set_active([])

    def export_to(self, path: str) -> None:
        """Save the current plot (axes, grid, legend, curves) as an image."""
        exporter = ImageExporter(self._plot.getPlotItem())
        exporter.export(str(path))


def _series_label(pid: int, definition: object) -> str:
    name = getattr(definition, "name", None) or f"PID {pid:02X}"
    unit = getattr(definition, "unit", "")
    return f"{name} [{unit}]" if unit else name
