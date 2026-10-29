import pytest
from PySide6.QtWidgets import QDialog, QInputDialog, QMenu, QMessageBox, QWidget

from it_toolbox.core import async_utils, pinned_tls, settings
from it_toolbox.modules.infrastructure import products
from it_toolbox.core.infrastructure_hosts import InfrastructureHost, normalize_url
from it_toolbox.modules.infrastructure.product import InfrastructureProduct
from it_toolbox.modules.infrastructure.ui import host_dialog, main_view
from it_toolbox.modules.infrastructure.ui.host_dialog import HostDialog
from it_toolbox.modules.infrastructure.ui.main_view import (
    IS_ADD_ITEM_ROLE,
    NODE_ROLE,
    InfrastructureView,
)

PVE = InfrastructureHost(
    name="pve1",
    url="https://pve1.lan:8006",
    token_id="root@pam!toolbox",
    secret_encrypted=b"cipher",
    fingerprint="AA:BB",
)


class FakeDashboard(QWidget):
    def __init__(self, host, secret):
        super().__init__()
        self.host = host
        self.secret = secret
        self.closed = False

    def close_session(self):
        self.closed = True


class FakeProduct(InfrastructureProduct):
    id = "fake"
    display_name = "Fake"
    default_port = 8006

    def __init__(self, view):
        super().__init__(view)
        self.expanded = []
        self.double_clicked = []

    def test_connection(self, host, secret):
        return f"ok {host.name} {secret}"

    def create_dashboard(self, host, secret):
        return FakeDashboard(host, secret)

    def fill_host(self, item, host):
        item.addChild(self.view.make_item(self, host, "guest 100", node=("qemu", 100)))

    def on_host_expanded(self, item, host):
        self.expanded.append(host.name)

    def on_item_double_clicked(self, item, host, node):
        self.double_clicked.append(node)

    def add_item_actions(self, menu, item, host, node):
        if node is not None:
            menu.addAction("Guest action")


