"""Dark theme: palette constants + application-wide stylesheet."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication

# palette -------------------------------------------------------------------
BG = "#0f141a"
SURFACE = "#171e26"
SURFACE2 = "#1e2732"
BORDER = "#2a3441"
TEXT = "#e6edf3"
MUTED = "#8b949e"
ACCENT = "#2f81f7"
ACCENT_HOVER = "#4593f8"
OK = "#3fb950"
WARN = "#e3b341"
DANGER = "#f85149"
SELECTED_ROW = "#1d3a5f"
BREACH_BG = "#4a3a12"  # amber fill for a value cell that crossed an alert limit

# graph series colors (cycle for selected PIDs)
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

APP_STYLESHEET = f"""
QMainWindow, QDialog {{ background: {BG}; }}
QWidget {{ color: {TEXT}; font-size: 13px; }}
QToolTip {{ background: {SURFACE2}; color: {TEXT}; border: 1px solid {BORDER}; padding: 4px; }}

QToolBar {{ background: {SURFACE}; border: none; border-bottom: 1px solid {BORDER};
    padding: 8px 10px; spacing: 8px; }}
QLabel#chip {{ background: {SURFACE2}; border: 1px solid {BORDER}; border-radius: 12px;
    padding: 3px 12px; color: {MUTED}; }}
QLabel#chip[data-live="1"] {{ color: {OK}; border-color: {OK}; }}
QLabel#heading {{ font-size: 16px; font-weight: 600; }}
QLabel#subtle {{ color: {MUTED}; }}

QPushButton {{ background: {SURFACE2}; border: 1px solid {BORDER}; border-radius: 6px;
    padding: 6px 14px; color: {TEXT}; }}
QPushButton:hover {{ background: #263140; border-color: #3a4653; }}
QPushButton:pressed {{ background: #1a222c; }}
QPushButton:disabled {{ color: {MUTED}; background: {SURFACE}; border-color: {BORDER}; }}
QPushButton#primary {{ background: {ACCENT}; border: 1px solid {ACCENT};
    font-weight: 600; }}
QPushButton#primary:hover {{ background: {ACCENT_HOVER}; border-color: {ACCENT_HOVER}; }}
QPushButton#primary:pressed {{ background: #2671d4; }}
QPushButton#primary:disabled {{ background: {SURFACE2}; border-color: {BORDER};
    color: {MUTED}; }}
QPushButton#danger {{ background: transparent; border: 1px solid {DANGER};
    color: {DANGER}; font-weight: 600; }}
QPushButton#danger:hover {{ background: {DANGER}; color: white; }}
QPushButton#danger:disabled {{ background: {SURFACE}; border-color: {BORDER};
    color: {MUTED}; }}
QPushButton#nav {{ text-align: left; background: transparent; border: none;
    border-radius: 6px; padding: 9px 14px; color: {MUTED}; }}
QPushButton#nav:hover {{ background: {SURFACE2}; color: {TEXT}; }}
QPushButton#nav:checked {{ background: {SELECTED_ROW}; color: {TEXT}; font-weight: 600; }}

QComboBox, QSpinBox, QDoubleSpinBox {{ background: {SURFACE2}; border: 1px solid {BORDER};
    border-radius: 6px; padding: 5px 8px; min-height: 20px; }}
QComboBox:focus, QSpinBox:focus {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{ image: none; border-left: 4px solid transparent;
    border-right: 4px solid transparent; border-top: 5px solid {MUTED};
    margin-right: 8px; }}
QComboBox QAbstractItemView {{ background: {SURFACE2}; border: 1px solid {BORDER};
    selection-background-color: {SELECTED_ROW}; outline: none; }}

QTableWidget, QTreeView, QTableView {{ background: {SURFACE};
    alternate-background-color: {SURFACE2}; border: 1px solid {BORDER};
    border-radius: 8px; gridline-color: {BORDER};
    selection-background-color: {SELECTED_ROW}; selection-color: {TEXT}; }}
QHeaderView::section {{ background: {SURFACE2}; color: {MUTED}; border: none;
    border-bottom: 1px solid {BORDER}; padding: 7px; font-weight: 600; }}
QTableCornerButton::section {{ background: {SURFACE2}; border: none; }}

QListWidget#nav {{ background: {SURFACE}; border: none;
    border-right: 1px solid {BORDER}; outline: none; font-size: 13px; }}
QListWidget#nav::item {{ padding: 2px; margin: 2px 8px; border-radius: 6px; }}

QStatusBar {{ background: {SURFACE}; border-top: 1px solid {BORDER};
    color: {MUTED}; }}

QGroupBox {{ border: 1px solid {BORDER}; border-radius: 8px; margin-top: 14px;
    padding: 14px 10px 10px; font-weight: 600; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 6px;
    color: {MUTED}; }}

QCheckBox {{ spacing: 6px; }}
QCheckBox::indicator {{ width: 15px; height: 15px; border-radius: 4px;
    border: 1px solid {BORDER}; background: {SURFACE2}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QCheckBox:disabled {{ color: {MUTED}; }}

QScrollBar:vertical {{ background: {BG}; width: 11px; border: none; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 5px;
    min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #3a4653; }}
QScrollBar:horizontal {{ background: {BG}; height: 11px; border: none; }}
QScrollBar::handle:horizontal {{ background: {BORDER}; border-radius: 5px;
    min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}

QSplitter::handle {{ background: {BORDER}; }}
QSplitter::handle:horizontal {{ width: 2px; }}

QLabel#value {{ font-size: 14px; font-weight: 600; }}
"""


def apply_theme(app: QApplication) -> None:
    """Install the dark stylesheet, style hint and pyqtgraph defaults."""
    app.setStyle("Fusion")
    app.setStyleSheet(APP_STYLESHEET)

    import pyqtgraph as pg

    pg.setConfigOptions(antialias=True, background=BG, foreground=MUTED)
