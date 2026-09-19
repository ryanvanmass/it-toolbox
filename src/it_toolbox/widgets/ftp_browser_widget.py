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

Uploading/downloading a folder recursively walks it (locally via
os.walk, remotely via a "scan_remote" job that itself goes through the
same queue -- see _enqueue_recursive_download's comment) and enqueues a
"create the folder" job for each directory plus a transfer job for each
file, all through the same sequential queue as a single-file transfer —
os.walk/the remote walk visits a directory before its contents, so a
directory's own create-folder job is always enqueued before any job
that needs it to exist.

Every entry point that touches self._session (a queued job, the initial
connect+first listing, and — should new ones ever get added — anything
else) must never run concurrently with another one: a single SFTP/FTP
connection corrupts under concurrent use from two threads, which
doesn't raise cleanly, it just hangs forever (confirmed live against a
real sshd while building the recursive-transfer feature above — a
completed job used to trigger a pane reload and dispatch the next
queued job's own session call back to back, with nothing ordering them,
and a fresh connection's first listing could race the very first
transfer fired immediately after it). _session_ready and the "only
reload once _pending_transfers is truly empty" check in
_on_transfer_done exist specifically to close those two windows —
don't reintroduce a bare async_utils.run_in_background call touching
self._session outside of _process_transfer_queue without re-checking
this reasoning.

Known v1 limitations, tracked in docs/ftp-sftp-client-status.md: no
drag-and-drop between panes or from the OS file manager — only
double-click (single files only; double-clicking a folder navigates
into it, in either pane) and the context menu's Download/Upload
actions (which do accept folders). Also, New Folder/Rename/Delete/
Change Permissions each still dispatch their own one-off
async_utils.run_in_background session call directly, bypassing the
transfer queue entirely -- clicking one of those while a transfer is
actively running races it the same way described above. This predates
recursive transfers (it was already possible to race a plain single-
file transfer this way) and is out of scope here; a real fix would
route every one of these through the same queue _process_transfer_queue
already serializes.
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

_QUEUE_COLLAPSED_MAX_HEIGHT = 160
# Qt's own "effectively no maximum" sentinel (QWIDGETSIZE_MAX) -- used
# instead of a specific pixel value since the expanded queue should
# claim however much space the tab actually has, not a guessed number.
_QUEUE_EXPANDED_MAX_HEIGHT = 16777215


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


# A recursive folder upload/download enqueues one of these per directory
# (see _enqueue_recursive_upload/_enqueue_remote_tree) alongside the
# regular "upload"/"download" file jobs, so the whole tree runs through
# the same one-at-a-time queue in the right order.
_DIRECTION_LABELS = {
    "upload": "upload",
    "download": "download",
    "mkdir_remote": "create folder",
    "mkdir_local": "create folder",
    "scan_remote": "scan folder",
}


