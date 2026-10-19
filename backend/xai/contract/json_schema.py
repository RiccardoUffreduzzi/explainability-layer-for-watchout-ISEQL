"""JSON schema of the contract draft, generated from the model.

The schema file is generated, never edited by hand::

    cd backend && python -m xai.contract.json_schema           # rewrite the file
    cd backend && python -m xai.contract.json_schema --check   # exit 1 if it is stale

A test fails when the committed file differs from the model.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from pydantic.json_schema import GenerateJsonSchema, JsonSchemaMode, JsonSchemaValue
from pydantic_core import CoreSchema

from xai.contract.model import CONTRACT_VERSION, ContractDraft

SCHEMA_PATH = Path(__file__).parent / "schema" / "contract_draft.schema.json"
SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
SCHEMA_ID = f"urn:watchout-xai:contract-draft:{CONTRACT_VERSION}"

_INTEGER = {"type": "integer"}
_NUMBER = {"type": "number"}


class ContractSchemaGenerator(GenerateJsonSchema):
    """Pydantic's generator without its noise.

    - no title made up from the field name (``Start S``): a field is named by its key;
    - ``anyOf [integer, number]`` (``StrictInt | StrictFloat``, kept apart in Python so
      that ``24`` and ``24.0`` stay distinct) is just ``number`` in JSON Schema.
    """

    def field_title_should_be_set(self, schema: Any) -> bool:
        return False

    def generate(self, schema: CoreSchema, mode: JsonSchemaMode = "validation") -> JsonSchemaValue:
        merged: JsonSchemaValue = _merge_integer_into_number(super().generate(schema, mode))
        return merged


def _merge_integer_into_number(value: Any) -> Any:
    if isinstance(value, list):
        return [_merge_integer_into_number(v) for v in value]
    if not isinstance(value, dict):
        return value
    value = {k: _merge_integer_into_number(v) for k, v in value.items()}
    variants = value.get("anyOf")
    if isinstance(variants, list) and _INTEGER in variants and _NUMBER in variants:
        kept = [v for v in variants if v != _INTEGER]
        del value["anyOf"]
        if len(kept) == 1:
            value.update(kept[0])
        else:
            value["anyOf"] = kept
    return value


def contract_draft_schema() -> dict[str, Any]:
    """The schema of a draft as K1 accepts it on input, bound to ``CONTRACT_VERSION``."""
    schema = ContractDraft.model_json_schema(mode="validation", schema_generator=ContractSchemaGenerator)
    return {"$schema": SCHEMA_DIALECT, "$id": SCHEMA_ID, **schema}


def schema_text() -> str:
    return json.dumps(contract_draft_schema(), indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--check", action="store_true", help="fail if the file is out of date")
    args = parser.parse_args(argv)
    expected = schema_text()
    if args.check:
        current = SCHEMA_PATH.read_text(encoding="utf-8") if SCHEMA_PATH.exists() else ""
        if current != expected:
            print(f"{SCHEMA_PATH} is out of date: run python -m xai.contract.json_schema", file=sys.stderr)
            return 1
        return 0
    SCHEMA_PATH.write_text(expected, encoding="utf-8")
    print(f"wrote {SCHEMA_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
