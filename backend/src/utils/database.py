from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Tuple

from utils.api_logger import get_logger

log = get_logger(__name__)


def ensure_default_db() -> bool:
    """Copy the committed default seed DB into place on a fresh checkout.

    The runtime ``data/analysis.db`` is gitignored (it accumulates analysis
    history); the seed template ``data/analysis.seed.db`` holds the defined
    events + config with empty results. Returns True if a seed was applied.
    """
    from utils.config import Config

    cfg = Config.get()
    db_path = Path(cfg.data.db_path)
    seed_path = Path(cfg.data.dir) / "analysis.seed.db"
    if db_path.exists() or not seed_path.exists():
        return False
    import shutil

    shutil.copy(seed_path, db_path)
    log.info("Seeded default database from %s", seed_path)
    return True

SCHEMA_STATEMENTS: list[str] = [
    "PRAGMA journal_mode=WAL;",
    "PRAGMA busy_timeout=60000;",
    "PRAGMA foreign_keys = ON;",

    """CREATE TABLE IF NOT EXISTS Analyses (
        ID             TEXT PRIMARY KEY,
        VideoPath      TEXT    NOT NULL,
        VideoFilename  TEXT    NOT NULL,
        Condition      TEXT    NOT NULL,
        VLMProvider    TEXT,
        Model          TEXT,
        GridRows       INTEGER,
        GridCols       INTEGER,
        SamplingRate   REAL,
        SamplingHz     REAL    DEFAULT 1.0,
        VLMDelay       REAL    DEFAULT 0.0,
        MaxRetries     INTEGER DEFAULT 3,
        EmbedProvider  TEXT    DEFAULT 'huggingface',
        EmbedModel     TEXT    DEFAULT 'google/siglip-base-patch16-224',
        MemoryN        INTEGER DEFAULT 3,
        MemoryTopK     INTEGER DEFAULT 5,
        AudioProvider  TEXT    DEFAULT 'panns',
        AudioModel     TEXT,
        AudioQuantization TEXT DEFAULT 'none',
        Stage          TEXT    NOT NULL    DEFAULT 'queued',
        CreatedAt      TEXT    NOT NULL,
        CompletedAt    TEXT
    );""",

    """CREATE TABLE IF NOT EXISTS VisualPerFrame (
        AnalysisID  TEXT    NOT NULL,
        Frame       INTEGER NOT NULL,
        ClassID     INTEGER NOT NULL,
        Class       TEXT    NOT NULL,
        Block       INTEGER NOT NULL,
        Description TEXT    NOT NULL,
        PRIMARY KEY (AnalysisID, Frame, ClassID, Block)
    );""",
    "CREATE INDEX IF NOT EXISTS idx_VisualPerFrame_aid ON VisualPerFrame (AnalysisID);",
    "CREATE INDEX IF NOT EXISTS idx_VisualPerFrame_frame ON VisualPerFrame (Frame);",

    """CREATE TABLE IF NOT EXISTS VisualRelation (
        AnalysisID   TEXT    NOT NULL,
        Frame        INTEGER NOT NULL,
        RelationID   INTEGER NOT NULL,
        RelationType TEXT    NOT NULL,
        ClassID      INTEGER NOT NULL,
        PRIMARY KEY (AnalysisID, Frame, RelationID, ClassID)
    );""",
    "CREATE INDEX IF NOT EXISTS idx_VisualRelation_aid  ON VisualRelation (AnalysisID);",
    "CREATE INDEX IF NOT EXISTS idx_VisualRelation_frame ON VisualRelation (Frame);",

    """CREATE TABLE IF NOT EXISTS VisualPerInterval (
        RelationID   INTEGER PRIMARY KEY AUTOINCREMENT,
        AnalysisID   TEXT    NOT NULL,
        StartFrame   INTEGER NOT NULL,
        EndFrame     INTEGER NOT NULL,
        RelationType TEXT    NOT NULL
    );""",
    "CREATE INDEX IF NOT EXISTS idx_VisualPerInterval_aid   ON VisualPerInterval (AnalysisID);",
    "CREATE INDEX IF NOT EXISTS idx_VisualPerInterval_start ON VisualPerInterval (StartFrame);",
    "CREATE INDEX IF NOT EXISTS idx_VisualPerInterval_type  ON VisualPerInterval (RelationType);",

    """CREATE TABLE IF NOT EXISTS VisualParticipant (
        RelationID  INTEGER NOT NULL REFERENCES VisualPerInterval(RelationID),
        ClassID     INTEGER NOT NULL,
        Class       TEXT    NOT NULL,
        PRIMARY KEY (RelationID, ClassID)
    );""",

    """CREATE TABLE IF NOT EXISTS AudioPerInterval (
        AudioIntervalID INTEGER PRIMARY KEY AUTOINCREMENT,
        AnalysisID      TEXT    NOT NULL,
        StartFrame      INTEGER NOT NULL,
        EndFrame        INTEGER NOT NULL,
        AudioClass      TEXT    NOT NULL,
        Confidence      REAL    DEFAULT 1.0
    );""",
    "CREATE INDEX IF NOT EXISTS idx_AudioPerInterval_aid   ON AudioPerInterval (AnalysisID);",
    "CREATE INDEX IF NOT EXISTS idx_AudioPerInterval_start ON AudioPerInterval (StartFrame);",
    "CREATE INDEX IF NOT EXISTS idx_AudioPerInterval_end   ON AudioPerInterval (EndFrame);",
    "CREATE INDEX IF NOT EXISTS idx_AudioPerInterval_class ON AudioPerInterval (AudioClass);",

    """CREATE TABLE IF NOT EXISTS EventSpec (
        id           TEXT    NOT NULL,
        condition    TEXT    NOT NULL,
        model_json   TEXT,
        created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
        updated_at   TEXT    NOT NULL DEFAULT (datetime('now')),
        PRIMARY KEY (id, condition)
    );""",
    "CREATE INDEX IF NOT EXISTS idx_EventSpec_condition ON EventSpec (condition);",

    """CREATE TABLE IF NOT EXISTS AppConfig (
        key        TEXT PRIMARY KEY,
        value_json TEXT    NOT NULL,
        updated_at TEXT    NOT NULL DEFAULT (datetime('now'))
    );""",
]


