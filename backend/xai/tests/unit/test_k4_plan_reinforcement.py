"""Reinforcement: a step only when K2 wrote a fixed sentence for it."""

import pytest

from xai.contract.plan import StepRole, StepType
from xai.contract.source_of_truth import source_of_truth_to_data
from xai.k4_planner.reinforcement import ReinforcementRule
from xai.tests.k4_plan_support import (
    AUDIO,
    frames_missing,
    plan_of,
    resolve_pointer,
    source_and_plan,
    step,
    step_ids,
    without_audio_rule,
)
from xai.tests.k4_support import view_of


def test_a_multimodal_row_has_the_step_with_the_sentence_of_k2() -> None:
    document, plan = source_and_plan(AUDIO)

    made = step(plan, "s_reinforcement")

    assert made.type is StepType.REINFORCEMENT
    assert made.role is StepRole.CONTEXT
    assert made.in_report2 is True
    assert made.fixed_text == document.event.reinforcement.sentence  # type: ignore[union-attr]
    assert made.depends_on == ["s_s1_proj"]
    assert made.t_order == step(plan, "s_s1_proj").t_order


def test_it_cites_the_event_and_each_detection_by_modality() -> None:
    document, plan = source_and_plan(AUDIO)
    data = source_of_truth_to_data(document)

    refs = step(plan, "s_reinforcement").refs

    detections = data["event"]["modality_detections"]
    assert refs[0] == document.event.event_id
    assert refs[1:] == [f"#/event/modality_detections/{i}" for i in range(len(detections))]
    assert [resolve_pointer(data, ref) for ref in refs[1:]] == detections


@pytest.mark.parametrize("name", ["handoff_s21_A", "fight_s5_A"])
def test_a_row_that_is_not_multimodal_has_no_step(name: str) -> None:
    # not_multimodal has no sentence (K4-D2).
    assert "s_reinforcement" not in step_ids(plan_of(name))


def test_a_status_without_sentence_leaves_no_step() -> None:
    plan = plan_of(AUDIO, without_audio_rule)  # no_counterpart

    assert "s_reinforcement" not in step_ids(plan)
    assert (
        ReinforcementRule(view_of(AUDIO, without_audio_rule)).step(["s_s1_proj"], {"s_s1_proj": 2.5}) is None
    )


def test_not_comparable_has_its_step_too() -> None:
    # K4-D3: its sentence says that frame numbers are missing, and Report 2 reads it.
    document, plan = source_and_plan(AUDIO, frames_missing)

    made = step(plan, "s_reinforcement")

    assert document.event.reinforcement is not None
    assert document.event.reinforcement.status.value == "not_comparable"
    assert made.fixed_text == document.event.reinforcement.sentence
