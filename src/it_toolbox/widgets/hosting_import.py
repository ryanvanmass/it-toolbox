"""The Hosting Manager's two import wizards, as on the cockpit-hosting
page: sites from a CloudPanel server (Sites tab), and everything from a
dedicated Zabbix server into a Zabbix site (that site's Settings tab).

Both work the same way on the server: scan the source over SSH (read
only), start the import in a unit of its own, and poll its status until
it ends, so closing the dialog doesn't stop it.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from it_toolbox.core import async_utils
from it_toolbox.core import hosting_manager as hm
from it_toolbox.ui import theme
from it_toolbox.widgets import status_bar
from it_toolbox.widgets.hosting_dialogs import monospace
from it_toolbox.widgets.remote_helper_widget import fill_table, make_table, table_item

POLL_MS = 2000


def _label(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


class ConnectPage(QWidget):
    """Where the source server is and how to log in to it: a password, or
    this server's import key (made the first time it's asked for)."""

    def __init__(self, what: str, connection: hm.HostingConnection, source: dict | None) -> None:
        super().__init__()
        self.connection = connection
        self.public_key: str | None = None
        source = source or {}
        self.previous = source
        self.host = QLineEdit(source.get("host") or "")
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(int(source.get("port") or 22))
        self.user = QLineEdit(source.get("user") or "root")
        self.user.setToolTip("root, or a user who can use sudo without a password")
        self.with_password = QRadioButton("Password")
        self.with_key = QRadioButton("This server's import key")
        (self.with_key if source.get("auth") == "key" else self.with_password).setChecked(True)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.key = QPlainTextEdit()
        self.key.setReadOnly(True)
        self.key.setFont(monospace())
        self.key.setFixedHeight(60)
        self.copy_key = QPushButton("Copy")
        self.copy_key.clicked.connect(lambda _=False: QGuiApplication.clipboard().setText(self.key.toPlainText()))
        self.key_row = QWidget()
        key_layout = QHBoxLayout(self.key_row)
        key_layout.setContentsMargins(0, 0, 0, 0)
        key_layout.addWidget(self.key, 1)
        key_layout.addWidget(self.copy_key)
        auth = QHBoxLayout()
        auth.addWidget(self.with_password)
        auth.addWidget(self.with_key)
        auth.addStretch(1)
        self.form = QFormLayout()
        self.form.addRow(f"{what} server:", self.host)
        self.form.addRow("SSH port:", self.port)
        self.form.addRow("SSH user:", self.user)
        self.form.addRow("Log in with:", auth)
        self.form.addRow("SSH password:", self.password)
        self.form.addRow("Import key:", self.key_row)
        self.layout_ = QVBoxLayout(self)
        self.layout_.addWidget(_label(
            f"Nothing is written to or deleted from the {what} server: it is only read."))
        self.layout_.addLayout(self.form)
        self.with_password.toggled.connect(self._update_auth)
        self.host.textChanged.connect(self._update_auth)
        self._update_auth()

    def _update_auth(self) -> None:
        key = self.with_key.isChecked()
        self.form.setRowVisible(self.password, not key)
        self.form.setRowVisible(self.key_row, key)
        same = self.previous.get("auth") == "password" and self.previous.get("host") == self.host.text().strip()
        self.password.setPlaceholderText("Leave empty to use the password given before" if same else
                                         "Kept on the server, readable by root only, until the import finishes")
        user = self.user.text().strip() or "root"
        self.key.setToolTip(f"Add it to ~{user}/.ssh/authorized_keys on the source server first.")
        if key and self.public_key is None:
            self.public_key = ""

            def show(public_key: str) -> None:
                try:
                    self.public_key = public_key
                    self.key.setPlainText(public_key)
                except RuntimeError:
                    pass

            def failed(error: Exception) -> None:
                try:
                    self.public_key = None
                    self.key.setPlainText(f"Could not make the import key: {error}")
                except RuntimeError:
                    pass

            async_utils.run_in_background(self.connection.import_key, on_result=show, on_error=failed)

    def set_public_key(self, public_key: str | None) -> None:
        if public_key:
            self.public_key = public_key
            self.key.setPlainText(public_key)

    def scan_input(self) -> dict:
        result = {
            "host": self.host.text().strip(),
            "port": self.port.value(),
            "user": self.user.text().strip(),
            "auth": "key" if self.with_key.isChecked() else "password",
        }
        if not self.with_key.isChecked() and self.password.text():
            result["password"] = self.password.text()
        return result


class _ImportDialog(QDialog):
    """A wizard on a QStackedWidget with Back/Next-style buttons, polling
    the import's status while a job runs."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(820, 600)
        self.status: dict = {}
        self.pages = QStackedWidget()
        self.error = _label()
        theme.set_tone(self.error, "danger")
        self.error.hide()
        self.buttons = QHBoxLayout()
        layout = QVBoxLayout(self)
        layout.addWidget(self.error)
        layout.addWidget(self.pages, 1)
        layout.addLayout(self.buttons)
        self._poll = QTimer(self)
        self._poll.setInterval(POLL_MS)
        self._poll.setSingleShot(True)
        self._poll.timeout.connect(self.refresh)

    def set_buttons(self, *buttons: QPushButton) -> None:
        while self.buttons.count():
            item = self.buttons.takeAt(0)
            if item.widget() is not None:
                item.widget().setParent(None)
        self.buttons.addStretch(1)
        for button in buttons:
            self.buttons.addWidget(button)

    def button(self, text: str, slot) -> QPushButton:
        button = QPushButton(text)
        button.clicked.connect(lambda _=False: slot())
        return button

    def show_error(self, error: Exception | str | None) -> None:
        self.error.setText(str(error or ""))
        self.error.setVisible(bool(error))

    def call(self, message: str, fn, on_result) -> None:
        """A helper call, with the dialog's buttons off while it runs and
        its failure shown in the dialog."""
        self.show_error(None)
        task = status_bar.begin(self, message)
        self.setEnabled(False)

        def ok(result) -> None:
            task.finish()
            try:
                self.setEnabled(True)
                on_result(result)
            except RuntimeError:
                pass

        def failed(error: Exception) -> None:
            task.finish()
            try:
                self.setEnabled(True)
                self.show_error(error)
            except RuntimeError:
                pass

        async_utils.run_in_background(fn, on_result=ok, on_error=failed)

    def fetch_status(self):
        raise NotImplementedError

    def refresh(self) -> None:
        def show(status: dict) -> None:
            try:
                self.show_status(status)
            except RuntimeError:
                pass

        async_utils.run_in_background(self.fetch_status, on_result=show,
                                      on_error=lambda error: self._safe(self.show_error, error))

    @staticmethod
    def _safe(fn, *args) -> None:
        try:
            fn(*args)
        except RuntimeError:
            pass

    def show_status(self, status: dict) -> None:
        self.status = status
        if status.get("running"):
            self._poll.start()

    def done(self, result: int) -> None:
        self._poll.stop()
        super().done(result)


