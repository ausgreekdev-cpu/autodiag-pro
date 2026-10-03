"""Test-wide setup: force the offscreen Qt platform before any Qt import."""

from __future__ import annotations

import os
import tempfile

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# QSettings from any MainWindow/Dashboard built in tests lands here, never in
# the developer's real ~/.config (applied in the qapp fixture before first use).
_SETTINGS_DIR = tempfile.mkdtemp(prefix="autodiag-qsettings-")


@pytest.fixture(scope="session")
def qapp():
    """One QApplication for the whole session (offscreen, theme applied)."""
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    from autodiag.ui.theme import apply_theme

    app = QApplication.instance() or QApplication([])
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(
        QSettings.Format.IniFormat, QSettings.Scope.UserScope, _SETTINGS_DIR
    )
    apply_theme(app)
    return app
