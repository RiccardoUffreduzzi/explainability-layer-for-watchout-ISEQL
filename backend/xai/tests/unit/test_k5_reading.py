"""Reading the text of the LLM: what can be rendered, and the problems that send it back."""

from dataclasses import replace

import pytest

from xai.k5_report1.profile import REPORT1
from xai.reporting.llm_input import build_input
from xai.reporting.reading import ParsedText, TextProblems, TextRules, read_answer, read_text, text_rules
from xai.tests.k5_support import K5_DATA_DIR, LABELS, NAMES, hand_text, input_of, pair_of

LLM_WRITES_ALL = replace(REPORT1, sections=tuple(replace(s, by_system=False) for s in REPORT1.sections))
"""Report 1 as if the LLM wrote the limits too: lists, lead-ins and sentences of the system."""


@pytest.fixture(scope="module")
def rules() -> TextRules:
    return text_rules(REPORT1, input_of("handoff_s21_A"))


@pytest.fixture(scope="module")
def all_rules() -> TextRules:
    return text_rules(LLM_WRITES_ALL, build_input(*pair_of("handoff_s21_A"), LLM_WRITES_ALL, LABELS))


def problems(text: str, rules: TextRules) -> list[str]:
    with pytest.raises(TextProblems) as caught:
        read_text(text, rules)
    return caught.value.problems


def answer_problems(text: str, rules: TextRules) -> list[str]:
    with pytest.raises(TextProblems) as caught:
        read_answer(text, rules)
    return caught.value.problems


def real_text(name: str) -> str:
    """A text of gemini-3.5-flash-lite on the prompt of handoff, trial of 14 November 2026.

    That prompt still gave the label of the event (``{ev_….label}``) and did not check the
    phrases of the terms.
    """
    return (K5_DATA_DIR / "llm" / f"handoff_s21_A.{name}.txt").read_text(encoding="utf-8")


@pytest.mark.parametrize("name", NAMES)
def test_the_hand_written_texts_can_be_rendered(name: str) -> None:
    parsed = read_answer(hand_text(name), text_rules(REPORT1, input_of(name)))

    assert all(s.step_ids for section in parsed.sections for s in section.sentences)


def test_sections_blocks_and_list_items(all_rules: TextRules) -> None:
    text = (
        "## Event and rule\n\nA handoff. [s_s1_proj]\n\n## Limits\n\n"
        "These limits concern the detection:\n"
        "- {s_lim_temporal_resolution.fixed_text} [s_lim_temporal_resolution]\n"
        "- {s_lim_data_not_available.fixed_text} [s_lim_data_not_available] "
        "Not available here: {missing_fields}. [s_lim_data_not_available]"
    )

    parsed = read_text(text, all_rules)

    limits = parsed.sections[-1]
    assert [section.title for section in parsed.sections] == ["Event and rule", "Limits"]
    assert [(s.block, s.list_item) for s in limits.sentences] == [(0, False), (1, True), (2, True), (2, True)]


def test_several_markers_close_one_sentence(rules: TextRules) -> None:
    parsed = read_text("## What was observed\n\nBoth carry it. [s_s1_sel1][s_s1_sel2]", rules)

    assert parsed.sections[0].sentences[0].step_ids == ("s_s1_sel1", "s_s1_sel2")


def test_a_sentence_without_marker_is_refused(rules: TextRules) -> None:
    found = problems("## Why it was flagged\n\nA sentence. [s_s1_cc1] And one more.", rules)

    assert found == ["a sentence without a step marker after it: 'And one more.'"]


def test_a_marker_of_a_step_not_received_is_refused(rules: TextRules) -> None:
    assert problems("## Why it was flagged\n\nA sentence. [s_reinforcement]", rules) == [
        "the marker [s_reinforcement] is not a step of the plan you received"
    ]


def test_an_unknown_name_is_refused(rules: TextRules) -> None:
    assert problems("## Why it was flagged\n\nAt {iv_v99.start}. [s_s1_cc1]", rules) == [
        "{iv_v99.start} is not a name of the values table"
    ]


def test_a_step_in_braces_is_told_to_be_a_marker(rules: TextRules) -> None:
    assert problems("## Why it was flagged\n\nIt ends before {s_s1_sel2}. [s_s1_cc1]", rules) == [
        "{s_s1_sel2} is a step, not a value: say what the step says and put [s_s1_sel2] after the sentence"
    ]


def test_an_interval_without_a_field_gets_its_start_and_end(rules: TextRules) -> None:
    assert problems("## Why it was flagged\n\nM1 was {iv_v59}. [s_s1_cc1]", rules) == [
        "{iv_v59} is not a name of the values table: "
        "cite one of its values, such as {iv_v59.start} or {iv_v59.end}"
    ]


