"""``ReportWriter``: the attempts, the trace and no report when the LLM gives no usable text (S9)."""

import pytest

from xai.adapters.llm_replay import ReplayLanguageModel
from xai.contract.report import dump_report
from xai.reporting.failure import ReportFailure
from xai.reporting.ports import LlmUnavailable
from xai.tests.k5_support import ScriptedModel, hand_text, pair_of, writer

HANDOFF = "handoff_s21_A"
BAD = "## Limits\n\nNo marker here."


def test_a_good_answer_is_rendered_at_the_first_attempt() -> None:
    llm = ScriptedModel([hand_text(HANDOFF)])

    written = writer(llm).write(*pair_of(HANDOFF))

    assert written.report.report_meta.attempts == 1
    assert [c.problems for c in written.trace.calls] == [[]]
    assert written.trace.calls[0].prompt == llm.prompts[0]
    assert written.trace.calls[0].answer == hand_text(HANDOFF)


def test_a_text_that_cannot_be_rendered_goes_back_with_its_problems() -> None:
    llm = ScriptedModel([BAD, hand_text(HANDOFF)])

    written = writer(llm).write(*pair_of(HANDOFF))

    assert written.report.report_meta.attempts == 2
    retry = llm.prompts[1]
    assert retry.startswith(llm.prompts[0])
    assert BAD in retry and "a sentence without a step marker after it: 'No marker here.'" in retry
    assert [bool(c.problems) for c in written.trace.calls] == [True, False]


def test_no_report_after_the_last_attempt() -> None:
    llm = ScriptedModel([BAD, BAD, BAD, hand_text(HANDOFF)])

    with pytest.raises(ReportFailure) as caught:
        writer(llm, max_attempts=3).write(*pair_of(HANDOFF))

    assert caught.value.code == "TEXT_NOT_RENDERABLE"
    assert len(llm.prompts) == 3
    assert caught.value.trace is not None and len(caught.value.trace.calls) == 3


def test_no_report_when_the_llm_cannot_be_reached() -> None:
    llm = ScriptedModel([LlmUnavailable("connection refused")])

    with pytest.raises(ReportFailure) as caught:
        writer(llm).write(*pair_of(HANDOFF))

    assert (caught.value.code, caught.value.message) == ("LLM_UNAVAILABLE", "connection refused")
    assert caught.value.trace is not None and caught.value.trace.calls[0].error == "connection refused"


def test_the_trace_makes_the_same_report_again_without_the_llm() -> None:
    first = writer(ScriptedModel([BAD, hand_text(HANDOFF)])).write(*pair_of(HANDOFF))
    replay = ReplayLanguageModel(
        {c.prompt: c.answer for c in first.trace.calls if c.answer is not None}, settings=first.trace.llm
    )

    again = writer(replay).write(*pair_of(HANDOFF))

    assert dump_report(again.report) == dump_report(first.report)
    assert again.markdown == first.markdown


def test_a_prompt_without_recorded_answer_is_an_unavailable_llm() -> None:
    with pytest.raises(ReportFailure) as caught:
        writer(ReplayLanguageModel({})).write(*pair_of(HANDOFF))

    assert caught.value.code == "LLM_UNAVAILABLE"


def test_at_least_one_attempt() -> None:
    with pytest.raises(ValueError):
        writer(ScriptedModel([]), max_attempts=0)
