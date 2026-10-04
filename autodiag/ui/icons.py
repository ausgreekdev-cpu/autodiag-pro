"""Application icon: the packaged PNG loaded without touching the filesystem."""

from __future__ import annotations

from PySide6.QtGui import QIcon, QPixmap

from autodiag.data import read_bytes

ICON_PNG = "icon-256.png"


def app_icon() -> QIcon:
    """The AutoDiag Pro icon, loaded from bundled bytes (one-file safe)."""
    pixmap = QPixmap()
    pixmap.loadFromData(read_bytes(ICON_PNG))
    return QIcon(pixmap)
