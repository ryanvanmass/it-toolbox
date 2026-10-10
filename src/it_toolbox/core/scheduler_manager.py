"""Remote management of the automated tasks of the user's cockpit-scheduler
Cockpit module, for the General Tools Scheduler Manager.

Everything is done by the module's own privileged helper
(`cockpit-scheduler-helper <subcommand>`, JSON in, one JSON object out),
called over SSH exactly the way the Cockpit page's src/helper.ts calls it,
so both UIs share the module's SQLite database and generated systemd
units. As with the Hosting Manager there is no bundled copy of the
helper: it bakes its own installed path into the units it writes, so the
module itself must be installed on the server.

The connection methods mirror helper.ts's `helper` object one to one; the
module-level functions are Python ports of the page's pure helpers
(src/schedule.ts, src/shebang.ts, src/command.ts, src/notify.ts), so a
task edited here reads back the same way in Cockpit and vice versa.
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass, field

from it_toolbox.core.remote_helper import (
    RemoteHelperConnection,
    RemoteHelperError,
    RemoteServer,
)

HELPER_PATH = "/usr/libexec/cockpit-scheduler/cockpit-scheduler-helper"

TASK_KINDS = ["inline", "path"]

CHANNEL_TYPES = ["webhook", "googlechat", "healthchecks"]
CHANNEL_TYPE_LABELS = {"webhook": "Webhook", "googlechat": "Google Chat", "healthchecks": "Healthchecks.io"}

NOTIFY_EVENTS = ["failure", "recovery", "success", "missed"]
EVENT_WORDS = {"failure": "failure", "recovery": "recovery", "success": "success", "missed": "missed run"}
EVENT_LABELS = {
    "failure": "The task fails (non-zero exit, timeout or killed)",
    "recovery": "The task recovers (its first success after failing)",
    "success": "Every successful run",
    "missed": "A run is missed (the task didn't start when it was due)",
}
DEFAULT_EVENTS = ["failure"]

RUN_STATUS_LABELS = {
    "success": "Succeeded",
    "failed": "Failed",
    "running": "Running",
    "interrupted": "Interrupted",
}

# The helper's own limits (see its constants), checked here only so a
# dialog can say so before the round trip.
MAX_TIMEOUT_SEC = 7 * 24 * 3600
MAX_RETRIES = 10
MAX_RETRY_DELAY_SEC = 24 * 3600
MIN_MISSED_GRACE_MIN = 1
MAX_MISSED_GRACE_MIN = 24 * 60
MAX_BACKUP_RETENTION = 365
DEFAULT_BACKUP_DIR = "/var/backups/cockpit-scheduler"

SLUG_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")


SchedulerError = RemoteHelperError


class SchedulerServer(RemoteServer):
    """A server saved in the Scheduler Manager's sidebar."""


