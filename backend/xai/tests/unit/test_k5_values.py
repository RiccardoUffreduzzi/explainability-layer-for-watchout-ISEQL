"""The table of the values (K56-A2): every fact the plan cites, with its text and its pointer."""

from typing import Any

import pytest

from xai.contract.plan import PlanStep, StepType, TOrderBasis
from xai.contract.reasons import Reason
from xai.contract.source_of_truth import ReinforcementStatus
from xai.reporting.failure import ReportFailure
from xai.reporting.values import (
    NOT_AVAILABLE,
    ValueReader,
    ValueTable,
    cited_refs,
    clock,
    number,
    seconds,
    threshold,
)
from xai.tests.k4_plan_support import resolve_pointer, step
from xai.tests.k5_support import LABELS, NAMES, input_of, pair_of


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (0.0, "0:00"),
        (1.0, "0:01"),
        (2.5, "0:02.5"),
        (61.25, "1:01.25"),
        (600.0, "10:00"),
        (3725.0, "1:02:05"),
    ],
)
def test_times_are_written_as_minutes_and_seconds(value: float, text: str) -> None:
    assert clock(value) == text


def test_numbers_keep_their_type_and_durations_their_unit() -> None:
    assert (number(24), number(1.0), number(0.87)) == ("24", "1.0", "0.87")
    assert (seconds(2.0), seconds(2.5)) == ("2 s", "2.5 s")


def test_a_threshold_is_infinite_or_a_number_with_the_unit_of_the_engine() -> None:
    assert threshold("inf", "seconds") == "∞"
    assert threshold(2, "seconds") == "2 seconds"
    assert threshold(1, "frames") == "1 frame"


def covers(table: ValueTable, ref: str) -> bool:
    """Whether a reference of the plan has its values (or its entity) in the table."""
    return any(ref in (v.step_ref, v.pointer) for v in table.values) or table.entity(ref) is not None


@pytest.mark.parametrize("name", NAMES)
def test_every_ref_of_the_steps_has_its_values(name: str) -> None:
    report_input = input_of(name)

    missing = [ref for ref in cited_refs(report_input.steps) if not covers(report_input.table, ref)]

    assert missing == []


@pytest.mark.parametrize("name", NAMES)
def test_every_value_points_at_its_place_in_the_source_of_truth(name: str) -> None:
    report_input = input_of(name)
    data = report_input.document.model_dump(mode="json")

    for value in report_input.table.values:
        resolve_pointer(data, value.pointer)  # raises when the pointer leads nowhere


@pytest.mark.parametrize("name", NAMES)
def test_every_provenance_value_has_a_label(name: str) -> None:
    report_input = input_of(name)
    provenance = {
        r for s in report_input.steps if s.type == StepType.PROVENANCE for r in s.refs if r.startswith("#/")
    }

    unlabelled = [v.name for v in report_input.table.values if v.step_ref in provenance and v.label is None]

    assert unlabelled == []


def test_every_reason_and_every_coded_value_has_words() -> None:
    assert set(LABELS.reasons) == {reason.value for reason in Reason}
    assert set(LABELS.values["reinforcement.status"]) == {status.value for status in ReinforcementStatus}
    assert set(LABELS.values["params_origin"]) == {"rule_defaults", "saved_by_gui"}
    assert {"engine_lineage", "attributed", "ambiguous", "not_found"} <= set(LABELS.codes)


@pytest.mark.parametrize("name", NAMES)
def test_every_missing_field_of_the_golden_drafts_has_a_label(name: str) -> None:
    _, document = pair_of(name)

    assert [
        m.path for m in document.harvest_report.missing_fields if m.path not in LABELS.missing_fields
    ] == []


def test_the_values_of_the_handoff_plan() -> None:
    table = input_of("handoff_s21_A").table

    texts = {v.name: v.written for v in table.values}
    assert texts["iv_v59.start"] == "0:01"
    assert texts["iv_v60.end_frame"] == "192"
    assert texts["c_s1_op1.δ"] == "∞"
    assert texts["ev_beffcb6f2a6e.model_id"] == "handoff/A"
    assert texts["pipeline_config.merge_tolerance_s"] == "2 s"
    assert texts["params_origin"] == "rule defaults"
    assert texts["ent_5"] == "person 2"
    assert texts["missing_fields"].startswith("audio rule (EventSpec has no handoff/B); Re-ID similarity (")
    assert (
        texts["s_lim_reid_dependence.fixed_text"]
        == step(input_of("handoff_s21_A").plan, "s_lim_reid_dependence").fixed_text
    )


