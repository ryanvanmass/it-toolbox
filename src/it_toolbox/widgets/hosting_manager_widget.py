"""One Hosting Manager tab (General Tools): manages a web server set up by
the user's cockpit-hosting Cockpit module over SSH, with the same features
as that module's page -- sites (static, PHP, reverse proxy, Node.js,
Python, container), SSL, databases, cron jobs, SFTP, logs, WordPress and
Nextcloud deployment, malware scanning, and installing the server stack.
See core/hosting_manager.py for how it talks to the server.
"""

from __future__ import annotations

import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from it_toolbox.core import hosting_manager as hm
from it_toolbox.widgets import hosting_dialogs as dialogs
from it_toolbox.widgets import status_bar
from it_toolbox.widgets.remote_helper_widget import (
    RemoteHelperTab,
    fill_table,
    make_table,
    selected_data,
)

TITLE = dialogs.TITLE


def when_label(value: str | None) -> str:
    """An ISO timestamp from the helper as local time, minutes precision."""
    if not value:
        return ""
    try:
        parsed = datetime.datetime.fromisoformat(value)
    except ValueError:
        return value
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone()
    return parsed.strftime("%Y-%m-%d %H:%M")


def size_label(num_bytes: int | None) -> str:
    if num_bytes is None:
        return ""
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return ""


def https_label(site: dict) -> str:
    mode = site.get("ssl_mode") or "none"
    if mode == "none":
        return "No"
    cert = site.get("certificate") or {}
    expires = cert.get("expires")
    return f"{hm.SSL_MODE_LABELS.get(mode, mode)}, expires {when_label(expires)}" if expires else \
        hm.SSL_MODE_LABELS.get(mode, mode)


def app_label(site: dict) -> str:
    if site.get("application"):
        app = site["application"]
        return f"{hm.APPLICATION_LABELS.get(app['name'], app['name'])} {app.get('version') or ''}".strip()
    return site.get("app_state") or ""


def _group(title: str, *rows: QWidget | QHBoxLayout) -> QGroupBox:
    box = QGroupBox(title)
    layout = QVBoxLayout(box)
    for row in rows:
        if isinstance(row, QWidget):
            layout.addWidget(row)
        else:
            layout.addLayout(row)
    return box


def _row(*widgets: QWidget, stretch: bool = True) -> QHBoxLayout:
    layout = QHBoxLayout()
    for widget in widgets:
        layout.addWidget(widget)
    if stretch:
        layout.addStretch(1)
    return layout


def _button(text: str, slot) -> QPushButton:
    button = QPushButton(text)
    button.clicked.connect(lambda _=False: slot())
    return button


def _confirm(parent: QWidget, title: str, text: str) -> bool:
    return QMessageBox.question(parent, title, text) == QMessageBox.StandardButton.Yes


# -- One site --------------------------------------------------------------------


