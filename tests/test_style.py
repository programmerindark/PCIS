"""Tests for pcis.gui.style theming.

These exist because the app shipped twice with the same class of bug:
a stylesheet that only ever defined light colours, so on a desktop set
to dark mode any widget the stylesheet did not explicitly name fell
through to the system palette. The result was authored dark text on a
system dark background -- the engineering explanation, the densest and
most important panel in the app, was effectively invisible.
"""

from __future__ import annotations

import re

import pytest

from pcis.gui import style


def test_both_palettes_define_exactly_the_same_keys():
    # A key present in one theme but not the other is a KeyError waiting
    # for whichever user runs the other theme.
    assert set(style.LIGHT) == set(style.DARK)


def test_every_palette_value_is_a_hex_colour():
    for name, palette in (("LIGHT", style.LIGHT), ("DARK", style.DARK)):
        for key, value in palette.items():
            assert re.fullmatch(r"#[0-9a-fA-F]{6}", value), f"{name}[{key}] = {value!r}"


def test_stylesheet_contains_no_hardcoded_colours():
    # Any literal hex in the generated stylesheet is a colour that cannot
    # follow the theme -- exactly how the table header band stayed white
    # on a dark window.
    import inspect

    source = inspect.getsource(style.build_stylesheet)
    body = source[source.index('return f"""'):]
    leftovers = sorted(set(re.findall(r"#[0-9a-fA-F]{6}", body)))
    assert not leftovers, f"hardcoded colours in stylesheet: {leftovers}"


def test_light_and_dark_stylesheets_actually_differ():
    assert style.build_stylesheet(style.LIGHT) != style.build_stylesheet(style.DARK)


def test_dark_stylesheet_uses_dark_surface_colours():
    css = style.build_stylesheet(style.DARK)
    assert style.DARK["SURFACE"] in css
    assert style.LIGHT["SURFACE"] not in css


@pytest.mark.parametrize("widget", ["QTextBrowser", "QTableWidget", "QListWidget",
                                    "QMenu", "QMessageBox", "QHeaderView"])
def test_text_bearing_widgets_are_explicitly_styled(widget):
    # Anything that paints text on its own background must be named in
    # the stylesheet, or it inherits the system palette independently of
    # the text colour we set.
    assert widget in style.build_stylesheet(style.DARK)


def test_apply_theme_rebinds_the_module_level_colour_constants(qapp):
    style.apply_theme(qapp, dark=True)
    assert style.INK == style.DARK["INK"]
    assert style.active()["SURFACE"] == style.DARK["SURFACE"]

    style.apply_theme(qapp, dark=False)
    assert style.INK == style.LIGHT["INK"]
    assert style.active()["SURFACE"] == style.LIGHT["SURFACE"]


def test_status_color_thresholds_are_ordered():
    good = style.status_color(0.9)
    mid = style.status_color(0.6)
    bad = style.status_color(0.2)
    assert good != mid != bad