VISUAL_SCRATCH_SCHEMA: list[str] = [
    """CREATE TABLE IF NOT EXISTS VisualPerFrame (
        AnalysisID  TEXT    NOT NULL,
        Frame       INTEGER NOT NULL,
        ClassID     INTEGER NOT NULL,
        Class       TEXT    NOT NULL,
        Block       INTEGER NOT NULL,
        Description TEXT    NOT NULL,
        PRIMARY KEY (AnalysisID, Frame, ClassID, Block)
    );""",
    "CREATE INDEX IF NOT EXISTS idx_VisualPerFrame_aid ON VisualPerFrame (AnalysisID);",
    "CREATE INDEX IF NOT EXISTS idx_VisualPerFrame_frame ON VisualPerFrame (Frame);",

    """CREATE TABLE IF NOT EXISTS VisualRelation (
        AnalysisID   TEXT    NOT NULL,
        Frame        INTEGER NOT NULL,
        RelationID   INTEGER NOT NULL,
        RelationType TEXT    NOT NULL,
        ClassID      INTEGER NOT NULL,
        PRIMARY KEY (AnalysisID, Frame, RelationID, ClassID)
    );""",
    "CREATE INDEX IF NOT EXISTS idx_VisualRelation_aid  ON VisualRelation (AnalysisID);",
    "CREATE INDEX IF NOT EXISTS idx_VisualRelation_frame ON VisualRelation (Frame);",

    """CREATE TABLE IF NOT EXISTS VisualPerInterval (
        RelationID   INTEGER PRIMARY KEY AUTOINCREMENT,
        AnalysisID   TEXT    NOT NULL,
        StartFrame   INTEGER NOT NULL,
        EndFrame     INTEGER NOT NULL,
        RelationType TEXT    NOT NULL
    );""",

    """CREATE TABLE IF NOT EXISTS VisualParticipant (
        RelationID  INTEGER NOT NULL,
        ClassID     INTEGER NOT NULL,
        Class       TEXT    NOT NULL,
        PRIMARY KEY (RelationID, ClassID)
    );""",
]


