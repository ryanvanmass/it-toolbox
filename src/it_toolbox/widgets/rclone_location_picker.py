"""Shared "where is rclone" prompt — used by both Cloud Storage's sidebar
menu and the Settings page's rclone section, so the override lives in one
place (core/settings.py's rclone_path) no matter which one set it.
"""

from PySide6.QtWidgets import QFileDialog, QWidget

from it_toolbox.core import settings


def prompt_for_rclone_path(parent: QWidget) -> str | None:
    """Shows a file picker for the rclone executable and saves the choice.
    Returns the chosen path, or None if the user cancelled."""
    current = settings.load_rclone_path() or ""
    path, _ = QFileDialog.getOpenFileName(parent, "Locate the rclone executable", current)
    if not path:
        return None
    settings.save_rclone_path(path)
    return path


def clear_rclone_path() -> None:
    settings.save_rclone_path(None)
