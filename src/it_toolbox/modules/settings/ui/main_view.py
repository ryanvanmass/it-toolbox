"""App-wide Settings page — a single scrollable page, not tab/session-based
like the other modules, so it never touches the shared session-tab pane.
"""

import os
import platform
import subprocess
from pathlib import Path

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
from it_toolbox.core.auth import gcp_auth
from it_toolbox.modules.connection_manager import qemu_client
from it_toolbox.widgets.rclone_location_picker import clear_rclone_path, prompt_for_rclone_path

# FreeRDP DLL loading happens as an import-time side effect in
# core/rdp/freerdp_client.py (raises OSError there if the libraries
# aren't found), so — same reasoning as the SpiceWidget/PyGObject import
# guard above it in connection_manager/ui/main_view.py — this can't be a
# plain top-level import without risking crashing the whole Settings page
# (and thus the whole app) on any machine without FreeRDP installed.
try:
    from it_toolbox.core.rdp import freerdp_client
except (ImportError, OSError):
    freerdp_client = None

_FREERDP_FETCH_SCRIPT = Path(__file__).resolve().parents[5] / "scripts" / "fetch_freerdp_windows.ps1"
_FREERDP_DEST_DIR_ENV = "IT_TOOLBOX_FREERDP_DIR"


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
        self._content_layout.addWidget(self._build_gcloud_section())
        self._content_layout.addWidget(self._build_qemu_section())
        self._content_layout.addWidget(self._build_freerdp_section())
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

    # -- gcloud -------------------------------------------------------------

    def _build_gcloud_section(self) -> QGroupBox:
        box = QGroupBox("gcloud")
        layout = QVBoxLayout(box)

        self._gcloud_status_label = QLabel()

        self._gcloud_sign_in_button = QPushButton("Sign In…")
        self._gcloud_sign_in_button.clicked.connect(self._on_gcloud_sign_in_clicked)

        self._gcloud_sign_out_button = QPushButton("Sign Out")
        self._gcloud_sign_out_button.clicked.connect(self._on_gcloud_sign_out_clicked)

        button_row = QHBoxLayout()
        button_row.addWidget(self._gcloud_sign_in_button)
        button_row.addWidget(self._gcloud_sign_out_button)
        button_row.addStretch(1)

        layout.addWidget(self._gcloud_status_label)
        layout.addLayout(button_row)

        if gcp_auth.is_available():
            self._gcloud_status_label.setText("Checking sign-in status…")
            self._gcloud_sign_in_button.setEnabled(False)
            self._gcloud_sign_out_button.setEnabled(False)
            run_in_background(
                gcp_auth.get_active_account,
                on_result=self._set_gcloud_account,
                on_error=lambda error: self._set_gcloud_account(None),
            )
        else:
            self._gcloud_status_label.setText(
                f"gcloud CLI not found. Install it from {gcp_auth.INSTALL_URL} and relaunch."
            )
            self._gcloud_sign_in_button.setEnabled(False)
            self._gcloud_sign_out_button.setEnabled(False)

        return box

    def _set_gcloud_account(self, account: str | None) -> None:
        self._gcloud_sign_in_button.setEnabled(True)
        self._gcloud_sign_out_button.setEnabled(account is not None)
        if account is not None:
            self._gcloud_status_label.setText(f"Signed in as {account}")
        else:
            self._gcloud_status_label.setText("Not signed in")

    def _on_gcloud_sign_in_clicked(self) -> None:
        self._gcloud_sign_in_button.setEnabled(False)
        self._gcloud_status_label.setText("Signing in…")
        run_in_background(
            gcp_auth.sign_in,
            on_result=self._set_gcloud_account,
            on_error=self._on_gcloud_error,
        )

    def _on_gcloud_sign_out_clicked(self) -> None:
        self._gcloud_sign_out_button.setEnabled(False)
        self._gcloud_status_label.setText("Signing out…")
        run_in_background(
            gcp_auth.sign_out,
            on_result=lambda _: self._set_gcloud_account(None),
            on_error=self._on_gcloud_error,
        )

    def _on_gcloud_error(self, error: Exception) -> None:
        self._gcloud_sign_in_button.setEnabled(True)
        self._gcloud_sign_out_button.setEnabled(True)
        self._gcloud_status_label.setText(f"gcloud error: {error}")

    # -- QEMU/libvirt ---------------------------------------------------------

    def _build_qemu_section(self) -> QGroupBox:
        box = QGroupBox("QEMU / libvirt")
        layout = QVBoxLayout(box)

        if platform.system() != "Linux":
            self._qemu_status_label = QLabel("Not applicable on this platform.")
            layout.addWidget(self._qemu_status_label)
            return box

        if qemu_client.is_available():
            self._qemu_status_label = QLabel(
                "virsh found — QEMU/libvirt host connections are available."
            )
        else:
            self._qemu_status_label = QLabel(
                "virsh not found. It's a system package, not something this app can "
                "download — install it via your distro's package manager, e.g.:\n"
                "  Debian/Ubuntu: sudo apt install libvirt-clients\n"
                "  Fedora/RHEL:   sudo dnf install libvirt-client"
            )
        layout.addWidget(self._qemu_status_label)

        return box

    # -- FreeRDP (Windows) ------------------------------------------------

    def _build_freerdp_section(self) -> QGroupBox:
        box = QGroupBox("FreeRDP (Windows)")
        layout = QVBoxLayout(box)

        if platform.system() != "Windows":
            self._freerdp_status_label = QLabel("Not applicable on this platform.")
            layout.addWidget(self._freerdp_status_label)
            return box

        self._freerdp_status_label = QLabel()
        layout.addWidget(self._freerdp_status_label)

        self._freerdp_fetch_button = QPushButton("Fetch FreeRDP DLLs")
        self._freerdp_fetch_button.clicked.connect(self._on_fetch_freerdp_clicked)
        layout.addWidget(self._freerdp_fetch_button)

        self._refresh_freerdp_status()
        return box

    def _refresh_freerdp_status(self) -> None:
        if freerdp_client is not None:
            self._freerdp_status_label.setText("FreeRDP libraries loaded — embedded RDP is available.")
            self._freerdp_fetch_button.setText("Re-fetch FreeRDP DLLs")
        else:
            self._freerdp_status_label.setText(
                "FreeRDP libraries not found — embedded RDP sessions won't work until "
                "these are fetched (or built manually, see docs/windows-freerdp-setup.md)."
            )
            self._freerdp_fetch_button.setText("Fetch FreeRDP DLLs")

    def _on_fetch_freerdp_clicked(self) -> None:
        if not _FREERDP_FETCH_SCRIPT.is_file():
            self._freerdp_status_label.setText(
                f"Fetch script not found at {_FREERDP_FETCH_SCRIPT} — this app installation "
                "doesn't include it. Download it manually from the it-toolbox repo's scripts/ "
                "folder, or build FreeRDP yourself (docs/windows-freerdp-setup.md)."
            )
            return

        self._freerdp_fetch_button.setEnabled(False)
        self._freerdp_status_label.setText("Fetching FreeRDP DLLs…")
        run_in_background(
            self._run_freerdp_fetch_script,
            on_result=self._on_freerdp_fetched,
            on_error=self._on_freerdp_fetch_error,
        )

    def _run_freerdp_fetch_script(self) -> Path:
        result = subprocess.run(
            ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(_FREERDP_FETCH_SCRIPT)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "fetch_freerdp_windows.ps1 failed")
        dest_dir = Path(os.environ["LOCALAPPDATA"]) / "it-toolbox" / "freerdp"
        return dest_dir

    def _on_freerdp_fetched(self, dest_dir: Path) -> None:
        self._freerdp_fetch_button.setEnabled(True)
        # The script only persists IT_TOOLBOX_FREERDP_DIR for *future*
        # processes (a User-scope env var) — set it here too so this
        # already-running process picks it up without a restart, then
        # retry the import (freerdp_client isn't left in a half-imported
        # state in sys.modules after its earlier OSError, so a fresh
        # import genuinely re-runs its DLL-loading from scratch).
        os.environ[_FREERDP_DEST_DIR_ENV] = str(dest_dir)
        global freerdp_client
        try:
            from it_toolbox.core.rdp import freerdp_client as _freerdp_client

            freerdp_client = _freerdp_client
        except (ImportError, OSError) as exc:
            self._freerdp_status_label.setText(f"Fetched DLLs, but still couldn't load them: {exc}")
            return
        self._refresh_freerdp_status()

    def _on_freerdp_fetch_error(self, error: Exception) -> None:
        self._freerdp_fetch_button.setEnabled(True)
        self._freerdp_status_label.setText(f"Couldn't fetch FreeRDP DLLs: {error}")
