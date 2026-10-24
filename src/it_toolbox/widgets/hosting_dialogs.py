"""Dialogs for the Hosting Manager (widgets/hosting_manager_widget.py).
Each one only collects input; the manager makes the helper call."""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from it_toolbox.core import async_utils
from it_toolbox.core import hosting_manager as hm

TITLE = "Hosting Manager"


def _buttons(dialog: QDialog, accept) -> QDialogButtonBox:
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    buttons.accepted.connect(accept)
    buttons.rejected.connect(dialog.reject)
    return buttons


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.replace(",", "\n").splitlines() if line.strip()]


def parse_env(text: str) -> dict[str, str]:
    """KEY=value lines (blank lines and # comments skipped) into a dict.
    Raises ValueError naming the first bad line."""
    env = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep or not key.strip():
            raise ValueError(f"'{line}' isn't KEY=value")
        env[key.strip()] = value
    return env


def format_env(env: dict | None) -> str:
    return "\n".join(f"{key}={value}" for key, value in (env or {}).items())


def monospace() -> QFont:
    font = QFont("monospace")
    font.setStyleHint(QFont.StyleHint.TypeWriter)
    return font


def site_kind_missing(kind: str, status: dict) -> str | None:
    """Why a Create Site choice can't be made yet (the Cockpit page's
    siteTypeOptions `missing`), or None."""
    stack = status.get("stack") or {}
    php = bool(stack.get("php"))
    mariadb = bool((stack.get("mariadb") or {}).get("version"))
    podman = bool((stack.get("podman") or {}).get("quadlet"))
    if kind in ("wordpress", "nextcloud"):
        return None if php and mariadb else "Install PHP and MariaDB on the Server tab first"
    if kind == "repo":
        return None if (stack.get("repo") or {}).get("ready") else \
            "Install the package repository tools on the Server tab first"
    if kind in ("forgejo", "zabbix", "container"):
        return None if podman else "Install Podman on the Server tab first"
    if kind == "php":
        return None if php else "Install PHP on the Server tab first"
    if kind == "node":
        return None if (stack.get("node") or {}).get("version") else "Install Node.js on the Server tab first"
    if kind == "python":
        return None if (stack.get("python") or {}).get("venv") else "Install the Python tools on the Server tab first"
    return None


class DeployFields:
    """The admin fields a ready-made application needs (the Cockpit page's
    DeployFields), added to `form`; shared by Create Site and the deploy
    and admin dialogs."""

    def __init__(self, form: QFormLayout, title: str = "") -> None:
        self.form = form
        self.title = QLineEdit(title)
        self.admin_user = QLineEdit()
        self.admin_email = QLineEdit()
        self.admin_password = QLineEdit()
        self.admin_password.setPlaceholderText("Generated when left empty")
        self.admin_password.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Site title:", self.title)
        form.addRow("Admin user:", self.admin_user)
        form.addRow("Admin email:", self.admin_email)
        form.addRow("Admin password:", self.admin_password)
        self.application: str | None = None

    def show_for(self, application: str | None) -> None:
        self.application = application
        shown = application not in (None, "repo")
        self.form.setRowVisible(self.title, application == "wordpress")
        self.form.setRowVisible(self.admin_user, shown and application != "zabbix")
        self.form.setRowVisible(self.admin_email, shown and application != "zabbix")
        self.form.setRowVisible(self.admin_password, shown)
        self.admin_user.setPlaceholderText("Your own name (Forgejo keeps “admin”)" if application == "forgejo"
                                           else "admin")
        self.admin_email.setPlaceholderText("" if application == "wordpress" else "Optional")
        label = self.form.labelForField(self.admin_password)
        if label is not None:
            label.setText("Password of Zabbix's Admin:" if application == "zabbix" else "Admin password:")

    def problem(self) -> str | None:
        application = self.application
        password = self.admin_password.text()
        if application == "wordpress" and not re.fullmatch(r"\S+@\S+\.\S+", self.admin_email.text().strip()):
            return "WordPress needs an admin email address."
        if application == "forgejo" and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,39}",
                                                         self.admin_user.text().strip()):
            return "Forgejo needs an admin user name (letters, digits and . _ -), other than “admin”."
        if password and len(password) < 8:
            return "The admin password needs at least 8 characters."
        return None

    def deploy_input(self) -> dict:
        """What app-deploy takes, empty fields left out so the helper applies its defaults."""
        application = self.application
        result: dict = {"application": application}
        if application == "repo":
            return result
        if application == "wordpress" and self.title.text().strip():
            result["title"] = self.title.text().strip()
        if application != "zabbix":
            for key, edit in (("admin_user", self.admin_user), ("admin_email", self.admin_email)):
                if edit.text().strip():
                    result[key] = edit.text().strip()
        if self.admin_password.text():
            result["admin_password"] = self.admin_password.text()
        return result


