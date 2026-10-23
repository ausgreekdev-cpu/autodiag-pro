"""Themes: dark (default) and light — palette constants + stylesheet builder."""

from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtWidgets import QApplication

# palette -------------------------------------------------------------------
# Dark is the default; light is the toggleable alternative (Settings →
# Appearance).  These module constants are rebound by apply_theme() so
# panels using `theme.X` follow the active theme at runtime.

DARK_PALETTE: dict[str, str] = {
    "BG": "#0f141a",
    "SURFACE": "#171e26",
    "SURFACE2": "#1e2732",
    "BORDER": "#2a3441",
    "TEXT": "#e6edf3",
    "MUTED": "#8b949e",
    "ACCENT": "#2f81f7",
    "ACCENT_HOVER": "#4593f8",
    "OK": "#3fb950",
    "WARN": "#e3b341",
    "DANGER": "#f85149",
    "SELECTED_ROW": "#1d3a5f",
    "BREACH_BG": "#4a3a12",  # amber fill for a value cell that crossed an alert limit
    "BTN_HOVER": "#263140",
    "BTN_HOVER_BORDER": "#3a4653",
    "BTN_PRESSED": "#1a222c",
    "PRIMARY_PRESSED": "#2671d4",
    "SCROLL_HOVER": "#3a4653",
}

LIGHT_PALETTE: dict[str, str] = {
    "BG": "#ffffff",
    "SURFACE": "#f6f8fa",
    "SURFACE2": "#eaedf0",
    "BORDER": "#d0d7de",
    "TEXT": "#1f2328",
    "MUTED": "#59636e",
    "ACCENT": "#0969da",
    "ACCENT_HOVER": "#0550ae",
    "OK": "#1a7f37",
    "WARN": "#9a6700",
    "DANGER": "#cf222e",
    "SELECTED_ROW": "#ddf4ff",
    "BREACH_BG": "#fff8c5",
    "BTN_HOVER": "#e7ebef",
    "BTN_HOVER_BORDER": "#b6bdc4",
    "BTN_PRESSED": "#dde2e7",
    "PRIMARY_PRESSED": "#034f8c",
    "SCROLL_HOVER": "#b6bdc4",
}


def build_stylesheet(palette: Mapping[str, str]) -> str:
    """Application-wide QSS built from a palette mapping."""
    p = palette
    return f"""
QMainWindow, QDialog {{ background: {p['BG']}; }}
QWidget {{ color: {p['TEXT']}; font-size: 13px; }}
QToolTip {{ background: {p['SURFACE2']}; color: {p['TEXT']};
    border: 1px solid {p['BORDER']}; padding: 4px; }}

QToolBar {{ background: {p['SURFACE']}; border: none; border-bottom: 1px solid {p['BORDER']};
    padding: 8px 10px; spacing: 8px; }}
QLabel#chip {{ background: {p['SURFACE2']}; border: 1px solid {p['BORDER']}; border-radius: 12px;
    padding: 3px 12px; color: {p['MUTED']}; }}
QLabel#chip[data-live="1"] {{ color: {p['OK']}; border-color: {p['OK']}; }}
QLabel#heading {{ font-size: 16px; font-weight: 600; }}
QLabel#subtle {{ color: {p['MUTED']}; }}

QPushButton {{ background: {p['SURFACE2']}; border: 1px solid {p['BORDER']}; border-radius: 6px;
    padding: 6px 14px; color: {p['TEXT']}; }}
QPushButton:hover {{ background: {p['BTN_HOVER']}; border-color: {p['BTN_HOVER_BORDER']}; }}
QPushButton:pressed {{ background: {p['BTN_PRESSED']}; }}
QPushButton:disabled {{ color: {p['MUTED']}; background: {p['SURFACE']};
    border-color: {p['BORDER']}; }}
QPushButton#primary {{ background: {p['ACCENT']}; border: 1px solid {p['ACCENT']};
    color: white; font-weight: 600; }}
QPushButton#primary:hover {{ background: {p['ACCENT_HOVER']}; border-color: {p['ACCENT_HOVER']}; }}
QPushButton#primary:pressed {{ background: {p['PRIMARY_PRESSED']}; }}
QPushButton#primary:disabled {{ background: {p['SURFACE2']}; border-color: {p['BORDER']};
    color: {p['MUTED']}; }}
QPushButton#danger {{ background: transparent; border: 1px solid {p['DANGER']};
    color: {p['DANGER']}; font-weight: 600; }}
QPushButton#danger:hover {{ background: {p['DANGER']}; color: white; }}
QPushButton#danger:disabled {{ background: {p['SURFACE']}; border-color: {p['BORDER']};
    color: {p['MUTED']}; }}
QPushButton#nav {{ text-align: left; background: transparent; border: none;
    border-radius: 6px; padding: 9px 14px; color: {p['MUTED']}; }}
QPushButton#nav:hover {{ background: {p['SURFACE2']}; color: {p['TEXT']}; }}
QPushButton#nav:checked {{ background: {p['SELECTED_ROW']}; color: {p['TEXT']}; font-weight: 600; }}

QComboBox, QSpinBox, QDoubleSpinBox {{ background: {p['SURFACE2']}; border: 1px solid {p['BORDER']};
    border-radius: 6px; padding: 5px 8px; min-height: 20px; color: {p['TEXT']}; }}
QComboBox:focus, QSpinBox:focus {{ border-color: {p['ACCENT']}; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{ image: none; border-left: 4px solid transparent;
    border-right: 4px solid transparent; border-top: 5px solid {p['MUTED']};
    margin-right: 8px; }}
QComboBox QAbstractItemView {{ background: {p['SURFACE2']}; border: 1px solid {p['BORDER']};
    selection-background-color: {p['SELECTED_ROW']}; outline: none; }}

QTableWidget, QTreeView, QTableView {{ background: {p['SURFACE']};
    alternate-background-color: {p['SURFACE2']}; border: 1px solid {p['BORDER']};
    border-radius: 8px; gridline-color: {p['BORDER']};
    selection-background-color: {p['SELECTED_ROW']}; selection-color: {p['TEXT']}; }}
QHeaderView::section {{ background: {p['SURFACE2']}; color: {p['MUTED']}; border: none;
    border-bottom: 1px solid {p['BORDER']}; padding: 7px; font-weight: 600; }}
QTableCornerButton::section {{ background: {p['SURFACE2']}; border: none; }}

QListWidget#nav {{ background: {p['SURFACE']}; border: none;
    border-right: 1px solid {p['BORDER']}; outline: none; font-size: 13px; }}
QListWidget#nav::item {{ padding: 2px; margin: 2px 8px; border-radius: 6px; }}

QStatusBar {{ background: {p['SURFACE']}; border-top: 1px solid {p['BORDER']};
    color: {p['MUTED']}; }}

QGroupBox {{ border: 1px solid {p['BORDER']}; border-radius: 8px; margin-top: 14px;
    padding: 14px 10px 10px; font-weight: 600; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 6px;
    color: {p['MUTED']}; }}

QCheckBox {{ spacing: 6px; }}
QCheckBox::indicator {{ width: 15px; height: 15px; border-radius: 4px;
    border: 1px solid {p['BORDER']}; background: {p['SURFACE2']}; }}
QCheckBox::indicator:checked {{ background: {p['ACCENT']}; border-color: {p['ACCENT']}; }}
QCheckBox:disabled {{ color: {p['MUTED']}; }}

QScrollBar:vertical {{ background: {p['BG']}; width: 11px; border: none; }}
QScrollBar::handle:vertical {{ background: {p['BORDER']}; border-radius: 5px;
    min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {p['SCROLL_HOVER']}; }}
QScrollBar:horizontal {{ background: {p['BG']}; height: 11px; border: none; }}
QScrollBar::handle:horizontal {{ background: {p['BORDER']}; border-radius: 5px;
    min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}

QSplitter::handle {{ background: {p['BORDER']}; }}
QSplitter::handle:horizontal {{ width: 2px; }}

QLabel#value {{ font-size: 14px; font-weight: 600; }}
"""