def test_a_misspelt_name_of_a_known_fact_gets_a_hint(all_rules: TextRules) -> None:
    assert problems(
        "## Limits\n\nMissing: {missing_fields.value}. [s_lim_data_not_available]", all_rules
    ) == ["{missing_fields.value} is not a name of the values table: did you mean {missing_fields}?"]


def test_an_entity_the_plan_does_not_cite_is_refused(rules: TextRules) -> None:
    assert problems("## Why it was flagged\n\nThe [car](ent_9) left. [s_s1_cc1]", rules) == [
        "ent_9 is not an entity cited by the plan"
    ]


def test_an_entity_with_a_description_is_not_cited_by_its_label(rules: TextRules) -> None:
    text = "## Why it was flagged\n\n{ent_3} left. [s_s1_cc1]"

    assert problems(text, rules) == [
        "{ent_3} is the label of an entity that has a description: "
        "name it with words of its description, marked with its ID, as [words](ent_3)"
    ]
    without_description = replace(rules, entities={**rules.entities, "ent_3": None})
    assert read_text(text, without_description).sections[0].sentences[0].names == ("ent_3",)


def test_a_number_written_by_the_llm_is_refused(rules: TextRules) -> None:
    found = problems("## Why it was flagged\n\nIt lasted 3 seconds, at 0:04. [s_s1_cc1]", rules)

    assert found == [
        f"the number {n!r} is written in the text: cite every number by its {{name}}"
        for n in ("3", "0", "04")
    ]


def test_digits_in_the_names_of_the_rule_are_not_numbers(rules: TextRules) -> None:
    parsed = read_text(
        "## Why it was flagged\n\nM1.arg1 differs from M2.arg1 in M1 and M2. [s_s1_cc1]", rules
    )

    assert parsed.sections[0].sentences[0].names == ()


def test_digits_of_a_description_may_be_copied_only_from_it(rules: TextRules) -> None:
    assert problems("## Why it was flagged\n\nThe [man aged 30](ent_3) left. [s_s1_cc1]", rules) == [
        "the number '30' is written in the text: cite every number by its {name}"
    ]


def test_an_id_left_in_the_words_is_refused(rules: TextRules) -> None:
    assert problems("## Why it was flagged\n\nThe man ent_3 left. [s_s1_cc1]", rules) == [
        "the ID 'ent_3' is written in the words: cite a value as {name}, an entity as [words](ID)"
    ]


def test_the_detection_is_timed_by_the_event_not_by_an_interval(rules: TextRules) -> None:
    text = "## Event and rule\n\nA handoff from {iv_v59.start} to {iv_v60.end}. [s_s1_proj]"

    assert problems(text, rules) == [
        f"{{{name}}} is a time of an interval: the detection has its own, "
        "cite {ev_beffcb6f2a6e.start} and {ev_beffcb6f2a6e.end}"
        for name in ("iv_v59.start", "iv_v60.end")
    ]


def test_an_interval_is_timed_in_a_sentence_that_also_renders_its_observation(rules: TextRules) -> None:
    text = "## Event and rule\n\nIt starts with M1, from {iv_v59.start}. [s_s1_proj][s_s1_sel1]"

    assert read_text(text, rules).sections[0].sentences[0].names == ("iv_v59.start",)


def test_braces_that_cite_no_name_are_refused(rules: TextRules) -> None:
    text = "## Event and rule\n\nThe arguments {[man](ent_3), [box](ent_4)}. [s_s1_proj]"

    assert problems(text, rules) == [
        "braces that cite no name: '{[man](ent_3), [box](ent_4)}'; "
        "write braces only around the name of a value, as {name}"
    ]


def test_titles_must_be_those_of_the_profile(rules: TextRules) -> None:
    found = problems("Hello.\n## Summary\n\nText. [s_lim_temporal_resolution]", rules)

    assert found[0] == "text before the first section title: 'Hello.'"
    assert found[1].startswith("unknown section title 'Summary'")


def test_an_empty_text_is_refused(rules: TextRules) -> None:
    assert problems("   ", rules) == ["the text has no section"]


def test_a_code_fence_around_the_text_and_a_period_after_the_marker_are_tolerated(
    all_rules: TextRules,
) -> None:
    item = "- {s_lim_temporal_resolution.fixed_text} [s_lim_temporal_resolution]."
    text = f"```markdown\n## limits:\n\n{item}\n```"

    parsed = read_text(text, all_rules)

    assert isinstance(parsed, ParsedText)
    sentence = parsed.sections[0].sentences[0]
    assert (parsed.sections[0].title, sentence.body) == ("Limits", "{s_lim_temporal_resolution.fixed_text}.")


