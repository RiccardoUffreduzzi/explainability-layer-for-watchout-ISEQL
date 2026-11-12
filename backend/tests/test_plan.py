"""Tests of the compiler's plan (``iseql.compiler.compile_event_plan``).

``data/compile_snapshot.json`` holds what ``compile_event`` returned for the 16
rules of ``data/analysis.seed.db`` before the plan existed, for three parameter
sets. The SQL must not change by a character, and the plan must describe the
same query: every operator and condition of the plan is in the SQL.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import iseql
from iseql.compiler import compile_event, compile_event_plan
from iseql.helpers import sql_threshold

SNAPSHOT = json.loads((Path(__file__).parent / "data" / "compile_snapshot.json").read_text(encoding="utf-8"))
AUDIO = set(SNAPSHOT["audio_predicates"])
VOCAB = SNAPSHOT["predicate_vocab"]
CASES = SNAPSHOT["cases"]
IDS = [c["id"] for c in CASES]


def _plan(case: dict, **kw):
    return compile_event_plan(case["model_json"], case["deltas"], case["analysis_id"], fps=case["fps"],
                              audio_predicates=AUDIO, predicate_vocab=VOCAB, condition=case["condition"], **kw)


def _case(case_id: str) -> dict:
    return next(c for c in CASES if c["id"] == case_id)


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_compile_event_sql_is_unchanged(case):
    text, sql = compile_event(case["model_json"], case["deltas"], case["analysis_id"], fps=case["fps"],
                              audio_predicates=AUDIO, predicate_vocab=VOCAB, condition=case["condition"])
    assert sql == case["sql"]
    assert text == case["iseql_text"]


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_plan_describes_the_sql(case):
    ev = _plan(case, lineage=True)
    assert ev.sql == case["sql"]
    assert ev.iseql_text == case["iseql_text"]
    assert ev.plan.branches
    for branch in ev.plan.branches:
        for op in branch.operators:
            assert op.sql in ev.sql
            assert [p.in_sql for p in op.params] == [sql_threshold(p.name, p.resolved) for p in op.params]
        for cond in branch.conditions:
            assert cond.sql in ev.sql
    json.dumps(ev.plan.to_json())
    if ev.plan.lineage:
        assert ev.lineage_sql.startswith("WITH r(")
        assert ev.sql in ev.lineage_sql
    else:
        assert ev.lineage_sql is None


@pytest.mark.parametrize("case", CASES[:16], ids=IDS[:16])
def test_no_lineage_sql_unless_asked(case):
    assert _plan(case).lineage_sql is None


def test_operator_records_choice_and_threshold_origin():
    ev = _plan(_case("C/vehicle_collision/defaults/seconds24"))
    assert ev.plan.form == "F2"
    assert ev.plan.set_tree.op == "∪" and ev.plan.set_tree.children == ("s1", "s2")
    op = ev.plan.branch("s1").operators[0]
    assert (op.operator, op.chosen_by, op.override_index, op.delta_map_key) == ("SP", "override", 0, "s1.0")
    params = {p.name: p for p in op.params}
    assert params["zeta"].origin == "named_key"
    assert params["zeta"].authored == "zeta_audio_vehicle_collision"
    assert params["zeta"].pointer == "/delta_map/s1.0/zeta"
    assert params["rho"].in_sql == 0
    assert op.sql == "((M1.st - 0) <= M2.st AND M2.st < (M1.et + 0))"


def test_columns_name_the_result_columns():
    ev = _plan(_case("C/vehicle_collision/defaults/seconds24"))
    cols = [(c.label, c.kind, c.fields, c.arg_class) for c in ev.plan.columns]
    assert cols == [
        ("M1_vehicle", "arg1", (("s2", "M1.arg1"),), "vehicle"),
        ("M1.st", "st", (("s1", "M1.st"), ("s2", "M1.st")), None),
        ("M2.et", "et", (("s1", "M2.et"), ("s2", "M1.et")), None),
    ]
    assert (ev.plan.extent.start, ev.plan.extent.end) == ("M1", "M2")


def test_text_values_change_only_the_plan_text():
    # detect() passes the values as written (2 s) while the SQL gets frames (48).
    case = _case("A/vehicle_escape/defaults/seconds24")
    plain = _plan(case)
    shown = _plan(case, text_values={"delta_visual_vehicle_escape": 2})
    assert shown.sql == plain.sql
    assert plain.plan.branches[0].operators[0].text == "Bef(δ:48; ζ:<=, ρ:0)"
    assert shown.plan.branches[0].operators[0].text == "Bef(δ:2; ζ:<=, ρ:0)"
    assert shown.plan.branches[0].operators[0].params == plain.plan.branches[0].operators[0].params


def test_facade_exposes_compile_event_plan():
    case = _case("A/fight/defaults/seconds24")
    ev = iseql.compile_event_plan(case["model_json"], case["deltas"], case["analysis_id"], fps=case["fps"],
                                  audio_predicates=AUDIO)
    assert ev.sql == case["sql"]