class SchedulerConnection(RemoteHelperConnection):
    HELPER_PATHS = (HELPER_PATH,)
    MODULE_NAME = "cockpit-scheduler"

    def status(self) -> dict:
        return self.call("status")

    def dialog_data(self) -> dict:
        """Users, shells and channels in one call -- what the task dialog needs."""
        return self.call("dialog-data")

    def validate_schedule(self, schedule: str) -> dict:
        return self.call("validate-schedule", {"schedule": schedule})

    # -- Tasks ------------------------------------------------------------

    def list_tasks(self) -> list[dict]:
        return self.call("list-tasks").get("tasks", [])

    def get_task(self, task_id: str) -> dict:
        return self.call("get-task", {"id": task_id})["task"]

    def create_task(self, task_input: dict) -> dict:
        return self.call("create-task", task_input)["task"]

    def update_task(self, task_id: str, task_input: dict) -> dict:
        return self.call("update-task", {"id": task_id, **task_input})["task"]

    def set_enabled(self, task_id: str, enabled: bool) -> dict:
        return self.call("set-enabled", {"id": task_id, "enabled": enabled})["task"]

    def delete_task(self, task_id: str) -> dict:
        return self.call("delete-task", {"id": task_id})

    def trigger_task(self, task_id: str) -> dict:
        return self.call("trigger-task", {"id": task_id})

    def list_task_runs(self, task_id: str) -> list[dict]:
        return self.call("list-task-runs", {"id": task_id}).get("runs", [])

    def get_task_logs(self, task_id: str, invocation_id: str | None = None) -> list[dict]:
        args = {"id": task_id}
        if invocation_id:
            args["invocation_id"] = invocation_id
        return self.call("get-task-logs", args).get("lines", [])

    # -- Notification channels --------------------------------------------

    def list_channels(self) -> list[dict]:
        return self.call("list-channels").get("channels", [])

    def create_channel(self, name: str, channel_type: str, url: str, headers: dict | None = None) -> dict:
        args = {"name": name, "type": channel_type, "url": url}
        if headers is not None:
            args["headers"] = headers
        return self.call("create-channel", args)["channel"]

    def update_channel(self, channel_id: str, name: str, url: str, headers: dict | None = None) -> dict:
        args = {"id": channel_id, "name": name, "url": url}
        if headers is not None:
            args["headers"] = headers
        return self.call("update-channel", args)["channel"]

    def delete_channel(self, channel_id: str) -> dict:
        return self.call("delete-channel", {"id": channel_id})

    def test_channel(self, channel_id: str) -> dict:
        return self.call("test-channel", {"id": channel_id})

    # -- Export, import and backups -----------------------------------------

    def export_config(self, include_secrets: bool) -> dict:
        return self.call("export-config", {"include_secrets": include_secrets})

    def preview_import(self, source: dict, mode: str, channel_urls: dict, import_paused: bool) -> dict:
        return self.call("preview-import", _import_args(source, mode, channel_urls, import_paused))["plan"]

    def apply_import(self, source: dict, mode: str, channel_urls: dict, import_paused: bool) -> dict:
        return self.call("apply-import", _import_args(source, mode, channel_urls, import_paused))

    def get_backup_settings(self) -> dict:
        return self.call("get-backup-settings")

    def set_backup_settings(self, settings: dict) -> dict:
        return self.call("set-backup-settings", settings)

    def backup_now(self) -> dict:
        return self.call("backup-now")

    def list_backups(self) -> dict:
        return self.call("list-backups")

    def get_backup(self, name: str) -> dict:
        return self.call("get-backup", {"name": name})

    def delete_backup(self, name: str) -> dict:
        return self.call("delete-backup", {"name": name})


def _import_args(source: dict, mode: str, channel_urls: dict, import_paused: bool) -> dict:
    """`source` is {"document": {...}} (an uploaded file) or {"backup": name}."""
    return {
        **{key: value for key, value in source.items() if key in ("document", "backup")},
        "mode": mode,
        "channel_urls": channel_urls,
        "import_paused": import_paused,
    }


# -- Schedules (src/schedule.ts) ----------------------------------------------

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
SCHEDULE_KINDS = ["hourly", "interval", "daily", "weekly", "monthly", "custom"]
SCHEDULE_KIND_LABELS = {
    "hourly": "Hourly",
    "interval": "Every N hours",
    "daily": "Daily",
    "weekly": "Weekly",
    "monthly": "Monthly",
    "custom": "Custom (systemd calendar expression)",
}


@dataclass
class ScheduleSpec:
    """One of the Cockpit page's schedule presets, or a custom expression.
    Only the fields the kind uses matter."""

    kind: str
    minute: int = 0
    hour: int = 3
    hours: int = 6
    days: list[str] = field(default_factory=lambda: ["Mon"])
    day: int = 1
    expression: str = ""


def _pad2(n: int) -> str:
    return f"{n:02d}"


_DAY = "|".join(WEEKDAYS)
_HOURLY_RE = re.compile(r"^\*-\*-\* \*:(\d\d):00$")
_INTERVAL_RE = re.compile(r"^\*-\*-\* 0/(\d{1,2}):(\d\d):00$")
_DAILY_RE = re.compile(r"^\*-\*-\* (\d\d):(\d\d):00$")
_WEEKLY_RE = re.compile(rf"^((?:{_DAY})(?:,(?:{_DAY}))*) \*-\*-\* (\d\d):(\d\d):00$")
_MONTHLY_RE = re.compile(r"^\*-\*-(\d\d) (\d\d):(\d\d):00$")


