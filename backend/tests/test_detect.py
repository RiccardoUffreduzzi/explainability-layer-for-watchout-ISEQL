"""Tests of one detection (``EventsService.detect``) on a small database built here.

``detect`` is what the GUI runs (through ``detect_event``) and what the XAI
pipeline calls. With ``with_lineage`` it runs a single query that returns the
same rows, in the same order, each with the interval rows that produce it.
The rules are the 16 of ``data/compile_snapshot.json``.
"""
from __future__ import annotations

import inspect
import json
import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("pandas")

from iseql.compiler import compile_event_plan  # noqa: E402
from service.events_service import DetectionResult  # noqa: E402
from service.impl.events_service_impl import EventsServiceImpl, resolve_params  # noqa: E402
from utils.database import setup_database  # noqa: E402

SNAPSHOT = json.loads((Path(__file__).parent / "data" / "compile_snapshot.json").read_text(encoding="utf-8"))
RULES = {(c["condition"], c["event"]): c["model_json"] for c in SNAPSHOT["cases"]}
AID = "t1"
FPS = 24

# RelationID -> (relation, StartFrame, EndFrame, participants); frames at 24 fps
VISUAL = {
    1: ("running", 0, 48, [(1, "person")]),                                # 0-2 s
    2: ("running", 24, 120, [(2, "person")]),                              # 1-5 s
    3: ("enter_or_exit_vehicle", 144, 192, [(2, "person"), (7, "vehicle")]),  # 6-8 s
    4: ("vehicle_collision", 120, 168, [(7, "vehicle")]),                  # 5-7 s
}
AUDIO = {1: ("horn", 0, 60), 2: ("impact", 24, 72)}                        # 0-2.5 s, 1-3 s


@pytest.fixture
def db_path(tmp_path) -> Path:
    path = tmp_path / "analysis.db"
    conn, _ = setup_database(path)
    for key, value in SNAPSHOT["app_config"].items():
        conn.execute("INSERT INTO AppConfig (key, value_json) VALUES (?, ?)", (key, json.dumps(value)))
    for (condition, event), model_json in RULES.items():
        conn.execute("INSERT INTO EventSpec (id, condition, model_json) VALUES (?, ?, ?)",
                     (event, condition, model_json))
    conn.execute("INSERT INTO Analyses (ID, VideoPath, VideoFilename, Condition, SamplingRate, Stage, CreatedAt) "
                 "VALUES (?, 'v.mp4', 'v.mp4', 'C', ?, 'done', '2026-01-01T00:00:00')", (AID, FPS))
    for rid, (relation, sf, ef, participants) in VISUAL.items():
        conn.execute("INSERT INTO VisualPerInterval (RelationID, AnalysisID, StartFrame, EndFrame, RelationType) "
                     "VALUES (?, ?, ?, ?, ?)", (rid, AID, sf, ef, relation))
        for class_id, class_name in participants:
            conn.execute("INSERT INTO VisualParticipant (RelationID, ClassID, Class) VALUES (?, ?, ?)",
                         (rid, class_id, class_name))
    for iid, (audio_class, sf, ef) in AUDIO.items():
        conn.execute("INSERT INTO AudioPerInterval (AudioIntervalID, AnalysisID, StartFrame, EndFrame, AudioClass, "
                     "Confidence) VALUES (?, ?, ?, ?, ?, 1.0)", (iid, AID, sf, ef, audio_class))
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def conn(db_path):
    c = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    yield c
    c.close()


def _detect(conn, condition, event, **kw) -> DetectionResult:
    return EventsServiceImpl().detect(conn, analysis_id=AID, event_type=event, condition=condition, **kw)


def _witnesses(row):
    return [(w.branch, [(i.alias, i.table, i.id, [(a.position, a.class_id, a.class_name) for a in i.args])
                        for i in w.intervals]) for w in row.witnesses]


def test_vehicle_collision_c_rows_and_witnesses(conn):
    res = _detect(conn, "C", "vehicle_collision", with_lineage=True)
    assert [r.gui for r in res.rows] == [
        {"M1_vehicle": None, "M1.st": "00:00:00.000", "M2.et": "00:00:03.000", "M1.sf": 0, "M2.ef": 72},
        {"M1_vehicle": 7.0, "M1.st": "00:00:05.000", "M2.et": "00:00:07.000", "M1.sf": 120, "M2.ef": 168},
    ]
    assert [_witnesses(r) for r in res.rows] == [
        [("s1", [("M1", "AudioPerInterval", 1, []), ("M2", "AudioPerInterval", 2, [])])],
        [("s2", [("M1", "VisualPerInterval", 4, [(1, 7, "vehicle")])])],
    ]
    assert res.lineage and res.sampling_rate == FPS and res.plan.form == "F2"


