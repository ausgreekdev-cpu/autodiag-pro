"""Theme builder and palette switching (pure — the shared QApplication is
never re-styled here: repeated setStyleSheet churn aborts CI workers under
PySide6 6.12.0, the same bug family documented for the conftest teardown).
The live app path (app.py reads the pref and calls apply_theme once) is
covered by the Settings combo tests: pref save + callback wiring.
"""

from __future__ import annotations

import re

from autodiag.ui import theme


def test_dark_stylesheet_unchanged_structure():
    dark = theme.build_stylesheet(theme.DARK_PALETTE)
    assert "#0f141a" in dark
    assert "QLabel#heading" in dark
    assert theme.APP_STYLESHEET == dark  # back-compat name equals dark build


def test_light_stylesheet_uses_light_colors():
    light = theme.build_stylesheet(theme.LIGHT_PALETTE)
    assert "#ffffff" in light
    assert "#0f141a" not in light
    assert "QLabel#heading" in light


def test_palettes_have_identical_selectors():
    def selectors(qss: str) -> set[str]:
        return set(re.findall(r"^[A-Za-z#\[\]:, ]+(?= \{)", qss, re.M))

    dark = theme.build_stylesheet(theme.DARK_PALETTE)
    light = theme.build_stylesheet(theme.LIGHT_PALETTE)
    assert selectors(dark) == selectors(light)


def test_activate_palette_rebinds_module_constants():
    try:
        theme._activate_palette(theme.LIGHT_PALETTE)
        assert theme.BG == theme.LIGHT_PALETTE["BG"]
        assert theme.MUTED == theme.LIGHT_PALETTE["MUTED"]
        assert theme.DANGER == theme.LIGHT_PALETTE["DANGER"]
        # module-attribute readers (the pattern panels use) follow
        from autodiag.ui.panels import overview  # noqa: F401

        assert theme.BG == theme.LIGHT_PALETTE["BG"]
    finally:
        theme._activate_palette(theme.DARK_PALETTE)  # never leave light active
    assert theme.BG == theme.DARK_PALETTE["BG"]
    assert theme.DANGER == theme.DARK_PALETTE["DANGER"]


def test_activate_palette_unknown_keys_ignored():
    before = dict(theme.LIGHT_PALETTE)
    try:
        theme._activate_palette({"NOT_A_PALETTE_KEY": "red"})
        assert theme.BG == theme.DARK_PALETTE["BG"]  # untouched
    finally:
        theme._activate_palette(theme.DARK_PALETTE)
    assert theme.BG == before["BG"] or theme.BG == theme.DARK_PALETTE["BG"]


def test_semantic_colors_differ_between_themes():
    assert theme.DARK_PALETTE["OK"] != theme.LIGHT_PALETTE["OK"]
    assert theme.DARK_PALETTE["DANGER"] != theme.LIGHT_PALETTE["DANGER"]
    assert theme.DARK_PALETTE["MUTED"] != theme.LIGHT_PALETTE["MUTED"]
