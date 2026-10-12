"""One Restic Manager tab (Cockpit module): manages the restic backups of a
server running the user's cockpit-restic Cockpit module over SSH, with the
same features as that module's page -- installing restic, repositories
(local or SFTP) with health checks, stale-lock removal and snapshot
browse/restore/delete, and scheduled backup jobs with run now and run
history. See core/restic_manager.py for how it talks to the server.
"""

from __future__ import annotations

import html
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from it_toolbox.core import async_utils
from it_toolbox.core import restic_manager as rm
from it_toolbox.widgets import restic_dialogs as dialogs
from it_toolbox.widgets import status_bar
from it_toolbox.widgets.hosting_manager_widget import when_label
from it_toolbox.widgets.remote_helper_widget import (
    RemoteHelperTab,
    fill_table,
    make_table,
    selected_data,
)

TITLE = dialogs.TITLE
# While a job or check is running (or was just started), the lists refresh
# this often so its status updates in place, like the Cockpit page's.
POLL_INTERVAL_MS = 3000
POLL_AFTER_TRIGGER_SEC = 60
BANNER_STYLE = "QLabel { color: palette(text); background: rgba(201, 25, 11, 0.12); padding: 6px; }"


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


def _confirm(parent: QWidget, title: str, text: str) -> bool:
    return QMessageBox.question(parent, title, text) == QMessageBox.StandardButton.Yes


def _banner() -> QLabel:
    label = QLabel()
    label.setWordWrap(True)
    label.setStyleSheet(BANNER_STYLE)
    label.setTextFormat(Qt.TextFormat.RichText)
    label.hide()
    return label


def run_label(run: dict | None, never: str) -> str:
    """The page's RunStatusCell as text: "Failure, 2026-10-12 03:00"."""
    if not run:
        return never
    return f"{rm.run_status_label(run.get('status'))}, {when_label(run.get('started_at'))}"


