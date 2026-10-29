"""One Proxmox Backup Server datastore's snapshots -- the Infrastructure
module's "PBS: <host> / <datastore>" tab.

A namespace picker and a search box over a snapshot table (newest first
within each backup group). Read-only in phase 1; verify / protect /
forget arrive with phase 2's safe actions.
"""

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from it_toolbox.core import async_utils, pbs_client
from it_toolbox.core.pbs_models import Snapshot
from it_toolbox.widgets.pbs_dashboard_widget import (
    FAILED_BRUSH,
    table_item,
    make_table,
    format_bytes,
    format_time,
)

COLUMNS = ["Group", "Backup time", "Size", "Verified", "Protected", "Encrypted", "Owner", "Comment"]


def snapshot_matches(snapshot: Snapshot, text: str) -> bool:
    """The search box: matches the group ("vm/101" or just "101"), the
    comment, or the owner, case-insensitively."""
    text = text.strip().lower()
    if not text:
        return True
    haystack = (snapshot.group_label, snapshot.comment, snapshot.owner)
    return any(text in value.lower() for value in haystack)


class PbsDatastoreWidget(QWidget):
    def __init__(self, host, secret: str, store: str, ns: str = "", search: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._host = host
        self._secret = secret
        self._store = store
        self._snapshots: list[Snapshot] = []

        self._ns_combo = QComboBox()
        self._ns_combo.addItem("(root)", "")
        if ns:
            self._ns_combo.addItem(ns, ns)
            self._ns_combo.setCurrentIndex(1)
        self._ns_combo.currentIndexChanged.connect(lambda _index: self.refresh())

        self._search = QLineEdit(search)
        self._search.setPlaceholderText("Filter by VMID, group, owner or comment")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(lambda _text: self._fill_table())

        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self.refresh)

        top = QHBoxLayout()
        top.addWidget(QLabel("Namespace:"))
        top.addWidget(self._ns_combo)
        top.addWidget(self._search, 1)
        top.addWidget(refresh_button)

        self._status_label = QLabel("Loading…")
        self._table: QTableWidget = make_table(COLUMNS)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self._table, 1)
        layout.addWidget(self._status_label)

        self._load_namespaces(ns)
        self.refresh()

    @property
    def namespace(self) -> str:
        return self._ns_combo.currentData() or ""

    def set_filter(self, ns: str, search: str) -> None:
        """Used when the tree reopens this tab for another group/namespace."""
        index = self._ns_combo.findData(ns)
        if index == -1:
            self._ns_combo.addItem(ns or "(root)", ns)
            index = self._ns_combo.count() - 1
        self._search.setText(search)
        if index != self._ns_combo.currentIndex():
            self._ns_combo.setCurrentIndex(index)  # triggers refresh

    def _load_namespaces(self, selected: str) -> None:
        def done(names: list[str]) -> None:
            current = self.namespace or selected
            self._ns_combo.blockSignals(True)
            self._ns_combo.clear()
            for name in names:
                self._ns_combo.addItem(name or "(root)", name)
            index = self._ns_combo.findData(current)
            self._ns_combo.setCurrentIndex(max(index, 0))
            self._ns_combo.blockSignals(False)
            self._ns_combo.setEnabled(len(names) > 1)

        async_utils.run_in_background(
            lambda: pbs_client.list_namespaces(self._host, self._secret, self._store),
            on_result=done,
            on_error=lambda _error: None,  # the snapshot load reports errors
        )

    def refresh(self) -> None:
        self._status_label.setText("Loading…")
        ns = self.namespace
        async_utils.run_in_background(
            lambda: pbs_client.list_snapshots(self._host, self._secret, self._store, ns),
            on_result=self._on_snapshots,
            on_error=lambda error: self._status_label.setText(f"Couldn't load snapshots: {error}"),
        )

    def _on_snapshots(self, snapshots: list[Snapshot]) -> None:
        self._snapshots = snapshots
        self._fill_table()

    def _fill_table(self) -> None:
        shown = [s for s in self._snapshots if snapshot_matches(s, self._search.text())]
        table = self._table
        table.setRowCount(len(shown))
        for row, snap in enumerate(shown):
            verified = table_item({"ok": "OK", "failed": "Failed"}.get(snap.verify_state, "Not verified"))
            if snap.verify_state == "failed":
                verified.setForeground(FAILED_BRUSH)
            group = table_item(snap.group_label)
            group.setToolTip("\n".join(snap.files))
            table.setItem(row, 0, group)
            table.setItem(row, 1, table_item(format_time(snap.backup_time)))
            table.setItem(row, 2, table_item(format_bytes(snap.size)))
            table.setItem(row, 3, verified)
            table.setItem(row, 4, table_item("Yes" if snap.protected else ""))
            table.setItem(row, 5, table_item("Yes" if snap.encrypted else ""))
            table.setItem(row, 6, table_item(snap.owner))
            table.setItem(row, 7, table_item(snap.comment))
        total = sum(s.size or 0 for s in shown)
        groups = len({s.group_label for s in shown})
        self._status_label.setText(
            f"{len(shown)} snapshot{'s' if len(shown) != 1 else ''} in {groups} group{'s' if groups != 1 else ''}"
            f", {format_bytes(total)} before deduplication"
            + (f" (filtered from {len(self._snapshots)})" if len(shown) != len(self._snapshots) else "")
        )

    def close_session(self) -> None:
        pass
