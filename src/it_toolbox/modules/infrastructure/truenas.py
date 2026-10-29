"""TrueNAS in the Infrastructure module: one host per NAS, logged in with
a user-linked API key over the JSON-RPC websocket (core/truenas_client).

Under each host: one item per dashboard area (Overview, Storage, ...);
double-clicking one opens the host's dashboard on that area. Expanding a
host checks its alerts and pool health once and colours its dot.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QTreeWidgetItem, QWidget

from it_toolbox.core import async_utils, truenas_api, truenas_client
from it_toolbox.core.infrastructure_hosts import InfrastructureHost
from it_toolbox.modules.infrastructure.product import InfrastructureProduct
from it_toolbox.widgets.truenas_dashboard_widget import AREAS, TrueNasDashboardWidget

HEALTH_COLORS = {"green": "#2e9d4f", "amber": "#d99a00", "red": "#d03a2f", "unknown": "#8a8a8a"}
HEALTH_TEXT = {
    "green": "Healthy",
    "amber": "Warnings",
    "red": "Needs attention (pool unhealthy or critical alerts)",
}


def health_icon(health: str) -> QIcon:
    pixmap = QPixmap(12, 12)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(HEALTH_COLORS.get(health, HEALTH_COLORS["unknown"])))
    painter.drawEllipse(1, 1, 10, 10)
    painter.end()
    return QIcon(pixmap)


class TrueNasProduct(InfrastructureProduct):
    id = "truenas"
    display_name = "TrueNAS"
    default_port = 443
    token_id_label = None
    secret_label = "API key:"
    url_placeholder = "https://nas.lan"
    token_help = (
        "TrueNAS 25.04 or later. Create a key in the TrueNAS web UI from the user menu (top right) > "
        "API Keys, ideally for a dedicated user. A read-only admin can view everything; "
        "actions need a full admin (or sharing/storage admin for those areas)."
    )

    def _connect(self, host: InfrastructureHost, secret: str) -> truenas_client.TrueNasConnection:
        return truenas_client.open_connection(host.url, secret, host.verify_ssl, host.fingerprint)

    def test_connection(self, host: InfrastructureHost, secret: str) -> str:
        return truenas_client.test_connection(host.url, secret, host.verify_ssl, host.fingerprint)

    def create_dashboard(self, host: InfrastructureHost, secret: str) -> QWidget:
        return TrueNasDashboardWidget(host.name, lambda: self._connect(host, secret), web_url=host.url)

    def fill_host(self, item: QTreeWidgetItem, host: InfrastructureHost) -> None:
        item.setIcon(0, health_icon("unknown"))
        for area in AREAS:
            item.addChild(self.view.make_item(self, host, area, area))

    def on_host_expanded(self, item: QTreeWidgetItem, host: InfrastructureHost) -> None:
        secret = self.view.secret_for(self, host)
        if secret is None:
            return
        key = host.key

        def check() -> str:
            connection = self._connect(host, secret)
            try:
                return truenas_api.host_health(connection)
            finally:
                connection.close()

        def show(health: str) -> None:
            current = self.view.host_item(self, key)
            if current is not None:
                current.setIcon(0, health_icon(health))
                current.setToolTip(0, f"{host.url}\n{HEALTH_TEXT.get(health, '')}")

        def failed(error: Exception) -> None:
            current = self.view.host_item(self, key)
            if current is not None:
                current.setIcon(0, health_icon("unknown"))
                current.setToolTip(0, f"{host.url}\nCouldn't check: {error}")

        async_utils.run_in_background(check, on_result=show, on_error=failed)

    def on_item_double_clicked(self, item: QTreeWidgetItem, host: InfrastructureHost, node) -> None:
        dashboard = self.view.open_dashboard(self, host)
        if isinstance(dashboard, TrueNasDashboardWidget) and isinstance(node, str):
            dashboard.show_area(node)
