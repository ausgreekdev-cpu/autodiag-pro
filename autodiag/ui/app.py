"""Application bootstrap: QApplication, theme, main window, worker start."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from autodiag.ui.main_window import MainWindow
from autodiag.ui.theme import apply_theme


def main(argv: list[str] | None = None) -> int:
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("AutoDiag Pro")
    app.setOrganizationName("AutoDiagPro")
    apply_theme(app)

    window = MainWindow()
    window.show()
    window.worker.start()
    try:
        return app.exec()
    finally:
        window.worker.shutdown(5000)
