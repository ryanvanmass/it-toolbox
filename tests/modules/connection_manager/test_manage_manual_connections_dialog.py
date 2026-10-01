from it_toolbox.modules.connection_manager.models import SSH_PORT, ManualConnection
from it_toolbox.modules.connection_manager.ui.manage_manual_connections_dialog import (
    ManageManualConnectionsDialog,
    _ConnectionEditDialog,
)


def test_add_dialog_starts_with_gateway_disabled(qtbot):
    dialog = _ConnectionEditDialog()
    qtbot.addWidget(dialog)

    assert dialog._gateway_checkbox.isChecked() is False
    assert dialog._gateway_host_edit.isEnabled() is False

    connection = dialog.connection()
    assert connection.gateway_host is None
    assert connection.gateway_username is None
    assert connection.gateway_port == SSH_PORT


def test_edit_dialog_prefills_existing_gateway(qtbot):
    connection = ManualConnection(
        name="internal-rdp", host="10.0.0.5", port=3389, kind="rdp", username="alice",
        gateway_host="bastion.example.com", gateway_port=2222, gateway_username="bob",
    )
    dialog = _ConnectionEditDialog(connection)
    qtbot.addWidget(dialog)

    assert dialog._gateway_checkbox.isChecked() is True
    assert dialog._gateway_host_edit.isEnabled() is True
    assert dialog._gateway_host_edit.text() == "bastion.example.com"
    assert dialog._gateway_port_spin.value() == 2222
    assert dialog._gateway_username_edit.text() == "bob"

    assert dialog.connection() == connection


def test_gateway_fields_disabled_until_checkbox_checked(qtbot):
    dialog = _ConnectionEditDialog()
    qtbot.addWidget(dialog)

    dialog._gateway_checkbox.setChecked(True)

    assert dialog._gateway_host_edit.isEnabled() is True
    assert dialog._gateway_port_spin.isEnabled() is True
    assert dialog._gateway_username_edit.isEnabled() is True
    assert dialog._gateway_password_edit.isEnabled() is True


def test_edit_dialog_prefills_existing_gateway_password(qtbot):
    connection = ManualConnection(
        name="internal-rdp", host="10.0.0.5", port=3389, kind="rdp",
        gateway_host="pvsrv-zabbixproxy", gateway_username="planview-admin",
        gateway_password="hunter2",
    )
    dialog = _ConnectionEditDialog(connection)
    qtbot.addWidget(dialog)

    assert dialog._gateway_password_edit.text() == "hunter2"
    assert dialog.connection() == connection


def test_unchecking_gateway_clears_password_too(qtbot):
    connection = ManualConnection(
        name="internal-rdp", host="10.0.0.5", port=3389, kind="rdp",
        gateway_host="bastion.example.com", gateway_password="hunter2",
    )
    dialog = _ConnectionEditDialog(connection)
    qtbot.addWidget(dialog)

    dialog._gateway_checkbox.setChecked(False)

    assert dialog.connection().gateway_password is None


def test_edit_dialog_prefills_prompt_for_password_checkbox(qtbot):
    connection = ManualConnection(
        name="internal-rdp", host="10.0.0.5", port=3389, kind="rdp",
        gateway_host="pvsrv-zabbixproxy", gateway_prompt_for_password=True,
    )
    dialog = _ConnectionEditDialog(connection)
    qtbot.addWidget(dialog)

    assert dialog._gateway_prompt_password_checkbox.isChecked() is True
    assert dialog._gateway_password_edit.isEnabled() is False
    assert dialog.connection() == connection


def test_checking_prompt_for_password_disables_and_clears_the_stored_field(qtbot):
    connection = ManualConnection(
        name="internal-rdp", host="10.0.0.5", port=3389, kind="rdp",
        gateway_host="pvsrv-zabbixproxy", gateway_password="hunter2",
    )
    dialog = _ConnectionEditDialog(connection)
    qtbot.addWidget(dialog)

    dialog._gateway_prompt_password_checkbox.setChecked(True)

    assert dialog._gateway_password_edit.isEnabled() is False
    assert dialog._gateway_password_edit.text() == ""
    updated = dialog.connection()
    assert updated.gateway_password is None
    assert updated.gateway_prompt_for_password is True


def test_unchecking_gateway_clears_it_from_the_resulting_connection(qtbot):
    connection = ManualConnection(
        name="internal-rdp", host="10.0.0.5", port=3389, kind="rdp",
        gateway_host="bastion.example.com",
    )
    dialog = _ConnectionEditDialog(connection)
    qtbot.addWidget(dialog)

    dialog._gateway_checkbox.setChecked(False)

    updated = dialog.connection()
    assert updated.gateway_host is None
    assert updated.gateway_username is None


def test_manage_dialog_list_label_shows_gateway(qtbot):
    connection = ManualConnection(
        name="internal-rdp", host="10.0.0.5", port=3389, kind="rdp",
        gateway_host="bastion.example.com",
    )
    dialog = ManageManualConnectionsDialog([connection])
    qtbot.addWidget(dialog)

    assert dialog._list.item(0).text() == "internal-rdp — RDP 10.0.0.5:3389 (via bastion.example.com)"


def test_manage_dialog_list_label_omits_gateway_when_unset(qtbot):
    connection = ManualConnection(name="my-box", host="10.0.0.5", port=3389, kind="rdp")
    dialog = ManageManualConnectionsDialog([connection])
    qtbot.addWidget(dialog)

    assert dialog._list.item(0).text() == "my-box — RDP 10.0.0.5:3389"
