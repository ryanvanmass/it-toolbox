"""A read-only GCS bucket file browser — browse + download only for now
(no upload/delete/rename), styled after tools like rclone browser: a
breadcrumb/path bar, an Up button, and a table of folders (GCS's
delimiter-based simulation of directories) and files.
"""

from collections.abc import Callable

from google.oauth2.credentials import Credentials
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

from it_toolbox.core import async_utils
from it_toolbox.modules.connection_manager import gcp_client
from it_toolbox.modules.connection_manager.models import GcsBucket, GcsEntry

ENTRY_ROLE = Qt.ItemDataRole.UserRole


def format_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


class BucketBrowserWidget(QWidget):
    def __init__(
        self,
        bucket: GcsBucket,
        get_credentials: Callable[[], Credentials],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._bucket = bucket
        self._get_credentials = get_credentials
        self._prefix = ""

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
        self._path_label.setText(f"{self._bucket.name}/{self._prefix}")
        self._up_button.setEnabled(bool(self._prefix))
        self._table.setRowCount(0)
        async_utils.run_in_background(
            lambda: gcp_client.list_objects(self._get_credentials(), self._bucket, self._prefix),
            on_result=self._populate_table,
            on_error=self._on_error,
        )

    def _populate_table(self, entries: list[GcsEntry]) -> None:
        # The tab (and this widget) can be closed while a listing was still
        # in flight — nothing to update if so.
        try:
            self._table.setRowCount(len(entries))
        except RuntimeError:
            return
        for row, entry in enumerate(entries):
            name_item = QTableWidgetItem(("📁 " if entry.is_folder else "") + entry.name)
            name_item.setData(ENTRY_ROLE, entry)
            self._table.setItem(row, 0, name_item)
            size_text = "" if entry.is_folder else format_size(entry.size)
            self._table.setItem(row, 1, QTableWidgetItem(size_text))
            self._table.setItem(row, 2, QTableWidgetItem(entry.updated))

    def _on_item_double_clicked(self, item: QTableWidgetItem) -> None:
        entry: GcsEntry = self._table.item(item.row(), 0).data(ENTRY_ROLE)
        if entry.is_folder:
            self._prefix = entry.full_path
            self._reload()
        else:
            self._download(entry)

    def _go_up(self) -> None:
        trimmed = self._prefix.rstrip("/")
        self._prefix = trimmed.rsplit("/", 1)[0] + "/" if "/" in trimmed else ""
        self._reload()

    def _download(self, entry: GcsEntry) -> None:
        default_name = entry.full_path.rsplit("/", 1)[-1]
        dest, _ = QFileDialog.getSaveFileName(self, "Download File", default_name)
        if not dest:
            return
        self._status_before_download = self._path_label.text()
        self._path_label.setText(f"Downloading {entry.name}…")
        async_utils.run_in_background(
            lambda: gcp_client.download_object(
                self._get_credentials(), self._bucket, entry.full_path, dest
            ),
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
            self._path_label.setText(f"{self._bucket.name}/{self._prefix}")
            QMessageBox.warning(self, "Error", str(error))
        except RuntimeError:
            pass  # tab was closed before the background call finished

    def close_session(self) -> None:
        """No-op — kept so main_view can treat this tab the same as a
        session widget when tearing down tabs; there's no tunnel or
        background process here to actually close."""
