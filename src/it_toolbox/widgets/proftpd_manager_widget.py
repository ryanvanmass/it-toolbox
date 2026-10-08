"""One ProFTPD Manager tab (General Tools): manages a server set up by the
cockpit-proftpd Cockpit module over SSH, with the same features as that
module's page (setup, users, groups, virtual directories, firewall,
recent transfers) plus a FileZilla-Server-style Live Traffic view. See
core/proftpd_manager.py for how it talks to the server.
"""

from __future__ import annotations

import datetime
import time

from PySide6.QtCore import QDate, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from it_toolbox.core import async_utils
from it_toolbox.core import proftpd_manager as pm
from it_toolbox.core.ftp_client import UnknownHostKeyError
from it_toolbox.widgets import status_bar

MAX_LIVE_ROWS = 5000
SESSION_POLL_MS = 3000


def bytes_label(num_bytes: int | float | None) -> str:
    if num_bytes is None:
        return ""
    if num_bytes >= 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.1f} MB"
    if num_bytes >= 1024:
        return f"{num_bytes / 1024:.1f} KB"
    return f"{int(num_bytes)} B"


def quota_label(user: dict) -> str:
    if not user.get("quota_mb"):
        return "Unlimited"
    return f"{user.get('quota_used_mb') or 0} / {user['quota_mb']} MB"


def status_label(user: dict) -> str:
    if user.get("locked"):
        return "Locked"
    if user.get("expires_at"):
        return f"Expires {user['expires_at']}"
    return "Active"


def time_label(timestamp: float) -> str:
    return datetime.datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")


def _item(text, data=None) -> QTableWidgetItem:
    item = QTableWidgetItem("" if text is None else str(text))
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    if data is not None:
        item.setData(Qt.ItemDataRole.UserRole, data)
    return item


def _table(headers: list[str], multi_select: bool = False) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.verticalHeader().setVisible(False)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(
        QAbstractItemView.SelectionMode.ExtendedSelection
        if multi_select
        else QAbstractItemView.SelectionMode.SingleSelection
    )
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.horizontalHeader().setStretchLastSection(True)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    return table


class _Busy:
    """Runs a blocking connection call in the background, with a status
    bar message, and reports a failure in one message box."""

    def __init__(self, owner: QWidget) -> None:
        self._owner = owner

    def __call__(self, message: str, fn, on_result=None, done_message: str = "") -> None:
        task = status_bar.begin(self._owner, message)

        def ok(result):
            task.finish(done_message)
            if on_result is not None:
                on_result(result)

        def failed(error: Exception):
            task.finish()
            try:
                QMessageBox.warning(self._owner, "ProFTPD Manager", str(error))
            except RuntimeError:
                pass  # widget closed while the call was running

        async_utils.run_in_background(fn, on_result=ok, on_error=failed)


# -- Dialogs ---------------------------------------------------------------