def test_witness_args_follow_the_predicate_positions(conn):
    res = _detect(conn, "A", "vehicle_escape", with_lineage=True)
    assert [_witnesses(r) for r in res.rows] == [[("s1", [
        ("M1", "VisualPerInterval", 2, [(1, 2, "person")]),
        ("M2", "VisualPerInterval", 3, [(1, 2, "person"), (2, 7, "vehicle")]),
    ])]]


@pytest.mark.parametrize("condition,event", sorted(RULES))
def test_lineage_keeps_rows_and_order(conn, condition, event):
    plain = _detect(conn, condition, event)
    rich = _detect(conn, condition, event, with_lineage=True)
    assert [r.values for r in rich.rows] == [r.values for r in plain.rows]
    assert [r.gui for r in rich.rows] == [r.gui for r in plain.rows]
    assert all(r.witnesses is None for r in plain.rows)
    assert len(plain.rows) == len(conn.execute(plain.sql).fetchall())
    assert rich.sql == plain.sql
    for row in rich.rows:
        assert row.witnesses
        for w in row.witnesses:
            for i in w.intervals:
                if i.table == "AudioPerInterval":
                    assert i.id in AUDIO and not i.args
                else:
                    assert i.table == "VisualPerInterval"
                    relation, _sf, _ef, participants = VISUAL[i.id]
                    assert {(a.class_id, a.class_name) for a in i.args} <= set(participants)


def test_default_params_are_the_ones_the_gui_prefills(conn):
    res = _detect(conn, "A", "vehicle_escape")
    assert res.params.origin == "rule_defaults"
    # A, then B, then C: a later rule overwrites an earlier one, as in the frontend.
    assert res.params.provided_by["delta_visual_vehicle_escape"] == "vehicle_escape/C"
    assert "vehicle_escape/A" in res.params.rule_defaults
    assert res.params.written["delta_visual_vehicle_escape"] == 2
    assert res.params.engine["delta_visual_vehicle_escape"] == 2 * FPS


def test_seconds_are_converted_with_the_sampling_rate(conn):
    written = {"delta_visual_vehicle_escape": 2, "zeta_visual_vehicle_escape": "<=",
               "rho_visual_vehicle_escape": 0, "delta_visual_handoff": "inf",
               "zeta_visual_handoff": "<=", "rho_visual_handoff": 0}
    params = resolve_params(conn, "A", written, "seconds", FPS)
    assert params.origin == "request" and params.unit == "seconds"
    assert params.converted["delta_visual_vehicle_escape"] == 48
    assert params.engine["delta_visual_vehicle_escape"] == 48
    assert params.engine["delta_visual_handoff"] is None
    res = _detect(conn, "A", "vehicle_escape", params=written)
    assert res.plan.branches[0].operators[0].text == "Bef(δ:2; ζ:<=, ρ:0)"


def test_unknown_analysis_or_event_is_a_value_error(conn):
    with pytest.raises(ValueError, match="unknown analysis_id"):
        EventsServiceImpl().detect(conn, analysis_id="nope", event_type="fight", condition="A")
    with pytest.raises(ValueError, match="not available for condition A"):
        _detect(conn, "A", "nope")
    with pytest.raises(ValueError, match="unknown condition"):
        _detect(conn, "D", "fight")


def _running_set_rule(op: str) -> dict:
    """F3 rule: every running interval (left) op the running intervals longer than 3 s (right)."""
    running = json.loads(RULES[("A", "vehicle_escape")])["intervals"][0]
    running = {k: v for k, v in running.items() if k not in ("group", "group_id")}
    return {"intervals": [dict(running, set_side="left"), dict(running, set_side="right")],
            "delta_unit": "seconds", "set_operator": op, "delta_map": {},
            "cross_conditions": [{"type": "duration", "left_alias": "M2", "left_attr": "et",
                                  "right_alias": "M2", "right_attr": "st", "op": ">=", "value": 3}],
            "left_projection": ["M1.arg1", "M1.st", "M1.et"],
            "right_projection": ["M1.arg1", "M1.st", "M1.et"]}


