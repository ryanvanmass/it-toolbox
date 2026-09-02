import pytest

from it_toolbox.modules.connection_manager import storage
from it_toolbox.modules.connection_manager.models import Connection


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "connections.db"


def _make_connection(**overrides) -> Connection:
    defaults = dict(
        id=None,
        name="My VM",
        type="ssh",
        project_id="proj-1",
        zone="us-central1-a",
        instance_name="vm-1",
        network_interface="nic0",
        remote_port=22,
        username="alice",
        folder=None,
        last_used_at=None,
        created_at=None,
    )
    defaults.update(overrides)
    return Connection(**defaults)


def test_list_connections_empty_on_fresh_db(db_path):
    assert storage.list_connections(db_path) == []


def test_add_and_list_connection(db_path):
    new_id = storage.add_connection(_make_connection(), db_path)

    connections = storage.list_connections(db_path)
    assert len(connections) == 1
    assert connections[0].id == new_id
    assert connections[0].name == "My VM"
    assert connections[0].created_at is not None


def test_update_connection(db_path):
    new_id = storage.add_connection(_make_connection(), db_path)

    updated = _make_connection(id=new_id, name="Renamed", username="bob")
    storage.update_connection(updated, db_path)

    [connection] = storage.list_connections(db_path)
    assert connection.name == "Renamed"
    assert connection.username == "bob"


def test_delete_connection(db_path):
    new_id = storage.add_connection(_make_connection(), db_path)
    storage.delete_connection(new_id, db_path)

    assert storage.list_connections(db_path) == []


def test_touch_last_used_sets_timestamp(db_path):
    new_id = storage.add_connection(_make_connection(), db_path)
    assert storage.list_connections(db_path)[0].last_used_at is None

    storage.touch_last_used(new_id, db_path)

    assert storage.list_connections(db_path)[0].last_used_at is not None


def test_list_connections_sorted_by_name_case_insensitive(db_path):
    storage.add_connection(_make_connection(name="zebra"), db_path)
    storage.add_connection(_make_connection(name="Apple"), db_path)
    storage.add_connection(_make_connection(name="banana"), db_path)

    names = [c.name for c in storage.list_connections(db_path)]
    assert names == ["Apple", "banana", "zebra"]
