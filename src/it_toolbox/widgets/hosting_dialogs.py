"""Dialogs for the Hosting Manager (widgets/hosting_manager_widget.py).
Each one only collects input; the manager makes the helper call."""

from __future__ import annotations

from pathlib import Path

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


class CreateSiteDialog(QDialog):
    """New site: the same fields as the Cockpit page's CreateSiteDialog,
    showing only the ones the chosen type uses."""

    def __init__(self, status: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Create Site")
        self.setMinimumWidth(520)
        self.type = QComboBox()
        for site_type in hm.SITE_TYPES:
            self.type.addItem(hm.SITE_TYPE_LABELS[site_type], site_type)
        self.domain = QLineEdit()
        self.domain.setPlaceholderText("example.com")
        self.aliases = QLineEdit()
        self.aliases.setPlaceholderText("www.example.com, other.example.com")
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

        self.form = QFormLayout()
        self.form.addRow("Type:", self.type)
        self.form.addRow("Domain:", self.domain)
        self.form.addRow("Aliases:", self.aliases)
        self.form.addRow("Site user:", self.name)
        self.form.addRow("PHP version:", self.php_version)
        self.form.addRow("Upstream URL:", self.upstream)
        self.form.addRow("Start command:", self.app_command)
        self.form.addRow("Image:", self.image)
        self.form.addRow("Container port:", self.container_port)
        self.form.addRow("Volumes:", self.volumes)
        self.form.addRow("Environment:", self.env)

        layout = QVBoxLayout(self)
        layout.addLayout(self.form)
        layout.addWidget(_buttons(self, self._accept))
        self.type.currentIndexChanged.connect(self._update_fields)
        self._update_fields()

    def site_type(self) -> str:
        return self.type.currentData()

    def _update_fields(self) -> None:
        site_type = self.site_type()
        visible = {
            self.php_version: site_type == "php",
            self.upstream: site_type == "proxy",
            self.app_command: site_type in ("node", "python", "container"),
            self.image: site_type == "container",
            self.container_port: site_type == "container",
            self.volumes: site_type == "container",
            self.env: site_type in hm.APP_SITE_TYPES,
        }
        for widget, shown in visible.items():
            self.form.setRowVisible(widget, shown)
        self.app_command.setPlaceholderText(
            "Default: the image's own command" if site_type == "container"
            else "Default: node server.js / the venv's python app.py"
        )

    def _accept(self) -> None:
        site_type = self.site_type()
        problem = None
        if not self.domain.text().strip():
            problem = "A domain is required."
        elif site_type == "php" and self.php_version.count() == 0:
            problem = "No PHP version is installed. Install one on the Server tab first."
        elif site_type == "proxy" and not self.upstream.text().strip():
            problem = "A reverse proxy site needs an upstream URL."
        elif site_type == "container" and not self.image.text().strip():
            problem = "A container site needs an image."
        else:
            try:
                parse_env(self.env.toPlainText())
            except ValueError as exc:
                problem = f"Environment: {exc}"
        if problem:
            QMessageBox.warning(self, TITLE, problem)
            return
        self.accept()

    def site_input(self) -> dict:
        site_type = self.site_type()
        result = {
            "type": site_type,
            "domain": self.domain.text().strip(),
            "aliases": _lines(self.aliases.text()),
            "name": self.name.text().strip(),
        }
        if site_type == "php":
            result["php_version"] = self.php_version.currentData()
        if site_type == "proxy":
            result["upstream"] = self.upstream.text().strip()
        if site_type in hm.APP_SITE_TYPES:
            if self.app_command.text().strip():
                result["app_command"] = self.app_command.text().strip()
            result["app_env"] = parse_env(self.env.toPlainText())
        if site_type == "container":
            result["image"] = self.image.text().strip()
            result["container_port"] = self.container_port.value()
            result["volumes"] = _lines(self.volumes.text())
        return result


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


class CronJobDialog(QDialog):
    def __init__(self, job: dict | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Cron Job" if job else "Add Cron Job")
        self.setMinimumWidth(480)
        self.schedule = QLineEdit(job["schedule"] if job else "")
        self.schedule.setPlaceholderText("*/15 * * * *  or  @daily")
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
        if not self.schedule.text().strip() or not self.command.text().strip():
            QMessageBox.warning(self, TITLE, "A schedule and a command are required.")
            return
        self.accept()

    def values(self) -> tuple[str, str]:
        return self.schedule.text().strip(), self.command.text().strip()


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
        note = QLabel("The site's web folder must be empty apart from the placeholder page. "
                      "A database is created for the application. This can take several minutes.")
        note.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addLayout(self.form)
        layout.addWidget(note)
        layout.addWidget(_buttons(self, self._accept))
        self.application.currentIndexChanged.connect(self._update_fields)
        self._update_fields()

    def _update_fields(self) -> None:
        wordpress = self.application.currentData() == "wordpress"
        self.form.setRowVisible(self.title, wordpress)
        self.form.setRowVisible(self.admin_email, wordpress)

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
