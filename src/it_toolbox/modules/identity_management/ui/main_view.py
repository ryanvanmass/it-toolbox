from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFormLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from it_toolbox.core import async_utils, settings
from it_toolbox.modules.identity_management import jumpcloud_client
from it_toolbox.modules.identity_management.models import Device, User

IS_JUMPCLOUD_ROOT_ROLE = Qt.ItemDataRole.UserRole
CATEGORY_ROLE = Qt.ItemDataRole.UserRole + 1
DEVICE_ROLE = Qt.ItemDataRole.UserRole + 2
USER_ROLE = Qt.ItemDataRole.UserRole + 3

CATEGORY_DEVICES = "devices"
CATEGORY_USERS = "users"

REFRESH_INTERVAL_MS = 30 * 60 * 1000  # manual refresh covers "need it sooner"


class IdentityManagementView(QWidget):
    """Browser for identity-management provider integrations (issue #15)
    -- JumpCloud is the first, with more (e.g. GAM/Google Workspace)
    expected to follow. Mirrors Connection Manager's sidebar-tree shape
    (provider as a root node, its categories as children,
    e.g. connection_manager/ui/main_view.py's GCP root -> project ->
    VMs/Buckets) rather than a provider-specific tab set, so a second
    provider means adding a sibling root, not restructuring this view
    again. One level shallower than GCP's: JumpCloud itself is the root,
    directly followed by its categories, since there's no "project" layer.

    Unlike Connection Manager's tree (pure navigation/action trigger,
    fully decoupled from its own main-content page), this module's whole
    point is browsing/inspecting device and user info -- so tree
    selection here drives a detail panel in the main content area
    directly, via a QStackedWidget of (placeholder, device detail, user
    detail) pages.

    Tree leaves are single-column (name/username only) rather than also
    showing OS/Last Contact/Email inline: a QTreeWidget has one shared
    header row for the whole tree, and Devices/Users need different
    columns that don't cleanly coexist under one header. Matches
    Connection Manager's own tree, which never hits this (VMs and
    Buckets are both single-column too) -- the detail panel is one click
    away regardless, via selection.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        # Cached in memory only for this session once successfully
        # decrypted — never re-persisted — so a passphrase-protected SSH
        # key isn't re-prompted on every single API call.
        self._cached_api_key: str | None = None
        self._selected_device: Device | None = None

        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("Search devices and users…")
        self._search_box.textChanged.connect(self._on_search_text_changed)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Providers"])
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_tree_context_menu)
        self._tree.currentItemChanged.connect(self._on_tree_selection_changed)

        self._jumpcloud_root = QTreeWidgetItem(["JumpCloud"])
        self._jumpcloud_root.setData(0, IS_JUMPCLOUD_ROOT_ROLE, True)
        self._tree.addTopLevelItem(self._jumpcloud_root)

        self._devices_category = QTreeWidgetItem(["Devices"])
        self._devices_category.setData(0, CATEGORY_ROLE, CATEGORY_DEVICES)
        self._jumpcloud_root.addChild(self._devices_category)

        self._users_category = QTreeWidgetItem(["Users"])
        self._users_category.setData(0, CATEGORY_ROLE, CATEGORY_USERS)
        self._jumpcloud_root.addChild(self._users_category)

        self._jumpcloud_root.setExpanded(True)
        self._devices_category.setExpanded(True)
        self._users_category.setExpanded(True)

        self._sidebar_widget = QWidget()
        sidebar_layout = QVBoxLayout(self._sidebar_widget)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.addWidget(self._search_box)
        sidebar_layout.addWidget(self._tree, 1)

        self._placeholder_label = QLabel("Select a device or user to see its details.")
        self._placeholder_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._placeholder_label)
        self._stack.addWidget(self._build_device_detail_panel())
        self._stack.addWidget(self._build_user_detail_panel())

        layout = QVBoxLayout(self)
        layout.addWidget(self._stack)

        # Keeps devices/users from going stale between visits, same as
        # Connection Manager's own periodic GCP refresh
        # (_gcp_refresh_timer) — a manual "Refresh" on the JumpCloud root
        # covers "I need it sooner than that."
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(REFRESH_INTERVAL_MS)
        self._refresh_timer.timeout.connect(self.refresh)
        self._refresh_timer.start()

        self.refresh()

    @property
    def sidebar_widget(self) -> QWidget:
        """The provider/category/item browser (search box + tree), hosted
        in the app sidebar (nested under this module's entry) rather than
        in this view's own layout — see
        IdentityManagementModule.create_sidebar_widget().
        """
        return self._sidebar_widget

    # -- Device detail ----------------------------------------------------

    def _build_device_detail_panel(self) -> QWidget:
        panel = QWidget()
        form = QFormLayout(panel)

        self._device_fields = {
            "hostname": QLabel(""),
            "os_version": QLabel(""),
            "serial_number": QLabel(""),
            "agent_version": QLabel(""),
            "last_contact": QLabel(""),
        }
        form.addRow("Hostname:", self._device_fields["hostname"])
        form.addRow("OS Version:", self._device_fields["os_version"])
        form.addRow("Serial Number:", self._device_fields["serial_number"])
        form.addRow("Agent Version:", self._device_fields["agent_version"])
        form.addRow("Last Contact:", self._device_fields["last_contact"])

        return panel

    def _build_user_detail_panel(self) -> QWidget:
        panel = QWidget()
        form = QFormLayout(panel)

        self._user_fields = {
            "first_name": QLabel(""),
            "last_name": QLabel(""),
            "suspended": QLabel(""),
        }
        form.addRow("First Name:", self._user_fields["first_name"])
        form.addRow("Last Name:", self._user_fields["last_name"])
        form.addRow("Suspended:", self._user_fields["suspended"])

        return panel

    def _on_tree_selection_changed(self, current: QTreeWidgetItem | None, previous) -> None:
        device: Device | None = current.data(0, DEVICE_ROLE) if current is not None else None
        user: User | None = current.data(0, USER_ROLE) if current is not None else None

        if device is not None:
            self._selected_device = device
            self._stack.setCurrentIndex(1)
            # Instant partial render from the tree item's own data, then
            # backfill the detail-only fields once get_device() resolves —
            # avoids a blank/loading flash on every click.
            self._device_fields["hostname"].setText(device.hostname)
            self._device_fields["os_version"].setText(device.os_version or "Loading…")
            self._device_fields["serial_number"].setText(device.serial_number or "Loading…")
            self._device_fields["agent_version"].setText(device.agent_version or "Loading…")
            self._device_fields["last_contact"].setText(device.last_contact or "Loading…")

            api_key = self._get_api_key()
            if api_key is None:
                return
            async_utils.run_in_background(
                lambda: jumpcloud_client.get_device(api_key, device.id),
                on_result=self._populate_device_detail,
                on_error=self._on_detail_error,
            )
        elif user is not None:
            self._selected_device = None
            self._stack.setCurrentIndex(2)
            # Unlike devices, list_users() already returns everything the
            # detail panel shows — no separate detail endpoint/async call
            # needed, just render straight from the tree item's stashed User.
            self._user_fields["first_name"].setText(user.first_name)
            self._user_fields["last_name"].setText(user.last_name)
            self._user_fields["suspended"].setText("Yes" if user.suspended else "No")
        else:
            self._selected_device = None
            self._stack.setCurrentIndex(0)

    def _populate_device_detail(self, device: Device) -> None:
        try:
            # The selection may have moved on before this resolved.
            if self._selected_device is None or self._selected_device.id != device.id:
                return
            self._device_fields["os_version"].setText(device.os_version)
            self._device_fields["serial_number"].setText(device.serial_number)
            self._device_fields["agent_version"].setText(device.agent_version)
            self._device_fields["last_contact"].setText(device.last_contact)
        except RuntimeError:
            pass  # widget torn down mid-flight

    def _on_detail_error(self, error: Exception) -> None:
        try:
            QMessageBox.warning(self, "Failed to load device details", str(error))
        except RuntimeError:
            pass  # widget torn down mid-flight

    # -- Populating the tree ------------------------------------------------

    @staticmethod
    def _show_category_placeholder(category: QTreeWidgetItem, text: str) -> None:
        category.takeChildren()
        category.addChild(QTreeWidgetItem([text]))

    def _populate_devices(self, devices: list[Device]) -> None:
        try:
            if not devices:
                self._show_category_placeholder(self._devices_category, "No devices found.")
                return
            self._devices_category.takeChildren()
            for device in devices:
                item = QTreeWidgetItem([device.display_name])
                item.setData(0, DEVICE_ROLE, device)
                self._devices_category.addChild(item)
            # Re-apply an already-typed search — a Refresh shouldn't
            # un-filter results the user was in the middle of narrowing.
            self._filter_category(self._devices_category, self._search_box.text())
        except RuntimeError:
            pass  # widget torn down mid-flight

    def _populate_users(self, users: list[User]) -> None:
        try:
            if not users:
                self._show_category_placeholder(self._users_category, "No users found.")
                return
            self._users_category.takeChildren()
            for user in users:
                item = QTreeWidgetItem([user.username])
                item.setData(0, USER_ROLE, user)
                self._users_category.addChild(item)
            self._filter_category(self._users_category, self._search_box.text())
        except RuntimeError:
            pass  # widget torn down mid-flight

    # -- Search -------------------------------------------------------------

    def _on_search_text_changed(self, text: str) -> None:
        self._filter_category(self._devices_category, text)
        self._filter_category(self._users_category, text)

    @staticmethod
    def _filter_category(category: QTreeWidgetItem, query: str) -> None:
        query = query.strip().lower()
        visible_count = 0
        for i in range(category.childCount()):
            child = category.child(i)
            is_leaf = child.data(0, DEVICE_ROLE) is not None or child.data(0, USER_ROLE) is not None
            if not is_leaf:
                # A "Loading…"/"No devices found." placeholder, not a real
                # item — only worth showing when not actively searching.
                child.setHidden(bool(query))
                continue
            matches = not query or query in child.text(0).lower()
            child.setHidden(not matches)
            if matches:
                visible_count += 1
        # Hide the whole category (rather than an empty, expandable
        # "Devices"/"Users" row with nothing under it) once a search
        # excludes everything in it.
        category.setHidden(bool(query) and visible_count == 0)

    # -- Context menu / API key / refresh -------------------------------------

    def _build_jumpcloud_root_menu(self) -> QMenu:
        """Split out from _on_tree_context_menu so tests can check the
        built menu's actions without ever calling QMenu.exec() (which
        opens a real, blocking popup with nothing to dismiss it
        headless — see app.py's _build_session_tab_menu for the same
        split, done for the same reason).
        """
        menu = QMenu(self)
        menu.addAction("Refresh").triggered.connect(self.refresh)
        return menu

    def _on_tree_context_menu(self, pos) -> None:
        item = self._tree.itemAt(pos)
        if item is None or not item.data(0, IS_JUMPCLOUD_ROOT_ROLE):
            return
        self._build_jumpcloud_root_menu().exec(self._tree.viewport().mapToGlobal(pos))

    def _get_api_key(self) -> str | None:
        if self._cached_api_key is not None:
            return self._cached_api_key
        try:
            api_key = settings.load_jumpcloud_api_key()
        except settings.SecretDecryptionError:
            passphrase, ok = QInputDialog.getText(
                self,
                "SSH Key Passphrase",
                "Your SSH key is passphrase-protected — enter its passphrase to unlock "
                "the stored JumpCloud API key:",
                QLineEdit.EchoMode.Password,
            )
            if not ok:
                return None
            try:
                api_key = settings.load_jumpcloud_api_key(passphrase=passphrase)
            except settings.SecretDecryptionError as exc:
                QMessageBox.warning(self, "JumpCloud", str(exc))
                return None
        if api_key is not None:
            self._cached_api_key = api_key
        return api_key

    def refresh(self) -> None:
        # Cleared unconditionally (not just left to _get_api_key()'s own
        # is-not-None check) so that an explicit Refresh always re-reads
        # from disk — otherwise a key changed via Settings after this
        # view already cached the old (or no) key would never be picked
        # up without restarting the app.
        self._cached_api_key = None
        api_key = self._get_api_key()
        if api_key is None:
            message = (
                "Couldn't unlock the stored JumpCloud API key — set it again in Settings."
                if settings.jumpcloud_api_key_path().is_file()
                else "No JumpCloud API key configured — set one in Settings."
            )
            self._show_category_placeholder(self._devices_category, message)
            self._show_category_placeholder(self._users_category, message)
            return

        self._show_category_placeholder(self._devices_category, "Loading…")
        self._show_category_placeholder(self._users_category, "Loading…")
        async_utils.run_in_background(
            lambda: jumpcloud_client.list_devices(api_key),
            on_result=self._populate_devices,
            on_error=self._on_load_error,
        )
        async_utils.run_in_background(
            lambda: jumpcloud_client.list_users(api_key),
            on_result=self._populate_users,
            on_error=self._on_load_error,
        )

    def _on_load_error(self, error: Exception) -> None:
        try:
            QMessageBox.warning(self, "Failed to load from JumpCloud", str(error))
        except RuntimeError:
            pass  # widget torn down mid-flight
