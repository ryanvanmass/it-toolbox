"""Remote management of the backups of the user's cockpit-restic Cockpit
module, for the Restic Manager (Cockpit module).

Everything is done by the module's own privileged helper
(`cockpit-restic-helper <subcommand>`, JSON in, one JSON object out),
called over SSH exactly the way the Cockpit page's src/helper.ts calls it,
so both UIs share the module's database, secrets and generated systemd
units. As with the Scheduler Manager there is no bundled copy of the
helper: the job and check units it writes run its installed path, so the
module itself must be installed on the server.

The connection methods mirror helper.ts's `helper` object one to one; the
module-level functions are small ports of the page's display helpers
(RunStatus.tsx, ReposPage/JobsPage labels, RestoreDialog's path list).
"""

from __future__ import annotations

from it_toolbox.core.remote_helper import (
    RemoteHelperConnection,
    RemoteHelperError,
    RemoteServer,
)

HELPER_PATH = "/usr/libexec/cockpit-restic/cockpit-restic-helper"

#: setup (a dnf install), restore and forget --prune can take a long time
#: on a big or remote repository.
SLOW_TIMEOUT = 45 * 60

BACKENDS = ["local", "sftp"]
BACKEND_LABELS = {"local": "Local", "sftp": "SFTP"}

#: The page's schedule presets (systemd OnCalendar= shorthands).
SCHEDULE_PRESETS = {"hourly": "Hourly", "daily": "Daily", "weekly": "Weekly", "monthly": "Monthly"}

RUN_STATUS_LABELS = {"success": "Success", "failure": "Failure", "running": "Running"}

DEFAULT_RESTORE_TARGET = "/var/restore"
DEFAULT_RETENTION = {"keep_daily": 7, "keep_weekly": 4, "keep_monthly": 6, "keep_yearly": 0}

ResticError = RemoteHelperError


class ResticServer(RemoteServer):
    """A machine running cockpit-restic, as the Restic Manager tab takes it."""


def _drop_none(args: dict) -> dict:
    """helper.ts leaves out `undefined` options, which the helper reads as
    "keep the current value"; None plays that part here."""
    return {key: value for key, value in args.items() if value is not None}


class ResticConnection(RemoteHelperConnection):
    HELPER_PATHS = (HELPER_PATH,)
    MODULE_NAME = "cockpit-restic"

    def status(self) -> dict:
        return self.call("status")

    def setup(self) -> dict:
        """Installs restic (dnf) and creates the module's database."""
        return self.call("setup", timeout=SLOW_TIMEOUT)

    # -- Repositories -------------------------------------------------------

    def list_repos(self) -> list[dict]:
        return self.call("list-repos").get("repos", [])

    def create_repo(
        self,
        name: str,
        backend: str,
        *,
        path: str | None = None,
        host: str | None = None,
        port: int | None = None,
        remote_path: str | None = None,
        user: str | None = None,
        password: str | None = None,
    ) -> dict:
        """{"repo", "generated_password"?, "public_key"?} -- the password
        and key are only ever returned here."""
        args = {"name": name, "backend": backend, "path": path, "host": host, "port": port,
                "remote_path": remote_path, "user": user, "password": password or None}
        return self.call("create-repo", _drop_none(args), timeout=SLOW_TIMEOUT)

    def init_repo(self, repo_id: str) -> dict:
        return self.call("init-repo", {"id": repo_id}, timeout=SLOW_TIMEOUT)["repo"]

    def update_repo(
        self,
        repo_id: str,
        *,
        name: str | None = None,
        check_schedule: str | None = None,
        check_read_data: int | None = None,
        healthcheck_url: str | None = None,
    ) -> dict:
        """check_schedule "" turns scheduled checks off; None keeps it."""
        args = {"id": repo_id, "name": name, "check_schedule": check_schedule,
                "check_read_data": check_read_data, "healthcheck_url": healthcheck_url}
        return self.call("update-repo", _drop_none(args))["repo"]

    def delete_repo(self, repo_id: str) -> dict:
        return self.call("delete-repo", {"id": repo_id})

    def trigger_check(self, repo_id: str) -> dict:
        """Starts the repository's check unit and returns at once."""
        return self.call("trigger-check", {"repo_id": repo_id})

    def list_repo_checks(self, repo_id: str) -> list[dict]:
        return self.call("list-repo-checks", {"repo_id": repo_id}).get("checks", [])

    def unlock_repo(self, repo_id: str) -> dict:
        """Removes stale locks only, never a running backup's lock."""
        return self.call("unlock-repo", {"repo_id": repo_id}, timeout=SLOW_TIMEOUT)

    def repo_stats(self, repo_id: str) -> dict:
        return self.call("repo-stats", {"repo_id": repo_id}, timeout=SLOW_TIMEOUT)

    # -- Backup jobs ----------------------------------------------------------

    def list_jobs(self) -> list[dict]:
        return self.call("list-jobs").get("jobs", [])

    def create_job(self, job_input: dict) -> dict:
        return self.call("create-job", _drop_none(job_input))["job"]

    def update_job(self, job_id: str, job_input: dict) -> dict:
        return self.call("update-job", _drop_none({"id": job_id, **job_input}))["job"]

    def delete_job(self, job_id: str) -> dict:
        return self.call("delete-job", {"id": job_id})

    def trigger_job(self, job_id: str) -> dict:
        return self.call("trigger-job", {"id": job_id})

    def list_job_runs(self, job_id: str) -> list[dict]:
        return self.call("list-job-runs", {"job_id": job_id}).get("runs", [])

    # -- Snapshots ------------------------------------------------------------

    def list_snapshots(self, repo_id: str) -> list[dict]:
        return self.call("list-snapshots", {"repo_id": repo_id}, timeout=SLOW_TIMEOUT).get("snapshots", [])

    def list_snapshot_files(self, repo_id: str, snapshot_id: str, path: str = "/") -> list[dict]:
        """The direct children of one directory of a snapshot, folders first."""
        args = {"repo_id": repo_id, "snapshot_id": snapshot_id, "path": path}
        return self.call("list-snapshot-files", args, timeout=SLOW_TIMEOUT).get("files", [])

    def find_snapshot_files(self, repo_id: str, snapshot_id: str, pattern: str) -> dict:
        """{"matches": [...], "truncated": bool}; `*` and `?` are wildcards."""
        args = {"repo_id": repo_id, "snapshot_id": snapshot_id, "pattern": pattern}
        return self.call("find-snapshot-files", args, timeout=SLOW_TIMEOUT)

    def forget_snapshots(self, repo_id: str, snapshot_ids: list[str]) -> dict:
        """Permanently deletes the snapshots and prunes data only they used."""
        args = {"repo_id": repo_id, "snapshot_ids": snapshot_ids}
        return self.call("forget-snapshots", args, timeout=SLOW_TIMEOUT)

    def restore_snapshot(self, repo_id: str, snapshot_id: str, target: str,
                         include_paths: list[str] | None = None) -> dict:
        args = {"repo_id": repo_id, "snapshot_id": snapshot_id, "target": target,
                "include_paths": include_paths or []}
        return self.call("restore-snapshot", args, timeout=SLOW_TIMEOUT)


