"""Properties of the plans of the limits, the order and the delivery, on the golden sources.

They hold for every plan, whatever the row: they are the checks that K4 does not make at run
time (K4-D6). Each runs on the example drafts of K1 and on variants that exercise the rare
paths: undefined terms, two explained branches, no audio rule, frames missing, no merge
tolerance.
"""

from typing import Any

import jsonschema
import pytest

from xai.contract.plan import IN_REPORT2, ExplanationPlan, PlanStep, StepType, compute_plan_hash, plan_to_data
from xai.contract.plan_schema import plan_schema
from xai.contract.source_of_truth import SourceOfTruth, source_of_truth_to_data
from xai.tests.k4_plan_support import (
    AUDIO,
    AUDIO_CLASSES,
    both_branches,
    frames_missing,
    resolve_pointer,
    source_and_plan,
    undefine_terms,
    without_audio_rule,
    without_merge_tolerance,
)
from xai.tests.k4_support import GOLDEN_NAMES, Change

Case = tuple[str, Change | None]
CASES: list[Case] = [
    *((name, None) for name in GOLDEN_NAMES),
    (AUDIO, undefine_terms(*AUDIO_CLASSES)),
    (AUDIO, undefine_terms("g_operator_SP")),
    (AUDIO, without_audio_rule),
    (AUDIO, frames_missing),
    ("vehicle_collision_s15_C_F3_visual", both_branches),
    ("vehicle_collision_s15_C_visual", undefine_terms("g_audio_class_horn")),
    ("handoff_s21_A", without_merge_tolerance),
]
IDS = [f"{name}-{i}" for i, (name, _) in enumerate(CASES)]


@pytest.fixture(params=CASES, ids=IDS)
def made(request: pytest.FixtureRequest) -> tuple[SourceOfTruth, ExplanationPlan]:
    name, change = request.param
    return source_and_plan(name, change)


def _position(plan: ExplanationPlan) -> dict[str, int]:
    return {s.step_id: i for i, s in enumerate(plan.steps)}


def _of_type(plan: ExplanationPlan, step_type: StepType) -> list[PlanStep]:
    return [s for s in plan.steps if s.type is step_type]


def test_step_ids_are_unique(made: tuple[SourceOfTruth, ExplanationPlan]) -> None:
    ids = [s.step_id for s in made[1].steps]

    assert len(ids) == len(set(ids))


def test_every_step_comes_after_the_steps_it_depends_on(made: tuple[SourceOfTruth, ExplanationPlan]) -> None:
    position = _position(made[1])

    for s in made[1].steps:
        assert all(position[d] < position[s.step_id] for d in s.depends_on), s.step_id


def test_every_limit_of_k2_has_one_step_right_after_its_last_anchor(
    made: tuple[SourceOfTruth, ExplanationPlan],
) -> None:
    document, plan = made
    position = _position(plan)
    limit_steps = _of_type(plan, StepType.LIMIT)

    assert len(limit_steps) == len(document.knowledge_limits)
    assert {s.limit_code for s in limit_steps} == {limit.code for limit in document.knowledge_limits}
    for s in limit_steps:
        last = max(position[d] for d in s.depends_on)
        between = [p.step_id for p in plan.steps[last + 1 : position[s.step_id]]]
        assert all(i.startswith("s_lim_") for i in between), (s.step_id, between)


def test_a_limit_step_copies_the_sentence_and_the_refs_of_k2(
    made: tuple[SourceOfTruth, ExplanationPlan],
) -> None:
    document, plan = made
    by_code = {limit.code: limit for limit in document.knowledge_limits}

    for s in _of_type(plan, StepType.LIMIT):
        assert s.limit_code is not None
        assert s.fixed_text == by_code[s.limit_code].sentence
        assert s.refs[1:] == list(by_code[s.limit_code].refs or ())


def test_the_reinforcement_step_exists_if_and_only_if_k2_wrote_a_sentence(
    made: tuple[SourceOfTruth, ExplanationPlan],
) -> None:
    document, plan = made
    reinforcement = document.event.reinforcement
    has_sentence = reinforcement is not None and reinforcement.sentence is not None

    assert len(_of_type(plan, StepType.REINFORCEMENT)) == (1 if has_sentence else 0)


def test_the_reinforcement_comes_after_the_last_conclusion_and_all_the_limits(
    made: tuple[SourceOfTruth, ExplanationPlan],
) -> None:
    plan = made[1]
    position = _position(plan)
    found = _of_type(plan, StepType.REINFORCEMENT)
    if not found:
        return  # the rows with no reinforcement step have nothing to order
    after = [
        position[s.step_id] for s in _of_type(plan, StepType.CONCLUSION) + _of_type(plan, StepType.LIMIT)
    ]

    assert position[found[0].step_id] > max(after)


def test_the_provenance_steps_are_the_last_ones(made: tuple[SourceOfTruth, ExplanationPlan]) -> None:
    kinds = [s.type for s in made[1].steps]
    first = kinds.index(StepType.PROVENANCE)

    assert all(k is StepType.PROVENANCE for k in kinds[first:])


def test_in_report2_follows_the_type(made: tuple[SourceOfTruth, ExplanationPlan]) -> None:
    assert all(s.in_report2 is IN_REPORT2[s.type] for s in made[1].steps)


def test_every_ref_is_a_fact_of_the_source_or_a_pointer_that_resolves(
    made: tuple[SourceOfTruth, ExplanationPlan],
) -> None:
    document, plan = made
    data = source_of_truth_to_data(document)
    ids = {
        *(i.interval_id for i in document.intervals),
        *(e.entity_id for e in document.entities),
        *(n.constraint_id for n in document.rule.constraints),
        *(g.term_id for g in document.glossary),
        document.event.event_id,
    }

    for s in plan.steps:
        for ref in s.refs:
            if ref.startswith("#/"):
                resolve_pointer(data, ref)
            else:
                assert ref in ids, (s.step_id, ref)


def test_the_text_of_the_steps_made_here_is_a_copy_of_the_contract(
    made: tuple[SourceOfTruth, ExplanationPlan],
) -> None:
    document, plan = made
    sentences = {limit.sentence for limit in document.knowledge_limits}
    if document.event.reinforcement is not None and document.event.reinforcement.sentence:
        sentences.add(document.event.reinforcement.sentence)

    for s in plan.steps:
        if s.type in (StepType.LIMIT, StepType.REINFORCEMENT):
            assert s.fixed_text in sentences
        if s.type is StepType.PROVENANCE:
            assert s.fixed_text is None


def test_the_plan_is_valid_and_its_hash_is_the_one_of_its_content(
    made: tuple[SourceOfTruth, ExplanationPlan],
) -> None:
    plan = made[1]
    data: dict[str, Any] = plan_to_data(plan)

    jsonschema.validate(data, plan_schema())
    assert compute_plan_hash(data) == plan.plan_meta.plan_hash
