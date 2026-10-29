"""The ready-made application boxes on a Hosting Manager site's Settings
tab that go beyond WordPress and Nextcloud, as on the cockpit-hosting
page: a package repository (RepoCard), Forgejo with its Actions runners
(ForgejoCard), and Zabbix with its import (ZabbixCard). Each box is
given the site-get reply with show_site(), and works through the
SiteDetail it belongs to (its connection, busy runner and show_site)."""

from __future__ import annotations

import html
import re

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from it_toolbox.core import async_utils
from it_toolbox.core import hosting_manager as hm
from it_toolbox.ui import theme
from it_toolbox.widgets import hosting_dialogs as dialogs
from it_toolbox.widgets.hosting_import import ZabbixImportDialog
from it_toolbox.widgets.remote_helper_widget import (
    fill_table,
    make_table,
    selected_data,
)

STATUS_POLL_MS = 15000


def _label() -> QLabel:
    label = QLabel()
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


_KEY_LINE = re.compile(r"^([A-Z][\w .'-]{0,24}): (.+)$")


def info_html(lines: list[str]) -> str:
    """A card's facts as rich text: runs of "Key: value" lines become a
    two-column grid with muted keys, anything else a paragraph."""
    muted = theme.color("muted").name()
    parts: list[str] = []
    rows: list[str] = []

    def flush() -> None:
        if rows:
            parts.append(f'<table cellspacing="0" cellpadding="1">{"".join(rows)}</table>')
            rows.clear()

    for line in lines:
        match = _KEY_LINE.match(line)
        if match:
            key, value = (html.escape(part) for part in match.groups())
            rows.append(f'<tr><td style="color:{muted}; padding-right:16px">{key}</td><td>{value}</td></tr>')
        else:
            flush()
            parts.append(f'<p style="margin-top:4px">{html.escape(line)}</p>')
    flush()
    return "".join(parts)


def _button(text: str, slot) -> QPushButton:
    button = QPushButton(text)
    button.clicked.connect(lambda _=False: slot())
    return button


def _row(*widgets: QWidget) -> QHBoxLayout:
    layout = QHBoxLayout()
    for widget in widgets:
        layout.addWidget(widget)
    layout.addStretch(1)
    return layout


def site_base_url(site: dict) -> str:
    scheme = "http" if (site.get("ssl_mode") or "none") == "none" else "https"
    return f"{scheme}://{site.get('primary_domain') or site['name']}"


def _confirm(parent: QWidget, title: str, text: str) -> bool:
    return QMessageBox.question(parent, title, text) == QMessageBox.StandardButton.Yes


class _Card(QGroupBox):
    def __init__(self, title: str, detail) -> None:
        super().__init__(title)
        self.detail = detail
        self.site: dict = {}

    @property
    def connection(self) -> hm.HostingConnection:
        return self.detail.connection

    @property
    def name(self) -> str:
        return self.site.get("name", "")

    def show_new_password(self, title: str, reply: dict) -> None:
        dialogs.CredentialsDialog(title, "Save the password now — it isn't stored, so it can't be shown again.",
                                  [("User", reply.get("user", "")), ("Password", reply.get("password", ""))],
                                  self).exec()

    def show_deployed(self, result: dict) -> None:
        self.detail.show_site(result["site"])
        app = result["site"].get("application") or {}
        label = hm.APPLICATION_LABELS.get(app.get("name"), app.get("name") or "")
        dialogs.CredentialsDialog(
            f"{label} {app.get('version') or ''} Is Ready".replace("  ", " "),
            "Save the password now — it isn't stored, so it can't be shown again.",
            [("Sign in at", result.get("admin_url", "")), ("User", result.get("admin_user", "")),
             ("Password", result.get("admin_password", ""))], self).exec()


# -- Package repository ---------------------------------------------------------------------

CI_SNIPPET = """      - name: Publish packages
        env:
          REPO_SSH_KEY: ${{{{ secrets.REPO_SSH_KEY }}}}
        run: |
          install -m 600 /dev/null ~/repo-key && echo "$REPO_SSH_KEY" > ~/repo-key
          sftp -i ~/repo-key -P {port} -o StrictHostKeyChecking=accept-new -b - {user}@{host} <<'EOF'
          cd {path}
          -put *.rpm
          -put *.deb
          EOF"""


