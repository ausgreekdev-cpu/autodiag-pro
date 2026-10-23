"""Theme builder and runtime theme switching."""

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


def test_apply_theme_light_then_dark_restores(qapp):
    try:
        theme.apply_theme(qapp, "light")
        assert qapp.styleSheet() == theme.build_stylesheet(theme.LIGHT_PALETTE)
        assert theme.BG == theme.LIGHT_PALETTE["BG"]
        assert theme.DANGER == theme.LIGHT_PALETTE["DANGER"]

        theme.apply_theme(qapp, "dark")
        assert qapp.styleSheet() == theme.build_stylesheet(theme.DARK_PALETTE)
        assert theme.BG == theme.DARK_PALETTE["BG"]
        assert theme.DANGER == theme.DARK_PALETTE["DANGER"]
    finally:
        theme.apply_theme(qapp, "dark")  # never leave the suite on light


def test_apply_theme_unknown_mode_falls_back_to_dark(qapp):
    try:
        theme.apply_theme(qapp, "solarized")
        assert qapp.styleSheet() == theme.build_stylesheet(theme.DARK_PALETTE)
        assert theme.BG == theme.DARK_PALETTE["BG"]
    finally:
        theme.apply_theme(qapp, "dark")


def test_semantic_colors_differ_between_themes():
    assert theme.DARK_PALETTE["OK"] != theme.LIGHT_PALETTE["OK"]
    assert theme.DARK_PALETTE["DANGER"] != theme.LIGHT_PALETTE["DANGER"]
    assert theme.DARK_PALETTE["MUTED"] != theme.LIGHT_PALETTE["MUTED"]
