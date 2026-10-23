"""Application bootstrap: QApplication, theme, main window, worker start."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from autodiag.ui.icons import app_icon
from autodiag.ui.license import ensure_eula_accepted
from autodiag.ui.main_window import MainWindow
from autodiag.ui.prefs import Prefs
from autodiag.ui.theme import apply_theme


def main(argv: list[str] | None = None) -> int:
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("AutoDiag Pro")
    app.setOrganizationName("AutoDiagPro")
    app.setWindowIcon(app_icon())

    prefs = Prefs()
    apply_theme(app, prefs.theme())

    window = MainWindow(prefs=prefs)
    window.show()
    if not ensure_eula_accepted(window, prefs):
        return 0  # declined: exit without starting the worker
    window.worker.start()
    try:
        return app.exec()
    finally:
        window.worker.shutdown(5000)
