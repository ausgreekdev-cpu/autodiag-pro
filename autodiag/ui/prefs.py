"""Persistent preferences: port, poll interval, layout, auto-connect.

Thin typed wrapper over ``QSettings`` so tests can inject an isolated INI
file and no suite ever touches the user's real configuration.
"""

from __future__ import annotations

import json

from PySide6.QtCore import QByteArray, QSettings


def _as_qbytearray(value: object) -> QByteArray | None:
    if isinstance(value, QByteArray):
        return value
    if isinstance(value, bytes | bytearray):
        return QByteArray(bytes(value))
    return None


GRAPH_WINDOW_DEFAULT = "2 min"
GRAPH_WINDOW_CHOICES = ("30 s", "2 min", "10 min", "All")

# ELM327 ATSP codes → UI labels ("0" = auto-search on the bus).
PROTOCOL_CHOICES = (
    ("0", "Auto (search all)"),
    ("1", "SAE J1850 PWM (41.6 kbit/s)"),
    ("2", "SAE J1850 VPW (10.4 kbit/s)"),
    ("3", "ISO 9141-2 (5-baud init)"),
    ("4", "ISO 14230-4 KWP (5-baud init)"),
    ("5", "ISO 14230-4 KWP (fast init)"),
    ("6", "ISO 15765-4 CAN (11-bit, 500 kbit/s)"),
    ("7", "ISO 15765-4 CAN (29-bit, 500 kbit/s)"),
    ("8", "ISO 15765-4 CAN (11-bit, 250 kbit/s)"),
    ("9", "ISO 15765-4 CAN (29-bit, 250 kbit/s)"),
    ("A", "SAE J1939 CAN (11-bit, 250 kbit/s)"),
    ("B", "User 1 CAN (11-bit, 125 kbit/s)"),
    ("C", "User 2 CAN (11-bit, 50 kbit/s)"),
)
_PROTOCOL_CODES = frozenset(code for code, _ in PROTOCOL_CHOICES)


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

    def protocol(self) -> str:
        """Pinned OBD protocol (``ATSP`` digit); ``"0"`` = auto-search."""
        raw = str(self._s.value("protocol", "0") or "0").upper()
        return raw if raw in _PROTOCOL_CODES else "0"

    def set_protocol(self, code: str) -> None:
        value = str(code).strip().upper()
        self._s.setValue("protocol", value if value in _PROTOCOL_CODES else "0")

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

    def watchlist(self) -> dict[int, tuple[float | None, float | None]]:
        """pid → (low, high) alert thresholds; unparsable entries are dropped."""
        raw = self._s.value("watchlist", "")
        if not raw:
            return {}
        try:
            data = json.loads(str(raw))
        except ValueError:
            return {}
        if not isinstance(data, dict):
            return {}
        result: dict[int, tuple[float | None, float | None]] = {}
        for key, bounds in data.items():
            try:
                pid = int(str(key), 16)
                low_raw, high_raw = bounds
                low = float(low_raw) if low_raw is not None else None
                high = float(high_raw) if high_raw is not None else None
            except (TypeError, ValueError):
                continue
            result[pid] = (low, high)
        return result

    def set_watchlist(self, thresholds: dict[int, tuple[float | None, float | None]]) -> None:
        data = {f"{pid:02X}": [low, high] for pid, (low, high) in thresholds.items()}
        self._s.setValue("watchlist", json.dumps(data))

    # -- io ---------------------------------------------------------------------

    def sync(self) -> None:
        """Flush pending writes to disk (tests, imminent hard exits)."""
        self._s.sync()