@pytest.mark.parametrize(
    "heading",
    ["## Limits: s_lim_temporal_resolution", "## Limits (s_lim_temporal_resolution, s_lim_reid_dependence)"],
)
def test_the_steps_copied_after_a_title_are_tolerated(all_rules: TextRules, heading: str) -> None:
    parsed = read_text(f"{heading}\n\nA limit. [s_lim_temporal_resolution]", all_rules)

    assert parsed.sections[0].title == "Limits"


def test_a_title_with_a_word_changed_is_that_title(rules: TextRules) -> None:
    """gemini-3.5-flash-lite wrote "Why it is flagged" on scene 15."""
    parsed = read_text("## Why it is flagged\n\nIt ends before. [s_s1_op1]", rules)

    assert parsed.sections[0].title == "Why it was flagged"


def test_another_title_is_still_refused(rules: TextRules) -> None:
    assert problems("## Event\n\nA limit. [s_lim_temporal_resolution]", rules)[0].startswith(
        "unknown section title 'Event'"
    )


def test_a_line_break_inside_a_name_is_joined(rules: TextRules) -> None:
    """gemini-3.5-flash-lite broke {ev_8709b27746f6.end} and {iv_a22.confidence} on two lines."""
    text = (
        "## Event and rule\n\n"
        "From {ev_beffcb6f2a6e.start} to {ev_beffcb6\nf2a6e.end}, at {iv\n_v59.start}. [s_s1_proj][s_s1_sel1]"
    )

    sentence = read_text(text, rules).sections[0].sentences[0]

    assert sentence.names == ("ev_beffcb6f2a6e.start", "ev_beffcb6f2a6e.end", "iv_v59.start")


@pytest.mark.parametrize("target", ["g_event_model_handoff", "g_event_model_handoff.term"])
def test_a_term_marked_as_an_entity_is_told_its_name(rules: TextRules, target: str) -> None:
    """gemini-3.5-flash-lite wrote [fight](g_event_model_fight) and [fight](g_event_model_fight.term)."""
    assert problems(f"## Event and rule\n\nIt is a [handoff]({target}). [s_s1_proj]", rules) == [
        f"[handoff]({target}) is not an entity: only an entity is marked as [words](ent_…); "
        "write {g_event_model_handoff.term} instead"
    ]


def test_a_title_followed_by_other_words_is_still_refused(rules: TextRules) -> None:
    found = problems("## Limits: of the video\n\nA limit. [s_lim_temporal_resolution]", rules)

    assert found[0].startswith("unknown section title 'Limits: of the video'")


def test_the_first_text_of_a_real_llm_has_only_the_problems_a_new_attempt_fixes(all_rules: TextRules) -> None:
    assert answer_problems(real_text("flash_lite"), all_rules) == [
        "{ev_beffcb6f2a6e.label} is not a name of the values table",
        *(
            f"{{{name}}} is a time of an interval: the detection has its own, "
            "cite {ev_beffcb6f2a6e.start} and {ev_beffcb6f2a6e.end}"
            for name in ("iv_v59.start", "iv_v59.end")
        ),
        "{missing_fields.value} is not a name of the values table: did you mean {missing_fields}?",
        "the step [s_s1_proj] has a term, and its sentence does not say what it means: write its phrase "
        "'an object passing from one person to another', each placeholder replaced by the words for its slot",
    ]


def test_a_sentence_that_introduces_a_list_takes_the_markers_of_the_list(all_rules: TextRules) -> None:
    text = (
        "## Limits\n\n"
        "These limits concern the detection:\n"
        "- {s_lim_temporal_resolution.fixed_text} [s_lim_temporal_resolution]\n"
        "- {s_lim_reid_dependence.fixed_text} [s_lim_reid_dependence]\n"
        "Not available here: {missing_fields}. [s_lim_data_not_available]"
    )

    sentences = read_text(text, all_rules).sections[0].sentences

    assert [(s.body, s.step_ids, s.list_item) for s in sentences[:2]] == [
        (
            "These limits concern the detection:",
            ("s_lim_temporal_resolution", "s_lim_reid_dependence"),
            False,
        ),
        ("{s_lim_temporal_resolution.fixed_text}", ("s_lim_temporal_resolution",), True),
    ]
    assert sentences[-1].step_ids == ("s_lim_data_not_available",)


def test_the_second_real_text_is_accepted_with_its_lead_in(all_rules: TextRules) -> None:
    text = real_text("flash_lite.lead_in").replace("{ev_beffcb6f2a6e.label}", "handoff")
    parsed = read_text(text, all_rules)

    limits = parsed.sections[-1].sentences
    assert limits[0].body == "These limits concern the conditions and the detection:"
    assert len(limits[0].step_ids) == len(all_rules.sections["Limits"])