def test_the_event_is_cited_by_its_rule_and_its_times_not_by_its_label() -> None:
    model_id = input_of("handoff_s21_A").table.value("ev_beffcb6f2a6e.model_id")

    assert input_of("handoff_s21_A").table.value("ev_beffcb6f2a6e.label") is None
    assert model_id is not None and model_id.form == "code"
    assert model_id.for_llm() == {"value": "handoff/A", "label": LABELS.fields["event.model_id"]}


def test_an_interval_of_a_single_analysed_frame_has_one_time() -> None:
    table = input_of("vehicle_collision_s15_C_audio").table

    names = {v.name for v in table.values if v.name.startswith("modality_detections.0.")}
    assert names == {
        "modality_detections.0.modality",
        "modality_detections.0.at",
        "modality_detections.0.frame",
    }
    assert table.value("modality_detections.0.at").written == "0:05"  # type: ignore[union-attr]
    assert table.value("iv_a22.end").written == "0:07.5"  # type: ignore[union-attr]


def test_a_value_without_data_says_why() -> None:
    confidence = input_of("handoff_s21_A").table.value("iv_v59.confidence")

    assert confidence is not None
    assert confidence.text is None and confidence.written == NOT_AVAILABLE
    assert confidence.for_llm() == {"value": None, "reason": LABELS.reasons["visual_confidence_not_recorded"]}


def test_forms_tell_how_the_reader_sees_a_value() -> None:
    table = input_of("handoff_s21_A").table

    forms = {name: table.value(name).form for name in table.names()}  # type: ignore[union-attr]
    assert forms["c_s1_op1.text"] == "code"
    assert forms["g_predicate_carrying.definition"] == "quote"
    assert forms["g_operator_Bef.definition"] == "code"
    assert forms["g_event_model_handoff.definition"] == "block"
    assert forms["iv_v59.start"] == "plain"


def test_entities_have_the_vlm_description_their_roles_and_a_label() -> None:
    rows = {row.entity_id: row for row in input_of("handoff_s21_A").table.entities}

    assert rows["ent_3"].description == "man in dark blue hoodie carrying a box"
    assert rows["ent_3"].roles == ("M1.arg1",)
    assert (rows["ent_3"].label, rows["ent_5"].label, rows["ent_4"].label) == (
        "person 1",
        "person 2",
        "object 1",
    )


def test_an_entity_without_description_keeps_its_label() -> None:
    def undescribed(data: dict[str, Any]) -> None:
        entity = data["entities"][0]
        entity["vlm_description"] = None
        entity["unavailable"]["vlm_description"] = {"reason": "entity_not_described", "detail": "x"}

    rows = input_of("handoff_s21_A", undescribed).table.entities

    assert next(r for r in rows if r.entity_id == "ent_3").for_llm()["description"] is None


def test_a_slot_that_points_into_a_rule_node_is_a_value_of_the_node() -> None:
    table = input_of("suspicious_near_vehicle_s18_A").table

    value = table.value("c_s1_cc1.value")
    assert value is not None and value.written == "3"
    assert covers(table, "#/rule/constraints/1/payload/value")
    assert covers(table, "#/rule/constraints/1/payload/unit")


def test_the_reinforcement_and_the_detections_of_each_modality() -> None:
    table = input_of("vehicle_collision_s15_C_audio").table

    status = table.value("reinforcement.status")
    assert status is not None and status.written == LABELS.values["reinforcement.status"]["both_overlapping"]
    assert table.value("modality_detections.3.modality").written == "audio"  # type: ignore[union-attr]
    assert table.value("iv_a22.start").written == "0:02.5"  # type: ignore[union-attr]
    assert table.value("iv_a21.confidence").written == "1.0"  # type: ignore[union-attr]


def test_missing_details_that_differ_fall_back_to_the_words_of_the_reason() -> None:
    def two_details(data: dict[str, Any]) -> None:
        data["entities"][1]["unavailable"]["reid_evidence"]["detail"] = "another detail"

    text = input_of("handoff_s21_A", two_details).table.value("missing_fields").written  # type: ignore[union-attr]

    assert f"Re-ID similarity ({LABELS.reasons['reid_similarity_not_persisted']})" in text


def test_a_ref_no_report_reads_yet_is_refused() -> None:
    _, document = pair_of("handoff_s21_A")
    keyframe = PlanStep(
        step_id="s_kf",
        type=StepType.CONTEXT,
        refs=["kf_1"],
        depends_on=[],
        t_order=None,
        t_order_basis=TOrderBasis.NONE,
        in_report2=True,
    )

    with pytest.raises(ReportFailure) as caught:
        ValueReader(document, LABELS).table([keyframe])

    assert caught.value.code == "UNSUPPORTED_REF"