# -- Display helpers ----------------------------------------------------------------


def location_label(repo: dict) -> str:
    if repo.get("backend") == "local":
        return repo.get("path") or ""
    return f"{repo.get('user', '')}@{repo.get('host', '')}:{repo.get('remote_path', '')}"


def retention_label(job: dict) -> str:
    return (f"{job.get('keep_daily', 0)} daily, {job.get('keep_weekly', 0)} weekly, "
            f"{job.get('keep_monthly', 0)} monthly, {job.get('keep_yearly', 0)} yearly")


def schedule_label(schedule: str) -> str:
    return SCHEDULE_PRESETS.get(schedule, schedule)


def run_status_label(status: str | None) -> str:
    return RUN_STATUS_LABELS.get(status or "", status or "")


def failed_names(items: list[dict], last_run_key: str) -> list[str]:
    """Names of the jobs/repos whose most recent run (`last_run` /
    `last_check`) failed, for the failure banners."""
    return [item["name"] for item in items if (item.get(last_run_key) or {}).get("status") == "failure"]


def any_running(items: list[dict], last_run_key: str) -> bool:
    return any((item.get(last_run_key) or {}).get("status") == "running" for item in items)


# -- Restore path selection (RestoreDialog.tsx) ---------------------------------------


def path_lines(text: str) -> list[str]:
    """One path per line, as typed."""
    return [line.strip() for line in text.splitlines() if line.strip()]


def normalize_path(path: str) -> str:
    """A trailing slash means the same as none."""
    return path.rstrip("/") or "/"


def toggle_path(lines: list[str], path: str, checked: bool) -> list[str]:
    """Adds or removes `path` from the restore list. Choosing a folder
    covers everything inside it, so earlier choices from within it are
    dropped rather than listed twice."""
    others = [line for line in lines if normalize_path(line) != path]
    if not checked:
        return others
    prefix = "/" if path == "/" else path + "/"
    return [line for line in others if not normalize_path(line).startswith(prefix)] + [path]


def covered_by(path: str, selected: list[str]) -> str | None:
    """The selected folder that already includes `path`, if any."""
    for folder in selected:
        prefix = "/" if folder == "/" else folder + "/"
        if folder != path and path.startswith(prefix):
            return folder
    return None
