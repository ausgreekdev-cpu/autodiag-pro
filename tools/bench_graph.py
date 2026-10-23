"""Benchmark: per-batch cost of the live graph as its buffer fills.

Run from the repository root, with the app's dependencies importable::

    QT_QPA_PLATFORM=offscreen python tools/bench_graph.py

It drives the real ``LiveGraph`` exactly as the dashboard does: six active
PIDs, one sample every 250 ms, one flush per batch. Two numbers are reported
per fill level:

``ms/batch``
    UI-thread work for six ``add_point`` calls plus the coalesced redraw.
    This is the cost that competes with the rest of the window.
``ms/paint``
    A synchronous ``grab()`` of the widget, i.e. tessellating the curves.
    Paint runs at most once per frame regardless of sample rate.

Before the numpy/coalescing rewrite (0.23.0) the same harness reported
1.93 → 3.04 ms/batch for the 2-minute window and 1.95 → 6.60 ms/batch for
"All", i.e. cost grew with history. It is now flat.
"""

from __future__ import annotations

import statistics
import sys
import time

from PySide6.QtWidgets import QApplication

from autodiag.ui import theme
from autodiag.ui.widgets.graph import LiveGraph

PIDS = (0x0C, 0x0D, 0x05, 0x11, 0x0F, 0x10)
DT = 0.25  # default poll interval
FILLS = (50, 300, 600, 1200, 2400)
BATCHES = 12  # median over more batches: these numbers are small


def fill(graph: LiveGraph, target: int, start: float = 1000.0) -> float:
    """Add whole batches until the first series holds ``target`` samples."""
    t = start
    while len(graph._xs[PIDS[0]]) < target:
        for pid in PIDS:
            graph.add_point(pid, 100.0 + (pid % 7), t)
            t += DT
    return t


def measure(graph: LiveGraph, t: float) -> tuple[float, float]:
    """Median (batch, paint) seconds over a few batches at the current fill."""
    batches: list[float] = []
    paints: list[float] = []
    for _ in range(BATCHES):
        started = time.perf_counter()
        for pid in PIDS:
            graph.add_point(pid, 100.0 + (pid % 7), t)
            t += DT
        graph.flush()
        batches.append(time.perf_counter() - started)

        started = time.perf_counter()
        graph.grab()
        paints.append(time.perf_counter() - started)
    return statistics.median(batches), statistics.median(paints)


def bench(window: float | None) -> None:
    label = "All" if window is None else f"{window:g}s window"
    print(f"\n{label}")
    print(f"{'fill':>6} {'ms/batch':>10} {'ms/paint':>10}")
    for target in FILLS:
        graph = LiveGraph()
        graph.set_window(window)
        graph.set_active(PIDS)
        t = fill(graph, target)
        graph.flush()
        batch_ms, paint_ms = measure(graph, t)
        print(f"{target:>6} {batch_ms * 1e3:>10.3f} {paint_ms * 1e3:>10.3f}")


if __name__ == "__main__":
    if QApplication.instance() is None:  # a QWidget needs an application
        app = QApplication(sys.argv)
        theme.apply_theme(app)
    bench(120.0)
    bench(None)
