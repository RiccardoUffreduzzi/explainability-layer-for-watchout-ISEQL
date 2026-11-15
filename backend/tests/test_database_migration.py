from __future__ import annotations

import sqlite3

from utils.database import setup_database


def test_legacy_sampling_columns_are_split_into_frame_and_sampling_rates(tmp_path) -> None:
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE Analyses (ID TEXT PRIMARY KEY, SamplingRate REAL, SamplingHz REAL)"
    )
    conn.execute(
        "INSERT INTO Analyses (ID, SamplingRate, SamplingHz) VALUES ('old', 29.97, 2.0)"
    )
    conn.commit()
    conn.close()

    conn, _ = setup_database(db_path)
    row = conn.execute(
        "SELECT FrameRate, SamplingRate FROM Analyses WHERE ID = 'old'"
    ).fetchone()
    columns = {r[1] for r in conn.execute("PRAGMA table_info(Analyses)")}

    assert tuple(row) == (29.97, 2.0)
    assert "SamplingHz" not in columns
    conn.close()