def serialize_schedule(spec: ScheduleSpec) -> str:
    if spec.kind == "hourly":
        return f"*-*-* *:{_pad2(spec.minute)}:00"
    if spec.kind == "interval":
        return f"*-*-* 0/{spec.hours}:{_pad2(spec.minute)}:00"
    if spec.kind == "daily":
        return f"*-*-* {_pad2(spec.hour)}:{_pad2(spec.minute)}:00"
    if spec.kind == "weekly":
        days = [day for day in WEEKDAYS if day in spec.days]
        if not days:
            return ""
        return f"{','.join(days)} *-*-* {_pad2(spec.hour)}:{_pad2(spec.minute)}:00"
    if spec.kind == "monthly":
        return f"*-*-{_pad2(spec.day)} {_pad2(spec.hour)}:{_pad2(spec.minute)}:00"
    return spec.expression.strip()


def parse_schedule(expression: str) -> ScheduleSpec:
    """The preset an OnCalendar= expression is exactly in the canonical form
    of, else 'custom' with the expression unchanged."""
    text = expression.strip()
    shorthand = {
        "hourly": ScheduleSpec("hourly", minute=0),
        "daily": ScheduleSpec("daily", hour=0, minute=0),
        "weekly": ScheduleSpec("weekly", days=["Mon"], hour=0, minute=0),
        "monthly": ScheduleSpec("monthly", day=1, hour=0, minute=0),
    }
    if text in shorthand:
        return shorthand[text]

    m = _HOURLY_RE.match(text)
    if m and 0 <= int(m[1]) <= 59:
        return ScheduleSpec("hourly", minute=int(m[1]))
    m = _INTERVAL_RE.match(text)
    # canonical only: no leading zero on the hours, and 1 is just "hourly"
    if m and m[1] == str(int(m[1])) and 2 <= int(m[1]) <= 23 and 0 <= int(m[2]) <= 59:
        return ScheduleSpec("interval", hours=int(m[1]), minute=int(m[2]))
    m = _DAILY_RE.match(text)
    if m and 0 <= int(m[1]) <= 23 and 0 <= int(m[2]) <= 59:
        return ScheduleSpec("daily", hour=int(m[1]), minute=int(m[2]))
    m = _WEEKLY_RE.match(text)
    if m and 0 <= int(m[2]) <= 23 and 0 <= int(m[3]) <= 59:
        days = m[1].split(",")
        # only canonical (Mon..Sun order, no repeats) so that it round-trips exactly
        if len(set(days)) == len(days) and [d for d in WEEKDAYS if d in days] == days:
            return ScheduleSpec("weekly", days=days, hour=int(m[2]), minute=int(m[3]))
    m = _MONTHLY_RE.match(text)
    if m and 1 <= int(m[1]) <= 28 and 0 <= int(m[2]) <= 23 and 0 <= int(m[3]) <= 59:
        return ScheduleSpec("monthly", day=int(m[1]), hour=int(m[2]), minute=int(m[3]))
    return ScheduleSpec("custom", expression=text)


def describe_schedule(expression: str) -> str:
    """The task list's schedule column (TasksPage.tsx describeSchedule)."""
    spec = parse_schedule(expression or "")
    time = f"{_pad2(spec.hour)}:{_pad2(spec.minute)}"
    if spec.kind == "hourly":
        return f"Hourly, at minute {spec.minute}"
    if spec.kind == "interval":
        return f"Every {spec.hours} hours, at minute {spec.minute}"
    if spec.kind == "daily":
        return f"Daily at {time}"
    if spec.kind == "weekly":
        return f"Weekly on {', '.join(spec.days)} at {time}"
    if spec.kind == "monthly":
        return f"Monthly on day {spec.day} at {time}"
    return spec.expression


# -- Shells and scripts (src/shebang.ts, src/command.ts) ----------------------


def parse_shebang(script: str) -> tuple[str, str] | None:
    """(interpreter, argument) from a script's #! line, or None."""
    line = script.split("\n", 1)[0]
    if not line.startswith("#!"):
        return None
    m = re.match(r"^(\S+)\s*(.*)$", line[2:].strip())
    return (m[1], m[2].strip()) if m else None


def shell_for(script: str, shells: list[dict]) -> dict | None:
    """The listed shell whose path (or alias) is the script's interpreter."""
    shebang = parse_shebang(script)
    if shebang is None:
        return None
    interpreter = shebang[0]
    return next((s for s in shells if s["path"] == interpreter or interpreter in s.get("aliases", [])), None)