# -- CloudPanel ---------------------------------------------------------------------------

STATE_LABELS = {"pending": "Waiting", "running": "Importing", "done": "Imported", "failed": "Failed",
                "cancelled": "Cancelled"}


def plan_details(plan: dict) -> str:
    """What happens to one CloudPanel site, as the page's SiteDetails."""
    certificate = {
        "letsencrypt": "Its Let's Encrypt certificate is copied; switch to Let's Encrypt here once DNS points here",
        "imported": "Its uploaded certificate is copied",
        "self-signed": "It gets a self-signed certificate, as on CloudPanel",
        "expired": "Its certificate has expired: it gets a self-signed one",
    }.get((plan.get("certificate") or {}).get("type"))
    copied = [f"Files of htdocs/{plan['domain']}" if str(plan.get("root", "")).startswith(plan["domain"])
              else "Files of htdocs"]
    if len(plan.get("domains") or []) > 1:
        copied.append(f"Domains: {', '.join(plan['domains'])}")
    for db in plan.get("databases") or []:
        size = f", {hm.format_bytes(db['size'])}" if db.get("size") is not None else ""
        copied.append(f"Database {db['name']} (user {db['user']}){size}")
    for job in plan.get("cron") or []:
        copied.append(f"Cron job {job['schedule']} {job['command']}"
                      + (" (adapted for this server)" if job.get("changed") else ""))
    if certificate:
        copied.append(certificate)
    if plan.get("sftp_keys"):
        copied.append("The site user's SSH keys, for SFTP")
    sections = []
    for title, items in (("Can't be imported", plan.get("blockers") or []), ("Check", plan.get("notes") or []),
                         ("Copied", copied), ("Not copied (no equivalent here)", plan.get("skipped") or [])):
        if items:
            sections.append(title + ":\n" + "\n".join(f"  • {item}" for item in items))
    return "\n\n".join(sections)


