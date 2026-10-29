"""Shared pieces of the Cockpit managers that drive a Cockpit
module's helper over SSH (see core/remote_helper.py): the saved-server
dialog, a background-call runner, a tab base class that connects on
construction and prompts for host keys and passwords as needed, and the
offer to install the user's SSH key after a password login.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from it_toolbox.core import async_utils
from it_toolbox.core import remote_helper as rh
from it_toolbox.core import ssh_key_install
from it_toolbox.core.ftp_client import UnknownHostKeyError
from it_toolbox.widgets import status_bar


class Busy:
    """Runs a blocking connection call in the background, with a status
    bar message, and reports a failure in one message box titled `title`."""

    def __init__(self, owner: QWidget, title: str) -> None:
        self._owner = owner
        self._title = title

    def __call__(self, message: str, fn, on_result=None, done_message: str = "", on_error=None) -> None:
        task = status_bar.begin(self._owner, message)

        def ok(result):
            task.finish(done_message)
            if on_result is not None:
                try:
                    on_result(result)
                except RuntimeError:
                    pass  # widget closed while the call was running

        def failed(error: Exception):
            task.finish()
            try:
                if on_error is not None:
                    on_error(error)
                QMessageBox.warning(self._owner, self._title, str(error))
            except RuntimeError:
                pass

        async_utils.run_in_background(fn, on_result=ok, on_error=failed)


def prompt_to_retry(parent: QWidget, connection, error: Exception, credentials: dict) -> bool:
    """Handles a failed connect() that the user can fix: confirms an
    unknown host key, or asks for the key passphrase, login password or
    sudo password (stored in `credentials`, in memory only). True when the
    caller should connect again."""
    server = connection.server
    if isinstance(error, UnknownHostKeyError):
        confirmed = QMessageBox.question(
            parent,
            "Unknown Host Key",
            f"The authenticity of host '{error.hostname}' can't be established.\n"
            f"{error.key.get_name()} key fingerprint is {error.fingerprint}.\n\n"
            "Are you sure you want to continue connecting? This adds the key to your "
            "~/.ssh/known_hosts, the same as accepting it in a regular ssh client would.",
        )
        if confirmed != QMessageBox.StandardButton.Yes:
            return False
        connection.trust_host_key(error.hostname, error.key)
        return True
    if isinstance(error, rh.KeyPassphraseRequired):
        return _ask(parent, credentials, "key_passphrase", "SSH Key Passphrase", f"{error}\nPassphrase:")
    if isinstance(error, rh.LoginPasswordRequired):
        return _ask(
            parent, credentials, "password", "SSH Password",
            f"{error}\nPassword for {server.username}@{server.host}:",
        )
    if isinstance(error, rh.SudoPasswordRequired):
        return _ask(
            parent, credentials, "sudo_password", "sudo Password",
            f"{error}\nsudo password for {server.username}:",
        )
    return False


def _ask(parent: QWidget, credentials: dict, key: str, title: str, label: str) -> bool:
    value, ok = QInputDialog.getText(parent, title, label, QLineEdit.EchoMode.Password)
    if not ok or not value:
        return False
    credentials[key] = value
    # The login password doubles as the likely sudo password.
    if key == "password":
        credentials.setdefault("sudo_password", value)
    return True


#: user@host:port targets already offered a key install this run, so
#: every manager tab on a machine doesn't ask again after a "No".
_key_install_offered: set[tuple[str, str, int]] = set()


def offer_key_install(parent: QWidget, server: rh.RemoteServer, credentials: dict) -> None:
    """After a connection that only worked with the SSH password, offers
    (once per machine per run) to put the user's public key in the
    server's authorized_keys, ssh-copy-id style, generating a key first
    if they have none. On success the password is dropped from
    `credentials`, so the next connect proves the key works."""
    password = credentials.get("password")
    target = (server.username, server.host.lower(), server.port)
    if not password or target in _key_install_offered:
        return
    _key_install_offered.add(target)
    local = ssh_key_install.find_local_key(server.key_path)
    where = f"{server.username}@{server.host}"
    if local.exists:
        detail = f"This adds your public key ({local.private_path}.pub) to ~/.ssh/authorized_keys there."
    else:
        detail = (
            f"You don't have an SSH key yet, so a new one is created at {local.private_path} "
            "(without a passphrase) and its public half added to ~/.ssh/authorized_keys there."
        )
    answer = QMessageBox.question(
        parent,
        "Use an SSH Key Instead?",
        f"You signed in to {where} with a password.\n\nInstall your SSH key on it so future "
        f"connections don't ask for one?\n\n{detail}",
    )
    if answer != QMessageBox.StandardButton.Yes:
        return

    def work() -> bool:
        key = local if local.exists else ssh_key_install.generate_key(local.private_path)
        ssh_key_install.install_public_key(server.host, server.port, server.username, password, key.public_key)
        return ssh_key_install.key_login_works(
            server.host, server.port, server.username, key.private_path, credentials.get("key_passphrase")
        )

    def done(works: bool) -> None:
        if works:
            credentials.pop("password", None)
            QMessageBox.information(
                parent, "SSH Key Installed", f"Your SSH key is installed on {where}; it's used from now on."
            )
        else:
            QMessageBox.warning(
                parent,
                "SSH Key Installed",
                f"Your key was added to {where}'s authorized_keys, but logging in with it still "
                "failed. The server may not allow key logins (PubkeyAuthentication), or its "
                "~/.ssh permissions may be too open.",
            )

    Busy(parent, "SSH Key")(f"Installing your SSH key on {server.host}…", work, done)


class ServerDialog(QDialog):
    """Add/edit a saved server: name, host, SSH port, user and key."""

    def __init__(
        self,
        tool_name: str,
        server_class: type[rh.RemoteServer] = rh.RemoteServer,
        server: rh.RemoteServer | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tool_name = tool_name
        self._server_class = server_class
        self.setWindowTitle(f"Edit {tool_name} Server" if server else f"Add {tool_name} Server")
        self._name = QLineEdit(server.name if server else "")
        self._host = QLineEdit(server.host if server else "")
        self._port = QSpinBox()
        self._port.setRange(1, 65535)
        self._port.setValue(server.port if server else rh.SSH_PORT)
        self._username = QLineEdit(server.username if server else "root")
        self._key_path = QLineEdit((server.key_path or "") if server else "")
        self._key_path.setPlaceholderText("Optional — default keys and the SSH agent are tried")

        form = QFormLayout()
        form.addRow("Name:", self._name)
        form.addRow("Host:", self._host)
        form.addRow("SSH port:", self._port)
        form.addRow("SSH username:", self._username)
        form.addRow("SSH key:", self._key_path)
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
            QMessageBox.warning(self, self._tool_name, "Host and SSH username are required.")
            return
        self.accept()

    def server(self) -> rh.RemoteServer:
        host = self._host.text().strip()
        return self._server_class(
            name=self._name.text().strip() or host,
            host=host,
            port=self._port.value(),
            username=self._username.text().strip(),
            key_path=self._key_path.text().strip() or None,
        )


class RemoteHelperTab(QWidget):
    """A manager tab: a status line with Reconnect over a stacked area.
    Connects on construction; subclasses add their pages to `stack` and
    implement on_connected(), called once the connection (with root) is up.
    """

    TOOL_NAME = "Manager"

    connected = Signal()

    def __init__(
        self,
        server: rh.RemoteServer,
        connection_factory,
        parent: QWidget | None = None,
        credentials: dict | None = None,
    ) -> None:
        super().__init__(parent)
        self.server = server
        self._connection_factory = connection_factory
        # Shared, not copied: the Cockpit machine tree passes the dict its
        # detection already filled in, so passwords typed here or there
        # are asked for once per machine.
        self._credentials: dict = credentials if credentials is not None else {}
        self.connection: rh.RemoteHelperConnection | None = None
        self._closed = False
        self.busy = Busy(self, self.TOOL_NAME)

        self.status = QLabel()
        self.status.setWordWrap(True)
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

        layout = QVBoxLayout(self)
        layout.addLayout(header)
        layout.addWidget(self.stack, 1)

    def show_message(self, text: str) -> None:
        self.message_page.setText(text)
        self.stack.setCurrentWidget(self.message_page)

    # -- Connecting ----------------------------------------------------------

    def connect_to_server(self) -> None:
        self.before_reconnect()
        if self.connection is not None:
            self.connection.close()
            self.connection = None
        self.reconnect_button.setEnabled(False)
        target = f"{self.server.username}@{self.server.host}"
        self.status.setText(f"Connecting to {target}…")
        self.show_message(f"Connecting to {target}…")
        connection = self._connection_factory(self.server, **self._credentials)
        task = status_bar.begin(self, f"Connecting to {self.server.name}…")

        def ok(_):
            task.finish()
            if self._closed:
                connection.close()
                return
            self.connection = connection
            self.reconnect_button.setEnabled(True)
            self.status.setText(f"Connected to {target}")
            self.connected.emit()
            self.on_connected()
            offer_key_install(self, self.server, self._credentials)

        def failed(error):
            task.finish()
            if not self._closed:
                self._on_connect_error(connection, error)

        async_utils.run_in_background(connection.connect, on_result=ok, on_error=failed)

    def _on_connect_error(self, connection, error: Exception) -> None:
        self.reconnect_button.setEnabled(True)
        self.status.setText(f"Not connected — {error}")
        if prompt_to_retry(self, connection, error, self._credentials):
            self.connect_to_server()
            return
        self.show_message(f"Couldn't connect to {self.server.host}.\n\n{error}")

    # -- Hooks ----------------------------------------------------------------

    def before_reconnect(self) -> None:
        """Stop anything that uses the old connection."""

    def on_connected(self) -> None:
        raise NotImplementedError

    # -- Lifecycle ----------------------------------------------------------------

    def close_session(self) -> None:
        self._closed = True
        self.before_reconnect()
        if self.connection is not None:
            connection, self.connection = self.connection, None
            async_utils.run_in_background(connection.close)


# -- Small table helpers ------------------------------------------------------


def table_item(text, data=None) -> QTableWidgetItem:
    item = QTableWidgetItem("" if text is None else str(text))
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    if data is not None:
        item.setData(Qt.ItemDataRole.UserRole, data)
    return item


def make_table(headers: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.verticalHeader().setVisible(False)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.horizontalHeader().setStretchLastSection(True)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    return table


def fill_table(table: QTableWidget, rows: list[list], data: list | None = None) -> None:
    """Replaces the table's rows; data[i] (if given) is stored on row i's
    first cell under UserRole."""
    table.setRowCount(0)
    for row, values in enumerate(rows):
        table.insertRow(row)
        for column, value in enumerate(values):
            table.setItem(row, column, table_item(value, data[row] if data and column == 0 else None))
    table.resizeColumnsToContents()


def selected_data(table: QTableWidget):
    """UserRole data of the selected row's first cell, or None."""
    rows = table.selectionModel().selectedRows() if table.selectionModel() else []
    if not rows:
        return None
    item = table.item(rows[0].row(), 0)
    return item.data(Qt.ItemDataRole.UserRole) if item is not None else None