def setup_scratch_database() -> sqlite3.Connection:
    """Per-analysis in-memory SQLite that hosts the full visual pipeline.

    The visual pipeline (frame-level rows + interval construction) runs entirely
    against this connection, so the shared on-disk DB is never held under a long
    write lock. The caller then merges all four visual tables into the main DB
    in a single atomic transaction (see ``_merge_scratch_into_main``).
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    for stmt in VISUAL_SCRATCH_SCHEMA:
        conn.execute(stmt)
    return conn


def commit_with_retry(conn: sqlite3.Connection, retries: int = 10, sleep_s: float = 0.5) -> None:
    """Commit, retrying on a transient ``database is locked`` (busy writer).

    SQLite allows a single writer at a time; short-lived concurrent writers can
    still collide at commit. Retry briefly rather than failing the whole run.
    """
    for attempt in range(retries):
        try:
            conn.commit()
            return
        except sqlite3.OperationalError as e:
            if "locked" not in str(e).lower() or attempt == retries - 1:
                raise
            time.sleep(sleep_s)


def setup_database(db_path: Path) -> Tuple[sqlite3.Connection, sqlite3.Cursor]:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    log.info("Setting up database at %s", db_path)
    conn = sqlite3.connect(str(db_path), timeout=60.0)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    for stmt in SCHEMA_STATEMENTS:
        cursor.execute(stmt)
    _migrate_eventspec(conn)
    _migrate_drop_vlm_quantization(conn)
    _ensure_columns(conn, "Analyses", {
        "EmbedProvider": "TEXT DEFAULT 'huggingface'",
        "EmbedModel": "TEXT DEFAULT 'google/siglip-base-patch16-224'",
        "MemoryN": "INTEGER DEFAULT 3",
        "MemoryTopK": "INTEGER DEFAULT 5",
        "AudioWindow": "REAL DEFAULT 2.5",
        "AudioHop": "REAL DEFAULT 1.25",
        "DeltasJson": "TEXT",
        "DeltaUnit": "TEXT DEFAULT 'seconds'",
        "SamplingHz": "REAL DEFAULT 1.0",
    })
    conn.commit()
    return conn, cursor


_LEGACY_EVENTSPEC_COLUMNS = {
    "enabled", "delta_visual", "delta_audio", "epsilon_visual", "epsilon_audio",
    "eta_visual", "eta_audio", "zeta_visual", "zeta_audio", "rho_visual", "rho_audio",
    "iseql", "query_sql",
}


def _migrate_eventspec(conn: sqlite3.Connection) -> None:
    """Rebuild EventSpec without legacy columns and drop GeometryEventSpec.

    Older DBs carry a dead ``GeometryEventSpec`` table and a denormalised
    EventSpec (enabled / per-parameter delta columns / cached iseql + query_sql).
    ``model_json`` is the single source of truth, so those columns are dropped.
    """
    conn.execute("DROP TABLE IF EXISTS GeometryEventSpec")
    cols = {row[1] for row in conn.execute("PRAGMA table_info(EventSpec)").fetchall()}
    if not (cols & _LEGACY_EVENTSPEC_COLUMNS):
        return
    conn.execute(
        """CREATE TABLE EventSpec_migrated (
            id           TEXT    NOT NULL,
            condition    TEXT    NOT NULL,
            model_json   TEXT,
            created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
            updated_at   TEXT    NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (id, condition)
        )"""
    )
    conn.execute(
        "INSERT INTO EventSpec_migrated (id, condition, model_json, created_at, updated_at) "
        "SELECT id, condition, model_json, created_at, updated_at FROM EventSpec"
    )
    conn.execute("DROP TABLE EventSpec")
    conn.execute("ALTER TABLE EventSpec_migrated RENAME TO EventSpec")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_EventSpec_condition ON EventSpec (condition)")
    log.info("Migrated EventSpec: dropped legacy columns")


def _migrate_drop_vlm_quantization(conn: sqlite3.Connection) -> None:
    """Drop the legacy Analyses.VLMQuantization column.

    The Ollama VLM quantization picker was never wired to a real effect (Ollama
    quantization is a property of the pulled model tag, not a request knob), so
    the column is dead. SQLite supports DROP COLUMN since 3.35.0; guard on the
    column's presence so this is a no-op on fresh or already-migrated DBs.
    """
    cols = {row[1] for row in conn.execute("PRAGMA table_info(Analyses)").fetchall()}
    if "VLMQuantization" not in cols:
        return
    conn.execute("ALTER TABLE Analyses DROP COLUMN VLMQuantization")
    log.info("Migrated Analyses: dropped legacy VLMQuantization column")


def _ensure_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    """Additive migration: append any missing columns so existing DBs work."""
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    for name, ddl in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