class CloudPanelImportDialog(_ImportDialog):
    """Import sites from a CloudPanel server: connect, choose, watch."""

    COLUMNS = ("Import", "Domain", "Type", "PHP", "Site user here", "Start command", "Size")

    def __init__(self, connection: hm.HostingConnection, on_imported=None, parent: QWidget | None = None) -> None:
        super().__init__("Import Sites from CloudPanel", parent)
        self.connection = connection
        self.on_imported = on_imported
        self.scan: dict | None = None
        self._done_count = 0
        self._started = False

        self.connect_page: ConnectPage | None = None
        self.mysql_password = QLineEdit()
        self.mysql_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.mysql_password.setPlaceholderText("Only if CloudPanel can't show it (clpctl db:show:master-credentials)")

        self.choose_page = QWidget()
        self.source_label = _label()
        self.sites_table = make_table(list(self.COLUMNS))
        self.sites_table.itemSelectionChanged.connect(self._show_plan)
        self.plan_view = QPlainTextEdit()
        self.plan_view.setReadOnly(True)
        self.plan_view.setFixedHeight(150)
        choose = QVBoxLayout(self.choose_page)
        choose.addWidget(self.source_label)
        choose.addWidget(_label("Each site is created here with its files, databases, cron jobs and certificate. "
                                "A site that fails is removed again here; the CloudPanel server is never changed."))
        choose.addWidget(self.sites_table, 1)
        choose.addWidget(self.plan_view)

        self.progress_page = QWidget()
        self.progress_summary = _label()
        self.passwords_box = QGroupBox("New database passwords")
        self.passwords_table = make_table(["Database", "User", "Password"])
        passwords = QVBoxLayout(self.passwords_box)
        passwords.addWidget(_label("The site's own configuration didn't name these databases' passwords, so new "
                                   "ones were made. Put them in the site's configuration; they are shown until you "
                                   "clear the results."))
        passwords.addWidget(self.passwords_table)
        self.progress_table = make_table(["Domain", "Site user", "State", "Details"])
        progress = QVBoxLayout(self.progress_page)
        progress.addWidget(self.progress_summary)
        progress.addWidget(self.passwords_box)
        progress.addWidget(self.progress_table, 1)

        self.loading = _label("Loading…")
        self.pages.addWidget(self.loading)
        self.pages.addWidget(self.choose_page)
        self.pages.addWidget(self.progress_page)
        self.set_buttons(self.button("Close", self.reject))
        self.refresh()

    def fetch_status(self) -> dict:
        return self.connection.import_status()

    def show_status(self, status: dict) -> None:
        super().show_status(status)
        if self.connect_page is None:
            self._build_connect(status)
        job = status.get("job")
        if job:
            self._show_progress(job, bool(status.get("running")))
            done = sum(1 for site in job.get("sites") or [] if site.get("state") == "done")
            if done != self._done_count:
                self._done_count = done
                if self.on_imported is not None:
                    self.on_imported()
        elif not self._started:
            self._started = True
            if status.get("scan"):
                self._show_choose(status["scan"])
            else:
                self._show_connect()

    def _build_connect(self, status: dict) -> None:
        source = (status.get("scan") or {}).get("source") or status.get("source")
        self.connect_page = ConnectPage("CloudPanel", self.connection, source)
        self.connect_page.set_public_key(status.get("public_key"))
        self.connect_page.form.addRow("MySQL root password:", self.mysql_password)
        self.pages.addWidget(self.connect_page)

    def _show_connect(self) -> None:
        self.pages.setCurrentWidget(self.connect_page)
        buttons = [self.button("Scan", self._scan)]
        if self.scan:
            buttons.append(self.button("Back to the Sites", lambda: self._show_choose(self.scan)))
        self.set_buttons(*buttons, self.button("Cancel", self.reject))

    def _scan(self) -> None:
        scan_input = self.connect_page.scan_input()
        if not scan_input["host"]:
            self.show_error("Enter the CloudPanel server's host name or address.")
            return
        if self.mysql_password.text():
            scan_input["mysql_password"] = self.mysql_password.text()
        self.call("Scanning the CloudPanel server…", lambda: self.connection.import_scan(scan_input),
                  self._show_choose)

    def _show_choose(self, scan: dict) -> None:
        self.scan = scan
        source = scan.get("source") or {}
        text = (f"CloudPanel {source.get('cloudpanel_version') or ''} on {source.get('host')}, "
                + (f"MySQL {source['db_version']}" if source.get("db_version") else "database not readable"))
        if source.get("fingerprint"):
            text += f"\nHost key {source['fingerprint']}"
        if source.get("mysql_error"):
            text += f"\nThe databases can't be read: {source['mysql_error']}"
        if not scan.get("sites"):
            text += "\nThis CloudPanel server has no sites."
        self.source_label.setText(text)
        self._fill_sites(scan)
        self.pages.setCurrentWidget(self.choose_page)
        self.set_buttons(self.button("Import", self._start), self.button("Scan Again", self._show_connect),
                         self.button("Cancel", self.reject))

    def _fill_sites(self, scan: dict) -> None:
        table: QTableWidget = self.sites_table
        plans = scan.get("sites") or []
        table.setRowCount(0)
        php_here = scan.get("php_here") or []
        for row, plan in enumerate(plans):
            table.insertRow(row)
            check = QCheckBox()
            check.setChecked(not plan.get("blockers"))
            check.setEnabled(not self._blockers(plan, plan.get("php_target") or ""))
            table.setCellWidget(row, 0, check)
            domain = plan["domain"] + (" (sync again)" if plan.get("existing") else "")
            table.setItem(row, 1, table_item(domain, plan))
            label = hm.SITE_TYPE_LABELS.get(plan.get("type"), plan.get("cloudpanel_type") or "")
            if plan.get("application"):
                label += f" ({plan['application']})"
            table.setItem(row, 2, table_item(label))
            if plan.get("type") == "php" and not plan.get("existing"):
                php = QComboBox()
                if not plan.get("php_target"):
                    php.addItem(f"PHP {plan.get('php_version') or ''} missing", "")
                for version in php_here:
                    php.addItem(f"PHP {version}", version)
                php.setCurrentIndex(max(0, php.findData(plan.get("php_target") or "")))
                php.currentIndexChanged.connect(lambda _=0, r=row: self._php_changed(r))
                table.setCellWidget(row, 3, php)
            else:
                table.setItem(row, 3, table_item(plan.get("php_version") or ""))
            if plan.get("existing"):
                table.setItem(row, 4, table_item(plan["existing"]))
            else:
                table.setCellWidget(row, 4, QLineEdit(plan.get("name") or ""))
            if plan.get("type") in ("node", "python") and not plan.get("existing"):
                table.setCellWidget(row, 5, QLineEdit(plan.get("app_command") or ""))
            else:
                table.setItem(row, 5, table_item(""))
            table.setItem(row, 6, table_item(hm.format_bytes(plan.get("size"))))
        table.resizeColumnsToContents()
        if plans:
            table.selectRow(0)

    @staticmethod
    def _blockers(plan: dict, php: str) -> list[str]:
        """A missing PHP version stops blocking once another one is picked."""
        return [b for b in plan.get("blockers") or []
                if not (php and b.startswith(f"PHP {plan.get('php_version')} is not"))]

    def _php_changed(self, row: int) -> None:
        plan = self.sites_table.item(row, 1).data(Qt.ItemDataRole.UserRole)
        check = self.sites_table.cellWidget(row, 0)
        allowed = not self._blockers(plan, self._php(row))
        check.setEnabled(allowed)
        check.setChecked(allowed)

    def _php(self, row: int) -> str:
        widget = self.sites_table.cellWidget(row, 3)
        return widget.currentData() if isinstance(widget, QComboBox) else ""

    def _show_plan(self) -> None:
        rows = self.sites_table.selectionModel().selectedRows()
        if rows:
            plan = self.sites_table.item(rows[0].row(), 1).data(Qt.ItemDataRole.UserRole)
            self.plan_view.setPlainText(plan_details(plan))

    def chosen(self) -> list[dict]:
        """import-start's sites, as the page's `chosen`."""
        result = []
        for row in range(self.sites_table.rowCount()):
            plan = self.sites_table.item(row, 1).data(Qt.ItemDataRole.UserRole)
            check = self.sites_table.cellWidget(row, 0)
            php = self._php(row)
            if not check.isChecked() or self._blockers(plan, php):
                continue
            if plan.get("existing"):
                result.append({"id": plan["id"]})
                continue
            choice = {"id": plan["id"], "name": self.sites_table.cellWidget(row, 4).text().strip()}
            if plan.get("type") == "php" and php:
                choice["php_version"] = php
            command = self.sites_table.cellWidget(row, 5)
            if isinstance(command, QLineEdit) and command.text().strip():
                choice["app_command"] = command.text().strip()
            result.append(choice)
        return result

    def _start(self) -> None:
        sites = self.chosen()
        if not sites:
            self.show_error("Choose at least one site that can be imported.")
            return

        def started(status: dict) -> None:
            self._done_count = 0
            self.show_status(status)

        self.call(f"Starting the import of {len(sites)} site(s)…", lambda: self.connection.import_start(sites),
                  started)

    def _show_progress(self, job: dict, running: bool) -> None:
        sites = job.get("sites") or []
        if job.get("state") == "running":
            self.progress_summary.setText("Importing. This goes on if you close this dialog.")
        else:
            done = sum(1 for site in sites if site.get("state") == "done")
            self.progress_summary.setText(
                f"{done} of {len(sites)} sites imported. Each site answers here to its own domains: point their "
                "DNS at this server, then switch the certificates to Let's Encrypt.")
        passwords = [p for site in sites for p in site.get("passwords") or []]
        self.passwords_box.setVisible(bool(passwords))
        fill_table(self.passwords_table, [[p["database"], p["user"], p["password"]] for p in passwords])

        def details(site: dict) -> str:
            parts = []
            if site.get("state") == "running" and site.get("step"):
                parts.append(site["step"] + (f" ({site['progress']}%)" if site.get("progress") is not None else "…"))
            if site.get("error"):
                parts.append(site["error"])
            parts.extend(site.get("warnings") or [])
            if site.get("state") != "running" and site.get("results"):
                parts.append(" · ".join(site["results"]))
            return "\n".join(parts)

        def state(site: dict) -> str:
            if site.get("state") == "done" and site.get("existing"):
                return "Synced"
            return STATE_LABELS.get(site.get("state"), site.get("state") or "")

        fill_table(self.progress_table, [[site["domain"], site.get("name", ""), state(site), details(site)]
                                         for site in sites])
        self.pages.setCurrentWidget(self.progress_page)
        if running:
            self.set_buttons(self.button("Stop the Import", self._cancel), self.button("Close", self.reject))
        else:
            self.set_buttons(self.button("Clear Results", self._clear), self.button("Close", self.reject))

    def _cancel(self) -> None:
        self.call("Stopping the import…", self.connection.import_cancel, self.show_status)

    def _clear(self) -> None:
        def cleared(status: dict) -> None:
            self.status = status
            if status.get("scan"):
                self._show_choose(status["scan"])
            else:
                self._show_connect()

        self.call("Clearing the results…", self.connection.import_clear, cleared)


