"""One opened .eml file, shown as a tab in the shared session-tab pane:
the message's headers, body and attachments, displayed by the same
MessageView the Mbox Browser uses for its preview.
"""

from pathlib import Path

import shiboken6
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QMessageBox, QVBoxLayout, QWidget

from it_toolbox.core import async_utils
from it_toolbox.core.eml_reader import EmlReader
from it_toolbox.widgets import status_bar
from it_toolbox.widgets.message_view import MessageView


class EmlViewerWidget(QWidget):
    #: Emitted once the file has been read, with True on success.
    loaded = Signal(bool)

    def __init__(self, path: str | Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.path = Path(path)
        self._closed = False

        self._view = MessageView()
        layout = QVBoxLayout(self)
        layout.addWidget(self._view)

        self._load()

    def _alive(self) -> bool:
        # The tab can be closed while the file is still being read.
        return not self._closed and shiboken6.isValid(self)

    def _load(self) -> None:
        task = status_bar.begin(self, f"Reading {self.path.name}…")
        path = self.path

        def read():
            reader = EmlReader(path)
            return reader, reader.load()

        async_utils.run_in_background(
            read,
            on_result=lambda result: self._on_loaded(result, task),
            on_error=lambda error: self._on_load_error(error, task),
        )

    def _on_loaded(self, result, task: status_bar.StatusTask) -> None:
        task.finish()
        if not self._alive():
            return
        reader, detail = result
        self._view.show_detail(detail, reader.attachment_bytes)
        self.loaded.emit(True)

    def _on_load_error(self, error: Exception, task: status_bar.StatusTask) -> None:
        if not self._alive():
            task.finish()
            return
        task.finish(f"Couldn't read {self.path.name}")
        self._view.show_error(f"Couldn't read this message: {error}")
        self.loaded.emit(False)
        QMessageBox.warning(self, "Couldn't open .eml file", f"{self.path}\n\n{error}")

    def close_session(self) -> None:
        self._closed = True
