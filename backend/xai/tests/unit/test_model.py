import copy
import json
from typing import Any

import pytest
from pydantic import ValidationError

from xai.contract import CONTRACT_VERSION, ContractDraft, draft_to_data, dump_draft, load_draft
from xai.contract.canonical import canonical_json
from xai.contract.model import (
    CheckResult,
    OperatorParam,
    RowMatch,
    TemporalOperatorNode,
)
from xai.contract.reasons import CheckName
from xai.tests.support import EXAMPLE_PATHS, from_json_data


def test_every_example_is_found() -> None:
    assert [p.name for p in EXAMPLE_PATHS] == [
        "fight_s5_A.bozza.json",
        "gunshot_or_explosion_s7_A.bozza.json",
        "handoff_s21_A.bozza.json",
        "suspicious_near_vehicle_s18_A.bozza.json",
        "vehicle_collision_s15_C_F3_visual.bozza.json",
        "vehicle_collision_s15_C_audio.bozza.json",
        "vehicle_collision_s15_C_visual.bozza.json",
    ]


def test_example_round_trips_unchanged(example: dict[str, Any]) -> None:
    draft = from_json_data(ContractDraft, example)

    # Canonical text also tells 24 from 24.0 and a missing key from a null one.
    assert canonical_json(draft_to_data(draft)) == canonical_json(example)


def test_canonical_text_reads_back_to_the_same_draft(example: dict[str, Any]) -> None:
    draft = from_json_data(ContractDraft, example)
    text = dump_draft(draft)

    assert load_draft(text) == draft
    assert dump_draft(load_draft(text)) == text


def test_canonical_text_is_sorted_and_compact(operator_example: dict[str, Any]) -> None:
    text = dump_draft(from_json_data(ContractDraft, operator_example))
    parsed = json.loads(text)

    assert list(parsed) == sorted(parsed)
    assert list(parsed["contract_meta"]) == sorted(parsed["contract_meta"])
    assert "\n" not in text
    assert "δ" in text  # non-ASCII is kept, not escaped


def test_draft_is_immutable(example: dict[str, Any]) -> None:
    draft = from_json_data(ContractDraft, example)

    with pytest.raises(ValidationError):
        draft.event.label = "something_else"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("knowledge_limits",), []),  # K2 field: absent in K1, not null
        (("contract_meta", "contract_hash"), "abc"),  # K2 field
        (("event", "reinforcement"), {"status": "not_multimodal"}),  # K2 field
        (("contract_meta", "event_model_version"), "x"),  # no longer in the contract
        (("rule", "unknown"), 1),
    ],
)
def test_unknown_keys_are_rejected(example: dict[str, Any], path: tuple[str, ...], value: object) -> None:
    data = copy.deepcopy(example)
    _set(data, path, value)

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        from_json_data(ContractDraft, data)


def test_required_nullable_field_cannot_be_left_out(example: dict[str, Any]) -> None:
    data = copy.deepcopy(example)
    del data["intervals"][0]["confidence"]

    with pytest.raises(ValidationError, match="confidence"):
        from_json_data(ContractDraft, data)


def test_reason_outside_the_catalog_is_rejected(example: dict[str, Any]) -> None:
    data = copy.deepcopy(example)
    data["unavailable"]["actions"]["reason"] = "not_implemented_yet"

    with pytest.raises(ValidationError, match="reason"):
        from_json_data(ContractDraft, data)


def test_actions_must_stay_null_until_key_frames(example: dict[str, Any]) -> None:
    data = copy.deepcopy(example)
    data["actions"] = []

    with pytest.raises(ValidationError, match="actions"):
        from_json_data(ContractDraft, data)


def test_payload_must_match_the_node_kind(operator_example: dict[str, Any]) -> None:
    data = copy.deepcopy(operator_example)
    operator = next(c for c in data["rule"]["constraints"] if c["kind"] == "temporal_operator")
    operator["kind"] = "projection"

    with pytest.raises(ValidationError, match=r"projection\.payload"):
        from_json_data(ContractDraft, data)


def test_nodes_are_typed_by_kind(operator_example: dict[str, Any]) -> None:
    draft = from_json_data(ContractDraft, operator_example)

    operators = [c for c in draft.rule.constraints if c.kind == "temporal_operator"]
    assert operators
    assert all(isinstance(c, TemporalOperatorNode) for c in operators)


def test_anchor_needs_the_pair_it_was_read_as(example: dict[str, Any]) -> None:
    data = copy.deepcopy(example)
    data["event"]["interval"]["start_s"] = None  # read_as = seconds

    with pytest.raises(ValidationError, match="read_as='seconds'"):
        from_json_data(ContractDraft, data)


