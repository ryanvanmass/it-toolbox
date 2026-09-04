"""An rclone remote file browser — browse, download, upload, and delete.
Near-identical in shape to bucket_browser_widget.py (breadcrumb/path
bar, Up button, a table of folders and files), generalized from GCS's
bucket+prefix model to any rclone remote+path via rclone_client's
lsjson/copyto/deletefile/purge wrappers. No rename — rclone has no
single "rename" primitive beyond move, and that's not needed yet.

The path bar is a clickable breadcrumb (Windows Explorer-style): one
button per path segment, each jumping straight to that ancestor
directory, with only the current (last) segment inert.
"""

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
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
        self._breadcrumb_layout = QHBoxLayout()
        self._breadcrumb_layout.setContentsMargins(0, 0, 0, 0)
        self._breadcrumb_layout.setSpacing(2)
        self._upload_button = QPushButton("Upload")
        self._upload_button.clicked.connect(self._on_upload_clicked)
        self._refresh_button = QPushButton("Refresh")
        self._refresh_button.clicked.connect(self._reload)

        top_bar = QHBoxLayout()
        top_bar.addWidget(self._up_button)
        top_bar.addLayout(self._breadcrumb_layout, 1)
        top_bar.addWidget(self._upload_button)
        top_bar.addWidget(self._refresh_button)

        self._status_label = QLabel()
        self._status_label.setStyleSheet("color: gray; font-style: italic;")
        self._status_label.setVisible(False)

        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["Name", "Size", "Modified"])
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_table_context_menu)

        layout = QVBoxLayout(self)
        layout.addLayout(top_bar)
        layout.addWidget(self._status_label)
        layout.addWidget(self._table)

        self._reload()

    def _reload(self) -> None:
        self._update_breadcrumb()
        self._up_button.setEnabled(bool(self._path))
        self._table.setRowCount(0)
        async_utils.run_in_background(
            lambda: rclone_client.list_directory(self._remote_name, self._path),
            on_result=self._populate_table,
            on_error=self._on_error,
        )

    def _update_breadcrumb(self) -> None:
        while self._breadcrumb_layout.count():
            item = self._breadcrumb_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        parts = [p for p in self._path.split("/") if p]
        for i in range(len(parts) + 1):
            is_current = i == len(parts)
            button = QPushButton(self._remote_name if i == 0 else parts[i - 1])
            button.setFlat(True)
            button.setEnabled(not is_current)
            if not is_current:
                button.setCursor(Qt.CursorShape.PointingHandCursor)
                target_path = "/".join(parts[:i])
                button.clicked.connect(
                    lambda checked=False, p=target_path: self._navigate_to(p)
                )
            self._breadcrumb_layout.addWidget(button)
            if not is_current:
                self._breadcrumb_layout.addWidget(QLabel("›"))
        self._breadcrumb_layout.addStretch(1)

    def _navigate_to(self, path: str) -> None:
        self._path = path
        self._reload()

    def _set_status(self, text: str) -> None:
        self._status_label.setText(text)
        self._status_label.setVisible(bool(text))

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
        self._set_status(f"Downloading {entry.name}…")
        async_utils.run_in_background(
            lambda: rclone_client.download(self._remote_name, full_path, dest),
            on_result=lambda _: self._on_download_done(),
            on_error=self._on_error,
        )

    def _on_download_done(self) -> None:
        try:
            self._set_status("")
        except RuntimeError:
            pass  # tab was closed before the download finished

    def _on_upload_clicked(self) -> None:
        local_path, _ = QFileDialog.getOpenFileName(self, "Upload File")
        if not local_path:
            return
        dest_path = _join(self._path, os.path.basename(local_path))
        self._set_status(f"Uploading {os.path.basename(local_path)}…")
        async_utils.run_in_background(
            lambda: rclone_client.upload(self._remote_name, local_path, dest_path),
            on_result=lambda _: self._on_upload_done(),
            on_error=self._on_error,
        )

    def _on_upload_done(self) -> None:
        try:
            self._set_status("")
        except RuntimeError:
            return  # tab was closed before the upload finished
        self._reload()

    def _build_entry_menu(self, entry: RcloneEntry) -> tuple[QMenu, object, object]:
        """Returns (menu, download_action_or_None, delete_action) — split
        out from _on_table_context_menu so tests can inspect the menu's
        contents without exec()ing it (which blocks for real).
        """
        menu = QMenu(self)
        download_action = menu.addAction("Download") if not entry.is_dir else None
        delete_action = menu.addAction("Delete")
        return menu, download_action, delete_action

    def _on_table_context_menu(self, pos) -> None:
        row = self._table.indexAt(pos).row()
        if row < 0:
            return
        entry: RcloneEntry = self._table.item(row, 0).data(ENTRY_ROLE)
        menu, download_action, delete_action = self._build_entry_menu(entry)
        chosen = menu.exec(self._table.viewport().mapToGlobal(pos))
        if download_action is not None and chosen is download_action:
            self._download(entry)
        elif chosen is delete_action:
            self._delete_entry(entry)

    def _delete_entry(self, entry: RcloneEntry) -> None:
        kind = "folder and everything in it" if entry.is_dir else "file"
        confirmed = QMessageBox.question(
            self,
            "Delete",
            f'Delete the {kind} "{entry.name}"? This cannot be undone.',
        )
        if confirmed != QMessageBox.StandardButton.Yes:
            return
        full_path = _join(self._path, entry.path)
        delete_call = rclone_client.delete_directory if entry.is_dir else rclone_client.delete_file
        async_utils.run_in_background(
            lambda: delete_call(self._remote_name, full_path),
            on_result=lambda _: self._reload(),
            on_error=self._on_error,
        )

    def _on_error(self, error: Exception) -> None:
        try:
            self._set_status("")
            QMessageBox.warning(self, "Error", str(error))
        except RuntimeError:
            pass  # tab was closed before the background call finished

    def close_session(self) -> None:
        """No-op — kept so main_view can treat this tab the same as a
        session widget when tearing down tabs; there's no live process
        here to actually close."""
