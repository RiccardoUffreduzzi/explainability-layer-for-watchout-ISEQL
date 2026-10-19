"""SQL queries on WatchOut's tables"""

import sqlite3
from collections.abc import Sequence
from typing import Any

ANALYSIS_COLUMNS = (
    "ID",
    "Condition",
    "Stage",
    "VLMProvider",
    "Model",
    "AudioProvider",
    "AudioModel",
    "AudioQuantization",
    "SamplingRate",
    "AudioWindow",
    "AudioHop",
)


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    """Columns of a table; empty when the table does not exist."""
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def analysis_row(conn: sqlite3.Connection, analysis_id: str) -> dict[str, Any] | None:
    """The ``Analyses`` row; columns an older database does not have are None."""
    present = table_columns(conn, "Analyses")
    if "ID" not in present:
        return None
    columns = [c for c in ANALYSIS_COLUMNS if c in present]
    row = conn.execute(f"SELECT {', '.join(columns)} FROM Analyses WHERE ID = ?", (analysis_id,)).fetchone()
    if row is None:
        return None
    return {c: (row[c] if c in present else None) for c in ANALYSIS_COLUMNS}


def saved_params_row(conn: sqlite3.Connection, analysis_id: str) -> tuple[str | None, str | None]:
    """reads DeltasJson, DeltaUnit of the analysis; None for a missing column."""
    present = table_columns(conn, "Analyses")
    columns = [c for c in ("DeltasJson", "DeltaUnit") if c in present]
    if not columns:
        return None, None
    row = conn.execute(f"SELECT {', '.join(columns)} FROM Analyses WHERE ID = ?", (analysis_id,)).fetchone()
    if row is None:
        return None, None
    values = {c: row[c] for c in columns}
    return values.get("DeltasJson"), values.get("DeltaUnit")


def appconfig_updated_at(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT updated_at FROM AppConfig WHERE key = ?", (key,)).fetchone()
    return None if row is None or row["updated_at"] is None else str(row["updated_at"])


def visual_intervals(
    conn: sqlite3.Connection, analysis_id: str, predicates: Sequence[str]
) -> list[sqlite3.Row]:
    if not predicates:
        return []
    marks = ", ".join("?" for _ in predicates)
    return conn.execute(
        "SELECT RelationID, StartFrame, EndFrame, RelationType FROM VisualPerInterval "
        f"WHERE AnalysisID = ? AND RelationType IN ({marks}) ORDER BY RelationID",
        (analysis_id, *predicates),
    ).fetchall()


def participants(conn: sqlite3.Connection, relation_ids: Sequence[int]) -> list[sqlite3.Row]:
    if not relation_ids:
        return []
    marks = ", ".join("?" for _ in relation_ids)
    return conn.execute(
        f"SELECT RelationID, ClassID, Class FROM VisualParticipant WHERE RelationID IN ({marks}) "
        "ORDER BY RelationID, ClassID",
        tuple(relation_ids),
    ).fetchall()


def audio_intervals(conn: sqlite3.Connection, analysis_id: str, classes: Sequence[str]) -> list[sqlite3.Row]:
    if not classes:
        return []
    marks = ", ".join("?" for _ in classes)
    return conn.execute(
        "SELECT AudioIntervalID, StartFrame, EndFrame, AudioClass, Confidence FROM AudioPerInterval "
        f"WHERE AnalysisID = ? AND AudioClass IN ({marks}) ORDER BY AudioIntervalID",
        (analysis_id, *classes),
    ).fetchall()