@pytest.mark.parametrize("op,expected", [
    # left: running 1 (0-2 s) and running 2 (1-5 s); right: running 2 only (longer than 3 s)
    ("∪", {(1, 0.0, 2.0): [("left", 1)], (2, 1.0, 5.0): [("left", 2), ("right", 2)]}),
    ("\\", {(1, 0.0, 2.0): [("left", 1)]}),
    ("∩", {(2, 1.0, 5.0): [("left", 2), ("right", 2)]}),
])
def test_set_operation_witnesses(conn, op, expected):
    audio = set(SNAPSHOT["audio_predicates"])
    ev = compile_event_plan(_running_set_rule(op), {}, AID, fps=FPS, audio_predicates=audio, lineage=True)
    plain = [tuple(r) for r in conn.execute(ev.sql).fetchall()]
    rich = conn.execute(ev.lineage_sql).fetchall()
    assert [tuple(r)[:3] for r in rich] == plain
    got = {tuple(r)[:3]: sorted((w["branch"], w["intervals"][0]["id"]) for w in json.loads(r["lineage"]))
           for r in rich}
    assert got == expected


def test_detect_event_returns_the_detect_rows_and_writes_only_the_parameters(db_path, monkeypatch):
    pytest.importorskip("fastapi")
    from service.impl.analysis_service_impl import AnalysisServiceImpl
    from utils.config import Config

    monkeypatch.setattr(Config.get().data, "db_path", str(db_path))

    def content():
        c = sqlite3.connect(db_path)
        tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        out = {t: c.execute(f"SELECT * FROM {t} ORDER BY 1").fetchall() for t in tables if t != "Analyses"}
        out["Analyses"] = c.execute("SELECT * FROM Analyses").fetchall()
        cols = [d[1] for d in c.execute("PRAGMA table_info(Analyses)")]
        c.close()
        return out, cols

    before, cols = content()
    params = {"delta_visual_vehicle_escape": 2, "zeta_visual_vehicle_escape": "<=", "rho_visual_vehicle_escape": 0,
              "delta_visual_handoff": "inf", "zeta_visual_handoff": "<=", "rho_visual_handoff": 0}
    response = AnalysisServiceImpl().detect_event(analysis_id=AID, event_type="vehicle_escape", condition="A",
                                                  deltas=params, unit="seconds")
    after, _ = content()

    c = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    expected = [r.gui for r in _detect(c, "A", "vehicle_escape", params=params).rows]
    c.close()
    assert response == {"analysis_id": AID, "event_type": "vehicle_escape", "condition": "A", "rows": expected}
    assert len(expected) == 1
    # the only write: Analyses.DeltasJson and Analyses.DeltaUnit
    assert {t: v for t, v in after.items() if t != "Analyses"} == {t: v for t, v in before.items() if t != "Analyses"}
    changed = {cols[i] for i, (a, b) in enumerate(zip(before["Analyses"][0], after["Analyses"][0])) if a != b}
    assert changed == {"DeltasJson"}  # DeltaUnit was already 'seconds'
    assert json.loads(after["Analyses"][0][cols.index("DeltasJson")]) == {"deltas": params, "unit": "seconds"}


def test_reading_methods_return_the_values_the_code_uses():
    from service.impl.interval_service_impl import IntervalServiceImpl
    from utils.vlm_client import VLMClient

    assert VLMClient.generation_defaults() == {"temperature": 0.0, "seed": 42}
    init = inspect.signature(VLMClient.__init__).parameters
    assert (init["temperature"].default, init["seed"].default) == (0.0, 42)
    assert IntervalServiceImpl.merge_tolerance_samples() == 2


def test_audio_constant_confidence():
    pytest.importorskip("numpy")
    from service.impl.audio_service_impl import AudioServiceImpl

    assert AudioServiceImpl.constant_confidence("huggingface") == 1.0
    assert AudioServiceImpl.constant_confidence("panns") is None


def test_sqlite_has_the_json_functions_the_lineage_query_uses():
    c = sqlite3.connect(":memory:")
    assert c.execute("SELECT json_group_array(json(json_object('a', 1)))").fetchone()[0] == '[{"a":1}]'
