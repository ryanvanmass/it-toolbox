"""Checks for the safety nets in tests/conftest.py."""

import pytest
from PySide6.QtWidgets import QMessageBox


@pytest.mark.parametrize("kind", ["warning", "critical", "information", "question", "about"])
def test_an_unmocked_message_box_fails_instead_of_blocking(kind):
    with pytest.raises(AssertionError, match=f"Unexpected blocking QMessageBox.{kind}"):
        getattr(QMessageBox, kind)(None, "Title", "text")


def test_a_test_can_still_patch_a_message_box_itself(monkeypatch):
    monkeypatch.setattr(
        QMessageBox, "warning", lambda *a, **k: QMessageBox.StandardButton.Ok
    )

    assert QMessageBox.warning(None, "Title", "text") == QMessageBox.StandardButton.Ok
