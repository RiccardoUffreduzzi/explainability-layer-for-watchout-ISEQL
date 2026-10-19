"""``default_params`` are the defaults the GUI pre-fills.

The GUI reads ``/schema`` (``api/schema_controller.py``, ``_event_specs``) for the
conditions A, B and C and merges each rule's ``default_deltas`` in that order, later
rules winning (``Object.assign``).
"""

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from xai.tests.harness import PinnedReader


def test_defaults_equal_the_gui_merge(
    reader: PinnedReader, watchout_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import api.schema_controller as schema

    def registry_conn() -> sqlite3.Connection:
        conn = sqlite3.connect(f"{watchout_db.as_uri()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(schema, "_registry_conn", registry_conn)
    merged: dict[str, Any] = {}
    per_rule: dict[str, dict[str, Any]] = {}
    for condition in ("A", "B", "C"):
        for spec in schema._event_specs(condition):
            per_rule[f"{spec['id']}/{condition}"] = spec["default_deltas"]
            merged.update(spec["default_deltas"])

    defaults = reader.default_params()

    assert defaults.origin == "rule_defaults"
    assert defaults.unit == "seconds"
    assert dict(defaults.values) == merged
    assert {ref: dict(values) for ref, values in defaults.rule_defaults.items()} == per_rule
    assert len(per_rule) == 16
