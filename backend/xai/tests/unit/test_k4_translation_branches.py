"""Which branches are explained and which nodes are left out (UC-K4-03, K4-A8)."""

from typing import Any

import pytest

from xai.k4_planner.branches import choose_branches
from xai.tests.k4_support import view_of

CASES = [
    ("handoff_s21_A", ("s1",), []),
    ("fight_s5_A", ("s1",), []),
    (
        "vehicle_collision_s15_C_audio",
        ("s1",),
        [("c_set1", "set_operation"), ("c_s2_proj", "other_branch"), ("c_s2_sel1", "other_branch")],
    ),
    (
        "vehicle_collision_s15_C_visual",
        ("s2",),
        [
            ("c_set1", "set_operation"),
            ("c_s1_proj", "other_branch"),
            ("c_s1_op1", "other_branch"),
            ("c_s1_sel1", "other_branch"),
            ("c_s1_sel2", "other_branch"),
        ],
    ),
    (
        "vehicle_collision_s15_C_F3_visual",
        ("right",),
        [
            ("c_set1", "set_operation"),
            ("c_left_proj", "other_branch"),
            ("c_left_op1", "other_branch"),
            ("c_left_sel1", "other_branch"),
            ("c_left_sel2", "other_branch"),
        ],
    ),
]


@pytest.mark.parametrize(("name", "explained", "excluded"), CASES, ids=[c[0] for c in CASES])
def test_explained_and_excluded(
    name: str, explained: tuple[str, ...], excluded: list[tuple[str, str]]
) -> None:
    choice = choose_branches(view_of(name))

    assert choice.explained == explained
    assert [(e.constraint_id, e.reason.value) for e in choice.excluded] == excluded


def test_a_row_of_both_modalities_explains_both_branches() -> None:
    def both(data: dict[str, Any]) -> None:
        data["event"]["origin_basis"]["branch"] = "s1, s2"

    choice = choose_branches(view_of("vehicle_collision_s15_C_audio", both))

    assert choice.explained == ("s1", "s2")
    assert [(e.constraint_id, e.reason.value) for e in choice.excluded] == [("c_set1", "set_operation")]


@pytest.mark.parametrize("op", ["∩", "\\"])
def test_every_set_operation_is_left_out_the_same_way(op: str) -> None:
    def other_operation(data: dict[str, Any]) -> None:
        data["rule"]["constraints"][0]["payload"]["op"] = op

    choice = choose_branches(view_of("vehicle_collision_s15_C_audio", other_operation))

    assert choice.explained == ("s1",)
    assert choice.excluded[0].reason.value == "set_operation"