def template_for(shell_path: str) -> str:
    """A starter script for a shell, with a strict-mode line that fits it."""
    name = posixpath.basename(shell_path)
    strict = "\n"
    if name in ("bash", "zsh"):
        strict = "set -euo pipefail\n\n"
    elif name in ("sh", "dash", "ash", "ksh", "mksh"):
        strict = "set -eu\n\n"
    return f"#!{shell_path}\n{strict}"


def _after_first_line(script: str) -> str:
    return "\n".join(script.split("\n")[1:])


def change_shell(script: str, new_shell_path: str, shells: list[dict]) -> str:
    """Points the script's #! line at another shell; an untouched starter
    template is regenerated for the new shell instead."""
    current = shell_for(script, shells)
    shebang = parse_shebang(script)
    if current and not (shebang and shebang[1]) and \
            _after_first_line(script) == _after_first_line(template_for(current["path"])):
        return template_for(new_shell_path)
    arg = shebang[1] if current and shebang else ""
    line = f"#!{new_shell_path}{' ' + arg if arg else ''}"
    lines = script.split("\n")
    if lines and lines[0].startswith("#!"):
        lines[0] = line
    else:
        lines.insert(0, line)
    return "\n".join(lines)


def _quote(word: str) -> str:
    return '"' + word.replace("\\", "\\\\").replace('"', '\\"') + '"'


def compose_command(interpreter: str, program: str, args: str) -> tuple[str, str]:
    """(command_path, command_args) for "run an existing program or script":
    a script run by a shell is stored as the shell plus the quoted script."""
    program, args = program.strip(), args.strip()
    if not interpreter:
        return program, args
    return interpreter, " ".join(part for part in (_quote(program), args) if part)


def _first_word(text: str) -> tuple[str, str] | None:
    text = text.lstrip()
    if not text:
        return None
    word, i, in_quote = "", 0, None
    while i < len(text):
        c = text[i]
        if c == "\\" and in_quote != "'" and i + 1 < len(text):
            i += 1
            word += text[i]
        elif in_quote:
            if c == in_quote:
                in_quote = None
            else:
                word += c
        elif c in ('"', "'"):
            in_quote = c
        elif c.isspace():
            break
        else:
            word += c
        i += 1
    return None if in_quote else (word, text[i:].strip())


def split_command(command_path: str, command_args: str, shells: list[dict]) -> tuple[str, str, str]:
    """(interpreter, program, args): the inverse of compose_command."""
    shell = next((s for s in shells if s["path"] == command_path or command_path in s.get("aliases", [])), None)
    first = _first_word(command_args) if shell else None
    if shell is None or first is None:
        return "", command_path, command_args
    return shell["path"], first[0], first[1]


# -- Alerts (src/notify.ts) ------------------------------------------------------


def summarize_rules(rules: list[dict], channels: list[dict]) -> str:
    """"Ops (failure, missed run), Chat (every run)" for the task list."""
    by_id = {c["id"]: c for c in channels}
    parts = []
    for rule in rules or []:
        channel = by_id.get(rule.get("channel_id"))
        if channel is None:
            continue
        if channel["type"] == "healthchecks":
            parts.append(f"{channel['name']} (every run)")
        else:
            parts.append(f"{channel['name']} ({', '.join(EVENT_WORDS[e] for e in rule['events'])})")
    return ", ".join(parts)


def run_detail(run: dict) -> str:
    """Why a failed run failed (TaskRunsDialog.tsx detail())."""
    if run.get("status") != "failed":
        return ""
    if run.get("result") == "timeout":
        return "Timed out"
    if run.get("exit_code") is not None and run.get("exit_kind") == "exited":
        return f"Exit code {run['exit_code']}"
    if run.get("exit_code") is not None:
        return f"Killed by signal {run['exit_code']}"
    return run.get("result") or ""


def run_result_label(run: dict) -> str:
    """"Failed (Exit code 2)", "Succeeded", ..."""
    label = RUN_STATUS_LABELS.get(run.get("status"), run.get("status") or "")
    detail = run_detail(run)
    return f"{label} ({detail})" if detail else label


def duration_label(seconds: float | None) -> str:
    if seconds is None:
        return ""
    if seconds < 0.1:
        return "< 0.1 s"
    if seconds < 60:
        return f"{round(seconds, 1):g} s"
    return f"{int(seconds // 60)} min {round(seconds % 60)} s"