@pytest.fixture(autouse=True)
def data_dir(monkeypatch, tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    monkeypatch.setattr(settings, "data_dir", lambda: d)
    return d


@pytest.fixture(autouse=True)
def fake_products(monkeypatch):
    monkeypatch.setattr(main_view, "PRODUCT_CLASSES", [FakeProduct])


@pytest.fixture(autouse=True)
def fake_crypto(monkeypatch):
    monkeypatch.setattr(settings, "encrypt_infrastructure_secret", lambda s: f"enc:{s}".encode())
    monkeypatch.setattr(
        settings, "decrypt_infrastructure_secret", lambda b, passphrase=None: b.decode().removeprefix("enc:")
    )


@pytest.fixture(autouse=True)
def synchronous(monkeypatch):
    def run(fn, on_result=None, on_error=None):
        try:
            result = fn()
        except Exception as error:  # noqa: BLE001 -- mirrors run_in_background
            if on_error is not None:
                on_error(error)
            return
        if on_result is not None:
            on_result(result)

    monkeypatch.setattr(async_utils, "run_in_background", run)


def _view(qtbot):
    view = InfrastructureView()
    qtbot.addWidget(view)
    return view


def _children(item):
    return [item.child(i).text(0) for i in range(item.childCount())]


def test_shipped_product_list_is_importable():
    assert isinstance(products.PRODUCT_CLASSES, list)


def test_each_product_gets_a_root_with_add_host_and_its_hosts(qtbot):
    settings.save_infrastructure_hosts("fake", [PVE.to_dict()])
    view = _view(qtbot)

    root = view._tree.topLevelItem(0)
    assert root.text(0) == "Fake"
    assert _children(root) == ["Add host…", "pve1"]
    assert root.child(0).data(0, IS_ADD_ITEM_ROLE) is True
    host_item = root.child(1)
    assert host_item.toolTip(0) == "https://pve1.lan:8006"
    assert _children(host_item) == ["guest 100"]
    assert host_item.child(0).data(0, NODE_ROLE) == ("qemu", 100)


def test_no_products_shows_a_placeholder(qtbot, monkeypatch):
    monkeypatch.setattr(main_view, "PRODUCT_CLASSES", [])
    view = _view(qtbot)
    assert view._tree.topLevelItem(0).text(0) == "(no products available yet)"


def test_host_round_trips_through_its_dict():
    assert InfrastructureHost.from_dict(PVE.to_dict()) == PVE
    assert InfrastructureHost.from_dict({"url": "x"}) is None


@pytest.mark.parametrize(
    "typed, expected",
    [
        ("pve1.lan", "https://pve1.lan:8006"),
        ("https://pve1.lan/", "https://pve1.lan:8006"),
        ("https://pve1.lan:443", "https://pve1.lan:443"),
        ("  ", ""),
    ],
)
def test_normalize_url_adds_scheme_and_default_port(typed, expected):
    assert normalize_url(typed, 8006) == expected


def test_expanding_a_host_and_double_clicking_a_child_reach_the_product(qtbot):
    settings.save_infrastructure_hosts("fake", [PVE.to_dict()])
    view = _view(qtbot)
    product = view.products[0]
    host_item = view._tree.topLevelItem(0).child(1)

    host_item.setExpanded(True)
    view._on_item_double_clicked(host_item.child(0), 0)

    assert product.expanded == ["pve1"]
    assert product.double_clicked == [("qemu", 100)]


def test_double_clicking_a_host_opens_its_dashboard_once(qtbot):
    settings.save_infrastructure_hosts("fake", [PVE.with_changes(secret_encrypted=b"enc:s3cret").to_dict()])
    view = _view(qtbot)
    host_item = view._tree.topLevelItem(0).child(1)

    view._on_item_double_clicked(host_item, 0)
    view._on_item_double_clicked(host_item, 0)

    assert view.tabs.count() == 1
    assert view.tabs.tabText(0) == "Fake: pve1"
    dashboard = view.tabs.widget(0)
    assert dashboard.secret == "s3cret"

    assert view.try_close_tab(dashboard)
    assert dashboard.closed and view.tabs.count() == 0


def test_a_host_without_a_stored_secret_is_asked_once_per_session(qtbot, monkeypatch):
    settings.save_infrastructure_hosts("fake", [PVE.with_changes(secret_encrypted=None).to_dict()])
    asked = []

    def ask(*args, **kwargs):
        asked.append(args[1])
        return "typed", True

    monkeypatch.setattr(QInputDialog, "getText", ask)
    view = _view(qtbot)
    product = view.products[0]
    host = view.hosts(product)[0]

    assert view.secret_for(product, host) == "typed"
    assert view.secret_for(product, host) == "typed"
    assert asked == ["Fake Token"]


def test_add_host_saves_the_encrypted_secret(qtbot, monkeypatch):
    class Dialog:
        def __init__(self, product, parent=None):
            pass

        def exec(self):
            return QDialog.DialogCode.Accepted

        def host(self):
            return PVE.with_changes(secret_encrypted=None)

        def secret(self):
            return "s3cret"

    monkeypatch.setattr(main_view, "HostDialog", Dialog)
    view = _view(qtbot)
    view.add_host(view.products[0])

    saved = settings.load_infrastructure_hosts("fake")
    assert len(saved) == 1
    assert InfrastructureHost.from_dict(saved[0]).secret_encrypted == b"enc:s3cret"
    assert _children(view._tree.topLevelItem(0)) == ["Add host…", "pve1"]


def test_remove_host_asks_first(qtbot, monkeypatch):
    settings.save_infrastructure_hosts("fake", [PVE.to_dict()])
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    view = _view(qtbot)
    view.remove_host(view.products[0], PVE.key)
    assert settings.load_infrastructure_hosts("fake") == []


def test_host_menu_has_the_shared_actions_after_the_products(qtbot):
    settings.save_infrastructure_hosts("fake", [PVE.to_dict()])
    view = _view(qtbot)
    product = view.products[0]
    menu = QMenu()
    product.add_item_actions(menu, None, PVE, ("qemu", 100))
    view.add_host_actions(menu, product, PVE)
    labels = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert labels == [
        "Guest action",
        "Open Dashboard",
        "Refresh",
        "Open Web UI",
        "Open SSH Shell",
        "Edit…",
        "Remove",
    ]


def test_open_ssh_shell_uses_the_host_and_ssh_user(qtbot, monkeypatch):
    launched = []
    monkeypatch.setattr(main_view.session_launcher, "launch_ssh", lambda *a: launched.append(a))
    view = _view(qtbot)
    view.open_ssh_shell(PVE)
    assert launched == [("pve1.lan", 22, "root")]


# -- HostDialog --------------------------------------------------------------


def _dialog(qtbot, host=None):
    view = _view(qtbot)
    dialog = HostDialog(view.products[0], host)
    qtbot.addWidget(dialog)
    return dialog


def test_dialog_pins_the_certificate_the_user_trusts(qtbot, monkeypatch):
    monkeypatch.setattr(host_dialog.pinned_tls, "fetch_fingerprint", lambda url, timeout=10: "CC:DD")
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    dialog = _dialog(qtbot)
    dialog._url.setText("pve1.lan")
    dialog._token_id.setText("root@pam!toolbox")
    dialog._secret.setText("s3cret")

    dialog._on_save()

    assert dialog.result() == QDialog.DialogCode.Accepted
    host = dialog.host()
    assert host.url == "https://pve1.lan:8006" and host.name == "pve1.lan"
    assert host.fingerprint == "CC:DD"
    assert dialog.secret() == "s3cret"


def test_dialog_does_not_save_when_the_certificate_is_declined(qtbot, monkeypatch):
    monkeypatch.setattr(host_dialog.pinned_tls, "fetch_fingerprint", lambda url, timeout=10: "CC:DD")
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    dialog = _dialog(qtbot)
    dialog._url.setText("pve1.lan")
    dialog._token_id.setText("root@pam!toolbox")
    dialog._secret.setText("s3cret")

    dialog._on_save()

    assert dialog.result() != QDialog.DialogCode.Accepted


def test_dialog_skips_the_prompt_for_an_unchanged_certificate(qtbot, monkeypatch):
    monkeypatch.setattr(host_dialog.pinned_tls, "fetch_fingerprint", lambda url, timeout=10: "aa:bb")
    dialog = _dialog(qtbot, PVE)  # pinned AA:BB; the forbidden-dialog fixture fails any prompt

    dialog._on_save()

    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.secret() is None  # blank = keep the stored one
    assert dialog.host().secret_encrypted == b"cipher"


def test_dialog_test_connection_shows_the_products_summary(qtbot, monkeypatch):
    monkeypatch.setattr(host_dialog.pinned_tls, "fetch_fingerprint", lambda url, timeout=10: "AA:BB")
    dialog = _dialog(qtbot, PVE)
    dialog._secret.setText("typed")

    dialog._on_test_clicked()

    assert dialog._result.text() == "Connected: ok pve1 typed"


def test_dialog_with_verification_on_never_fetches_the_certificate(qtbot, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("fetched")

    monkeypatch.setattr(host_dialog.pinned_tls, "fetch_fingerprint", boom)
    dialog = _dialog(qtbot)
    dialog._url.setText("pve1.lan")
    dialog._token_id.setText("root@pam!toolbox")
    dialog._secret.setText("s3cret")
    dialog._verify.setChecked(True)

    dialog._on_save()

    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.host().verify_ssl and dialog.host().fingerprint is None


def test_pinned_tls_is_what_the_dialog_uses():
    assert host_dialog.pinned_tls is pinned_tls
