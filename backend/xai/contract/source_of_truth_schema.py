"""JSON schema of the source of truth, generated from the model.

The schema file is generated, never edited by hand::

    cd backend && python -m xai.contract.source_of_truth_schema           # rewrite the file
    cd backend && python -m xai.contract.source_of_truth_schema --check   # exit 1 if it is stale
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from xai.contract.json_schema import SCHEMA_DIALECT, ContractSchemaGenerator
from xai.contract.source_of_truth import SOURCE_OF_TRUTH_VERSION, SourceOfTruth

SCHEMA_PATH = Path(__file__).parent / "schema" / "source_of_truth.schema.json"
SCHEMA_ID = f"urn:watchout-xai:source-of-truth:{SOURCE_OF_TRUTH_VERSION}"


def source_of_truth_schema() -> dict[str, Any]:
    schema = SourceOfTruth.model_json_schema(mode="validation", schema_generator=ContractSchemaGenerator)
    return {"$schema": SCHEMA_DIALECT, "$id": SCHEMA_ID, **schema}


def schema_text() -> str:
    return json.dumps(source_of_truth_schema(), indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--check", action="store_true", help="fail if the file is out of date")
    args = parser.parse_args(argv)
    expected = schema_text()
    if args.check:
        current = SCHEMA_PATH.read_text(encoding="utf-8") if SCHEMA_PATH.exists() else ""
        if current != expected:
            print(
                f"{SCHEMA_PATH} is out of date: run python -m xai.contract.source_of_truth_schema",
                file=sys.stderr,
            )
            return 1
        return 0
    SCHEMA_PATH.write_text(expected, encoding="utf-8")
    print(f"wrote {SCHEMA_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
