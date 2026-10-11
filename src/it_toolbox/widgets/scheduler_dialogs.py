"""Dialogs for the Scheduler Manager (widgets/scheduler_manager_widget.py).
They collect input the way the cockpit-scheduler page's dialogs do; the
manager makes the helper calls, except where a dialog needs the server
while it is open (the schedule preview, run history, the import preview),
which it does through the `validate` / connection callables it is given.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QRadioButton,
    QSpinBox,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from it_toolbox.core import async_utils
from it_toolbox.core import scheduler_manager as sm
from it_toolbox.widgets.hosting_dialogs import monospace
from it_toolbox.widgets.hosting_manager_widget import when_label

TITLE = "Scheduler Manager"


def _buttons(dialog: QDialog, accept, ok_text: str | None = None) -> QDialogButtonBox:
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    if ok_text:
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(ok_text)
    buttons.accepted.connect(accept)
    buttons.rejected.connect(dialog.reject)
    return buttons


def _note(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    return label


def parse_pairs(text: str, separator: str, what: str) -> dict[str, str]:
    """`KEY<separator>value` lines into a dict (blank lines skipped).
    Raises ValueError naming the first bad or repeated line."""
    pairs: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        key, sep, value = line.partition(separator)
        key = key.strip()
        if not sep or not key:
            raise ValueError(f"'{line.strip()}' isn't {what}")
        if key in pairs:
            raise ValueError(f"{key} is listed twice.")
        pairs[key] = value.strip() if separator == ":" else value
    return pairs


# -- Schedule --------------------------------------------------------------------


class SchedulePicker(QWidget):
    """The page's SchedulePicker: Hourly / Every N hours / Daily / Weekly /
    Monthly pickers, or a custom OnCalendar= expression, with systemd's own
    verdict and the next runs underneath. `validate(expression)` is a
    blocking call (SchedulerConnection.validate_schedule) run in the
    background; None skips the preview."""

    def __init__(self, expression: str, validate=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._validate = validate
        self._generation = 0
        self.valid: bool | None = None
        spec = sm.parse_schedule(expression or "*-*-* 03:00:00")

        self.kind = QComboBox()
        for kind in sm.SCHEDULE_KINDS:
            self.kind.addItem(sm.SCHEDULE_KIND_LABELS[kind], kind)
        self.hours = self._spin(2, 23, spec.hours)
        self.hour = self._spin(0, 23, spec.hour)
        self.minute = self._spin(0, 59, spec.minute)
        self.day = self._spin(1, 28, spec.day)
        self.days = {day: QCheckBox(day) for day in sm.WEEKDAYS}
        for day, box in self.days.items():
            box.setChecked(day in spec.days)
            box.toggled.connect(self._changed)
        self.expression = QLineEdit(spec.expression if spec.kind == "custom" else "")
        self.expression.setPlaceholderText("e.g. Mon..Fri *-*-* 09:00:00  or  *:0/15")
        self.expression.textChanged.connect(self._changed)
        self.preview = QLabel()
        self.preview.setWordWrap(True)
        self.preview.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self._every_row = self._labelled("Every", self.hours, "hours")
        self._day_row = self._labelled("Day of month", self.day)
        days_row = QWidget()
        days_layout = QHBoxLayout(days_row)
        days_layout.setContentsMargins(0, 0, 0, 0)
        for box in self.days.values():
            days_layout.addWidget(box)
        days_layout.addStretch(1)
        self._days_row = days_row
        self._time_row = self._labelled("At", self.hour, ":", self.minute)
        self._minute_row = self._labelled("At minute", self.minute_only())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.kind)
        for row in (self._every_row, self._days_row, self._day_row, self._time_row, self._minute_row):
            layout.addWidget(row)
        layout.addWidget(self.expression)
        layout.addWidget(self.preview)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(400)
        self._timer.timeout.connect(self._check)
        self.kind.setCurrentIndex(sm.SCHEDULE_KINDS.index(spec.kind))
        self.kind.currentIndexChanged.connect(self._kind_changed)
        self._show_rows()
        self._changed()

    def _spin(self, low: int, high: int, value: int) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(low, high)
        spin.setValue(value)
        spin.valueChanged.connect(self._changed)
        return spin

    def minute_only(self) -> QSpinBox:
        # "Hourly" and "Every N hours" have their own minute box, kept in
        # step with the time-of-day one so switching presets keeps it.
        self.minute_alone = self._spin(0, 59, self.minute.value())
        self.minute_alone.valueChanged.connect(self.minute.setValue)
        self.minute.valueChanged.connect(self.minute_alone.setValue)
        return self.minute_alone

    @staticmethod
    def _labelled(text: str, *widgets: QWidget | str) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel(text))
        for widget in widgets:
            layout.addWidget(QLabel(widget) if isinstance(widget, str) else widget)
        layout.addStretch(1)
        return row

    def current_kind(self) -> str:
        return self.kind.currentData()

    def _kind_changed(self) -> None:
        if self.current_kind() == "custom" and not self.expression.text().strip():
            # switchScheduleKind: carry the preset over as the custom text
            previous = sm.SCHEDULE_KINDS[self._last_kind_index]
            self.expression.setText(sm.serialize_schedule(self._spec(previous)))
        self._show_rows()
        self._changed()

    def _show_rows(self) -> None:
        kind = self.current_kind()
        self._last_kind_index = self.kind.currentIndex()
        self._every_row.setVisible(kind == "interval")
        self._days_row.setVisible(kind == "weekly")
        self._day_row.setVisible(kind == "monthly")
        self._time_row.setVisible(kind in ("daily", "weekly", "monthly"))
        self._minute_row.setVisible(kind in ("hourly", "interval"))
        self.expression.setVisible(kind == "custom")

    def _spec(self, kind: str) -> sm.ScheduleSpec:
        return sm.ScheduleSpec(
            kind=kind,
            minute=self.minute.value(),
            hour=self.hour.value(),
            hours=self.hours.value(),
            days=[day for day, box in self.days.items() if box.isChecked()],
            day=self.day.value(),
            expression=self.expression.text(),
        )

    def schedule(self) -> str:
        return sm.serialize_schedule(self._spec(self.current_kind()))

    def _changed(self) -> None:
        self.valid = None
        if not self.schedule():
            self.preview.setText("Choose at least one day." if self.current_kind() == "weekly"
                                 else "Enter a systemd calendar expression.")
            self.valid = False
            return
        if self._validate is None:
            self.preview.setText("")
            return
        self.preview.setText("Checking…")
        self._timer.start()

    def _check(self) -> None:
        self._generation += 1
        generation = self._generation
        expression = self.schedule()

        def ok(result: dict) -> None:
            if generation != self._generation:
                return
            self.valid = True
            upcoming = result.get("next") or []
            self.preview.setText(f"Next runs (server time): {'; '.join(upcoming[:2])}" if upcoming
                                 else "Valid schedule.")

        def failed(error: Exception) -> None:
            if generation != self._generation:
                return
            self.valid = False
            self.preview.setText(f"Invalid schedule: {error}")

        async_utils.run_in_background(lambda: self._validate(expression), on_result=ok, on_error=failed)


# -- Task -------------------------------------------------------------------------


class TaskDialog(QDialog):
    """Create or edit a task: the page's TaskDialog, with its Advanced
    options and Alerts sections as tabs. `data` is the helper's
    dialog-data reply (users, shells, channels); `task` a get-task reply."""

    def __init__(self, data: dict, other_tasks: list[dict], task: dict | None = None,
                 validate=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.task = task
        self.shells: list[dict] = data.get("shells") or []
        self.channels: list[dict] = data.get("channels") or []
        self.setWindowTitle(f"Edit {task['name']}" if task else "Create Task")
        self.resize(720, 680)
        task = task or {}

        tabs = QTabWidget()
        tabs.addTab(self._build_general(task, data, validate), "General")
        tabs.addTab(self._build_advanced(task, other_tasks), "Advanced")
        tabs.addTab(self._build_alerts(task), "Alerts")
        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(_buttons(self, self._accept, "Save" if self.task else "Create"))

    # -- General --------------------------------------------------------------

    def _build_general(self, task: dict, data: dict, validate) -> QWidget:
        page = QWidget()
        self.name = QLineEdit(task.get("name", ""))
        self.description = QLineEdit(task.get("description", ""))
        self.inline_radio = QRadioButton("Write a script")
        self.path_radio = QRadioButton("Run an existing program or script")
        group = QButtonGroup(page)
        group.addButton(self.inline_radio)
        group.addButton(self.path_radio)
        kind_row = QHBoxLayout()
        kind_row.addWidget(self.inline_radio)
        kind_row.addWidget(self.path_radio)
        kind_row.addStretch(1)

        default_shell = self.shells[0]["path"] if self.shells else "/bin/bash"
        self.script = QPlainTextEdit(task.get("script") or sm.template_for(default_shell))
        self.script.setFont(monospace())
        self.script_shell = QComboBox()
        self.script_shell.currentIndexChanged.connect(self._script_shell_chosen)
        self.script.textChanged.connect(self._sync_script_shell)
        inline_page = QWidget()
        inline_form = QFormLayout(inline_page)
        inline_form.setContentsMargins(0, 0, 0, 0)
        inline_form.addRow("Shell:", self.script_shell)
        inline_form.addRow("Script:", self.script)
        inline_form.addRow("", _note("The first line (#!) names the interpreter; the Shell menu sets it. "
                                     "Saved as a root-owned file that only the run-as user can read."))

        interpreter, program, args = sm.split_command(task.get("command_path") or "",
                                                      task.get("command_args") or "", self.shells)
        self.command_shell = QComboBox()
        self.command_shell.addItem("None (run the file itself)", "")
        for shell in self.shells:
            self.command_shell.addItem(shell["path"], shell["path"])
        self.command_shell.setCurrentIndex(max(0, self.command_shell.findData(interpreter)))
        self.program = QLineEdit(program)
        self.program.setPlaceholderText("e.g. /usr/local/bin/backup  or  /home/user/backup.sh")
        self.arguments = QLineEdit(args)
        path_page = QWidget()
        path_form = QFormLayout(path_page)
        path_form.setContentsMargins(0, 0, 0, 0)
        path_form.addRow("Shell:", self.command_shell)
        path_form.addRow("Program:", self.program)
        path_form.addRow("Arguments:", self.arguments)
        path_form.addRow("", _note("Split like a shell would (quotes group words), but never run through a "
                                   "shell: $VARIABLES, pipes and redirects are not expanded."))

        self.what = QStackedWidget()
        self.what.addWidget(inline_page)
        self.what.addWidget(path_page)
        self.inline_radio.toggled.connect(lambda on: self.what.setCurrentIndex(0 if on else 1))
        (self.path_radio if task.get("kind") == "path" else self.inline_radio).setChecked(True)
        self.what.setCurrentIndex(1 if task.get("kind") == "path" else 0)

        self.schedule = SchedulePicker(task.get("schedule") or "*-*-* 03:00:00", validate)
        self.run_as = QComboBox()
        self.run_as.setEditable(True)
        for user in data.get("users") or [{"name": "root"}]:
            self.run_as.addItem(user["name"])
        self.run_as.setCurrentText(task.get("run_as") or "root")
        self.enabled = QCheckBox("Enabled (runs on the schedule)")
        self.enabled.setChecked(task.get("enabled", True))

        form = QFormLayout(page)
        form.addRow("Name:", self.name)
        form.addRow("Description:", self.description)
        form.addRow("What to run:", kind_row)
        form.addRow(self.what)
        form.addRow("Schedule:", self.schedule)
        form.addRow("Run as:", self.run_as)
        form.addRow("", self.enabled)
        self._sync_script_shell()
        return page

    def _sync_script_shell(self) -> None:
        """The Shell menu reflects the script's #! line (shebang.ts)."""
        script = self.script.toPlainText()
        combo = self.script_shell
        combo.blockSignals(True)
        combo.clear()
        for shell in self.shells:
            combo.addItem(shell["path"], shell["path"])
        current = sm.shell_for(script, self.shells)
        if current is not None:
            combo.setCurrentIndex(combo.findData(current["path"]))
        else:
            shebang = sm.parse_shebang(script)
            label = f"Other ({' '.join(shebang).strip()}, set by the first line)" if shebang \
                else "None (add a #! first line)"
            combo.insertItem(0, label, None)
            combo.setCurrentIndex(0)
        combo.blockSignals(False)

    def _script_shell_chosen(self) -> None:
        path = self.script_shell.currentData()
        if not path:
            return
        updated = sm.change_shell(self.script.toPlainText(), path, self.shells)
        if updated != self.script.toPlainText():
            self.script.setPlainText(updated)

    # -- Advanced ---------------------------------------------------------------

    def _build_advanced(self, task: dict, other_tasks: list[dict]) -> QWidget:
        page = QWidget()
        self.timeout = QSpinBox()
        self.timeout.setRange(0, sm.MAX_TIMEOUT_SEC)
        self.timeout.setValue(task.get("timeout_sec", 0))
        self.timeout.setSpecialValueText("No timeout")
        self.working_dir = QLineEdit(task.get("working_dir") or "")
        self.working_dir.setPlaceholderText("/var/lib/myapp")
        self.env = QPlainTextEdit("\n".join(f"{k}={v}" for k, v in (task.get("env") or {}).items()))
        self.env.setFont(monospace())
        self.env.setPlaceholderText("NAME=value, one per line")
        self.retries = QSpinBox()
        self.retries.setRange(0, sm.MAX_RETRIES)
        self.retries.setValue(task.get("retries", 0))
        self.retry_delay = QSpinBox()
        self.retry_delay.setRange(0, sm.MAX_RETRY_DELAY_SEC)
        self.retry_delay.setValue(task.get("retry_delay_sec", 60))
        self.on_failure = QComboBox()
        self.on_failure.addItem("Nothing", "")
        for other in other_tasks:
            self.on_failure.addItem(other["name"], other["id"])
        self.on_failure.setCurrentIndex(max(0, self.on_failure.findData(task.get("on_failure_task_id") or "")))

        form = QFormLayout(page)
        form.addRow("Timeout (seconds):", self.timeout)
        form.addRow("", _note("Covers the whole run, including any retries."))
        form.addRow("Working directory:", self.working_dir)
        form.addRow("Environment variables:", self.env)
        form.addRow("", _note("Stored in a root-only file, not in the (world-readable) systemd unit."))
        form.addRow("Retries on failure:", self.retries)
        form.addRow("Wait between retries (seconds):", self.retry_delay)
        form.addRow("If it still fails, run:", self.on_failure)
        return page

    # -- Alerts -------------------------------------------------------------------

    def _build_alerts(self, task: dict) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        rules = {rule["channel_id"]: rule for rule in task.get("notify") or []}
        self.channel_rows: dict[str, dict] = {}
        if not self.channels:
            layout.addWidget(_note("No notification channels yet. Add one on the Notification Channels tab, "
                                   "then pick it here."))
        for channel in self.channels:
            rule = rules.get(channel["id"])
            box = QGroupBox(f"{channel['name']} ({channel.get('type_label') or channel['type']})")
            box.setCheckable(True)
            box.setChecked(rule is not None)
            box_layout = QVBoxLayout(box)
            row = {"box": box, "events": {}, "slug": None}
            if channel["type"] == "healthchecks":
                slug = QLineEdit(rule["slug"] if rule else "")
                slug.setPlaceholderText("(named after the task)")
                row["slug"] = slug
                box_layout.addWidget(self._form_row("Check name:", slug))
                box_layout.addWidget(_note("Every run pings this check. Healthchecks decides for itself when "
                                           "to alert, including on a missing ping."))
            else:
                events = rule["events"] if rule else sm.DEFAULT_EVENTS
                for event in sm.NOTIFY_EVENTS:
                    check = QCheckBox(sm.EVENT_LABELS[event])
                    check.setChecked(event in events)
                    check.toggled.connect(self._sync_grace)
                    row["events"][event] = check
                    box_layout.addWidget(check)
            box.toggled.connect(self._sync_grace)
            self.channel_rows[channel["id"]] = row
            layout.addWidget(box)
        self.grace = QSpinBox()
        self.grace.setRange(sm.MIN_MISSED_GRACE_MIN, sm.MAX_MISSED_GRACE_MIN)
        self.grace.setValue(task.get("missed_grace_min", 15))
        self.grace_row = self._form_row("Missed-run grace (minutes):", self.grace)
        layout.addWidget(self.grace_row)
        layout.addStretch(1)
        self._sync_grace()
        return page

    @staticmethod
    def _form_row(label: str, widget: QWidget) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel(label))
        layout.addWidget(widget, 1)
        return row

    def _sync_grace(self) -> None:
        self.grace_row.setVisible(any(
            row["box"].isChecked() and row["events"].get("missed") and row["events"]["missed"].isChecked()
            for row in self.channel_rows.values()
        ))

    def notify_rules(self) -> list[dict]:
        """rulesFromSelections: in the channels' own order."""
        rules = []
        for channel in self.channels:
            row = self.channel_rows[channel["id"]]
            if not row["box"].isChecked():
                continue
            if channel["type"] == "healthchecks":
                rules.append({"channel_id": channel["id"], "events": [], "slug": row["slug"].text().strip()})
            else:
                events = [e for e in sm.NOTIFY_EVENTS if row["events"][e].isChecked()]
                rules.append({"channel_id": channel["id"], "events": events, "slug": ""})
        return rules

    # -- Result -------------------------------------------------------------------

    def _problem(self) -> str | None:
        if not self.name.text().strip():
            return "A task name is required."
        if self.inline_radio.isChecked():
            if not self.script.toPlainText().startswith("#!"):
                return "The script must start with a #! line naming its interpreter."
        elif not self.program.text().strip():
            return "Choose the program to run."
        if self.schedule.valid is False:
            return self.schedule.preview.text() or "The schedule isn't valid."
        try:
            env = parse_pairs(self.env.toPlainText(), "=", "NAME=value")
        except ValueError as exc:
            return f"Environment variables: {exc}"
        bad = next((key for key in env if not sm.ENV_KEY_RE.match(key)), None)
        if bad:
            return f"{bad} isn't a valid environment variable name."
        for channel in self.channels:
            row = self.channel_rows[channel["id"]]
            if not row["box"].isChecked():
                continue
            if channel["type"] == "healthchecks":
                slug = row["slug"].text().strip()
                if slug and not sm.SLUG_RE.match(slug):
                    return (f"The Healthchecks check name for {channel['name']} may only use letters, digits, "
                            '"-" and "_".')
            elif not any(check.isChecked() for check in row["events"].values()):
                return f"Choose at least one event for {channel['name']}, or untick it."
        return None

    def _accept(self) -> None:
        problem = self._problem()
        if problem:
            QMessageBox.warning(self, TITLE, problem)
            return
        self.accept()

    def values(self) -> dict:
        """The create-task / update-task arguments (helper.ts taskArgs)."""
        values = {
            "name": self.name.text().strip(),
            "description": self.description.text().strip(),
            "kind": "inline" if self.inline_radio.isChecked() else "path",
            "run_as": self.run_as.currentText().strip() or "root",
            "schedule": self.schedule.schedule(),
            "timeout_sec": self.timeout.value(),
            "env": parse_pairs(self.env.toPlainText(), "=", "NAME=value"),
            "working_dir": self.working_dir.text().strip(),
            "retries": self.retries.value(),
            "retry_delay_sec": self.retry_delay.value(),
            "on_failure_task_id": self.on_failure.currentData() or "",
            "enabled": self.enabled.isChecked(),
            "notify": self.notify_rules(),
            "missed_grace_min": self.grace.value(),
        }
        if values["kind"] == "inline":
            values["script"] = self.script.toPlainText()
        else:
            values["command_path"], values["command_args"] = sm.compose_command(
                self.command_shell.currentData() or "", self.program.text(), self.arguments.text())
        return values


