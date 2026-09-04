from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QLineEdit, QMessageBox

from it_toolbox.modules.cloud_storage.models import ConfigStep, Provider, ProviderOption
from it_toolbox.modules.cloud_storage.ui.add_remote_dialog import AddRemoteDialog

LOCAL_PROVIDER = Provider(name="local", description="Local Disk", options=())
WEBDAV_PROVIDER = Provider(
    name="webdav",
    description="WebDAV",
    options=(
        ProviderOption(
            name="url", help="URL of WebDAV host.", type="string", default="",
            required=True, is_password=False, advanced=False, exclusive=False,
        ),
        ProviderOption(
            name="vendor", help="Name of the WebDAV site/service/software.", type="string",
            default="", required=False, is_password=False, advanced=False, exclusive=True,
            examples=(("nextcloud", "Nextcloud"), ("owncloud", "ownCloud")),
        ),
        ProviderOption(
            name="pass", help="Password.", type="string", default="",
            required=False, is_password=True, advanced=False, exclusive=False,
        ),
        ProviderOption(
            name="bearer_token_command", help="Command to run to get a bearer token.",
            type="string", default="", required=False, is_password=False,
            advanced=True, exclusive=False,
        ),
    ),
)


def _make_dialog(qtbot, monkeypatch, providers=(LOCAL_PROVIDER, WEBDAV_PROVIDER)):
    monkeypatch.setattr(
        "it_toolbox.modules.cloud_storage.ui.add_remote_dialog.rclone_client.list_providers",
        lambda: list(providers),
    )
    dialog = AddRemoteDialog()
    qtbot.addWidget(dialog)
    qtbot.waitUntil(lambda: dialog._provider_list.count() == len(providers), timeout=1000)
    return dialog


def test_providers_load_and_populate_the_list(qtbot, monkeypatch):
    dialog = _make_dialog(qtbot, monkeypatch)

    labels = [dialog._provider_list.item(i).text() for i in range(dialog._provider_list.count())]
    assert "local — Local Disk" in labels
    assert "webdav — WebDAV" in labels


def test_filter_hides_non_matching_providers(qtbot, monkeypatch):
    dialog = _make_dialog(qtbot, monkeypatch)

    dialog._filter_edit.setText("web")

    visible = [
        dialog._provider_list.item(i).text()
        for i in range(dialog._provider_list.count())
        if not dialog._provider_list.item(i).isHidden()
    ]
    assert visible == ["webdav — WebDAV"]


def test_next_button_disabled_until_name_and_provider_chosen(qtbot, monkeypatch):
    dialog = _make_dialog(qtbot, monkeypatch)

    assert dialog._next_button.isEnabled() is False

    dialog._name_edit.setText("myRemote")
    assert dialog._next_button.isEnabled() is False

    dialog._provider_list.item(0).setSelected(True)
    assert dialog._next_button.isEnabled() is True


def test_next_shows_config_form_with_non_advanced_fields(qtbot, monkeypatch):
    dialog = _make_dialog(qtbot, monkeypatch)
    dialog._name_edit.setText("myRemote")
    dialog._provider_list.item(1).setSelected(True)  # webdav

    dialog._on_next_clicked()

    assert set(dialog._field_widgets.keys()) == {"url", "vendor", "pass"}
    assert isinstance(dialog._field_widgets["vendor"], QComboBox)
    assert dialog._field_widgets["pass"].echoMode() == QLineEdit.EchoMode.Password


def test_show_advanced_options_reveals_advanced_fields(qtbot, monkeypatch):
    dialog = _make_dialog(qtbot, monkeypatch)
    dialog._name_edit.setText("myRemote")
    dialog._provider_list.item(1).setSelected(True)
    dialog._on_next_clicked()
    assert "bearer_token_command" not in dialog._field_widgets

    advanced_checkbox = next(
        w for w in dialog.findChildren(QCheckBox) if w.text() == "Show advanced options"
    )
    advanced_checkbox.setChecked(True)

    assert "bearer_token_command" in dialog._field_widgets


