from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication

import pytest

from it_toolbox.ui import theme


@pytest.fixture(autouse=True)
def _restore_unthemed_app(qapp):
    """Undo apply() after each test: the rest of the suite runs unthemed,
    and leaving the app stylesheet behind makes every later widget test
    noticeably slower (and timing-sensitive ones flaky)."""
    style = qapp.style().name()
    palette = qapp.palette()
    yield
    qapp.setStyleSheet("")
    qapp.setStyle(style)
    qapp.setPalette(palette)


def test_explicit_modes_pick_their_palette(qapp):
    theme.apply(qapp, "dark")
    assert theme.is_dark()
    assert qapp.palette().color(QPalette.ColorRole.Window).name() == theme.DARK.window

    theme.apply(qapp, "light")
    assert not theme.is_dark()
    assert qapp.palette().color(QPalette.ColorRole.Window).name() == theme.LIGHT.window


def test_unknown_mode_falls_back_to_system(qapp):
    theme.apply(qapp, "purple")
    assert theme._mode == "system"


def test_apply_announces_the_change(qapp):
    seen = []
    theme.events.changed.connect(lambda: seen.append(True))
    theme.apply(qapp, "light")
    assert seen


def test_bundled_icons_tint_and_missing_ones_are_empty(qapp):
    assert not theme.icon("settings").isNull()
    assert theme.icon("no-such-icon").isNull()


def test_stylesheet_glyphs_are_written_for_each_tint(qapp):
    path = theme._glyph("check", "#123456")
    with open(path, encoding="utf-8") as f:
        assert "#123456" in f.read()


def test_label_style_uses_the_current_tokens(qapp):
    theme.apply(QApplication.instance(), "dark")
    try:
        assert theme.label_style("danger") == f"color: {theme.DARK.danger};"
    finally:
        theme.apply(qapp, "light")
