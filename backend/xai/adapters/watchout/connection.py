"""The only place that opens WatchOut's database: read-only.

The file is opened in ``mode=ro`` and the connection is set to
``PRAGMA query_only``, so this part cannot write. With ``config_db``
(ablation databases without ``AppConfig``) the configuration is copied
from that database into a temporary
"""

import sqlite3
from pathlib import Path

_APPCONFIG_COLUMNS = "key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TEXT"


def default_db_path() -> Path:
    """The database WatchOut uses: ``Config.get().data.db_path``."""
    from utils.config import Config

    return Path(Config.get().data.db_path)


def open_read_only(db_path: Path | str, config_db_path: Path | str | None = None) -> sqlite3.Connection:
    path = _existing(db_path)
    conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        if config_db_path is not None:
            config_path = _existing(config_db_path)
            conn.execute("ATTACH DATABASE ? AS config", (f"{config_path.as_uri()}?mode=ro",))
            conn.execute(f"CREATE TEMP TABLE AppConfig ({_APPCONFIG_COLUMNS})")
            has_config = conn.execute(
                "SELECT 1 FROM config.sqlite_master WHERE type = 'table' AND name = 'AppConfig'"
            ).fetchone()
            if has_config:
                conn.execute(
                    "INSERT INTO temp.AppConfig (key, value_json, updated_at) "
                    "SELECT key, value_json, updated_at FROM config.AppConfig"
                )
        conn.execute("PRAGMA query_only = ON")
    except BaseException:
        conn.close()
        raise
    return conn


def _existing(path: Path | str) -> Path:
    resolved = Path(path).resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"database not found: {resolved}")
    return resolved
