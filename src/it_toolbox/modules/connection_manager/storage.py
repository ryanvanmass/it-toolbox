import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from it_toolbox.core.settings import data_dir
from it_toolbox.modules.connection_manager.models import Connection

_SCHEMA = """
CREATE TABLE IF NOT EXISTS connections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    project_id TEXT NOT NULL,
    zone TEXT NOT NULL,
    instance_name TEXT NOT NULL,
    network_interface TEXT NOT NULL DEFAULT 'nic0',
    remote_port INTEGER NOT NULL,
    username TEXT,
    folder TEXT,
    last_used_at TEXT,
    created_at TEXT NOT NULL
)
"""


def default_db_path() -> Path:
    return data_dir() / "connections.db"


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(_SCHEMA)
    return conn


def _row_to_connection(row: sqlite3.Row) -> Connection:
    return Connection(
        id=row["id"],
        name=row["name"],
        type=row["type"],
        project_id=row["project_id"],
        zone=row["zone"],
        instance_name=row["instance_name"],
        network_interface=row["network_interface"],
        remote_port=row["remote_port"],
        username=row["username"],
        folder=row["folder"],
        last_used_at=row["last_used_at"],
        created_at=row["created_at"],
    )


def list_connections(db_path: Path | None = None) -> list[Connection]:
    conn = _connect(db_path or default_db_path())
    try:
        rows = conn.execute("SELECT * FROM connections ORDER BY name COLLATE NOCASE").fetchall()
        return [_row_to_connection(row) for row in rows]
    finally:
        conn.close()


def add_connection(connection: Connection, db_path: Path | None = None) -> int:
    now = datetime.now(UTC).isoformat()
    conn = _connect(db_path or default_db_path())
    try:
        cursor = conn.execute(
            """
            INSERT INTO connections
                (name, type, project_id, zone, instance_name, network_interface,
                 remote_port, username, folder, last_used_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                connection.name,
                connection.type,
                connection.project_id,
                connection.zone,
                connection.instance_name,
                connection.network_interface,
                connection.remote_port,
                connection.username,
                connection.folder,
                None,
                now,
            ),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def update_connection(connection: Connection, db_path: Path | None = None) -> None:
    conn = _connect(db_path or default_db_path())
    try:
        conn.execute(
            """
            UPDATE connections
            SET name=?, type=?, project_id=?, zone=?, instance_name=?,
                network_interface=?, remote_port=?, username=?, folder=?
            WHERE id=?
            """,
            (
                connection.name,
                connection.type,
                connection.project_id,
                connection.zone,
                connection.instance_name,
                connection.network_interface,
                connection.remote_port,
                connection.username,
                connection.folder,
                connection.id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def delete_connection(connection_id: int, db_path: Path | None = None) -> None:
    conn = _connect(db_path or default_db_path())
    try:
        conn.execute("DELETE FROM connections WHERE id=?", (connection_id,))
        conn.commit()
    finally:
        conn.close()


def touch_last_used(connection_id: int, db_path: Path | None = None) -> None:
    now = datetime.now(UTC).isoformat()
    conn = _connect(db_path or default_db_path())
    try:
        conn.execute("UPDATE connections SET last_used_at=? WHERE id=?", (now, connection_id))
        conn.commit()
    finally:
        conn.close()
