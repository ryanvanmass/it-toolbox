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
    QComboBox,
    QFileDialog,
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
from it_toolbox.modules.identity_management.ui.api_key_dialog import ApiKeyDialog
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

# (dropdown label, stored value) — None means "match window size", the
# default. See settings.load_default_rdp_resolution()'s docstring for why
# a fixed choice exists at all.
RDP_RESOLUTION_PRESETS: list[tuple[str, tuple[int, int] | None]] = [
    ("Match window size", None),
    ("1280 × 720", (1280, 720)),
    ("1920 × 1080", (1920, 1080)),
    ("2560 × 1440", (2560, 1440)),
    ("3840 × 2160", (3840, 2160)),
]

# (dropdown label, stored value) — see
# settings.load_default_double_click_action()'s docstring for exactly
# when this is consulted.
DOUBLE_CLICK_ACTION_PRESETS: list[tuple[str, str]] = [
    ("Ask each time", "ask"),
    ("RDP", "rdp"),
    ("SSH", "ssh"),
]

# (dropdown label, stored value) — None means the default monospace size
# (TerminalWidget leaves the font's point size unset). See
# settings.load_terminal_font_size()'s docstring.
TERMINAL_FONT_SIZE_PRESETS: list[tuple[str, int | None]] = [
    ("Default", None),
    ("10", 10),
    ("12", 12),
    ("14", 14),
    ("16", 16),
    ("18", 18),
    ("20", 20),
]

