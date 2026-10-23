"""Dialog: diff two session reports (sessions from disk or loaded files)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from autodiag.services.compare import compare_reports, format_comparison
from autodiag.services.history import SessionStore, load_report_file


class CompareDialog(QDialog):
    """Pick two reports to diff — saved sessions or files from disk.

    Each side is either a saved session (combo) or a loaded report file
    (button toggles load / clear); the diff updates live.
    """

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
        # file overrides: (display name, report, source path)
        self._file_a: tuple[str, dict, str] | None = None
        self._file_b: tuple[str, dict, str] | None = None

        self.setWindowTitle("Compare reports")
        self.resize(760, 560)

        layout = QVBoxLayout(self)
        picks = QHBoxLayout()
        picks.setSpacing(6)
        picks.addWidget(QLabel("Baseline:"))
        self._combo_a = QComboBox()
        self._combo_a.currentIndexChanged.connect(self._refresh)
        picks.addWidget(self._combo_a, 1)
        self._file_btn_a = QPushButton("Load file…")
        self._file_btn_a.setToolTip(
            "Diff against a report JSON exported to disk "
            "(click again to return to session selection)"
        )
        self._file_btn_a.clicked.connect(lambda: self._toggle_file(0))
        picks.addWidget(self._file_btn_a)
        layout.addLayout(picks)

        picks_b = QHBoxLayout()
        picks_b.setSpacing(6)
        picks_b.addWidget(QLabel("Current:"))
        self._combo_b = QComboBox()
        self._combo_b.currentIndexChanged.connect(self._refresh)
        picks_b.addWidget(self._combo_b, 1)
        self._file_btn_b = QPushButton("Load file…")
        self._file_btn_b.setToolTip(
            "Diff against a report JSON exported to disk "
            "(click again to return to session selection)"
        )
        self._file_btn_b.clicked.connect(lambda: self._toggle_file(1))
        picks_b.addWidget(self._file_btn_b)
        layout.addLayout(picks_b)

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

    # -- file loading -------------------------------------------------------------

    def _toggle_file(self, side: int) -> None:
        current = self._file_a if side == 0 else self._file_b
        if current is not None:  # second click clears back to the combo
            self._set_file(side, None)
            return
        caption = "Load baseline report" if side == 0 else "Load current report"
        path, _ = QFileDialog.getOpenFileName(
            self,
            caption,
            "",
            "AutoDiag reports (*.json);;All files (*)",
        )
        if not path:
            return
        report = load_report_file(path)
        if report is None:
            QMessageBox.warning(
                self,
                "Could not load report",
                f"{path}\n\nNot a readable AutoDiag report JSON.",
            )
            return
        self._set_file(side, (Path(path).name, report, path))
        self._refresh()

    def _set_file(self, side: int, value: tuple[str, dict, str] | None) -> None:
        if side == 0:
            self._file_a = value
            combo, button = self._combo_a, self._file_btn_a
        else:
            self._file_b = value
            combo, button = self._combo_b, self._file_btn_b
        if value is None:
            button.setText("Load file…")
            combo.setEnabled(True)
        else:
            button.setText(f"File: {value[0]}")
            combo.setEnabled(False)
        self._refresh()

    # -- slots ---------------------------------------------------------------------

    def _refresh(self) -> None:
        name_a = (
            self._file_a[0] if self._file_a is not None else self._combo_name(self._combo_a)
        )
        name_b = (
            self._file_b[0] if self._file_b is not None else self._combo_name(self._combo_b)
        )
        report_a = self._file_a[1] if self._file_a is not None else None
        report_b = self._file_b[1] if self._file_b is not None else None

        if report_a is None and not self._summaries:
            self._body.setPlainText("No sessions to compare.")
            return
        if name_a is None or name_b is None:
            return
        if report_a is None:
            report_a = self._store.load(str(name_a))
        if report_b is None:
            report_b = self._store.load(str(name_b)) if name_b is not None else None

        if name_a == name_b and (
            self._file_a is None or self._file_b is None or self._file_a[2] == self._file_b[2]
        ):
            self._body.setPlainText("Pick two different reports.")
            return
        if report_a is None or report_b is None:
            self._body.setPlainText("Could not read one of the report sources.")
            return
        diff = compare_reports(report_a, report_b)
        self._body.setPlainText(
            format_comparison(diff, baseline_name=str(name_a), current_name=str(name_b))
        )

    @staticmethod
    def _combo_name(combo: QComboBox) -> str | None:
        data = combo.currentData()
        return str(data) if data is not None else None
