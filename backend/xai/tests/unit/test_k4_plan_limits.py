"""Limits: one step per knowledge limit of K2, hooked to the steps it comes from."""

import pytest

from xai.contract.plan import StepRole, StepType
from xai.contract.source_of_truth import LimitCode, source_of_truth_to_data
from xai.k4_planner.limits import LIMIT_DATA, LimitLinker
from xai.tests.k4_plan_support import (
    AUDIO,
    both_branches,
    plan_of,
    resolve_pointer,
    step,
    translation_of,
    undefine_terms,
)
from xai.tests.k4_support import GOLDEN_NAMES, view_of


@pytest.mark.parametrize("name", GOLDEN_NAMES)
def test_one_step_for_each_limit_in_the_order_of_k2(name: str) -> None:
    view = view_of(name)

    steps = LimitLinker(view).link(translation_of(name).branches)

    assert [s.step_id for s in steps] == [f"s_lim_{limit.code.value}" for limit in view.limits()]
    assert [s.limit_code for s in steps] == [limit.code for limit in view.limits()]


@pytest.mark.parametrize("name", GOLDEN_NAMES)
def test_a_limit_step_copies_what_k2_wrote(name: str) -> None:
    view = view_of(name)
    data = source_of_truth_to_data(view.document)

    steps = LimitLinker(view).link(translation_of(name).branches)

    for index, (made, limit) in enumerate(zip(steps, view.limits(), strict=True)):
        assert made.type is StepType.LIMIT
        assert made.role is StepRole.LIMIT
        assert made.in_report2 is False
        assert made.construct_ is None
        assert made.fixed_text == limit.sentence
        assert made.refs[0] == f"#/knowledge_limits/{index}"
        assert resolve_pointer(data, made.refs[0])["code"] == limit.code.value
        spoken_of = len(LIMIT_DATA.get(limit.code, ()))
        assert made.refs[1 + spoken_of :] == list(limit.refs or ())
        assert made.depends_on


def test_only_the_missing_data_limit_points_at_data_without_an_id() -> None:
    assert dict(LIMIT_DATA) == {LimitCode.DATA_NOT_AVAILABLE: (("harvest_report", "missing_fields"),)}


@pytest.mark.parametrize("name", GOLDEN_NAMES)
def test_the_missing_data_limit_points_at_the_missing_fields(name: str) -> None:
    view = view_of(name)
    data = source_of_truth_to_data(view.document)

    steps = LimitLinker(view).link(translation_of(name).branches)

    [made] = [s for s in steps if s.limit_code is LimitCode.DATA_NOT_AVAILABLE]
    assert made.refs[1:] == ["#/harvest_report/missing_fields"]
    assert resolve_pointer(data, made.refs[1]) == data["harvest_report"]["missing_fields"] != []
    for other in steps:
        if other is not made:
            assert "#/harvest_report/missing_fields" not in other.refs


def test_the_handoff_step_cites_its_four_missing_fields() -> None:
    plan = plan_of("handoff_s21_A")
    data = source_of_truth_to_data(view_of("handoff_s21_A").document)

    limit = step(plan, "s_lim_data_not_available")

    assert limit.refs == ["#/knowledge_limits/5", "#/harvest_report/missing_fields"]
    assert [(f["path"], f["reason"]) for f in resolve_pointer(data, limit.refs[1])] == [
        ("event.modality_rules.audio", "modality_rule_absent"),
        ("entities[*].reid_evidence", "reid_similarity_not_persisted"),
        ("intervals[*].confidence", "visual_confidence_not_recorded"),
        ("actions", "keyframes_not_persisted"),
    ]
    assert limit.depends_on == ["s_s1_proj"]  # the pointer adds no anchor


def test_the_reid_limits_are_hooked_to_the_identity_nodes() -> None:
    plan = plan_of("handoff_s21_A")

    for code in ("reid_dependence", "reid_evidence_unavailable"):
        assert step(plan, f"s_lim_{code}").depends_on == ["s_s1_cc1", "s_s1_cc2"]
    assert step(plan, "s_lim_reid_dependence").refs[1:] == ["c_s1_cc1", "c_s1_cc2"]


def test_a_limit_without_refs_is_hooked_to_the_conclusion() -> None:
    plan = plan_of("fight_s5_A")

    for code in ("visual_confidence_unavailable", "temporal_resolution", "data_not_available"):
        assert step(plan, f"s_lim_{code}").depends_on == ["s_s1_proj"]


def test_the_glossary_limit_is_hooked_to_the_steps_that_use_the_terms() -> None:
    plan = plan_of(AUDIO, undefine_terms(*("g_audio_class_horn", "g_audio_class_glass_breaking")))

    limit = step(plan, "s_lim_glossary_entry_missing")

    assert limit.depends_on == ["s_s1_sel1", "s_s1_sel2"]
    assert limit.refs[1:] == ["g_audio_class_glass_breaking", "g_audio_class_horn"]


def test_a_term_used_only_as_an_alternative_hooks_the_step_that_lists_it() -> None:
    plan = plan_of(AUDIO, undefine_terms("g_audio_class_skidding"))

    assert step(plan, "s_lim_glossary_entry_missing").depends_on == ["s_s1_sel1"]


def test_a_term_cited_only_in_the_refs_of_a_step_hooks_that_step() -> None:
    plan = plan_of(AUDIO, undefine_terms("g_operator_SP"))

    assert step(plan, "s_lim_glossary_entry_missing").depends_on == ["s_s1_op1"]


def test_a_term_no_step_uses_falls_back_to_the_conclusion() -> None:
    # The audio classes appear in no step of a visual row.
    plan = plan_of("vehicle_collision_s15_C_visual", undefine_terms("g_audio_class_horn"))

    assert step(plan, "s_lim_glossary_entry_missing").depends_on == ["s_s2_proj"]


def test_with_two_branches_a_limit_without_refs_is_hooked_to_both_conclusions() -> None:
    plan = plan_of("vehicle_collision_s15_C_F3_visual", both_branches)

    limit = step(plan, "s_lim_temporal_resolution")

    assert limit.depends_on == ["s_left_proj", "s_right_proj"]
    assert limit.t_order == 6.0  # the latest of the conclusions that have one


def test_the_t_order_of_a_limit_is_the_latest_of_its_anchors() -> None:
    plan = plan_of("handoff_s21_A")

    assert step(plan, "s_lim_reid_dependence").t_order == 5.0
    assert step(plan, "s_lim_reid_dependence").t_order_basis.value == "interval"