# -- Notification channel ------------------------------------------------------------


class ChannelDialog(QDialog):
    """Add or edit a notification channel. On an edit the stored URL and
    header values are never shown: a blank field keeps them."""

    URL_NOTES = {
        "webhook": "The full URL is a secret: it is stored on the server and never shown again.",
        "googlechat": "The incoming-webhook URL of a Google Chat space "
                      "(Space name > Apps & integrations > Webhooks).",
        "healthchecks": "Your project's ping URL, e.g. https://hc-ping.com/<ping-key>. Each task pings its own "
                        "check, created on the first ping.",
    }

    def __init__(self, channel: dict | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.channel = channel
        self.setWindowTitle(f"Edit {channel['name']}" if channel else "Add Notification Channel")
        self.setMinimumWidth(520)
        self.name = QLineEdit(channel["name"] if channel else "")
        self.type = QComboBox()
        for channel_type in sm.CHANNEL_TYPES:
            self.type.addItem(sm.CHANNEL_TYPE_LABELS[channel_type], channel_type)
        if channel:
            self.type.setCurrentIndex(self.type.findData(channel["type"]))
            self.type.setEnabled(False)  # fixed once created
        self.url = QLineEdit()
        self.url.setPlaceholderText(f"Leave blank to keep {channel['destination']}" if channel else "https://...")
        self.url_note = _note("")
        self.headers = QPlainTextEdit("\n".join(f"{name}: " for name in (channel or {}).get("header_names", [])))
        self.headers.setFont(monospace())
        self.headers.setPlaceholderText("Authorization: Bearer ...")
        self.headers.setMaximumHeight(110)
        self.headers_note = _note("For example an Authorization header, one per line. Values are never shown "
                                  "again; leave one blank to keep it.")
        form = QFormLayout()
        form.addRow("Name:", self.name)
        form.addRow("Type:", self.type)
        form.addRow("URL:", self.url)
        form.addRow("", self.url_note)
        self.headers_label = QLabel("Headers:")
        form.addRow(self.headers_label, self.headers)
        form.addRow("", self.headers_note)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(_buttons(self, self._accept, "Save" if channel else "Add"))
        self.type.currentIndexChanged.connect(self._type_changed)
        self._type_changed()

    def _type_changed(self) -> None:
        channel_type = self.type.currentData()
        self.url_note.setText(self.URL_NOTES[channel_type])
        for widget in (self.headers_label, self.headers, self.headers_note):
            widget.setVisible(channel_type == "webhook")

    def _accept(self) -> None:
        if not self.name.text().strip():
            QMessageBox.warning(self, TITLE, "A channel name is required.")
            return
        if not self.channel and not self.url.text().strip():
            QMessageBox.warning(self, TITLE, "A URL is required.")
            return
        try:
            self.header_values()
        except ValueError as exc:
            QMessageBox.warning(self, TITLE, f"Headers: {exc}")
            return
        self.accept()

    def header_values(self) -> dict | None:
        if self.type.currentData() != "webhook":
            return None
        return parse_pairs(self.headers.toPlainText(), ":", "Name: value")

    def values(self) -> dict:
        return {
            "name": self.name.text().strip(),
            "type": self.type.currentData(),
            "url": self.url.text().strip(),
            "headers": self.header_values(),
        }


# -- Export ---------------------------------------------------------------------------


class ExportDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export Configuration")
        self.setMinimumWidth(480)
        self.include_secrets = QCheckBox("Include secrets")
        warning = _note("Channel URLs and header values (they often contain tokens) and environment variable "
                        "values. Without them the file is safe to share, but importing it needs you to enter "
                        "the channel URLs again. With them, keep the file as private as a password file.")
        layout = QVBoxLayout(self)
        layout.addWidget(_note("Saves every task and notification channel to a file, so it can be imported on "
                               "this or another server. Run history and logs aren't included."))
        layout.addWidget(self.include_secrets)
        layout.addWidget(warning)
        layout.addWidget(_buttons(self, self.accept, "Export…"))


# -- Import / restore -------------------------------------------------------------------


ACTION_LABELS = {"create": "Create", "update": "Update", "skip": "Skip", "reject": "Can't import"}
RESULT_LABELS = {"created": "Created", "updated": "Updated", "skipped": "Skipped", "rejected": "Not imported",
                 "failed": "Failed"}


class ImportDialog(QDialog):
    """Import a configuration file, or restore a backup: choose what to do
    with name clashes, preview what would change (the helper's
    preview-import), then apply it. `connection` is the manager's
    SchedulerConnection; `source` is {"document": ...} or {"backup": name}."""

    def __init__(self, connection, source: dict, source_label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._connection = connection
        self._source = source
        self._generation = 0
        self.plan: dict | None = None
        self.outcome: dict | None = None
        restoring = "backup" in source
        self.setWindowTitle("Restore from Backup" if restoring else "Import Configuration")
        self.resize(760, 600)

        self.mode = QComboBox()
        self.mode.addItem("Skip it", "skip")
        self.mode.addItem("Overwrite it", "overwrite")
        self.mode.setCurrentIndex(1 if restoring else 0)
        self.paused = QCheckBox("Import tasks paused")
        self.paused.setToolTip("Every imported task is created disabled, so nothing runs until you have "
                               "reviewed it and switched it on.")
        self.mode.currentIndexChanged.connect(self.refresh)
        self.paused.toggled.connect(self.refresh)

        self.summary = _note("Checking what would change…")
        self.urls_box = QGroupBox("Channels without a URL in the file")
        self.urls_layout = QFormLayout(self.urls_box)
        self.url_fields: dict[str, QLineEdit] = {}
        self.urls_box.setVisible(False)
        self.plan_view = QPlainTextEdit()
        self.plan_view.setReadOnly(True)
        self.plan_view.setFont(monospace())

        form = QFormLayout()
        form.addRow("Source:", QLabel(source_label))
        form.addRow("If a task or channel with the same name already exists:", self.mode)
        form.addRow("", self.paused)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.apply_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.apply_button.setText("Restore" if restoring else "Import")
        self.apply_button.setEnabled(False)
        self.buttons.accepted.connect(self.apply)
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(_note("Only import files you trust: imported tasks run their scripts as the users "
                               "named in the file, root included. Nothing is deleted: tasks and channels are "
                               "matched by name, and anything else is left alone."))
        layout.addLayout(form)
        layout.addWidget(self.urls_box)
        layout.addWidget(self.summary)
        layout.addWidget(self.plan_view, 1)
        layout.addWidget(self.buttons)
        self.refresh()

    def _args(self) -> tuple:
        urls = {name: field.text().strip() for name, field in self.url_fields.items() if field.text().strip()}
        return self._source, self.mode.currentData(), urls, self.paused.isChecked()

    def refresh(self) -> None:
        self._generation += 1
        generation = self._generation
        self.apply_button.setEnabled(False)
        self.summary.setText("Checking what would change…")
        args = self._args()

        def ok(plan: dict) -> None:
            if generation == self._generation:
                self.show_plan(plan)

        def failed(error: Exception) -> None:
            if generation == self._generation:
                self.plan = None
                self.summary.setText(f"Can't import: {error}")
                self.plan_view.clear()

        async_utils.run_in_background(lambda: self._connection.preview_import(*args), on_result=ok, on_error=failed)

    def show_plan(self, plan: dict) -> None:
        self.plan = plan
        for channel in plan.get("channels", []):
            if channel.get("needs_url") and channel["name"] not in self.url_fields:
                field = QLineEdit()
                field.setPlaceholderText("Leave empty to leave this channel out")
                field.editingFinished.connect(self.refresh)
                self.url_fields[channel["name"]] = field
                self.urls_layout.addRow(f"URL for {channel['name']}:", field)
        self.urls_box.setVisible(bool(self.url_fields))

        source = plan.get("source") or {}
        lines = []
        if source.get("host"):
            lines.append(f"Exported from {source['host']} on {when_label(source.get('exported_at')) or '?'}"
                         + ("" if source.get("secrets_included") else " (without secrets)"))
        for warning in plan.get("warnings", []):
            lines.append(f"! {warning}")
        for kind, title in (("channels", "Channels"), ("tasks", "Tasks")):
            items = plan.get(kind, [])
            if not items:
                continue
            lines.append("")
            lines.append(f"{title} in the file:")
            for item in items:
                detail = item["name"]
                if kind == "tasks":
                    detail += f"  (runs as {item.get('run_as') or '?'}, {sm.describe_schedule(item.get('schedule') or '')})"
                line = f"  {ACTION_LABELS.get(item['action'], item['action']):<13}{detail}"
                if item.get("reason"):
                    line += f" — {item['reason']}"
                lines.append(line)
                lines.extend(f"      ! {warning}" for warning in item.get("warnings", []))
        self.plan_view.setPlainText("\n".join(lines).strip() or "The file contains no tasks or channels.")

        summary = plan.get("summary", {})
        changes = sum(summary.get(kind, {}).get(action, 0)
                      for kind in ("channels", "tasks") for action in ("create", "update"))
        words = {"create": "to create", "update": "to update", "skip": "to skip", "reject": "can't be imported"}
        counts = "  ".join(
            f"{kind.capitalize()}: " + ", ".join(f"{n} {words[a]}" for a, n in c.items() if n and a in words)
            for kind, c in summary.items() if any(c.values()))
        self.summary.setText(counts if changes else "Nothing would change.")
        self.apply_button.setEnabled(bool(changes))

    def apply(self) -> None:
        self.apply_button.setEnabled(False)
        self.summary.setText("Importing…")
        args = self._args()

        def ok(outcome: dict) -> None:
            self.outcome = outcome
            self.accept()

        def failed(error: Exception) -> None:
            self.summary.setText(f"Import failed: {error}")
            self.apply_button.setEnabled(True)

        async_utils.run_in_background(lambda: self._connection.apply_import(*args), on_result=ok, on_error=failed)


def describe_outcome(outcome: dict) -> str:
    """A finished import, as the text of a message box."""
    lines = []
    for kind, title in (("channels", "Channels"), ("tasks", "Tasks")):
        for result in outcome.get("results", {}).get(kind, []):
            line = f"{title[:-1]} {result['name']}: {RESULT_LABELS.get(result['status'], result['status'])}"
            if result.get("reason"):
                line += f" — {result['reason']}"
            lines.append(line)
            lines.extend(f"    ! {warning}" for warning in result.get("warnings") or [])
    return "\n".join(lines) or "Nothing was imported."


# -- Backup settings --------------------------------------------------------------------


class BackupSettingsBox(QGroupBox):
    """The Backup & Restore tab's settings form."""

    def __init__(self, validate=None, parent: QWidget | None = None) -> None:
        super().__init__("Automatic backups", parent)
        self._validate = validate
        self.enabled = QCheckBox("Back up the configuration on a schedule")
        self.directory = QLineEdit(sm.DEFAULT_BACKUP_DIR)
        self.retention = QSpinBox()
        self.retention.setRange(1, sm.MAX_BACKUP_RETENTION)
        self.retention.setValue(14)
        self.retention.setMaximumWidth(120)
        self.schedule = SchedulePicker("*-*-* 02:00:00", validate)
        self.grid = QGridLayout(self)
        self.grid.addWidget(self.enabled, 0, 0, 1, 2)
        self.grid.addWidget(QLabel("Schedule:"), 1, 0, Qt.AlignmentFlag.AlignTop)
        self.grid.addWidget(self.schedule, 1, 1)
        self.grid.addWidget(QLabel("Backups to keep:"), 2, 0)
        self.grid.addWidget(self.retention, 2, 1)
        self.grid.addWidget(QLabel("Directory:"), 3, 0)
        self.grid.addWidget(self.directory, 3, 1)

    def set_settings(self, settings: dict) -> None:
        self.enabled.setChecked(bool(settings.get("enabled")))
        self.directory.setText(settings.get("directory") or sm.DEFAULT_BACKUP_DIR)
        self.retention.setValue(int(settings.get("retention") or 14))
        replacement = SchedulePicker(settings.get("schedule") or "*-*-* 02:00:00", self._validate)
        self.grid.replaceWidget(self.schedule, replacement)
        self.schedule.deleteLater()
        self.schedule = replacement

    def settings(self) -> dict:
        return {
            "enabled": self.enabled.isChecked(),
            "schedule": self.schedule.schedule(),
            "retention": self.retention.value(),
            "directory": self.directory.text().strip(),
        }
