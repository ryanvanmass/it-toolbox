"""App-wide Settings page — a single scrollable page, not tab/session-based
like the other modules, so it never touches the shared session-tab pane.
"""

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from it_toolbox.core import rclone_client, settings, update_checker
from it_toolbox.core.async_utils import run_in_background
from it_toolbox.widgets.rclone_location_picker import clear_rclone_path, prompt_for_rclone_path


class SettingsView(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        outer_layout.addWidget(scroll_area)

        content = QWidget()
        self._content_layout = QVBoxLayout(content)
        self._content_layout.addWidget(self._build_updates_section())
        self._content_layout.addWidget(self._build_rclone_section())
        self._content_layout.addStretch(1)
        scroll_area.setWidget(content)

    def _build_updates_section(self) -> QGroupBox:
        box = QGroupBox("App Updates")
        layout = QVBoxLayout(box)

        installed_version = update_checker.get_installed_version()
        self._update_status_label = QLabel(f"Installed version: {installed_version}")

        self._update_link_button = QPushButton("View Release")
        self._update_link_button.hide()
        self._update_link_button.clicked.connect(self._open_latest_release)
        self._latest_release_url: str | None = None

        self._check_updates_button = QPushButton("Check for Updates")
        self._check_updates_button.clicked.connect(self._on_check_updates_clicked)

        button_row = QHBoxLayout()
        button_row.addWidget(self._check_updates_button)
        button_row.addWidget(self._update_link_button)
        button_row.addStretch(1)

        layout.addWidget(self._update_status_label)
        layout.addLayout(button_row)
        return box

    def _on_check_updates_clicked(self) -> None:
        self._check_updates_button.setEnabled(False)
        self._update_status_label.setText("Checking for updates…")
        self._update_link_button.hide()
        run_in_background(
            update_checker.get_latest_release,
            on_result=self._on_latest_release_checked,
            on_error=self._on_check_updates_error,
        )

    def _on_latest_release_checked(self, release: update_checker.ReleaseInfo | None) -> None:
        self._check_updates_button.setEnabled(True)
        installed_version = update_checker.get_installed_version()

        if release is None:
            self._update_status_label.setText(
                f"Installed version: {installed_version} (no releases published yet)"
            )
            return

        if update_checker.is_update_available(installed_version, release.version):
            self._update_status_label.setText(
                f"Update available: v{release.version} (installed: {installed_version})"
            )
            self._latest_release_url = release.html_url
            self._update_link_button.show()
        else:
            self._update_status_label.setText(f"Up to date (v{installed_version})")

    def _on_check_updates_error(self, error: Exception) -> None:
        self._check_updates_button.setEnabled(True)
        self._update_status_label.setText(f"Couldn't check for updates: {error}")

    def _open_latest_release(self) -> None:
        if self._latest_release_url is not None:
            QDesktopServices.openUrl(QUrl(self._latest_release_url))

    # -- rclone -----------------------------------------------------------

    def _build_rclone_section(self) -> QGroupBox:
        box = QGroupBox("rclone")
        layout = QVBoxLayout(box)

        self._rclone_status_label = QLabel()

        self._rclone_location_button = QPushButton()
        self._rclone_location_button.clicked.connect(self._on_rclone_location_clicked)

        self._rclone_use_path_button = QPushButton("Use rclone from PATH")
        self._rclone_use_path_button.clicked.connect(self._on_use_rclone_from_path_clicked)

        self._rclone_download_button = QPushButton("Download rclone…")
        self._rclone_download_button.clicked.connect(self._on_download_rclone_clicked)

        button_row = QHBoxLayout()
        button_row.addWidget(self._rclone_location_button)
        button_row.addWidget(self._rclone_use_path_button)
        button_row.addWidget(self._rclone_download_button)
        button_row.addStretch(1)

        layout.addWidget(self._rclone_status_label)
        layout.addLayout(button_row)

        self._refresh_rclone_status()
        return box

    def _refresh_rclone_status(self) -> None:
        override = settings.load_rclone_path()
        if rclone_client.is_available():
            exe = rclone_client.rclone_executable()
            self._rclone_status_label.setText(f"Found at {exe}")
        else:
            self._rclone_status_label.setText(
                f"rclone not found. Install it from {rclone_client.INSTALL_URL}, "
                "point at an existing copy, or download one below."
            )

        self._rclone_location_button.setText(
            "Change rclone Location…" if override else "Set rclone Location…"
        )
        self._rclone_use_path_button.setVisible(override is not None)

    def _on_rclone_location_clicked(self) -> None:
        if prompt_for_rclone_path(self) is not None:
            self._refresh_rclone_status()

    def _on_use_rclone_from_path_clicked(self) -> None:
        clear_rclone_path()
        self._refresh_rclone_status()

    def _on_download_rclone_clicked(self) -> None:
        self._rclone_download_button.setEnabled(False)
        self._rclone_status_label.setText("Downloading rclone…")
        dest_dir = settings.data_dir() / "rclone"
        run_in_background(
            lambda: rclone_client.download_latest(dest_dir),
            on_result=self._on_rclone_downloaded,
            on_error=self._on_rclone_download_error,
        )

    def _on_rclone_downloaded(self, path) -> None:
        self._rclone_download_button.setEnabled(True)
        self._refresh_rclone_status()

    def _on_rclone_download_error(self, error: Exception) -> None:
        self._rclone_download_button.setEnabled(True)
        self._rclone_status_label.setText(f"Couldn't download rclone: {error}")
