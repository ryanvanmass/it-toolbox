"""A FileZilla-style dual-pane FTP/SFTP client — local filesystem on the
left, the remote host on the right, a transfer queue underneath. One
FtpBrowserWidget owns one ftp_client.SftpSession/FtpSession for its
whole life (see core/ftp_client.py's module docstring for why that's a
single persistent connection rather than rclone_browser_widget.py's
per-call CLI invocation).

Transfers land straight in the other pane's current directory (double-
click, or "Download"/"Upload" from the context menu) rather than
prompting a save-file dialog per file — that's what makes this a
dual-pane browser instead of a single-pane one like
rclone_browser_widget.py/bucket_browser_widget.py. They're queued and
run one at a time on a background thread (core.async_utils), since a
single SFTP/FTP connection isn't safe for concurrent calls; a
_TransferSignals bridge marshals each transfer's progress callback
(invoked on that background thread) back onto the Qt main thread.

Known v1 limitations, tracked in docs/ftp-sftp-client-status.md: no
recursive folder transfers (only individual files), and no drag-and-drop
between panes or from the OS file manager — only double-click and the
context menu's Download/Upload actions.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from it_toolbox.core import async_utils, ftp_client
from it_toolbox.widgets.bucket_browser_widget import format_size

ENTRY_ROLE = Qt.ItemDataRole.UserRole


def _format_modified(epoch_seconds: float) -> str:
    if not epoch_seconds:
        return ""
    import datetime

    return datetime.datetime.fromtimestamp(epoch_seconds).strftime("%Y-%m-%d %H:%M")


class _FilePaneWidget(QWidget):
    """One side of the dual-pane browser — a path bar, Up/Refresh
    buttons, and a table of entries. Purely a view: all listing/
    navigation logic lives in FtpBrowserWidget, which owns two of these
    (one local, one remote) and wires their signals up identically.
    """

    path_submitted = Signal(str)
    up_clicked = Signal()
    refresh_clicked = Signal()
    item_activated = Signal(int)
    context_menu_requested = Signal(object)

    def __init__(self, title: str, show_permissions: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._show_permissions = show_permissions

        self._path_edit = QLineEdit()
        self._path_edit.returnPressed.connect(
            lambda: self.path_submitted.emit(self._path_edit.text())
        )
        up_button = QPushButton("Up")
        up_button.clicked.connect(self.up_clicked)
        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self.refresh_clicked)

        top_bar = QHBoxLayout()
        top_bar.addWidget(up_button)
        top_bar.addWidget(self._path_edit, 1)
        top_bar.addWidget(refresh_button)

        columns = ["Name", "Size", "Modified"] + (["Permissions"] if show_permissions else [])
        self._table = QTableWidget(0, len(columns))
        self._table.setHorizontalHeaderLabels(columns)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.itemDoubleClicked.connect(lambda item: self.item_activated.emit(item.row()))
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(
            lambda pos: self.context_menu_requested.emit(pos)
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel(f"<b>{title}</b>"))
        layout.addLayout(top_bar)
        layout.addWidget(self._table)

    def set_path(self, path: str) -> None:
        self._path_edit.setText(path)

    def set_entries(self, entries: list[ftp_client.FileEntry]) -> None:
        try:
            self._table.setRowCount(len(entries))
        except RuntimeError:
            return  # the tab was closed while a listing was still in flight
        for row, entry in enumerate(entries):
            name_item = QTableWidgetItem(("📁 " if entry.is_dir else "") + entry.name)
            name_item.setData(ENTRY_ROLE, entry)
            self._table.setItem(row, 0, name_item)
            self._table.setItem(row, 1, QTableWidgetItem("" if entry.is_dir else format_size(entry.size)))
            self._table.setItem(row, 2, QTableWidgetItem(_format_modified(entry.modified)))
            if self._show_permissions:
                self._table.setItem(row, 3, QTableWidgetItem(entry.permissions))

    def entry_at(self, row: int) -> ftp_client.FileEntry:
        return self._table.item(row, 0).data(ENTRY_ROLE)

    def selected_entries(self) -> list[ftp_client.FileEntry]:
        rows = sorted({index.row() for index in self._table.selectedIndexes()})
        return [self.entry_at(row) for row in rows]

    def map_to_global(self, pos):
        return self._table.viewport().mapToGlobal(pos)


class _TransferSignals(QObject):
    # (transfer_id, bytes_transferred, total_bytes) -- emitted from the
    # background transfer thread, delivered to the main thread via Qt's
    # normal cross-thread queued-connection behavior.
    progress = Signal(int, int, int)


@dataclass
class _TransferJob:
    id: int
    direction: str  # "upload" or "download"
    name: str
    local_path: str
    remote_path: str
    size: int


class FtpBrowserWidget(QWidget):
    def __init__(
        self, session: ftp_client.SftpSession | ftp_client.FtpSession, display_name: str, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._session = session
        self._display_name = display_name
        self._local_path = str(Path.home())
        self._remote_path = "/"

        self._next_transfer_id = 0
        self._pending_transfers: list[_TransferJob] = []
        self._transfer_in_progress = False
        self._transfer_rows: dict[int, int] = {}

        self._transfer_signals = _TransferSignals()
        self._transfer_signals.progress.connect(self._on_transfer_progress)

        self._status_label = QLabel(f"Connecting to {display_name}…")
        self._status_label.setStyleSheet("color: gray; font-style: italic;")

        self._local_pane = _FilePaneWidget("Local", show_permissions=True)
        self._local_pane.path_submitted.connect(self._navigate_local)
        self._local_pane.up_clicked.connect(self._local_up)
        self._local_pane.refresh_clicked.connect(self._reload_local)
        self._local_pane.item_activated.connect(self._on_local_item_activated)
        self._local_pane.context_menu_requested.connect(self._on_local_context_menu)

        self._remote_pane = _FilePaneWidget("Remote", show_permissions=(session.kind == "sftp"))
        self._remote_pane.path_submitted.connect(self._navigate_remote)
        self._remote_pane.up_clicked.connect(self._remote_up)
        self._remote_pane.refresh_clicked.connect(self._reload_remote)
        self._remote_pane.item_activated.connect(self._on_remote_item_activated)
        self._remote_pane.context_menu_requested.connect(self._on_remote_context_menu)

        panes = QHBoxLayout()
        panes.addWidget(self._local_pane, 1)
        panes.addWidget(self._remote_pane, 1)

        self._queue_table = QTableWidget(0, 4)
        self._queue_table.setHorizontalHeaderLabels(["File", "Direction", "Progress", "Status"])
        self._queue_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._queue_table.verticalHeader().setVisible(False)
        self._queue_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._queue_table.setMaximumHeight(160)

        layout = QVBoxLayout(self)
        layout.addWidget(self._status_label)
        layout.addLayout(panes, 3)
        layout.addWidget(QLabel("Transfers"))
        layout.addWidget(self._queue_table, 1)

        self._reload_local()
        self._connect_remote()

    # -- Connect ------------------------------------------------------

    def _connect_remote(self) -> None:
        async_utils.run_in_background(
            self._session.connect, on_result=lambda _: self._on_connected(), on_error=self._on_connect_error
        )

    def _on_connect_error(self, error: Exception) -> None:
        if isinstance(error, ftp_client.UnknownHostKeyError):
            self._prompt_trust_host_key(error)
            return
        self._on_error(error)

    def _prompt_trust_host_key(self, error: ftp_client.UnknownHostKeyError) -> None:
        try:
            self._status_label.setText(f"Unknown host key for {error.hostname}")
        except RuntimeError:
            return  # tab was closed before the connection attempt finished
        confirmed = QMessageBox.question(
            self,
            "Unknown Host Key",
            f"The authenticity of host '{error.hostname}' can't be established.\n"
            f"{error.key.get_name()} key fingerprint is {error.fingerprint}.\n\n"
            "Are you sure you want to continue connecting? This adds the key to your "
            "~/.ssh/known_hosts, the same as accepting it in a regular ssh client would.",
        )
        if confirmed != QMessageBox.StandardButton.Yes:
            self._status_label.setText("Connection cancelled — host key not trusted.")
            return
        self._session.trust_host_key(error.hostname, error.key)
        self._status_label.setText(f"Connecting to {self._display_name}…")
        self._connect_remote()

    def _on_connected(self) -> None:
        try:
            self._remote_path = self._session.home_dir()
        except Exception:  # noqa: BLE001 - fall back to a sane default, not fatal
            self._remote_path = "/"
        try:
            self._status_label.setText(f"Connected to {self._display_name}")
        except RuntimeError:
            return  # tab was closed before the connection finished
        self._reload_remote()

    # -- Local pane -----------------------------------------------------

    def _reload_local(self) -> None:
        self._local_pane.set_path(self._local_path)
        try:
            entries = ftp_client.list_local_dir(self._local_path)
        except OSError as exc:
            QMessageBox.warning(self, "Error", str(exc))
            return
        self._local_pane.set_entries(entries)

    def _navigate_local(self, path: str) -> None:
        path = os.path.expanduser(path.strip()) or self._local_path
        if os.path.isdir(path):
            self._local_path = os.path.normpath(path)
            self._reload_local()
        else:
            QMessageBox.warning(self, "Error", f"Not a directory: {path}")
            self._local_pane.set_path(self._local_path)

    def _local_up(self) -> None:
        parent = os.path.dirname(self._local_path.rstrip(os.sep))
        self._local_path = parent or self._local_path
        self._reload_local()

    def _on_local_item_activated(self, row: int) -> None:
        entry = self._local_pane.entry_at(row)
        full_path = os.path.join(self._local_path, entry.name)
        if entry.is_dir:
            self._local_path = full_path
            self._reload_local()
        else:
            self._upload_paths([full_path])

    def _on_local_context_menu(self, pos) -> None:
        entries = self._local_pane.selected_entries()
        menu = QMenu(self)
        upload_action = menu.addAction("Upload") if any(not e.is_dir for e in entries) else None
        menu.addSeparator()
        new_folder_action = menu.addAction("New Folder…")
        rename_action = menu.addAction("Rename…") if len(entries) == 1 else None
        delete_action = menu.addAction("Delete") if entries else None
        chosen = menu.exec(self._local_pane.map_to_global(pos))
        if upload_action is not None and chosen is upload_action:
            self._upload_paths(
                [os.path.join(self._local_path, e.name) for e in entries if not e.is_dir]
            )
        elif chosen is new_folder_action:
            self._new_local_folder()
        elif rename_action is not None and chosen is rename_action:
            self._rename_local(entries[0])
        elif delete_action is not None and chosen is delete_action:
            self._delete_local(entries)

    def _new_local_folder(self) -> None:
        name, ok = QInputDialog.getText(self, "New Folder", "Folder name:")
        if not ok or not name.strip():
            return
        try:
            os.mkdir(os.path.join(self._local_path, name.strip()))
        except OSError as exc:
            QMessageBox.warning(self, "Error", str(exc))
            return
        self._reload_local()

    def _rename_local(self, entry: ftp_client.FileEntry) -> None:
        new_name, ok = QInputDialog.getText(self, "Rename", "New name:", text=entry.name)
        if not ok or not new_name.strip() or new_name.strip() == entry.name:
            return
        try:
            os.rename(
                os.path.join(self._local_path, entry.name),
                os.path.join(self._local_path, new_name.strip()),
            )
        except OSError as exc:
            QMessageBox.warning(self, "Error", str(exc))
            return
        self._reload_local()

    def _delete_local(self, entries: list[ftp_client.FileEntry]) -> None:
        import shutil

        names = ", ".join(e.name for e in entries)
        confirmed = QMessageBox.question(
            self, "Delete", f'Delete "{names}"? This cannot be undone.'
        )
        if confirmed != QMessageBox.StandardButton.Yes:
            return
        for entry in entries:
            full_path = os.path.join(self._local_path, entry.name)
            try:
                if entry.is_dir:
                    shutil.rmtree(full_path)
                else:
                    os.remove(full_path)
            except OSError as exc:
                QMessageBox.warning(self, "Error", str(exc))
        self._reload_local()

    # -- Remote pane ------------------------------------------------------

    def _reload_remote(self) -> None:
        self._remote_pane.set_path(self._remote_path)
        path = self._remote_path
        async_utils.run_in_background(
            lambda: self._session.list_dir(path),
            on_result=self._remote_pane.set_entries,
            on_error=self._on_error,
        )

    def _navigate_remote(self, path: str) -> None:
        self._remote_path = path.strip() or "/"
        self._reload_remote()

    def _remote_up(self) -> None:
        self._remote_path = self._session.parent(self._remote_path)
        self._reload_remote()

    def _on_remote_item_activated(self, row: int) -> None:
        entry = self._remote_pane.entry_at(row)
        if entry.is_dir:
            self._remote_path = self._session.join(self._remote_path, entry.name)
            self._reload_remote()
        else:
            self._download_entries([entry])

    def _on_remote_context_menu(self, pos) -> None:
        entries = self._remote_pane.selected_entries()
        files = [e for e in entries if not e.is_dir]
        menu = QMenu(self)
        download_action = menu.addAction("Download") if files else None
        menu.addSeparator()
        new_folder_action = menu.addAction("New Folder…")
        rename_action = menu.addAction("Rename…") if len(entries) == 1 else None
        delete_action = menu.addAction("Delete") if entries else None
        chmod_action = None
        if len(entries) == 1 and self._session.kind == "sftp":
            chmod_action = menu.addAction("Change Permissions…")
        chosen = menu.exec(self._remote_pane.map_to_global(pos))
        if download_action is not None and chosen is download_action:
            self._download_entries(files)
        elif chosen is new_folder_action:
            self._new_remote_folder()
        elif rename_action is not None and chosen is rename_action:
            self._rename_remote(entries[0])
        elif delete_action is not None and chosen is delete_action:
            self._delete_remote(entries)
        elif chmod_action is not None and chosen is chmod_action:
            self._chmod_remote(entries[0])

    def _new_remote_folder(self) -> None:
        name, ok = QInputDialog.getText(self, "New Folder", "Folder name:")
        if not ok or not name.strip():
            return
        path = self._session.join(self._remote_path, name.strip())
        async_utils.run_in_background(
            lambda: self._session.mkdir(path), on_result=lambda _: self._reload_remote(), on_error=self._on_error
        )

    def _rename_remote(self, entry: ftp_client.FileEntry) -> None:
        new_name, ok = QInputDialog.getText(self, "Rename", "New name:", text=entry.name)
        if not ok or not new_name.strip() or new_name.strip() == entry.name:
            return
        old_path = self._session.join(self._remote_path, entry.name)
        new_path = self._session.join(self._remote_path, new_name.strip())
        async_utils.run_in_background(
            lambda: self._session.rename(old_path, new_path),
            on_result=lambda _: self._reload_remote(),
            on_error=self._on_error,
        )

    def _delete_remote(self, entries: list[ftp_client.FileEntry]) -> None:
        names = ", ".join(e.name for e in entries)
        kind = "and everything in it " if any(e.is_dir for e in entries) else ""
        confirmed = QMessageBox.question(
            self, "Delete", f'Delete "{names}" {kind}? This cannot be undone.'
        )
        if confirmed != QMessageBox.StandardButton.Yes:
            return
        base_path = self._remote_path
        paths = [(self._session.join(base_path, e.name), e.is_dir) for e in entries]

        def run() -> None:
            for path, is_dir in paths:
                self._delete_remote_recursive(path, is_dir)

        async_utils.run_in_background(run, on_result=lambda _: self._reload_remote(), on_error=self._on_error)

    def _delete_remote_recursive(self, path: str, is_dir: bool) -> None:
        # Runs on the background thread the delete request was submitted
        # on -- ftp_client sessions are only ever touched from one
        # background call at a time (see FtpBrowserWidget's module
        # docstring), so recursing here is safe.
        if not is_dir:
            self._session.remove(path)
            return
        for child in self._session.list_dir(path):
            self._delete_remote_recursive(self._session.join(path, child.name), child.is_dir)
        self._session.rmdir(path)

    def _chmod_remote(self, entry: ftp_client.FileEntry) -> None:
        mode_text, ok = QInputDialog.getText(
            self, "Change Permissions", "Octal mode (e.g. 755):"
        )
        if not ok or not mode_text.strip():
            return
        try:
            mode = int(mode_text.strip(), 8)
        except ValueError:
            QMessageBox.warning(self, "Error", f"Not a valid octal mode: {mode_text}")
            return
        path = self._session.join(self._remote_path, entry.name)
        async_utils.run_in_background(
            lambda: self._session.chmod(path, mode),
            on_result=lambda _: self._reload_remote(),
            on_error=self._on_error,
        )

    # -- Transfers --------------------------------------------------------

    def _upload_paths(self, local_paths: list[str]) -> None:
        for local_path in local_paths:
            if os.path.isdir(local_path):
                continue  # recursive folder upload isn't supported in v1
            name = os.path.basename(local_path)
            remote_path = self._session.join(self._remote_path, name)
            try:
                size = os.path.getsize(local_path)
            except OSError:
                size = 0
            self._enqueue_transfer("upload", name, local_path, remote_path, size)

    def _download_entries(self, entries: list[ftp_client.FileEntry]) -> None:
        for entry in entries:
            if entry.is_dir:
                continue  # recursive folder download isn't supported in v1
            remote_path = self._session.join(self._remote_path, entry.name)
            local_path = os.path.join(self._local_path, entry.name)
            self._enqueue_transfer("download", entry.name, local_path, remote_path, entry.size)

    def _enqueue_transfer(self, direction: str, name: str, local_path: str, remote_path: str, size: int) -> None:
        transfer_id = self._next_transfer_id
        self._next_transfer_id += 1
        row = self._queue_table.rowCount()
        self._queue_table.insertRow(row)
        self._queue_table.setItem(row, 0, QTableWidgetItem(name))
        self._queue_table.setItem(row, 1, QTableWidgetItem(direction))
        self._queue_table.setItem(row, 2, QTableWidgetItem("0%"))
        self._queue_table.setItem(row, 3, QTableWidgetItem("Queued"))
        self._transfer_rows[transfer_id] = row
        self._pending_transfers.append(
            _TransferJob(transfer_id, direction, name, local_path, remote_path, size)
        )
        self._process_transfer_queue()

    def _process_transfer_queue(self) -> None:
        if self._transfer_in_progress or not self._pending_transfers:
            return
        job = self._pending_transfers.pop(0)
        self._transfer_in_progress = True
        self._set_transfer_status(job.id, "Transferring")

        def progress(transferred: int, total: int) -> None:
            self._transfer_signals.progress.emit(job.id, transferred, total or job.size)

        def run() -> None:
            if job.direction == "upload":
                self._session.upload(job.local_path, job.remote_path, progress=progress)
            else:
                self._session.download(job.remote_path, job.local_path, progress=progress)

        async_utils.run_in_background(
            run,
            on_result=lambda _: self._on_transfer_done(job),
            on_error=lambda exc: self._on_transfer_failed(job, exc),
        )

    def _on_transfer_progress(self, transfer_id: int, transferred: int, total: int) -> None:
        row = self._transfer_rows.get(transfer_id)
        if row is None:
            return
        pct = int(transferred * 100 / total) if total else 0
        try:
            self._queue_table.setItem(row, 2, QTableWidgetItem(f"{pct}%"))
        except RuntimeError:
            pass  # tab was closed mid-transfer

    def _on_transfer_done(self, job: _TransferJob) -> None:
        self._set_transfer_status(job.id, "Done")
        self._transfer_in_progress = False
        try:
            if job.direction == "upload":
                self._reload_remote()
            else:
                self._reload_local()
        except RuntimeError:
            return  # tab was closed mid-transfer
        self._process_transfer_queue()

    def _on_transfer_failed(self, job: _TransferJob, exc: Exception) -> None:
        self._set_transfer_status(job.id, f"Failed: {exc}")
        self._transfer_in_progress = False
        self._process_transfer_queue()

    def _set_transfer_status(self, transfer_id: int, status: str) -> None:
        row = self._transfer_rows.get(transfer_id)
        if row is None:
            return
        try:
            self._queue_table.setItem(row, 3, QTableWidgetItem(status))
        except RuntimeError:
            pass  # tab was closed mid-transfer

    # -- Errors / teardown ------------------------------------------------

    def _on_error(self, error: Exception) -> None:
        try:
            self._status_label.setText(f"Error: {error}")
            QMessageBox.warning(self, "Error", str(error))
        except RuntimeError:
            pass  # tab was closed before the background call finished

    def close_session(self) -> None:
        async_utils.run_in_background(self._session.close)
