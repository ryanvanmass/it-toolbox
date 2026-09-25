from PySide6.QtWidgets import QComboBox

from it_toolbox.modules.connection_manager.ui.searchable_combo import make_searchable, resolve_data


def _make_combo(qtbot, items):
    combo = QComboBox()
    qtbot.addWidget(combo)
    make_searchable(combo, combo, "search…")
    for text, data in items:
        combo.addItem(text, data)
    combo.setCurrentIndex(-1)
    return combo


def test_resolve_data_returns_none_when_blank(qtbot):
    combo = _make_combo(qtbot, [("a.iso", "/a.iso"), ("b.iso", "/b.iso")])
    assert resolve_data(combo) is None


def test_resolve_data_finds_exact_typed_match_even_without_a_popup_selection(qtbot):
    # This is the regression case: setCurrentText() (and real typed-
    # then-moved-on text) does NOT update currentData() -- confirmed
    # live this silently looked like "nothing selected" before
    # resolve_data() existed.
    combo = _make_combo(qtbot, [("a.iso", "/a.iso"), ("b.iso", "/b.iso")])
    combo.setCurrentText("b.iso")

    assert combo.currentData() is None  # the bug this function works around
    assert resolve_data(combo) == "/b.iso"


def test_resolve_data_returns_none_for_text_matching_nothing(qtbot):
    combo = _make_combo(qtbot, [("a.iso", "/a.iso")])
    combo.setCurrentText("not-in-the-list.iso")
    assert resolve_data(combo) is None


def test_resolve_data_matches_real_selection_via_set_current_index(qtbot):
    combo = _make_combo(qtbot, [("a.iso", "/a.iso"), ("b.iso", "/b.iso")])
    combo.setCurrentIndex(1)
    assert resolve_data(combo) == "/b.iso"
