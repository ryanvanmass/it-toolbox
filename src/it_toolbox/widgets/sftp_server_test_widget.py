"""One SFTP Server Test tab (General Tools): a form for the server,
credentials and how hard to push it, Start/Stop, and live numbers while
the test runs -- operations per second, per-operation counts, errors and
latency, bytes moved, and the most recent errors. See
core/sftp_stress_test.py for what the workers actually do.
"""

import time
from collections import deque
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from it_toolbox.core import async_utils, settings
from it_toolbox.core.ftp_client import UnknownHostKeyError
from it_toolbox.core.sftp_stress_test import (
    OPERATIONS,
    RECENT_ERRORS_LIMIT,
    StatsSnapshot,
    StressTest,
    StressTestConfig,
    format_bytes,
)
from it_toolbox.widgets import status_bar

POLL_INTERVAL_MS = 500
#: Ops/sec is averaged over this trailing window, so it reacts within a few
#: seconds without jumping around on every poll.
RATE_WINDOW_S = 5.0
MAX_WORKERS = 64
SIZE_UNITS = {"KB": 1024, "MB": 1024**2, "GB": 1024**3}
MAX_SIZE_VALUE = 1024 * 1024

IDLE, STARTING, RUNNING, STOPPING = "idle", "starting", "running", "stopping"

STAT_COLUMNS = ["Operation", "Count", "Errors", "Ops/sec", "Avg latency", "Max latency"]
ERROR_COLUMNS = ["Time", "Worker", "Operation", "Error"]
ROW_LABELS = {name: name.capitalize() for name in (*OPERATIONS, "connect")}


def _ms(seconds: float) -> str:
    return f"{seconds * 1000:.0f} ms"


