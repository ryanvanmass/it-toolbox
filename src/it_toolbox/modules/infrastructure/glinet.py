"""GL.iNet routers in the Infrastructure module (they used to be a root in
Connection Manager). Each host opens the existing GL.iNet dashboard
(widgets/glinet_dashboard_widget.py) through glinet_client, which needs
the optional, not-bundled python-glinet package -- see
docs/glinet-dashboard-status.md.

The saved hosts stay in glinet_hosts.json, the file Connection Manager
used, rewritten once into the shared InfrastructureHost shape by
migrate_legacy_hosts(): username -> token_id, password_encrypted ->
secret_encrypted (the same age ciphertext, to the same default SSH key),
and the "/rpc" suffix moved out of the URL.
"""

from PySide6.QtWidgets import QTreeWidgetItem, QWidget

from it_toolbox.core import settings
from it_toolbox.core.infrastructure_hosts import InfrastructureHost
from it_toolbox.modules.connection_manager import glinet_client
from it_toolbox.modules.connection_manager.models import GlinetHost
from it_toolbox.modules.infrastructure.product import InfrastructureProduct
from it_toolbox.widgets.glinet_dashboard_widget import GlinetDashboardWidget

PRODUCT_ID = "glinet"
RPC_PATH = "/rpc"


def to_glinet_host(host: InfrastructureHost) -> GlinetHost:
    """The shape glinet_client and the dashboard take. The secret stays
    out of it -- they're handed the decrypted password separately."""
    return GlinetHost(
        name=host.name,
        url=host.url.rstrip("/") + RPC_PATH,
        username=host.token_id or "root",
        verify_ssl=host.verify_ssl,
    )


def _is_legacy(entry: dict) -> bool:
    return "token_id" not in entry and ("username" in entry or "password_encrypted" in entry)


def migrate_legacy_entry(entry: dict) -> dict:
    url = str(entry.get("url") or "").rstrip("/")
    if url.endswith(RPC_PATH):
        url = url[: -len(RPC_PATH)]
    return {
        "name": entry.get("name") or url,
        "url": url,
        "token_id": entry.get("username") or "root",
        "secret_encrypted": entry.get("password_encrypted"),
        "verify_ssl": bool(entry.get("verify_ssl", False)),
        "fingerprint": None,
        "ssh_username": "root",
    }


def migrate_legacy_hosts() -> None:
    """Rewrites Connection Manager-era entries in glinet_hosts.json in
    place. Already-migrated entries are left alone, so this is safe to
    run on every start."""
    entries = settings.load_infrastructure_hosts(PRODUCT_ID)
    if not any(isinstance(e, dict) and _is_legacy(e) for e in entries):
        return
    settings.save_infrastructure_hosts(
        PRODUCT_ID,
        [migrate_legacy_entry(e) if isinstance(e, dict) and _is_legacy(e) else e for e in entries],
    )


class GlinetProduct(InfrastructureProduct):
    id = PRODUCT_ID
    display_name = "GL.iNet"
    default_port = 443
    token_id_label = "Username:"
    token_id_placeholder = "root"
    secret_label = "Password:"
    url_placeholder = "https://192.168.8.1"
    token_help = (
        "The router's admin login (firmware 4.0 or later). Needs python-glinet, which isn't "
        "bundled: pip install python-glinet."
    )

    def __init__(self, view) -> None:
        super().__init__(view)
        migrate_legacy_hosts()

    def test_connection(self, host: InfrastructureHost, secret: str) -> str:
        glinet_host = to_glinet_host(host)
        overview = glinet_client.get_overview(glinet_host, secret)
        parts = ["GL.iNet router"]
        if overview.lan_ip:
            parts.append(f"LAN {overview.lan_ip}")
        if overview.uptime:
            parts.append(f"up {overview.uptime}")
        return ", ".join(parts)

    def create_dashboard(self, host: InfrastructureHost, secret: str) -> QWidget:
        return GlinetDashboardWidget(to_glinet_host(host), secret)

    def fill_host(self, item: QTreeWidgetItem, host: InfrastructureHost) -> None:
        """A router is just its dashboard -- nothing to list under it."""
