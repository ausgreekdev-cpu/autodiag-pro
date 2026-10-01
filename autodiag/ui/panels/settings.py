"""Settings & reports panel: export scan results, about info."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from autodiag import __version__
from autodiag.obd.dictionary import load_dictionary
from autodiag.services.export import write_report
from autodiag.services.record import ScanRecord

_JSON_FILTER = "JSON report (*.json)"
_CSV_FILTER = "CSV report (*.csv)"


class SettingsPanel(QWidget):
    def __init__(
        self,
        record: ScanRecord,
        on_message: Callable[[str], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._record = record
        self._on_message = on_message

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        heading = QLabel("Settings & reports")
        heading.setObjectName("heading")
        layout.addWidget(heading)

        report_group = QGroupBox("Scan report")
        report_layout = QVBoxLayout(report_group)
        description = QLabel(
            "Exports everything collected this session: VIN, DTCs with descriptions,\n"
            "readiness monitors, freeze frame, Mode $06 results and the latest readings."
        )
        description.setObjectName("subtle")
        report_layout.addWidget(description)

        buttons = QHBoxLayout()
        self._json_btn = QPushButton("Export JSON…")
        self._json_btn.clicked.connect(lambda: self.export_with_dialog("json"))
        buttons.addWidget(self._json_btn)
        self._csv_btn = QPushButton("Export CSV…")
        self._csv_btn.clicked.connect(lambda: self.export_with_dialog("csv"))
        buttons.addWidget(self._csv_btn)
        buttons.addStretch(1)
        report_layout.addLayout(buttons)

        self._export_label = QLabel("")
        self._export_label.setObjectName("subtle")
        report_layout.addWidget(self._export_label)
        layout.addWidget(report_group)

        about_group = QGroupBox("About")
        about_layout = QVBoxLayout(about_group)
        about_layout.addWidget(
            QLabel(f"AutoDiag Pro v{__version__} — offline OBD-II diagnostics.")
        )
        dictionary_note = QLabel(
            f"DTC dictionary: {len(load_dictionary()):,} codes bundled."
        )
        dictionary_note.setObjectName("subtle")
        about_layout.addWidget(dictionary_note)
        privacy_note = QLabel("No data leaves this machine: no accounts, no servers.")
        privacy_note.setObjectName("subtle")
        about_layout.addWidget(privacy_note)
        layout.addWidget(about_group)

        layout.addStretch(1)

    # -- export -----------------------------------------------------------------

    def export_with_dialog(self, suffix: str) -> None:
        _filter = _JSON_FILTER if suffix == "json" else _CSV_FILTER
        path, _selected = QFileDialog.getSaveFileName(
            self,
            "Export scan report",
            f"autodiag-report.{suffix}",
            _filter,
        )
        if path:
            self.export_to(path)

    def export_to(self, path: str | Path) -> Path:
        """Write the report to ``path`` (pure — also used by tests)."""
        target = Path(path)
        if not target.suffix:
            target = target.with_suffix(".json")
        write_report(self._record, target)
        message = f"Report written to {target}"
        self._export_label.setText(message)
        self._on_message(message)
        return target
