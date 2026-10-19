"""The adapters' connection cannot write, with or without ``--config-db``."""

import sqlite3
from pathlib import Path

import pytest

from xai.adapters.watchout.connection import open_read_only

WRITES = [
    "INSERT INTO Analyses (ID, VideoPath, VideoFilename, Condition, CreatedAt) "
    "VALUES ('x', 'v', 'v', 'A', 't')",
    "UPDATE Analyses SET DeltasJson = '{}'",
    "DELETE FROM EventSpec",
    "CREATE TABLE Extra (x INTEGER)",
    "INSERT INTO AppConfig (key, value_json) VALUES ('k', '{}')",
]


@pytest.mark.parametrize("statement", WRITES)
def test_the_connection_refuses_writes(watchout_db: Path, statement: str) -> None:
    conn = open_read_only(watchout_db)
    try:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute(statement)
    finally:
        conn.close()


@pytest.mark.parametrize("statement", WRITES)
def test_the_connection_with_a_config_db_refuses_writes(watchout_db: Path, statement: str) -> None:
    conn = open_read_only(watchout_db, config_db_path=watchout_db)
    try:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute(statement)
    finally:
        conn.close()


def test_the_database_file_is_unchanged(watchout_db: Path) -> None:
    before = watchout_db.read_bytes()
    conn = open_read_only(watchout_db)
    conn.execute("SELECT COUNT(*) FROM Analyses").fetchone()
    conn.close()

    assert watchout_db.read_bytes() == before


def test_a_missing_database_is_not_created(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        open_read_only(tmp_path / "missing.db")
    assert list(tmp_path.iterdir()) == []
