from PySide6.QtWidgets import QMessageBox

from it_toolbox.modules.connection_manager import storage
from it_toolbox.modules.connection_manager.models import Connection
from it_toolbox.modules.connection_manager.ui.main_view import ConnectionManagerView


def _make_view(qtbot, monkeypatch, tmp_path):
    # Hermetic: don't touch the real user's gcloud state, and use a
    # throwaway DB rather than the real one on this machine.
    monkeypatch.setattr(
        "it_toolbox.modules.connection_manager.ui.main_view.gcp_auth.is_available",
        lambda: False,
    )
    monkeypatch.setattr(storage, "default_db_path", lambda: tmp_path / "connections.db")

    view = ConnectionManagerView()
    qtbot.addWidget(view)
    return view


def test_saved_connections_start_empty(qtbot, monkeypatch, tmp_path):
    view = _make_view(qtbot, monkeypatch, tmp_path)
    assert view._connections_list.count() == 0


def test_reload_shows_persisted_connections(qtbot, monkeypatch, tmp_path):
    view = _make_view(qtbot, monkeypatch, tmp_path)

    storage.add_connection(
        Connection(
            id=None,
            name="Prod Bastion",
            type="ssh",
            project_id="proj-1",
            zone="us-central1-a",
            instance_name="bastion-1",
            network_interface="nic0",
            remote_port=22,
            username="alice",
            folder=None,
            last_used_at=None,
            created_at=None,
        )
    )
    view._reload_saved_connections()

    assert view._connections_list.count() == 1
    assert "Prod Bastion" in view._connections_list.item(0).text()


def test_selecting_a_connection_enables_action_buttons(qtbot, monkeypatch, tmp_path):
    view = _make_view(qtbot, monkeypatch, tmp_path)
    storage.add_connection(
        Connection(
            id=None,
            name="VM",
            type="rdp",
            project_id="p",
            zone="z",
            instance_name="vm",
            network_interface="nic0",
            remote_port=3389,
            username=None,
            folder=None,
            last_used_at=None,
            created_at=None,
        )
    )
    view._reload_saved_connections()

    assert not view._connect_saved_button.isEnabled()
    view._connections_list.setCurrentRow(0)
    assert view._connect_saved_button.isEnabled()
    assert view._edit_connection_button.isEnabled()
    assert view._delete_connection_button.isEnabled()


def test_delete_connection_removes_it_from_list_and_storage(qtbot, monkeypatch, tmp_path):
    view = _make_view(qtbot, monkeypatch, tmp_path)
    storage.add_connection(
        Connection(
            id=None,
            name="Doomed",
            type="ssh",
            project_id="p",
            zone="z",
            instance_name="vm",
            network_interface="nic0",
            remote_port=22,
            username=None,
            folder=None,
            last_used_at=None,
            created_at=None,
        )
    )
    view._reload_saved_connections()
    view._connections_list.setCurrentRow(0)

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    view._on_delete_connection_clicked()

    assert view._connections_list.count() == 0
    assert storage.list_connections() == []