class CreateSiteDialog(QDialog):
    """New site: the same choices as the Cockpit page's Create site dialog
    (ready-made applications, your own code, containers and proxies),
    showing only the fields the chosen one uses. A ready-made application
    is deployed right after the site is created (see deploy_input())."""

    def __init__(self, status: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Create Site")
        self.setMinimumWidth(560)
        self.type = QComboBox()
        for kind, _site_type, _application, label in hm.SITE_KINDS:
            missing = site_kind_missing(kind, status)
            self.type.addItem(label, kind)
            index = self.type.count() - 1
            if missing:
                self.type.setItemData(index, missing, Qt.ItemDataRole.ToolTipRole)
                item = self.type.model().item(index)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
        default = "php" if not site_kind_missing("php", status) else "static"
        self.type.setCurrentIndex(self.type.findData(default))
        self.domain = QLineEdit()
        self.domain.setPlaceholderText("example.com")
        self.www = QCheckBox()
        self.www.setChecked(True)
        self.aliases = QLineEdit()
        self.aliases.setPlaceholderText("other.example.com, separated by commas")
        self.name = QLineEdit()
        self.name.setPlaceholderText("Chosen from the domain when left empty")
        self.php_version = QComboBox()
        for php in (status.get("stack") or {}).get("php") or []:
            self.php_version.addItem(f"PHP {php['version']}", php["version"])
        self.upstream = QLineEdit()
        self.upstream.setPlaceholderText("http://127.0.0.1:8080")
        self.app_command = QLineEdit()
        self.app_command.setPlaceholderText("Default: node server.js / the venv's python app.py")
        self.image = QLineEdit()
        self.image.setPlaceholderText("docker.io/library/nginx:latest")
        self.container_port = QSpinBox()
        self.container_port.setRange(1, 65535)
        self.container_port.setValue(80)
        self.volumes = QLineEdit()
        self.volumes.setPlaceholderText("/data, /config (paths inside the container)")
        self.env = QPlainTextEdit()
        self.env.setPlaceholderText("KEY=value, one per line")
        self.env.setFixedHeight(80)
        self.zabbix_version = QComboBox()
        for release in hm.ZABBIX_NEW_RELEASES:
            self.zabbix_version.addItem(hm.zabbix_release_label(release), release)
        self.zabbix_version.setToolTip("To bring in an existing Zabbix, create the site, then use Import on its "
                                       "Settings tab.")

        self.form = QFormLayout()
        self.form.addRow("Type:", self.type)
        self.form.addRow("Domain:", self.domain)
        self.form.addRow("", self.www)
        self.form.addRow("Other domains:", self.aliases)
        self.form.addRow("Site user:", self.name)
        self.form.addRow("PHP version:", self.php_version)
        self.form.addRow("Upstream URL:", self.upstream)
        self.form.addRow("Start command:", self.app_command)
        self.form.addRow("Image:", self.image)
        self.form.addRow("Container port:", self.container_port)
        self.form.addRow("Volumes:", self.volumes)
        self.form.addRow("Environment:", self.env)
        self.form.addRow("Zabbix release:", self.zabbix_version)
        self.deploy = DeployFields(self.form)
        self.note = QLabel()
        self.note.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.addLayout(self.form)
        layout.addWidget(self.note)
        layout.addWidget(_buttons(self, self._accept))
        self.type.currentIndexChanged.connect(self._update_fields)
        self.domain.textChanged.connect(self._update_www)
        self._update_fields()

    def kind(self) -> tuple[str, str | None]:
        """(site type, ready-made application or None) of the chosen entry."""
        kind = self.type.currentData()
        entry = next(k for k in hm.SITE_KINDS if k[0] == kind)
        return entry[1], entry[2]

    def site_type(self) -> str:
        return self.kind()[0]

    def application(self) -> str | None:
        return self.kind()[1]

    def _www_alias(self) -> str | None:
        """www.example.com for example.com, not for www.example.com or blog.example.com."""
        domain = self.domain.text().strip().lower().rstrip(".")
        if domain and not domain.startswith("www.") and domain.count(".") == 1:
            return f"www.{domain}"
        return None

    def _update_www(self) -> None:
        alias = self._www_alias()
        self.www.setText(f"Also answer on {alias}" if alias else "")
        self.form.setRowVisible(self.www, alias is not None)

    def _update_fields(self) -> None:
        site_type, application = self.kind()
        custom_container = site_type == "container" and application not in hm.CONTAINER_APPLICATIONS
        visible = {
            self.php_version: site_type == "php",
            self.upstream: site_type == "proxy",
            self.app_command: site_type in ("node", "python") or custom_container,
            self.image: custom_container,
            self.container_port: custom_container,
            self.volumes: custom_container,
            self.env: site_type in ("node", "python") or custom_container,
            self.zabbix_version: application == "zabbix",
        }
        for widget, shown in visible.items():
            self.form.setRowVisible(widget, shown)
        self.app_command.setPlaceholderText(
            "Default: the image's own command" if site_type == "container"
            else "Default: node server.js / the venv's python app.py"
        )
        self.deploy.show_for(application)
        notes = {
            "wordpress": "The latest WordPress is installed with its database and cron job. This can take a few "
                         "minutes.",
            "nextcloud": "The latest Nextcloud is installed with its database and cron job, with Nextcloud Office "
                         "(Collabora Online in a container; needs Podman and about 1 GB of memory), draw.io and "
                         "Team folders. This can take a few minutes.",
            "repo": "A signing key and an empty RPM and .deb repository are made. Upload packages over SFTP or "
                    "from the site's Settings tab.",
            "forgejo": "Forgejo runs in a container of the site's user, with its own SSH server for Git. Add "
                       "Actions runners from the site's Settings tab.",
            "zabbix": "Zabbix server, frontend and database run in containers of the site's user.",
        }
        self.note.setText(notes.get(application or "", ""))
        self.note.setVisible(bool(application))
        self._update_www()

    def _accept(self) -> None:
        site_type = self.site_type()
        problem = None
        missing = self.type.itemData(self.type.currentIndex(), Qt.ItemDataRole.ToolTipRole)
        if missing:
            problem = missing + "."
        elif not self.domain.text().strip():
            problem = "A domain is required."
        elif site_type == "php" and self.php_version.count() == 0:
            problem = "No PHP version is installed. Install one on the Server tab first."
        elif site_type == "proxy" and not self.upstream.text().strip():
            problem = "A reverse proxy site needs an upstream URL."
        elif self.form.isRowVisible(self.image) and not self.image.text().strip():
            problem = "A container site needs an image."
        else:
            problem = self.deploy.problem()
            if problem is None:
                try:
                    parse_env(self.env.toPlainText())
                except ValueError as exc:
                    problem = f"Environment: {exc}"
        if problem:
            QMessageBox.warning(self, TITLE, problem)
            return
        self.accept()

    def site_input(self) -> dict:
        site_type, application = self.kind()
        aliases = _lines(self.aliases.text())
        www = self._www_alias()
        if www and self.www.isChecked() and www not in aliases:
            aliases.insert(0, www)
        result = {
            "type": site_type,
            "domain": self.domain.text().strip(),
            "aliases": aliases,
            "name": self.name.text().strip(),
        }
        if site_type == "php":
            result["php_version"] = self.php_version.currentData()
        if site_type == "proxy":
            result["upstream"] = self.upstream.text().strip()
        if self.form.isRowVisible(self.app_command) and self.app_command.text().strip():
            result["app_command"] = self.app_command.text().strip()
        if self.form.isRowVisible(self.env):
            result["app_env"] = parse_env(self.env.toPlainText())
        if self.form.isRowVisible(self.image):
            result["image"] = self.image.text().strip()
            result["container_port"] = self.container_port.value()
            result["volumes"] = _lines(self.volumes.text())
        if application in hm.CONTAINER_APPLICATIONS:
            result["application"] = application
        if application == "zabbix":
            result["zabbix_version"] = self.zabbix_version.currentData()
        return result

    def deploy_input(self) -> dict | None:
        """The app-deploy call that follows site-create, or None for a plain site."""
        return self.deploy.deploy_input() if self.application() else None


class DeleteSiteDialog(QDialog):
    def __init__(self, site: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Delete Site")
        domain = site.get("primary_domain") or site["name"]
        label = QLabel(
            f"Delete {domain}? Its nginx configuration, certificate, app, cron jobs and the "
            f"site user {site['name']} are removed."
        )
        label.setWordWrap(True)
        self.delete_databases = QCheckBox("Also delete the site's databases")
        self.keep_files = QCheckBox(f"Keep the site's files ({site.get('home', '')})")
        layout = QVBoxLayout(self)
        layout.addWidget(label)
        layout.addWidget(self.delete_databases)
        layout.addWidget(self.keep_files)
        layout.addWidget(_buttons(self, self.accept))


class StackDialog(QDialog):
    """Pick stack components and PHP versions to install."""

    def __init__(self, status: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Install Server Components")
        stack = status.get("stack") or {}
        installed = {
            "nginx": stack.get("nginx", {}).get("version"),
            "mariadb": stack.get("mariadb", {}).get("version"),
            "certbot": stack.get("certbot", {}).get("version"),
            "nodejs": stack.get("node", {}).get("version"),
            "python": stack.get("python", {}).get("venv"),
            "podman": stack.get("podman", {}).get("version"),
            "clamav": stack.get("clamav", {}).get("version"),
            "fail2ban": stack.get("fail2ban", {}).get("version"),
            "repo": (stack.get("repo") or {}).get("version") if (stack.get("repo") or {}).get("ready") else None,
            "backup": (stack.get("backup") or {}).get("version") if (stack.get("backup") or {}).get("rclone")
            else None,
        }
        self.components: dict[str, QCheckBox] = {}
        components_box = QGroupBox("Components")
        components_layout = QVBoxLayout(components_box)
        for component in hm.STACK_COMPONENTS:
            label = hm.STACK_COMPONENT_LABELS[component]
            if installed.get(component):
                label += " (installed)"
            box = QCheckBox(label)
            self.components[component] = box
            components_layout.addWidget(box)

        have_php = {php["version"] for php in stack.get("php") or []}
        self.php: dict[str, QCheckBox] = {}
        php_box = QGroupBox("PHP versions")
        php_layout = QHBoxLayout(php_box)
        for version in status.get("php_choices") or []:
            box = QCheckBox(f"{version} (installed)" if version in have_php else version)
            self.php[version] = box
            php_layout.addWidget(box)
        php_layout.addStretch(1)

        note = QLabel("Installing can take several minutes.")
        layout = QVBoxLayout(self)
        layout.addWidget(components_box)
        layout.addWidget(php_box)
        layout.addWidget(note)
        layout.addWidget(_buttons(self, self._accept))

    def selection(self) -> tuple[list[str], list[str]]:
        components = [name for name, box in self.components.items() if box.isChecked()]
        php = [version for version, box in self.php.items() if box.isChecked()]
        return components, php

    def _accept(self) -> None:
        if self.selection() == ([], []):
            QMessageBox.warning(self, TITLE, "Pick at least one component or PHP version.")
            return
        self.accept()


class DnsProviderDialog(QDialog):
    def __init__(self, provider: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{hm.DNS_PROVIDER_LABELS[provider]} API Credentials")
        self.fields: dict[str, QLineEdit] = {}
        form = QFormLayout()
        for key, label in hm.DNS_PROVIDER_FIELDS[provider]:
            edit = QLineEdit()
            edit.setEchoMode(QLineEdit.EchoMode.Password)
            self.fields[key] = edit
            form.addRow(f"{label}:", edit)
        note = QLabel("The credentials are tested before they're saved on the server (root-only file).")
        note.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addWidget(_buttons(self, self._accept))

    def credentials(self) -> dict[str, str]:
        return {key: edit.text().strip() for key, edit in self.fields.items()}

    def _accept(self) -> None:
        if not all(self.credentials().values()):
            QMessageBox.warning(self, TITLE, "Fill in every field.")
            return
        self.accept()


class CustomCertificateDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Upload Certificate")
        self.setMinimumSize(560, 480)
        self.certificate = QPlainTextEdit()
        self.certificate.setPlaceholderText("-----BEGIN CERTIFICATE-----\n… (with the chain, if any)")
        self.certificate.setFont(monospace())
        self.private_key = QPlainTextEdit()
        self.private_key.setPlaceholderText("-----BEGIN PRIVATE KEY-----\n…")
        self.private_key.setFont(monospace())
        layout = QVBoxLayout(self)
        for label, edit in (("Certificate (PEM):", self.certificate), ("Private key (PEM):", self.private_key)):
            row = QHBoxLayout()
            row.addWidget(QLabel(label), 1)
            load = QPushButton("Load from File…")
            load.clicked.connect(lambda _=False, e=edit: self._load(e))
            row.addWidget(load)
            layout.addLayout(row)
            layout.addWidget(edit, 1)
        layout.addWidget(_buttons(self, self._accept))

    def _load(self, edit: QPlainTextEdit) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open PEM File", "", "PEM files (*.pem *.crt *.key);;All files (*)")
        if path:
            try:
                edit.setPlainText(Path(path).read_text())
            except (OSError, UnicodeDecodeError) as exc:
                QMessageBox.warning(self, TITLE, f"Couldn't read {path}: {exc}")

    def _accept(self) -> None:
        if not self.certificate.toPlainText().strip() or not self.private_key.toPlainText().strip():
            QMessageBox.warning(self, TITLE, "Both the certificate and the private key are needed.")
            return
        self.accept()


class ScheduleEdit(QWidget):
    """A schedule field that the helper's schedule-check reads while it's
    typed (debounced), showing the next run or why it's refused -- as the
    Cockpit page's cron and backup schedule fields do. `checker(schedule)`
    is the blocking HostingConnection.schedule_check; without one the
    field is plain. `presets` adds a menu of (schedule, label) choices."""

    DELAY_MS = 400

    def __init__(self, schedule: str = "", checker=None, presets: list[tuple[str, str]] | None = None,
                 placeholder: str = "", next_label: str = "Next run") -> None:
        super().__init__()
        self._checker = checker
        self._next_label = next_label
        self._checked: tuple[str, str | None] | None = None
        self.edit = QLineEdit(schedule)
        self.edit.setPlaceholderText(placeholder)
        self.edit.setFont(monospace())
        self.presets = QComboBox()
        for value, label in presets or []:
            self.presets.addItem(label, value)
        self.presets.addItem("Custom", "")
        self.presets.setVisible(bool(presets))
        self.presets.activated.connect(self._preset_chosen)
        self.result = QLabel()
        self.result.setWordWrap(True)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(self.DELAY_MS)
        self._timer.timeout.connect(self._check)
        self.edit.textChanged.connect(self._changed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.presets)
        layout.addWidget(self.edit)
        layout.addWidget(self.result)
        self._changed()

    def text(self) -> str:
        return self.edit.text().strip()

    def error(self) -> str | None:
        """Why the helper refused the current text, once it has been checked."""
        if self._checked and self._checked[0] == self.text():
            return self._checked[1]
        return None

    def _preset_chosen(self) -> None:
        if self.presets.currentData():
            self.edit.setText(self.presets.currentData())

    def _changed(self) -> None:
        index = self.presets.findData(self.text())
        self.presets.setCurrentIndex(index if index >= 0 else self.presets.count() - 1)
        if self._checker is not None and self.text():
            self._timer.start()
        else:
            self.result.clear()

    def _check(self) -> None:
        schedule = self.text()

        def ok(reply: dict) -> None:
            try:
                if schedule != self.text():
                    return
                self._checked = (schedule, None)
                text = f"systemd: {reply.get('on_calendar', '')}"
                if reply.get("next_run"):
                    text += f" — {self._next_label}: {reply['next_run']}"
                self.result.setStyleSheet("")
                self.result.setText(text)
            except RuntimeError:
                pass

        def failed(error: Exception) -> None:
            try:
                if schedule != self.text():
                    return
                self._checked = (schedule, str(error))
                self.result.setStyleSheet("color: #c9190b;")
                self.result.setText(str(error))
            except RuntimeError:
                pass

        async_utils.run_in_background(lambda: self._checker(schedule), on_result=ok, on_error=failed)


class CronJobDialog(QDialog):
    def __init__(self, job: dict | None = None, parent: QWidget | None = None, checker=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Cron Job" if job else "Add Cron Job")
        self.setMinimumWidth(480)
        self.schedule = ScheduleEdit(job["schedule"] if job else "", checker,
                                     placeholder="*/15 * * * *  or  @daily")
        self.command = QLineEdit(job["command"] if job else "")
        self.command.setPlaceholderText("php htdocs/example.com/cron.php")
        note = QLabel("Cron syntax (minute hour day month weekday) or @hourly, @daily, @weekly, @monthly. "
                      "The command runs as the site user in its home folder.")
        note.setWordWrap(True)
        form = QFormLayout()
        form.addRow("Schedule:", self.schedule)
        form.addRow("Command:", self.command)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addWidget(_buttons(self, self._accept))

    def _accept(self) -> None:
        if not self.schedule.text() or not self.command.text().strip():
            QMessageBox.warning(self, TITLE, "A schedule and a command are required.")
            return
        if self.schedule.error():
            QMessageBox.warning(self, TITLE, f"Schedule: {self.schedule.error()}")
            return
        self.accept()

    def values(self) -> tuple[str, str]:
        return self.schedule.text(), self.command.text().strip()


class DatabaseDialog(QDialog):
    def __init__(self, sites: list[str], site: str | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Create Database")
        self.name = QLineEdit()
        self.user = QLineEdit()
        self.user.setPlaceholderText("Same as the database name")
        self.password = QLineEdit()
        self.password.setPlaceholderText("Generated when left empty")
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.site = QComboBox()
        self.site.addItem("(none)", "")
        for name in sites:
            self.site.addItem(name, name)
        if site:
            self.site.setCurrentIndex(max(0, self.site.findData(site)))
            self.site.setEnabled(False)
        form = QFormLayout()
        form.addRow("Database name:", self.name)
        form.addRow("User:", self.user)
        form.addRow("Password:", self.password)
        form.addRow("Site:", self.site)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(_buttons(self, self._accept))

    def _accept(self) -> None:
        if not self.name.text().strip():
            QMessageBox.warning(self, TITLE, "A database name is required.")
            return
        self.accept()

    def values(self) -> dict:
        return {
            "name": self.name.text().strip(),
            "user": self.user.text().strip(),
            "password": self.password.text(),
            "site": self.site.currentData() or "",
        }


class DeployDialog(QDialog):
    """Deploy WordPress or Nextcloud into a PHP site."""

    def __init__(self, site: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Deploy Application")
        self.application = QComboBox()
        for app in hm.APPLICATIONS:
            self.application.addItem(hm.APPLICATION_LABELS[app], app)
        self.title = QLineEdit(site.get("primary_domain") or "")
        self.admin_user = QLineEdit("admin")
        self.admin_email = QLineEdit()
        self.admin_password = QLineEdit()
        self.admin_password.setPlaceholderText("Generated when left empty")
        self.admin_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.form = QFormLayout()
        self.form.addRow("Application:", self.application)
        self.form.addRow("Site title:", self.title)
        self.form.addRow("Admin user:", self.admin_user)
        self.form.addRow("Admin email:", self.admin_email)
        self.form.addRow("Admin password:", self.admin_password)
        self.note = QLabel()
        self.note.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addLayout(self.form)
        layout.addWidget(self.note)
        layout.addWidget(_buttons(self, self._accept))
        self.application.currentIndexChanged.connect(self._update_fields)
        self._update_fields()

    def _update_fields(self) -> None:
        wordpress = self.application.currentData() == "wordpress"
        self.form.setRowVisible(self.title, wordpress)
        self.form.setRowVisible(self.admin_email, wordpress)
        note = ("The site's web folder must be empty apart from the placeholder page. "
                "A database is created for the application. This can take several minutes.")
        if not wordpress:
            note += ("\n\nNextcloud Office (Collabora Online in a container of the site's user; needs Podman "
                     "and about 1 GB of memory), draw.io and Team folders are set up with it.")
        self.note.setText(note)

    def _accept(self) -> None:
        if not self.admin_user.text().strip():
            QMessageBox.warning(self, TITLE, "An admin user is required.")
            return
        if self.application.currentData() == "wordpress" and not self.admin_email.text().strip():
            QMessageBox.warning(self, TITLE, "WordPress needs an admin email address.")
            return
        self.accept()

    def deploy_input(self) -> dict:
        result = {"application": self.application.currentData(), "admin_user": self.admin_user.text().strip()}
        if self.application.currentData() == "wordpress":
            result["admin_email"] = self.admin_email.text().strip()
            if self.title.text().strip():
                result["title"] = self.title.text().strip()
        if self.admin_password.text():
            result["admin_password"] = self.admin_password.text()
        return result


class CredentialsDialog(QDialog):
    """Shows generated credentials once, each with a Copy button."""

    def __init__(self, title: str, intro: str, rows: list[tuple[str, str]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(460)
        label = QLabel(intro)
        label.setWordWrap(True)
        form = QFormLayout()
        for name, value in rows:
            edit = QLineEdit(str(value))
            edit.setReadOnly(True)
            copy = QPushButton("Copy")
            copy.clicked.connect(lambda _=False, v=str(value): QGuiApplication.clipboard().setText(v))
            row = QHBoxLayout()
            row.addWidget(edit, 1)
            row.addWidget(copy)
            form.addRow(f"{name}:", row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.accept)
        layout = QVBoxLayout(self)
        layout.addWidget(label)
        layout.addLayout(form)
        layout.addWidget(buttons)


class MalwareAlertsDialog(QDialog):
    """Where malware scan alerts go: Pushover and/or email over SMTP, as in
    the Cockpit page's malware settings. Stored secrets are never sent back
    by the helper, so their fields start empty and are only sent when typed.
    `send_test(target, changes, dialog)` sends a test alert with the values
    as they are in the dialog."""

    def __init__(self, alerts: dict, send_test=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Malware Alerts")
        self.setMinimumWidth(520)
        self.saved_pushover = alerts.get("pushover") or {}
        self.saved_smtp = alerts.get("smtp") or {}
        self._send_test = send_test
        saved_hint = "Saved. Leave empty to keep it."

        self.pushover_enabled = QCheckBox("Send alerts with Pushover")
        self.pushover_enabled.setChecked(bool(self.saved_pushover.get("enabled")))
        self.pushover_token = QLineEdit()
        self.pushover_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.pushover_token.setPlaceholderText(
            saved_hint if self.saved_pushover.get("token_set") else "The token of an application at pushover.net")
        self.pushover_user = QLineEdit()
        self.pushover_user.setEchoMode(QLineEdit.EchoMode.Password)
        self.pushover_user.setPlaceholderText(
            saved_hint if self.saved_pushover.get("user_set") else "Your user or group key")
        self.pushover_test = QPushButton("Send Test Alert")
        self.pushover_test.clicked.connect(lambda _=False: self._test("pushover"))
        pushover_box = QGroupBox("Pushover")
        pushover_form = QFormLayout(pushover_box)
        pushover_form.addRow("", self.pushover_enabled)
        pushover_form.addRow("API token:", self.pushover_token)
        pushover_form.addRow("User key:", self.pushover_user)
        pushover_form.addRow("", self.pushover_test)

        smtp = self.saved_smtp
        self.smtp_enabled = QCheckBox("Send alerts by email")
        self.smtp_enabled.setChecked(bool(smtp.get("enabled")))
        self.smtp_host = QLineEdit(smtp.get("host") or "")
        self.smtp_host.setPlaceholderText("smtp.example.com")
        self.smtp_security = QComboBox()
        for security in hm.SMTP_SECURITY:
            self.smtp_security.addItem(hm.SMTP_SECURITY_LABELS[security], security)
        self.smtp_security.setCurrentIndex(max(0, self.smtp_security.findData(smtp.get("security") or "starttls")))
        self.smtp_port = QSpinBox()
        self.smtp_port.setRange(1, 65535)
        self.smtp_port.setValue(int(smtp.get("port") or hm.SMTP_PORTS[self.smtp_security.currentData()]))
        self.smtp_security.currentIndexChanged.connect(self._security_changed)
        self.smtp_user = QLineEdit(smtp.get("username") or "")
        self.smtp_user.setPlaceholderText("Leave empty if the server doesn't need a login")
        self.smtp_password = QLineEdit()
        self.smtp_password.setEchoMode(QLineEdit.EchoMode.Password)
        if smtp.get("password_set"):
            self.smtp_password.setPlaceholderText(saved_hint)
        self.smtp_user.textChanged.connect(lambda text: self.smtp_password.setEnabled(bool(text.strip())))
        self.smtp_password.setEnabled(bool(self.smtp_user.text().strip()))
        self.smtp_sender = QLineEdit(smtp.get("sender") or "")
        self.smtp_sender.setPlaceholderText("server@example.com")
        self.smtp_recipients = QLineEdit(", ".join(smtp.get("recipients") or []))
        self.smtp_recipients.setPlaceholderText("One or more addresses, separated by commas")
        self.smtp_test = QPushButton("Send Test Alert")
        self.smtp_test.clicked.connect(lambda _=False: self._test("smtp"))
        smtp_box = QGroupBox("Email")
        smtp_form = QFormLayout(smtp_box)
        smtp_form.addRow("", self.smtp_enabled)
        smtp_form.addRow("SMTP server:", self.smtp_host)
        smtp_form.addRow("Security:", self.smtp_security)
        smtp_form.addRow("Port:", self.smtp_port)
        smtp_form.addRow("User name:", self.smtp_user)
        smtp_form.addRow("Password:", self.smtp_password)
        smtp_form.addRow("From:", self.smtp_sender)
        smtp_form.addRow("To:", self.smtp_recipients)
        smtp_form.addRow("", self.smtp_test)

        note = QLabel("An alert goes out when a scan finds infected files (not ones marked as false positives).")
        note.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addWidget(note)
        layout.addWidget(pushover_box)
        layout.addWidget(smtp_box)
        layout.addWidget(_buttons(self, self._accept))

    def _security_changed(self) -> None:
        # Follow the usual port, unless someone typed another one.
        if self.smtp_port.value() in hm.SMTP_PORTS.values():
            self.smtp_port.setValue(hm.SMTP_PORTS[self.smtp_security.currentData()])

    def pushover_ready(self) -> bool:
        return ((bool(self.pushover_token.text().strip()) or bool(self.saved_pushover.get("token_set")))
                and (bool(self.pushover_user.text().strip()) or bool(self.saved_pushover.get("user_set"))))

    def smtp_ready(self) -> bool:
        return all(edit.text().strip() for edit in (self.smtp_host, self.smtp_sender, self.smtp_recipients))

    def pushover_changes(self) -> dict:
        changes = {"enabled": self.pushover_enabled.isChecked()}
        if self.pushover_token.text().strip():
            changes["token"] = self.pushover_token.text().strip()
        if self.pushover_user.text().strip():
            changes["user"] = self.pushover_user.text().strip()
        return changes

    def smtp_changes(self) -> dict:
        user = self.smtp_user.text().strip()
        changes = {
            "enabled": self.smtp_enabled.isChecked(),
            "host": self.smtp_host.text().strip(),
            "port": self.smtp_port.value(),
            "security": self.smtp_security.currentData(),
            "username": user,
            "sender": self.smtp_sender.text().strip(),
            "recipients": [r for r in self.smtp_recipients.text().replace(";", ",").replace(" ", ",").split(",") if r],
        }
        if user and self.smtp_password.text():
            changes["password"] = self.smtp_password.text()
        if not user:
            # No user name, no login: don't keep a password that can't be used.
            changes["clear_password"] = True
        return changes

    def _test(self, target: str) -> None:
        ready = self.pushover_ready() if target == "pushover" else self.smtp_ready()
        if not ready:
            QMessageBox.warning(self, TITLE, "Pushover needs an API token and a user key."
                                if target == "pushover" else "Email needs an SMTP server, a From and a To address.")
            return
        if self._send_test is not None:
            changes = self.pushover_changes() if target == "pushover" else self.smtp_changes()
            self._send_test(target, changes, self)

    def _accept(self) -> None:
        if self.pushover_enabled.isChecked() and not self.pushover_ready():
            QMessageBox.warning(self, TITLE, "Pushover needs an API token and a user key.")
            return
        if self.smtp_enabled.isChecked() and not self.smtp_ready():
            QMessageBox.warning(self, TITLE, "Email needs an SMTP server, a From and a To address.")
            return
        self.accept()


def _duration_combo(value: int, choices: list[tuple[int, str]]) -> QComboBox:
    combo = QComboBox()
    if value not in dict(choices):
        combo.addItem(hm.duration_label(value), value)
    for seconds, label in choices:
        combo.addItem(label, seconds)
    combo.setCurrentIndex(combo.findData(value))
    return combo


class Fail2banSettingsDialog(QDialog):
    """Intrusion protection settings: on/off, which managed jails run, and
    when to ban (the Cockpit page's Fail2banCard settings)."""

    def __init__(self, status: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Intrusion Protection")
        self.setMinimumWidth(520)
        self.enabled = QCheckBox("Ban addresses that attack the server")
        self.enabled.setChecked(bool(status.get("enabled")))
        self.jails: dict[str, QCheckBox] = {}
        jails_box = QGroupBox("Watch for")
        jails_layout = QVBoxLayout(jails_box)
        for jail in status.get("jails") or []:
            if not jail.get("managed"):
                continue
            box = QCheckBox(hm.jail_label(jail["id"]))
            box.setToolTip(hm.FAIL2BAN_JAILS.get(jail["id"], ("", ""))[1])
            box.setChecked(bool(jail.get("selected")))
            self.jails[jail["id"]] = box
            jails_layout.addWidget(box)
        self.maxretry = QSpinBox()
        self.maxretry.setRange(1, 100)
        self.maxretry.setValue(int(status.get("maxretry") or 5))
        self.findtime = _duration_combo(int(status.get("findtime") or 600), hm.FAIL2BAN_FINDTIMES)
        self.bantime = _duration_combo(int(status.get("bantime") or 3600), hm.FAIL2BAN_DURATIONS)
        self.increment = QCheckBox("Ban repeat offenders for longer each time")
        self.increment.setChecked(bool(status.get("increment")))
        self.ignoreip = QPlainTextEdit("\n".join(status.get("ignoreip") or []))
        self.ignoreip.setFixedHeight(70)
        self.ignoreip.setFont(monospace())
        self.ignoreip.setToolTip("Addresses or networks (such as 203.0.113.0/24), one per line. "
                                 "Add your own, so a mistyped password can't lock you out.")
        form = QFormLayout()
        form.addRow("Attempts:", self.maxretry)
        form.addRow("Within:", self.findtime)
        form.addRow("Ban for:", self.bantime)
        form.addRow("", self.increment)
        form.addRow("Never ban:", self.ignoreip)
        when_box = QGroupBox("When to ban")
        when_box.setLayout(form)
        note = QLabel("fail2ban watches the logs and blocks addresses that keep failing, in the server's firewall. "
                      "127.0.0.1 and ::1 are never banned.")
        note.setWordWrap(True)
        self.enabled.toggled.connect(self._update_enabled)
        layout = QVBoxLayout(self)
        layout.addWidget(note)
        layout.addWidget(self.enabled)
        layout.addWidget(jails_box)
        layout.addWidget(when_box)
        layout.addWidget(_buttons(self, self.accept))
        self._update_enabled()

    def _update_enabled(self) -> None:
        on = self.enabled.isChecked()
        for widget in (*self.jails.values(), self.maxretry):
            widget.setEnabled(on)

    def settings(self) -> dict:
        return {
            "enabled": self.enabled.isChecked(),
            "jails": [jail for jail, box in self.jails.items() if box.isChecked()],
            "maxretry": self.maxretry.value(),
            "findtime": self.findtime.currentData(),
            "bantime": self.bantime.currentData(),
            "increment": self.increment.isChecked(),
            "ignoreip": [v for v in self.ignoreip.toPlainText().replace(",", " ").split() if v],
        }


class MoveStorageDialog(QDialog):
    """Move a site's files to another folder or disk (bind-mounted onto its
    home folder), or back into it -- the Cockpit page's MoveStorageDialog."""

    def __init__(self, site: dict, used: int | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Move Site Files")
        self.setMinimumWidth(480)
        self.site = site
        where = f"The files are in {site.get('storage_dir') or site['home']}."
        if used is not None:
            where += f" They take {hm.format_bytes(used)}."
        self.location = QLineEdit()
        self.location.setPlaceholderText("/srv/sites")
        self.keep_old = QCheckBox("Keep the old copy (otherwise it's deleted once the site runs from the new location)")
        self.help = QLabel()
        self.help.setWordWrap(True)
        note = QLabel("The files are copied while the site runs. It is then disabled for a moment, while what "
                      "changed is copied and it switches over, and enabled again.")
        note.setWordWrap(True)
        form = QFormLayout()
        form.addRow("New location:", self.location)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(where))
        layout.addLayout(form)
        layout.addWidget(self.help)
        layout.addWidget(self.keep_old)
        layout.addWidget(note)
        layout.addWidget(_buttons(self, self._accept))
        self.location.textChanged.connect(self._update_help)
        self._update_help()

    def target(self) -> str:
        return self.location.text().strip().rstrip("/")

    def _back_home(self) -> bool:
        return self.target() in ("", "/home")

    def _update_help(self) -> None:
        site = self.site
        if self._back_home() and site.get("storage"):
            self.help.setText(f"Empty: back into {site['home']}.")
        else:
            self.help.setText(f"An existing folder, such as a disk's mount point. The files go in "
                              f"{self.target() or '…'}/{site['name']}, and the site goes on using {site['home']}.")

    def _accept(self) -> None:
        if self._back_home() and not self.site.get("storage"):
            QMessageBox.warning(self, TITLE, "The files are already in the home folder. Enter a folder to move "
                                             "them to.")
            return
        self.accept()


class StorageDefaultDialog(QDialog):
    def __init__(self, current: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Location of New Sites' Files")
        self.setMinimumWidth(460)
        self.location = QLineEdit(current)
        self.location.setPlaceholderText("/srv/sites")
        note = QLabel("An existing folder, such as a disk's mount point. A new site's files go in "
                      "<folder>/<site user>, mounted onto its home folder. Empty: in /home. Existing sites stay "
                      "where they are; move them from their own Settings tab.")
        note.setWordWrap(True)
        form = QFormLayout()
        form.addRow("Folder:", self.location)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addWidget(_buttons(self, self.accept))


class BackupDestinationDialog(QDialog):
    """Where backups go (Google Drive, S3, SFTP or a local folder) and the
    encryption password -- the Cockpit page's DestinationDialog. Stored
    secrets are never sent back by the helper, so their fields start empty
    and are only sent when typed."""

    def __init__(self, backup: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Backup Destination")
        self.setMinimumWidth(560)
        self.saved = backup.get("destination") or {}
        saved = self.saved
        self.kind = QComboBox()
        for kind in hm.BACKUP_KINDS:
            self.kind.addItem(hm.BACKUP_KIND_LABELS[kind], kind)
        self.kind.setCurrentIndex(max(0, self.kind.findData(saved.get("kind") or "drive")))
        self.path = QLineEdit(saved.get("path") or f"cockpit-hosting/{backup.get('host') or 'server'}")
        self.path.setFont(monospace())
        self.auth = QComboBox()
        self.auth.addItem("A service account (best for a shared drive)", "service_account")
        self.auth.addItem("Your Google account (rclone authorize \"drive\")", "token")
        self.auth.setCurrentIndex(max(0, self.auth.findData(saved.get("auth") or "service_account")))
        self.secret_json = QPlainTextEdit()
        self.secret_json.setFont(monospace())
        self.secret_json.setFixedHeight(80)
        self.shared_drive = QLineEdit(saved.get("shared_drive") or "")
        self.provider = QComboBox()
        for value, label in hm.S3_PROVIDERS:
            self.provider.addItem(label, value)
        self.provider.setCurrentIndex(max(0, self.provider.findData(saved.get("provider") or "Other")))
        self.endpoint = QLineEdit(saved.get("endpoint") or "")
        self.endpoint.setPlaceholderText("s3.example.com")
        self.region = QLineEdit(saved.get("region") or "")
        self.access_key = QLineEdit(saved.get("access_key_id") or "")
        self.secret_key = QLineEdit()
        self.secret_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.host = QLineEdit(saved.get("host") or "")
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(int(saved.get("port") or 22))
        self.user = QLineEdit(saved.get("user") or "")
        self.sftp_password = QLineEdit()
        self.sftp_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.private_key = QPlainTextEdit()
        self.private_key.setFont(monospace())
        self.private_key.setFixedHeight(70)
        self.local_path = QLineEdit(saved.get("local_path") or "/srv/backups")
        self.local_path.setToolTip("Another disk, or a network share mounted here. A folder on the same disk as "
                                   "the sites doesn't survive losing it.")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText(
            "Leave empty to keep the current one" if saved else "Leave empty to make a strong one")
        self.password.setToolTip("To use backups made before (by a server you are replacing), enter their password.")

        self.form = QFormLayout()
        self.form.addRow("Store backups on:", self.kind)
        self.form.addRow("Sign in with:", self.auth)
        self.form.addRow("Key or token:", self.secret_json)
        self.form.addRow("Shared drive ID:", self.shared_drive)
        self.form.addRow("Provider:", self.provider)
        self.form.addRow("Endpoint:", self.endpoint)
        self.form.addRow("Region:", self.region)
        self.form.addRow("Access key:", self.access_key)
        self.form.addRow("Secret key:", self.secret_key)
        self.form.addRow("Server:", self.host)
        self.form.addRow("Port:", self.port)
        self.form.addRow("User name:", self.user)
        self.form.addRow("Password:", self.sftp_password)
        self.form.addRow("Private key:", self.private_key)
        self.form.addRow("Folder:", self.path)
        self.form.addRow("Folder on this server:", self.local_path)
        self.form.addRow("Encryption password:", self.password)
        note = QLabel("Backups are encrypted before they leave the server. Saving connects to the destination, "
                      "which can take a moment.")
        note.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addLayout(self.form)
        layout.addWidget(note)
        layout.addWidget(_buttons(self, self._accept))
        self.kind.currentIndexChanged.connect(self._update_fields)
        self.auth.currentIndexChanged.connect(self._update_fields)
        self._update_fields()

    def _secret_saved(self, key: str) -> bool:
        return self.saved.get("kind") == self.kind.currentData() and bool(self.saved.get(key))

    def _update_fields(self) -> None:
        kind = self.kind.currentData()
        rows = {
            "drive": [self.auth, self.secret_json, self.shared_drive, self.path],
            "s3": [self.provider, self.endpoint, self.region, self.access_key, self.secret_key, self.path],
            "sftp": [self.host, self.port, self.user, self.sftp_password, self.private_key, self.path],
            "local": [self.local_path],
        }[kind]
        for widget in (self.auth, self.secret_json, self.shared_drive, self.provider, self.endpoint, self.region,
                       self.access_key, self.secret_key, self.host, self.port, self.user, self.sftp_password,
                       self.private_key, self.path, self.local_path):
            self.form.setRowVisible(widget, widget in rows)
        hint = "Saved. Leave empty to keep it."
        service_account = self.auth.currentData() == "service_account"
        self.secret_json.setPlaceholderText(
            hint if self._secret_saved("service_account_set" if service_account else "token_set")
            else "The service account's JSON key file" if service_account
            else "The JSON rclone printed, starting with {\"access_token\"")
        self.shared_drive.setPlaceholderText("After /folders/ in the shared drive's address" if service_account
                                             else "Leave empty for your own My Drive")
        self.secret_key.setPlaceholderText(hint if self._secret_saved("secret_access_key_set") else "")
        self.sftp_password.setPlaceholderText(hint if self._secret_saved("password_set")
                                              else "Or a private key below")
        self.private_key.setPlaceholderText(hint if self._secret_saved("private_key_set")
                                            else "Without a passphrase, -----BEGIN … PRIVATE KEY----- and all")
        self.path.setPlaceholderText("my-bucket/cockpit-hosting" if kind == "s3" else "")
        label = self.form.labelForField(self.path)
        if label is not None:
            label.setText("Bucket and folder:" if kind == "s3" else "Folder:")

    def destination(self) -> dict:
        kind = self.kind.currentData()
        if kind == "drive":
            auth = self.auth.currentData()
            result = {"kind": kind, "path": self.path.text().strip(), "auth": auth,
                      "shared_drive": self.shared_drive.text().strip()}
            if self.secret_json.toPlainText().strip():
                result[auth] = self.secret_json.toPlainText().strip()
            return result
        if kind == "s3":
            result = {"kind": kind, "path": self.path.text().strip(), "provider": self.provider.currentData(),
                      "endpoint": self.endpoint.text().strip(), "region": self.region.text().strip(),
                      "access_key_id": self.access_key.text().strip()}
            if self.secret_key.text():
                result["secret_access_key"] = self.secret_key.text()
            return result
        if kind == "sftp":
            result = {"kind": kind, "path": self.path.text().strip(), "host": self.host.text().strip(),
                      "port": self.port.value(), "user": self.user.text().strip()}
            if self.sftp_password.text():
                result["password"] = self.sftp_password.text()
            if self.private_key.toPlainText().strip():
                result["private_key"] = self.private_key.toPlainText().strip()
            return result
        return {"kind": kind, "local_path": self.local_path.text().strip()}

    def problem(self) -> str | None:
        kind = self.kind.currentData()
        path = self.path.text().strip()
        if kind == "drive":
            service_account = self.auth.currentData() == "service_account"
            if not self.secret_json.toPlainText().strip() and not self._secret_saved(
                    "service_account_set" if service_account else "token_set"):
                return "Paste the service account key." if service_account else "Paste the token rclone printed."
            if service_account and not self.shared_drive.text().strip():
                return "A service account needs a shared drive ID."
        elif kind == "s3":
            if not self.access_key.text().strip() or not (self.secret_key.text()
                                                          or self._secret_saved("secret_access_key_set")):
                return "S3 needs an access key and a secret key."
            if self.provider.currentData() != "AWS" and not self.endpoint.text().strip():
                return "This provider needs an endpoint."
        elif kind == "sftp":
            if not self.host.text().strip() or not self.user.text().strip():
                return "SFTP needs a server and a user name."
            if not (self.sftp_password.text() or self.private_key.toPlainText().strip()
                    or self._secret_saved("password_set") or self._secret_saved("private_key_set")):
                return "SFTP needs a password or a private key."
        elif not self.local_path.text().strip().startswith("/"):
            return "The folder must be an absolute path."
        if kind != "local" and not path:
            return "A folder is required."
        return None

    def _accept(self) -> None:
        problem = self.problem()
        if problem:
            QMessageBox.warning(self, TITLE, problem)
            return
        self.accept()


class BackupSettingsDialog(QDialog):
    """When the server backs up its sites, how many backups are kept, and
    whether a failure sends an alert (the Cockpit page's SettingsDialog)."""

    def __init__(self, backup: dict, checker=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Backup Schedule")
        self.setMinimumWidth(500)
        self.enabled = QCheckBox("Back up the sites on a schedule")
        self.enabled.setChecked(bool(backup.get("enabled")))
        self.enabled.setToolTip("Backs up every site that follows the server's schedule. A site can have its own "
                                "schedule, or none, on its Backups tab.")
        self.schedule = ScheduleEdit(backup.get("schedule") or "0 2 * * *", checker, hm.BACKUP_SCHEDULE_PRESETS,
                                     next_label="Next backup")
        keep = backup.get("keep") or {}
        self.keep: dict[str, QSpinBox] = {}
        form = QFormLayout()
        form.addRow("", self.enabled)
        form.addRow("When:", self.schedule)
        for key, label in (("daily", "Daily backups"), ("weekly", "Weekly backups"), ("monthly", "Monthly backups")):
            box = QSpinBox()
            box.setRange(0, 1000)
            box.setValue(int(keep.get(key) or 0))
            self.keep[key] = box
            form.addRow(f"Keep {label.lower()}:", box)
        self.alerts = QCheckBox("Alert when a backup fails (through the malware scan alert targets)")
        self.alerts.setChecked(bool(backup.get("alerts")))
        form.addRow("", self.alerts)
        note = QLabel("For each site: the last backup of each of that many days, weeks and months. Older ones are "
                      "removed after each backup.")
        note.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addWidget(_buttons(self, self._accept))
        self.enabled.toggled.connect(self.schedule.setEnabled)
        self.schedule.setEnabled(self.enabled.isChecked())

    def settings(self) -> dict:
        return {
            "enabled": self.enabled.isChecked(),
            "schedule": self.schedule.text(),
            "keep": {key: box.value() for key, box in self.keep.items()},
            "alerts": self.alerts.isChecked(),
        }

    def _accept(self) -> None:
        if not self.schedule.text() or self.schedule.error():
            QMessageBox.warning(self, TITLE, f"Schedule: {self.schedule.error() or 'required'}")
            return
        if not any(box.value() for box in self.keep.values()):
            QMessageBox.warning(self, TITLE, "Keep at least one backup.")
            return
        self.accept()


class RestoreDialog(QDialog):
    def __init__(self, site: dict, snapshot: dict, when: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Restore {site.get('primary_domain') or site['name']}")
        self.setMinimumWidth(460)
        has_databases = bool(site.get("databases"))
        intro = QLabel(f"Put the site back as it was at {when} (snapshot {snapshot.get('short_id', '')}).")
        intro.setWordWrap(True)
        self.files = QCheckBox("Files")
        self.files.setChecked(True)
        self.files.setToolTip("The home folder is replaced by the backup's: files changed since go back, files made "
                              "since are removed. Logs are left alone.")
        self.databases = QCheckBox("Databases" if has_databases else "Databases (the site has none)")
        self.databases.setChecked(has_databases)
        self.databases.setEnabled(has_databases)
        self.databases.setToolTip("Each of the site's databases is replaced by its copy in the backup. Users and "
                                  "passwords stay as they are now.")
        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(self.files)
        layout.addWidget(self.databases)
        layout.addWidget(_buttons(self, self._accept))

    def _accept(self) -> None:
        if not self.files.isChecked() and not self.databases.isChecked():
            QMessageBox.warning(self, TITLE, "Choose the files, the databases, or both.")
            return
        self.accept()


FORGEJO_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}:docker://[A-Za-z0-9][A-Za-z0-9._/:@-]{0,300}$")
FORGEJO_RUNNER_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class AddRunnerDialog(QDialog):
    def __init__(self, site_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add a Runner")
        self.setMinimumWidth(560)
        intro = QLabel("The runner is registered in this Forgejo for all its repositories and started in a "
                       "container of the site's user. Its jobs run in containers of their own, on this server's "
                       "network.")
        intro.setWordWrap(True)
        self.runner_name = QLineEdit()
        self.runner_name.setPlaceholderText(f"Leave empty for {site_name}-N")
        self.labels = QPlainTextEdit("\n".join(hm.FORGEJO_DEFAULT_LABELS))
        self.labels.setFont(monospace())
        self.labels.setFixedHeight(80)
        self.labels.setToolTip("One per line: what runs-on: says, and the image its jobs run in")
        self.capacity = QSpinBox()
        self.capacity.setRange(1, 16)
        form = QFormLayout()
        form.addRow("Name:", self.runner_name)
        form.addRow("Labels:", self.labels)
        form.addRow("Jobs at once:", self.capacity)
        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addLayout(form)
        layout.addWidget(_buttons(self, self._accept))

    def label_list(self) -> list[str]:
        return [label for label in re.split(r"[\s,]+", self.labels.toPlainText()) if label]

    def _accept(self) -> None:
        name = self.runner_name.text().strip()
        bad = next((label for label in self.label_list() if not FORGEJO_LABEL.match(label)), None)
        if name and not FORGEJO_RUNNER_NAME.match(name):
            problem = "The name may only have letters, digits and . _ -"
        elif bad:
            problem = f"“{bad}” is not name:docker://image"
        elif not self.label_list():
            problem = "A runner needs at least one label."
        else:
            problem = None
        if problem:
            QMessageBox.warning(self, TITLE, problem)
            return
        self.accept()


class ZabbixUpdateDialog(QDialog):
    def __init__(self, current: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Update Zabbix")
        self.current = current
        self.release = QComboBox()
        for release in hm.ZABBIX_RELEASES:
            if release == current or hm.release_newer(release, current):
                self.release.addItem(hm.zabbix_release_label(release), release)
        self.release.setCurrentIndex(max(0, self.release.findData(current)))
        self.note = QLabel()
        self.note.setWordWrap(True)
        form = QFormLayout()
        form.addRow("Release:", self.release)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.note)
        layout.addWidget(_buttons(self, self.accept))
        self.release.currentIndexChanged.connect(self._update_note)
        self._update_note()

    def new_release(self) -> str:
        """The release to move to, or "" to stay on the current one."""
        release = self.release.currentData()
        return "" if release == self.current else release

    def _update_note(self) -> None:
        release = self.new_release()
        self.note.setText(
            f"Zabbix moves to {release}; the server upgrades the database when it starts, which can't be undone. "
            "Take a backup first." if release
            else "The newest images of this release are pulled, and the server and frontend restarted with them.")


class AdminDialog(QDialog):
    """Create Forgejo's admin, or give Zabbix's Admin its own password, when
    that wasn't done with the site (app-deploy)."""

    def __init__(self, application: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Create the Forgejo Admin" if application == "forgejo" else "Set Admin's Password")
        self.setMinimumWidth(460)
        form = QFormLayout()
        self.fields = DeployFields(form)
        self.fields.show_for(application)
        layout = QVBoxLayout(self)
        if application == "zabbix":
            note = QLabel("Zabbix makes its Admin user with the password “zabbix”: it gets a password of its own.")
            note.setWordWrap(True)
            layout.addWidget(note)
        layout.addLayout(form)
        layout.addWidget(_buttons(self, self._accept))

    def _accept(self) -> None:
        problem = self.fields.problem()
        if problem:
            QMessageBox.warning(self, TITLE, problem)
            return
        self.accept()