class SiteDetail(QWidget):
    """The right-hand side of the Sites tab: everything about one site,
    in sub-tabs. `site` is the helper's site-get reply."""

    def __init__(self, manager: HostingManagerWidget) -> None:
        super().__init__()
        self.manager = manager
        self.site: dict | None = None

        self.heading = QLabel()
        font = self.heading.font()
        font.setPointSize(font.pointSize() + 3)
        font.setBold(True)
        self.heading.setFont(font)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_settings_tab(), "Settings")
        self.tabs.addTab(self._build_https_tab(), "SSL")
        self.databases_index = self.tabs.addTab(self._build_databases_tab(), "Databases")
        self.cron_index = self.tabs.addTab(self._build_cron_tab(), "Cron Jobs")
        self.sftp_index = self.tabs.addTab(self._build_sftp_tab(), "SFTP")
        self.logs_index = self.tabs.addTab(self._build_logs_tab(), "Logs")
        self.tabs.addTab(self._build_nginx_tab(), "nginx")
        self.tabs.currentChanged.connect(self._on_tab_changed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.heading)
        layout.addWidget(self.tabs, 1)
        self.setEnabled(False)

    @property
    def connection(self) -> hm.HostingConnection:
        return self.manager.connection

    @property
    def name(self) -> str:
        return self.site["name"] if self.site else ""

    def busy(self, *args, **kwargs) -> None:
        self.manager.busy(*args, **kwargs)

    def clear(self) -> None:
        self.site = None
        self.heading.setText("Select a site")
        self.setEnabled(False)

    def load(self, name: str) -> None:
        self.busy(f"Loading {name}…", lambda: self.connection.site_get(name), self.show_site)

    def show_site(self, site: dict) -> None:
        """Shows a fresh site-get reply, and passes it on to the list."""
        previous = self.name
        self.site = site
        self.setEnabled(True)
        self.heading.setText(
            f"{site.get('primary_domain') or site['name']} — {hm.SITE_TYPE_LABELS.get(site['type'], site['type'])}"
        )
        self._show_settings(site)
        self._show_https(site)
        self._show_databases(site)
        self.custom_nginx.setPlainText(site.get("custom_nginx") or "")
        self.manager.update_site_row(site)
        if previous != site["name"]:
            self.cron_table.setRowCount(0)
            self.log_view.clear()
            self.sftp_loaded = False
        self._on_tab_changed(self.tabs.currentIndex())

    def _on_tab_changed(self, index: int) -> None:
        if self.site is None:
            return
        if index == self.cron_index:
            self.refresh_cron()
        elif index == self.sftp_index and not self.sftp_loaded:
            self.refresh_sftp()
        elif index == self.logs_index and not self.log_view.toPlainText():
            self.refresh_logs()

    def _update(self, message: str, changes: dict, done: str = "Saved") -> None:
        name = self.name
        self.busy(message, lambda: self.connection.site_update(name, changes), self.show_site, done)

    # -- Settings -------------------------------------------------------------

    def _build_settings_tab(self) -> QWidget:
        page = QWidget()
        self.info = QLabel()
        self.info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.info.setWordWrap(True)

        self.domains = QPlainTextEdit()
        self.domains.setFixedHeight(70)
        self.domains.setToolTip("One per line; the first is the primary domain.")
        self.force_https = QCheckBox("Redirect HTTP to HTTPS")
        self.php_version = QComboBox()
        self.php_settings: dict[str, QLineEdit] = {key: QLineEdit() for key in hm.PHP_SETTING_KEYS}
        self.upstream = QLineEdit()
        self.app_command = QLineEdit()
        self.app_env = QPlainTextEdit()
        self.app_env.setFixedHeight(70)
        self.app_env.setPlaceholderText("KEY=value, one per line")
        self.image = QLineEdit()
        self.container_port = QSpinBox()
        self.container_port.setRange(1, 65535)
        self.volumes = QLineEdit()
        self.volumes.setToolTip("Paths inside the container, comma-separated")
        self.auto_update = QCheckBox("Update the image automatically (podman auto-update)")

        self.settings_form = QFormLayout()
        self.settings_form.addRow("Domains:", self.domains)
        self.settings_form.addRow("", self.force_https)
        self.settings_form.addRow("PHP version:", self.php_version)
        for key, edit in self.php_settings.items():
            self.settings_form.addRow(f"{key}:", edit)
        self.settings_form.addRow("Upstream URL:", self.upstream)
        self.settings_form.addRow("Image:", self.image)
        self.settings_form.addRow("Container port:", self.container_port)
        self.settings_form.addRow("Volumes:", self.volumes)
        self.settings_form.addRow("", self.auto_update)
        self.settings_form.addRow("Start command:", self.app_command)
        self.settings_form.addRow("Environment:", self.app_env)
        save = _button("Save Settings", self._save_settings)

        self.app_state = QLabel()
        self.app_buttons = {
            action: _button(label, lambda a=action: self._app_control(a))
            for action, label in (("start", "Start"), ("stop", "Stop"), ("restart", "Restart"),
                                  ("pull", "Pull Image && Restart"))
        }
        self.app_box = _group("App", _row(self.app_state, *self.app_buttons.values()))

        self.application_label = QLabel()
        self.application_label.setWordWrap(True)
        self.deploy_button = _button("Deploy WordPress or Nextcloud…", self._deploy)
        self.application_box = _group("Application", _row(self.application_label, self.deploy_button))

        delete = _button("Delete Site…", lambda: self.manager.delete_site(self.site))

        inner = QVBoxLayout(page)
        inner.addWidget(self.info)
        inner.addWidget(self.app_box)
        inner.addWidget(self.application_box)
        inner.addLayout(self.settings_form)
        inner.addLayout(_row(save, delete))
        inner.addStretch(1)
        return page

    def _show_settings(self, site: dict) -> None:
        site_type = site["type"]
        lines = [
            f"Site user: {site['system_user']}    Home: {site['home']}",
            f"Files: {site['root_dir']}",
            f"Logs: {site['logs_dir']}",
        ]
        if site.get("runtime_version"):
            lines.append(f"Runtime: {site['runtime_version']}")
        if site.get("app_port"):
            lines.append(f"App port: 127.0.0.1:{site['app_port']}")
        info = site.get("container_info")
        if info:
            lines.append(f"Image ID: {info.get('image_id', '')[:12]}  created {when_label(info.get('created'))}  "
                         f"{size_label(info.get('size'))}")
        lines.append(f"Created: {when_label(site.get('created_at'))}")
        self.info.setText("\n".join(lines))

        self.domains.setPlainText("\n".join(site.get("domains") or []))
        self.force_https.setChecked(bool(site.get("force_https")))
        self.force_https.setEnabled(site.get("ssl_mode", "none") != "none")

        php = site_type == "php"
        self.php_version.clear()
        if php:
            for entry in (self.manager.server_status.get("stack") or {}).get("php") or []:
                self.php_version.addItem(f"PHP {entry['version']}", entry["version"])
            index = self.php_version.findData(site.get("runtime_version"))
            if index < 0:
                self.php_version.addItem(f"PHP {site.get('runtime_version')}", site.get("runtime_version"))
                index = self.php_version.count() - 1
            self.php_version.setCurrentIndex(index)
        settings = site.get("php_settings") or {}
        for key, edit in self.php_settings.items():
            edit.setText(str(settings.get(key, "")))
            self.settings_form.setRowVisible(edit, php)
        self.settings_form.setRowVisible(self.php_version, php)

        self.upstream.setText(site.get("upstream") or "")
        self.settings_form.setRowVisible(self.upstream, site_type == "proxy")

        container = site.get("container") or {}
        is_container = site_type == "container"
        self.image.setText(container.get("image", ""))
        self.container_port.setValue(int(container.get("port") or 80))
        self.volumes.setText(", ".join(container.get("volumes") or []))
        self.auto_update.setChecked(bool(container.get("auto_update")))
        for widget in (self.image, self.container_port, self.volumes, self.auto_update):
            self.settings_form.setRowVisible(widget, is_container)

        runs_app = site_type in hm.APP_SITE_TYPES
        self.app_command.setText((container.get("command") if is_container else site.get("app_command")) or "")
        self.app_env.setPlainText(dialogs.format_env(site.get("app_env")))
        self.settings_form.setRowVisible(self.app_command, runs_app)
        self.settings_form.setRowVisible(self.app_env, runs_app)

        self.app_box.setVisible(runs_app)
        self.app_state.setText(f"State: {site.get('app_state') or 'unknown'}")
        self.app_buttons["pull"].setVisible(is_container)

        self.application_box.setVisible(php)
        app = site.get("application")
        if app:
            self.application_label.setText(
                f"{hm.APPLICATION_LABELS.get(app['name'], app['name'])} {app.get('version') or ''} — "
                f"admin user {app.get('admin_user')}, admin page {app.get('admin_path')}"
            )
        else:
            self.application_label.setText("No application deployed.")
        self.deploy_button.setVisible(not app)

    def _save_settings(self) -> None:
        site = self.site
        changes: dict = {}
        domains = [line.strip() for line in self.domains.toPlainText().splitlines() if line.strip()]
        if domains != (site.get("domains") or []):
            changes["domains"] = domains
        if self.force_https.isEnabled() and self.force_https.isChecked() != bool(site.get("force_https")):
            changes["force_https"] = self.force_https.isChecked()
        site_type = site["type"]
        if site_type == "php":
            if self.php_version.currentData() != site.get("runtime_version"):
                changes["php_version"] = self.php_version.currentData()
            current = site.get("php_settings") or {}
            php_changes = {key: edit.text().strip() for key, edit in self.php_settings.items()
                           if edit.text().strip() != str(current.get(key, ""))}
            if php_changes:
                changes["php_settings"] = php_changes
        if site_type == "proxy" and self.upstream.text().strip() != (site.get("upstream") or ""):
            changes["upstream"] = self.upstream.text().strip()
        if site_type in hm.APP_SITE_TYPES:
            try:
                env = dialogs.parse_env(self.app_env.toPlainText())
            except ValueError as exc:
                QMessageBox.warning(self, TITLE, f"Environment: {exc}")
                return
            if env != (site.get("app_env") or {}):
                changes["app_env"] = env
        if site_type == "container":
            container = site.get("container") or {}
            wanted = {
                "image": self.image.text().strip(),
                "container_port": self.container_port.value(),
                "volumes": [v.strip() for v in self.volumes.text().split(",") if v.strip()],
                "command": self.app_command.text().strip(),
                "auto_update": self.auto_update.isChecked(),
            }
            have = {
                "image": container.get("image", ""),
                "container_port": container.get("port"),
                "volumes": container.get("volumes") or [],
                "command": container.get("command") or "",
                "auto_update": bool(container.get("auto_update")),
            }
            changes.update({key: value for key, value in wanted.items() if value != have[key]})
        elif site_type in hm.APP_SITE_TYPES and self.app_command.text().strip() != (site.get("app_command") or ""):
            changes["app_command"] = self.app_command.text().strip()
        if not changes:
            self.manager.flash("Nothing changed")
            return
        self._update(f"Saving {self.name}…", changes)

    def _app_control(self, action: str) -> None:
        name = self.name
        labels = {"start": "Starting", "stop": "Stopping", "restart": "Restarting", "pull": "Pulling the image for"}
        self.busy(f"{labels[action]} {name}…", lambda: self.connection.app_control(name, action), self.show_site,
                  "Done")

    def _deploy(self) -> None:
        dialog = dialogs.DeployDialog(self.site, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        deploy_input = dialog.deploy_input()
        name = self.name
        label = hm.APPLICATION_LABELS[deploy_input["application"]]

        def done(result: dict) -> None:
            self.show_site(result["site"])
            self.manager.refresh_databases()
            dialogs.CredentialsDialog(
                f"{label} Deployed",
                f"{label} is installed. Save the admin password now — it isn't shown again.",
                [("Admin page", result.get("admin_url", "")), ("Admin user", result.get("admin_user", "")),
                 ("Admin password", result.get("admin_password", ""))],
                self,
            ).exec()

        self.busy(f"Deploying {label} to {name}…", lambda: self.connection.app_deploy(name, deploy_input), done,
                  f"{label} deployed")

    # -- SSL ------------------------------------------------------------------

    def _build_https_tab(self) -> QWidget:
        page = QWidget()
        self.https_state = QLabel()
        self.https_state.setWordWrap(True)
        self.dns_provider = QComboBox()
        for provider in hm.DNS_PROVIDERS:
            self.dns_provider.addItem(hm.DNS_PROVIDER_LABELS[provider], provider)
        http = _button("Get Certificate (HTTP Challenge)", lambda: self._issue("http"))
        dns = _button("Get Certificate (DNS Challenge)", lambda: self._issue("dns"))
        custom = _button("Upload Certificate…", self._custom_certificate)
        self.remove_cert = _button("Remove SSL", self._remove_certificate)
        note = QLabel(
            "Let's Encrypt over HTTP needs every domain pointing at this server on port 80. "
            "The DNS challenge needs the provider's API credentials (Server tab) and also covers "
            "domains that aren't reachable yet."
        )
        note.setWordWrap(True)
        layout = QVBoxLayout(page)
        layout.addWidget(self.https_state)
        layout.addWidget(_group("Let's Encrypt", _row(http), _row(dns, QLabel("Provider:"), self.dns_provider), note))
        layout.addLayout(_row(custom, self.remove_cert))
        layout.addStretch(1)
        return page

    def _show_https(self, site: dict) -> None:
        mode = site.get("ssl_mode") or "none"
        text = f"SSL: {hm.SSL_MODE_LABELS.get(mode, mode)}"
        cert = site.get("certificate")
        if cert:
            text += f"\nIssuer: {cert.get('issuer', '')}\nExpires: {when_label(cert.get('expires'))}"
        if site.get("dns_provider"):
            text += f"\nDNS provider: {hm.DNS_PROVIDER_LABELS.get(site['dns_provider'], site['dns_provider'])}"
        self.https_state.setText(text)
        self.remove_cert.setEnabled(mode != "none")
        if site.get("dns_provider"):
            self.dns_provider.setCurrentIndex(max(0, self.dns_provider.findData(site["dns_provider"])))

    def _issue(self, method: str) -> None:
        name = self.name
        provider = self.dns_provider.currentData() if method == "dns" else None
        if not self.manager.server_status.get("settings", {}).get("acme_email") and not _confirm(
            self, TITLE, "No Let's Encrypt account email is set (Server tab), so you won't get expiry "
                         "warnings. Continue anyway?"):
            return
        self.busy(f"Getting a certificate for {name}…", lambda: self.connection.ssl_issue(name, method, provider),
                  self.show_site, "Certificate installed")

    def _custom_certificate(self) -> None:
        dialog = dialogs.CustomCertificateDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name = self.name
        cert, key = dialog.certificate.toPlainText(), dialog.private_key.toPlainText()
        self.busy(f"Installing the certificate for {name}…", lambda: self.connection.ssl_custom(name, cert, key),
                  self.show_site, "Certificate installed")

    def _remove_certificate(self) -> None:
        name = self.name
        if _confirm(self, "Remove SSL", f"Remove {name}'s certificate and serve it over HTTP only?"):
            self.busy(f"Removing SSL from {name}…", lambda: self.connection.ssl_remove(name), self.show_site,
                      "SSL removed")

    # -- Databases --------------------------------------------------------------

    def _build_databases_tab(self) -> QWidget:
        page = QWidget()
        self.site_db_table = make_table(["Database", "User", "Created"])
        layout = QVBoxLayout(page)
        layout.addLayout(_row(
            _button("Create Database…", lambda: self.manager.create_database(self.name)),
            _button("Reset Password…", lambda: self.manager.reset_database_password(selected_data(self.site_db_table))),
            _button("Delete…", lambda: self.manager.delete_database(selected_data(self.site_db_table))),
        ))
        layout.addWidget(self.site_db_table, 1)
        return page

    def _show_databases(self, site: dict) -> None:
        databases = site.get("databases") or []
        fill_table(self.site_db_table,
                   [[db["name"], db.get("db_user"), when_label(db.get("created_at"))] for db in databases],
                   [db["name"] for db in databases])

    # -- Cron -------------------------------------------------------------------

    def _build_cron_tab(self) -> QWidget:
        page = QWidget()
        self.cron_table = make_table(["Schedule", "Command", "Enabled", "Next run", "Last run", "Last result"])
        self.cron_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.cron_table.customContextMenuRequested.connect(self._cron_menu)
        self.cron_table.doubleClicked.connect(lambda _: self._edit_cron())
        layout = QVBoxLayout(page)
        layout.addLayout(_row(
            _button("Add Job…", self._add_cron),
            _button("Edit…", self._edit_cron),
            _button("Run Now", self._run_cron),
            _button("Show Output", self._cron_log),
            _button("Delete", self._delete_cron),
            _button("Refresh", self.refresh_cron),
        ))
        layout.addWidget(self.cron_table, 1)
        return page

    def refresh_cron(self) -> None:
        name = self.name
        self.busy(f"Loading {name}'s cron jobs…", lambda: self.connection.cron_list(name), self.show_cron)

    def show_cron(self, jobs: list[dict]) -> None:
        def result(job):
            if job.get("running"):
                return "running"
            if not job.get("last_result"):
                return ""
            status = job.get("last_status")
            return job["last_result"] + (f" (exit {status})" if status not in (None, 0) else "")

        fill_table(self.cron_table, [
            [job["schedule"], job["command"], "Yes" if job.get("enabled") else "No",
             when_label(job.get("next_run")), when_label(job.get("last_run")), result(job)]
            for job in jobs
        ], jobs)

    def _selected_job(self) -> dict | None:
        job = selected_data(self.cron_table)
        if job is None:
            self.manager.flash("Select a cron job first")
        return job

    def _cron_menu(self, pos) -> None:
        job = selected_data(self.cron_table)
        menu = QMenu(self)
        if job is not None:
            menu.addAction("Edit…").triggered.connect(self._edit_cron)
            menu.addAction("Disable" if job.get("enabled") else "Enable").triggered.connect(self._toggle_cron)
            menu.addAction("Run Now").triggered.connect(self._run_cron)
            menu.addAction("Show Output").triggered.connect(self._cron_log)
            menu.addAction("Delete").triggered.connect(self._delete_cron)
            menu.addSeparator()
        menu.addAction("Add Job…").triggered.connect(self._add_cron)
        menu.exec(self.cron_table.viewport().mapToGlobal(pos))

    def _after_cron_change(self, _=None) -> None:
        self.refresh_cron()

    def _add_cron(self) -> None:
        dialog = dialogs.CronJobDialog(parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        schedule, command = dialog.values()
        name = self.name
        self.busy("Adding the cron job…", lambda: self.connection.cron_create(name, schedule, command),
                  self._after_cron_change, "Cron job added")

    def _edit_cron(self) -> None:
        job = self._selected_job()
        if job is None:
            return
        dialog = dialogs.CronJobDialog(job, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        schedule, command = dialog.values()
        self.busy("Saving the cron job…",
                  lambda: self.connection.cron_update(job["id"], {"schedule": schedule, "command": command}),
                  self._after_cron_change, "Cron job saved")

    def _toggle_cron(self) -> None:
        job = self._selected_job()
        if job is not None:
            enabled = not job.get("enabled")
            self.busy("Saving the cron job…", lambda: self.connection.cron_update(job["id"], {"enabled": enabled}),
                      self._after_cron_change)

    def _run_cron(self) -> None:
        job = self._selected_job()
        if job is not None:
            self.busy("Starting the cron job…", lambda: self.connection.cron_run(job["id"]),
                      self._after_cron_change, "Cron job started")

    def _cron_log(self) -> None:
        job = self._selected_job()
        if job is not None:
            self.busy("Loading the job's output…", lambda: self.connection.cron_log(job["id"]),
                      lambda text: self.manager.show_text(f"Output of: {job['command']}", text or "(no output yet)"))

    def _delete_cron(self) -> None:
        job = self._selected_job()
        if job is not None and _confirm(self, "Delete Cron Job", f"Delete the job '{job['command']}'?"):
            self.busy("Deleting the cron job…", lambda: self.connection.cron_delete(job["id"]),
                      self._after_cron_change, "Cron job deleted")

    # -- SFTP -------------------------------------------------------------------

    def _build_sftp_tab(self) -> QWidget:
        page = QWidget()
        self.sftp_loaded = False
        self.sftp: dict = {}
        self.sftp_info = QLabel()
        self.sftp_info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.sftp_info.setWordWrap(True)
        self.sftp_enabled = QCheckBox("Allow SFTP logins for this site's user")
        self.sftp_enabled.clicked.connect(self._toggle_sftp)
        self.sftp_keys = QPlainTextEdit()
        self.sftp_keys.setPlaceholderText("ssh-ed25519 AAAA… one public key per line")
        self.sftp_keys.setFont(dialogs.monospace())
        layout = QVBoxLayout(page)
        layout.addWidget(self.sftp_enabled)
        layout.addWidget(self.sftp_info)
        layout.addLayout(_row(_button("Set Password…", self._sftp_password),
                              _button("Remove Password", self._sftp_clear_password)))
        layout.addWidget(QLabel("Authorized public keys:"))
        layout.addWidget(self.sftp_keys, 1)
        layout.addLayout(_row(_button("Save Keys", self._sftp_save_keys), _button("Refresh", self.refresh_sftp)))
        return page

    def refresh_sftp(self) -> None:
        name = self.name
        self.busy(f"Loading {name}'s SFTP access…", lambda: self.connection.sftp_get(name), self.show_sftp)

    def show_sftp(self, sftp: dict) -> None:
        self.sftp = sftp
        self.sftp_loaded = True
        self.sftp_enabled.setChecked(bool(sftp.get("enabled")))
        lines = [
            f"Login: {sftp.get('user')}@{sftp.get('host')} port {sftp.get('port')}",
            f"Starts in: {sftp.get('path')} (on the server: {sftp.get('server_path')})",
            "Password: " + ("set" if sftp.get("password_set") else "not set"),
        ]
        if not sftp.get("ssh_installed", True):
            lines.append("The SSH server isn't installed, so nobody can log in yet.")
        self.sftp_info.setText("\n".join(lines))
        self.sftp_keys.setPlainText("\n".join(sftp.get("keys") or []))

    def _sftp_set(self, changes: dict, message: str = "Saving SFTP access…") -> None:
        name = self.name

        def failed(_error):
            self.sftp_enabled.setChecked(bool(self.sftp.get("enabled")))

        self.busy(message, lambda: self.connection.sftp_set(name, changes), self.show_sftp, "Saved", failed)

    def _toggle_sftp(self, checked: bool) -> None:
        self._sftp_set({"enabled": checked})

    def _sftp_password(self) -> None:
        password, ok = QInputDialog.getText(self, "SFTP Password", f"New SFTP password for {self.name}:",
                                            QLineEdit.EchoMode.Password)
        if ok and password:
            self._sftp_set({"password": password})

    def _sftp_clear_password(self) -> None:
        if _confirm(self, "Remove Password", "Remove the SFTP password? Only key logins will work."):
            self._sftp_set({"clear_password": True})

    def _sftp_save_keys(self) -> None:
        self._sftp_set({"keys": self.sftp_keys.toPlainText()})

    # -- Logs -------------------------------------------------------------------

    def _build_logs_tab(self) -> QWidget:
        page = QWidget()
        self.log_name = QComboBox()
        for log in hm.LOG_NAMES:
            self.log_name.addItem(hm.LOG_LABELS[log], log)
        self.log_lines = QSpinBox()
        self.log_lines.setRange(1, 5000)
        self.log_lines.setValue(200)
        self.log_path = QLabel()
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFont(dialogs.monospace())
        self.log_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.log_name.currentIndexChanged.connect(lambda _: self.refresh_logs())
        layout = QVBoxLayout(page)
        layout.addLayout(_row(self.log_name, QLabel("Lines:"), self.log_lines, _button("Refresh", self.refresh_logs),
                              self.log_path))
        layout.addWidget(self.log_view, 1)
        return page

    def refresh_logs(self) -> None:
        if self.site is None:
            return
        name, log, lines = self.name, self.log_name.currentData(), self.log_lines.value()

        def show(result: dict) -> None:
            self.log_path.setText(result.get("path", ""))
            self.log_view.setPlainText(result.get("text") or "(empty)")
            self.log_view.verticalScrollBar().setValue(self.log_view.verticalScrollBar().maximum())

        self.busy("Loading the log…", lambda: self.connection.site_logs(name, log, lines), show)

    # -- Custom nginx ----------------------------------------------------------

    def _build_nginx_tab(self) -> QWidget:
        page = QWidget()
        note = QLabel("Extra nginx directives for this site's server block. They're checked with "
                      "nginx -t before being applied, and rolled back if nginx rejects them.")
        note.setWordWrap(True)
        self.custom_nginx = QPlainTextEdit()
        self.custom_nginx.setFont(dialogs.monospace())
        self.custom_nginx.setPlaceholderText("location /downloads/ {\n    autoindex on;\n}")
        layout = QVBoxLayout(page)
        layout.addWidget(note)
        layout.addWidget(self.custom_nginx, 1)
        layout.addLayout(_row(_button("Save", self._save_nginx)))
        return page

    def _save_nginx(self) -> None:
        name, text = self.name, self.custom_nginx.toPlainText()
        self.busy("Saving the nginx directives…", lambda: self.connection.site_custom_nginx(name, text),
                  self.custom_nginx.setPlainText, "nginx reloaded")


# -- The manager tab ---------------------------------------------------------------


class HostingManagerWidget(RemoteHelperTab):
    """Connects on construction, then shows the management tabs, or a
    page explaining that cockpit-hosting isn't installed."""

    TOOL_NAME = TITLE
    SITE_COLUMNS = ("Domain", "Type", "Site user", "SSL", "App")

    def __init__(self, server: hm.HostingServer, connection_factory=hm.HostingConnection,
                 parent: QWidget | None = None) -> None:
        super().__init__(server, connection_factory, parent)
        self.server_status: dict = {}
        self.sites: list[dict] = []
        self.databases: list[dict] = []
        self.malware: dict = {}

        self.missing_page = QLabel(
            "This server doesn't have the cockpit-hosting module "
            f"({hm.HELPER_PATH}).\n\nInstall the cockpit-hosting package (from the Bonkcloud "
            "package registry, or the RPM/.deb on its release page), then click Reconnect."
        )
        self.missing_page.setWordWrap(True)
        self.missing_page.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stack.addWidget(self.missing_page)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_sites_tab(), "Sites")
        self.tabs.addTab(self._build_databases_tab(), "Databases")
        self.tabs.addTab(self._build_malware_tab(), "Malware Scanning")
        self.tabs.addTab(self._build_server_tab(), "Server")
        self.stack.addWidget(self.tabs)

        self.connect_to_server()

    def flash(self, message: str) -> None:
        status_bar.begin(self, message).finish(message)

    def show_text(self, title: str, text: str) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(720, 480)
        view = QPlainTextEdit(text)
        view.setReadOnly(True)
        view.setFont(dialogs.monospace())
        layout = QVBoxLayout(dialog)
        layout.addWidget(view)
        dialog.exec()

    # -- Connecting --------------------------------------------------------------

    def on_connected(self) -> None:
        if self.connection.helper_path is None:
            self.stack.setCurrentWidget(self.missing_page)
            return
        self.show_message("Reading the server's status…")
        self.busy("Reading cockpit-hosting status…", self.connection.status, self._on_first_status)

    def _on_first_status(self, status: dict) -> None:
        self.show_status(status)
        self.stack.setCurrentWidget(self.tabs)
        self.refresh_sites()
        self.refresh_databases()
        self.refresh_malware()
        if not (status.get("stack") or {}).get("nginx", {}).get("version"):
            self.tabs.setCurrentIndex(self.tabs.count() - 1)

    # -- Sites -------------------------------------------------------------------

    def _build_sites_tab(self) -> QWidget:
        page = QWidget()
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter sites")
        self.filter.textChanged.connect(self._filter_sites)
        self.site_table = make_table(list(self.SITE_COLUMNS))
        self.site_table.itemSelectionChanged.connect(self._on_site_selected)
        self.site_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.site_table.customContextMenuRequested.connect(self._sites_menu)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addLayout(_row(_button("Create Site…", self.create_site), _button("Refresh", self.refresh_sites),
                                   stretch=False))
        left_layout.addWidget(self.filter)
        left_layout.addWidget(self.site_table, 1)
        self.detail = SiteDetail(self)
        self.detail.clear()
        splitter = QSplitter()
        splitter.addWidget(left)
        splitter.addWidget(self.detail)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([420, 880])
        layout = QVBoxLayout(page)
        layout.addWidget(splitter)
        return page

    def refresh_sites(self) -> None:
        self.busy("Loading sites…", self.connection.site_list, self.show_sites)

    def _site_row(self, site: dict) -> list:
        return [site.get("primary_domain") or site["name"], hm.SITE_TYPE_LABELS.get(site["type"], site["type"]),
                site["name"], https_label(site), app_label(site)]

    def show_sites(self, sites: list[dict]) -> None:
        selected = self.detail.name
        self.sites = sites
        self.site_table.blockSignals(True)
        fill_table(self.site_table, [self._site_row(site) for site in sites], [site["name"] for site in sites])
        self.site_table.blockSignals(False)
        self._filter_sites()
        names = [site["name"] for site in sites]
        if selected in names:
            self.site_table.selectRow(names.index(selected))
        else:
            self.detail.clear()

    def update_site_row(self, site: dict) -> None:
        for row in range(self.site_table.rowCount()):
            if self.site_table.item(row, 0).data(Qt.ItemDataRole.UserRole) == site["name"]:
                for column, value in enumerate(self._site_row(site)):
                    self.site_table.item(row, column).setText(str(value))
        self.sites = [site if s["name"] == site["name"] else s for s in self.sites]

    def _filter_sites(self) -> None:
        needle = self.filter.text().strip().lower()
        for row in range(self.site_table.rowCount()):
            text = " ".join(self.site_table.item(row, c).text() for c in range(self.site_table.columnCount()))
            domains = next((" ".join(s.get("domains") or []) for s in self.sites
                            if s["name"] == self.site_table.item(row, 0).data(Qt.ItemDataRole.UserRole)), "")
            self.site_table.setRowHidden(row, bool(needle) and needle not in f"{text} {domains}".lower())

    def _on_site_selected(self) -> None:
        name = selected_data(self.site_table)
        if name is None:
            self.detail.clear()
        elif name != self.detail.name:
            self.detail.load(name)

    def _sites_menu(self, pos) -> None:
        name = selected_data(self.site_table)
        site = next((s for s in self.sites if s["name"] == name), None)
        menu = QMenu(self)
        if site is not None:
            if site["type"] in hm.APP_SITE_TYPES:
                for action, label in (("start", "Start App"), ("stop", "Stop App"), ("restart", "Restart App")):
                    menu.addAction(label).triggered.connect(
                        lambda _=False, a=action: self.detail._app_control(a))
                menu.addSeparator()
            menu.addAction("Delete Site…").triggered.connect(lambda: self.delete_site(site))
            menu.addSeparator()
        menu.addAction("Create Site…").triggered.connect(self.create_site)
        menu.exec(self.site_table.viewport().mapToGlobal(pos))

    def create_site(self) -> None:
        dialog = dialogs.CreateSiteDialog(self.server_status, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        site_input = dialog.site_input()

        def done(site: dict) -> None:
            self.sites.append(site)
            self.detail.site = None
            self.show_sites(sorted(self.sites, key=lambda s: s["name"]))
            names = [s["name"] for s in self.sites]
            self.site_table.selectRow(names.index(site["name"]))

        self.busy(f"Creating {site_input['domain']}…", lambda: self.connection.site_create(site_input), done,
                  "Site created")

    def delete_site(self, site: dict | None) -> None:
        if site is None:
            return
        dialog = dialogs.DeleteSiteDialog(site, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name = site["name"]
        delete_databases, keep_files = dialog.delete_databases.isChecked(), dialog.keep_files.isChecked()

        def done(_):
            if self.detail.name == name:
                self.detail.clear()
            self.refresh_sites()
            self.refresh_databases()

        self.busy(f"Deleting {name}…", lambda: self.connection.site_delete(name, delete_databases, keep_files), done,
                  "Site deleted")

    # -- Databases ------------------------------------------------------------------

    def _build_databases_tab(self) -> QWidget:
        page = QWidget()
        self.db_table = make_table(["Database", "User", "Site", "Size", "Created"])
        layout = QVBoxLayout(page)
        layout.addLayout(_row(
            _button("Create Database…", lambda: self.create_database(None)),
            _button("Reset Password…", lambda: self.reset_database_password(selected_data(self.db_table))),
            _button("Delete…", lambda: self.delete_database(selected_data(self.db_table))),
            _button("Refresh", self.refresh_databases),
        ))
        layout.addWidget(self.db_table, 1)
        return page

    def refresh_databases(self) -> None:
        if not ((self.server_status.get("stack") or {}).get("mariadb") or {}).get("version"):
            self.db_table.setRowCount(0)
            return
        self.busy("Loading databases…", self.connection.db_list, self.show_databases)

    def show_databases(self, databases: list[dict]) -> None:
        self.databases = databases
        fill_table(self.db_table, [
            [db["name"], db.get("db_user") or "", db.get("site") or "", size_label(db.get("size")),
             when_label(db.get("created_at"))]
            for db in databases
        ], [db["name"] for db in databases])

    def _after_database_change(self, _=None) -> None:
        self.refresh_databases()
        if self.detail.site is not None:
            self.detail.load(self.detail.name)

    def _show_credentials(self, title: str, credentials: dict) -> None:
        self._after_database_change()
        dialogs.CredentialsDialog(
            title, "Save the password now — it isn't stored, so it can't be shown again.",
            [("Database", credentials.get("name", "")), ("User", credentials.get("user", "")),
             ("Password", credentials.get("password", "")), ("Host", credentials.get("host", ""))],
            self,
        ).exec()

    def create_database(self, site: str | None) -> None:
        dialog = dialogs.DatabaseDialog([s["name"] for s in self.sites], site, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        self.busy(f"Creating database {values['name']}…", lambda: self.connection.db_create(**values),
                  lambda creds: self._show_credentials("Database Created", creds), "Database created")

    def reset_database_password(self, name: str | None) -> None:
        if name is None:
            self.flash("Select a database first")
            return
        if _confirm(self, "Reset Password", f"Set a new random password for {name}'s user? "
                                            "Apps using the old one stop connecting until updated."):
            self.busy("Resetting the password…", lambda: self.connection.db_password(name),
                      lambda creds: self._show_credentials("New Database Password", creds))

    def delete_database(self, name: str | None) -> None:
        if name is None:
            self.flash("Select a database first")
            return
        if _confirm(self, "Delete Database", f"Delete the database {name} and its user? This can't be undone."):
            self.busy(f"Deleting {name}…", lambda: self.connection.db_delete(name), self._after_database_change,
                      "Database deleted")

    # -- Malware scanning --------------------------------------------------------

    def _build_malware_tab(self) -> QWidget:
        page = QWidget()
        self.malware_info = QLabel()
        self.malware_info.setWordWrap(True)
        self.malware_enabled = QCheckBox("Scan all sites on a schedule")
        self.malware_schedule = QLineEdit()
        self.malware_schedule.setPlaceholderText("@daily, or cron syntax")
        self.malware_action = QComboBox()
        for action in hm.MALWARE_ACTIONS:
            self.malware_action.addItem(hm.MALWARE_ACTION_LABELS[action], action)
        settings = QFormLayout()
        settings.addRow("", self.malware_enabled)
        settings.addRow("Schedule:", self.malware_schedule)
        settings.addRow("When malware is found:", self.malware_action)
        settings_box = QGroupBox("Settings")
        settings_layout = QVBoxLayout(settings_box)
        settings_layout.addLayout(settings)
        settings_layout.addLayout(_row(_button("Save", self._save_malware_settings)))

        self.scans_table = make_table(["Started", "Finished", "State", "Sites", "Files", "Infected"])
        self.findings_table = make_table(["Site", "File", "Signature", "Status", "Last seen"])
        self.findings_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.findings_table.customContextMenuRequested.connect(self._findings_menu)
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(_group("Findings (right-click for actions)", self.findings_table))
        splitter.addWidget(_group("Recent scans", self.scans_table))
        layout = QVBoxLayout(page)
        layout.addWidget(self.malware_info)
        layout.addLayout(_row(_button("Scan Now", self._scan_now), _button("Refresh", self.refresh_malware)))
        layout.addWidget(settings_box)
        layout.addWidget(splitter, 1)
        return page

    def refresh_malware(self) -> None:
        self.busy("Loading malware scan status…", self.connection.malware_status, self.show_malware)

    def show_malware(self, status: dict) -> None:
        self.malware = status
        if not status.get("installed"):
            info = "ClamAV isn't installed. Install it on the Server tab to scan sites for malware."
        else:
            signatures = status.get("signatures")
            info = (f"ClamAV {status.get('version') or ''} — signatures "
                    + (f"{signatures['version']} ({signatures['date']})" if signatures else "not downloaded yet")
                    + ("" if status.get("updater_active") else " — the signature updater isn't running"))
            if status.get("running"):
                info += "\nA scan is running."
            elif status.get("enabled") and status.get("next_run"):
                info += f"\nNext scan: {when_label(status['next_run'])}"
        self.malware_info.setText(info)
        self.malware_enabled.setChecked(bool(status.get("enabled")))
        self.malware_schedule.setText(status.get("schedule") or "")
        self.malware_action.setCurrentIndex(max(0, self.malware_action.findData(status.get("action"))))
        fill_table(self.scans_table, [
            [when_label(scan.get("started_at")), when_label(scan.get("finished_at")),
             scan.get("failure") or scan.get("state"), scan.get("sites"), scan.get("files_scanned"),
             scan.get("infected")]
            for scan in status.get("scans") or []
        ])
        findings = status.get("findings") or []
        fill_table(self.findings_table, [
            [f["site"], f["path"], f["signature"],
             f["status"] + (f" ({f['action_error']})" if f.get("action_error") else ""), when_label(f.get("last_seen"))]
            for f in findings
        ], findings)

    def _save_malware_settings(self) -> None:
        settings = {
            "enabled": self.malware_enabled.isChecked(),
            "schedule": self.malware_schedule.text().strip() or "@daily",
            "action": self.malware_action.currentData(),
        }
        self.busy("Saving malware scan settings…", lambda: self.connection.malware_settings(settings),
                  self.show_malware, "Saved")

    def _scan_now(self) -> None:
        self.busy("Starting a malware scan…", self.connection.malware_scan, self.show_malware, "Scan started")

    def _findings_menu(self, pos) -> None:
        finding = selected_data(self.findings_table)
        if finding is None:
            return
        actions = {
            "found": [("quarantine", "Move to Quarantine"), ("delete", "Delete File"), ("ignore", "Ignore (False Positive)")],
            "quarantined": [("restore", "Restore (False Positive)"), ("delete", "Delete File")],
            "ignored": [("unignore", "Stop Ignoring")],
        }.get(finding["status"], [])
        if not actions:
            return
        menu = QMenu(self)
        for action, label in actions:
            menu.addAction(label).triggered.connect(lambda _=False, a=action: self._finding_action(finding, a))
        menu.exec(self.findings_table.viewport().mapToGlobal(pos))

    def _finding_action(self, finding: dict, action: str) -> None:
        if action == "delete" and not _confirm(self, "Delete File", f"Delete {finding['path']}? This can't be undone."):
            return
        self.busy("Updating the finding…", lambda: self.connection.malware_finding(finding["id"], action),
                  self.show_malware, "Done")

    # -- Server -----------------------------------------------------------------

    def _build_server_tab(self) -> QWidget:
        page = QWidget()
        self.system_info = QLabel()
        self.system_info.setWordWrap(True)
        self.stack_table = make_table(["Component", "Version", "Running"])
        self.acme_email = QLineEdit()
        self.acme_email.setPlaceholderText("you@example.com")
        self.dns_labels: dict[str, QLabel] = {}
        dns_rows = []
        for provider in hm.DNS_PROVIDERS:
            label = QLabel()
            self.dns_labels[provider] = label
            dns_rows.append(_row(
                QLabel(hm.DNS_PROVIDER_LABELS[provider] + ":"), label,
                _button("Set Credentials…", lambda p=provider: self._set_dns_provider(p)),
                _button("Remove", lambda p=provider: self._clear_dns_provider(p)),
            ))
        layout = QVBoxLayout(page)
        layout.addWidget(self.system_info)
        layout.addWidget(self.stack_table, 1)
        layout.addLayout(_row(_button("Install Components…", self._install_stack),
                              _button("Refresh", self.refresh_status)))
        layout.addWidget(_group("Let's Encrypt", _row(QLabel("Account email:"), self.acme_email,
                                                      _button("Save", self._save_acme_email), stretch=False)))
        layout.addWidget(_group("DNS providers (for DNS challenges)", *dns_rows))
        return page

    def refresh_status(self) -> None:
        self.busy("Reading cockpit-hosting status…", self.connection.status, self.show_status)

    def show_status(self, status: dict) -> None:
        self.server_status = status
        distro = status.get("distro") or {}
        security = status.get("security") or {}
        firewall = status.get("firewall") or {}
        lines = [distro.get("name") or f"{distro.get('id', '')} {distro.get('version', '')}".strip()]
        if not status.get("supported", True):
            lines.append("This distribution isn't supported by cockpit-hosting.")
        if security.get("kind") and security["kind"] != "none":
            lines.append(f"{'SELinux' if security['kind'] == 'selinux' else 'AppArmor'}: {security.get('mode')}")
        if firewall.get("kind") and firewall["kind"] != "none":
            lines.append(f"Firewall: {firewall['kind']} ({'active' if firewall.get('active') else 'inactive'})")
        if status.get("usr_readonly"):
            lines.append("Packages come from the system image, so components can't be installed here.")
        self.system_info.setText("\n".join(lines))

        stack = status.get("stack") or {}

        def running(tool: dict) -> str:
            if "active" not in tool or not tool.get("version"):
                return ""
            return "Yes" if tool.get("active") else "No"

        rows = []
        for key, label in (("nginx", "nginx"), ("mariadb", "MariaDB"), ("certbot", "Certbot"),
                           ("node", "Node.js"), ("python", "Python"), ("podman", "Podman"),
                           ("clamav", "ClamAV")):
            tool = stack.get(key) or {}
            version = tool.get("version") or "Not installed"
            if key == "python" and tool.get("version") and not tool.get("venv"):
                version += " (no venv module)"
            if key == "podman" and tool.get("version") and not tool.get("quadlet"):
                version += " (too old for container sites)"
            rows.append([label, version, running(tool)])
        for php in stack.get("php") or []:
            version = php["version"] + ("" if php.get("cli_installed") else " (no command-line PHP)")
            rows.append([f"PHP {php['version']}", version, "Yes" if php.get("active") else "No"])
        fill_table(self.stack_table, rows)

        settings = status.get("settings") or {}
        self.acme_email.setText(settings.get("acme_email") or "")
        for provider, label in self.dns_labels.items():
            label.setText("Configured" if (settings.get("dns_providers") or {}).get(provider) else "Not set")

    def _install_stack(self) -> None:
        dialog = dialogs.StackDialog(self.server_status, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        components, php = dialog.selection()

        def done(_):
            self.refresh_status()
            self.refresh_malware()

        self.busy("Installing server components (this can take several minutes)…",
                  lambda: self.connection.stack_install(components, php), done, "Components installed")

    def _save_acme_email(self) -> None:
        email = self.acme_email.text().strip()
        self.busy("Saving…", lambda: self.connection.settings_set(email), lambda _: self.refresh_status(), "Saved")

    def _set_dns_provider(self, provider: str) -> None:
        dialog = dialogs.DnsProviderDialog(provider, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        credentials = dialog.credentials()
        self.busy(f"Testing the {hm.DNS_PROVIDER_LABELS[provider]} credentials…",
                  lambda: self.connection.dns_provider_set(provider, credentials),
                  lambda _: self.refresh_status(), "Credentials saved")

    def _clear_dns_provider(self, provider: str) -> None:
        if _confirm(self, "Remove Credentials", f"Remove the saved {hm.DNS_PROVIDER_LABELS[provider]} credentials?"):
            self.busy("Removing the credentials…", lambda: self.connection.dns_provider_set(provider, None),
                      lambda _: self.refresh_status())
