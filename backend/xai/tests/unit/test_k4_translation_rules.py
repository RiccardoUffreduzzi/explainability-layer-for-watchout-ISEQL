"""One rule at a time: the steps of 02 §8, with a context built by the test."""

from collections.abc import Mapping
from typing import Any

import pytest

from xai.contract.plan import PlanStep
from xai.k4_planner.bindings import resolve_bindings
from xai.k4_planner.rules import RULES, RuleContext, RuleResult
from xai.k4_planner.view import SourceOfTruthView
from xai.tests.k4_support import node_data, view_of


def _context(
    view: SourceOfTruthView,
    branch: str = "s1",
    t_orders: Mapping[str, float | None] | None = None,
    leaves: tuple[str, ...] = (),
) -> RuleContext:
    """The context of a branch as ``translate`` builds it: observations made by selection order."""
    bindings = {b.variable: b for b in resolve_bindings(view, branch)}
    observation_of = {b.variable: "s_" + b.selection.removeprefix("c_") for b in bindings.values()}
    return RuleContext(
        view=view,
        branch=branch,
        bindings=bindings,
        observation_of=observation_of,
        t_orders=t_orders or {},
        leaves=leaves,
    )


def _interval(data: dict[str, Any], interval_id: str) -> dict[str, Any]:
    """An interval of draft data, to change it."""
    interval: dict[str, Any] = next(i for i in data["intervals"] if i["interval_id"] == interval_id)
    return interval


def _result(view: SourceOfTruthView, constraint_id: str, ctx: RuleContext) -> RuleResult:
    node = view.node(constraint_id)
    return RULES[node.kind].translate(node, ctx)


def _step(view: SourceOfTruthView, constraint_id: str, ctx: RuleContext) -> dict[str, Any]:
    step: PlanStep = _result(view, constraint_id, ctx).step
    data: dict[str, Any] = step.model_dump(mode="json")
    return data


# --------------------------------------------------------------------------- handoff, s21, A


@pytest.fixture(scope="module")
def handoff() -> SourceOfTruthView:
    return view_of("handoff_s21_A")


def test_handoff_first_observation(handoff: SourceOfTruthView) -> None:
    assert _step(handoff, "c_s1_sel1", _context(handoff)) == {
        "step_id": "s_s1_sel1",
        "type": "observation",
        "construct": "c_s1_sel1",
        "refs": ["c_s1_sel1", "iv_v59", "ent_3", "ent_4", "g_predicate_carrying"],
        "role": "because",
        "depends_on": [],
        "t_order": 1.0,
        "t_order_basis": "interval",
        "in_report2": True,
        "term": "g_predicate_carrying",
        "slots": {"arg1": "ent_3", "arg2": "ent_4"},
    }


def test_handoff_second_observation(handoff: SourceOfTruthView) -> None:
    step = _step(handoff, "c_s1_sel2", _context(handoff))

    assert step["refs"] == ["c_s1_sel2", "iv_v60", "ent_5", "ent_4", "g_predicate_carrying"]
    assert step["slots"] == {"arg1": "ent_5", "arg2": "ent_4"}  # arg2: argument 2 of iv_v60
    assert step["t_order"] == 5.0


def test_handoff_operator(handoff: SourceOfTruthView) -> None:
    ctx = _context(handoff, t_orders={"s_s1_sel1": 1.0, "s_s1_sel2": 5.0})

    assert _step(handoff, "c_s1_op1", ctx) == {
        "step_id": "s_s1_op1",
        "type": "temporal",
        "construct": "c_s1_op1",
        "refs": ["c_s1_op1", "g_operator_Bef"],
        "role": "because",
        "depends_on": ["s_s1_sel1", "s_s1_sel2"],
        "t_order": 5.0,
        "t_order_basis": "interval",
        "in_report2": False,
        "term": "g_operator_Bef",
        "slots": {"r": "s_s1_sel1", "s": "s_s1_sel2"},
        "readings": [{"param": "δ", "condition": "δ = ∞", "phrase": "at any time after"}],
    }


