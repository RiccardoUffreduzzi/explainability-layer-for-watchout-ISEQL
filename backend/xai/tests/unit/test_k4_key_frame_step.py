"""The step of the key frame of the detection, ``s_key_frame`` (UC-K4-15)."""

from typing import Any

import pytest

from xai.contract.plan import IN_REPORT2, StepRole, StepType, TOrderBasis
from xai.k4_planner.key_frame import KEY_FRAME_STEP_ID, KeyFrameRule
from xai.tests.k4_plan_support import plan_of, step, step_ids
from xai.tests.k4_support import GOLDEN_NAMES, view_of


def _without_key_frame(data: dict[str, Any]) -> None:
    data["event"]["key_frame"] = None
    data["event"].setdefault("unavailable", {})["key_frame"] = {"reason": "keyframe_not_shown", "detail": "x"}


def test_the_handoff_key_frame_is_a_context_step_after_the_conclusion() -> None:
    plan = plan_of("handoff_s21_A")

    key_frame = step(plan, KEY_FRAME_STEP_ID)

    assert (key_frame.type, key_frame.role) == (StepType.CONTEXT, StepRole.CONTEXT)
    assert key_frame.refs == ["kf_108"]
    assert key_frame.depends_on == ["s_s1_proj"]
    assert (key_frame.t_order, key_frame.t_order_basis) == (None, TOrderBasis.NONE)
    assert key_frame.in_report2 is IN_REPORT2[StepType.CONTEXT] is True
    assert key_frame.construct_ is None and key_frame.term is None and key_frame.fixed_text is None


@pytest.mark.parametrize("name", GOLDEN_NAMES)
def test_every_golden_plan_cites_the_key_frame_of_its_event_only_in_its_step(name: str) -> None:
    plan = plan_of(name)
    key_frame = view_of(name).event.key_frame
    assert key_frame is not None

    citing = [s.step_id for s in plan.steps if key_frame.keyframe_id in s.refs]

    assert citing == [KEY_FRAME_STEP_ID]
    conclusions = [s.step_id for s in plan.steps if s.type is StepType.CONCLUSION]
    assert step(plan, KEY_FRAME_STEP_ID).depends_on == conclusions


@pytest.mark.parametrize("name", GOLDEN_NAMES)
def test_without_key_frame_there_is_no_step(name: str) -> None:
    plan = plan_of(name, _without_key_frame)

    assert KEY_FRAME_STEP_ID not in step_ids(plan)
    assert not any(ref.startswith("kf_") for s in plan.steps for ref in s.refs)


def test_the_rule_reads_the_key_frame_from_the_view() -> None:
    view = view_of("fight_s5_A")

    made = KeyFrameRule(view).step(["s_s1_proj"])

    assert made is not None and made.refs == ["kf_60"]