@dataclass
class _TransferJob:
    id: int
    direction: str  # "upload", "download", "mkdir_remote", or "mkdir_local"
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
        # Guards against a transfer job being dispatched while the
        # initial connect()+first listing is still in flight -- both
        # would independently touch self._session, and a single SFTP/FTP
        # connection isn't safe for concurrent use from two threads at
        # once (see _on_transfer_done's note on the equivalent hazard
        # between a completed job's reload and the next queued job).
        # Enqueued jobs just wait harmlessly in _pending_transfers until
        # _on_connected flips this and kicks the queue.
        self._session_ready = False

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

        self._panes_container = QWidget()
        panes = QHBoxLayout(self._panes_container)
        panes.setContentsMargins(0, 0, 0, 0)
        panes.addWidget(self._local_pane, 1)
        panes.addWidget(self._remote_pane, 1)

        self._queue_table = QTableWidget(0, 4)
        self._queue_table.setHorizontalHeaderLabels(["File", "Direction", "Progress", "Status"])
        self._queue_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._queue_table.verticalHeader().setVisible(False)
        self._queue_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._queue_table.setMaximumHeight(_QUEUE_COLLAPSED_MAX_HEIGHT)

        self._queue_expanded = False
        self._queue_expand_button = QPushButton("Expand")
        self._queue_expand_button.clicked.connect(self._on_toggle_queue_expanded)
        queue_header = QHBoxLayout()
        queue_header.addWidget(QLabel("Transfers"))
        queue_header.addStretch(1)
        queue_header.addWidget(self._queue_expand_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self._status_label)
        layout.addWidget(self._panes_container, 3)
        layout.addLayout(queue_header)
        layout.addWidget(self._queue_table, 1)

        self._reload_local()
        self._connect_remote()

    def _on_toggle_queue_expanded(self) -> None:
        # "Fullscreen" here means filling this tab, not the OS window --
        # the browser is always embedded in the app's shared tab widget,
        # never a standalone window of its own. Hiding the panes lets
        # the queue table's own stretch factor claim that space; without
        # also lifting its collapsed max-height cap, Qt would just leave
        # the freed space empty instead of growing the table into it.
        self._queue_expanded = not self._queue_expanded
        self._panes_container.setVisible(not self._queue_expanded)
        self._queue_table.setMaximumHeight(
            _QUEUE_EXPANDED_MAX_HEIGHT if self._queue_expanded else _QUEUE_COLLAPSED_MAX_HEIGHT
        )
        self._queue_expand_button.setText("Collapse" if self._queue_expanded else "Expand")

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

        def mark_ready_and_finish(entries: list[ftp_client.FileEntry] | None, error: Exception | None) -> None:
            # Runs whether the first listing succeeded or failed --
            # either way the in-flight session.list_dir call this
            # dispatched is done, so it's safe to let a queued transfer
            # (see __init__'s _session_ready) start now.
            if entries is not None:
                self._remote_pane.set_entries(entries)
            else:
                self._on_error(error)
            self._session_ready = True
            self._process_transfer_queue()

        self._remote_pane.set_path(self._remote_path)
        path = self._remote_path
        async_utils.run_in_background(
            lambda: self._session.list_dir(path),
            on_result=lambda entries: mark_ready_and_finish(entries, None),
            on_error=lambda exc: mark_ready_and_finish(None, exc),
        )

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
        upload_action = menu.addAction("Upload") if entries else None
        menu.addSeparator()
        new_folder_action = menu.addAction("New Folder…")
        rename_action = menu.addAction("Rename…") if len(entries) == 1 else None
        delete_action = menu.addAction("Delete") if entries else None
        chosen = menu.exec(self._local_pane.map_to_global(pos))
        if upload_action is not None and chosen is upload_action:
            self._upload_paths([os.path.join(self._local_path, e.name) for e in entries])
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
        menu = QMenu(self)
        download_action = menu.addAction("Download") if entries else None
        menu.addSeparator()
        new_folder_action = menu.addAction("New Folder…")
        rename_action = menu.addAction("Rename…") if len(entries) == 1 else None
        delete_action = menu.addAction("Delete") if entries else None
        chmod_action = None
        if len(entries) == 1 and self._session.kind == "sftp":
            chmod_action = menu.addAction("Change Permissions…")
        chosen = menu.exec(self._remote_pane.map_to_global(pos))
        if download_action is not None and chosen is download_action:
            self._download_entries(entries)
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
            name = os.path.basename(local_path.rstrip(os.sep))
            remote_path = self._session.join(self._remote_path, name)
            if os.path.isdir(local_path):
                self._enqueue_recursive_upload(local_path, remote_path)
            else:
                try:
                    size = os.path.getsize(local_path)
                except OSError:
                    size = 0
                self._enqueue_transfer("upload", name, local_path, remote_path, size)

    def _enqueue_recursive_upload(self, local_dir: str, remote_dir: str) -> None:
        self._enqueue_transfer("mkdir_remote", os.path.basename(local_dir), local_dir, remote_dir, 0)
        for root, dirs, files in os.walk(local_dir):
            rel = os.path.relpath(root, local_dir)
            current_remote = remote_dir if rel == "." else self._session.join(remote_dir, rel.replace(os.sep, "/"))
            # os.walk visits `root` (and so enqueues each of its immediate
            # subdirectories' own create-folder jobs, right here) before
            # ever recursing into them, so by the time a subdirectory
            # becomes `root` itself, its create-folder job is already
            # ahead of it in the queue.
            for name in sorted(dirs):
                self._enqueue_transfer(
                    "mkdir_remote", name, os.path.join(root, name), self._session.join(current_remote, name), 0
                )
            for name in sorted(files):
                full_path = os.path.join(root, name)
                try:
                    size = os.path.getsize(full_path)
                except OSError:
                    size = 0
                self._enqueue_transfer(
                    "upload", name, full_path, self._session.join(current_remote, name), size
                )

    def _download_entries(self, entries: list[ftp_client.FileEntry]) -> None:
        for entry in entries:
            remote_path = self._session.join(self._remote_path, entry.name)
            local_path = os.path.join(self._local_path, entry.name)
            if entry.is_dir:
                self._enqueue_recursive_download(remote_path, local_path)
            else:
                self._enqueue_transfer("download", entry.name, local_path, remote_path, entry.size)

    def _enqueue_recursive_download(self, remote_dir: str, local_dir: str) -> None:
        self._enqueue_transfer("mkdir_local", os.path.basename(local_dir), local_dir, remote_dir, 0)
        # The remote tree walk itself goes through the same one-job-at-a-
        # time queue as everything else ("scan_remote", below), rather
        # than firing off its own independent background thread right
        # here -- otherwise it could run concurrently with another
        # already-queued job (e.g. a plain file selected alongside this
        # folder in the same Download click) touching the same session
        # from a second thread at the same time, which paramiko/ftplib
        # don't support.
        self._enqueue_transfer("scan_remote", os.path.basename(local_dir), local_dir, remote_dir, 0)

    def _walk_remote_tree(self, remote_dir: str) -> list[tuple[str, bool, int]]:
        """Runs on a background thread: returns a flat list of
        (path_relative_to_remote_dir, is_dir, size) for every descendant
        of remote_dir, a directory always listed before its own contents
        (matches os.walk's top-down default, which _enqueue_recursive_upload
        relies on the same way).
        """
        results: list[tuple[str, bool, int]] = []

        def walk(path: str, rel: str) -> None:
            for entry in self._session.list_dir(path):
                entry_rel = f"{rel}/{entry.name}" if rel else entry.name
                results.append((entry_rel, entry.is_dir, entry.size))
                if entry.is_dir:
                    walk(self._session.join(path, entry.name), entry_rel)

        walk(remote_dir, "")
        return results

    def _enqueue_remote_tree(self, tree: list[tuple[str, bool, int]], remote_dir: str, local_dir: str) -> None:
        for rel_path, is_dir, size in tree:
            local_path = os.path.join(local_dir, *rel_path.split("/"))
            remote_path = self._session.join(remote_dir, rel_path)
            name = rel_path.rsplit("/", 1)[-1]
            if is_dir:
                self._enqueue_transfer("mkdir_local", name, local_path, remote_path, 0)
            else:
                self._enqueue_transfer("download", name, local_path, remote_path, size)

    def _enqueue_transfer(self, direction: str, name: str, local_path: str, remote_path: str, size: int) -> None:
        transfer_id = self._next_transfer_id
        self._next_transfer_id += 1
        row = self._queue_table.rowCount()
        self._queue_table.insertRow(row)
        self._queue_table.setItem(row, 0, QTableWidgetItem(name))
        self._queue_table.setItem(row, 1, QTableWidgetItem(_DIRECTION_LABELS.get(direction, direction)))
        self._queue_table.setItem(row, 2, QTableWidgetItem("0%" if direction in ("upload", "download") else "—"))
        self._queue_table.setItem(row, 3, QTableWidgetItem("Queued"))
        self._transfer_rows[transfer_id] = row
        self._pending_transfers.append(
            _TransferJob(transfer_id, direction, name, local_path, remote_path, size)
        )
        self._process_transfer_queue()

    def _process_transfer_queue(self) -> None:
        if not self._session_ready or self._transfer_in_progress or not self._pending_transfers:
            return
        job = self._pending_transfers.pop(0)
        self._transfer_in_progress = True
        self._set_transfer_status(job.id, "Transferring")

        def progress(transferred: int, total: int) -> None:
            self._transfer_signals.progress.emit(job.id, transferred, total or job.size)

        def run():
            if job.direction == "upload":
                self._session.upload(job.local_path, job.remote_path, progress=progress)
            elif job.direction == "download":
                self._session.download(job.remote_path, job.local_path, progress=progress)
            elif job.direction == "mkdir_remote":
                try:
                    self._session.mkdir(job.remote_path)
                except Exception:  # noqa: BLE001 - best-effort: fine if it already exists
                    pass
            elif job.direction == "mkdir_local":
                os.makedirs(job.local_path, exist_ok=True)
            else:  # "scan_remote"
                return self._walk_remote_tree(job.remote_path)
            return None

        async_utils.run_in_background(
            run,
            on_result=lambda result: self._on_transfer_done(job, result),
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

    def _on_transfer_done(self, job: _TransferJob, result=None) -> None:
        self._set_transfer_status(job.id, "Done")
        self._transfer_in_progress = False
        try:
            if job.direction == "scan_remote":
                self._enqueue_remote_tree(result, job.remote_path, job.local_path)
        except RuntimeError:
            return  # tab was closed mid-transfer

        self._process_transfer_queue()

        if not self._pending_transfers and not self._transfer_in_progress:
            # The whole queue has just drained -- nothing else is about to
            # touch the session, so it's safe to refresh both panes now.
            # Reloading after *every* job instead (rather than once here,
            # at the end) would race the next job's own session call --
            # both would be background async_utils calls with no ordering
            # between them, and a single SFTP/FTP connection isn't safe
            # for concurrent use from two threads at once. This was
            # latent but harmless for a single manually-triggered
            # transfer (nothing was ever still queued by the time it
            # finished); a recursive folder transfer enqueues many jobs
            # up front, so the next one really is already waiting.
            try:
                self._reload_remote()
                self._reload_local()
            except RuntimeError:
                pass  # tab was closed

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
