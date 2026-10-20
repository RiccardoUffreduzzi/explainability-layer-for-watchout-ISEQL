"""The closing checks on the examples and on drafts broken on purpose."""

import copy
import json
from typing import Any

from xai.contract.reasons import CheckName, Reason
from xai.contract.serialization import load_draft
from xai.k1_harvester.checks.completeness import check_completeness
from xai.k1_harvester.checks.referential_closure import check_referential_closure
from xai.k1_harvester.checks.report import missing_fields


def _closure(data: dict[str, Any]) -> list[str]:
    violations = check_referential_closure(load_draft(json.dumps(data, ensure_ascii=False)))
    assert {v.check for v in violations} <= {CheckName.REFERENTIAL_CLOSURE}
    return [v.element_path for v in violations]


def _completeness(data: dict[str, Any]) -> list[str]:
    violations = check_completeness(data)
    assert {v.check for v in violations} <= {CheckName.COMPLETENESS}
    return [v.element_path for v in violations]


def test_examples_pass_both_checks(example: dict[str, Any]) -> None:
    assert _completeness(example) == []
    assert _closure(example) == []


# ----------------------------------------------------------------------------- completeness


def test_a_null_without_a_reason_is_found(example: dict[str, Any]) -> None:
    data = copy.deepcopy(example)
    data["intervals"][0]["source_ref"] = None

    assert _completeness(data) == ["intervals[0].source_ref"]


def test_a_reason_for_a_field_with_a_value_is_found(example: dict[str, Any]) -> None:
    data = copy.deepcopy(example)
    data["event"].setdefault("unavailable", {})["label"] = {"reason": "fps_not_recorded", "detail": "x"}

    assert _completeness(data) == ["event.unavailable.label"]


def test_a_reason_for_a_missing_field_is_found(example: dict[str, Any]) -> None:
    data = copy.deepcopy(example)
    data["unavailable"]["no_such_field"] = {"reason": "fps_not_recorded", "detail": "x"}

    assert _completeness(data) == ["unavailable.no_such_field"]


def test_a_reason_does_not_cover_another_list_item(example: dict[str, Any]) -> None:
    data = copy.deepcopy(example)
    name, item = next(
        (n, i) for n in ("intervals", "entities", "glossary") for i in data[n] if i.get("unavailable")
    )
    field = next(iter(item["unavailable"]))
    data[name].append(copy.deepcopy(item))
    del data[name][-1]["unavailable"][field]
    if not data[name][-1]["unavailable"]:
        del data[name][-1]["unavailable"]

    assert _completeness(data) == [f"{name}[{len(data[name]) - 1}].{field}"]


def test_the_root_of_the_rule_has_no_parent_by_design(example: dict[str, Any]) -> None:
    roots = [c for c in example["rule"]["constraints"] if c["parent"] is None]

    assert len(roots) == 1
    assert _completeness(example) == []


# ----------------------------------------------------------------------------- referential closure


def test_a_parent_that_does_not_exist_is_found(example: dict[str, Any]) -> None:
    data = copy.deepcopy(example)
    child = next(i for i, c in enumerate(data["rule"]["constraints"]) if c["kind"] == "selection")
    data["rule"]["constraints"][child]["parent"] = "c_s9_proj"

    assert f"rule.constraints[{child}].parent" in _closure(data)


def test_an_argument_without_its_entity_is_found(example: dict[str, Any]) -> None:
    data = copy.deepcopy(example)
    data["event"]["arguments"].append(
        {"role": "M1.arg1", "class": "person", "entity_id": "ent_999", "column": "M1_person"}
    )

    assert _closure(data) == [f"event.arguments[{len(data['event']['arguments']) - 1}].entity_id"]


def test_a_term_without_its_glossary_entry_is_found(example: dict[str, Any]) -> None:
    data = copy.deepcopy(example)
    data["glossary"] = [g for g in data["glossary"] if g["kind"] != "event_model"]

    assert _closure(data) == ["event.label"]


def test_duplicate_ids_are_found(example: dict[str, Any]) -> None:
    data = copy.deepcopy(example)
    data["glossary"].append(copy.deepcopy(data["glossary"][0]))

    assert _closure(data) == ["glossary"]


def test_two_roots_are_found(example: dict[str, Any]) -> None:
    data = copy.deepcopy(example)
    node = next(c for c in data["rule"]["constraints"] if c["parent"] is not None)
    node["parent"] = None

    assert "rule.constraints" in _closure(data)


# ----------------------------------------------------------------------------- report


def test_missing_fields_list_every_reason_once(example: dict[str, Any]) -> None:
    listed = missing_fields(example)
    paths = [(m.path, m.reason) for m in listed]

    assert len(paths) == len(set(paths))
    assert ("actions", Reason.KEYFRAMES_NOT_PERSISTED) in paths
    assert [m.model_dump(mode="json") for m in listed] == example["harvest_report"]["missing_fields"]