class ResticManagerWidget(RemoteHelperTab):
    """Connects on construction, then shows the Repositories and Backup
    Jobs tabs -- or the install page when cockpit-restic isn't set up yet,
    or a page explaining that the module isn't installed."""

    TOOL_NAME = TITLE
    REPO_COLUMNS = ("Name", "Backend", "Location", "Last check", "Next check", "Status")
    JOB_COLUMNS = ("Name", "Repository", "Schedule", "Last run", "Next run", "Retention", "Status")

    def __init__(self, server: rm.ResticServer, connection_factory=rm.ResticConnection,
                 parent: QWidget | None = None, credentials: dict | None = None) -> None:
        super().__init__(server, connection_factory, parent, credentials)
        self.repos: list[dict] = []
        self.jobs: list[dict] = []
        self._loading = {"repos": False, "jobs": False}
        self._poll_until = 0.0

        self.missing_page = QLabel(
            "This server doesn't have the cockpit-restic module "
            f"({rm.HELPER_PATH}).\n\nInstall the cockpit-restic package (from the RPM registry on "
            "git.bonkcloud.lol), then click Reconnect."
        )
        self.missing_page.setWordWrap(True)
        self.missing_page.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stack.addWidget(self.missing_page)

        self.setup_page = self._build_setup_page()
        self.stack.addWidget(self.setup_page)

        self.server_label = QLabel()
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_repos_tab(), "Repositories")
        self.tabs.addTab(self._build_jobs_tab(), "Backup Jobs")
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.addWidget(self.server_label)
        page_layout.addWidget(self.tabs, 1)
        self.main_page = page
        self.stack.addWidget(page)

        self._poll = QTimer(self)
        self._poll.setInterval(POLL_INTERVAL_MS)
        self._poll.timeout.connect(self._tick)

        self.connect_to_server()

    def flash(self, message: str) -> None:
        status_bar.begin(self, message).finish(message)

    # -- Connecting / setup ------------------------------------------------------

    def before_reconnect(self) -> None:
        self._poll.stop()

    def on_connected(self) -> None:
        if self.connection.helper_path is None:
            self.stack.setCurrentWidget(self.missing_page)
            return
        self.show_message("Reading the server's status…")
        self.busy("Reading cockpit-restic status…", self.connection.status, self._on_status)

    def _on_status(self, status: dict) -> None:
        if not status.get("configured"):
            self.setup_error.hide()
            self.stack.setCurrentWidget(self.setup_page)
            return
        version = status.get("version") or ("restic is not installed" if not status.get("installed") else "restic")
        self.server_label.setText(f"{version} · next run/check times are in the server's time zone")
        self.stack.setCurrentWidget(self.main_page)
        self.refresh_repos()
        self.refresh_jobs()
        self._poll.start()

    def _build_setup_page(self) -> QWidget:
        page = QWidget()
        text = QLabel(
            "<b>Restic Backups</b><br><br>This machine doesn't have restic set up yet. Installing and "
            "configuring it will:<ul><li>Install the restic package (EPEL is required on AlmaLinux/RHEL)</li>"
            "<li>Create a directory for repository passwords and SSH keys, readable only by root</li>"
            "<li>Create the module's own local database of repositories, jobs and run history</li></ul>"
        )
        text.setWordWrap(True)
        self.setup_button = _button("Install && Configure restic", self.run_setup)
        self.setup_error = QLabel()
        self.setup_error.setWordWrap(True)
        self.setup_error.setStyleSheet(BANNER_STYLE)
        self.setup_error.hide()
        layout = QVBoxLayout(page)
        layout.addWidget(text)
        layout.addWidget(self.setup_error)
        layout.addLayout(_row(self.setup_button))
        layout.addStretch(1)
        return page

    def run_setup(self) -> None:
        self.setup_button.setEnabled(False)
        self.setup_error.hide()

        def done(status: dict) -> None:
            self.setup_button.setEnabled(True)
            if status.get("configured"):
                self._on_status(status)
            else:
                self._setup_failed("Setup finished, but restic still isn't reporting as configured.")

        def failed(error: Exception) -> None:
            self.setup_button.setEnabled(True)
            self._setup_failed(str(error))

        task = status_bar.begin(self, "Installing and configuring restic…")
        async_utils.run_in_background(
            self.connection.setup,
            on_result=lambda s: (task.finish("restic is set up"), _safe(done, s)),
            on_error=lambda e: (task.finish(), _safe(failed, e)),
        )

    def _setup_failed(self, message: str) -> None:
        self.setup_error.setText(f"Setup failed: {message}")
        self.setup_error.show()

    # -- Polling ---------------------------------------------------------------------

    def _poll_soon(self) -> None:
        self._poll_until = time.monotonic() + POLL_AFTER_TRIGGER_SEC

    def _tick(self) -> None:
        if self.connection is None or not self.isVisible():
            return
        recent = time.monotonic() < self._poll_until
        if recent or rm.any_running(self.repos, "last_check"):
            self.refresh_repos(quiet=True)
        if recent or rm.any_running(self.jobs, "last_run"):
            self.refresh_jobs(quiet=True)

    def _refresh(self, kind: str, load, show, quiet: bool, message: str) -> None:
        if self._loading[kind] or self.connection is None:
            return
        self._loading[kind] = True

        def done(items):
            self._loading[kind] = False
            show(items)

        def failed(_error):
            self._loading[kind] = False

        if quiet:
            async_utils.run_in_background(load, on_result=lambda v: _safe(done, v),
                                          on_error=lambda e: _safe(failed, e))
        else:
            self.busy(message, load, done, on_error=failed)

    # -- Repositories --------------------------------------------------------------------

    def _build_repos_tab(self) -> QWidget:
        page = QWidget()
        self.repo_banner = _banner()
        self.repo_banner.linkActivated.connect(self._on_unlock_link)
        self.repo_table = make_table(list(self.REPO_COLUMNS))
        self.repo_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.repo_table.customContextMenuRequested.connect(self._repos_menu)
        self.repo_table.doubleClicked.connect(lambda _: self.browse_snapshots(self.selected_repo()))
        self.repo_table.itemSelectionChanged.connect(self._sync_repo_buttons)
        self.init_button = _button("Initialize", lambda: self.init_repo(self.selected_repo()))
        self.repo_buttons = [
            _button("Snapshots…", lambda: self.browse_snapshots(self.selected_repo())),
            _button("Check Now", lambda: self.check_now(self.selected_repo())),
            _button("Check History…", lambda: self.show_checks(self.selected_repo())),
            _button("Health Checks…", lambda: self.edit_health_checks(self.selected_repo())),
            _button("Remove Stale Locks", lambda: self.unlock(self.selected_repo())),
        ]
        self.delete_repo_button = _button("Delete", lambda: self.delete_repo(self.selected_repo()))
        layout = QVBoxLayout(page)
        layout.addLayout(_row(_button("Create Repository…", self.create_repo), _button("Refresh", self.refresh_repos),
                              self.init_button, *self.repo_buttons, self.delete_repo_button))
        layout.addWidget(self.repo_banner)
        layout.addWidget(self.repo_table, 1)
        self._sync_repo_buttons()
        return page

    def selected_repo(self) -> dict | None:
        repo_id = selected_data(self.repo_table)
        return next((r for r in self.repos if r["id"] == repo_id), None)

    def repo_name(self, repo_id: str) -> str:
        return next((r["name"] for r in self.repos if r["id"] == repo_id), repo_id)

    def _sync_repo_buttons(self) -> None:
        repo = self.selected_repo()
        initialized = bool(repo and repo.get("initialized"))
        self.init_button.setVisible(repo is not None and not initialized)
        for button in self.repo_buttons:
            button.setEnabled(initialized)
        self.delete_repo_button.setEnabled(repo is not None)

    def refresh_repos(self, quiet: bool = False) -> None:
        self._refresh("repos", self.connection.list_repos if self.connection else None, self.show_repos, quiet,
                      "Loading repositories…")

    def _repo_row(self, repo: dict) -> list:
        initialized = repo.get("initialized")
        return [
            repo["name"],
            rm.BACKEND_LABELS.get(repo.get("backend"), repo.get("backend", "")),
            rm.location_label(repo),
            run_label(repo.get("last_check"), "Never checked") if initialized else "-",
            repo.get("next_check") or "-",
            "Ready" if initialized else "Needs key authorized on remote",
        ]

    def show_repos(self, repos: list[dict]) -> None:
        selected = selected_data(self.repo_table)
        self.repos = repos
        self.repo_table.blockSignals(True)
        fill_table(self.repo_table, [self._repo_row(r) for r in repos], [r["id"] for r in repos])
        ids = [r["id"] for r in repos]
        if selected in ids:
            self.repo_table.selectRow(ids.index(selected))
        self.repo_table.blockSignals(False)
        self._sync_repo_buttons()
        self._show_repo_banner()
        self._sync_job_create()
        if self.jobs:
            self.show_jobs(self.jobs)  # repository names

    def _show_repo_banner(self) -> None:
        failed = rm.failed_names(self.repos, "last_check")
        if not failed:
            self.repo_banner.hide()
            return
        noun = "repository failed its last check" if len(failed) == 1 else "repositories failed their last check"
        parts = [f"<b>{len(failed)} {noun}:</b> {html.escape(', '.join(failed))}"]
        for repo in self.repos:
            if (repo.get("last_check") or {}).get("blocked_by_lock"):
                parts.append(
                    f"The last check of {html.escape(repo['name'])} could not run because the repository is "
                    "locked. If no backup is running right now, the lock is stale and safe to remove. "
                    f"<a href=\"unlock:{html.escape(repo['id'])}\">Remove stale locks</a>"
                )
        self.repo_banner.setText("<br>".join(parts))
        self.repo_banner.show()

    def _on_unlock_link(self, link: str) -> None:
        if link.startswith("unlock:"):
            repo_id = link.split(":", 1)[1]
            self.unlock(next((r for r in self.repos if r["id"] == repo_id), {"id": repo_id, "name": repo_id}))

    def _repos_menu(self, pos) -> None:
        repo = self.selected_repo()
        menu = QMenu(self)
        if repo is not None:
            if not repo.get("initialized"):
                menu.addAction("Initialize").triggered.connect(lambda: self.init_repo(repo))
            else:
                menu.addAction("Browse Snapshots…").triggered.connect(lambda: self.browse_snapshots(repo))
                menu.addAction("Check Now").triggered.connect(lambda: self.check_now(repo))
                menu.addAction("Check History…").triggered.connect(lambda: self.show_checks(repo))
                menu.addAction("Health Check Settings…").triggered.connect(lambda: self.edit_health_checks(repo))
                menu.addAction("Remove Stale Locks").triggered.connect(lambda: self.unlock(repo))
            menu.addSeparator()
            menu.addAction("Delete").triggered.connect(lambda: self.delete_repo(repo))
            menu.addSeparator()
        menu.addAction("Create Repository…").triggered.connect(self.create_repo)
        menu.exec(self.repo_table.viewport().mapToGlobal(pos))

    def create_repo(self) -> None:
        dialog = dialogs.RepoDialog(parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()

        def created(result: dict) -> None:
            self.refresh_repos()
            if result.get("generated_password") or result.get("public_key"):
                dialogs.SecretsDialog(result, parent=self).exec()

        self.busy(f"Creating {values['name']}…", lambda: self.connection.create_repo(**values), created,
                  done_message="Repository created")

    def init_repo(self, repo: dict | None) -> None:
        if repo is None:
            return
        repo_id = repo["id"]
        self.busy(f"Initializing {repo['name']}…", lambda: self.connection.init_repo(repo_id),
                  lambda _: self.refresh_repos(), done_message="Repository initialized")

    def check_now(self, repo: dict | None) -> None:
        if repo is None:
            return
        repo_id = repo["id"]

        def started(_):
            self._poll_soon()
            self.flash(f"Started a check of {repo['name']} — its status updates as it runs.")
            self.refresh_repos()

        self.busy(f"Starting a check of {repo['name']}…", lambda: self.connection.trigger_check(repo_id), started)

    def show_checks(self, repo: dict | None) -> None:
        if repo is None:
            return
        connection, repo_id = self.connection, repo["id"]
        dialogs.RunsDialog(
            f"Check History — {repo['name']}",
            'This repository hasn\'t been checked yet — use "Check Now" or schedule one under Health Checks.',
            lambda: connection.list_repo_checks(repo_id), parent=self,
        ).exec()

    def edit_health_checks(self, repo: dict | None) -> None:
        if repo is None:
            return
        dialog = dialogs.HealthCheckDialog(repo, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values, repo_id = dialog.values(), repo["id"]
        self.busy(f"Saving {repo['name']}…", lambda: self.connection.update_repo(repo_id, **values),
                  lambda _: self.refresh_repos(), done_message="Saved")

    def unlock(self, repo: dict | None) -> None:
        if repo is None:
            return
        repo_id = repo["id"]

        def done(result: dict) -> None:
            output = (result.get("output") or "").strip()
            self.flash(f"Removed stale locks from {repo['name']}" + (f": {output}" if output else ""))
            self.refresh_repos()
            self.refresh_jobs()

        self.busy(f"Removing stale locks from {repo['name']}…", lambda: self.connection.unlock_repo(repo_id), done)

    def delete_repo(self, repo: dict | None) -> None:
        if repo is None or not _confirm(
                self, "Delete Repository",
                f"Delete repository {repo['name']}? The backups at its location are left alone, but the "
                "server forgets the repository and deletes its stored password (and SSH key). Make sure you "
                "have the password saved if you will need these backups."):
            return
        repo_id = repo["id"]
        self.busy(f"Deleting {repo['name']}…", lambda: self.connection.delete_repo(repo_id),
                  lambda _: self.refresh_repos(), done_message="Repository deleted")

    def browse_snapshots(self, repo: dict | None) -> None:
        if repo is not None and repo.get("initialized"):
            dialogs.SnapshotsDialog(self.connection, repo, parent=self).exec()

    # -- Backup jobs ------------------------------------------------------------------------

    def _build_jobs_tab(self) -> QWidget:
        page = QWidget()
        self.job_banner = _banner()
        self.job_banner.linkActivated.connect(self._on_unlock_link)
        self.no_repo_note = QLabel("Create and initialize a repository first.")
        self.job_table = make_table(list(self.JOB_COLUMNS))
        self.job_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.job_table.customContextMenuRequested.connect(self._jobs_menu)
        self.job_table.doubleClicked.connect(lambda _: self.edit_job(self.selected_job()))
        self.job_table.itemSelectionChanged.connect(self._sync_job_buttons)
        self.create_job_button = _button("Create Backup Job…", self.create_job)
        self.job_buttons = [
            _button("Run Now", lambda: self.run_job(self.selected_job())),
            _button("Edit…", lambda: self.edit_job(self.selected_job())),
            _button("Run History…", lambda: self.show_runs(self.selected_job())),
            _button("Delete", lambda: self.delete_job(self.selected_job())),
        ]
        layout = QVBoxLayout(page)
        layout.addLayout(_row(self.create_job_button, _button("Refresh", self.refresh_jobs), *self.job_buttons))
        layout.addWidget(self.no_repo_note)
        layout.addWidget(self.job_banner)
        layout.addWidget(self.job_table, 1)
        self._sync_job_buttons()
        self._sync_job_create()
        return page

    def initialized_repos(self) -> list[dict]:
        return [r for r in self.repos if r.get("initialized")]

    def _sync_job_create(self) -> None:
        has_repo = bool(self.initialized_repos())
        self.create_job_button.setEnabled(has_repo)
        self.no_repo_note.setVisible(not has_repo)

    def selected_job(self) -> dict | None:
        job_id = selected_data(self.job_table)
        return next((j for j in self.jobs if j["id"] == job_id), None)

    def _sync_job_buttons(self) -> None:
        job = self.selected_job()
        for button in self.job_buttons:
            button.setEnabled(job is not None)
        if job is not None:
            self.job_buttons[0].setEnabled((job.get("last_run") or {}).get("status") != "running")

    def refresh_jobs(self, quiet: bool = False) -> None:
        self._refresh("jobs", self.connection.list_jobs if self.connection else None, self.show_jobs, quiet,
                      "Loading backup jobs…")

    def _job_row(self, job: dict) -> list:
        return [
            job["name"],
            self.repo_name(job.get("repo_id", "")),
            rm.schedule_label(job.get("schedule", "")),
            run_label(job.get("last_run"), "Never run"),
            (job.get("next_run") or "-") if job.get("enabled") else "-",
            rm.retention_label(job),
            "Enabled" if job.get("enabled") else "Disabled",
        ]

    def show_jobs(self, jobs: list[dict]) -> None:
        selected = selected_data(self.job_table)
        self.jobs = jobs
        self.job_table.blockSignals(True)
        fill_table(self.job_table, [self._job_row(j) for j in jobs], [j["id"] for j in jobs])
        for row, job in enumerate(jobs):
            self.job_table.item(row, 0).setToolTip("\n".join(job.get("source_paths", [])))
        ids = [j["id"] for j in jobs]
        if selected in ids:
            self.job_table.selectRow(ids.index(selected))
        self.job_table.blockSignals(False)
        self._sync_job_buttons()
        self._show_job_banner()

    def _show_job_banner(self) -> None:
        failed = rm.failed_names(self.jobs, "last_run")
        if not failed:
            self.job_banner.hide()
            return
        noun = "backup job failed on its last run" if len(failed) == 1 else "backup jobs failed on their last run"
        parts = [f"<b>{len(failed)} {noun}:</b> {html.escape(', '.join(failed))}"]
        locked: dict[str, list[str]] = {}
        for job in self.jobs:
            if (job.get("last_run") or {}).get("blocked_by_lock"):
                locked.setdefault(job.get("repo_id", ""), []).append(job["name"])
        for repo_id, names in locked.items():
            parts.append(
                f"{html.escape(', '.join(names))} could not finish because repository "
                f"{html.escape(self.repo_name(repo_id))} is locked. If no backup is running right now, the lock is "
                f"stale and safe to remove. <a href=\"unlock:{html.escape(repo_id)}\">Remove stale locks</a>"
            )
        self.job_banner.setText("<br>".join(parts))
        self.job_banner.show()

    def _jobs_menu(self, pos) -> None:
        job = self.selected_job()
        menu = QMenu(self)
        if job is not None:
            run = menu.addAction("Run Now")
            run.setEnabled((job.get("last_run") or {}).get("status") != "running")
            run.triggered.connect(lambda: self.run_job(job))
            menu.addAction("Edit…").triggered.connect(lambda: self.edit_job(job))
            menu.addAction("Run History…").triggered.connect(lambda: self.show_runs(job))
            menu.addSeparator()
            menu.addAction("Delete").triggered.connect(lambda: self.delete_job(job))
            menu.addSeparator()
        create = menu.addAction("Create Backup Job…")
        create.setEnabled(bool(self.initialized_repos()))
        create.triggered.connect(self.create_job)
        menu.exec(self.job_table.viewport().mapToGlobal(pos))

    def _open_job_dialog(self, job: dict | None) -> None:
        dialog = dialogs.JobDialog(job, self.initialized_repos(), parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        if job is not None:
            job_id = job["id"]
            self.busy(f"Saving {values['name']}…", lambda: self.connection.update_job(job_id, values),
                      lambda _: self.refresh_jobs(), done_message="Saved")
        else:
            self.busy(f"Creating {values['name']}…", lambda: self.connection.create_job(values),
                      lambda _: self.refresh_jobs(), done_message="Backup job created")

    def create_job(self) -> None:
        if self.initialized_repos():
            self._open_job_dialog(None)

    def edit_job(self, job: dict | None) -> None:
        if job is not None:
            self._open_job_dialog(job)

    def run_job(self, job: dict | None) -> None:
        if job is None:
            return
        job_id = job["id"]

        def started(_):
            self._poll_soon()
            self.flash(f"Started {job['name']} — its status updates as it runs.")
            self.refresh_jobs()

        self.busy(f"Starting {job['name']}…", lambda: self.connection.trigger_job(job_id), started)

    def show_runs(self, job: dict | None) -> None:
        if job is None:
            return
        connection, job_id = self.connection, job["id"]
        dialogs.RunsDialog(
            f"Run History — {job['name']}",
            'This job hasn\'t run yet — use "Run Now" or wait for its schedule.',
            lambda: connection.list_job_runs(job_id), parent=self,
        ).exec()

    def delete_job(self, job: dict | None) -> None:
        if job is None or not _confirm(
                self, "Delete Backup Job", f"Delete backup job {job['name']}? This also removes its scheduled "
                                           "timer. Existing snapshots stay in the repository."):
            return
        job_id = job["id"]
        self.busy(f"Deleting {job['name']}…", lambda: self.connection.delete_job(job_id),
                  lambda _: self.refresh_jobs(), done_message="Backup job deleted")


def _safe(fn, value) -> None:
    try:
        fn(value)
    except RuntimeError:
        pass  # widget closed while the call was running
