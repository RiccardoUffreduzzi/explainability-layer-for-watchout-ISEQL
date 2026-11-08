"""The view of K4 on the source of truth : every ID found, nothing decided."""

from pathlib import Path
from typing import Any

import pytest

from xai.contract.model import ProjectionNode
from xai.contract.source_of_truth import ReinforcementStatus, SourceOfTruth
from xai.k4_planner.view import SourceOfTruthView
from xai.tests.k4_support import GOLDEN_NAMES, REAL_SOURCE_PATHS, golden_source, real_source, view_of


def _check_every_id_is_found(document: SourceOfTruth) -> None:
    view = SourceOfTruthView.of(document)

    for position, node in enumerate(document.rule.constraints):
        assert view.node(node.constraint_id) == node
        assert view.node_index(node.constraint_id) == position
    for interval in document.intervals:
        assert view.interval(interval.interval_id) == interval
    for entity in document.entities:
        assert view.entity(entity.entity_id) == entity
    for entry in document.glossary:
        assert view.term(entry.term_id) == entry
    for argument in document.event.arguments:
        assert view.argument(argument.role) == argument
    for branch in view.branches():
        assert all(node.branch == branch for node in view.nodes_of(branch))
        assert isinstance(view.projection_of(branch), ProjectionNode)
    assert view.limits() == tuple(document.knowledge_limits)


@pytest.mark.parametrize("name", GOLDEN_NAMES)
def test_every_id_of_a_golden_source_is_found(name: str) -> None:
    _check_every_id_is_found(golden_source(name))


@pytest.mark.parametrize("path", REAL_SOURCE_PATHS, ids=lambda p: p.name)
def test_every_id_of_a_real_source_is_found(path: Path) -> None:
    _check_every_id_is_found(real_source(path))


@pytest.mark.parametrize(
    ("name", "branches", "origin"),
    [
        ("handoff_s21_A", ("s1",), ()),
        ("vehicle_collision_s15_C_audio", ("s1", "s2"), ("s1",)),
        ("vehicle_collision_s15_C_visual", ("s1", "s2"), ("s2",)),
        ("vehicle_collision_s15_C_F3_visual", ("left", "right"), ("right",)),
    ],
)
def test_branches_in_rule_order_and_the_origin_of_the_row(
    name: str, branches: tuple[str, ...], origin: tuple[str, ...]
) -> None:
    view = view_of(name)

    assert view.branches() == branches
    assert view.origin_branches() == origin


def test_the_origin_string_of_k1_is_split_in_one_place() -> None:
    def both(data: dict[str, Any]) -> None:
        data["event"]["origin_basis"]["branch"] = "s1, s2"

    assert view_of("vehicle_collision_s15_C_audio", both).origin_branches() == ("s1", "s2")


def test_a_projected_argument_by_role() -> None:
    view = view_of("handoff_s21_A")

    argument = view.argument("M1.arg1")
    assert argument is not None
    assert argument.entity_id == "ent_3"
    assert view.argument("M2.arg2") is None


def test_the_reinforcement_as_k2_writes_it() -> None:
    multimodal = view_of("vehicle_collision_s15_C_audio").reinforcement()
    visual = view_of("handoff_s21_A").reinforcement()

    assert multimodal is not None
    assert multimodal.status is ReinforcementStatus.BOTH_OVERLAPPING
    assert multimodal.sentence
    assert visual is not None
    assert visual.status is ReinforcementStatus.NOT_MULTIMODAL
    assert visual.sentence is None


def test_the_limits_keep_the_refs_of_k2() -> None:
    refs = {limit.code.value: limit.refs for limit in view_of("handoff_s21_A").limits()}

    assert refs["reid_dependence"] == ["c_s1_cc1", "c_s1_cc2"]
    assert refs["temporal_resolution"] is None


def test_a_pointer_to_a_threshold() -> None:
    view = view_of("handoff_s21_A")

    assert (
        view.pointer("c_s1_op1", "payload", "params", 0, "engine_value")
        == "#/rule/constraints/3/payload/params/0/engine_value"
    )
    assert view.pointer("c_s1_proj") == "#/rule/constraints/0"


def test_a_pointer_escapes_its_tokens() -> None:
    assert view_of("handoff_s21_A").pointer("c_s1_proj", "a/b", "c~d") == "#/rule/constraints/0/a~1b/c~0d"