def test_anchor_converted_pair_may_be_null(example: dict[str, Any]) -> None:
    data = copy.deepcopy(example)
    data["event"]["interval"].update(start_frame=None, end_frame=None)

    draft = from_json_data(ContractDraft, data)

    assert draft.event.interval.start_frame is None


def test_alias_class_is_written_back_as_class(example: dict[str, Any]) -> None:
    data = draft_to_data(from_json_data(ContractDraft, example))

    for argument in data["event"]["arguments"]:
        assert "class" in argument
        assert "class_" not in argument


def _param(**changes: object) -> dict[str, object]:
    base: dict[str, object] = {
        "name": "δ",
        "raw": None,
        "value": 2,
        "unit": "seconds",
        "engine_value": 48,
        "compare_domain": "seconds",
        "origin": "literal",
        "source_ref": {"stage": "iseql", "store": "EventSpec", "record_id": "x/A", "mode": "read"},
    }
    base.update(changes)
    return base


def test_strictness_parameter_has_no_unit() -> None:
    with pytest.raises(ValidationError, match="strictness"):
        from_json_data(OperatorParam, _param(name="ζ", value="<=", engine_value="<="))


def test_parameter_without_unit_omits_the_key() -> None:
    data = _param(name="ζ", value="<", engine_value="<")
    del data["unit"]

    param = from_json_data(OperatorParam, data)

    assert param.unit is None
    assert "unit" not in param.model_dump(mode="json")


def test_optional_field_written_as_null_is_rejected() -> None:
    with pytest.raises(ValidationError, match="leave out unit instead of writing null"):
        from_json_data(OperatorParam, _param(name="ζ", value="<", engine_value="<", unit=None))


def test_optional_field_set_to_none_in_python_is_left_out() -> None:
    param = from_json_data(OperatorParam, _param())

    assert "unit" not in param.model_copy(update={"unit": None}).model_dump(mode="json")
    assert OperatorParam(**{**dict(param), "unit": None}).unit is None


def test_numbers_are_not_read_from_text(example: dict[str, Any]) -> None:
    data = copy.deepcopy(example)
    data["contract_meta"]["pipeline_config"]["sampling"]["source_fps"] = "24"

    with pytest.raises(ValidationError, match="source_fps"):
        from_json_data(ContractDraft, data)


def test_contract_version_is_the_current_one(example: dict[str, Any]) -> None:
    data = copy.deepcopy(example)
    data["contract_meta"]["contract_version"] = "0.2.0"

    assert from_json_data(ContractDraft, example).contract_meta.contract_version == CONTRACT_VERSION
    with pytest.raises(ValidationError, match="contract_version"):
        from_json_data(ContractDraft, data)


@pytest.mark.parametrize("value", ["2026-10-06T20:00:00", "2026-10-06 20:00:00Z", 1791000000])
def test_timestamp_is_rfc3339_text_with_an_offset(example: dict[str, Any], value: object) -> None:
    data = copy.deepcopy(example)
    data["contract_meta"]["source_snapshot"]["extracted_at"] = value

    with pytest.raises(ValidationError, match="RFC 3339"):
        from_json_data(ContractDraft, data)


def test_parameter_keeps_int_and_float_apart() -> None:
    param = from_json_data(OperatorParam, _param(value=2, engine_value=2.5))

    assert param.model_dump(mode="json")["value"] == 2
    assert isinstance(param.value, int)
    assert isinstance(param.engine_value, float)


@pytest.mark.parametrize(
    ("rows_returned", "matches", "matched_index"),
    [(0, 0, 0), (2, 0, 0), (2, 3, 0), (2, 1, 2)],
)
def test_row_match_must_point_to_a_returned_row(rows_returned: int, matches: int, matched_index: int) -> None:
    with pytest.raises(ValidationError):
        RowMatch(rows_returned=rows_returned, matches=matches, matched_index=matched_index)


def test_check_result_passed_agrees_with_violations() -> None:
    violation = {
        "check": "completeness",
        "element_path": "intervals[0].confidence",
        "detail": "null without a reason",
    }

    with pytest.raises(ValidationError, match="passed"):
        from_json_data(CheckResult, {"name": "completeness", "passed": True, "violations": [violation]})
    with pytest.raises(ValidationError, match="passed"):
        from_json_data(CheckResult, {"name": "completeness", "passed": False, "violations": []})
    assert not from_json_data(
        CheckResult, {"name": "completeness", "passed": False, "violations": [violation]}
    ).passed
    assert CheckResult(name=CheckName.COMPLETENESS, passed=True, violations=[]).passed


def _set(data: dict[str, Any], path: tuple[str, ...], value: object) -> None:
    target = data
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
