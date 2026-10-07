"""Preview of one email message: its headers, body and attachments, with
double-click to open an attachment and right-click to save it. Shared by
the Mbox Browser (for the selected message) and the EML Viewer.
"""

import shutil
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

import shiboken6
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QStyle,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from it_toolbox.core import async_utils
from it_toolbox.core.mbox_reader import Attachment, MessageDetail
from it_toolbox.widgets import status_bar

ATTACHMENT_ROLE = Qt.ItemDataRole.UserRole

#: Attachments opened with double-click are written under here, one fresh
#: subfolder per open so same-named attachments never collide. They're not
#: deleted when the message is closed (the app showing one may still be
#: reading it); instead each open sweeps away subfolders older than
#: OPENED_ATTACHMENT_MAX_AGE_S.
OPENED_ATTACHMENTS_DIR = Path(tempfile.gettempdir()) / "it-toolbox-attachments"
OPENED_ATTACHMENT_MAX_AGE_S = 24 * 60 * 60

#: Opening these with the system default app would run them, so the user
#: is asked first.
EXECUTABLE_SUFFIXES = {
    ".app", ".appimage", ".bat", ".cmd", ".com", ".command", ".cpl", ".desktop",
    ".dmg", ".exe", ".hta", ".jar", ".js", ".jse", ".lnk", ".msi", ".msp", ".pif",
    ".pkg", ".ps1", ".reg", ".scr", ".sh", ".vbe", ".vbs", ".wsf", ".wsh",
}  # fmt: skip

#: Returns the decoded bytes of the shown message's attachment with this
#: index. Called on a worker thread.
AttachmentSource = Callable[[int], bytes]


def _safe_filename(filename: str) -> str:
    """The attachment's name with any directory parts and characters that
    aren't valid in a filename on Windows removed."""
    name = filename.replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(c for c in name if c not in '<>:"|?*' and ord(c) >= 32).strip(" .")
    return name or "attachment"


def _sweep_old_opened_attachments() -> None:
    cutoff = time.time() - OPENED_ATTACHMENT_MAX_AGE_S
    try:
        folders = list(OPENED_ATTACHMENTS_DIR.iterdir())
    except OSError:
        return
    for folder in folders:
        try:
            if folder.stat().st_mtime < cutoff:
                shutil.rmtree(folder, ignore_errors=True)
        except OSError:
            pass


def write_attachment_for_opening(filename: str, data: bytes) -> Path:
    """Writes `data` to a new temp folder and returns the file's path."""
    _sweep_old_opened_attachments()
    OPENED_ATTACHMENTS_DIR.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(dir=OPENED_ATTACHMENTS_DIR))
    path = folder / _safe_filename(filename)
    path.write_bytes(data)
    return path


def _format_size(size: int) -> str:
    for unit in ("B", "KB", "MB"):
        if size < 1024:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def write_in_background(
    parent: QWidget, read_bytes: Callable[[], bytes], destination: str
) -> None:
    """Writes `read_bytes()` to `destination` on a worker thread, reporting
    progress in `parent`'s status bar and failures in a dialog."""
    name = Path(destination).name
    task = status_bar.begin(parent, f"Saving {name}…")

    def write():
        Path(destination).write_bytes(read_bytes())

    def on_error(error: Exception) -> None:
        task.finish(f"Couldn't save {name}")
        if not shiboken6.isValid(parent):
            return
        QMessageBox.warning(parent, "Couldn't save file", str(error))

    async_utils.run_in_background(
        write, on_result=lambda _: task.finish(f"Saved {name}"), on_error=on_error
    )


