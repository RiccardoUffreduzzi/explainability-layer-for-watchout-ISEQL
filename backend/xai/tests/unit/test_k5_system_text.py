"""The sections the system writes: method and provenance, limits; with the values of the table."""

from dataclasses import replace
from typing import Any

import pytest

from xai.adapters.report_resources import load_sentences
from xai.contract.plan import Binding, BindingStatus
from xai.k5_report1.profile import REPORT1
from xai.reporting.failure import ReportFailure
from xai.reporting.reading import ParsedSection
from xai.reporting.system_text import system_sections
from xai.tests.k5_support import NAMES, ScriptedModel, hand_text, input_of, pair_of, writer

SENTENCES = load_sentences("report1")
HANDOFF = "handoff_s21_A"


def sections_of(name: str = HANDOFF, **change: Any) -> dict[str, ParsedSection]:
    report_input = input_of(name)
    if change:
        report_input = replace(report_input, plan=report_input.plan.model_copy(update=change))
    return {section.title: section for section in system_sections(REPORT1, report_input, SENTENCES)}


def bodies(section: ParsedSection) -> list[str]:
    return [sentence.body for sentence in section.sentences]


@pytest.mark.parametrize("name", NAMES)
def test_the_system_renders_every_step_of_its_sections(name: str) -> None:
    report_input = input_of(name)

    sections = system_sections(REPORT1, report_input, SENTENCES)

    assert [s.title for s in sections] == ["Method and provenance", "Limits"]
    assert all(s.written_by == "system" for s in sections)
    rendered = {step for s in sections for sentence in s.sentences for step in sentence.step_ids}
    assert rendered == {step.step_id for step in report_input.system_steps}
    names = {name for s in sections for sentence in s.sentences for name in sentence.names}
    assert names <= report_input.table.names()


def test_the_method_is_one_paragraph_with_the_intervals_of_the_variables() -> None:
    method = sections_of()["Method and provenance"]

    assert {sentence.block for sentence in method.sentences} == {0}
    assert bodies(method)[5] == (
        "WatchOut's lineage of this detection records M1 as the interval from {iv_v59.start} to "
        "{iv_v59.end} and M2 as the interval from {iv_v60.start} to {iv_v60.end}."
    )


def test_a_variable_with_more_than_one_interval_names_them_all() -> None:
    ambiguous = Binding(
        branch="s1",
        variable="M1",
        status=BindingStatus.AMBIGUOUS,
        interval_ids=["iv_v59", "iv_v60"],
        basis=["engine_lineage"],
    )

    method = sections_of(bindings=[ambiguous])["Method and provenance"]

    assert bodies(method)[5] == (
        "WatchOut's lineage of this detection records M1 as one of the intervals from {iv_v59.start} "
        "to {iv_v59.end} and from {iv_v60.start} to {iv_v60.end}, each a witness of the same detection row."
    )


def test_an_interval_of_a_single_analysed_frame_is_cited_by_its_time() -> None:
    def single_frame(draft: dict[str, Any]) -> None:
        anchor = draft["intervals"][0]["anchor"]
        anchor.update(end_frame=anchor["start_frame"], end_s=anchor["start_s"])

    report_input = input_of(HANDOFF, single_frame)
    method = {s.title: s for s in system_sections(REPORT1, report_input, SENTENCES)}["Method and provenance"]

    assert "records M1 as the interval at {iv_v59.at} and M2" in bodies(method)[5]


def test_the_limits_are_listed_by_the_steps_they_concern() -> None:
    limits = sections_of()["Limits"]

    assert [(s.body, s.block, s.list_item) for s in limits.sentences] == [
        ("These limits concern the conditions {c_s1_cc1.text} and {c_s1_cc2.text} of the rule.", 0, False),
        ("{s_lim_reid_dependence.fixed_text}", 1, True),
        ("{s_lim_reid_evidence_unavailable.fixed_text}", 2, True),
        ("These limits concern the whole detection.", 3, False),
        ("{s_lim_visual_confidence_unavailable.fixed_text}", 4, True),
        ("{s_lim_perceptual_attribution_unavailable.fixed_text}", 5, True),
        ("{s_lim_temporal_resolution.fixed_text}", 6, True),
        ("{s_lim_data_not_available.fixed_text}", 7, True),
        ("Not available here: {missing_fields}.", 7, True),
    ]
    assert limits.sentences[0].step_ids == ("s_lim_reid_dependence", "s_lim_reid_evidence_unavailable")


def test_a_step_without_a_sentence_of_the_system_is_a_failure() -> None:
    steps = {step: text for step, text in SENTENCES.steps.items() if step != "s_prov_sampling"}

    with pytest.raises(ReportFailure) as caught:
        system_sections(REPORT1, input_of(HANDOFF), replace(SENTENCES, steps=steps))

    assert caught.value.code == "UNSUPPORTED_REF" and "s_prov_sampling" in caught.value.message


def test_a_sentence_citing_a_value_the_table_has_not_is_a_failure() -> None:
    steps = {**SENTENCES.steps, "s_prov_sampling": "Sampled at {pipeline_config.sampling.rate}."}

    with pytest.raises(ReportFailure) as caught:
        system_sections(REPORT1, input_of(HANDOFF), replace(SENTENCES, steps=steps))

    assert caught.value.code == "UNSUPPORTED_REF" and "pipeline_config.sampling.rate" in caught.value.message


def test_the_report_marks_the_sections_of_the_system_and_keeps_the_order_of_the_profile() -> None:
    report = writer(ScriptedModel([hand_text(HANDOFF)])).write(*pair_of(HANDOFF)).report

    assert [(s.title, s.written_by) for s in report.sections] == [
        ("Event and rule", "llm"),
        ("What was observed", "llm"),
        ("Why it was flagged", "llm"),
        ("Method and provenance", "system"),
        ("Limits", "system"),
    ]
    assert report.report_meta.sentences_version == SENTENCES.version
