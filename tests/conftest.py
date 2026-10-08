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
    yield app
    # PySide6 6.12.0 corrupts the heap when widgets whose Python wrappers are
    # only kept alive by signal→bound-method cycles are finally collected
    # during interpreter shutdown ("shared QObject was deleted directly" ->
    # malloc_consolidate abort). Destroy every widget here, while Qt is still
    # fully alive: the C++ cascade deletes children first, and the leftover
    # Python wrappers then tear down without touching freed memory.
    for widget in app.allWidgets():
        widget.deleteLater()
    app.processEvents()


@pytest.fixture(autouse=True)
def _isolate_default_store(monkeypatch, tmp_path_factory):
    """Tests that don't inject a store must not touch the real AppData dir.

    (``test_default_directory_ends_in_sessions`` holds an import-time bound
    to the original function, so it still checks the real path.)
    """
    target = tmp_path_factory.mktemp("autodiag-default-store")
    monkeypatch.setattr(
        "autodiag.services.history.default_directory", lambda: target
    )
