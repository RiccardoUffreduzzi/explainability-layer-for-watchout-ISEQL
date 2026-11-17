"""The renderer: values in place of names, no markers nor IDs, Markdown made from the report alone."""

from dataclasses import dataclass

from xai.contract.report import Report, dump_report, load_report
from xai.k5_report1.profile import REPORT1
from xai.reporting.reading import read_text, text_rules
from xai.reporting.renderer import BLOCK_INDENT, Header, markdown, render
from xai.tests.k5_support import NAMES, TEST_SETTINGS, ScriptedModel, hand_text, input_of, pair_of, writer

HANDOFF = "handoff_s21_A"


@dataclass(frozen=True)
class Rendered:
    report: Report
    markdown: str


def report_of(text: str, name: str = HANDOFF) -> Rendered:
    """The report of a text, which may render only some steps: the writer would want them all."""
    report_input = input_of(name)
    parsed = read_text(text, text_rules(REPORT1, report_input))
    report = render(parsed, report_input, 1, Header("report1@test", "report1@test", TEST_SETTINGS, 1))
    return Rendered(report, markdown(report))


def whole_report(name: str) -> Rendered:
    """The whole report of the hand-written text of ``name``: its sections and those of the system."""
    report = writer(ScriptedModel([hand_text(name)])).write(*pair_of(name)).report
    return Rendered(report, markdown(report))


def test_names_become_values_and_markers_and_ids_disappear() -> None:
    written = report_of(
        "## What was observed\n\n"
        "From {iv_v59.start} to {iv_v59.end}, a [man in a hoodie](ent_3) carried it. [s_s1_sel1]"
    )

    sentence = written.report.sections[0].sentences[0]
    assert sentence.text == "From 0:01 to 0:04, a man in a hoodie carried it."
    assert [(v.name, v.ref, v.text) for v in sentence.values] == [
        ("iv_v59.start", "#/intervals/0/anchor/start_s", "0:01"),
        ("iv_v59.end", "#/intervals/0/anchor/end_s", "0:04"),
    ]
    assert [(e.entity_id, e.text) for e in sentence.entities] == [("ent_3", "man in a hoodie")]
    assert (
        "[s_" not in written.markdown and "ent_3" not in written.markdown and "iv_v59" not in written.markdown
    )


def test_formal_terms_are_code_definitions_are_quoted_and_the_rule_is_a_block() -> None:
    written = report_of(
        "## Event and rule\n\n"
        "Selected by {c_s1_sel1.text}; carrying means {g_predicate_carrying.definition} [s_s1_sel1]\n"
        "The rule: {g_event_model_handoff.definition} [s_s1_proj]\n"
        "After the rule. [s_s1_proj]"
    )

    lines = written.markdown.split("\n")
    assert any('`σ_{pred="carrying" ∧ arg1="person" ∧ arg2="object"}(M1)`' in line for line in lines)
    assert any('means "The person is holding' in line for line in lines)
    rule = next(i for i, line in enumerate(lines) if line.endswith("The rule:"))
    assert lines[rule].startswith("Selected by ")
    assert (lines[rule + 1], lines[rule + 2][: len(BLOCK_INDENT) + 2]) == ("", BLOCK_INDENT + "π_")
    assert "After the rule." in lines


def test_a_value_that_is_not_available_says_so() -> None:
    written = report_of("## What was observed\n\nConfidence: {iv_v59.confidence}. [s_s1_sel1]")

    assert written.report.sections[0].sentences[0].text == "Confidence: not available."


def test_a_fixed_text_keeps_its_own_period() -> None:
    written = report_of(
        "## Confidences and reinforcement\n\n{s_reinforcement.fixed_text}. [s_reinforcement]",
        "vehicle_collision_s15_C_audio",
    )

    text = written.report.sections[0].sentences[0].text
    assert text.endswith(".") and not text.endswith("..") and written.markdown.endswith(f"\n{text}\n")


def test_a_sentence_left_without_a_period_gets_one() -> None:
    """gemini-3.5-flash-lite ended its sentences with the value, and they ran into each other."""
    written = report_of(
        "## What was observed\n\n"
        "It was seen from {iv_v59.start} to {iv_v59.end} [s_s1_sel1]\n"
        "Then from {iv_v60.start} to {iv_v60.end} [s_s1_sel2]"
    )

    assert [s.text for s in written.report.sections[0].sentences] == [
        "It was seen from 0:01 to 0:04.",
        "Then from 0:05 to 0:08.",
    ]
    assert "0:01 to 0:04. Then from 0:05 to 0:08." in written.markdown


def test_a_sentence_that_ends_with_the_rule_gets_no_period() -> None:
    written = report_of("## Event and rule\n\nThe rule: {g_event_model_handoff.definition} [s_s1_proj]")

    assert written.report.sections[0].sentences[0].text.endswith("))")
    assert not written.markdown.rstrip().endswith(".")


def test_the_report_declares_what_it_was_written_from() -> None:
    meta = writer(ScriptedModel([hand_text(HANDOFF)])).write(*pair_of(HANDOFF)).report.report_meta

    plan, _ = pair_of(HANDOFF)
    assert (meta.plan_hash, meta.contract_hash) == (plan.plan_meta.plan_hash, plan.plan_meta.contract_hash)
    assert meta.prompt_version.startswith("report1@") and len(meta.prompt_version) == len("report1@") + 12
    assert (
        meta.sentences_version.startswith("report1@") and len(meta.sentences_version) == len("report1@") + 12
    )
    assert (meta.report, meta.attempts, meta.verification) == (1, 1, "not_run")


def test_the_markdown_is_made_again_from_the_json_file() -> None:
    for name in NAMES:
        whole = whole_report(name)

        again = load_report(dump_report(whole.report))

        assert markdown(again) == whole.markdown


def test_every_value_of_the_final_text_comes_from_the_table() -> None:
    for name in NAMES:
        for section in whole_report(name).report.sections:
            for sentence in section.sentences:
                for value in sentence.values:
                    assert value.text in sentence.text
