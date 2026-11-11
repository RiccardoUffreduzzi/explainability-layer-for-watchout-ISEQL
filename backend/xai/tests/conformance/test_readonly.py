"""The adapters' connection cannot write, with or without ``--config-db``."""

import sqlite3
from pathlib import Path

import pytest

from xai.adapters.watchout.connection import open_read_only
from xai.adapters.watchout.reader import SqliteWatchOutReader
from xai.tests.support import scene

WRITES = [
    "INSERT INTO Analyses (ID, VideoPath, VideoFilename, Condition, CreatedAt) "
    "VALUES ('x', 'v', 'v', 'A', 't')",
    "UPDATE Analyses SET DeltasJson = '{}'",
    "DELETE FROM EventSpec",
    "CREATE TABLE Extra (x INTEGER)",
    "INSERT INTO AppConfig (key, value_json) VALUES ('k', '{}')",
    "INSERT INTO VisualPerFrame (AnalysisID, Frame, ClassID, Class, Block, Description) "
    "VALUES ('x', 0, 1, 'person', 1, 'd')",
    "UPDATE VisualPerFrame SET Description = 'd'",
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


def test_reading_the_descriptions_leaves_the_file_unchanged(watchout_db: Path) -> None:
    before = watchout_db.read_bytes()
    conn = open_read_only(watchout_db)
    rows = SqliteWatchOutReader(conn).frame_descriptions(scene(21), [3, 4, 5])
    conn.close()

    assert rows
    assert watchout_db.read_bytes() == before
    sidecars = [watchout_db.with_name(watchout_db.name + suffix) for suffix in ("-wal", "-shm", "-journal")]
    assert not [p for p in sidecars if p.exists()]


def test_a_missing_database_is_not_created(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        open_read_only(tmp_path / "missing.db")
    assert list(tmp_path.iterdir()) == []
