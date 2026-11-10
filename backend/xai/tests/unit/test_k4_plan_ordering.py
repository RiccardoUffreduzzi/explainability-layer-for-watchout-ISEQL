"""Reading order: dependencies, time, type, rule position; limits, reinforcement, provenance."""

import dataclasses
import random

import pytest

from xai.contract.plan import PlanStep
from xai.k4_planner.limits import LimitLinker
from xai.k4_planner.ordering import ReadingOrder
from xai.k4_planner.translation import BranchSteps
from xai.tests.k4_plan_support import (
    AUDIO,
    AUDIO_CLASSES,
    both_branches,
    plan_of,
    reading_ids,
    translation_of,
    undefine_terms,
)
from xai.tests.k4_support import view_of

HANDOFF = [
    "s_s1_sel1",
    "s_s1_sel2",
    "s_s1_op1",
    "s_s1_cc1",
    "s_s1_cc2",
    "s_lim_reid_dependence",
    "s_lim_reid_evidence_unavailable",
    "s_s1_proj",
    "s_lim_visual_confidence_unavailable",
    "s_lim_perceptual_attribution_unavailable",
    "s_lim_temporal_resolution",
    "s_lim_data_not_available",
]
FIGHT = [
    "s_s1_sel1",
    "s_s1_cc1",
    "s_lim_reid_dependence",
    "s_lim_reid_evidence_unavailable",
    "s_s1_proj",
    "s_lim_visual_confidence_unavailable",
    "s_lim_perceptual_attribution_unavailable",
    "s_lim_temporal_resolution",
    "s_lim_data_not_available",
]
AUDIO_WITH_GLOSSARY_LIMIT = [
    "s_s1_sel1",
    "s_s1_sel2",
    "s_lim_glossary_entry_missing",
    "s_s1_op1",
    "s_s1_proj",
    "s_lim_temporal_resolution",
    "s_lim_audio_without_participants",
    "s_lim_data_not_available",
    "s_reinforcement",
]


def test_the_handoff_row_reads_like_the_expected_table() -> None:
    assert reading_ids(plan_of("handoff_s21_A")) == HANDOFF


def test_the_fight_row_reads_like_the_expected_table() -> None:
    assert reading_ids(plan_of("fight_s5_A")) == FIGHT


def test_the_audio_row_reads_like_the_expected_table() -> None:
    plan = plan_of(AUDIO, undefine_terms(*AUDIO_CLASSES))

    assert reading_ids(plan) == AUDIO_WITH_GLOSSARY_LIMIT


def test_the_audio_row_as_k2_writes_it_today_has_no_glossary_limit() -> None:
    assert reading_ids(plan_of(AUDIO)) == [i for i in AUDIO_WITH_GLOSSARY_LIMIT if "glossary" not in i]


def test_the_provenance_steps_close_the_plan() -> None:
    plan = plan_of(AUDIO)
    ids = [s.step_id for s in plan.steps]
    first = next(i for i, name in enumerate(ids) if name.startswith("s_prov_"))

    assert all(name.startswith("s_prov_") for name in ids[first:])
    assert ids[first - 1] == "s_reinforcement"


def _branch(name: str) -> BranchSteps:
    return translation_of(name).branches[0]


def _with_steps(branch: BranchSteps, steps: list[PlanStep]) -> BranchSteps:
    return dataclasses.replace(branch, steps=tuple(steps))


def _order(name: str, branches: list[BranchSteps]) -> list[str]:
    view = view_of(name)
    limits = LimitLinker(view).link(branches)
    return [s.step_id for s in ReadingOrder(view).order(branches, limits, None, ())]


@pytest.mark.parametrize("seed", range(5))
def test_the_order_does_not_depend_on_the_order_of_the_translated_steps(seed: int) -> None:
    branch = _branch("handoff_s21_A")
    shuffled = list(branch.steps)
    random.Random(seed).shuffle(shuffled)

    assert _order("handoff_s21_A", [_with_steps(branch, shuffled)]) == HANDOFF


def test_among_ready_steps_the_earlier_one_in_time_comes_first() -> None:
    branch = _branch("handoff_s21_A")
    earlier = [s.model_copy(update={"t_order": 0.5}) if s.step_id == "s_s1_sel2" else s for s in branch.steps]

    order = _order("handoff_s21_A", [_with_steps(branch, earlier)])

    assert order.index("s_s1_sel2") < order.index("s_s1_sel1")


def test_a_step_with_no_time_comes_after_the_steps_that_have_one() -> None:
    branch = _branch("handoff_s21_A")
    untimed = [
        s.model_copy(update={"t_order": None}) if s.step_id == "s_s1_sel1" else s for s in branch.steps
    ]

    order = _order("handoff_s21_A", [_with_steps(branch, untimed)])

    assert order.index("s_s1_sel2") < order.index("s_s1_sel1")


def test_at_the_same_time_the_temporal_step_comes_before_the_identity_ones() -> None:
    order = reading_ids(plan_of("handoff_s21_A"))

    assert order.index("s_s1_op1") < order.index("s_s1_cc1") < order.index("s_s1_cc2")


def test_a_cyclic_dependency_is_an_error() -> None:
    branch = _branch("fight_s5_A")
    cyclic = [
        s.model_copy(update={"depends_on": ["s_s1_cc1"]}) if s.step_id == "s_s1_sel1" else s
        for s in branch.steps
    ]

    with pytest.raises(ValueError, match="cyclic"):
        _order("fight_s5_A", [_with_steps(branch, cyclic)])


def test_branches_come_in_the_order_of_their_first_time_and_are_not_interleaved() -> None:
    plan = plan_of("vehicle_collision_s15_C_F3_visual", both_branches)

    assert reading_ids(plan)[:6] == [
        "s_right_sel1",
        "s_right_proj",
        "s_left_sel1",
        "s_left_sel2",
        "s_left_op1",
        "s_left_proj",
    ]


def test_branches_with_the_same_first_time_keep_the_rule_order() -> None:
    name = "vehicle_collision_s15_C_F3_visual"
    from xai.k4_planner.translation import translate
    from xai.k4_planner.view import SourceOfTruthView
    from xai.tests.k4_support import golden_source

    view = SourceOfTruthView.of(golden_source(name, both_branches))
    branches = [
        _with_steps(b, [s.model_copy(update={"t_order": 6.0}) for s in b.steps])
        for b in translate(view).branches
    ]

    order = [s.step_id for s in ReadingOrder(view).order(branches, (), None, ())]

    assert order[0].startswith("s_left_")
    assert order[-1] == "s_right_proj"


def test_a_limit_hooked_to_both_conclusions_goes_after_the_last_one() -> None:
    order = reading_ids(plan_of("vehicle_collision_s15_C_F3_visual", both_branches))

    assert order.index("s_lim_temporal_resolution") > order.index("s_left_proj")
    assert order[-1] == "s_reinforcement"


def test_limits_after_the_same_step_follow_the_order_of_k2() -> None:
    order = reading_ids(plan_of("handoff_s21_A"))

    assert order[order.index("s_s1_proj") + 1 :] == [
        "s_lim_visual_confidence_unavailable",
        "s_lim_perceptual_attribution_unavailable",
        "s_lim_temporal_resolution",
        "s_lim_data_not_available",
    ]
