"""Paths and helpers shared by the tests."""

import json
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

XAI_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = XAI_DIR.parent
WATCHOUT_SRC_DIR = BACKEND_DIR / "src"
EXAMPLES_DIR = XAI_DIR / "tests" / "data"
EXAMPLE_PATHS = sorted(EXAMPLES_DIR.glob("*.bozza.json"))


def load_example(path: Path) -> dict[str, Any]:
    """An example draft from tests/data, without its ``$comment`` annotation."""
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    data.pop("$comment", None)
    return data


ModelT = TypeVar("ModelT", bound=BaseModel)


def from_json_data(model: type[ModelT], data: object) -> ModelT:
    """Validate ``data`` as the JSON text it stands for, the way drafts are read (``load_draft``).

    The models are strict: in Python an enum field wants the enum, in JSON its value.
    """
    return model.model_validate_json(json.dumps(data, ensure_ascii=False))


# --------------------------------------------------------------------------- WatchOut test database

REPO_DIR = BACKEND_DIR.parent
SEED_DB = REPO_DIR / "data" / "analysis.seed.db"
"""WatchOut's seed: the 16 rules and the configuration (``AppConfig``)."""
FIXTURE_PATH = EXAMPLES_DIR / "watchout_fixture.json"
"""Analyses and intervals of 30 real scenes (see its ``$comment``)."""

_ANALYSIS_COLUMNS = (
    "VLMProvider",
    "Model",
    "SamplingRate",
    "AudioProvider",
    "AudioModel",
    "AudioQuantization",
    "AudioWindow",
    "AudioHop",
    "Stage",
    "CreatedAt",
)


def scene(number: int) -> str:
    """Analysis id of a scene of the test database."""
    return f"gemini_3_6_flash_qwen2_audio_s{number}"


def consolidated_copy(source: Path, path: Path) -> Path:
    """A one-file copy of a repository database, its WAL included.

    The file is copied first, so the repository's file is never opened, not even
    read-only: SQLite would create its ``-shm`` next to it.
    """
    with tempfile.TemporaryDirectory() as folder:
        raw = Path(folder) / source.name
        shutil.copyfile(source, raw)
        wal = source.with_name(source.name + "-wal")
        if wal.is_file() and wal.stat().st_size:
            shutil.copyfile(wal, raw.with_name(raw.name + "-wal"))
        reader = sqlite3.connect(raw)
        target = sqlite3.connect(path)
        try:
            reader.backup(target)
            target.execute("PRAGMA journal_mode = DELETE")
        finally:
            reader.close()
            target.close()
    return path


def build_fixture_db(path: Path) -> Path:
    """A WatchOut database: the seed plus the analyses and intervals of ``watchout_fixture.json``.

    The seed is read through ``consolidated_copy``.
    """
    consolidated_copy(SEED_DB, path)
    target = sqlite3.connect(path)
    try:
        data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        for analysis_id, condition in data["conditions"].items():
            columns = ("ID", "VideoPath", "VideoFilename", "Condition", *_ANALYSIS_COLUMNS)
            values = (
                analysis_id,
                f"/videos/{analysis_id}.mp4",
                f"{analysis_id}.mp4",
                condition,
                *(data["analysis"][c] for c in _ANALYSIS_COLUMNS),
            )
            target.execute(
                f"INSERT INTO Analyses ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})",
                values,
            )
        _insert_intervals(target, data)
        target.commit()
    finally:
        target.close()
    return path


def _insert_intervals(conn: sqlite3.Connection, data: dict[str, Any]) -> None:
    conn.executemany(
        "INSERT INTO VisualPerInterval (RelationID, AnalysisID, StartFrame, EndFrame, RelationType) "
        "VALUES (?, ?, ?, ?, ?)",
        data["visual_intervals"],
    )
    conn.executemany(
        "INSERT INTO VisualParticipant (RelationID, ClassID, Class) VALUES (?, ?, ?)",
        data["participants"],
    )
    conn.executemany(
        "INSERT INTO AudioPerInterval "
        "(AudioIntervalID, AnalysisID, StartFrame, EndFrame, AudioClass, Confidence) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        data["audio_intervals"],
    )


# --------------------------------------------------------------------------- ablation databases

ABLATION_FIXTURE_PATH = EXAMPLES_DIR / "ablation_fixture.json"
"""Schema, rules and usable parameters of an ablation database (see its ``$comment``)."""
ABLATION_DB = (
    REPO_DIR
    / "data"
    / "ablation_gemini_3_6_flash_vlm_rag_reid_qwen2_audio"
    / "gemini_3_6_flash_vlm_rag_reid_qwen2_audio_w5_0s_h2_5s.db"
)
"""The ablation database the fixtures come from, for the test on a whole dataset."""


_INSERT_EVENT_SPEC = (
    "INSERT INTO EventSpec (id, condition, model_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?)"
)


def load_ablation_fixture() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(ABLATION_FIXTURE_PATH.read_text(encoding="utf-8"))
    return data


def build_ablation_db(path: Path) -> Path:
    """A database shaped like the ablation ones: their schema and rules, no Analyses or AppConfig rows.

    The intervals are those of ``watchout_fixture.json`` (the same scenes).
    """
    ablation = load_ablation_fixture()
    conn = sqlite3.connect(path)
    try:
        for statement in ablation["schema"]:
            conn.execute(statement)
        conn.executemany(_INSERT_EVENT_SPEC, ablation["event_specs"])
        _insert_intervals(conn, json.loads(FIXTURE_PATH.read_text(encoding="utf-8")))
        conn.commit()
    finally:
        conn.close()
    return path


def add_analyses(path: Path) -> list[str]:
    """``Analyses`` rows for the analyses that have intervals, in the columns the table has.

    The ablation databases have none: the values are those of ``watchout_fixture.json``,
    condition C for the scenes it does not list. Returns the analysis ids.
    """
    data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    conn = sqlite3.connect(path)
    try:
        present = {row[1] for row in conn.execute("PRAGMA table_info(Analyses)")}
        ids = sorted(
            row[0]
            for row in conn.execute(
                "SELECT AnalysisID FROM VisualPerInterval UNION SELECT AnalysisID FROM AudioPerInterval"
            )
        )
        own = [c for c in _ANALYSIS_COLUMNS if c in present]
        columns = ("ID", "VideoPath", "VideoFilename", "Condition", *own)
        conn.executemany(
            f"INSERT INTO Analyses ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})",
            [
                (
                    analysis_id,
                    f"/videos/{analysis_id}.mp4",
                    f"{analysis_id}.mp4",
                    data["conditions"].get(analysis_id, "C"),
                    *(data["analysis"][c] for c in own),
                )
                for analysis_id in ids
            ],
        )
        conn.commit()
    finally:
        conn.close()
    return ids


def use_ablation_rules(path: Path) -> Path:
    """The test database with the ablation rules and their usable parameters saved as the GUI saves them."""
    ablation = load_ablation_fixture()
    conn = sqlite3.connect(path)
    try:
        conn.execute("DELETE FROM EventSpec")
        conn.executemany(_INSERT_EVENT_SPEC, ablation["event_specs"])
        saved = ablation["saved_params"]
        conn.execute("UPDATE Analyses SET DeltasJson = ?, DeltaUnit = ?", (json.dumps(saved), saved["unit"]))
        conn.commit()
    finally:
        conn.close()
    return path


def copy_db(source: Path, folder: Path) -> Path:
    """A writable copy, for tests that change the database or run WatchOut's own functions on it."""
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / source.name
    shutil.copyfile(source, target)
    return target
