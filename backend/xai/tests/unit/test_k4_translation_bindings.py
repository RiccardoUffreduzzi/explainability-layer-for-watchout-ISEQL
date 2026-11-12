"""Which interval each variable stands for (UC-K4-04, K4-A2, K4-D1).

The candidates of a variable are the intervals whose ``bindings`` name it: K1 copies
them from WatchOut's lineage.
"""

from typing import Any

import pytest

from xai.contract.plan import BindingStatus
from xai.k4_planner.bindings import BASIS_LINEAGE, resolve_bindings
from xai.tests.k4_support import view_of

CASES = [
    ("handoff_s21_A", "s1", "M1", ["iv_v59"]),
    ("handoff_s21_A", "s1", "M2", ["iv_v60"]),
    ("fight_s5_A", "s1", "M1", ["iv_v6"]),
    ("vehicle_collision_s15_C_audio", "s1", "M1", ["iv_a21"]),
    ("vehicle_collision_s15_C_audio", "s1", "M2", ["iv_a22"]),
    ("vehicle_collision_s15_C_visual", "s2", "M1", ["iv_v48"]),
    ("gunshot_or_explosion_s7_A", "s1", "M1", ["iv_v11"]),
]


@pytest.mark.parametrize(
    ("name", "branch", "variable", "intervals"), CASES, ids=[f"{c[0]}-{c[2]}" for c in CASES]
)
def test_each_variable_of_a_golden_draft_is_attributed(
    name: str, branch: str, variable: str, intervals: list[str]
) -> None:
    found = {b.variable: b for b in resolve_bindings(view_of(name), branch)}[variable]

    assert found.status is BindingStatus.ATTRIBUTED
    assert list(found.candidates) == intervals
    assert found.basis == (BASIS_LINEAGE,)
    assert found.interval_id == intervals[0]


def _interval(data: dict[str, Any], interval_id: str) -> dict[str, Any]:
    interval: dict[str, Any] = next(i for i in data["intervals"] if i["interval_id"] == interval_id)
    return interval


def test_two_witnesses_leave_the_variable_ambiguous() -> None:
    def both_m1(data: dict[str, Any]) -> None:  # iv_v60 also satisfies M1 in another witness
        _interval(data, "iv_v60")["bindings"].append({"branch": "s1", "variable": "M1"})

    found = resolve_bindings(view_of("handoff_s21_A", both_m1), "s1")

    assert [(b.variable, b.status, b.candidates) for b in found] == [
        ("M1", BindingStatus.AMBIGUOUS, ("iv_v59", "iv_v60")),
        ("M2", BindingStatus.ATTRIBUTED, ("iv_v60",)),
    ]
    assert found[0].interval_id is None


def test_an_interval_bound_in_another_branch_is_no_candidate() -> None:
    def other_branch(data: dict[str, Any]) -> None:
        _interval(data, "iv_v59")["bindings"] = [{"branch": "s9", "variable": "M1"}]

    found = resolve_bindings(view_of("handoff_s21_A", other_branch), "s1")[0]

    assert found.status is BindingStatus.NOT_FOUND
    assert found.candidates == ()


def test_the_binding_record_of_the_plan() -> None:
    record = resolve_bindings(view_of("handoff_s21_A"), "s1")[1].to_binding()

    assert record.model_dump(mode="json") == {
        "branch": "s1",
        "variable": "M2",
        "status": "attributed",
        "interval_ids": ["iv_v60"],
        "basis": ["engine_lineage"],
    }
