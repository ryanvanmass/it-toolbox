"""One Hosting Manager tab (Cockpit module): manages a web server set up by
the user's cockpit-hosting Cockpit module over SSH, with the same features
as that module's page -- sites (static, PHP, reverse proxy, Node.js,
Python, container), SSL, the nginx vhost editor, databases, cron jobs,
SFTP, logs, traffic, disabling a site and moving its files, WordPress and
Nextcloud (with Nextcloud updates, Nextcloud Office, draw.io and Team
folders), package repository, Forgejo and Zabbix sites, importing sites
from CloudPanel, backups, malware scanning and its alerts, fail2ban
intrusion protection, and installing the server stack.
See core/hosting_manager.py for how it talks to the server.
"""

from __future__ import annotations

import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStackedLayout,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from it_toolbox.core import async_utils
from it_toolbox.core import hosting_manager as hm
from it_toolbox.ui import theme
from it_toolbox.widgets import hosting_dialogs as dialogs
from it_toolbox.widgets import status_bar
from it_toolbox.widgets.hosting_apps import ForgejoCard, RepoCard, ZabbixCard
from it_toolbox.widgets.hosting_backups import BackupsTab, SiteBackupsPanel
from it_toolbox.widgets.hosting_import import CloudPanelImportDialog
from it_toolbox.widgets.hosting_traffic import TrafficPanel
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


