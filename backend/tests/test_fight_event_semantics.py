from __future__ import annotations

import sqlite3

from iseql.compiler import compile_event


def test_fight_canonical_participant_order_returns_one_match() -> None:
    model = {
        "event_name": "fight",
        "intervals": [{
            "pred": {"name": "physical_altercation", "arguments": ["person", "person"]},
            "selection": {"preds": ["physical_altercation"], "args": {"1": ["person"], "2": ["person"]}},
            "ts": 0,
            "te": 100,
            "group": "s1",
        }],
        "cross_conditions": [{
            "left_alias": "M1", "left_attr": "arg1", "op": "<",
            "right_alias": "M1", "right_attr": "arg2",
        }],
        "set_expression": {"group": "s1", "projection": ["M1.arg1", "M1.arg2", "M1.st", "M1.et"]},
    }
    _, sql = compile_event(model, {}, "analysis-1", fps=24, audio_predicates=set())

    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE VisualPerInterval (
            RelationID INTEGER PRIMARY KEY,
            AnalysisID TEXT NOT NULL,
            StartFrame INTEGER NOT NULL,
            EndFrame INTEGER NOT NULL,
            RelationType TEXT NOT NULL
        );
        CREATE TABLE VisualParticipant (
            RelationID INTEGER NOT NULL,
            ClassID INTEGER NOT NULL,
            Class TEXT NOT NULL
        );
    """)
    conn.execute(
        "INSERT INTO VisualPerInterval VALUES (1, 'analysis-1', 48, 96, 'physical_altercation')"
    )
    conn.executemany(
        "INSERT INTO VisualParticipant VALUES (1, ?, 'person')",
        [(7,), (8,)],
    )

    assert conn.execute(sql).fetchall() == [(7, 8, 2.0, 4.0)]