class MessageView(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._attachment_source: AttachmentSource | None = None

        self._headers_label = QLabel()
        self._headers_label.setTextFormat(Qt.TextFormat.PlainText)
        self._headers_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._headers_label.setWordWrap(True)
        self._body_view = QTextBrowser()
        # Links open in the system browser. QTextBrowser never fetches
        # remote resources itself, so tracking pixels in HTML mail stay dark.
        self._body_view.setOpenExternalLinks(True)
        self._attachment_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)
        self._attachments = QListWidget()
        self._attachments.setMaximumHeight(90)
        self._attachments.itemDoubleClicked.connect(self._on_attachment_activated)
        self._attachments.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._attachments.customContextMenuRequested.connect(self._on_attachment_context_menu)
        self._attachments.setToolTip(
            "Double-click an attachment to open it; right-click to save it"
        )
        self._attachments.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._headers_label)
        layout.addWidget(self._body_view, 1)
        layout.addWidget(self._attachments)

    def show_detail(
        self, detail: MessageDetail | None, attachment_source: AttachmentSource | None = None
    ) -> None:
        """Shows `detail` (or clears the view for None). `attachment_source`
        fetches its attachments for opening and saving."""
        self._attachments.clear()
        self._attachment_source = attachment_source if detail is not None else None
        if detail is None:
            self._headers_label.clear()
            self._body_view.clear()
            self._attachments.hide()
            return
        self._headers_label.setText("\n".join(f"{name}: {value}" for name, value in detail.headers))
        if detail.text_body is not None:
            self._body_view.setPlainText(detail.text_body)
        elif detail.html_body is not None:
            self._body_view.setHtml(detail.html_body)
        else:
            self._body_view.setPlainText("(no text content)")
        for attachment in detail.attachments:
            item = QListWidgetItem(
                self._attachment_icon,
                f"{attachment.filename}  ({_format_size(attachment.size)}, "
                f"{attachment.content_type})"
            )
            item.setData(ATTACHMENT_ROLE, attachment)
            self._attachments.addItem(item)
        self._attachments.setVisible(bool(detail.attachments))

    def show_error(self, text: str) -> None:
        self.show_detail(None)
        self._body_view.setPlainText(text)

    # -- Attachments ------------------------------------------------------

    def _on_attachment_activated(self, item: QListWidgetItem) -> None:
        self._open_attachment(item.data(ATTACHMENT_ROLE))

    def _open_attachment(self, attachment: Attachment) -> None:
        """Opens the attachment in the system's default app for its type,
        from a temp copy (see OPENED_ATTACHMENTS_DIR)."""
        source = self._attachment_source
        if source is None:
            return
        if Path(attachment.filename).suffix.lower() in EXECUTABLE_SUFFIXES:
            answer = QMessageBox.question(
                self,
                "Open attachment?",
                f"“{attachment.filename}” is a program or script. Opening it will "
                "run it on this computer.\n\nOnly continue if you trust the sender.",
                QMessageBox.StandardButton.Open | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Open:
                return
        task = status_bar.begin(self, f"Opening {attachment.filename}…")

        def on_written(path: Path) -> None:
            opened = QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
            task.finish("" if opened else f"No app found to open {attachment.filename}")

        def on_error(error: Exception) -> None:
            task.finish(f"Couldn't open {attachment.filename}")
            if shiboken6.isValid(self):
                QMessageBox.warning(self, "Couldn't open attachment", str(error))

        async_utils.run_in_background(
            lambda: write_attachment_for_opening(attachment.filename, source(attachment.index)),
            on_result=on_written,
            on_error=on_error,
        )

    def _on_attachment_context_menu(self, pos) -> None:
        item = self._attachments.itemAt(pos)
        if item is None:
            return
        menu = QMenu(self)
        menu.addAction("Open").triggered.connect(
            lambda: self._open_attachment(item.data(ATTACHMENT_ROLE))
        )
        menu.addAction("Save Attachment…").triggered.connect(
            lambda: self._save_attachment(item.data(ATTACHMENT_ROLE))
        )
        menu.exec(self._attachments.viewport().mapToGlobal(pos))

    def _save_attachment(self, attachment: Attachment) -> None:
        source = self._attachment_source
        if source is None:
            return
        destination, _ = QFileDialog.getSaveFileName(
            self, "Save Attachment", str(Path.home() / _safe_filename(attachment.filename))
        )
        if not destination:
            return
        write_in_background(self, lambda: source(attachment.index), destination)