class RepoCard(_Card):
    """A package repository site: how clients use it, its packages, and
    uploading or deleting packages."""

    def __init__(self, detail) -> None:
        super().__init__("Package Repository", detail)
        self.repo: dict = {}
        self.sftp: dict = {}
        self.info = _label()
        self.problem = _label()
        theme.set_tone(self.problem, "danger")
        self.packages = make_table(["File", "Type", "Size", "Added"])
        self.waiting = _label()
        layout = QVBoxLayout(self)
        layout.addWidget(self.problem)
        layout.addWidget(self.info)
        layout.addLayout(_row(_button("Upload Packages…", self._upload), _button("Rebuild Index", self._reindex),
                              _button("Delete…", self._delete), _button("CI Snippet…", self._ci_snippet),
                              _button("Refresh", self.refresh)))
        layout.addWidget(self.waiting)
        layout.addWidget(self.packages)

    def show_site(self, site: dict) -> None:
        changed = site.get("name") != self.name
        self.site = site
        if changed:
            self.repo = {}
            self.packages.setRowCount(0)
            self.info.setText("Loading…")
            self.refresh()

    def refresh(self) -> None:
        name = self.name
        self.detail.busy("Loading the package repository…", lambda: self.connection.repo_status(name),
                         self.show_repo)
        async_utils.run_in_background(lambda: self.connection.sftp_get(name),
                                      on_result=lambda sftp: setattr(self, "sftp", sftp),
                                      on_error=lambda _error: None)

    def show_repo(self, repo: dict) -> None:
        self.repo = repo
        commands = repo.get("commands") or {}
        rpms = sum(1 for p in repo.get("packages") or [] if p.get("kind") == "rpm")
        debs = len(repo.get("packages") or []) - rpms
        self.info.setText(info_html([
            f"dnf: {commands.get('dnf', '')}",
            f"apt: {commands.get('apt', '')}",
            f"Signing key: {repo.get('fingerprint', '')}  ({repo.get('key_url', '')})",
            (f"Uploads: put .rpm and .deb files in {repo.get('sftp_path', '')} over SFTP (turn it on in the SFTP "
             "tab), or upload them here. They are signed into the index within seconds."),
            "Last indexed: " + (repo.get("indexed_at") or "Never") + f" — {rpms} RPM, {debs} .deb",
        ]))
        problems = []
        if repo.get("last_error"):
            problems.append(f"The last indexing failed: {repo['last_error']}")
        if not repo.get("watching"):
            problems.append("Uploads are not being watched. Rebuild Index to start watching again.")
        self.problem.setText("\n".join(problems))
        self.problem.setVisible(bool(problems))
        waiting = repo.get("waiting") or []
        self.waiting.setText("Left in the incoming folder:\n" + "\n".join(
            f"  {w['file']}: {w.get('reason') or 'waiting to be indexed'}" for w in waiting))
        self.waiting.setVisible(bool(waiting))
        packages = repo.get("packages") or []
        rows = [[p["file"], "RPM" if p["kind"] == "rpm" else ".deb", hm.format_bytes(p.get("size")),
                 p.get("modified", "")] for p in packages]
        data = [{"kind": p["kind"], "file": p["file"]} for p in packages]
        rows += [[w["file"], "incoming", "", w.get("reason") or "waiting"] for w in waiting]
        data += [{"kind": "incoming", "file": w["file"]} for w in waiting]
        fill_table(self.packages, rows, data)

    def _upload(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Upload Packages", "", "Packages (*.rpm *.deb)")
        if not paths:
            return
        bad = next((Path(p).name for p in paths if not hm.PACKAGE_NAME.match(Path(p).name)), None)
        if bad:
            QMessageBox.warning(self, dialogs.TITLE, f"{bad} is not an .rpm or .deb file name.")
            return
        name, incoming = self.name, self.repo.get("incoming")
        if not incoming:
            return

        def upload() -> dict:
            for path in paths:
                self.connection.repo_upload(incoming, Path(path).name, Path(path).read_bytes())
            return self.connection.repo_reindex(name)

        self.detail.busy(f"Uploading {len(paths)} package(s)…", upload, self.show_repo, "Packages published")

    def _reindex(self) -> None:
        name = self.name
        self.detail.busy("Rebuilding the index…", lambda: self.connection.repo_reindex(name), self.show_repo,
                         "Index rebuilt")

    def _delete(self) -> None:
        target = selected_data(self.packages)
        if target is None:
            self.detail.manager.flash("Select a package first")
            return
        text = ("It is removed from the incoming folder." if target["kind"] == "incoming"
                else "It is removed from the repository, and the index is rebuilt. Machines that installed it keep it.")
        if not _confirm(self, "Delete Package", f"Delete {target['file']}? {text}"):
            return
        name = self.name
        self.detail.busy(f"Deleting {target['file']}…",
                         lambda: self.connection.repo_delete(name, target["kind"], target["file"]), self.show_repo,
                         "Deleted")

    def _ci_snippet(self) -> None:
        sftp = self.sftp
        intro = ("Turn SFTP on in the SFTP tab with the public half of an SSH key, and store the private half as "
                 "the secret REPO_SSH_KEY. This step, after the one that builds the packages, uploads them:\n\n")
        if sftp and not sftp.get("enabled"):
            intro = "SFTP is off for this site.\n\n" + intro
        snippet = CI_SNIPPET.format(port=sftp.get("port", 22), user=sftp.get("user", self.name),
                                    host=sftp.get("host", ""), path=self.repo.get("sftp_path", ""))
        self.detail.manager.show_text("Publish from Forgejo or GitHub Actions", intro + snippet)


# -- Forgejo ------------------------------------------------------------------------------------


def runner_status(runner: dict) -> str:
    if runner.get("state") != "active":
        return runner.get("state") or ""
    return {"active": "Running a job", "idle": "Idle", "offline": "Not connected"}.get(runner.get("status"),
                                                                                       "Started")


class ForgejoCard(_Card):
    def __init__(self, detail) -> None:
        super().__init__("Forgejo", detail)
        self.info = _label()
        self.warning = _label()
        theme.set_tone(self.warning, "warning")
        self.update_button = _button("Update…", self._update)
        self.admin_button = _button("Create Admin…", self._create_admin)
        self.password_button = _button("New Admin Password…", self._new_password)
        self.runners = make_table(["Runner", "Labels", "Jobs at once", "Status"])
        self.runners.setMaximumHeight(160)
        self.add_runner_button = _button("Add Runner…", self._add_runner)
        self.no_runners = _label()
        layout = QVBoxLayout(self)
        layout.addWidget(self.info)
        layout.addLayout(_row(self.update_button, self.admin_button, self.password_button))
        layout.addWidget(QLabel("Actions runners:"))
        layout.addWidget(self.warning)
        layout.addWidget(self.no_runners)
        layout.addWidget(self.runners)
        layout.addLayout(_row(self.add_runner_button, _button("Remove Runner…", self._remove_runner),
                              _button("Refresh", self.refresh_runners)))
        self._poll = QTimer(self)
        self._poll.setInterval(STATUS_POLL_MS)
        self._poll.timeout.connect(self._poll_runners)

    def stop(self) -> None:
        self._poll.stop()

    def show_site(self, site: dict) -> None:
        changed = site.get("name") != self.name
        self.site = site
        app = site.get("application") or {}
        base = site_base_url(site)
        ssh = f"ssh://git@{site.get('primary_domain')}:{app.get('ssh_port')}/OWNER/REPO.git"
        admin = (f"{base}{app.get('admin_path') or ''} ({app['admin_user']})" if app.get("admin_user")
                 else "No admin user yet")
        self.info.setText(info_html([
            f"Version: {app.get('version') or 'not known yet'}",
            f"Admin: {admin}",
            f"Git over SSH: {ssh}",
            (f"Forgejo's own SSH server listens on port {app.get('ssh_port')} (opened in firewalld or ufw when one "
             "is on). Users add their SSH keys in Forgejo's settings."),
        ]))
        disabled = bool(site.get("disabled"))
        has_admin = bool(app.get("admin_user"))
        self.update_button.setEnabled(not disabled)
        self.admin_button.setVisible(not has_admin)
        self.password_button.setVisible(has_admin)
        for button in (self.admin_button, self.password_button):
            button.setEnabled(not disabled)
        self.add_runner_button.setEnabled(not disabled and has_admin)
        if changed:
            self.warning.hide()
            self.runners.setRowCount(0)
            self.refresh_runners()
        self._poll.start()

    def refresh_runners(self) -> None:
        name = self.name
        self.detail.busy("Loading the runners…", lambda: self.connection.forgejo_runners(name), self.show_runners)

    def _poll_runners(self) -> None:
        if not self.isVisible() or not self.name:
            return
        name = self.name
        async_utils.run_in_background(lambda: self.connection.forgejo_runners(name),
                                      on_result=lambda runners: self._safe_show(name, runners),
                                      on_error=lambda _error: None)

    def _safe_show(self, name: str, runners: list[dict]) -> None:
        try:
            if name == self.name:
                self.show_runners(runners)
        except RuntimeError:
            pass

    def show_runners(self, runners: list[dict]) -> None:
        self.no_runners.setText("No runners yet. Workflows in .forgejo/workflows/ wait for one whose label matches "
                                "their runs-on:." if not runners else "")
        self.no_runners.setVisible(not runners)
        fill_table(self.runners, [
            [r["name"] + (f" {r['version']}" if r.get("version") else ""),
             ", ".join(label.split(":")[0] for label in r.get("labels") or []), r.get("capacity"), runner_status(r)]
            for r in runners
        ], runners)

    def _update(self) -> None:
        image = (self.site.get("container") or {}).get("image", "")
        if not _confirm(self, "Update Forgejo",
                        f"The newest image of {image} is pulled and Forgejo restarted with it; it upgrades its "
                        "database itself. The runners get their newest image too.\n\nTo move to a new major "
                        "version, change the image's tag under Container first. Take a backup before a major "
                        "upgrade.\n\nUpdate now?"):
            return
        name = self.name

        def done(result: dict) -> None:
            self.detail.show_site(result["site"])
            if result.get("version") == result.get("previous_version"):
                message = f"Forgejo {result.get('version')} is already the newest of its image's tag."
            else:
                message = f"Forgejo was updated from {result.get('previous_version')} to {result.get('version')}."
            if result.get("runners_error"):
                message += f"\n\nThe runners could not be updated:\n{result['runners_error']}"
            QMessageBox.information(self, "Update Forgejo", message)

        self.detail.busy(f"Updating Forgejo on {name}…", lambda: self.connection.app_update(name), done,
                         "Forgejo updated")

    def _create_admin(self) -> None:
        dialog = dialogs.AdminDialog("forgejo", self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        deploy_input, name = dialog.fields.deploy_input(), self.name
        self.detail.busy("Creating the Forgejo admin…", lambda: self.connection.app_deploy(name, deploy_input),
                         self.show_deployed, "Admin created")

    def _new_password(self) -> None:
        admin = (self.site.get("application") or {}).get("admin_user")
        if not _confirm(self, "New Admin Password", f"{admin} gets a new, generated password, and the module a new "
                                                    "access token for Forgejo's API.\n\nSet a new password?"):
            return
        name = self.name
        self.detail.busy("Setting a new admin password…", lambda: self.connection.forgejo_password(name),
                         lambda reply: self.show_new_password("New Admin Password", reply))

    def _add_runner(self) -> None:
        dialog = dialogs.AddRunnerDialog(self.name, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name, runner_name = self.name, dialog.runner_name.text().strip()
        labels, capacity = dialog.label_list(), dialog.capacity.value()

        def done(runners: list[dict]) -> None:
            self.warning.hide()
            self.show_runners(runners)

        self.detail.busy("Registering the runner and starting it…",
                         lambda: self.connection.forgejo_runner_add(name, runner_name, labels, capacity), done,
                         "Runner added")

    def _remove_runner(self) -> None:
        runner = selected_data(self.runners)
        if runner is None:
            self.detail.manager.flash("Select a runner first")
            return
        if not _confirm(self, "Remove Runner", f"Remove runner {runner['name']}? Its container stops and it is "
                                               "removed from Forgejo. A job it is running is cut short."):
            return
        name = self.name

        def done(reply: dict) -> None:
            self.show_runners(reply.get("runners") or [])
            self.warning.setText(reply.get("warning") or "")
            self.warning.setVisible(bool(reply.get("warning")))

        self.detail.busy(f"Removing runner {runner['name']}…",
                         lambda: self.connection.forgejo_runner_delete(name, runner["id"]), done, "Runner removed")


# -- Zabbix ---------------------------------------------------------------------------------------


def container_state(state: str | None) -> str:
    return "running" if state == "active" else (state or "unknown")


class ZabbixCard(_Card):
    def __init__(self, detail) -> None:
        super().__init__("Zabbix", detail)
        self.status: dict = {}
        self.info = _label()
        self.importing = _label()
        theme.set_tone(self.importing, "accent")
        self.update_button = _button("Update…", self._update)
        self.admin_button = _button("Set Admin Password…", self._set_admin)
        self.password_button = _button("New Password…", self._new_password)
        self.import_button = _button("Import from Another Zabbix Server…", self._import)
        layout = QVBoxLayout(self)
        layout.addWidget(self.importing)
        layout.addWidget(self.info)
        layout.addLayout(_row(self.update_button, self.admin_button, self.password_button, self.import_button))
        self._poll = QTimer(self)
        self._poll.setInterval(STATUS_POLL_MS)
        self._poll.timeout.connect(self._poll_status)

    def stop(self) -> None:
        self._poll.stop()

    def show_site(self, site: dict) -> None:
        changed = site.get("name") != self.name
        self.site = site
        if changed:
            self.status = {}
        self._show()
        if changed:
            self._poll_status(force=True)
        self._poll.start()

    def _poll_status(self, force: bool = False) -> None:
        if not self.name or not (force or self.isVisible()):
            return
        name = self.name

        def show(status: dict) -> None:
            try:
                if name == self.name:
                    self.status = status
                    self._show()
            except RuntimeError:
                pass

        async_utils.run_in_background(lambda: self.connection.zabbix_status(name), on_result=show,
                                      on_error=lambda _error: None)

    def _show(self) -> None:
        site, status = self.site, self.status
        app = site.get("application") or {}
        engine = hm.ZABBIX_ENGINE_LABELS.get(app.get("engine"), app.get("engine") or "")
        lines = [
            f"Version: {app.get('version') or (app.get('zabbix', '') + ' (not known yet)')}",
            f"Sign in: {site_base_url(site)}/" + (f" ({app['admin_user']})" if app.get("admin_user") else "")
            + (" — Admin still has the default password" if not app.get("admin_user") and not app.get("imported")
               else ""),
            (f"Agents and proxies: {site.get('primary_domain')}:{app.get('server_port')} (agents' ServerActive= "
             "and proxies' Server= point here; the port is opened in firewalld or ufw when one is on)"),
        ]
        if status:
            lines.append(f"Containers: server {container_state(status.get('zabbixserver'))}, database ({engine}) "
                         f"{container_state(status.get('zabbixdb'))}, "
                         f"frontend {container_state(site.get('app_state'))}")
            counts = status.get("counts")
            if counts:
                lines.append(f"{counts.get('hosts')} hosts, {counts.get('templates')} templates")
        imported = app.get("imported")
        if imported:
            lines.append(f"Imported from {imported.get('host')} (Zabbix "
                         f"{imported.get('server_version') or imported.get('release')}), {imported.get('at')}"
                         + ("" if imported.get("history") else " without history"))
        self.info.setText(info_html(lines))
        running = bool(status.get("import_running"))
        self.importing.setText("An import is running. Open the import to see its progress.")
        self.importing.setVisible(running)
        busy = bool(site.get("disabled")) or running
        has_password = bool(app.get("admin_user") or app.get("imported"))
        self.admin_button.setVisible(not has_password)
        self.password_button.setVisible(has_password)
        for button in (self.update_button, self.admin_button, self.password_button):
            button.setEnabled(not busy)
        self.import_button.setEnabled(not site.get("disabled"))

    def _update(self) -> None:
        current = (self.site.get("application") or {}).get("zabbix") or "7.0"
        dialog = dialogs.ZabbixUpdateDialog(current, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name, release = self.name, dialog.new_release()

        def done(result: dict) -> None:
            self.detail.show_site(result["site"])
            if result.get("version") == result.get("previous_version"):
                message = f"Zabbix {result.get('version')} is already the newest of its release."
            else:
                message = (f"Zabbix was updated from {result.get('previous_version') or current} to "
                           f"{result.get('version')}.")
            QMessageBox.information(self, "Update Zabbix", message)

        self.detail.busy(f"Updating Zabbix on {name}…", lambda: self.connection.zabbix_update(name, release), done,
                         "Zabbix updated")

    def _set_admin(self) -> None:
        dialog = dialogs.AdminDialog("zabbix", self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        deploy_input, name = dialog.fields.deploy_input(), self.name
        self.detail.busy("Setting Admin's password…", lambda: self.connection.app_deploy(name, deploy_input),
                         self.show_deployed, "Password set")

    def _new_password(self) -> None:
        user, ok = QInputDialog.getText(
            self, "New Password", "The Zabbix user gets a new, generated password, and is unblocked if too many "
                                  "wrong passwords blocked it.\n\nZabbix user:",
            text=(self.site.get("application") or {}).get("admin_user") or "Admin")
        if not ok or not user.strip():
            return
        name = self.name
        self.detail.busy("Setting a new password…", lambda: self.connection.zabbix_password(name, user.strip()),
                         lambda reply: self.show_new_password("New Password", reply))

    def _import(self) -> None:
        ZabbixImportDialog(self.connection, self.site, self).exec()
        self._poll_status(force=True)
        self.detail.load(self.name)

