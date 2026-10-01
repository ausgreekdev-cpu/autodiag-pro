"""Test-wide setup: force the offscreen Qt platform before any Qt import."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qapp():
    """One QApplication for the whole session (offscreen, theme applied)."""
    from PySide6.QtWidgets import QApplication

    from autodiag.ui.theme import apply_theme

    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    return app