class ServerDialog(QDialog):
    """Add/edit a saved server."""

    def __init__(self, server: pm.ProftpdServer | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit ProFTPD Server" if server else "Add ProFTPD Server")
        self._name = QLineEdit(server.name if server else "")
        self._host = QLineEdit(server.host if server else "")
        self._port = QSpinBox()
        self._port.setRange(1, 65535)
        self._port.setValue(server.port if server else pm.SSH_PORT)
        self._username = QLineEdit(server.username if server else "root")
        self._key_path = QLineEdit(server.key_path or "" if server else "")
        self._key_path.setPlaceholderText("Optional — default keys and the SSH agent are tried")
        self._container = QLineEdit(server.docker_container or "" if server else "")
        self._container.setPlaceholderText("Only for the cockpit-proftpd Docker/TrueNAS app")

        form = QFormLayout()
        form.addRow("Name:", self._name)
        form.addRow("Host:", self._host)
        form.addRow("SSH port:", self._port)
        form.addRow("SSH username:", self._username)
        form.addRow("SSH key:", self._key_path)
        form.addRow("Docker container:", self._container)
        note = QLabel(
            "The SSH user needs root or sudo on the server. Passwords are asked for when "
            "needed and never saved."
        )
        note.setWordWrap(True)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addWidget(buttons)

    def _accept(self) -> None:
        if not self._host.text().strip() or not self._username.text().strip():
            QMessageBox.warning(self, "ProFTPD Manager", "Host and SSH username are required.")
            return
        self.accept()

    def server(self) -> pm.ProftpdServer:
        host = self._host.text().strip()
        return pm.ProftpdServer(
            name=self._name.text().strip() or host,
            host=host,
            port=self._port.value(),
            username=self._username.text().strip(),
            key_path=self._key_path.text().strip() or None,
            docker_container=self._container.text().strip() or None,
        )


class UserDialog(QDialog):
    """Create/edit an FTP/SFTP user -- the same fields as the Cockpit
    module's UserDialog."""

    def __init__(self, user: dict | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.is_create = user is None
        self.original_username = (user or {}).get("username", "")
        self.setWindowTitle("Create User" if self.is_create else f"Edit {self.original_username}")
        user = user or {}

        self.username = QLineEdit(self.original_username)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        if not self.is_create:
            self.password.setPlaceholderText("Leave blank to keep the current password")
        self.homedir = QLineEdit(user.get("homedir", ""))
        if self.is_create:
            self.homedir.setPlaceholderText("Default: <FTP root>/<username>")
        self.protocol = QComboBox()
        for value, label in pm.PROTOCOL_LABELS.items():
            self.protocol.addItem(label, value)
        self.protocol.setCurrentIndex(self.protocol.findData(user.get("protocol", "both")))
        self.quota = QSpinBox()
        self.quota.setRange(0, 10_000_000)
        self.quota.setSpecialValueText("Unlimited")
        self.quota.setSuffix(" MB")
        self.quota.setValue(int(user.get("quota_mb") or 0))
        self.readonly = QCheckBox("Read-only (cannot upload, delete, or rename files)")
        self.readonly.setChecked(bool(user.get("readonly")))
        self.public_key = QPlainTextEdit(user.get("public_key") or "")
        self.public_key.setPlaceholderText(
            "Optional — paste an ssh-ed25519/ssh-rsa public key to allow SFTP login without a password"
        )
        self.public_key.setFixedHeight(70)
        self.rate_limit = QComboBox()
        for value, label in pm.RATE_LIMIT_LABELS.items():
            self.rate_limit.addItem(label, value)
        self.rate_limit.setCurrentIndex(self.rate_limit.findData(user.get("rate_limit", "unlimited")))
        self.locked = QCheckBox("Locked (login disabled, password/key kept for later)")
        self.locked.setChecked(bool(user.get("locked")))
        self.expires = QCheckBox("Expires on")
        self.expires_date = QDateEdit()
        self.expires_date.setCalendarPopup(True)
        self.expires_date.setDisplayFormat("yyyy-MM-dd")
        expires_at = user.get("expires_at")
        date = QDate.fromString(expires_at, "yyyy-MM-dd") if expires_at else QDate()
        self.expires.setChecked(date.isValid())
        self.expires_date.setDate(date if date.isValid() else QDate.currentDate().addMonths(1))
        self.expires_date.setEnabled(date.isValid())
        self.expires.toggled.connect(self.expires_date.setEnabled)
        expires_row = QHBoxLayout()
        expires_row.addWidget(self.expires)
        expires_row.addWidget(self.expires_date, 1)

        form = QFormLayout()
        form.addRow("Username:", self.username)
        form.addRow("Password:" if self.is_create else "New password:", self.password)
        form.addRow("Home directory:", self.homedir)
        form.addRow("Protocol:", self.protocol)
        form.addRow("Storage quota:", self.quota)
        form.addRow("Access:", self.readonly)
        form.addRow("SFTP public key:", self.public_key)
        form.addRow("Transfer speed:", self.rate_limit)
        form.addRow("Login:", self.locked)
        form.addRow("Expiry:", expires_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(
            "Create" if self.is_create else "Save"
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _accept(self) -> None:
        if not self.username.text().strip():
            QMessageBox.warning(self, "ProFTPD Manager", "A username is required.")
            return
        if self.is_create and not self.password.text() and not self.public_key.toPlainText().strip():
            QMessageBox.warning(self, "ProFTPD Manager", "A password or a public key is required.")
            return
        self.accept()

    def options(self) -> dict:
        """The helper's create-user/update-user args besides username and
        password (blank strings clear the key/expiry, like the Cockpit page)."""
        options = {
            "protocol": self.protocol.currentData(),
            "quota_mb": self.quota.value(),
            "readonly": self.readonly.isChecked(),
            "public_key": self.public_key.toPlainText().strip(),
            "rate_limit": self.rate_limit.currentData(),
            "locked": self.locked.isChecked(),
            "expires_at": (
                self.expires_date.date().toString("yyyy-MM-dd") if self.expires.isChecked() else ""
            ),
        }
        if self.homedir.text().strip():
            options["homedir"] = self.homedir.text().strip()
        new_username = self.username.text().strip()
        if not self.is_create and new_username != self.original_username:
            options["new_username"] = new_username
        return options


class _MountEditor(QWidget):
    """Name / real path / read-only row plus an Add button, shared by the
    per-user and per-group virtual directory editors."""

    add_requested = Signal(str, str, bool)

    def __init__(self, button_text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.name = QLineEdit()
        self.name.setPlaceholderText("Name, e.g. shared")
        self.real_path = QLineEdit()
        self.real_path.setPlaceholderText("Real path on server, e.g. /srv/shared-docs")
        self.readonly = QCheckBox("Read-only")
        self.add_button = QPushButton(button_text)
        self.add_button.clicked.connect(self._emit)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.name, 1)
        layout.addWidget(self.real_path, 2)
        layout.addWidget(self.readonly)
        layout.addWidget(self.add_button)

    def _emit(self) -> None:
        name, path = self.name.text().strip(), self.real_path.text().strip()
        if name and path:
            self.add_requested.emit(name, path, self.readonly.isChecked())

    def clear(self) -> None:
        self.name.clear()
        self.real_path.clear()
        self.readonly.setChecked(False)


class VirtualMountsDialog(QDialog):
    """A user's virtual directories (bind mounts into their home). Mounting
    a real path a second time for another user makes it a shared team
    directory -- the helper handles that automatically."""

    def __init__(self, connection: pm.ProftpdConnection, username: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._connection = connection
        self._username = username
        self._busy = _Busy(self)
        self.setWindowTitle(f"Virtual Directories for {username}")
        self.resize(720, 360)

        self.table = _table(["Name", "Real path on server", "Access", "Team"])
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        remove_button = QPushButton("Remove Selected")
        remove_button.clicked.connect(self._remove_selected)
        self.editor = _MountEditor("Add Virtual Directory")
        self.editor.add_requested.connect(self._add)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.table, 1)
        layout.addWidget(remove_button, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.editor)
        layout.addWidget(close)
        self.refresh()

    def refresh(self) -> None:
        self._busy(
            f"Loading virtual directories for {self._username}…",
            lambda: self._connection.list_virtual_mounts(self._username),
            self._show,
        )

    def _show(self, mounts: list[dict]) -> None:
        self.table.setRowCount(0)
        for mount in mounts:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, _item(mount["virtual_name"], mount["virtual_name"]))
            self.table.setItem(row, 1, _item(mount["real_path"]))
            self.table.setItem(row, 2, _item("Read-only" if mount.get("readonly") else "Read-write"))
            self.table.setItem(row, 3, _item(mount.get("group_name") or "—"))
        self.table.resizeColumnsToContents()

    def _add(self, name: str, path: str, readonly: bool) -> None:
        def done(_):
            self.editor.clear()
            self.refresh()

        self._busy(
            f"Adding virtual directory {name}…",
            lambda: self._connection.add_virtual_mount(self._username, name, path, readonly),
            done,
        )

    def _context_menu(self, pos) -> None:
        if self.table.itemAt(pos) is None:
            return
        menu = QMenu(self)
        menu.addAction("Remove").triggered.connect(self._remove_selected)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _remove_selected(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        name = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        self._busy(
            f"Removing virtual directory {name}…",
            lambda: self._connection.remove_virtual_mount(self._username, name),
            lambda _: self.refresh(),
        )


# -- Live traffic ------------------------------------------------------------


class _LiveLogFollower(QObject):
    """Bridges ProftpdConnection.follow_live_log (running on a pool thread)
    to the GUI thread via a queued signal."""

    lines = Signal(list)

    def __init__(self) -> None:
        super().__init__()
        self.stop_requested = False


class LiveTrafficView(QWidget):
    """FileZilla-Server-style view: connected sessions on top (from ftpwho,
    with Disconnect), every command and response streaming in below."""

    def __init__(self, manager: ProftpdManagerWidget) -> None:
        super().__init__()
        self._manager = manager
        self._follower: _LiveLogFollower | None = None
        self._paused = False
        self._session_pids: set[int] = set()
        self._sessions_in_flight = False
        self._sessions_unavailable = False
        self.enabled: bool | None = None

        # Shown while the extra ExtendedLog isn't configured on the server.
        self.off_panel = QWidget()
        off_label = QLabel(
            "Live logging is off on this server. Turning it on adds a separate ProFTPD log "
            f"({pm.LIVE_LOG_CONF_PATH}) recording every FTP/SFTP command and response, and "
            "reloads ProFTPD without dropping anyone connected. The Cockpit module's own "
            "config is not touched."
        )
        off_label.setWordWrap(True)
        self.enable_button = QPushButton("Turn On Live Logging")
        self.enable_button.clicked.connect(self._enable)
        off_layout = QVBoxLayout(self.off_panel)
        off_layout.addWidget(off_label)
        off_layout.addWidget(self.enable_button, 0, Qt.AlignmentFlag.AlignLeft)
        off_layout.addStretch(1)

        # Shown once it is.
        self.on_panel = QWidget()
        self.pause_button = QPushButton("Pause")
        self.pause_button.setCheckable(True)
        self.pause_button.toggled.connect(self._set_paused)
        self.autoscroll = QCheckBox("Auto-scroll")
        self.autoscroll.setChecked(True)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter by user, client, command or response")
        self.filter.textChanged.connect(self._apply_filter)
        clear_button = QPushButton("Clear")
        clear_button.clicked.connect(self.clear)
        self.disable_button = QPushButton("Turn Off Live Logging")
        self.disable_button.clicked.connect(self._disable)
        toolbar = QHBoxLayout()
        toolbar.addWidget(self.pause_button)
        toolbar.addWidget(clear_button)
        toolbar.addWidget(self.autoscroll)
        toolbar.addWidget(self.filter, 1)
        toolbar.addWidget(self.disable_button)

        self.sessions = _table(["Session", "User", "Client", "Protocol", "Connected", "State"])
        self.sessions.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.sessions.customContextMenuRequested.connect(self._sessions_menu)
        self.sessions_note = QLabel()
        self.sessions_note.setWordWrap(True)
        self.sessions_note.hide()
        kick_button = QPushButton("Disconnect Selected")
        kick_button.clicked.connect(self._kick_selected)
        sessions_box = QGroupBox("Connected sessions")
        sessions_layout = QVBoxLayout(sessions_box)
        sessions_layout.addWidget(self.sessions, 1)
        sessions_layout.addWidget(self.sessions_note)
        sessions_layout.addWidget(kick_button, 0, Qt.AlignmentFlag.AlignLeft)

        self.log = _table(["Time", "Session", "Client", "User", "Protocol", "Command", "Response"])
        self.log.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        time_width = self.log.fontMetrics().horizontalAdvance("2026-10-07 00:00:00") + 16
        self.log.setColumnWidth(0, time_width)
        self.log.setColumnWidth(5, 360)
        self.sessions.setColumnWidth(4, time_width + 90)
        log_box = QGroupBox("Traffic")
        log_layout = QVBoxLayout(log_box)
        log_layout.addWidget(self.log)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(sessions_box)
        splitter.addWidget(log_box)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        on_layout = QVBoxLayout(self.on_panel)
        on_layout.setContentsMargins(0, 0, 0, 0)
        on_layout.addLayout(toolbar)
        on_layout.addWidget(splitter, 1)

        self.stack = QStackedWidget()
        self.stack.addWidget(QLabel("Checking live logging…"))
        self.stack.addWidget(self.off_panel)
        self.stack.addWidget(self.on_panel)
        layout = QVBoxLayout(self)
        layout.addWidget(self.stack)

        self._session_timer = QTimer(self)
        self._session_timer.setInterval(SESSION_POLL_MS)
        self._session_timer.timeout.connect(self.refresh_sessions)

    # -- Turning live logging on/off ---------------------------------------

    def check(self) -> None:
        connection = self._manager.connection
        self._manager.busy("Checking live logging…", connection.live_log_enabled, self._set_enabled)

    def _set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        if enabled:
            self.stack.setCurrentWidget(self.on_panel)
            self.start()
        else:
            self.stop()
            self.stack.setCurrentWidget(self.off_panel)

    def _enable(self) -> None:
        self.enable_button.setEnabled(False)

        def done(_):
            self.enable_button.setEnabled(True)
            self._set_enabled(True)

        task = status_bar.begin(self, "Turning on live logging…")

        def failed(error):
            task.finish()
            self.enable_button.setEnabled(True)
            QMessageBox.warning(self, "ProFTPD Manager", str(error))

        async_utils.run_in_background(
            self._manager.connection.enable_live_log,
            on_result=lambda r: (task.finish("Live logging on"), done(r)),
            on_error=failed,
        )

    def _disable(self) -> None:
        confirmed = QMessageBox.question(
            self,
            "Turn Off Live Logging",
            "Stop recording FTP/SFTP commands on this server? This removes "
            f"{pm.LIVE_LOG_CONF_PATH} and reloads ProFTPD; the existing log file is kept.",
        )
        if confirmed != QMessageBox.StandardButton.Yes:
            return
        self._manager.busy(
            "Turning off live logging…",
            self._manager.connection.disable_live_log,
            lambda _: self._set_enabled(False),
            "Live logging off",
        )

    # -- Following ----------------------------------------------------------

    def start(self) -> None:
        if self._follower is not None:
            return
        follower = _LiveLogFollower()
        follower.lines.connect(self._on_lines)
        self._follower = follower
        connection = self._manager.connection

        def finished(_=None):
            if self._follower is follower:
                self._follower = None

        def failed(error):
            finished()
            if not follower.stop_requested:
                QMessageBox.warning(self, "ProFTPD Manager", f"The live log stopped: {error}")

        async_utils.run_in_background(
            lambda: connection.follow_live_log(
                follower.lines.emit, lambda: follower.stop_requested
            ),
            on_result=finished,
            on_error=failed,
        )
        self.refresh_sessions()
        self._session_timer.start()

    def stop(self) -> None:
        self._session_timer.stop()
        if self._follower is not None:
            self._follower.stop_requested = True
            self._follower = None

    def _set_paused(self, paused: bool) -> None:
        self._paused = paused
        self.pause_button.setText("Resume" if paused else "Pause")

    def clear(self) -> None:
        self.log.setRowCount(0)

    def _on_lines(self, lines: list[str]) -> None:
        if self._paused:
            return
        events = [event for event in map(pm.parse_live_line, lines) if event is not None]
        if not events:
            return
        scrollbar = self.log.verticalScrollBar()
        at_bottom = scrollbar.value() >= scrollbar.maximum() - 2
        for event in events:
            self.add_event(event)
        overflow = self.log.rowCount() - MAX_LIVE_ROWS
        for _ in range(max(0, overflow)):
            self.log.removeRow(0)
        if self.autoscroll.isChecked() and at_bottom:
            self.log.scrollToBottom()
        if any(event.is_session_event for event in events):
            self.refresh_sessions()

    def add_event(self, event: pm.LiveEvent) -> None:
        if event.is_session_event:
            # One line at session start (no user yet) and one at its end.
            if event.pid in self._session_pids or event.user is not None:
                self._session_pids.discard(event.pid)
                command, response = "Disconnected", ""
            else:
                self._session_pids.add(event.pid)
                command, response = "Connected", ""
        else:
            self._session_pids.add(event.pid)
            command = event.command
            response = " ".join(part for part in (event.code, event.response) if part)
            if event.bytes:
                response = f"{response} ({bytes_label(event.bytes)})".strip()
        row = self.log.rowCount()
        self.log.insertRow(row)
        values = [
            time_label(event.timestamp),
            event.pid,
            event.address,
            event.user or "",
            event.protocol,
            command,
            response,
        ]
        color = None
        if event.is_session_event:
            color = QColor("gray")
        elif event.code and event.code[:1] in ("4", "5"):
            color = QColor("#c62828")
        for column, value in enumerate(values):
            item = _item(value)
            if color is not None:
                item.setForeground(QBrush(color))
            if event.is_session_event:
                font = QFont(item.font())
                font.setItalic(True)
                item.setFont(font)
            self.log.setItem(row, column, item)
        self._filter_row(row)

    def _row_matches(self, row: int, needle: str) -> bool:
        if not needle:
            return True
        return any(
            needle in (self.log.item(row, column).text().lower() if self.log.item(row, column) else "")
            for column in range(self.log.columnCount())
        )

    def _filter_row(self, row: int) -> None:
        self.log.setRowHidden(row, not self._row_matches(row, self.filter.text().strip().lower()))

    def _apply_filter(self) -> None:
        for row in range(self.log.rowCount()):
            self._filter_row(row)

    # -- Sessions -----------------------------------------------------------

    def refresh_sessions(self) -> None:
        if self._sessions_in_flight or self._sessions_unavailable or not self.isVisible():
            return
        self._sessions_in_flight = True

        def done(sessions):
            self._sessions_in_flight = False
            self.show_sessions(sessions)

        def failed(error):
            self._sessions_in_flight = False
            self._sessions_unavailable = True
            self.sessions_note.setText(f"Session list unavailable: {error}")
            self.sessions_note.show()

        async_utils.run_in_background(
            self._manager.connection.list_sessions, on_result=done, on_error=failed
        )

    def show_sessions(self, sessions: list[pm.LiveSession]) -> None:
        selected = self._selected_session_pid()
        self.sessions.setRowCount(0)
        now = time.time()
        for session in sessions:
            row = self.sessions.rowCount()
            self.sessions.insertRow(row)
            if session.connected_since:
                elapsed = int(max(0, now - session.connected_since))
                connected = f"{time_label(session.connected_since)} ({elapsed // 60}m {elapsed % 60}s)"
            else:
                connected = ""
            if session.command and not session.idle:
                state = session.command
            else:
                state = "Idle" + (f" in {session.location}" if session.location else "")
            values = [session.pid, session.user or "(logging in)", session.address,
                      session.protocol, connected, state]
            for column, value in enumerate(values):
                self.sessions.setItem(row, column, _item(value, session.pid))
            if session.pid == selected:
                self.sessions.selectRow(row)

    def _selected_session_pid(self) -> int | None:
        row = self.sessions.currentRow()
        item = self.sessions.item(row, 0) if row >= 0 else None
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def _sessions_menu(self, pos) -> None:
        if self.sessions.itemAt(pos) is None:
            return
        menu = QMenu(self)
        menu.addAction("Disconnect").triggered.connect(self._kick_selected)
        menu.exec(self.sessions.viewport().mapToGlobal(pos))

    def _kick_selected(self) -> None:
        pid = self._selected_session_pid()
        if pid is None:
            return
        user = self.sessions.item(self.sessions.currentRow(), 1).text()
        confirmed = QMessageBox.question(
            self, "Disconnect Session", f"Disconnect session {pid} ({user})?"
        )
        if confirmed != QMessageBox.StandardButton.Yes:
            return
        self._manager.busy(
            f"Disconnecting session {pid}…",
            lambda: self._manager.connection.kick_session(pid),
            lambda _: self.refresh_sessions(),
            f"Disconnected session {pid}",
        )

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self.enabled:
            self.refresh_sessions()


# -- The manager tab ----------------------------------------------------------


class ProftpdManagerWidget(QWidget):
    """Connects on construction, then shows the setup page or the
    management tabs depending on the server's state."""

    connected = Signal()

    def __init__(
        self,
        server: pm.ProftpdServer,
        connection_factory=pm.ProftpdConnection,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.server = server
        self._connection_factory = connection_factory
        self._credentials: dict = {}
        self.connection: pm.ProftpdConnection | None = None
        self.users: list[dict] = []
        self._closed = False
        self.busy = _Busy(self)

        self.status = QLabel()
        self.reconnect_button = QPushButton("Reconnect")
        self.reconnect_button.clicked.connect(self.connect_to_server)
        header = QHBoxLayout()
        header.addWidget(self.status, 1)
        header.addWidget(self.reconnect_button)

        self.stack = QStackedWidget()
        self.message_page = QLabel()
        self.message_page.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message_page.setWordWrap(True)
        self.stack.addWidget(self.message_page)
        self.helper_page = self._build_helper_page()
        self.stack.addWidget(self.helper_page)
        self.setup_page = self._build_setup_page()
        self.stack.addWidget(self.setup_page)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_users_tab(), "Users")
        self.tabs.addTab(self._build_groups_tab(), "Groups")
        self.tabs.addTab(self._build_activity_tab(), "Recent Activity")
        self.live = LiveTrafficView(self)
        self.tabs.addTab(self.live, "Live Traffic")
        self.stack.addWidget(self.tabs)

        layout = QVBoxLayout(self)
        layout.addLayout(header)
        layout.addWidget(self.stack, 1)

        self.connect_to_server()

    def _show_message(self, text: str) -> None:
        self.message_page.setText(text)
        self.stack.setCurrentWidget(self.message_page)

    # -- Connecting ----------------------------------------------------------

    def connect_to_server(self) -> None:
        self.live.stop()
        if self.connection is not None:
            self.connection.close()
            self.connection = None
        self.reconnect_button.setEnabled(False)
        target = f"{self.server.username}@{self.server.host}"
        self.status.setText(f"Connecting to {target}…")
        self._show_message(f"Connecting to {target}…")
        connection = self._connection_factory(self.server, **self._credentials)
        task = status_bar.begin(self, f"Connecting to {self.server.name}…")

        def ok(_):
            task.finish()
            if self._closed:
                connection.close()
                return
            self.connection = connection
            self._on_connected()

        def failed(error):
            task.finish()
            if not self._closed:
                self._on_connect_error(connection, error)

        async_utils.run_in_background(connection.connect, on_result=ok, on_error=failed)

    def _on_connect_error(self, connection, error: Exception) -> None:
        self.reconnect_button.setEnabled(True)
        self.status.setText(f"Not connected — {error}")
        retry = False
        if isinstance(error, UnknownHostKeyError):
            confirmed = QMessageBox.question(
                self,
                "Unknown Host Key",
                f"The authenticity of host '{error.hostname}' can't be established.\n"
                f"{error.key.get_name()} key fingerprint is {error.fingerprint}.\n\n"
                "Are you sure you want to continue connecting? This adds the key to your "
                "~/.ssh/known_hosts, the same as accepting it in a regular ssh client would.",
            )
            if confirmed == QMessageBox.StandardButton.Yes:
                connection.trust_host_key(error.hostname, error.key)
                retry = True
        elif isinstance(error, pm.KeyPassphraseRequired):
            retry = self._ask("key_passphrase", "SSH Key Passphrase", f"{error}\nPassphrase:")
        elif isinstance(error, pm.LoginPasswordRequired):
            retry = self._ask(
                "password", "SSH Password",
                f"{error}\nPassword for {self.server.username}@{self.server.host}:",
            )
        elif isinstance(error, pm.SudoPasswordRequired):
            prompt = f"{error}\nsudo password for {self.server.username}:"
            retry = self._ask("sudo_password", "sudo Password", prompt)
        if retry:
            self.connect_to_server()
            return
        self._show_message(f"Couldn't connect to {self.server.host}.\n\n{error}")

    def _ask(self, key: str, title: str, label: str) -> bool:
        value, ok = QInputDialog.getText(self, title, label, QLineEdit.EchoMode.Password)
        if not ok or not value:
            return False
        self._credentials[key] = value
        # The login password doubles as the likely sudo password.
        if key == "password":
            self._credentials.setdefault("sudo_password", value)
        return True

    def _on_connected(self) -> None:
        self.reconnect_button.setEnabled(True)
        where = f" (container {self.server.docker_container})" if self.server.docker_container else ""
        self.status.setText(f"Connected to {self.server.username}@{self.server.host}{where}")
        self.connected.emit()
        if self.connection.helper_path is None:
            self.stack.setCurrentWidget(self.helper_page)
            return
        self.check_status()

    def check_status(self) -> None:
        self._show_message("Checking the FTP/SFTP server…")
        self.busy("Checking ProFTPD status…", self.connection.status, self._on_status)

    def _on_status(self, status: dict) -> None:
        if status.get("configured") and status.get("active"):
            self.stack.setCurrentWidget(self.tabs)
            self.refresh_users()
            self.refresh_groups()
            self.refresh_transfers()
            self.live.check()
        else:
            self.stack.setCurrentWidget(self.setup_page)

    # -- Helper missing / setup ---------------------------------------------------

    def _build_helper_page(self) -> QWidget:
        page = QWidget()
        label = QLabel(
            "This server doesn't have the cockpit-proftpd module's helper "
            f"({pm.COCKPIT_HELPER_PATH}).\n\nInstall the cockpit-proftpd package to manage it "
            "from Cockpit too, or install IT Toolbox's bundled copy of the same helper "
            f"(to {pm.BUNDLED_HELPER_DIR}) to manage it from here."
        )
        label.setWordWrap(True)
        self.install_helper_button = QPushButton("Install Bundled Helper")
        self.install_helper_button.clicked.connect(self._install_helper)
        layout = QVBoxLayout(page)
        layout.addWidget(label)
        layout.addWidget(self.install_helper_button, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addStretch(1)
        return page

    def _install_helper(self) -> None:
        self.busy(
            "Installing the ProFTPD helper…",
            self.connection.install_bundled_helper,
            lambda _: self.check_status(),
            "Helper installed",
        )

    def _build_setup_page(self) -> QWidget:
        page = QWidget()
        label = QLabel(
            "This server doesn't have a ProFTPD-based FTP/SFTP server configured yet. "
            "Installing and configuring it will:\n\n"
            "• Install the proftpd and proftpd-sqlite packages\n"
            "• Create a dedicated user database, separate from real system accounts\n"
            "• Enable FTP (port 21) and SFTP (port 2222) with per-user chroot\n"
            "• Start and enable the proftpd service"
        )
        label.setWordWrap(True)
        self.require_tls = QCheckBox(
            "Require encrypted login over plain FTP (recommended — a self-signed "
            "certificate is generated automatically)"
        )
        self.require_tls.setChecked(True)
        self.setup_button = QPushButton("Install && Configure ProFTPD")
        self.setup_button.clicked.connect(self._run_setup)
        layout = QVBoxLayout(page)
        layout.addWidget(label)
        layout.addWidget(self.require_tls)
        layout.addWidget(self.setup_button, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addStretch(1)
        return page

    def _run_setup(self) -> None:
        self.setup_button.setEnabled(False)
        require_tls = self.require_tls.isChecked()
        task = status_bar.begin(self, "Installing and configuring ProFTPD…")

        def done(status):
            task.finish("ProFTPD configured")
            self.setup_button.setEnabled(True)
            if not (status.get("configured") and status.get("active")):
                QMessageBox.warning(
                    self,
                    "ProFTPD Manager",
                    "Setup finished, but the service isn't reporting as active. "
                    "Check the ProFTPD service log.",
                )
                return
            self._on_status(status)

        def failed(error):
            task.finish()
            self.setup_button.setEnabled(True)
            QMessageBox.warning(self, "Setup failed", str(error))

        async_utils.run_in_background(
            lambda: self.connection.setup(require_tls), on_result=done, on_error=failed
        )

    # -- Users -------------------------------------------------------------------

    USER_COLUMNS = ["Username", "UID", "Home directory", "Protocol", "Access", "Quota",
                    "SFTP login", "Speed", "Status"]

    def _build_users_tab(self) -> QWidget:
        page = QWidget()
        create = QPushButton("Create User…")
        create.clicked.connect(lambda: self.edit_user(None))
        firewall = QPushButton("Open Firewall Ports")
        firewall.clicked.connect(self._open_firewall)
        self.delete_selected_button = QPushButton("Delete Selected")
        self.delete_selected_button.clicked.connect(self._delete_selected)
        self.delete_selected_button.setEnabled(False)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh_users)
        self.user_search = QLineEdit()
        self.user_search.setPlaceholderText("Search by username or home directory")
        self.user_search.textChanged.connect(self._filter_users)
        toolbar = QHBoxLayout()
        for widget in (create, firewall, self.delete_selected_button):
            toolbar.addWidget(widget)
        toolbar.addWidget(self.user_search, 1)
        toolbar.addWidget(refresh)

        self.users_table = _table(self.USER_COLUMNS, multi_select=True)
        self.users_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.users_table.customContextMenuRequested.connect(self._users_menu)
        self.users_table.itemDoubleClicked.connect(lambda item: self.edit_user(self._user_at(item.row())))
        self.users_table.itemSelectionChanged.connect(self._on_user_selection)
        self.users_empty = QLabel("No FTP/SFTP users yet. Create one to let someone connect.")
        self.users_empty.hide()

        layout = QVBoxLayout(page)
        layout.addLayout(toolbar)
        layout.addWidget(self.users_empty)
        layout.addWidget(self.users_table, 1)
        return page

    def refresh_users(self) -> None:
        self.busy("Loading FTP/SFTP users…", self.connection.list_users, self.show_users)

    def show_users(self, users: list[dict]) -> None:
        self.users = users
        table = self.users_table
        table.setRowCount(0)
        for user in users:
            row = table.rowCount()
            table.insertRow(row)
            values = [
                user["username"],
                user.get("uid"),
                user.get("homedir"),
                pm.PROTOCOL_LABELS.get(user.get("protocol"), user.get("protocol")),
                "Read-only" if user.get("readonly") else "Read-write",
                quota_label(user),
                "Key set" if user.get("public_key") else "Password only",
                pm.RATE_LIMIT_LABELS.get(user.get("rate_limit"), user.get("rate_limit")),
                status_label(user),
            ]
            for column, value in enumerate(values):
                table.setItem(row, column, _item(value, user["username"]))
        table.resizeColumnsToContents()
        self.users_empty.setVisible(not users)
        self._filter_users()

    def _filter_users(self) -> None:
        needle = self.user_search.text().strip().lower()
        for row in range(self.users_table.rowCount()):
            user = self._user_at(row)
            haystack = f"{user['username']} {user.get('homedir', '')}".lower() if user else ""
            self.users_table.setRowHidden(row, bool(needle) and needle not in haystack)

    def _user_at(self, row: int) -> dict | None:
        item = self.users_table.item(row, 0)
        if item is None:
            return None
        username = item.data(Qt.ItemDataRole.UserRole)
        return next((u for u in self.users if u["username"] == username), None)

    def selected_usernames(self) -> list[str]:
        rows = sorted({index.row() for index in self.users_table.selectedIndexes()})
        return [
            self.users_table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            for row in rows
            if not self.users_table.isRowHidden(row)
        ]

    def _on_user_selection(self) -> None:
        count = len(self.selected_usernames())
        self.delete_selected_button.setEnabled(count > 0)
        self.delete_selected_button.setText(f"Delete Selected ({count})" if count else "Delete Selected")

    def _users_menu(self, pos) -> None:
        item = self.users_table.itemAt(pos)
        user = self._user_at(item.row()) if item is not None else None
        menu = QMenu(self)
        if user is not None:
            name = user["username"]
            menu.addAction("Edit…").triggered.connect(lambda: self.edit_user(user))
            menu.addAction("Reset Permissions").triggered.connect(lambda: self.reset_permissions(name))
            menu.addAction("Unlock" if user.get("locked") else "Lock").triggered.connect(
                lambda: self.toggle_lock(user)
            )
            menu.addAction("Virtual Directories…").triggered.connect(lambda: self.manage_mounts(name))
            menu.addSeparator()
            menu.addAction("Delete…").triggered.connect(lambda: self.delete_users([name]))
            menu.addSeparator()
        menu.addAction("Create User…").triggered.connect(lambda: self.edit_user(None))
        menu.exec(self.users_table.viewport().mapToGlobal(pos))

    def edit_user(self, user: dict | None) -> None:
        dialog = UserDialog(user, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        username = dialog.username.text().strip()
        password = dialog.password.text()
        options = dialog.options()
        if dialog.is_create:
            fn = lambda: self.connection.create_user(username, password, options)  # noqa: E731
            message = f"Creating user {username}…"
        else:
            original = dialog.original_username
            fn = lambda: self.connection.update_user(original, password or None, options)  # noqa: E731
            message = f"Saving user {original}…"
        self.busy(message, fn, lambda _: self.refresh_users(), "User saved")

    def reset_permissions(self, username: str) -> None:
        self.busy(
            f"Resetting permissions for {username}…",
            lambda: self.connection.set_permissions(username),
            lambda _: self.refresh_users(),
            f"Permissions reset for {username}",
        )

    def toggle_lock(self, user: dict) -> None:
        locked = not user.get("locked")
        self.busy(
            f"{'Locking' if locked else 'Unlocking'} {user['username']}…",
            lambda: self.connection.update_user(user["username"], None, {"locked": locked}),
            lambda _: self.refresh_users(),
        )

    def manage_mounts(self, username: str) -> None:
        VirtualMountsDialog(self.connection, username, self).exec()
        self.refresh_groups()

    def _delete_selected(self) -> None:
        self.delete_users(self.selected_usernames())

    def delete_users(self, usernames: list[str]) -> None:
        if not usernames:
            return
        what = f"user {usernames[0]}" if len(usernames) == 1 else f"{len(usernames)} selected users"
        confirmed = QMessageBox.question(
            self,
            "Delete Users",
            f"Delete {what}? This does not remove home directories or their contents.",
        )
        if confirmed != QMessageBox.StandardButton.Yes:
            return
        connection = self.connection

        def delete_all():
            for username in usernames:
                connection.delete_user(username)

        self.busy(f"Deleting {what}…", delete_all, lambda _: self.refresh_users(), "Deleted")

    def _open_firewall(self) -> None:
        confirmed = QMessageBox.question(
            self,
            "Open Firewall Ports",
            "Open the FTP/SFTP ports (21, 2222, and the passive-mode data range) in firewalld?",
        )
        if confirmed != QMessageBox.StandardButton.Yes:
            return
        self.busy(
            "Opening firewall ports…",
            self.connection.open_firewall,
            lambda opened: QMessageBox.information(
                self, "Firewall", "Opened: " + ", ".join(opened)
            ),
        )

    # -- Groups -----------------------------------------------------------------

    def _build_groups_tab(self) -> QWidget:
        page = QWidget()
        self.groups_list = QListWidget()
        self.groups_list.currentItemChanged.connect(lambda *_: self._show_group())
        self.new_group_name = QLineEdit()
        self.new_group_name.setPlaceholderText("New group name, e.g. engineering")
        create = QPushButton("Create Group")
        create.clicked.connect(self._create_group)
        self.delete_group_button = QPushButton("Delete Group")
        self.delete_group_button.clicked.connect(self._delete_group)
        left = QVBoxLayout()
        left.addWidget(QLabel("Groups share virtual directories with every member at once."))
        left.addWidget(self.groups_list, 1)
        new_row = QHBoxLayout()
        new_row.addWidget(self.new_group_name, 1)
        new_row.addWidget(create)
        left.addLayout(new_row)
        left.addWidget(self.delete_group_button, 0, Qt.AlignmentFlag.AlignLeft)

        self.group_detail = QWidget()
        self.members_list = QListWidget()
        self.add_member_combo = QComboBox()
        add_member = QPushButton("Add Member")
        add_member.clicked.connect(self._add_member)
        remove_member = QPushButton("Remove Member")
        remove_member.clicked.connect(self._remove_member)
        member_row = QHBoxLayout()
        member_row.addWidget(self.add_member_combo, 1)
        member_row.addWidget(add_member)
        member_row.addWidget(remove_member)
        self.group_mounts = _table(["Name", "Real path on server", "Access"])
        remove_mount = QPushButton("Remove Virtual Directory")
        remove_mount.clicked.connect(self._remove_group_mount)
        self.group_mount_editor = _MountEditor("Add for This Group")
        self.group_mount_editor.add_requested.connect(self._add_group_mount)
        self.group_mount_hint = QLabel("Add a member first.")
        detail = QVBoxLayout(self.group_detail)
        detail.setContentsMargins(0, 0, 0, 0)
        detail.addWidget(QLabel("Members"))
        detail.addWidget(self.members_list, 1)
        detail.addLayout(member_row)
        detail.addWidget(QLabel("Virtual directories"))
        detail.addWidget(self.group_mounts, 1)
        detail.addWidget(remove_mount, 0, Qt.AlignmentFlag.AlignLeft)
        detail.addWidget(self.group_mount_editor)
        detail.addWidget(self.group_mount_hint)
        self.group_detail.setEnabled(False)

        left_widget = QWidget()
        left_widget.setLayout(left)
        splitter = QSplitter()
        splitter.addWidget(left_widget)
        splitter.addWidget(self.group_detail)
        splitter.setStretchFactor(1, 2)
        layout = QVBoxLayout(page)
        layout.addWidget(splitter)
        self.groups: list[dict] = []
        self.all_mounts: list[dict] = []
        return page

    def refresh_groups(self) -> None:
        connection = self.connection
        self.busy(
            "Loading groups…",
            lambda: (connection.list_groups(), connection.list_virtual_mounts()),
            lambda result: self.show_groups(*result),
        )

    def show_groups(self, groups: list[dict], mounts: list[dict]) -> None:
        current = self.groups_list.currentItem()
        current_name = current.text() if current is not None else None
        self.groups, self.all_mounts = groups, mounts
        self.groups_list.blockSignals(True)
        self.groups_list.clear()
        for group in groups:
            item = QListWidgetItem(group["groupname"])
            self.groups_list.addItem(item)
            if group["groupname"] == current_name:
                self.groups_list.setCurrentItem(item)
        self.groups_list.blockSignals(False)
        if self.groups_list.currentItem() is None and groups:
            self.groups_list.setCurrentRow(0)
        self._show_group()

    def _current_group(self) -> dict | None:
        item = self.groups_list.currentItem()
        if item is None:
            return None
        return next((g for g in self.groups if g["groupname"] == item.text()), None)

    def _show_group(self) -> None:
        group = self._current_group()
        self.group_detail.setEnabled(group is not None)
        self.delete_group_button.setEnabled(group is not None)
        self.members_list.clear()
        self.add_member_combo.clear()
        self.group_mounts.setRowCount(0)
        if group is None:
            return
        members = group.get("members", [])
        self.members_list.addItems(members)
        for user in self.users:
            if user["username"] not in members:
                self.add_member_combo.addItem(user["username"])
        # list-virtual-mounts has one row per member for a group-owned
        # directory; show each directory once.
        seen: set[str] = set()
        for mount in self.all_mounts:
            name = mount["virtual_name"]
            if mount.get("group_name") != group["groupname"] or name in seen:
                continue
            seen.add(name)
            row = self.group_mounts.rowCount()
            self.group_mounts.insertRow(row)
            self.group_mounts.setItem(row, 0, _item(name, name))
            self.group_mounts.setItem(row, 1, _item(mount["real_path"]))
            self.group_mounts.setItem(row, 2, _item("Read-only" if mount.get("readonly") else "Read-write"))
        self.group_mounts.resizeColumnsToContents()
        self.group_mount_editor.add_button.setEnabled(bool(members))
        self.group_mount_hint.setVisible(not members)

    def _group_call(self, message: str, fn) -> None:
        self.busy(message, fn, lambda _: self.refresh_groups())

    def _create_group(self) -> None:
        name = self.new_group_name.text().strip()
        if not name:
            return
        self.new_group_name.clear()
        self._group_call(f"Creating group {name}…", lambda: self.connection.create_group(name))

    def _delete_group(self) -> None:
        group = self._current_group()
        if group is None:
            return
        name = group["groupname"]
        self._group_call(f"Deleting group {name}…", lambda: self.connection.delete_group(name))

    def _add_member(self) -> None:
        group, username = self._current_group(), self.add_member_combo.currentText()
        if group is None or not username:
            return
        name = group["groupname"]
        self._group_call(
            f"Adding {username} to {name}…", lambda: self.connection.add_group_member(name, username)
        )

    def _remove_member(self) -> None:
        group, item = self._current_group(), self.members_list.currentItem()
        if group is None or item is None:
            return
        name, username = group["groupname"], item.text()
        self._group_call(
            f"Removing {username} from {name}…",
            lambda: self.connection.remove_group_member(name, username),
        )

    def _add_group_mount(self, virtual_name: str, real_path: str, readonly: bool) -> None:
        group = self._current_group()
        if group is None:
            return
        name = group["groupname"]
        self.group_mount_editor.clear()
        self._group_call(
            f"Adding virtual directory {virtual_name} for {name}…",
            lambda: self.connection.add_group_mount(name, virtual_name, real_path, readonly),
        )

    def _remove_group_mount(self) -> None:
        group, row = self._current_group(), self.group_mounts.currentRow()
        if group is None or row < 0:
            return
        name, virtual_name = group["groupname"], self.group_mounts.item(row, 0).text()
        self._group_call(
            f"Removing virtual directory {virtual_name}…",
            lambda: self.connection.remove_group_mount(name, virtual_name),
        )

    # -- Recent activity ---------------------------------------------------------

    def _build_activity_tab(self) -> QWidget:
        page = QWidget()
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh_transfers)
        note = QLabel("Completed uploads, downloads, and deletions (the same list as Cockpit's).")
        top = QHBoxLayout()
        top.addWidget(note, 1)
        top.addWidget(refresh)
        self.transfers_table = _table(["Time", "Username", "Command", "Path", "Size"])
        layout = QVBoxLayout(page)
        layout.addLayout(top)
        layout.addWidget(self.transfers_table, 1)
        return page

    def refresh_transfers(self) -> None:
        self.busy("Loading recent activity…", self.connection.list_transfers, self.show_transfers)

    def show_transfers(self, transfers: list[dict]) -> None:
        table = self.transfers_table
        table.setRowCount(0)
        for transfer in transfers:
            row = table.rowCount()
            table.insertRow(row)
            values = [
                time_label(transfer.get("timestamp") or 0),
                transfer.get("username"),
                transfer.get("command"),
                transfer.get("path"),
                bytes_label(transfer.get("bytes")),
            ]
            for column, value in enumerate(values):
                table.setItem(row, column, _item(value))
        table.resizeColumnsToContents()

    # -- Lifecycle ----------------------------------------------------------------

    def close_session(self) -> None:
        self._closed = True
        self.live.stop()
        if self.connection is not None:
            connection, self.connection = self.connection, None
            async_utils.run_in_background(connection.close)