# -- Zabbix ---------------------------------------------------------------------------------


class ZabbixImportDialog(_ImportDialog):
    """Replace a Zabbix site's data with a dedicated Zabbix server's:
    connect, review the scan and choose what comes across, watch."""

    def __init__(self, connection: hm.HostingConnection, site: dict, parent: QWidget | None = None) -> None:
        super().__init__("Import from Another Zabbix Server", parent)
        self.connection = connection
        self.site = site
        self.name = site["name"]
        self.connect_page: ConnectPage | None = None
        self._started = False
        self._rescan = False

        self.config = QLineEdit("/etc/zabbix/zabbix_server.conf")
        self.config.setToolTip("Where the database login is read from")
        self.db_engine = QComboBox()
        self.db_engine.addItem("From the installed server package", "")
        self.db_engine.addItem("PostgreSQL", "postgresql")
        self.db_engine.addItem("MySQL or MariaDB", "mysql")
        self.db_fields: dict[str, QLineEdit] = {}
        for key in ("host", "port", "name", "user", "password"):
            edit = QLineEdit()
            if key == "password":
                edit.setEchoMode(QLineEdit.EchoMode.Password)
            self.db_fields[key] = edit

        self.scan_page = QWidget()
        self.scan_summary = _label()
        self.history = QCheckBox("History and trends (without them, graphs start empty)")
        self.history.setChecked(True)
        self.scripts = QCheckBox("Alert and external scripts")
        self.scripts.setChecked(True)
        self.settings = QCheckBox("Server settings")
        self.settings.setChecked(True)
        self.scan_notes = _label()
        self.warning = _label(f"Everything in {site.get('primary_domain') or self.name}'s Zabbix is replaced by "
                              "the import. Its database is kept aside and put back if the import fails. Once this "
                              "Zabbix runs, it polls the same hosts and sends the same alerts as the old one until "
                              "that is switched off.")
        theme.set_tone(self.warning, "warning")
        scan = QVBoxLayout(self.scan_page)
        scan.addWidget(self.scan_summary)
        self.options_box = QGroupBox("What comes across")
        options = QVBoxLayout(self.options_box)
        for box in (self.history, self.scripts, self.settings):
            options.addWidget(box)
        scan.addWidget(self.options_box)
        scan.addWidget(self.scan_notes)
        scan.addWidget(self.warning)
        scan.addStretch(1)

        self.job_page = QWidget()
        self.job_state = _label()
        self.job_progress = QProgressBar()
        self.job_details = _label()
        job = QVBoxLayout(self.job_page)
        job.addWidget(self.job_state)
        job.addWidget(self.job_progress)
        job.addWidget(self.job_details)
        job.addStretch(1)

        self.pages.addWidget(_label("Loading…"))
        self.pages.addWidget(self.scan_page)
        self.pages.addWidget(self.job_page)
        self.set_buttons(self.button("Close", self.reject))
        self.refresh()

    def fetch_status(self) -> dict:
        return self.connection.zabbix_import_status(self.name)

    def show_status(self, status: dict) -> None:
        super().show_status(status)
        if self.connect_page is None:
            source = (status.get("scan") or {}).get("source") or status.get("source")
            self.connect_page = ConnectPage("Zabbix", self.connection, source)
            self.connect_page.set_public_key(status.get("public_key"))
            if (status.get("scan") or {}).get("config"):
                self.config.setText(status["scan"]["config"])
            form = self.connect_page.form
            form.addRow("Server configuration:", self.config)
            form.addRow(_label("Only when zabbix_server.conf doesn't name them (a vault, a server not installed "
                               "from packages): leave empty what it says."))
            form.addRow("Database type:", self.db_engine)
            for key, label in (("host", "Database host"), ("port", "Database port"), ("name", "Database name"),
                               ("user", "Database user"), ("password", "Database password")):
                form.addRow(f"{label}:", self.db_fields[key])
            self.pages.addWidget(self.connect_page)
        if status.get("job") and not self._rescan:
            self._show_job(status)
        elif not self._started:
            self._started = True
            if status.get("scan"):
                self._show_scan(status["scan"])
            else:
                self._show_connect()

    def _show_connect(self) -> None:
        self._rescan = True
        self.pages.setCurrentWidget(self.connect_page)
        self.set_buttons(self.button("Scan", self._scan), self.button("Cancel", self.reject))

    def scan_input(self) -> dict:
        scan_input = self.connect_page.scan_input()
        scan_input["config"] = self.config.text().strip()
        database = {key: edit.text().strip() if key != "password" else edit.text()
                    for key, edit in self.db_fields.items() if edit.text().strip()}
        if self.db_engine.currentData():
            database["engine"] = self.db_engine.currentData()
        if database:
            scan_input["database"] = database
        return scan_input

    def _scan(self) -> None:
        scan_input = self.scan_input()
        if not scan_input["host"]:
            self.show_error("Enter the Zabbix server's host name or address.")
            return
        self.call("Scanning the Zabbix server…", lambda: self.connection.zabbix_import_scan(self.name, scan_input),
                  self._show_scan)

    def _show_scan(self, scan: dict) -> None:
        self.scan = scan
        info = scan.get("info")
        source = scan.get("source") or {}
        lines = [f"Server: {source.get('host')}" + (f"  {source['fingerprint']}" if source.get("fingerprint") else "")]
        if info:
            version = scan.get("server_version") or info.get("release")
            target = scan.get("target")
            lines.append(f"Zabbix {version}" + (f" (becomes {target} here)" if target and target != info.get("release")
                                                else ""))
            history = (f" ({hm.format_bytes(info['history_size'])} history and trends)"
                       if info.get("history_size") else "")
            lines.append(f"Database: {hm.ZABBIX_ENGINE_LABELS.get(info.get('engine'), info.get('engine'))} "
                         f"{info.get('db_version')}, {hm.format_bytes(info.get('size'))}{history}")
            lines.append(f"Contents: {info.get('hosts')} hosts, {info.get('templates')} templates, "
                         f"{info.get('users')} users")
        scripts = scan.get("scripts") or {}
        lines.append("Scripts: " + ("; ".join(f"{s['path']}: {s['files']} files" for s in scripts.values()) or "None"))
        blockers = scan.get("blockers") or []
        if blockers:
            lines.append("\nThis Zabbix can't be imported:\n" + "\n".join(f"  • {b}" for b in blockers))
        self.scan_summary.setText("\n".join(lines))
        script_files = sum(s.get("files", 0) for s in scripts.values())
        self.scripts.setEnabled(script_files > 0)
        self.scripts.setText(f"Alert and external scripts ({script_files} files)")
        settings = scan.get("settings") or {}
        self.settings.setEnabled(bool(settings))
        self.settings.setText("Server settings: " + (", ".join(f"{k}={v}" for k, v in settings.items())
                                                     or "zabbix_server.conf changes none that come across"))
        notes = []
        if scan.get("notes"):
            notes.append("Good to know:\n" + "\n".join(f"  • {n}" for n in scan["notes"]))
        if scan.get("skipped"):
            notes.append("Not carried over:\n" + "\n".join(f"  • {s}" for s in scan["skipped"]))
        self.scan_notes.setText("\n\n".join(notes))
        self.options_box.setVisible(not blockers)
        self.warning.setVisible(not blockers)
        self.pages.setCurrentWidget(self.scan_page)
        start = self.button("Import", self._start)
        start.setEnabled(not blockers)
        self.set_buttons(start, self.button("Back", self._show_connect),
                         self.button("Forget This Server", self._forget), self.button("Cancel", self.reject))

    def options(self) -> dict:
        return {
            "history": self.history.isChecked(),
            "scripts": self.scripts.isChecked() and self.scripts.isEnabled(),
            "settings": self.settings.isChecked() and self.settings.isEnabled(),
        }

    def _start(self) -> None:
        options = self.options()

        def started(status: dict) -> None:
            self._rescan = False
            self.show_status(status)

        self.call("Starting the Zabbix import…", lambda: self.connection.zabbix_import_start(self.name, options),
                  started)

    def _forget(self) -> None:
        def forgotten(status: dict) -> None:
            self.status = status
            self._show_connect()

        self.call("Forgetting the server…", lambda: self.connection.zabbix_import_forget(self.name), forgotten)

    def _show_job(self, status: dict) -> None:
        job = status["job"]
        state = job.get("state")
        self.job_state.setText({
            "running": (job.get("step") or "Starting") + "\n\nThe import goes on if this dialog is closed.",
            "done": "Zabbix was imported.",
            "failed": f"The import failed:\n{job.get('failure') or ''}",
            "cancelled": "The import was cancelled.",
        }.get(state, state or ""))
        self.job_progress.setVisible(state == "running")
        if job.get("progress") is None:
            self.job_progress.setRange(0, 0)
        else:
            self.job_progress.setRange(0, 100)
            self.job_progress.setValue(int(job["progress"]))
        self.job_details.setText("\n".join([f"• {r}" for r in job.get("results") or []]
                                           + [f"⚠ {w}" for w in job.get("warnings") or []]))
        self.pages.setCurrentWidget(self.job_page)
        if status.get("running"):
            self.set_buttons(self.button("Cancel Import", self._cancel), self.button("Close", self.reject))
        else:
            self.set_buttons(self.button("Import Again", self._again), self.button("Done", self.accept))

    def _cancel(self) -> None:
        self.call("Cancelling the import…", lambda: self.connection.zabbix_import_cancel(self.name),
                  self.show_status)

    def _again(self) -> None:
        def cleared(status: dict) -> None:
            self.status = status
            self._show_connect()

        self.call("Clearing the import…", lambda: self.connection.zabbix_import_clear(self.name), cleared)
