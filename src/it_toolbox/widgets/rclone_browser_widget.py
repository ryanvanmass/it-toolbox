"""A read-only rclone remote file browser — browse + download only for
now (no upload/delete/rename). Near-identical in shape to
bucket_browser_widget.py (breadcrumb/path bar, Up button, a table of
folders and files), generalized from GCS's bucket+prefix model to any
rclone remote+path via rclone_client's lsjson/copyto wrappers.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from it_toolbox.core import async_utils, rclone_client
from it_toolbox.modules.cloud_storage.models import RcloneEntry
from it_toolbox.widgets.bucket_browser_widget import format_size

ENTRY_ROLE = Qt.ItemDataRole.UserRole


def _join(base: str, name: str) -> str:
    return f"{base}/{name}" if base else name


class RcloneBrowserWidget(QWidget):
    def __init__(
        self, remote_name: str, start_path: str = "", parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._remote_name = remote_name
        self._path = start_path

        self._up_button = QPushButton("Up")
        self._up_button.clicked.connect(self._go_up)
        self._path_label = QLabel()
        self._refresh_button = QPushButton("Refresh")
        self._refresh_button.clicked.connect(self._reload)

        top_bar = QHBoxLayout()
        top_bar.addWidget(self._up_button)
        top_bar.addWidget(self._path_label, 1)
        top_bar.addWidget(self._refresh_button)

        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["Name", "Size", "Modified"])
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.itemDoubleClicked.connect(self._on_item_double_clicked)

        layout = QVBoxLayout(self)
        layout.addLayout(top_bar)
        layout.addWidget(self._table)

        self._reload()

    def _reload(self) -> None:
        self._path_label.setText(f"{self._remote_name}:/{self._path}")
        self._up_button.setEnabled(bool(self._path))
        self._table.setRowCount(0)
        async_utils.run_in_background(
            lambda: rclone_client.list_directory(self._remote_name, self._path),
            on_result=self._populate_table,
            on_error=self._on_error,
        )

    def _populate_table(self, entries: list[RcloneEntry]) -> None:
        # The tab (and this widget) can be closed while a listing was still
        # in flight — nothing to update if so.
        try:
            self._table.setRowCount(len(entries))
        except RuntimeError:
            return
        for row, entry in enumerate(entries):
            name_item = QTableWidgetItem(("📁 " if entry.is_dir else "") + entry.name)
            name_item.setData(ENTRY_ROLE, entry)
            self._table.setItem(row, 0, name_item)
            size_text = "" if entry.is_dir else format_size(entry.size)
            self._table.setItem(row, 1, QTableWidgetItem(size_text))
            self._table.setItem(row, 2, QTableWidgetItem(entry.modified))

    def _on_item_double_clicked(self, item: QTableWidgetItem) -> None:
        entry: RcloneEntry = self._table.item(item.row(), 0).data(ENTRY_ROLE)
        if entry.is_dir:
            self._path = _join(self._path, entry.path)
            self._reload()
        else:
            self._download(entry)

    def _go_up(self) -> None:
        self._path = self._path.rsplit("/", 1)[0] if "/" in self._path else ""
        self._reload()

    def _download(self, entry: RcloneEntry) -> None:
        full_path = _join(self._path, entry.path)
        dest, _ = QFileDialog.getSaveFileName(self, "Download File", entry.name)
        if not dest:
            return
        self._status_before_download = self._path_label.text()
        self._path_label.setText(f"Downloading {entry.name}…")
        async_utils.run_in_background(
            lambda: rclone_client.download(self._remote_name, full_path, dest),
            on_result=lambda _: self._on_download_done(),
            on_error=self._on_error,
        )

    def _on_download_done(self) -> None:
        try:
            self._path_label.setText(self._status_before_download)
        except RuntimeError:
            pass  # tab was closed before the download finished

    def _on_error(self, error: Exception) -> None:
        try:
            self._path_label.setText(f"{self._remote_name}:/{self._path}")
            QMessageBox.warning(self, "Error", str(error))
        except RuntimeError:
            pass  # tab was closed before the background call finished

    def close_session(self) -> None:
        """No-op — kept so main_view can treat this tab the same as a
        session widget when tearing down tabs; there's no live process
        here to actually close."""