def test_handoff_identities(handoff: SourceOfTruthView) -> None:
    ctx = _context(handoff, t_orders={"s_s1_sel1": 1.0, "s_s1_sel2": 5.0})
    different = _step(handoff, "c_s1_cc1", ctx)
    same = _step(handoff, "c_s1_cc2", ctx)

    assert (different["type"], different["term"], different["slots"]) == (
        "identity",
        "g_comparison_identity_ne",
        {"left": "ent_3", "right": "ent_5"},
    )
    assert different["refs"] == ["c_s1_cc1", "ent_3", "ent_5", "g_comparison_identity_ne"]
    assert (same["type"], same["term"], same["slots"]) == (
        "identity",
        "g_comparison_identity_eq",
        {"left": "ent_4", "right": "ent_4"},  # right: argument 2 of iv_v60, not projected
    )
    assert same["depends_on"] == ["s_s1_sel1", "s_s1_sel2"]


def test_handoff_conclusion(handoff: SourceOfTruthView) -> None:
    leaves = ("s_s1_cc1", "s_s1_cc2", "s_s1_op1")
    ctx = _context(handoff, t_orders=dict.fromkeys(leaves, 5.0), leaves=leaves)

    assert _step(handoff, "c_s1_proj", ctx) == {
        "step_id": "s_s1_proj",
        "type": "conclusion",
        "construct": "c_s1_proj",
        "refs": ["c_s1_proj", "ev_beffcb6f2a6e", "ent_3", "ent_5", "ent_4", "g_event_model_handoff"],
        "depends_on": ["s_s1_cc1", "s_s1_cc2", "s_s1_op1"],
        "t_order": 5.0,
        "t_order_basis": "interval",
        "in_report2": True,
        "term": "g_event_model_handoff",
    }


# --------------------------------------------------------------------------- the other drafts


def test_fight_identity_on_one_variable_is_a_condition() -> None:
    view = view_of("fight_s5_A")
    ctx = _context(view, t_orders={"s_s1_sel1": 0.0})

    observation = _step(view, "c_s1_sel1", ctx)
    condition = _step(view, "c_s1_cc1", ctx)

    assert observation["slots"] == {"arg1": "ent_1", "arg2": "ent_2"}  # the argument positions of iv_v6
    assert (condition["type"], condition["term"], condition["depends_on"]) == (
        "condition",
        "g_comparison_identity_ne",
        ["s_s1_sel1"],
    )


def test_audio_observations_have_a_term_and_the_alternatives() -> None:
    view = view_of("vehicle_collision_s15_C_audio")
    ctx = _context(view)

    first = _step(view, "c_s1_sel1", ctx)
    second = _step(view, "c_s1_sel2", ctx)

    assert (first["term"], first["alternatives"]) == (
        "g_audio_class_horn",
        ["g_audio_class_horn", "g_audio_class_skidding"],
    )
    assert first["refs"] == ["c_s1_sel1", "iv_a21", "g_audio_class_horn"]
    assert (second["term"], second["t_order"]) == ("g_audio_class_glass_breaking", 2.5)
    assert "slots" not in first
    assert "slots" not in second


def test_a_disjunction_names_the_alternative_seen() -> None:
    view = view_of("gunshot_or_explosion_s7_A")

    step = _step(view, "c_s1_sel1", _context(view))

    assert step["term"] == "g_predicate_explosion_visible"
    assert step["alternatives"] == ["g_predicate_gunshot_visible", "g_predicate_explosion_visible"]


def test_an_observation_without_interval_cites_only_the_alternatives() -> None:
    def unbound(data: dict[str, Any]) -> None:  # no interval of the draft satisfied M2 of s1
        _interval(data, "iv_a22")["bindings"] = [{"branch": "s9", "variable": "M2"}]

    view = view_of("vehicle_collision_s15_C_audio", unbound)
    step = _step(view, "c_s1_sel2", _context(view))

    assert "term" not in step
    assert step["refs"] == ["c_s1_sel2", "g_audio_class_impact", "g_audio_class_glass_breaking"]
    assert (step["t_order"], step["t_order_basis"]) == (None, "none")  # no candidate