@pytest.mark.parametrize(
    "text",
    [
        "## Limits\n\nThese limits concern the detection:\n\nA sentence. [s_lim_temporal_resolution]",
        "## Limits\n\nThese limits concern the detection:",
        "## Limits\n\n- A limit [s_lim_temporal_resolution] and these:\n- Another. [s_lim_reid_dependence]",
    ],
)
def test_a_colon_without_a_list_after_it_is_still_a_sentence_without_marker(
    rules: TextRules, text: str
) -> None:
    assert [p for p in problems(text, rules) if "without a step marker" in p] != []


def test_every_step_of_the_sections_must_be_rendered(rules: TextRules) -> None:
    text = hand_text("handoff_s21_A").replace("[s_s1_sel2]", "[s_s1_sel1]")

    assert answer_problems(text, rules) == [
        "the step [s_s1_sel2] is not rendered: write a sentence about it "
        "in the section 'What was observed', with [s_s1_sel2] after it"
    ]


def test_a_sentence_of_the_system_rewritten_by_the_llm_is_refused(all_rules: TextRules) -> None:
    found = answer_problems(real_text("flash_lite.rewritten_limits"), all_rules)

    rewritten = [p for p in found if "sentence of the system" in p]
    assert len(rewritten) == len(all_rules.fixed_texts) == len(all_rules.sections["Limits"])
    assert rewritten[0] == (
        "the step [s_lim_reid_dependence] has a sentence of the system: cite it as "
        "{s_lim_reid_dependence.fixed_text}, followed by [s_lim_reid_dependence], and do not rewrite it"
    )
    assert not any("without a step marker" in p for p in found)


def test_a_term_must_be_said_with_the_words_of_its_phrase(rules: TextRules) -> None:
    text = hand_text("handoff_s21_A").replace(" carrying ", " {g_predicate_carrying.term} ")

    assert answer_problems(text, rules) == [
        f"the step [{step}] has a term, and its sentence does not say what it means: write its phrase "
        "'{arg1} carries {arg2}', each placeholder replaced by the words for its slot"
        for step in ("s_s1_sel1", "s_s1_sel2")
    ]


def test_a_code_written_in_the_words_is_refused_with_what_it_means(rules: TextRules) -> None:
    text = hand_text("handoff_s21_A").replace(
        "The first carrying ends before", "The engine_lineage of vehicle_collision ends before"
    )

    assert problems(text, rules) == [
        "the code 'engine_lineage' is written in the words: say what it means, "
        f"{rules.codes['engine_lineage']!r}",
        "the code 'vehicle_collision' is written in the words: say what it means",
    ]


def test_a_term_of_the_glossary_written_as_a_code_is_refused_with_its_phrase() -> None:
    name = "suspicious_near_vehicle_s18_A"
    text = (
        hand_text(name)
        .replace("detected an event with", "detected a suspicious_near_vehicle with")
        .replace("The observation lasts at least", "The observation is duration_ge")
    )

    assert problems(text, text_rules(REPORT1, input_of(name))) == [
        "the code 'suspicious_near_vehicle' is written in the words: say what it means, "
        "'a person lingering suspiciously near a vehicle'",
        "the code 'duration_ge' is written in the words: say what it means, "
        "'{x} lasts at least {value} {unit}', each placeholder replaced by the words for its slot",
    ]


def test_report_1_must_cite_the_definition_of_the_rule(rules: TextRules) -> None:
    text = hand_text("handoff_s21_A").replace(
        "The rule that was executed: {g_event_model_handoff.definition} [s_s1_proj]\n", ""
    )

    assert answer_problems(text, rules) == [
        "the definition of the rule is not cited: write {g_event_model_handoff.definition} "
        "at the end of a sentence of its own, after a colon"
    ]
    without = text_rules(replace(REPORT1, cites_rule_definition=False), input_of("handoff_s21_A"))
    assert read_answer(text, without).sections


def test_the_start_of_a_single_analysed_frame_is_its_time() -> None:
    rules = text_rules(REPORT1, input_of("vehicle_collision_s15_C_audio"))
    text = (
        "## Confidences and reinforcement\n\n"
        "The video detection starts at {modality_detections.0.start}. [s_prov_modality_association]"
    )

    assert problems(text, rules) == [
        "{modality_detections.0.start} is not a name of the values table: "
        "it is a single analysed frame, cite it as at {modality_detections.0.at}"
    ]


def test_report_1_leaves_the_method_and_the_limits_to_the_system(rules: TextRules) -> None:
    assert rules.titles == (
        "Event and rule",
        "What was observed",
        "Why it was flagged",
        "Confidences and reinforcement",
    )
    assert problems("## Why it was flagged\n\nContract {contract_hash}. [s_s1_cc1]", rules) == [
        "{contract_hash} is not a name of the values table"
    ]