# graph series colors (cycle for selected PIDs) — legible on both themes
SERIES_COLORS = (
    "#2f81f7",
    "#3fb950",
    "#f0883e",
    "#db61a2",
    "#a371f7",
    "#e3b341",
    "#39c5cf",
    "#ff7b72",
)

# Back-compat: the dark stylesheet under its historical name.
APP_STYLESHEET = build_stylesheet(DARK_PALETTE)

# Rebindable module constants — start on the dark palette.
BG = DARK_PALETTE["BG"]
SURFACE = DARK_PALETTE["SURFACE"]
SURFACE2 = DARK_PALETTE["SURFACE2"]
BORDER = DARK_PALETTE["BORDER"]
TEXT = DARK_PALETTE["TEXT"]
MUTED = DARK_PALETTE["MUTED"]
ACCENT = DARK_PALETTE["ACCENT"]
ACCENT_HOVER = DARK_PALETTE["ACCENT_HOVER"]
OK = DARK_PALETTE["OK"]
WARN = DARK_PALETTE["WARN"]
DANGER = DARK_PALETTE["DANGER"]
SELECTED_ROW = DARK_PALETTE["SELECTED_ROW"]
BREACH_BG = DARK_PALETTE["BREACH_BG"]


def _activate_palette(palette: Mapping[str, str]) -> None:
    """Rebind this module's constants to ``palette`` (runtime theme switch)."""
    module = globals()
    for key, value in palette.items():
        module[key] = value


def apply_theme(app: QApplication, mode: str = "dark") -> None:
    """Install the stylesheet + style hint for ``mode`` ("dark" or "light").

    Panel modules that read ``theme.X`` at call time follow immediately;
    widgets with an inline color set earlier refresh on their next update.
    The style is installed once — repeated setStyle() churns Qt's style
    objects (PySide6 6.12.0 has been observed to abort on that path).
    """
    palette = LIGHT_PALETTE if mode == "light" else DARK_PALETTE
    _activate_palette(palette)
    if not app.property("_autodiag_style_set"):
        app.setStyle("Fusion")
        app.setProperty("_autodiag_style_set", True)
    app.setStyleSheet(build_stylesheet(palette))

    import pyqtgraph as pg

    pg.setConfigOptions(
        antialias=True, background=palette["BG"], foreground=palette["MUTED"]
    )
