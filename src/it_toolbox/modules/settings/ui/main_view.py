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

from it_toolbox.core import update_checker
from it_toolbox.core.async_utils import run_in_background


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
