"""Provenance: one step for each voice the contract has, in a fixed order."""

import pytest

from xai.contract.plan import Binding, BindingStatus, StepRole, StepType, TOrderBasis
from xai.contract.source_of_truth import source_of_truth_to_data
from xai.k4_planner.provenance import ProvenanceRule
from xai.tests.k4_plan_support import (
    AUDIO,
    resolve_pointer,
    source_and_plan,
    translation_of,
    without_merge_tolerance,
)
from xai.tests.k4_support import GOLDEN_NAMES, view_of

ALL_VOICES = [
    "sampling",
    "merge_tolerance",
    "determinism",
    "detection_mode",
    "params_origin",
    "modality_association",
    "bindings",
    "confidences",
    "contract_hash",
]


def _prov(plan_steps: list[str]) -> list[str]:
    return [i.removeprefix("s_prov_") for i in plan_steps if i.startswith("s_prov_")]


def test_a_row_with_every_voice_has_nine_steps_in_the_fixed_order() -> None:
    _, plan = source_and_plan(AUDIO)

    assert _prov([s.step_id for s in plan.steps]) == ALL_VOICES


def test_a_visual_row_has_no_modality_association_and_no_confidences() -> None:
    _, plan = source_and_plan("handoff_s21_A")

    assert _prov([s.step_id for s in plan.steps]) == [
        "sampling",
        "merge_tolerance",
        "determinism",
        "detection_mode",
        "params_origin",
        "bindings",
        "contract_hash",
    ]


def test_without_a_merge_tolerance_there_is_no_step_for_it() -> None:
    _, plan = source_and_plan("handoff_s21_A", without_merge_tolerance)

    assert "merge_tolerance" not in _prov([s.step_id for s in plan.steps])


def test_the_bindings_step_cites_each_candidate_once_in_rule_order() -> None:
    view = view_of("handoff_s21_A")
    bindings = [b for branch in translation_of("handoff_s21_A").branches for b in branch.bindings]
    repeated = [*bindings, bindings[0]]

    steps = ProvenanceRule(view).steps(repeated, reinforcement=False)

    assert next(s for s in steps if s.step_id == "s_prov_bindings").refs == ["iv_v59", "iv_v60"]


def test_no_bindings_step_when_no_variable_has_candidates() -> None:
    view = view_of("handoff_s21_A")
    nothing = Binding(
        branch="s1", variable="M1", status=BindingStatus.NOT_FOUND, interval_ids=[], basis=["predicate"]
    )

    for bindings in ([], [nothing]):
        steps = ProvenanceRule(view).steps(bindings, reinforcement=False)

        assert "s_prov_bindings" not in [s.step_id for s in steps]


def test_the_confidences_step_cites_the_intervals_that_have_one() -> None:
    document, plan = source_and_plan(AUDIO)
    measured = [i.interval_id for i in document.intervals if i.confidence is not None]

    assert next(s for s in plan.steps if s.step_id == "s_prov_confidences").refs == measured


def test_the_modality_association_follows_the_reinforcement() -> None:
    view = view_of(AUDIO)

    with_step = ProvenanceRule(view).steps([], reinforcement=True)
    without = ProvenanceRule(view).steps([], reinforcement=False)

    assert "s_prov_modality_association" in [s.step_id for s in with_step]
    assert "s_prov_modality_association" not in [s.step_id for s in without]


@pytest.mark.parametrize("name", GOLDEN_NAMES)
def test_a_provenance_step_is_context_with_no_dependency_and_no_time(name: str) -> None:
    _, plan = source_and_plan(name)

    for made in (s for s in plan.steps if s.type is StepType.PROVENANCE):
        assert made.role is StepRole.CONTEXT
        assert made.depends_on == []
        assert made.t_order is None
        assert made.t_order_basis is TOrderBasis.NONE
        assert made.in_report2 is False
        assert made.fixed_text is None


@pytest.mark.parametrize("name", GOLDEN_NAMES)
def test_every_pointer_of_a_provenance_step_names_something_in_the_source(name: str) -> None:
    document, plan = source_and_plan(name)
    data = source_of_truth_to_data(document)

    pointers = [r for s in plan.steps if s.type is StepType.PROVENANCE for r in s.refs if r.startswith("#/")]

    assert pointers
    for pointer in pointers:
        resolve_pointer(data, pointer)
