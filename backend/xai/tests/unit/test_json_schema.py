import copy
from typing import Any

import jsonschema
import pytest

from xai.contract import CONTRACT_VERSION, json_schema


@pytest.fixture(scope="module")
def validator() -> jsonschema.Draft202012Validator:
    schema = json_schema.contract_draft_schema()
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def test_committed_schema_matches_the_model() -> None:
    assert json_schema.SCHEMA_PATH.read_text(encoding="utf-8") == json_schema.schema_text(), (
        "run: cd backend && python -m xai.contract.json_schema"
    )


def test_check_mode_reports_a_fresh_schema() -> None:
    assert json_schema.main(["--check"]) == 0


def test_examples_are_valid_against_the_schema(
    validator: jsonschema.Draft202012Validator, example: dict[str, Any]
) -> None:
    errors = sorted(validator.iter_errors(example), key=lambda e: list(e.absolute_path))

    assert [f"{list(e.absolute_path)}: {e.message}" for e in errors] == []


def test_schema_rejects_a_reason_outside_the_catalog(
    validator: jsonschema.Draft202012Validator, example: dict[str, Any]
) -> None:
    data = copy.deepcopy(example)
    data["unavailable"]["actions"]["reason"] = "not_implemented_yet"

    assert not validator.is_valid(data)


def test_schema_rejects_k2_fields(
    validator: jsonschema.Draft202012Validator, example: dict[str, Any]
) -> None:
    data = copy.deepcopy(example)
    data["contract_meta"]["contract_hash"] = "abc"

    assert not validator.is_valid(data)


def test_schema_selects_the_payload_by_kind(
    validator: jsonschema.Draft202012Validator, example: dict[str, Any]
) -> None:
    data = copy.deepcopy(example)
    projection = next(c for c in data["rule"]["constraints"] if c["kind"] == "projection")
    projection["kind"] = "selection"

    assert not validator.is_valid(data)


def test_schema_is_bound_to_the_contract_version() -> None:
    schema = json_schema.contract_draft_schema()

    assert schema["$id"].endswith(f":{CONTRACT_VERSION}")
    assert schema["$defs"]["ContractMeta"]["properties"]["contract_version"]["const"] == CONTRACT_VERSION


def test_contract_concepts_have_a_name_in_the_schema() -> None:
    defs = json_schema.contract_draft_schema()["$defs"]

    assert {"Source", "SourceMap", "UnavailableMap", "Timestamp"} <= set(defs)
    assert {"EventId", "IntervalId", "EntityId", "ConstraintId", "TermId"} <= set(defs)
    assert json_schema.schema_text().count(defs["ConstraintId"]["pattern"]) == 1


def test_optional_fields_admit_no_null() -> None:
    properties = json_schema.contract_draft_schema()["$defs"]["OperatorParam"]["properties"]

    assert properties["unit"] == {"enum": ["seconds", "frames"], "type": "string"}
    assert "unit" not in json_schema.contract_draft_schema()["$defs"]["OperatorParam"]["required"]


def test_fields_have_no_generated_titles() -> None:
    def titles(value: Any) -> int:
        if isinstance(value, dict):
            return int("title" in value and "properties" not in value and "enum" not in value) + sum(
                titles(v) for v in value.values()
            )
        if isinstance(value, list):
            return sum(titles(v) for v in value)
        return 0

    assert titles(json_schema.contract_draft_schema()["$defs"]) == 0


def test_integer_or_float_is_a_number() -> None:
    def unions(value: Any) -> list[list[Any]]:
        if isinstance(value, dict):
            found = [value["anyOf"]] if "anyOf" in value else []
            return found + [u for v in value.values() for u in unions(v)]
        if isinstance(value, list):
            return [u for v in value for u in unions(v)]
        return []

    schema = json_schema.contract_draft_schema()
    param_value = schema["$defs"]["OperatorParam"]["properties"]["value"]

    assert not [u for u in unions(schema) if {"type": "integer"} in u and {"type": "number"} in u]
    assert {"type": "number"} in param_value["anyOf"]