def _duration(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 3600}:{seconds // 60 % 60:02d}:{seconds % 60:02d}"


class _SizeInput(QWidget):
    """A file size as a number plus a KB/MB/GB unit."""

    changed = Signal()

    def __init__(self, minimum: int, value: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.spin = QSpinBox()
        self.spin.setRange(minimum, MAX_SIZE_VALUE)
        self.spin.setValue(value)
        self.unit_combo = QComboBox()
        self.unit_combo.addItems(list(SIZE_UNITS))
        self.spin.valueChanged.connect(self.changed)
        self.unit_combo.currentTextChanged.connect(self.changed)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.spin, 1)
        layout.addWidget(self.unit_combo)

    def size(self) -> tuple[int, str]:
        return self.spin.value(), self.unit_combo.currentText()

    def set_size(self, value: int, unit: str) -> None:
        # One change, not two: the in-between value (new unit, old number)
        # would otherwise push the other size field around.
        if self.size() == (value, unit):
            return
        self.spin.blockSignals(True)
        self.unit_combo.blockSignals(True)
        if unit in SIZE_UNITS:
            self.unit_combo.setCurrentText(unit)
        self.spin.setValue(value)
        self.spin.blockSignals(False)
        self.unit_combo.blockSignals(False)
        self.changed.emit()

    def bytes(self) -> int:
        return self.spin.value() * SIZE_UNITS[self.unit_combo.currentText()]


class SftpServerTestWidget(QWidget):
    title_changed = Signal(str)
    #: A test configuration was saved; the sidebar lists them.
    saved_tests_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = IDLE
        self._closed = False
        self._test: StressTest | None = None
        self._task: status_bar.StatusTask | None = None
        # (elapsed, per-operation counts) samples for the trailing rate window.
        self._samples: deque[tuple[float, dict[str, int]]] = deque()
        self._last_error_seq = 0
        # The saved test this tab was opened from or last saved as.
        self.saved_name: str | None = None

        self._timer = QTimer(self)
        self._timer.setInterval(POLL_INTERVAL_MS)
        self._timer.timeout.connect(self._refresh_stats)

        self._build_form()
        self._build_stats()

        self._start_button = QPushButton("Start Test")
        self._start_button.clicked.connect(self.start)
        self._stop_button = QPushButton("Stop")
        self._stop_button.clicked.connect(self.stop)
        self._save_config_button = QPushButton("Save Test…")
        self._save_config_button.setToolTip(
            "Save these settings (not the password) under a name in the sidebar, to open again later."
        )
        self._save_config_button.clicked.connect(self.save_test_config)
        self._status_label = QLabel("Fill in the server details and start the test.")
        self._status_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._status_label.setWordWrap(True)
        buttons = QHBoxLayout()
        buttons.addWidget(self._start_button)
        buttons.addWidget(self._stop_button)
        buttons.addWidget(self._save_config_button)
        buttons.addWidget(self._status_label, 1)

        top = QHBoxLayout()
        top.addWidget(self._server_box, 3)
        top.addWidget(self._test_box, 2)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self._stats_table)
        errors_box = QGroupBox("Recent Errors")
        errors_layout = QVBoxLayout(errors_box)
        errors_layout.addWidget(self._errors_tree)
        splitter.addWidget(errors_box)
        splitter.setSizes([260, 140])

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addLayout(buttons)
        layout.addLayout(self._summary_grid)
        layout.addWidget(splitter, 1)

        self._load_defaults()
        self._update_controls()

    # -- Layout -------------------------------------------------------------

    def _build_form(self) -> None:
        self._host_edit = QLineEdit()
        self._host_edit.setPlaceholderText("sftp.example.com")
        self._port_spin = QSpinBox()
        self._port_spin.setRange(1, 65535)
        self._port_spin.setValue(22)
        self._username_edit = QLineEdit()
        self._password_edit = QLineEdit()
        self._password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._password_edit.setPlaceholderText("Leave empty to use a key or the SSH agent")
        self._key_edit = QLineEdit()
        self._key_edit.setPlaceholderText("Optional private key file")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_key)
        key_row = QHBoxLayout()
        key_row.addWidget(self._key_edit, 1)
        key_row.addWidget(browse)
        self._remote_dir_edit = QLineEdit()
        self._remote_dir_edit.setPlaceholderText("Home directory")

        self._server_box = QGroupBox("Server")
        form = QFormLayout(self._server_box)
        form.addRow("Host:", self._host_edit)
        form.addRow("Port:", self._port_spin)
        form.addRow("Username:", self._username_edit)
        form.addRow("Password:", self._password_edit)
        form.addRow("Private key:", key_row)
        form.addRow("Test in folder:", self._remote_dir_edit)

        self._workers_spin = QSpinBox()
        self._workers_spin.setRange(1, MAX_WORKERS)
        self._workers_spin.setValue(4)
        self._workers_spin.setToolTip("Each concurrent action runs on its own SFTP connection.")
        self._min_size = _SizeInput(0, 1)
        self._max_size = _SizeInput(1, 1)
        self._max_size.set_size(1, "MB")
        # Keep min <= max: whichever one was just changed wins.
        self._min_size.changed.connect(lambda: self._keep_sizes_ordered(self._min_size, self._max_size))
        self._max_size.changed.connect(lambda: self._keep_sizes_ordered(self._max_size, self._min_size))
        self._cleanup_check = QCheckBox("Delete the test folder when finished")
        self._cleanup_check.setChecked(True)
        explanation = QLabel(
            "Workers upload, download (checking contents), list, stat, rename, create and delete "
            "files at random inside a new it-toolbox-sftp-test-… folder. Nothing outside it is touched."
        )
        explanation.setWordWrap(True)
        explanation.setEnabled(False)

        self._test_box = QGroupBox("Test")
        test_form = QFormLayout(self._test_box)
        test_form.addRow("Concurrent actions:", self._workers_spin)
        test_form.addRow("Min file size:", self._min_size)
        test_form.addRow("Max file size:", self._max_size)
        test_form.addRow(self._cleanup_check)
        test_form.addRow(explanation)

    def _build_stats(self) -> None:
        self._summary_labels: dict[str, QLabel] = {}
        self._summary_grid = QGridLayout()
        for column, (key, title) in enumerate(
            [
                ("elapsed", "Elapsed"),
                ("rate", "Ops/sec"),
                ("ops", "Operations"),
                ("errors", "Errors"),
                ("uploaded", "Uploaded"),
                ("downloaded", "Downloaded"),
                ("workers", "Connected"),
            ]
        ):
            caption = QLabel(title)
            caption.setEnabled(False)
            value = QLabel("—")
            font = value.font()
            font.setPointSizeF(font.pointSizeF() * 1.4)
            font.setBold(True)
            value.setFont(font)
            self._summary_grid.addWidget(caption, 0, column)
            self._summary_grid.addWidget(value, 1, column)
            self._summary_labels[key] = value

        self._stats_table = QTreeWidget()
        self._stats_table.setRootIsDecorated(False)
        self._stats_table.setHeaderLabels(STAT_COLUMNS)
        self._stats_table.header().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._stat_rows: dict[str, QTreeWidgetItem] = {}
        for name in (*OPERATIONS, "connect"):
            item = QTreeWidgetItem([ROW_LABELS[name], "0", "0", "—", "—", "—"])
            for column in range(1, len(STAT_COLUMNS)):
                item.setTextAlignment(column, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._stats_table.addTopLevelItem(item)
            self._stat_rows[name] = item

        self._errors_tree = QTreeWidget()
        self._errors_tree.setRootIsDecorated(False)
        self._errors_tree.setHeaderLabels(ERROR_COLUMNS)
        self._errors_tree.header().setStretchLastSection(True)

    # -- Form ---------------------------------------------------------------

    def _browse_key(self) -> None:
        start = self._key_edit.text() or str(Path.home() / ".ssh")
        path, _ = QFileDialog.getOpenFileName(self, "Choose Private Key", start)
        if path:
            self._key_edit.setText(path)

    def _keep_sizes_ordered(self, changed: _SizeInput, other: _SizeInput) -> None:
        too_big = changed is self._min_size and changed.bytes() > other.bytes()
        too_small = changed is self._max_size and changed.bytes() < other.bytes()
        if too_big or too_small:
            other.set_size(*changed.size())

    def form_values(self) -> dict:
        """The form as saved for next time or as a named configuration --
        everything except the password."""
        min_size, min_unit = self._min_size.size()
        max_size, max_unit = self._max_size.size()
        return {
            "host": self._host_edit.text().strip(),
            "port": self._port_spin.value(),
            "username": self._username_edit.text().strip(),
            "key_path": self._key_edit.text().strip(),
            "remote_dir": self._remote_dir_edit.text().strip(),
            "workers": self._workers_spin.value(),
            "min_size": min_size,
            "min_unit": min_unit,
            "max_size": max_size,
            "max_unit": max_unit,
            "cleanup": self._cleanup_check.isChecked(),
        }

    def apply_values(self, values: dict) -> None:
        self._host_edit.setText(str(values.get("host", "")))
        self._username_edit.setText(str(values.get("username", "")))
        self._key_edit.setText(str(values.get("key_path", "")))
        self._remote_dir_edit.setText(str(values.get("remote_dir", "")))
        for spin, key in [(self._port_spin, "port"), (self._workers_spin, "workers")]:
            if isinstance(values.get(key), int):
                spin.setValue(values[key])
        # Max first, so a saved min that's bigger than the current max
        # doesn't drag the max along with it.
        for size_input, prefix in [(self._max_size, "max"), (self._min_size, "min")]:
            value, unit = values.get(f"{prefix}_size"), values.get(f"{prefix}_unit")
            if isinstance(value, int) and unit in SIZE_UNITS:
                size_input.set_size(value, unit)
            elif isinstance(values.get(f"{prefix}_kb"), int):  # saved before units existed
                size_input.set_size(values[f"{prefix}_kb"], "KB")
        if isinstance(values.get("cleanup"), bool):
            self._cleanup_check.setChecked(values["cleanup"])

    def _load_defaults(self) -> None:
        self.apply_values(settings.load_sftp_server_test_defaults())

    def _save_defaults(self) -> None:
        settings.save_sftp_server_test_defaults(self.form_values())

    # -- Saved test configurations ------------------------------------------

    def load_saved_test(self, name: str) -> bool:
        """Fills the form from the saved test `name`; False if it's gone."""
        values = settings.load_sftp_server_test_configs().get(name)
        if values is None:
            return False
        self.apply_values(values)
        self._password_edit.clear()
        self.saved_name = name
        self.title_changed.emit(f"SFTP Test: {name}")
        self._status_label.setText(f"Loaded “{name}”.")
        return True

    def save_test_config(self) -> None:
        name, ok = QInputDialog.getText(
            self,
            "Save Test",
            "Name for this test (the password isn't saved):",
            text=self.saved_name or self._host_edit.text().strip(),
        )
        name = name.strip()
        if not ok or not name:
            return
        configs = settings.load_sftp_server_test_configs()
        if name in configs and name != self.saved_name:
            answer = QMessageBox.question(self, "Save Test", f"Replace the saved test “{name}”?")
            if answer != QMessageBox.StandardButton.Yes:
                return
        configs[name] = self.form_values()
        settings.save_sftp_server_test_configs(configs)
        self.saved_name = name
        self._status_label.setText(f"Saved “{name}”.")
        self.saved_tests_changed.emit()

    def config(self) -> StressTestConfig:
        return StressTestConfig(
            host=self._host_edit.text().strip(),
            port=self._port_spin.value(),
            username=self._username_edit.text().strip(),
            password=self._password_edit.text() or None,
            key_path=self._key_edit.text().strip() or None,
            workers=self._workers_spin.value(),
            min_file_size=self._min_size.bytes(),
            max_file_size=self._max_size.bytes(),
            remote_dir=self._remote_dir_edit.text().strip(),
            cleanup=self._cleanup_check.isChecked(),
        )

    def _set_state(self, state: str, message: str | None = None) -> None:
        self._state = state
        if message is not None:
            self._status_label.setText(message)
        self._update_controls()

    def _update_controls(self) -> None:
        idle = self._state == IDLE
        self._server_box.setEnabled(idle)
        self._test_box.setEnabled(idle)
        self._start_button.setEnabled(idle)
        self._save_config_button.setEnabled(idle)
        self._stop_button.setEnabled(self._state in (STARTING, RUNNING))

    # -- Running ------------------------------------------------------------

    def start(self) -> None:
        if self._state != IDLE:
            return
        config = self.config()
        if not config.host or not config.username:
            QMessageBox.warning(self, "SFTP Server Test", "Enter a host and a username first.")
            return
        self._save_defaults()
        self.title_changed.emit(f"SFTP Test: {config.host}")
        self._test = StressTest(config)
        self._set_state(STARTING, f"Connecting to {config.username}@{config.host}:{config.port}…")
        self._task = status_bar.begin(self, f"SFTP test: connecting to {config.host}…")
        self._prepare(self._test)

    def _prepare(self, test: StressTest) -> None:
        async_utils.run_in_background(
            test.prepare,
            on_result=lambda root: self._on_prepared(test, root),
            on_error=lambda error: self._on_prepare_error(test, error),
        )

    def _on_prepared(self, test: StressTest, root: str) -> None:
        if self._closed:
            # Tab closed while connecting: the folder exists but nothing ran.
            if test.config.cleanup:
                async_utils.run_in_background(test.cleanup)
            return
        if test is not self._test:
            return
        if self._state != STARTING:
            # Stopped while connecting: the folder exists but nothing ran yet.
            self._finish(test)
            return
        test.start()
        self._samples.clear()
        self._last_error_seq = 0
        self._errors_tree.clear()
        self._timer.start()
        self._set_state(
            RUNNING,
            f"Running {test.config.workers} concurrent actions in {root}",
        )
        if self._task is not None:
            self._task.finish()
        self._task = status_bar.begin(self, f"SFTP test running against {test.config.host}…")
        self._refresh_stats()

    def _on_prepare_error(self, test: StressTest, error: Exception) -> None:
        if test is not self._test:
            return
        if isinstance(error, UnknownHostKeyError) and self._state == STARTING:
            confirmed = QMessageBox.question(
                self,
                "Unknown Host Key",
                f"The authenticity of host '{error.hostname}' can't be established.\n"
                f"{error.key.get_name()} key fingerprint is {error.fingerprint}.\n\n"
                "Are you sure you want to continue connecting? This adds the key to your "
                "~/.ssh/known_hosts, the same as accepting it in a regular ssh client would.",
            )
            if confirmed == QMessageBox.StandardButton.Yes:
                test.config.session().trust_host_key(error.hostname, error.key)
                self._prepare(test)
                return
            error_text = "Host key not trusted."
        else:
            error_text = str(error) or type(error).__name__
        self._test = None
        self._end_task("SFTP test couldn't start")
        self._set_state(IDLE, f"Couldn't start the test: {error_text}")

    def stop(self) -> None:
        test = self._test
        if test is None or self._state not in (STARTING, RUNNING):
            return
        test.stop()
        if self._state == STARTING:
            # prepare() is still in flight; _on_prepared() picks it up.
            self._set_state(STOPPING, "Stopping…")
            return
        self._set_state(STOPPING, "Stopping — letting in-flight operations finish…")
        self._finish(test)

    def _finish(self, test: StressTest) -> None:
        cleanup = test.config.cleanup

        def wind_down() -> int | None:
            test.join()
            return test.cleanup() if cleanup else None

        async_utils.run_in_background(
            wind_down,
            on_result=lambda removed: self._on_finished(test, removed, None),
            on_error=lambda error: self._on_finished(test, None, error),
        )

    def _on_finished(self, test: StressTest, removed: int | None, error: Exception | None) -> None:
        try:
            self._timer.stop()
        except RuntimeError:
            return  # tab closed while winding down
        if test is not self._test:
            return
        self._refresh_stats()
        snapshot = test.stats.snapshot()
        summary = (
            f"Finished: {snapshot.total_ops} operations, {snapshot.total_errors} errors "
            f"in {_duration(snapshot.elapsed)}."
        )
        if error is not None:
            summary += f" Couldn't remove {test.root}: {error}"
        elif removed is None:
            summary += f" Test files were left in {test.root}."
        elif test.root is not None:
            summary += f" Removed {test.root}."
        self._end_task(summary)
        self._set_state(IDLE, summary)

    def _end_task(self, message: str) -> None:
        if self._task is not None:
            self._task.finish(message)
            self._task = None

    # -- Stats --------------------------------------------------------------

    def _refresh_stats(self) -> None:
        if self._test is None:
            return
        snapshot = self._test.stats.snapshot()
        counts = {name: op.count for name, op in snapshot.operations.items()}
        self._samples.append((snapshot.elapsed, counts))
        while len(self._samples) > 2 and snapshot.elapsed - self._samples[1][0] >= RATE_WINDOW_S:
            self._samples.popleft()
        rates = self._rates(snapshot)
        self.show_snapshot(snapshot, rates)

    def _rates(self, snapshot: StatsSnapshot) -> dict[str, float]:
        oldest_elapsed, oldest_counts = self._samples[0]
        window = snapshot.elapsed - oldest_elapsed
        if window <= 0:
            return {name: 0.0 for name in snapshot.operations}
        return {
            name: (op.count - oldest_counts.get(name, 0)) / window
            for name, op in snapshot.operations.items()
        }

    def show_snapshot(self, snapshot: StatsSnapshot, rates: dict[str, float]) -> None:
        labels = self._summary_labels
        labels["elapsed"].setText(_duration(snapshot.elapsed))
        labels["rate"].setText(f"{sum(r for n, r in rates.items() if n != 'connect'):.1f}")
        labels["ops"].setText(f"{snapshot.total_ops:,}")
        labels["errors"].setText(f"{snapshot.total_errors:,}")
        labels["errors"].setStyleSheet("color: #c0392b;" if snapshot.total_errors else "")
        labels["uploaded"].setText(format_bytes(snapshot.bytes_uploaded))
        labels["downloaded"].setText(format_bytes(snapshot.bytes_downloaded))
        workers = self._test.config.workers if self._test is not None else snapshot.active_workers
        labels["workers"].setText(f"{snapshot.active_workers} / {workers}")

        for name, op in snapshot.operations.items():
            item = self._stat_rows[name]
            item.setText(1, f"{op.count:,}")
            item.setText(2, f"{op.errors:,}")
            item.setText(3, f"{rates.get(name, 0.0):.1f}")
            item.setText(4, _ms(op.avg_latency) if op.count else "—")
            item.setText(5, _ms(op.max_latency) if op.count else "—")

        # New errors go on top; the engine keeps only the most recent ones.
        for record in (r for r in snapshot.errors if r.seq > self._last_error_seq):
            self._errors_tree.insertTopLevelItem(
                0,
                QTreeWidgetItem(
                    [
                        time.strftime("%H:%M:%S", time.localtime(record.timestamp)),
                        str(record.worker),
                        ROW_LABELS.get(record.operation, record.operation),
                        record.message,
                    ]
                ),
            )
            self._last_error_seq = record.seq
        while self._errors_tree.topLevelItemCount() > RECENT_ERRORS_LIMIT:
            self._errors_tree.takeTopLevelItem(self._errors_tree.topLevelItemCount() - 1)

    @property
    def state(self) -> str:
        return self._state

    def close_session(self) -> None:
        """Called when the tab closes or the app quits: stops the workers
        and, if asked to, removes the test folder in the background."""
        self._closed = True
        self._timer.stop()
        test, self._test = self._test, None
        self._end_task("")
        if test is None or self._state == IDLE:
            return
        test.stop()
        if test.root is None:
            return  # prepare() still in flight -- _on_prepared() cleans up
        cleanup = test.config.cleanup

        def wind_down() -> None:
            test.join()
            if cleanup:
                test.cleanup()

        async_utils.run_in_background(wind_down)