def test_an_ambiguous_observation_takes_its_time_from_the_first_candidate() -> None:
    def two_witnesses(data: dict[str, Any]) -> None:  # M1 and M2 both between iv_v59 and iv_v60
        data["event"]["arguments"] = []
        node_data(data, "c_s1_proj")["payload"]["fields"] = ["M1.st", "M1.et", "M2.st", "M2.et"]
        for interval_id in ("iv_v59", "iv_v60"):
            _interval(data, interval_id)["bindings"] = [
                {"branch": "s1", "variable": "M1"},
                {"branch": "s1", "variable": "M2"},
            ]

    view = view_of("handoff_s21_A", two_witnesses)
    step = _step(view, "c_s1_sel1", _context(view))

    assert step["term"] == "g_predicate_carrying"  # the only predicate of the selection
    assert step["slots"] == {"arg1": None, "arg2": None}  # no interval and no row value: unknown
    assert step["refs"] == ["c_s1_sel1", "g_predicate_carrying"]
    assert (step["t_order"], step["t_order_basis"]) == (1.0, "interval")  # iv_v59 starts at 1.0 s (K4-A3)


def test_the_order_of_an_unordered_interval_names_no_one() -> None:
    def no_arguments(data: dict[str, Any]) -> None:  # iv_v6 is still the only candidate
        data["event"]["arguments"] = []
        _interval(data, "iv_v6")["args_ordered"] = False

    view = view_of("fight_s5_A", no_arguments)
    step = _step(view, "c_s1_sel1", _context(view))

    assert step["slots"] == {"arg1": None, "arg2": None}  # args_ordered is false: K4 assigns no roles
    assert step["refs"] == ["c_s1_sel1", "iv_v6", "g_predicate_physical_altercation"]


def test_duration_points_at_its_value_and_unit() -> None:
    view = view_of("suspicious_near_vehicle_s18_A")
    ctx = _context(view, t_orders={"s_s1_sel1": 2.0})

    step = _step(view, "c_s1_cc1", ctx)

    assert (step["type"], step["term"], step["depends_on"]) == (
        "condition",
        "g_comparison_duration_ge",
        ["s_s1_sel1"],
    )
    assert step["slots"] == {
        "x": "s_s1_sel1",
        "value": "#/rule/constraints/1/payload/value",
        "unit": "#/rule/constraints/1/payload/unit",
    }


def test_an_attribute_comparison_cites_a_side_without_id_by_pointer() -> None:
    def attribute(data: dict[str, Any]) -> None:
        node = node_data(data, "c_s1_cc1")
        node.update(kind="attribute_comparison")
        node["payload"] = {"left": "M1.arg1", "op": "=", "right": "M1.colour"}

    view = view_of("fight_s5_A", attribute)
    step = _step(view, "c_s1_cc1", _context(view, t_orders={"s_s1_sel1": 0.0}))

    assert (step["type"], step["term"]) == ("condition", "g_comparison_attribute_comparison_eq")
    assert step["slots"] == {"left": "ent_1", "right": "#/rule/constraints/1/payload/right"}


def test_an_attribute_comparison_leaves_an_unknown_argument_null() -> None:
    def attribute(data: dict[str, Any]) -> None:  # no row values, and iv_v6 has no argument order
        data["event"]["arguments"] = []
        _interval(data, "iv_v6")["args_ordered"] = False
        node = node_data(data, "c_s1_cc1")
        node.update(kind="attribute_comparison")
        node["payload"] = {"left": "M1.arg1", "op": "<", "right": "M1.st"}

    view = view_of("fight_s5_A", attribute)
    step = _step(view, "c_s1_cc1", _context(view, t_orders={"s_s1_sel1": 0.0}))

    # null as in an identity: the pointer is only for a side that is not an argument
    assert step["slots"] == {"left": None, "right": "#/rule/constraints/1/payload/right"}
    assert step["refs"] == [
        "c_s1_cc1",
        "#/rule/constraints/1/payload/right",
        "g_comparison_attribute_comparison_lt",
    ]


def test_t_order_is_null_when_no_dependency_has_one() -> None:
    view = view_of("handoff_s21_A")
    ctx = _context(view, t_orders={"s_s1_sel1": None, "s_s1_sel2": None})

    step = _step(view, "c_s1_op1", ctx)

    assert (step["t_order"], step["t_order_basis"]) == (None, "none")


def test_a_rule_refuses_a_node_of_another_kind() -> None:
    view = view_of("handoff_s21_A")

    with pytest.raises(TypeError):
        RULES["selection"].translate(view.node("c_s1_op1"), _context(view))
