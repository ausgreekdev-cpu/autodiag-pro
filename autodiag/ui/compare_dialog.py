"""Dialog: diff two saved sessions (codes, readiness, tests, values)."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from autodiag.services.compare import compare_reports, format_comparison
from autodiag.services.history import SessionStore


class CompareDialog(QDialog):
    """Pick a baseline and a current session; the diff updates live."""

    def __init__(
        self,
        store: SessionStore,
        *,
        baseline: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._store = store
        self._summaries = store.list()  # newest first

        self.setWindowTitle("Compare sessions")
        self.resize(760, 560)

        layout = QVBoxLayout(self)
        picks = QHBoxLayout()
        picks.addWidget(QLabel("Baseline:"))
        self._combo_a = QComboBox()
        self._combo_a.currentIndexChanged.connect(self._refresh)
        picks.addWidget(self._combo_a, 1)
        picks.addWidget(QLabel("Current:"))
        self._combo_b = QComboBox()
        self._combo_b.currentIndexChanged.connect(self._refresh)
        picks.addWidget(self._combo_b, 1)
        layout.addLayout(picks)

        self._body = QPlainTextEdit()
        self._body.setReadOnly(True)
        layout.addWidget(self._body, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        for summary in self._summaries:
            vin = str(summary.get("vin") or "no VIN")
            self._combo_a.addItem(f"{summary['name']} · {vin}", summary["name"])
            self._combo_b.addItem(f"{summary['name']} · {vin}", summary["name"])

        names = [str(summary["name"]) for summary in self._summaries]
        if names:
            first = baseline if baseline in names else names[0]
            others = [name for name in names if name != first]
            self._combo_a.setCurrentIndex(names.index(first))
            self._combo_b.setCurrentIndex(names.index(others[0] if others else first))
        self._refresh()

    # -- slots ---------------------------------------------------------------------

    def _refresh(self) -> None:
        if not self._summaries:
            self._body.setPlainText("No sessions to compare.")
            return
        name_a = self._combo_a.currentData()
        name_b = self._combo_b.currentData()
        if name_a is None or name_b is None:
            return
        if name_a == name_b:
            self._body.setPlainText("Pick two different sessions.")
            return
        report_a = self._store.load(str(name_a))
        report_b = self._store.load(str(name_b))
        if report_a is None or report_b is None:
            self._body.setPlainText("Could not read one of the session files.")
            return
        diff = compare_reports(report_a, report_b)
        self._body.setPlainText(
            format_comparison(
                diff, baseline_name=str(name_a), current_name=str(name_b)
            )
        )