# (dropdown label, stored value) — the Windows keyboard layout ID declared
# to the RDP server (see settings.load_rdp_keyboard_layout()'s docstring).
# The *server* needs the declared layout actually installed to interpret
# scancodes with it, so this is only worth changing away from English (US)
# when a specific target VM doesn't have that layout available -- not an
# attempt to cover every layout in existence.
RDP_KEYBOARD_LAYOUT_PRESETS: list[tuple[str, int]] = [
    ("English (US)", 0x0409),
    ("English (UK)", 0x0809),
    ("French", 0x040C),
    ("German", 0x0407),
    ("Spanish", 0x040A),
    ("Italian", 0x0410),
    ("Portuguese (Brazil)", 0x0416),
    ("Dutch", 0x0413),
    ("Swedish", 0x041D),
    ("Japanese", 0x0411),
]


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
        self._content_layout.addWidget(self._build_gcp_ssh_key_section())
        self._content_layout.addWidget(self._build_jumpcloud_section())
        self._content_layout.addWidget(self._build_qemu_section())
        self._content_layout.addWidget(self._build_rdp_display_section())
        self._content_layout.addWidget(self._build_rdp_keyboard_layout_section())
        self._content_layout.addWidget(self._build_terminal_font_size_section())
        self._content_layout.addWidget(self._build_double_click_action_section())
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

    # -- GCP SSH key ------------------------------------------------------------

    def _build_gcp_ssh_key_section(self) -> QGroupBox:
        box = QGroupBox("GCP SSH Key")
        layout = QVBoxLayout(box)

        self._gcp_ssh_key_status_label = QLabel()
        self._gcp_ssh_key_status_label.setWordWrap(True)
        layout.addWidget(self._gcp_ssh_key_status_label)

        self._gcp_ssh_key_button = QPushButton()
        self._gcp_ssh_key_button.clicked.connect(self._on_set_gcp_ssh_key_clicked)

        self._gcp_ssh_key_clear_button = QPushButton("Use Default (~/.ssh)")
        self._gcp_ssh_key_clear_button.clicked.connect(self._on_clear_gcp_ssh_key_clicked)

        button_row = QHBoxLayout()
        button_row.addWidget(self._gcp_ssh_key_button)
        button_row.addWidget(self._gcp_ssh_key_clear_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        self._refresh_gcp_ssh_key_status()
        return box

    def _refresh_gcp_ssh_key_status(self) -> None:
        override = settings.load_gcp_ssh_key_path()
        public_key = settings.resolve_gcp_ssh_public_key()
        if public_key is not None:
            source = f"configured key ({override})" if override else "default (~/.ssh)"
            preview = public_key if len(public_key) <= 60 else f"{public_key[:60]}…"
            self._gcp_ssh_key_status_label.setText(
                f"Prefilled in Connection Manager's \"Upload Public Key…\" action, from "
                f"the {source}:\n{preview}"
            )
        else:
            self._gcp_ssh_key_status_label.setText(
                "No SSH public key found — set one below, or place one at "
                "~/.ssh/id_ed25519.pub or ~/.ssh/id_rsa.pub."
            )
        self._gcp_ssh_key_button.setText("Change Key…" if override else "Set Key…")
        self._gcp_ssh_key_clear_button.setVisible(override is not None)

    def _on_set_gcp_ssh_key_clicked(self) -> None:
        current = settings.load_gcp_ssh_key_path()
        start_dir = str(current) if current else str(Path.home() / ".ssh")
        path, _ = QFileDialog.getOpenFileName(self, "Locate your SSH public key", start_dir)
        if not path:
            return
        settings.save_gcp_ssh_key_path(path)
        self._refresh_gcp_ssh_key_status()

    def _on_clear_gcp_ssh_key_clicked(self) -> None:
        settings.save_gcp_ssh_key_path(None)
        self._refresh_gcp_ssh_key_status()

    # -- JumpCloud ------------------------------------------------------------

    def _build_jumpcloud_section(self) -> QGroupBox:
        box = QGroupBox("JumpCloud")
        layout = QVBoxLayout(box)

        self._jumpcloud_status_label = QLabel()
        self._jumpcloud_status_label.setWordWrap(True)
        layout.addWidget(self._jumpcloud_status_label)

        self._jumpcloud_key_button = QPushButton()
        self._jumpcloud_key_button.clicked.connect(self._on_set_jumpcloud_key_clicked)
        layout.addWidget(self._jumpcloud_key_button)

        self._refresh_jumpcloud_status()
        return box

    def _refresh_jumpcloud_status(self) -> None:
        configured = settings.jumpcloud_api_key_path().is_file()
        self._jumpcloud_status_label.setText(
            "API key configured — used by the Identity Management module."
            if configured
            else "No API key configured yet — needed by the Identity Management module."
        )
        self._jumpcloud_key_button.setText(
            "Change JumpCloud API Key…" if configured else "Set JumpCloud API Key…"
        )

    def _on_set_jumpcloud_key_clicked(self) -> None:
        dialog = ApiKeyDialog(parent=self)
        if dialog.exec() == ApiKeyDialog.DialogCode.Accepted:
            self._refresh_jumpcloud_status()

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

    # -- RDP display --------------------------------------------------------

    def _build_rdp_display_section(self) -> QGroupBox:
        box = QGroupBox("RDP Display")
        layout = QVBoxLayout(box)

        description = QLabel(
            "Resolution requested for embedded RDP sessions (Connect via RDP). A "
            "fixed size is requested once at connect and never changes with the "
            "window — the display just stretches to fit — instead of matching the "
            "window size on every resize, which can be slow to redraw over a slow "
            "connection."
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        self._rdp_resolution_combo = QComboBox()
        for label, _ in RDP_RESOLUTION_PRESETS:
            self._rdp_resolution_combo.addItem(label)

        current = settings.load_default_rdp_resolution()
        for index, (_, value) in enumerate(RDP_RESOLUTION_PRESETS):
            if value == current:
                self._rdp_resolution_combo.setCurrentIndex(index)
                break

        self._rdp_resolution_combo.currentIndexChanged.connect(self._on_rdp_resolution_changed)
        layout.addWidget(self._rdp_resolution_combo)
        return box

    def _on_rdp_resolution_changed(self, index: int) -> None:
        _, resolution = RDP_RESOLUTION_PRESETS[index]
        settings.save_default_rdp_resolution(resolution)

    # -- RDP keyboard layout --------------------------------------------------

    def _build_rdp_keyboard_layout_section(self) -> QGroupBox:
        box = QGroupBox("RDP Keyboard Layout")
        layout = QVBoxLayout(box)

        description = QLabel(
            "Keyboard layout declared to the RDP server for embedded RDP sessions. "
            "English (US) works for most VMs, but the server needs that layout "
            "actually installed to interpret keystrokes with it — a non-English "
            "Windows image may not have it, which shows up as Shift+punctuation "
            "(e.g. \" or :) typing the wrong character or nothing at all. Change "
            "this only if that happens on a specific VM."
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        self._rdp_keyboard_layout_combo = QComboBox()
        for label, _ in RDP_KEYBOARD_LAYOUT_PRESETS:
            self._rdp_keyboard_layout_combo.addItem(label)

        current = settings.load_rdp_keyboard_layout()
        for index, (_, value) in enumerate(RDP_KEYBOARD_LAYOUT_PRESETS):
            if value == current:
                self._rdp_keyboard_layout_combo.setCurrentIndex(index)
                break

        self._rdp_keyboard_layout_combo.currentIndexChanged.connect(
            self._on_rdp_keyboard_layout_changed
        )
        layout.addWidget(self._rdp_keyboard_layout_combo)
        return box

    def _on_rdp_keyboard_layout_changed(self, index: int) -> None:
        _, layout_id = RDP_KEYBOARD_LAYOUT_PRESETS[index]
        settings.save_rdp_keyboard_layout(layout_id)

    # -- Terminal font size ---------------------------------------------------

    def _build_terminal_font_size_section(self) -> QGroupBox:
        box = QGroupBox("Terminal Font Size")
        layout = QVBoxLayout(box)

        description = QLabel(
            "Font size for embedded terminal sessions — both Shell Launcher and "
            "Connection Manager's Connect via SSH. Applies to new sessions; already-open "
            "terminal tabs keep the size they were opened with."
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        self._terminal_font_size_combo = QComboBox()
        for label, _ in TERMINAL_FONT_SIZE_PRESETS:
            self._terminal_font_size_combo.addItem(label)

        current = settings.load_terminal_font_size()
        for index, (_, value) in enumerate(TERMINAL_FONT_SIZE_PRESETS):
            if value == current:
                self._terminal_font_size_combo.setCurrentIndex(index)
                break

        self._terminal_font_size_combo.currentIndexChanged.connect(
            self._on_terminal_font_size_changed
        )
        layout.addWidget(self._terminal_font_size_combo)
        return box

    def _on_terminal_font_size_changed(self, index: int) -> None:
        _, size = TERMINAL_FONT_SIZE_PRESETS[index]
        settings.save_terminal_font_size(size)

    # -- Double-click action --------------------------------------------------

    def _build_double_click_action_section(self) -> QGroupBox:
        box = QGroupBox("Double-Click Action")
        layout = QVBoxLayout(box)

        description = QLabel(
            "Default connection type when double-clicking a GCP instance whose "
            "OS couldn't be detected from its boot disk. Manual connections always "
            "use their own configured type, and QEMU VMs always launch SPICE, so "
            "neither is affected by this setting."
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        self._double_click_action_combo = QComboBox()
        for label, _ in DOUBLE_CLICK_ACTION_PRESETS:
            self._double_click_action_combo.addItem(label)

        current = settings.load_default_double_click_action()
        for index, (_, value) in enumerate(DOUBLE_CLICK_ACTION_PRESETS):
            if value == current:
                self._double_click_action_combo.setCurrentIndex(index)
                break

        self._double_click_action_combo.currentIndexChanged.connect(
            self._on_double_click_action_changed
        )
        layout.addWidget(self._double_click_action_combo)
        return box

    def _on_double_click_action_changed(self, index: int) -> None:
        _, action = DOUBLE_CLICK_ACTION_PRESETS[index]
        settings.save_default_double_click_action(action)

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
