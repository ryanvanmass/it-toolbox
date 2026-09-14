"""Shared "type to filter" QComboBox wiring -- used by both
CreateVmDialog (OS variant, ~940 real entries; install ISO, a
potentially large per-host library) and ConfigureVmDialog (the same
ISO-picking need for changing an existing VM's CD-ROM media).
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QCompleter, QWidget

# Real ISO filenames (and, to a lesser extent, --osinfo short IDs) easily
# outrun the combo box's own on-screen width -- widening the *popup*
# specifically (Qt doesn't clip a QComboBox's dropdown to its own field
# width) is what actually makes a large library legible, without forcing
# the whole compact form layout wider just to fit one field's content.
SEARCHABLE_POPUP_MIN_WIDTH = 420


def make_searchable(combo: QComboBox, parent: QWidget, placeholder: str) -> QCompleter:
    """Wires a QComboBox up for type-to-filter search over a large list
    (real cases: ~940 --osinfo short IDs, or a large ISO library where
    many entries share a long common prefix/suffix) -- editable so
    typing works at all, NoInsert so a search that doesn't exactly match
    anything can't silently create a bogus new entry, MatchContains
    (not the default MatchStartsWith) since a real library's names
    often need matching a substring in the middle, not just a prefix.
    The completer is bound to the combo's own model, which QComboBox
    mutates in place on clear()/addItem() rather than replacing --
    filtering results automatically stay current as items load in.

    Starts genuinely blank (placeholder text only, no item pre-selected)
    rather than defaulting to a specific entry -- confirmed live that an
    editable combo with no exact-matching text reports currentIndex()
    == -1 and currentData() == None, which is exactly "nothing chosen"
    for every field this is used on so far (an empty OS variant falls
    back to "generic" at submit time; an empty ISO choice means "no
    media"/"eject"), so leaving it blank needs no special-casing beyond
    that at each call site.
    """
    combo.setEditable(True)
    combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
    combo.setCurrentIndex(-1)
    combo.lineEdit().setPlaceholderText(placeholder)
    combo.view().setMinimumWidth(SEARCHABLE_POPUP_MIN_WIDTH)
    completer = QCompleter(combo.model(), parent)
    completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    completer.setFilterMode(Qt.MatchFlag.MatchContains)
    completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
    combo.setCompleter(completer)
    return completer


def resolve_data(combo: QComboBox):
    """The data for whatever the combo's edit text currently says,
    resolved by an exact-text lookup rather than trusting
    currentData() directly.

    Confirmed live, the hard way (a dialog test failure, not a doc):
    currentData() only reflects a completer-popup selection or an
    explicit setCurrentIndex() call -- text that ended up in the box by
    being typed out exactly and then just leaving the field (or,
    equivalently in a test, a plain setCurrentText() call) leaves
    currentIndex()/currentData() completely unchanged, still whatever
    they were before. A real user who types a valid name by hand
    (rather than clicking the actual popup suggestion) and clicks OK
    would otherwise have their choice silently treated as "nothing
    selected" -- exactly the class of bug this project's own testing
    discipline exists to catch before it ships. Every call site that
    needs the *data* behind a searchable combo's choice (not just its
    free-text value, e.g. an OS variant string where any typed text is
    already a valid value) must resolve it through this, not
    combo.currentData().
    """
    index = combo.findText(combo.currentText())
    return combo.itemData(index) if index != -1 else None