# How often a running move of a site's files is checked on.
STORAGE_POLL_MS = 2000


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
        self.vhost: dict | None = None

        self.heading = QLabel()
        theme.set_role(self.heading, "heading")
        self.subheading = QLabel()
        theme.set_role(self.subheading, "subheading")
        self.disable_button = _button("Disable Site…", self._toggle_disabled)
        self.disabled_note = QLabel(
            "This site is disabled. Visitors get a page saying the site is disabled, and its PHP pool, app or "
            "container, cron jobs and Nextcloud Office are stopped. Its files, databases, SFTP login and backups "
            "are kept.")
        self.disabled_note.setWordWrap(True)
        theme.set_tone(self.disabled_note, "warning")
        self.storage_note = QLabel()
        self.storage_note.setWordWrap(True)
        self.storage_dismiss = _button("Dismiss", self._dismiss_storage)
        self.storage_row = QWidget()
        storage_layout = QHBoxLayout(self.storage_row)
        storage_layout.setContentsMargins(0, 0, 0, 0)
        storage_layout.addWidget(self.storage_note, 1)
        storage_layout.addWidget(self.storage_dismiss)
        self.storage_row.hide()
        self.storage_job: dict | None = None
        self._storage_poll = QTimer(self)
        self._storage_poll.setSingleShot(True)
        self._storage_poll.setInterval(STORAGE_POLL_MS)
        self._storage_poll.timeout.connect(self._poll_storage)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_settings_tab(), "Settings")
        self.tabs.addTab(self._build_https_tab(), "SSL")
        self.tabs.addTab(self._build_nginx_tab(), "Vhost")
        self.databases_index = self.tabs.addTab(self._build_databases_tab(), "Databases")
        self.sftp_index = self.tabs.addTab(self._build_sftp_tab(), "SFTP")
        self.cron_index = self.tabs.addTab(self._build_cron_tab(), "Cron Jobs")
        self.backups = SiteBackupsPanel(self)
        self.backups_index = self.tabs.addTab(self.backups, "Backups")
        self.traffic = TrafficPanel(self)
        self.traffic_index = self.tabs.addTab(self.traffic, "Traffic")
        self.logs_index = self.tabs.addTab(self._build_logs_tab(), "Logs")
        self.tabs.currentChanged.connect(self._on_tab_changed)

        titles = QVBoxLayout()
        titles.setSpacing(0)
        titles.addWidget(self.heading)
        titles.addWidget(self.subheading)
        header = QHBoxLayout()
        header.addLayout(titles, 1)
        header.addWidget(self.disable_button, 0, Qt.AlignmentFlag.AlignTop)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(8, 0, 0, 0)
        layout.addLayout(header)
        layout.addWidget(self.disabled_note)
        layout.addWidget(self.storage_row)
        layout.addWidget(self.tabs, 1)

        # Shown until a site is picked, instead of every site type's
        # (empty, disabled) settings at once.
        self.placeholder = QLabel("Select a site on the left to see and change its settings.")
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder.setWordWrap(True)
        theme.set_tone(self.placeholder, "muted")
        self.pages = QStackedLayout(self)
        self.pages.addWidget(self.placeholder)
        self.pages.addWidget(content)
        self.content = content

    @property
    def connection(self) -> hm.HostingConnection:
        return self.manager.connection

    @property
    def name(self) -> str:
        return self.site["name"] if self.site else ""

    def busy(self, *args, **kwargs) -> None:
        self.manager.busy(*args, **kwargs)

    def clear(self) -> None:
        self.stop()
        self.site = None
        self.heading.setText("Select a site")
        self.subheading.clear()
        self.disabled_note.hide()
        self.storage_row.hide()
        self.pages.setCurrentWidget(self.placeholder)

    def stop(self) -> None:
        """Stops every poll (on clear and before a reconnect)."""
        self._storage_poll.stop()
        self.backups.clear()
        for card in (self.forgejo_card, self.zabbix_card):
            card.stop()

    def load(self, name: str) -> None:
        self.busy(f"Loading {name}…", lambda: self.connection.site_get(name), self.show_site)

    def show_site(self, site: dict) -> None:
        """Shows a fresh site-get reply, and passes it on to the list."""
        previous = self.name
        self.site = site
        self.pages.setCurrentWidget(self.content)
        disabled = bool(site.get("disabled"))
        self.heading.setText(site.get("primary_domain") or site["name"])
        subtitle = [hm.SITE_TYPE_LABELS.get(site["type"], site["type"])]
        if (site.get("application") or {}).get("name"):
            subtitle.append(hm.APPLICATION_LABELS.get(site["application"]["name"], site["application"]["name"]))
        if disabled:
            subtitle.append("disabled")
        self.subheading.setText("  ·  ".join(subtitle))
        self.disable_button.setText("Enable Site" if disabled else "Disable Site…")
        self._show_settings(site)
        self._show_https(site)
        self._show_databases(site)
        self._show_nginx(site)
        self.manager.update_site_row(site)
        if previous != site["name"]:
            self.cron_table.setRowCount(0)
            self.log_view.clear()
            self.sftp_loaded = False
            self.backups.clear()
            self.traffic.clear()
            self.storage_job = None
            self.storage_row.hide()
            self._poll_storage()
        self._show_disabled_note()
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
        elif index == self.backups_index and self.backups.loaded_for != self.name:
            self.backups.load()
        elif index == self.traffic_index and self.traffic.loaded_for != self.name:
            self.traffic.refresh()

    # -- Disabling, and moving the files ---------------------------------------

    def _show_disabled_note(self) -> None:
        moving = bool(self.storage_job) and self.storage_job.get("state") == "running"
        self.disabled_note.setVisible(bool(self.site and self.site.get("disabled")) and not moving)

    def _toggle_disabled(self) -> None:
        name = self.name
        if self.site.get("disabled"):
            self.busy(f"Enabling {name}…", lambda: self.connection.site_enable(name), self.show_site, "Site enabled")
            return
        if not _confirm(self, f"Disable {self.site.get('primary_domain') or name}",
                        "Visitors get a page saying the site is disabled, and its PHP pool, app or container, cron "
                        "jobs and Nextcloud Office are stopped. Its files, databases, certificate, SFTP login and "
                        "backups are kept, and enabling it brings it back as it was.\n\nDisable it?"):
            return
        self.busy(f"Disabling {name}…", lambda: self.connection.site_disable(name), self.show_site, "Site disabled")

    def _poll_storage(self) -> None:
        name = self.name
        if not name:
            return

        def show(status: dict) -> None:
            try:
                if name == self.name:
                    self.show_storage(status)
            except RuntimeError:
                pass

        async_utils.run_in_background(lambda: self.connection.storage_status(name), on_result=show,
                                      on_error=lambda _error: None)

    def show_storage(self, status: dict) -> None:
        """How a move of the site's files is going, or how it ended."""
        job = status.get("job")
        was_running = bool(self.storage_job) and self.storage_job.get("state") == "running"
        self.storage_job = job
        running = bool(job) and job.get("state") == "running"
        self.move_button.setEnabled(not running)
        if not job:
            self.storage_row.hide()
        elif running:
            step = job.get("step") or "Starting"
            progress = f" ({job['progress']}%)" if job.get("progress") is not None else ""
            self.storage_note.setText(f"Moving the files to {job.get('to')}: {step}{progress}")
            theme.set_tone(self.storage_note, None)
        elif job.get("state") == "failed":
            self.storage_note.setText(f"The files could not be moved: {job.get('failure')}")
            theme.set_tone(self.storage_note, "danger")
        else:
            result = job.get("result") or {}
            lines = [f"The files were moved to {job.get('to')}.", *(result.get("problems") or [])]
            if result.get("old_copy"):
                lines.append(f"The old copy is still in {result['old_copy']}.")
            self.storage_note.setText("\n".join(lines))
            theme.set_tone(self.storage_note, "warning" if result.get("problems") else None)
        if job:
            self.storage_row.show()
            self.storage_dismiss.setVisible(not running)
        self._show_disabled_note()
        if running:
            self._storage_poll.start()
        elif was_running:
            # The move ended: the site shows its new location (and is enabled again).
            self.load(self.name)

    def _move_files(self) -> None:
        site = self.site
        name = site["name"]

        def ask(status: dict) -> None:
            dialog = dialogs.MoveStorageDialog(site, status.get("used"), self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            target, keep_old = dialog.target(), dialog.keep_old.isChecked()
            self.busy(f"Starting to move {name}'s files…",
                      lambda: self.connection.storage_move(name, target, keep_old), self.show_storage, "Move started")

        self.busy(f"Measuring {name}'s files…", lambda: self.connection.storage_status(name, usage=True), ask)

    def _dismiss_storage(self) -> None:
        name = self.name
        self.busy("Dismissing…", lambda: self.connection.storage_clear(name), self.show_storage)

    def _update(self, message: str, changes: dict, done: str = "Saved") -> None:
        name = self.name
        self.busy(message, lambda: self.connection.site_update(name, changes), self.show_site, done)

    # -- Settings -------------------------------------------------------------

    def _build_settings_tab(self) -> QWidget:
        page = QWidget()
        # Key/value grid of the site's paths and facts, filled by _show_settings.
        self.overview = QGridLayout()
        self.overview.setHorizontalSpacing(16)
        self.overview.setVerticalSpacing(4)
        self.overview.setColumnStretch(1, 1)

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
        theme.set_primary(save)

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
        self.update_app_button = _button("Update Nextcloud…", self._update_application)
        self.office_label = QLabel()
        self.office_setup = _button("Set Up", lambda: self._set_office(True))
        self.office_remove = _button("Remove", lambda: self._set_office(False))
        self.drawio_label = QLabel()
        self.drawio_setup = _button("Set Up", lambda: self._set_drawio(True))
        self.drawio_remove = _button("Remove", lambda: self._set_drawio(False))
        self.team_folders_label = QLabel()
        self.team_folders_setup = _button("Set Up", lambda: self._set_team_folders(True))
        self.team_folders_remove = _button("Remove", lambda: self._set_team_folders(False))
        self.nextcloud_extras = QWidget()
        extras = QVBoxLayout(self.nextcloud_extras)
        extras.setContentsMargins(0, 0, 0, 0)
        extras.addLayout(_row(self.office_label, self.office_setup, self.office_remove))
        extras.addLayout(_row(self.drawio_label, self.drawio_setup, self.drawio_remove))
        extras.addLayout(_row(self.team_folders_label, self.team_folders_setup, self.team_folders_remove))
        self.application_box = _group(
            "Application", _row(self.application_label, self.update_app_button, self.deploy_button),
            self.nextcloud_extras,
        )

        self.repo_card = RepoCard(self)
        self.forgejo_card = ForgejoCard(self)
        self.zabbix_card = ZabbixCard(self)

        delete = _button("Delete Site…", lambda: self.manager.delete_site(self.site))
        theme.set_tone(delete, "danger")
        self.move_button = _button("Move Files…", self._move_files)

        overview_box = _group("Overview", self.overview, _row(self.move_button))
        settings_box = _group("Site Settings", self.settings_form, _row(save))
        delete_note = QLabel("Removes the site's files, databases, SFTP login, certificates and vhost.")
        delete_note.setWordWrap(True)
        theme.set_tone(delete_note, "muted")
        danger_row = QHBoxLayout()
        danger_row.addWidget(delete_note, 1)
        danger_row.addWidget(delete)
        danger_box = _group("Danger Zone", danger_row)

        inner = QVBoxLayout(page)
        inner.setSpacing(12)
        inner.addWidget(overview_box)
        inner.addWidget(self.app_box)
        inner.addWidget(self.forgejo_card)
        inner.addWidget(self.zabbix_card)
        inner.addWidget(self.application_box)
        inner.addWidget(self.repo_card)
        inner.addWidget(settings_box)
        inner.addWidget(danger_box)
        inner.addStretch(1)
        # The page grows with the app cards (Forgejo's runner table,
        # Nextcloud's extras...), so it scrolls rather than squeezing them.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        return scroll

    def _show_settings(self, site: dict) -> None:
        site_type = site["type"]
        rows = [
            ("Site user", site["system_user"]),
            ("Home", site["home"]),
            ("Files", site["root_dir"]),
            ("Logs", site["logs_dir"]),
        ]
        if (site.get("application") or {}).get("name") == "nextcloud":
            rows.append(("Nextcloud data", f"{site.get('data_dir')}/nextcloud"))
        if site.get("storage"):
            rows.append(("Stored in", site.get("storage_dir")))
        if site.get("runtime_version"):
            rows.append(("Runtime", site["runtime_version"]))
        if site.get("app_port"):
            rows.append(("App port", f"127.0.0.1:{site['app_port']}"))
        info = site.get("container_info")
        if info:
            rows.append(("Image ID", f"{info.get('image_id', '')[:12]}  created {when_label(info.get('created'))}  "
                                     f"{size_label(info.get('size'))}"))
        rows.append(("Created", when_label(site.get("created_at"))))
        self._fill_overview(rows)

        self.domains.setPlainText("\n".join(site.get("domains") or []))
        self.domains.setToolTip("One per line; the first is the primary domain." + (
            " The self-signed certificate is made again for the new domains."
            if site.get("ssl_mode") == "self-signed" else ""))
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
        app = site.get("application") or {}
        # Zabbix's containers are the helper's to set up, as on the Cockpit page.
        is_container = site_type == "container" and app.get("name") != "zabbix"
        self.image.setText(container.get("image", ""))
        self.container_port.setValue(int(container.get("port") or 80))
        self.volumes.setText(", ".join(container.get("volumes") or []))
        self.auto_update.setChecked(bool(container.get("auto_update")))
        for widget in (self.image, self.container_port, self.volumes, self.auto_update):
            self.settings_form.setRowVisible(widget, is_container)

        runs_app = site_type in hm.APP_SITE_TYPES and app.get("name") != "zabbix"
        self.app_command.setText((container.get("command") if is_container else site.get("app_command")) or "")
        self.app_env.setPlainText(dialogs.format_env(site.get("app_env")))
        self.settings_form.setRowVisible(self.app_command, runs_app)
        self.settings_form.setRowVisible(self.app_env, runs_app)

        self.app_box.setVisible(site_type in hm.APP_SITE_TYPES)
        state = site.get("app_state") or "unknown"
        self.app_state.setText(f"State: {state}")
        theme.set_tone(self.app_state, {"active": "success", "failed": "danger"}.get(state))
        self.app_buttons["pull"].setVisible(is_container)

        for card, application in ((self.repo_card, "repo"), (self.forgejo_card, "forgejo"),
                                  (self.zabbix_card, "zabbix")):
            shown = app.get("name") == application
            card.setVisible(shown)
            if shown:
                card.show_site(site)
            elif hasattr(card, "stop"):
                card.stop()

        self.application_box.setVisible(php)
        if app:
            self.application_label.setText(
                f"{hm.APPLICATION_LABELS.get(app['name'], app['name'])} {app.get('version') or ''} — "
                f"admin user {app.get('admin_user')}, admin page {app.get('admin_path')}"
            )
        else:
            self.application_label.setText("No application deployed.")
        self.deploy_button.setVisible(not app)
        nextcloud = bool(app) and app["name"] == "nextcloud"
        self.update_app_button.setVisible(nextcloud)
        self.nextcloud_extras.setVisible(nextcloud)
        if nextcloud:
            office = app.get("office")
            running = bool(office) and office.get("state") == "active"
            self.office_label.setText("Nextcloud Office: " + (
                ("running" if running else office.get("state") or "not running") if office else "not set up"))
            self.office_setup.setText("Repair" if office else "Set Up")
            self.office_setup.setVisible(not running)
            self.office_remove.setVisible(bool(office))
            drawio = bool(app.get("drawio"))
            self.drawio_label.setText("draw.io: " + ("set up" if drawio else "not set up"))
            self.drawio_setup.setText("Repair" if drawio else "Set Up")
            self.drawio_remove.setVisible(drawio)
            team_folders = bool(app.get("team_folders"))
            self.team_folders_label.setText("Team folders: " + ("set up" if team_folders else "not set up"))
            self.team_folders_setup.setText("Repair" if team_folders else "Set Up")
            self.team_folders_remove.setVisible(team_folders)

    def _fill_overview(self, rows: list[tuple[str, str]]) -> None:
        while self.overview.count():
            item = self.overview.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        for row, (key, value) in enumerate(rows):
            key_label = QLabel(key)
            theme.set_role(key_label, "key")
            value_label = QLabel(str(value))
            value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            value_label.setWordWrap(True)
            self.overview.addWidget(key_label, row, 0, Qt.AlignmentFlag.AlignTop)
            self.overview.addWidget(value_label, row, 1)

    def overview_text(self) -> str:
        """The overview grid as "Key: value" lines (for tests and copying)."""
        lines = []
        for row in range(self.overview.rowCount()):
            key, value = self.overview.itemAtPosition(row, 0), self.overview.itemAtPosition(row, 1)
            if key and value:
                lines.append(f"{key.widget().text()}: {value.widget().text()}")
        return "\n".join(lines)

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
        if self.settings_form.isRowVisible(self.app_env):
            try:
                env = dialogs.parse_env(self.app_env.toPlainText())
            except ValueError as exc:
                QMessageBox.warning(self, TITLE, f"Environment: {exc}")
                return
            if env != (site.get("app_env") or {}):
                changes["app_env"] = env
        if self.settings_form.isRowVisible(self.image):
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
        elif self.settings_form.isRowVisible(self.app_command) and \
                self.app_command.text().strip() != (site.get("app_command") or ""):
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
            self._extras_failed(result, "set up", "Try again with Set Up in the site's Application box.")
            dialogs.CredentialsDialog(
                f"{label} Deployed",
                f"{label} is installed. Save the admin password now — it isn't shown again.",
                [("Admin page", result.get("admin_url", "")), ("Admin user", result.get("admin_user", "")),
                 ("Admin password", result.get("admin_password", ""))],
                self,
            ).exec()

        self.busy(f"Deploying {label} to {name}…", lambda: self.connection.app_deploy(name, deploy_input), done,
                  f"{label} deployed")

    def _extras_failed(self, result: dict, verb: str, hint: str) -> None:
        """Nextcloud itself worked, but Nextcloud Office, draw.io or Team folders didn't."""
        for key, label in (("office_error", "Nextcloud Office"), ("drawio_error", "draw.io"),
                           ("team_folders_error", "Team folders")):
            if result.get(key):
                QMessageBox.warning(self, TITLE, f"Nextcloud works, but {label} could not be {verb}. "
                                                 f"{hint}\n\n{result[key]}")

    def _update_application(self) -> None:
        app = self.site.get("application") or {}
        extras = []
        if app.get("office"):
            extras.append("Nextcloud Office (its app and Collabora Online's newest image)")
        if app.get("drawio"):
            extras.append("the draw.io app")
        if app.get("team_folders"):
            extras.append("the Team folders app")
        text = ("Nextcloud's own updater backs up the current code, downloads the newest release and upgrades "
                "the database, one major version at a time until it is current. The site is in maintenance "
                "mode while it runs. Your files and database are not backed up by this; take a backup first "
                "for a major update.")
        if extras:
            text += f"\n\n{' and '.join(extras).capitalize()} will be updated too."
        if not _confirm(self, "Update Nextcloud", text + "\n\nUpdate now?"):
            return
        name = self.name

        def done(result: dict) -> None:
            self.show_site(result["site"])
            if result.get("version") == result.get("previous_version"):
                message = f"Nextcloud {result.get('version')} is already the newest release."
            else:
                message = f"Nextcloud was updated from {result.get('previous_version')} to {result.get('version')}."
            QMessageBox.information(self, "Update Nextcloud", message)
            self._extras_failed(result, "updated", "")

        self.busy(f"Updating Nextcloud on {name} (this can take several minutes)…",
                  lambda: self.connection.app_update(name), done, "Nextcloud updated")

    def _set_office(self, enabled: bool) -> None:
        name = self.name
        if enabled:
            if not _confirm(self, "Set Up Nextcloud Office",
                            "Nextcloud Office edits documents, spreadsheets and presentations in the browser. "
                            "Collabora Online runs for it in a container of the site's user (Podman is needed, "
                            "and about 1 GB of memory).\n\nSet it up now?"):
                return
            message = f"Downloading and starting Collabora Online for {name}…"
        else:
            if not _confirm(self, "Remove Nextcloud Office",
                            "Its container is stopped and removed, and the Nextcloud Office app turned off. "
                            "Documents stay in Nextcloud.\n\nRemove it?"):
                return
            message = f"Removing Nextcloud Office from {name}…"
        self.busy(message, lambda: self.connection.app_office(name, enabled), self.show_site, "Done")

    def _set_drawio(self, enabled: bool) -> None:
        name = self.name
        if enabled:
            text = ("draw.io creates and edits diagrams (.drawio files) in Nextcloud. Its editor is loaded from "
                    "embed.diagrams.net; diagrams stay in Nextcloud.\n\nSet it up now?")
        else:
            text = "The draw.io app is turned off. Diagrams stay in Nextcloud as files.\n\nRemove it?"
        if not _confirm(self, "Set Up draw.io" if enabled else "Remove draw.io", text):
            return
        self.busy(f"{'Setting up' if enabled else 'Removing'} draw.io on {name}…",
                  lambda: self.connection.app_drawio(name, enabled), self.show_site, "Done")

    def _set_team_folders(self, enabled: bool) -> None:
        name = self.name
        if enabled:
            text = ("Team folders are folders shared by groups of users, with their own quotas and permissions. An "
                    "admin creates them under Administration settings, Team folders, in Nextcloud.\n\nSet it up now?")
        else:
            text = ("The Team folders app is turned off, and its folders are hidden. They and their files are kept, "
                    "and come back when it is set up again.\n\nRemove it?")
        if not _confirm(self, "Set Up Team Folders" if enabled else "Remove Team Folders", text):
            return
        self.busy(f"{'Setting up' if enabled else 'Removing'} Team folders on {name}…",
                  lambda: self.connection.app_team_folders(name, enabled), self.show_site, "Done")

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
        self.self_signed = _button("Use Self-Signed Certificate…", self._self_signed_certificate)
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
        layout.addLayout(_row(custom, self.self_signed, self.remove_cert))
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
        self.self_signed.setText("Make New Self-Signed Certificate…" if mode == "self-signed"
                                 else "Use Self-Signed Certificate…")
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

    def _self_signed_certificate(self) -> None:
        choices = [f"{years} year" + ("" if years == 1 else "s") for years in hm.SELF_SIGNED_YEARS]
        choice, ok = QInputDialog.getItem(
            self, "Self-Signed Certificate",
            f"For {', '.join(self.site.get('domains') or [])}.\n\nBrowsers warn that it isn't trusted: use it for "
            "testing, internal sites, or behind a proxy such as Cloudflare in \"Full\" mode. It isn't renewed "
            "automatically.\n\nValid for:", choices, 0, False)
        if not ok:
            return
        days = min(hm.SELF_SIGNED_YEARS[choices.index(choice)] * 365, 3650)
        name = self.name
        self.busy(f"Making a self-signed certificate for {name}…",
                  lambda: self.connection.ssl_self_signed(name, days), self.show_site, "Certificate installed")

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
        dialog = dialogs.CronJobDialog(parent=self, checker=self.connection.schedule_check)
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
        dialog = dialogs.CronJobDialog(job, self, checker=self.connection.schedule_check)
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

    # -- nginx vhost ------------------------------------------------------------

    def _build_nginx_tab(self) -> QWidget:
        """The site's whole nginx vhost as a template (cockpit-hosting 7+), or
        on older servers the custom directives added to its server blocks."""
        page = QWidget()
        self.nginx_note = QLabel()
        self.nginx_note.setWordWrap(True)
        self.nginx_note.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.vhost_outdated = QLabel(
            "Recent changes to this site are not in your edited vhost: the module's own vhost changed (for "
            "example SSL, the HTTPS redirect or an application) in lines you edited, so it couldn't be merged "
            "in. Compare with the generated vhost and carry the change over, or reset to the generated one."
        )
        self.vhost_outdated.setWordWrap(True)
        theme.set_tone(self.vhost_outdated, "warning")
        self.vhost_generated_button = _button("Show Generated Vhost…", self._show_generated_vhost)
        self.vhost_outdated_row = QWidget()
        outdated_layout = QVBoxLayout(self.vhost_outdated_row)
        outdated_layout.setContentsMargins(0, 0, 0, 0)
        outdated_layout.addWidget(self.vhost_outdated)
        outdated_layout.addLayout(_row(self.vhost_generated_button))
        self.custom_nginx = QPlainTextEdit()
        self.custom_nginx.setFont(dialogs.monospace())
        self.custom_nginx.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.vhost_placeholders = _button("Placeholders…", self._show_vhost_placeholders)
        self.vhost_discard = _button("Discard Changes", self._discard_vhost)
        self.vhost_reset = _button("Reset to Generated…", self._reset_vhost)
        layout = QVBoxLayout(page)
        layout.addWidget(self.nginx_note)
        layout.addWidget(self.vhost_outdated_row)
        layout.addWidget(self.custom_nginx, 1)
        layout.addLayout(_row(_button("Save", self._save_nginx), self.vhost_discard, self.vhost_reset,
                              self.vhost_placeholders))
        return page

    def _show_nginx(self, site: dict) -> None:
        vhost = site.get("vhost")
        self.vhost = vhost
        editor = vhost is not None
        if editor:
            self.nginx_note.setText(
                f"Written to {vhost.get('path')}" + (" (edited)" if vhost.get("edited") else " (generated)")
                + ". Checked with nginx -t before it's applied: if nginx refuses it, nothing changes. Names in "
                "double braces are filled in from the site's settings, so domain, PHP and certificate changes "
                "still reach an edited vhost."
            )
            self.custom_nginx.setPlainText(vhost.get("template") or "")
            self.custom_nginx.setPlaceholderText("")
        else:
            self.nginx_note.setText(
                "Extra nginx directives for this site's server block. They're checked with nginx -t before "
                "being applied, and rolled back if nginx rejects them. (Update cockpit-hosting on the server "
                "to edit the whole vhost.)"
            )
            self.custom_nginx.setPlainText(site.get("custom_nginx") or "")
            self.custom_nginx.setPlaceholderText("location /downloads/ {\n    autoindex on;\n}")
        self.vhost_outdated_row.setVisible(editor and bool(vhost.get("outdated")))
        self.vhost_placeholders.setVisible(editor)
        self.vhost_discard.setVisible(editor)
        self.vhost_reset.setVisible(editor and bool(vhost.get("edited")))

    def _after_vhost_change(self, vhost: dict) -> None:
        # Reload the whole site: the reply only carries the vhost.
        self.load(self.name)

    def _save_nginx(self) -> None:
        name, text = self.name, self.custom_nginx.toPlainText()
        if self.vhost is None:
            self.busy("Saving the nginx directives…", lambda: self.connection.site_custom_nginx(name, text),
                      self.custom_nginx.setPlainText, "nginx reloaded")
            return
        if text == self.vhost.get("template"):
            self.manager.flash("Nothing changed")
            return
        if not text.strip():
            QMessageBox.warning(self, TITLE, "The vhost can't be empty. Use Reset to Generated instead.")
            return
        self.busy("Saving the nginx vhost…", lambda: self.connection.site_vhost_set(name, text),
                  self._after_vhost_change, "Saved and applied")

    def _discard_vhost(self) -> None:
        if self.vhost is not None:
            self.custom_nginx.setPlainText(self.vhost.get("template") or "")

    def _reset_vhost(self) -> None:
        name = self.name
        if _confirm(self, "Reset Vhost", "Throw away your edits to this site's vhost? The module writes it from "
                                         "the site's settings again."):
            self.busy("Resetting the nginx vhost…", lambda: self.connection.site_vhost_set(name, reset=True),
                      self._after_vhost_change, "Vhost reset")

    def _show_generated_vhost(self) -> None:
        if self.vhost is not None:
            self.manager.show_text(f"Generated vhost for {self.name}", self.vhost.get("generated") or "")

    def _show_vhost_placeholders(self) -> None:
        if self.vhost is not None:
            values = self.vhost.get("values") or {}
            width = max((len(key) for key in values), default=0) + 4
            self.manager.show_text("What the names in double braces stand for", "\n".join(
                f"{'{{' + key + '}}':<{width}}  {value}" for key, value in values.items()))


# -- The manager tab ---------------------------------------------------------------


class HostingManagerWidget(RemoteHelperTab):
    """Connects on construction, then shows the management tabs, or a
    page explaining that cockpit-hosting isn't installed."""

    TOOL_NAME = TITLE
    SITE_COLUMNS = ("Domain", "Type", "Site user", "SSL", "App")

    def __init__(self, server: hm.HostingServer, connection_factory=hm.HostingConnection,
                 parent: QWidget | None = None, credentials: dict | None = None) -> None:
        super().__init__(server, connection_factory, parent, credentials)
        self.server_status: dict = {}
        self.sites: list[dict] = []
        self.databases: list[dict] = []
        self.malware: dict = {}
        self.fail2ban: dict = {}

        self.missing_page = QLabel(
            "This server doesn't have the cockpit-hosting module "
            f"({hm.HELPER_PATH}).\n\nInstall the cockpit-hosting package (from the Bonkcloud "
            "package registry, or the RPM/.deb on its release page), then click Reconnect."
        )
        self.missing_page.setWordWrap(True)
        self.missing_page.setAlignment(Qt.AlignmentFlag.AlignCenter)
        theme.set_tone(self.missing_page, "muted")
        self.stack.addWidget(self.missing_page)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_sites_tab(), "Sites")
        self.tabs.addTab(self._build_databases_tab(), "Databases")
        self.backups_tab = BackupsTab(self)
        self.tabs.addTab(self.backups_tab, "Backups")
        self.tabs.addTab(self._build_malware_tab(), "Malware Scanning")
        self.tabs.addTab(self._build_fail2ban_tab(), "Intrusion Protection")
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

    def before_reconnect(self) -> None:
        self.detail.stop()
        self.backups_tab.stop()

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
        self.refresh_fail2ban()
        self.backups_tab.refresh()
        self.check_import()
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
        # The list only needs to pick a site: Site user and App are on the
        # site's own page (still matched by the filter), and the SSL column
        # takes what's left, eliding with the full text as a tooltip,
        # rather than every column running off the pane's right edge.
        header = self.site_table.horizontalHeader()
        for column in ("Site user", "App"):
            self.site_table.setColumnHidden(self.SITE_COLUMNS.index(column), True)
        for column in ("Domain", "Type"):
            header.setSectionResizeMode(self.SITE_COLUMNS.index(column), QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self.SITE_COLUMNS.index("SSL"), QHeaderView.ResizeMode.Stretch)
        self.site_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.import_button = _button("Import from CloudPanel…", self.import_sites)
        self.import_note = QLabel("Importing sites from CloudPanel: open the import to see its progress.")
        self.import_note.setWordWrap(True)
        self.import_note.hide()
        left_layout.addLayout(_row(_button("Create Site…", self.create_site), self.import_button,
                                   _button("Refresh", self.refresh_sites), stretch=False))
        left_layout.addWidget(self.import_note)
        left_layout.addWidget(self.filter)
        left_layout.addWidget(self.site_table, 1)
        # Never narrower than the button row above the list.
        left.setMinimumWidth(left_layout.itemAt(0).sizeHint().width())
        self.detail = SiteDetail(self)
        self.detail.clear()
        splitter = QSplitter()
        splitter.addWidget(left)
        splitter.addWidget(self.detail)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([460, 840])
        layout = QVBoxLayout(page)
        layout.addWidget(splitter)
        return page

    def refresh_sites(self) -> None:
        self.busy("Loading sites…", self.connection.site_list, self.show_sites)

    def _site_row(self, site: dict) -> list:
        domain = (site.get("primary_domain") or site["name"]) + (" (disabled)" if site.get("disabled") else "")
        return [domain, hm.SITE_TYPE_LABELS.get(site["type"], site["type"]), site["name"], https_label(site),
                app_label(site)]

    def show_sites(self, sites: list[dict]) -> None:
        selected = self.detail.name
        self.sites = sites
        self.site_table.blockSignals(True)
        fill_table(self.site_table, [self._site_row(site) for site in sites], [site["name"] for site in sites])
        self._set_site_tooltips()
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
        self._set_site_tooltips()
        self.sites = [site if s["name"] == site["name"] else s for s in self.sites]

    def _set_site_tooltips(self) -> None:
        for row in range(self.site_table.rowCount()):
            for column in range(self.site_table.columnCount()):
                item = self.site_table.item(row, column)
                item.setToolTip(item.text())

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
            if site["name"] == self.detail.name:
                menu.addAction("Enable Site" if site.get("disabled") else "Disable Site…").triggered.connect(
                    self.detail._toggle_disabled)
            menu.addAction("Delete Site…").triggered.connect(lambda: self.delete_site(site))
            menu.addSeparator()
        menu.addAction("Create Site…").triggered.connect(self.create_site)
        menu.addAction("Import from CloudPanel…").triggered.connect(self.import_sites)
        menu.exec(self.site_table.viewport().mapToGlobal(pos))

    def open_site(self, name: str, tab: str = "") -> None:
        """Shows a site on the Sites tab, on one of its sub-tabs ("backups")."""
        self.tabs.setCurrentIndex(0)
        names = [s["name"] for s in self.sites]
        if name in names:
            self.site_table.selectRow(names.index(name))
        if tab == "backups":
            self.detail.tabs.setCurrentIndex(self.detail.backups_index)

    def create_site(self) -> None:
        dialog = dialogs.CreateSiteDialog(self.server_status, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        site_input, deploy_input = dialog.site_input(), dialog.deploy_input()

        def add(site: dict) -> None:
            self.sites = [s for s in self.sites if s["name"] != site["name"]] + [site]
            self.detail.site = None
            self.show_sites(sorted(self.sites, key=lambda s: s["name"]))
            names = [s["name"] for s in self.sites]
            self.site_table.selectRow(names.index(site["name"]))

        def deployed(result: dict) -> None:
            add(result["site"])
            self.refresh_databases()
            if deploy_input["application"] == "repo":
                return
            self.detail._extras_failed(result, "set up", "Try again with Set Up in the site's Application box.")
            label = hm.APPLICATION_LABELS[deploy_input["application"]]
            dialogs.CredentialsDialog(
                f"{label} Is Ready",
                "Save the password now — it isn't stored, so it can't be shown again.",
                [("Sign in at", result.get("admin_url", "")), ("User", result.get("admin_user", "")),
                 ("Password", result.get("admin_password", ""))],
                self,
            ).exec()

        def created(site: dict) -> None:
            add(site)
            if deploy_input is None:
                return
            # The site exists from here on, whatever the deployment does.
            label = hm.APPLICATION_LABELS[deploy_input["application"]]
            self.busy(f"Installing {label} into {site['name']}…",
                      lambda: self.connection.app_deploy(site["name"], deploy_input), deployed, f"{label} installed",
                      on_error=lambda _error: self.detail.load(site["name"]))

        self.busy(f"Creating {site_input['domain']}…", lambda: self.connection.site_create(site_input), created,
                  "Site created")

    def check_import(self) -> None:
        """Shows that a CloudPanel import is running (it goes on without the dialog)."""
        def show(status: dict) -> None:
            try:
                self.import_note.setVisible(bool(status.get("running")))
            except RuntimeError:
                pass

        async_utils.run_in_background(self.connection.import_status, on_result=show, on_error=lambda _error: None)

    def import_sites(self) -> None:
        if self.connection is None:
            return
        CloudPanelImportDialog(self.connection, self.refresh_sites, self).exec()
        self.refresh_sites()
        self.refresh_databases()
        self.check_import()

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
        self.malware_alerts = QLabel()
        self.malware_alerts.setWordWrap(True)
        settings.addRow("Alerts:", _row(self.malware_alerts, _button("Alerts…", self._edit_malware_alerts)))
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
        alerts = status.get("alerts") or {}
        targets = [label for key, label in (("pushover", "Pushover"), ("smtp", "Email"))
                   if (alerts.get(key) or {}).get("enabled")]
        text = ", ".join(targets) or "Off"
        failure = status.get("alert_failure")
        if failure:
            text += f"\nLast alert failed ({when_label(failure.get('at'))}): {failure.get('message')}"
        self.malware_alerts.setText(text)
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

    def _edit_malware_alerts(self) -> None:
        def send_test(target: str, changes: dict, dialog: QDialog) -> None:
            self.busy("Sending a test alert…", lambda: self.connection.malware_alert_test(target, changes),
                      lambda _: QMessageBox.information(dialog, TITLE, "Test alert sent."), "Test alert sent")

        dialog = dialogs.MalwareAlertsDialog(self.malware.get("alerts") or {}, send_test, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        pushover, smtp = dialog.pushover_changes(), dialog.smtp_changes()
        self.busy("Saving malware alerts…", lambda: self.connection.malware_alerts(pushover, smtp),
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

    # -- Intrusion protection (fail2ban) ------------------------------------------

    def _build_fail2ban_tab(self) -> QWidget:
        page = QWidget()
        self.fail2ban_info = QLabel()
        self.fail2ban_info.setWordWrap(True)
        self.fail2ban_info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.fail2ban_install = _button("Install fail2ban", self._install_fail2ban)
        self.fail2ban_settings_button = _button("Settings…", self._edit_fail2ban)
        self.jails_table = make_table(["Watching for", "State", "Failures", "Banned now", "Banned in total"])
        self.bans_table = make_table(["Banned address", "For", "Until"])
        self.bans_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.bans_table.customContextMenuRequested.connect(self._bans_menu)
        self.fail2ban_tables = QSplitter(Qt.Orientation.Vertical)
        self.fail2ban_tables.addWidget(_group("Jails", self.jails_table))
        self.fail2ban_tables.addWidget(_group("Banned addresses (right-click to unban)", self.bans_table))
        layout = QVBoxLayout(page)
        layout.addWidget(self.fail2ban_info)
        layout.addLayout(_row(self.fail2ban_install, self.fail2ban_settings_button,
                              _button("Refresh", self.refresh_fail2ban)))
        layout.addWidget(self.fail2ban_tables, 1)
        return page

    def refresh_fail2ban(self) -> None:
        self.busy("Loading intrusion protection status…", self.connection.fail2ban_status, self.show_fail2ban)

    def show_fail2ban(self, status: dict) -> None:
        self.fail2ban = status
        installed = bool(status.get("installed"))
        self.fail2ban_install.setVisible(not installed)
        self.fail2ban_install.setEnabled(bool(self.server_status.get("supported", True))
                                         and not self.server_status.get("usr_readonly"))
        self.fail2ban_settings_button.setVisible(installed)
        self.fail2ban_tables.setVisible(installed)
        if not installed:
            self.fail2ban_info.setText(
                "fail2ban bans addresses that keep failing to log in over SSH, SFTP, WordPress or Nextcloud, "
                "or that probe the sites for weak spots. It isn't installed on this server.")
            self.jails_table.setRowCount(0)
            self.bans_table.setRowCount(0)
            return

        jails = status.get("jails") or []
        bans = [{**ban, "jail": jail["id"]} for jail in jails for ban in jail.get("banned") or []]
        maxretry = status.get("maxretry")
        lines = [
            f"fail2ban {status.get('version') or ''} — protection {'on' if status.get('enabled') else 'off'}"
            + ("" if status.get("active") else " — fail2ban is stopped"),
            f"Bans: after {maxretry} failure{'' if maxretry == 1 else 's'} within "
            f"{hm.duration_label(int(status.get('findtime') or 0))}, for "
            f"{hm.duration_label(int(status.get('bantime') or 0))}"
            + (", longer for repeat offenders" if status.get("increment") else ""),
            "Never banned: " + ", ".join(["127.0.0.1", "::1", *(status.get("ignoreip") or [])]),
            f"Banned now: {len(bans)}",
        ]
        if status.get("sync_failure"):
            lines.append(f"The jails could not be updated for the current sites: {status['sync_failure']}")
        self.fail2ban_info.setText("\n".join(lines))

        def state(jail: dict) -> str:
            if not jail.get("enabled"):
                return "Off"
            if jail.get("waiting"):
                return "Waiting for a site"
            if not status.get("active") or not jail.get("running"):
                return "Not running"
            return "Watching"

        shown = [jail for jail in jails if jail.get("enabled") or jail.get("running")]
        fill_table(self.jails_table, [
            [hm.jail_label(jail["id"]) + ("" if jail.get("managed") else " (set up outside cockpit-hosting)"),
             state(jail), jail.get("failed", 0), jail.get("banned_count", 0), jail.get("total_banned", 0)]
            for jail in shown
        ], [jail["id"] for jail in shown])
        fill_table(self.bans_table, [[ban["ip"], hm.jail_label(ban["jail"]), ban.get("until") or ""] for ban in bans],
                   bans)

    def _install_fail2ban(self) -> None:
        def done(_):
            self.refresh_status()
            self.refresh_fail2ban()

        self.busy("Installing fail2ban (this can take several minutes)…",
                  lambda: self.connection.stack_install(["fail2ban"], []), done, "fail2ban installed")

    def _edit_fail2ban(self) -> None:
        dialog = dialogs.Fail2banSettingsDialog(self.fail2ban, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        settings = dialog.settings()
        self.busy("Saving intrusion protection settings…", lambda: self.connection.fail2ban_settings(settings),
                  self.show_fail2ban, "Saved")

    def _bans_menu(self, pos) -> None:
        ban = selected_data(self.bans_table)
        if ban is None:
            return
        menu = QMenu(self)
        menu.addAction("Unban").triggered.connect(lambda: self._unban(ban, False))
        menu.addAction("Unban and Never Ban Again").triggered.connect(lambda: self._unban(ban, True))
        menu.exec(self.bans_table.viewport().mapToGlobal(pos))

    def _unban(self, ban: dict, allow: bool) -> None:
        self.busy(f"Unbanning {ban['ip']}…", lambda: self.connection.fail2ban_unban(ban["jail"], ban["ip"], allow),
                  self.show_fail2ban, "Unbanned")

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
        self.storage_default = QLabel()
        self.storage_default.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(_group("Site files", _row(QLabel("New sites' files:"), self.storage_default,
                                                   _button("Change…", self._edit_storage_default))))
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
                           ("clamav", "ClamAV"), ("fail2ban", "fail2ban"), ("repo", "Package repository tools"),
                           ("backup", "restic (backups)")):
            tool = stack.get(key) or {}
            version = tool.get("version") or "Not installed"
            if key == "python" and tool.get("version") and not tool.get("venv"):
                version += " (no venv module)"
            if key == "podman" and tool.get("version") and not tool.get("quadlet"):
                version += " (too old for container sites)"
            if key == "repo" and tool.get("version") and not tool.get("ready"):
                version += " (apt-ftparchive or gpg missing)"
            if key == "backup" and tool.get("version") and not tool.get("rclone"):
                version += " (rclone missing)"
            elif key == "backup" and tool.get("rclone"):
                version += f", rclone {tool['rclone']}"
            rows.append([label, version, running(tool)])
        for php in stack.get("php") or []:
            version = php["version"] + ("" if php.get("cli_installed") else " (no command-line PHP)")
            rows.append([f"PHP {php['version']}", version, "Yes" if php.get("active") else "No"])
        fill_table(self.stack_table, rows)

        settings = status.get("settings") or {}
        self.acme_email.setText(settings.get("acme_email") or "")
        storage = settings.get("storage_default") or ""
        self.storage_default.setText(f"{storage}/<site>" if storage else "/home/<site>")
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
            self.refresh_fail2ban()
            self.backups_tab.refresh()

        self.busy("Installing server components (this can take several minutes)…",
                  lambda: self.connection.stack_install(components, php), done, "Components installed")

    def _edit_storage_default(self) -> None:
        dialog = dialogs.StorageDefaultDialog((self.server_status.get("settings") or {}).get("storage_default") or "",
                                              self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        location = dialog.location.text().strip()
        self.busy("Saving…", lambda: self.connection.settings_set(storage_default=location),
                  lambda _: self.refresh_status(), "Saved")

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
