"""The model of the explanation plan (``contract/plan.py``) and its JSON schema."""

import copy
import json
from collections.abc import Callable
from typing import Any

import jsonschema
import pytest
from pydantic import ValidationError

from xai.contract.canonical import canonical_json
from xai.contract.plan import (
    IN_REPORT2,
    PLAN_VERSION,
    ExplanationPlan,
    StepType,
    compute_plan_hash,
    dump_plan,
    load_plan,
    plan_to_data,
)
from xai.contract.plan_schema import SCHEMA_ID, SCHEMA_PATH, main, plan_schema, schema_text

Plan = dict[str, Any]


def _minimal_plan() -> Plan:
    """A plan of two steps (fight, s5): an observation and its conclusion."""
    data: Plan = {
        "plan_meta": {
            "plan_version": PLAN_VERSION,
            "contract_hash": "0" * 64,
            "source_of_truth_version": "0.2.0-k2",
            "contract_version": "0.2.0-k1",
            "event_id": "ev_d966ffea748d",
            "model_id": "fight",
            "label": "fight",
            "branches": ["s1"],
            "plan_hash": "0" * 64,
        },
        "steps": [
            {
                "step_id": "s_s1_sel1",
                "type": "observation",
                "construct": "c_s1_sel1",
                "refs": ["c_s1_sel1", "iv_v6", "ent_1", "ent_2", "g_predicate_physical_altercation"],
                "role": "because",
                "depends_on": [],
                "t_order": 0.0,
                "t_order_basis": "interval",
                "in_report2": True,
                "term": "g_predicate_physical_altercation",
                "slots": {"arg1": "ent_1", "arg2": "ent_2"},
            },
            {
                "step_id": "s_s1_proj",
                "type": "conclusion",
                "construct": "c_s1_proj",
                "refs": ["c_s1_proj", "ev_d966ffea748d", "ent_1", "ent_2", "g_event_model_fight"],
                "depends_on": ["s_s1_sel1"],
                "t_order": 0.0,
                "t_order_basis": "interval",
                "in_report2": True,
                "term": "g_event_model_fight",
            },
            {
                "step_id": "s_lim_temporal_resolution",
                "type": "limit",
                "refs": [],
                "role": "limit",
                "depends_on": ["s_s1_proj"],
                "t_order": None,
                "t_order_basis": "none",
                "in_report2": False,
                "limit_code": "temporal_resolution",
                "fixed_text": "A sentence of K2.",
            },
        ],
        "bindings": [
            {
                "branch": "s1",
                "variable": "M1",
                "status": "attributed",
                "interval_ids": ["iv_v6"],
                "basis": ["predicate", "arg_classes", "M1.arg1"],
            }
        ],
        "plan_report": {
            "excluded_constructs": [],
            "unbound_intervals": ["iv_v7"],
            "unmatched_readings": [],
            "notes": [{"code": "rho_not_zero", "detail": "c_s1_op1: ρ = 2"}],
        },
    }
    data["plan_meta"]["plan_hash"] = compute_plan_hash(data)
    return data


def _step(plan: Plan, index: int = 0) -> dict[str, Any]:
    step: dict[str, Any] = plan["steps"][index]
    return step


def test_a_plan_survives_a_round_trip() -> None:
    plan = load_plan(json.dumps(_minimal_plan()))

    assert load_plan(dump_plan(plan, indent=2)) == plan
    assert plan_to_data(plan) == _minimal_plan()


def test_the_same_plan_gives_the_same_text() -> None:
    assert dump_plan(load_plan(json.dumps(_minimal_plan()))) == canonical_json(_minimal_plan())


def test_the_hash_leaves_out_its_own_field() -> None:
    data = _minimal_plan()
    changed = copy.deepcopy(data)
    changed["plan_meta"]["plan_hash"] = "f" * 64

    assert compute_plan_hash(changed) == compute_plan_hash(data)
    changed["steps"][0]["t_order"] = 1.0
    assert compute_plan_hash(changed) != compute_plan_hash(data)


def test_construct_is_written_with_its_name() -> None:
    plan = load_plan(json.dumps(_minimal_plan()))

    assert plan.steps[0].construct_ == "c_s1_sel1"
    assert "construct" in plan_to_data(plan)["steps"][0]


def test_every_step_type_says_whether_it_is_in_report_2() -> None:
    assert set(IN_REPORT2) == set(StepType)
    assert {t.value for t, shown in IN_REPORT2.items() if shown} == {
        "observation",
        "context",
        "conclusion",
        "reinforcement",
    }


# --------------------------------------------------------------------------- schema and model agree

Mutation = Callable[[Plan], None]

CASES: dict[str, tuple[Mutation, bool]] = {
    "unchanged": (lambda p: None, True),
    "unknown key": (lambda p: _step(p).update(unknown=1), False),
    "optional field written as null": (lambda p: _step(p).update(term=None), False),
    "another plan version": (lambda p: p["plan_meta"].update(plan_version="0.2.0-k4"), False),
    "step ID without prefix": (lambda p: _step(p).update(step_id="sel1"), False),
    "reference to a pointer": (lambda p: _step(p)["refs"].append("#/rule/constraints/1/payload/value"), True),
    "reference to a key frame": (lambda p: _step(p)["refs"].append("kf_12"), True),
    "reference that is no ID": (lambda p: _step(p)["refs"].append("person"), False),
    "slot filled by a step": (lambda p: _step(p)["slots"].update(r="s_s1_sel1"), True),
    "slot left empty": (lambda p: _step(p)["slots"].update(arg2=None), True),
    "slot filled with text": (lambda p: _step(p)["slots"].update(arg1="a man"), False),
    "step type outside the catalogue": (lambda p: _step(p).update(type="action"), False),
    "limit code outside the catalogue": (lambda p: _step(p, 2).update(limit_code="mood"), False),
    "reading of ζ": (
        lambda p: _step(p).update(readings=[{"param": "ζ", "condition": "ζ = <=", "phrase": "x"}]),
        False,
    ),
    "t_order as text": (lambda p: _step(p).update(t_order="1.0"), False),
    "no branch explained": (lambda p: p["plan_meta"].update(branches=[]), False),
    "binding status outside the catalogue": (lambda p: p["bindings"][0].update(status="guessed"), False),
    "note outside the catalogue": (lambda p: p["plan_report"]["notes"][0].update(code="other"), False),
}


@pytest.fixture(scope="module")
def validator() -> jsonschema.Draft202012Validator:
    return jsonschema.Draft202012Validator(plan_schema())


@pytest.mark.parametrize("case", list(CASES))
def test_schema_and_model_agree(validator: jsonschema.Draft202012Validator, case: str) -> None:
    mutate, valid = CASES[case]
    plan = _minimal_plan()
    mutate(plan)
    try:
        load_plan(json.dumps(plan))
        model_ok = True
    except ValidationError:
        model_ok = False

    assert (validator.is_valid(plan), model_ok) == (valid, valid)


def test_the_schema_is_bound_to_the_version() -> None:
    assert plan_schema()["$id"] == SCHEMA_ID == f"urn:watchout-xai:explanation-plan:{PLAN_VERSION}"


def test_the_schema_file_is_up_to_date() -> None:
    assert SCHEMA_PATH.read_text(encoding="utf-8") == schema_text()
    assert main(["--check"]) == 0


def test_the_model_is_the_one_the_schema_describes() -> None:
    assert plan_schema()["title"] == ExplanationPlan.__name__