def test_create_with_zero_field_backend_finishes_and_accepts(qtbot, monkeypatch):
    captured = {}

    def fake_create(name, provider_type, fields):
        captured["args"] = (name, provider_type, fields)
        return ConfigStep(done=True)

    monkeypatch.setattr(
        "it_toolbox.modules.cloud_storage.ui.add_remote_dialog.rclone_client.start_create_remote",
        fake_create,
    )
    dialog = _make_dialog(qtbot, monkeypatch)
    dialog._name_edit.setText("myLocal")
    dialog._provider_list.item(0).setSelected(True)  # local
    dialog._on_next_clicked()

    create_button = next(
        b for b in dialog.findChildren(type(dialog._next_button)) if b.text() == "Create"
    )
    create_button.click()

    qtbot.waitUntil(lambda: dialog.result() == QDialog.DialogCode.Accepted, timeout=1000)
    assert captured["args"] == ("myLocal", "local", {})


def test_create_with_fields_passes_non_empty_values_only(qtbot, monkeypatch):
    captured = {}

    def fake_create(name, provider_type, fields):
        captured["fields"] = fields
        return ConfigStep(done=True)

    monkeypatch.setattr(
        "it_toolbox.modules.cloud_storage.ui.add_remote_dialog.rclone_client.start_create_remote",
        fake_create,
    )
    dialog = _make_dialog(qtbot, monkeypatch)
    dialog._name_edit.setText("myWebdav")
    dialog._provider_list.item(1).setSelected(True)  # webdav
    dialog._on_next_clicked()

    dialog._field_widgets["url"].setText("https://example.com/dav")
    # leave "vendor" and "pass" blank

    create_button = next(
        b for b in dialog.findChildren(type(dialog._next_button)) if b.text() == "Create"
    )
    create_button.click()

    qtbot.waitUntil(lambda: "fields" in captured, timeout=1000)
    assert captured["fields"] == {"url": "https://example.com/dav"}


def test_backend_needing_extra_step_shows_one_question_then_accepts(qtbot, monkeypatch):
    question = ConfigStep(
        done=False,
        state="client_id_warning",
        option=ProviderOption(
            name="config_shared_client_id",
            help="Continue using the shared client_id anyway?",
            type="bool",
            default="false",
            required=False,
            is_password=False,
            advanced=False,
            exclusive=True,
            examples=(("true", "Yes"), ("false", "No")),
        ),
    )
    monkeypatch.setattr(
        "it_toolbox.modules.cloud_storage.ui.add_remote_dialog.rclone_client.start_create_remote",
        lambda name, provider_type, fields: question,
    )
    continued = {}

    def fake_continue(name, state, result):
        continued["args"] = (name, state, result)
        return ConfigStep(done=True)

    monkeypatch.setattr(
        "it_toolbox.modules.cloud_storage.ui.add_remote_dialog.rclone_client.continue_config_step",
        fake_continue,
    )

    dialog = _make_dialog(qtbot, monkeypatch)
    dialog._name_edit.setText("testDrive")
    dialog._provider_list.item(0).setSelected(True)
    dialog._on_next_clicked()
    create_button = next(
        b for b in dialog.findChildren(type(dialog._next_button)) if b.text() == "Create"
    )
    create_button.click()

    qtbot.waitUntil(lambda: hasattr(dialog, "_question_widget"), timeout=1000)
    # Exclusive + Examples (as this real Drive question carries) renders as
    # a combo box, not a checkbox, even though the underlying Type is bool.
    assert isinstance(dialog._question_widget, QComboBox)

    submit_button = next(
        b for b in dialog.findChildren(type(dialog._next_button)) if b.text() == "Submit"
    )
    submit_button.click()

    qtbot.waitUntil(lambda: dialog.result() == QDialog.DialogCode.Accepted, timeout=1000)
    assert continued["args"] == ("testDrive", "client_id_warning", "false")


def test_create_error_shows_warning_and_stays_open(qtbot, monkeypatch):
    monkeypatch.setattr(
        "it_toolbox.modules.cloud_storage.ui.add_remote_dialog.rclone_client.start_create_remote",
        lambda name, provider_type, fields: (_ for _ in ()).throw(RuntimeError("name exists")),
    )
    warnings = []
    monkeypatch.setattr(
        "it_toolbox.modules.cloud_storage.ui.add_remote_dialog.QMessageBox.warning",
        lambda *a, **k: warnings.append(a),
    )
    dialog = _make_dialog(qtbot, monkeypatch)
    dialog._name_edit.setText("dup")
    dialog._provider_list.item(0).setSelected(True)
    dialog._on_next_clicked()
    create_button = next(
        b for b in dialog.findChildren(type(dialog._next_button)) if b.text() == "Create"
    )
    create_button.click()

    qtbot.waitUntil(lambda: len(warnings) == 1, timeout=1000)
    assert dialog.result() != QDialog.DialogCode.Accepted
