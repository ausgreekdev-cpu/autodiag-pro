"""Log viewer: chart saved LiveLog CSVs with a parameter picker."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from autodiag.services.log_reader import LogData, read_log
from autodiag.ui.widgets.graph import LiveGraph

_COL_CHECK, _COL_PID, _COL_NAME, _COL_UNIT = range(4)
_DEFAULT_CHECKED = 4  # series pre-selected when a log is first opened
_CSV_FILTER = "CSV log (*.csv)"


def nearest_sample(xs: Sequence[float], ys: Sequence[float], t: float) -> float | None:
    """Value of the sample closest to ``t`` (cursor readout)."""
    if not xs:
        return None
    best = min(range(len(xs)), key=lambda i: abs(xs[i] - t))
    return ys[best]


def status_text(name: str, data: LogData) -> str:
    """``log-…csv · 12,345 rows · 34.5 min · 14 parameters``."""
    span = 0.0
    for series in data.series.values():
        if series.xs:
            span = max(span, series.xs[-1] - series.xs[0])
    return (
        f"{name} · {data.rows:,} rows · {span / 60.0:.1f} min · "
        f"{len(data.series)} parameter{'s' if len(data.series) != 1 else ''}"
    )


class LogViewerPanel(QWidget):
    """Read-only chart over the ``logs/`` directory (injected)."""

    def __init__(self, log_dir: str | Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._log_dir = Path(log_dir)
        self._data: LogData | None = None
        self._loaded: Path | None = None
        self._rows: dict[int, int] = {}  # pid → table row
        self._build_ui()

    # -- construction -----------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        heading = QLabel("Log viewer")
        heading.setObjectName("heading")
        layout.addWidget(heading)

        bar = QHBoxLayout()
        self._file_combo = QComboBox()
        self._file_combo.setMinimumWidth(300)
        self._file_combo.currentIndexChanged.connect(self._on_file_chosen)
        bar.addWidget(self._file_combo)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(lambda: self.refresh(force=True))
        bar.addWidget(refresh_btn)
        self._browse_btn = QPushButton("Browse…")
        self._browse_btn.clicked.connect(self._browse)
        bar.addWidget(self._browse_btn)
        bar.addStretch(1)
        self._export_btn = QPushButton("Export image…")
        self._export_btn.setEnabled(False)
        self._export_btn.clicked.connect(self._export)
        bar.addWidget(self._export_btn)
        layout.addLayout(bar)

        self._status_label = QLabel("No logs recorded yet.")
        self._status_label.setObjectName("subtle")
        layout.addWidget(self._status_label)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        table_box = QWidget()
        table_layout = QVBoxLayout(table_box)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setSpacing(8)
        hint = QLabel("Tick parameters to plot them")
        hint.setObjectName("subtle")
        table_layout.addWidget(hint)
        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["", "PID", "Parameter", "Unit"])
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(28)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(_COL_CHECK, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(_COL_PID, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(_COL_NAME, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(_COL_UNIT, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(_COL_CHECK, 30)
        self._table.setColumnWidth(_COL_PID, 54)
        self._table.setColumnWidth(_COL_UNIT, 70)
        self._table.itemChanged.connect(self._on_item_changed)
        table_layout.addWidget(self._table)

        graph_box = QWidget()
        graph_layout = QVBoxLayout(graph_box)
        graph_layout.setContentsMargins(0, 0, 0, 0)
        graph_layout.setSpacing(6)
        self._graph = LiveGraph()
        graph_layout.addWidget(self._graph, 1)
        self._cursor_label = QLabel("")
        self._cursor_label.setObjectName("subtle")
        graph_layout.addWidget(self._cursor_label)

        splitter.addWidget(table_box)
        splitter.addWidget(graph_box)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        layout.addWidget(splitter, 1)

        self._proxy = pg.SignalProxy(
            self._graph.plot_widget.scene().sigMouseMoved,
            rateLimit=50,
            slot=self._on_mouse_moved,
        )
        self.refresh()

    # -- public API ---------------------------------------------------------------

    def refresh(self, force: bool = False) -> None:
        """Re-list the log directory (reparse the current file when forced)."""
        names = sorted(
            (path.name for path in self._log_dir.glob("log-*.csv")), reverse=True
        )
        previous = self._file_combo.currentData()
        self._file_combo.blockSignals(True)
        self._file_combo.clear()
        for name in names:
            self._file_combo.addItem(name, name)
        if previous in names:
            self._file_combo.setCurrentIndex(names.index(previous))
        else:
            self._file_combo.setCurrentIndex(0)
        self._file_combo.blockSignals(False)
        if not names:
            self._clear_all()
            self._status_label.setText("No logs recorded yet.")
            return
        self._ensure_loaded(force=force)

    def load_log(self, name: str) -> bool:
        """Load ``name`` from the log directory (e.g. from the History panel)."""
        if Path(name).name != name:
            return False  # no directory traversal
        return self._load_path(self._log_dir / name, force=True, sync_combo=True)

    # -- slots -----------------------------------------------------------------------

    def _on_file_chosen(self, index: int) -> None:
        name = self._file_combo.itemData(index)
        if name:
            self._load_path(self._log_dir / str(name))

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() == _COL_CHECK:
            self._apply_selection()

    def _on_mouse_moved(self, events) -> None:
        if self._data is None or not events:
            return
        plot = self._graph.plot_widget
        pos = events[0]
        if not plot.sceneBoundingRect().contains(pos):
            return
        moment = plot.plotItem.vb.mapSceneToView(pos).x()
        parts: list[str] = []
        for pid in self._graph.active_pids():
            series = self._data.series.get(pid)
            if series is None:
                continue
            value = nearest_sample(series.xs, series.ys, moment)
            if value is None:
                continue
            unit = f" {series.unit}" if series.unit else ""
            parts.append(f"{series.name} {value:g}{unit}")
        if parts:
            self._cursor_label.setText(f"t={moment:.1f}s · " + " · ".join(parts))

    # -- loading -------------------------------------------------------------------

    def _ensure_loaded(self, *, force: bool = False) -> None:
        name = self._file_combo.currentData()
        if name:
            self._load_path(self._log_dir / str(name), force=force)

    def _load_path(
        self, path: Path, *, force: bool = False, sync_combo: bool = False
    ) -> bool:
        if not force and self._loaded == path and self._data is not None:
            return True
        try:
            data = read_log(path)
        except (OSError, ValueError) as exc:
            self._clear_all()
            self._status_label.setText(f"Could not read {path.name}: {exc}")
            return False
        self._data = data
        self._loaded = path
        self._status_label.setText(status_text(path.name, data))
        self._export_btn.setEnabled(True)
        if sync_combo:
            index = self._file_combo.findData(path.name)
            if index >= 0:
                self._file_combo.blockSignals(True)
                self._file_combo.setCurrentIndex(index)
                self._file_combo.blockSignals(False)
        self._populate_table()
        return True

    def _populate_table(self) -> None:
        assert self._data is not None
        self._table.blockSignals(True)
        self._table.setRowCount(0)
        self._rows.clear()
        for position, series in enumerate(self._data.series.values()):
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._rows[series.pid] = row
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            check.setCheckState(
                Qt.CheckState.Checked
                if position < _DEFAULT_CHECKED
                else Qt.CheckState.Unchecked
            )
            self._table.setItem(row, _COL_CHECK, check)
            self._table.setItem(
                row, _COL_PID, QTableWidgetItem(f"{series.pid:02X}")
            )
            self._table.setItem(row, _COL_NAME, QTableWidgetItem(series.name))
            self._table.setItem(row, _COL_UNIT, QTableWidgetItem(series.unit))
        self._table.blockSignals(False)
        self._apply_selection()

    def _apply_selection(self) -> None:
        selected: dict[int, tuple[list[float], list[float], str]] = {}
        if self._data is not None:
            for pid, row in self._rows.items():
                check = self._table.item(row, _COL_CHECK)
                if check is None or check.checkState() != Qt.CheckState.Checked:
                    continue
                series = self._data.series[pid]
                label = f"{series.name} [{series.unit}]" if series.unit else series.name
                selected[pid] = (series.xs, series.ys, label)
        self._graph.set_series(selected)
        self._cursor_label.setText("")

    def _clear_all(self) -> None:
        self._data = None
        self._loaded = None
        self._rows.clear()
        self._table.blockSignals(True)
        self._table.setRowCount(0)
        self._table.blockSignals(False)
        self._graph.set_series({})
        self._export_btn.setEnabled(False)
        self._cursor_label.setText("")

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open log", str(self._log_dir), _CSV_FILTER
        )
        if path:
            self._load_path(Path(path), force=True, sync_combo=True)

    def _export(self) -> None:
        if self._data is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export graph image",
            self._loaded.stem + "-view.png" if self._loaded else "log-view.png",
            "PNG image (*.png)",
        )
        if path:
            self._graph.export_to(path)

    def showEvent(self, event) -> None:  # noqa: N802 — Qt naming
        super().showEvent(event)
        self.refresh()  # cheap: reparses only if the selection changed
