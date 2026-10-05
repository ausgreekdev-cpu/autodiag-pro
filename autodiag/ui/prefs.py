"""Persistent preferences: port, poll interval, layout, auto-connect.

Thin typed wrapper over ``QSettings`` so tests can inject an isolated INI
file and no suite ever touches the user's real configuration.
"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QSettings


def _as_qbytearray(value: object) -> QByteArray | None:
    if isinstance(value, QByteArray):
        return value
    if isinstance(value, bytes | bytearray):
        return QByteArray(bytes(value))
    return None


GRAPH_WINDOW_DEFAULT = "2 min"
GRAPH_WINDOW_CHOICES = ("30 s", "2 min", "10 min", "All")


class Prefs:
    def __init__(self, settings: QSettings | None = None) -> None:
        self._s = settings if settings is not None else QSettings(
            "AutoDiag Pro", "autodiag"
        )

    # -- connection -----------------------------------------------------------

    def last_port(self) -> str | None:
        value = self._s.value("port", "")
        return str(value) if value else None

    def set_last_port(self, device: str | None) -> None:
        self._s.setValue("port", device or "")

    def auto_connect(self) -> bool:
        raw = self._s.value("auto_connect", False)
        if isinstance(raw, str):
            return raw.lower() in ("true", "1", "yes")
        return bool(raw)

    def set_auto_connect(self, enabled: bool) -> None:
        self._s.setValue("auto_connect", bool(enabled))

    def auto_log(self) -> bool:
        """Live-data CSV logging (on by default)."""
        raw = self._s.value("auto_log", True)
        if isinstance(raw, str):
            return raw.lower() in ("true", "1", "yes")
        return bool(raw)

    def set_auto_log(self, enabled: bool) -> None:
        self._s.setValue("auto_log", bool(enabled))

    # -- polling --------------------------------------------------------------

    def poll_interval_ms(self) -> int:
        raw = self._s.value("poll_interval_ms", 250)
        try:
            value = int(raw)  # QSettings may hand back str on some backends
        except (TypeError, ValueError):
            return 250
        return min(max(value, 50), 5000)

    def set_poll_interval_ms(self, ms: int) -> None:
        self._s.setValue("poll_interval_ms", int(ms))

    # -- graph ----------------------------------------------------------------

    def graph_window(self) -> str:
        """Dashboard graph time-window label (validated against the choices)."""
        raw = str(self._s.value("graph_window", GRAPH_WINDOW_DEFAULT) or "")
        return raw if raw in GRAPH_WINDOW_CHOICES else GRAPH_WINDOW_DEFAULT

    def set_graph_window(self, label: str) -> None:
        value = label if label in GRAPH_WINDOW_CHOICES else GRAPH_WINDOW_DEFAULT
        self._s.setValue("graph_window", value)

    # -- layout -----------------------------------------------------------------

    def panel_index(self) -> int | None:
        """Saved panel index; ``None`` when never set (caller picks a default)."""
        raw = self._s.value("panel_index")
        if raw is None:
            return None
        try:
            index = int(raw)
        except (TypeError, ValueError):
            return None
        return index if index >= 0 else None

    def set_panel_index(self, index: int) -> None:
        self._s.setValue("panel_index", int(index))

    def window_geometry(self) -> QByteArray | None:
        return _as_qbytearray(self._s.value("window/geometry"))

    def set_window_geometry(self, geometry: QByteArray) -> None:
        self._s.setValue("window/geometry", geometry)

    def window_state(self) -> QByteArray | None:
        return _as_qbytearray(self._s.value("window/state"))

    def set_window_state(self, state: QByteArray) -> None:
        self._s.setValue("window/state", state)

    # -- io ---------------------------------------------------------------------

    def sync(self) -> None:
        """Flush pending writes to disk (tests, imminent hard exits)."""
        self._s.sync()
