"""Which interval each variable stands for (UC-K4-04, K4-A2, K4-D1)."""

from typing import Any

import pytest

from xai.contract.model import SelectionNode
from xai.contract.plan import BindingStatus
from xai.k4_planner.bindings import by_predicate_and_classes, resolve_bindings
from xai.tests.k4_support import node_data, view_of

CASES = [
    (
        "handoff_s21_A",
        "s1",
        "M1",
        "attributed",
        ["iv_v59"],
        ["predicate", "arg_classes", "M1.arg1", "M1.arg2", "M1.st"],
    ),
    ("handoff_s21_A", "s1", "M2", "attributed", ["iv_v60"], ["predicate", "arg_classes", "M2.arg1", "M2.et"]),
    (
        "fight_s5_A",
        "s1",
        "M1",
        "attributed",
        ["iv_v6"],
        ["predicate", "arg_classes", "M1.arg1", "M1.arg2", "M1.st", "M1.et"],
    ),
    ("vehicle_collision_s15_C_audio", "s1", "M1", "attributed", ["iv_a21"], ["predicate", "M1.st"]),
    ("vehicle_collision_s15_C_audio", "s1", "M2", "attributed", ["iv_a22"], ["predicate", "M2.et"]),
    (
        "gunshot_or_explosion_s7_A",
        "s1",
        "M1",
        "attributed",
        ["iv_v11"],
        ["predicate", "arg_classes", "M1.arg1", "M1.st", "M1.et"],
    ),
]


@pytest.mark.parametrize(
    ("name", "branch", "variable", "status", "intervals", "basis"),
    CASES,
    ids=[f"{c[0]}-{c[2]}" for c in CASES],
)
def test_outcome_candidates_and_basis(
    name: str, branch: str, variable: str, status: str, intervals: list[str], basis: list[str]
) -> None:
    found = {b.variable: b for b in resolve_bindings(view_of(name), branch)}[variable]

    assert found.status.value == status
    assert list(found.candidates) == intervals
    assert list(found.basis) == basis
    assert found.interval_id == intervals[0]


def _criterion_1(name: str) -> dict[str, tuple[str, ...]]:
    """The candidates of criterion 1 alone, for the selections of branch s1."""
    view = view_of(name)
    return {
        node.variables[0]: by_predicate_and_classes(view, node)
        for node in view.nodes_of("s1")
        if isinstance(node, SelectionNode)
    }


def test_predicate_and_classes_alone_are_ambiguous_in_handoff() -> None:
    assert _criterion_1("handoff_s21_A") == {"M1": ("iv_v59", "iv_v60"), "M2": ("iv_v59", "iv_v60")}


def test_predicate_alone_is_ambiguous_for_m2_of_the_audio_row() -> None:
    assert _criterion_1("vehicle_collision_s15_C_audio")["M2"] == ("iv_a22", "iv_a23")


def test_an_interval_with_too_few_arguments_is_no_candidate() -> None:
    assert _criterion_1("fight_s5_A") == {"M1": ("iv_v6",)}  # iv_v7 has one participant


def test_without_projected_values_a_variable_stays_ambiguous() -> None:
    def no_row_values(data: dict[str, Any]) -> None:
        data["event"]["arguments"] = []
        node_data(data, "c_s1_proj")["payload"]["fields"] = ["M1.st", "M1.et", "M2.st", "M2.et"]

    found = resolve_bindings(view_of("handoff_s21_A", no_row_values), "s1")

    assert [(b.variable, b.status, b.candidates) for b in found] == [
        ("M1", BindingStatus.AMBIGUOUS, ("iv_v59", "iv_v60")),
        ("M2", BindingStatus.AMBIGUOUS, ("iv_v59", "iv_v60")),
    ]
    assert found[0].interval_id is None
    assert list(found[0].basis) == ["predicate", "arg_classes"]  # two .st fields: no endpoint criterion


def test_no_candidate_is_not_found() -> None:
    def other_entity(data: dict[str, Any]) -> None:
        data["event"]["arguments"][0]["entity_id"] = "ent_99"

    found = resolve_bindings(view_of("handoff_s21_A", other_entity), "s1")[0]

    assert found.status is BindingStatus.NOT_FOUND
    assert found.candidates == ()


def test_an_unordered_interval_matches_an_argument_in_any_position() -> None:
    def swapped(data: dict[str, Any]) -> None:  # the other row of fight s5: arguments swapped
        arguments = data["event"]["arguments"]
        arguments[0]["entity_id"], arguments[1]["entity_id"] = "ent_2", "ent_1"

    found = resolve_bindings(view_of("fight_s5_A", swapped), "s1")[0]

    assert found.candidates == ("iv_v6",)


def test_the_binding_record_of_the_plan() -> None:
    record = resolve_bindings(view_of("handoff_s21_A"), "s1")[1].to_binding()

    assert record.model_dump(mode="json") == {
        "branch": "s1",
        "variable": "M2",
        "status": "attributed",
        "interval_ids": ["iv_v60"],
        "basis": ["predicate", "arg_classes", "M2.arg1", "M2.et"],
    }
