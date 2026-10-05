"""Settings & reports panel: export scan results, about info."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QThread, Signal
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
from autodiag.services import update_check
from autodiag.services.export import write_report
from autodiag.services.record import ScanRecord

_JSON_FILTER = "JSON report (*.json)"
_CSV_FILTER = "CSV report (*.csv)"


class UpdateCheckWorker(QThread):
    """Runs check_for_update off the UI thread."""

    done = Signal(object)  # UpdateCheck

    def __init__(self, current: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._current = current

    def run(self) -> None:
        self.done.emit(update_check.check_for_update(self._current))


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
        self._update_worker: UpdateCheckWorker | None = None

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

        check_row = QHBoxLayout()
        self._update_btn = QPushButton("Check for updates")
        self._update_btn.setToolTip("One request to the GitHub releases API")
        self._update_btn.clicked.connect(self._on_check_updates)
        check_row.addWidget(self._update_btn)
        self._update_label = QLabel("")
        self._update_label.setObjectName("subtle")
        self._update_label.setOpenExternalLinks(True)
        check_row.addWidget(self._update_label, 1)
        about_layout.addLayout(check_row)

        privacy_note = QLabel(
            "No data leaves this machine unless you press Check for updates "
            "(one GitHub API request)."
        )
        privacy_note.setObjectName("subtle")
        about_layout.addWidget(privacy_note)
        layout.addWidget(about_group)

        layout.addStretch(1)

    # -- update check -----------------------------------------------------------

    def _on_check_updates(self) -> None:
        if self._update_worker is not None:
            return  # a check is already running
        self._update_btn.setEnabled(False)
        self._update_label.setText("Checking…")
        worker = UpdateCheckWorker(__version__)
        worker.done.connect(self._on_update_done)
        worker.finished.connect(self._on_update_finished)
        self._update_worker = worker  # keep the thread alive until finished
        worker.start()

    def _on_update_done(self, result: object) -> None:
        check = result  # UpdateCheck
        if not isinstance(check, update_check.UpdateCheck):
            return
        if check.status == "update":
            self._update_label.setText(
                f'<a href="{check.url}">{check.latest} is available</a>'
            )
        elif check.status == "current":
            self._update_label.setText(f"You're up to date (v{__version__}).")
        else:
            self._update_label.setText(f"Update check failed: {check.message}")

    def _on_update_finished(self) -> None:
        self._update_worker = None
        self._update_btn.setEnabled(True)

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
