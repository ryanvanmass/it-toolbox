from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFormLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
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

# self._stack page indices.
PAGE_PLACEHOLDER = 0
PAGE_DEVICE_DETAIL = 1
PAGE_USER_DETAIL = 2
PAGE_DEVICES_TABLE = 3
PAGE_USERS_TABLE = 4


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

    The tree itself stays deliberately uncluttered: Devices/Users
    categories never list every item as a permanent child (an org with
    hundreds of devices would make the tree unusable) -- clicking a
    category instead shows a full table of everything in the main
    content area. Tree leaves only ever exist as live search results
    (see the search box), letting a match be opened directly without
    hunting through the table. Selecting a leaf (search result or table
    row) drives a detail panel in the main content area -- a genuinely
    new UI idiom for this app otherwise, since Connection Manager's own
    tree is a pure navigation/action trigger, fully decoupled from its
    own main-content page.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        # Cached in memory only for this session once successfully
        # decrypted — never re-persisted — so a passphrase-protected SSH
        # key isn't re-prompted on every single API call.
        self._cached_api_key: str | None = None
        self._selected_device: Device | None = None
        # The full lists from the last successful refresh — backs both
        # the Devices/Users tables and the search box, independent of
        # whatever the tree currently displays.
        self._devices: list[Device] = []
        self._users: list[User] = []

        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("Search devices and users…")
        self._search_box.textChanged.connect(self._on_search_text_changed)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Providers"])
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_tree_context_menu)
        # itemClicked (not currentItemChanged) so re-clicking a category
        # that's already selected still switches back to its table --
        # e.g. after drilling into a search result's detail view, which
        # changes self._stack's page without changing the tree's own
        # selection at all.
        self._tree.itemClicked.connect(self._on_tree_item_clicked)

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

        self._placeholder_label = QLabel(
            'Select "Devices" or "Users" to browse all of them, or search to '
            "jump straight to one."
        )
        self._placeholder_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder_label.setWordWrap(True)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._placeholder_label)
        self._stack.addWidget(self._build_device_detail_panel())
        self._stack.addWidget(self._build_user_detail_panel())
        self._stack.addWidget(self._build_devices_table_page())
        self._stack.addWidget(self._build_users_table_page())

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

    # -- Devices/Users tables (the "browse everything" view) ------------------

    def _build_devices_table_page(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)

        self._devices_table_status_label = QLabel("")
        self._devices_table_status_label.setWordWrap(True)
        layout.addWidget(self._devices_table_status_label)

        self._devices_table = QTableWidget(0, 3)
        self._devices_table.setHorizontalHeaderLabels(["Name", "OS", "Last Contact"])
        self._devices_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._devices_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        devices_header = self._devices_table.horizontalHeader()
        devices_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        devices_header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        devices_header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._devices_table.currentCellChanged.connect(self._on_devices_table_selection_changed)
        layout.addWidget(self._devices_table)

        return container

    def _build_users_table_page(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)

        self._users_table_status_label = QLabel("")
        self._users_table_status_label.setWordWrap(True)
        layout.addWidget(self._users_table_status_label)

        self._users_table = QTableWidget(0, 2)
        self._users_table.setHorizontalHeaderLabels(["Username", "Email"])
        self._users_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._users_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        users_header = self._users_table.horizontalHeader()
        users_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        users_header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._users_table.currentCellChanged.connect(self._on_users_table_selection_changed)
        layout.addWidget(self._users_table)

        return container

    def _on_devices_table_selection_changed(
        self, current_row: int, current_col: int, previous_row: int, previous_col: int
    ) -> None:
        if current_row < 0:
            return
        item = self._devices_table.item(current_row, 0)
        device = item.data(DEVICE_ROLE) if item is not None else None
        if device is not None:
            self._show_device_detail(device)

    def _on_users_table_selection_changed(
        self, current_row: int, current_col: int, previous_row: int, previous_col: int
    ) -> None:
        if current_row < 0:
            return
        item = self._users_table.item(current_row, 0)
        user = item.data(USER_ROLE) if item is not None else None
        if user is not None:
            self._show_user_detail(user)

    # -- Device/user detail -----------------------------------------------

    def _build_device_detail_panel(self) -> QWidget:
        panel = QWidget()
        form = QFormLayout(panel)

        self._device_fields = {
            "hostname": QLabel(""),
            "status": QLabel(""),
            "os_version": QLabel(""),
            "arch": QLabel(""),
            "serial_number": QLabel(""),
            "agent_version": QLabel(""),
            "remote_ip": QLabel(""),
            "last_contact": QLabel(""),
            "created": QLabel(""),
            "description": QLabel(""),
        }
        self._device_fields["description"].setWordWrap(True)
        form.addRow("Hostname:", self._device_fields["hostname"])
        form.addRow("Status:", self._device_fields["status"])
        form.addRow("OS Version:", self._device_fields["os_version"])
        form.addRow("Architecture:", self._device_fields["arch"])
        form.addRow("Serial Number:", self._device_fields["serial_number"])
        form.addRow("Agent Version:", self._device_fields["agent_version"])
        form.addRow("Remote IP:", self._device_fields["remote_ip"])
        form.addRow("Last Contact:", self._device_fields["last_contact"])
        form.addRow("Enrolled:", self._device_fields["created"])
        form.addRow("Description:", self._device_fields["description"])

        return panel

    def _build_user_detail_panel(self) -> QWidget:
        panel = QWidget()
        form = QFormLayout(panel)

        self._user_fields = {
            "email": QLabel(""),
            "first_name": QLabel(""),
            "last_name": QLabel(""),
            "job_title": QLabel(""),
            "department": QLabel(""),
            "activated": QLabel(""),
            "suspended": QLabel(""),
            "mfa_configured": QLabel(""),
            "created": QLabel(""),
        }
        form.addRow("Email:", self._user_fields["email"])
        form.addRow("First Name:", self._user_fields["first_name"])
        form.addRow("Last Name:", self._user_fields["last_name"])
        form.addRow("Job Title:", self._user_fields["job_title"])
        form.addRow("Department:", self._user_fields["department"])
        form.addRow("Activated:", self._user_fields["activated"])
        form.addRow("Suspended:", self._user_fields["suspended"])
        form.addRow("MFA Configured:", self._user_fields["mfa_configured"])
        form.addRow("Created:", self._user_fields["created"])

        return panel

    def _show_device_detail(self, device: Device) -> None:
        self._selected_device = device
        self._stack.setCurrentIndex(PAGE_DEVICE_DETAIL)
        # Instant partial render from already-known data (only
        # hostname/status/last_contact come from the list call), then
        # backfill the rest once get_device() resolves — avoids a
        # blank/loading flash on every click.
        self._device_fields["hostname"].setText(device.hostname)
        self._device_fields["status"].setText("Active" if device.active else "Inactive")
        self._device_fields["os_version"].setText(device.os_version or "Loading…")
        self._device_fields["arch"].setText(device.arch or "Loading…")
        self._device_fields["serial_number"].setText(device.serial_number or "Loading…")
        self._device_fields["agent_version"].setText(device.agent_version or "Loading…")
        self._device_fields["remote_ip"].setText(device.remote_ip or "Loading…")
        self._device_fields["last_contact"].setText(device.last_contact or "Loading…")
        self._device_fields["created"].setText(device.created or "Loading…")
        self._device_fields["description"].setText(device.description or "Loading…")

        api_key = self._get_api_key()
        if api_key is None:
            return
        async_utils.run_in_background(
            lambda: jumpcloud_client.get_device(api_key, device.id),
            on_result=self._populate_device_detail,
            on_error=self._on_detail_error,
        )

    def _show_user_detail(self, user: User) -> None:
        # Unlike devices, list_users() already returns everything the
        # detail panel shows — no separate detail endpoint/async call
        # needed, just render straight from the given User.
        self._selected_device = None
        self._stack.setCurrentIndex(PAGE_USER_DETAIL)
        self._user_fields["email"].setText(user.email)
        self._user_fields["first_name"].setText(user.first_name)
        self._user_fields["last_name"].setText(user.last_name)
        self._user_fields["job_title"].setText(user.job_title or "—")
        self._user_fields["department"].setText(user.department or "—")
        self._user_fields["activated"].setText("Yes" if user.activated else "No")
        self._user_fields["suspended"].setText("Yes" if user.suspended else "No")
        self._user_fields["mfa_configured"].setText("Yes" if user.mfa_configured else "No")
        self._user_fields["created"].setText(user.created or "—")

    def _on_tree_item_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        device: Device | None = item.data(0, DEVICE_ROLE)
        user: User | None = item.data(0, USER_ROLE)
        category = item.data(0, CATEGORY_ROLE)

        if device is not None:
            self._show_device_detail(device)
        elif user is not None:
            self._show_user_detail(user)
        elif category == CATEGORY_DEVICES:
            self._stack.setCurrentIndex(PAGE_DEVICES_TABLE)
        elif category == CATEGORY_USERS:
            self._stack.setCurrentIndex(PAGE_USERS_TABLE)
        else:
            self._stack.setCurrentIndex(PAGE_PLACEHOLDER)

    def _populate_device_detail(self, device: Device) -> None:
        try:
            # The selection may have moved on before this resolved.
            if self._selected_device is None or self._selected_device.id != device.id:
                return
            self._device_fields["os_version"].setText(device.os_version or "—")
            self._device_fields["arch"].setText(device.arch or "—")
            self._device_fields["serial_number"].setText(device.serial_number or "—")
            self._device_fields["agent_version"].setText(device.agent_version or "—")
            self._device_fields["remote_ip"].setText(device.remote_ip or "—")
            self._device_fields["last_contact"].setText(device.last_contact or "—")
            self._device_fields["created"].setText(device.created or "—")
            self._device_fields["description"].setText(device.description or "—")
        except RuntimeError:
            pass  # widget torn down mid-flight

    def _on_detail_error(self, error: Exception) -> None:
        try:
            QMessageBox.warning(self, "Failed to load device details", str(error))
        except RuntimeError:
            pass  # widget torn down mid-flight

    # -- Populating from JumpCloud --------------------------------------------

    def _populate_devices(self, devices: list[Device]) -> None:
        try:
            self._devices = devices
            self._devices_table_status_label.setText("" if devices else "No devices found.")
            self._devices_table.setRowCount(len(devices))
            for row, device in enumerate(devices):
                name_item = QTableWidgetItem(device.display_name)
                name_item.setData(DEVICE_ROLE, device)
                self._devices_table.setItem(row, 0, name_item)
                self._devices_table.setItem(row, 1, QTableWidgetItem(device.os))
                self._devices_table.setItem(row, 2, QTableWidgetItem(device.last_contact))
            # Re-apply an already-typed search — a Refresh shouldn't
            # un-filter results the user was in the middle of narrowing.
            self._on_search_text_changed(self._search_box.text())
        except RuntimeError:
            pass  # widget torn down mid-flight

    def _populate_users(self, users: list[User]) -> None:
        try:
            self._users = users
            self._users_table_status_label.setText("" if users else "No users found.")
            self._users_table.setRowCount(len(users))
            for row, user in enumerate(users):
                username_item = QTableWidgetItem(user.username)
                username_item.setData(USER_ROLE, user)
                self._users_table.setItem(row, 0, username_item)
                self._users_table.setItem(row, 1, QTableWidgetItem(user.email))
            self._on_search_text_changed(self._search_box.text())
        except RuntimeError:
            pass  # widget torn down mid-flight

    # -- Search -------------------------------------------------------------
    #
    # The tree never lists every device/user as a permanent child (see the
    # class docstring) — search results are the *only* tree leaves that
    # ever exist, materialized fresh on every keystroke from self._devices/
    # self._users rather than filtered in place.

    def _on_search_text_changed(self, text: str) -> None:
        query = text.strip().lower()
        self._rebuild_search_results(
            self._devices_category, self._devices, lambda d: d.display_name, DEVICE_ROLE, query
        )
        self._rebuild_search_results(
            self._users_category, self._users, lambda u: u.username, USER_ROLE, query
        )

    @staticmethod
    def _rebuild_search_results(category, items, label_fn, role, query: str) -> None:
        category.takeChildren()
        if not query:
            category.setHidden(False)
            return
        matches = [item for item in items if query in label_fn(item).lower()]
        for item in matches:
            leaf = QTreeWidgetItem([label_fn(item)])
            leaf.setData(0, role, item)
            category.addChild(leaf)
        # Hide the whole category (rather than an empty, expandable
        # "Devices"/"Users" row with nothing under it) once a search
        # excludes everything in it.
        category.setHidden(not matches)

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
            self._devices = []
            self._users = []
            self._devices_table.setRowCount(0)
            self._users_table.setRowCount(0)
            self._devices_table_status_label.setText(message)
            self._users_table_status_label.setText(message)
            self._on_search_text_changed(self._search_box.text())
            return

        self._devices_table_status_label.setText("Loading…")
        self._users_table_status_label.setText("Loading…")
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
