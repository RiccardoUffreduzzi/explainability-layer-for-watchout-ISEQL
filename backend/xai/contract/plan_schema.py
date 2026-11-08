"""JSON schema of the explanation plan, generated from the model.

The schema file is generated, never edited by hand::

    cd backend && python -m xai.contract.plan_schema           # rewrite the file
    cd backend && python -m xai.contract.plan_schema --check   # exit 1 if it is stale
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from xai.contract.json_schema import SCHEMA_DIALECT, ContractSchemaGenerator
from xai.contract.plan import PLAN_VERSION, ExplanationPlan

SCHEMA_PATH = Path(__file__).parent / "schema" / "explanation_plan.schema.json"
SCHEMA_ID = f"urn:watchout-xai:explanation-plan:{PLAN_VERSION}"


def plan_schema() -> dict[str, Any]:
    schema = ExplanationPlan.model_json_schema(mode="validation", schema_generator=ContractSchemaGenerator)
    return {"$schema": SCHEMA_DIALECT, "$id": SCHEMA_ID, **schema}


def schema_text() -> str:
    return json.dumps(plan_schema(), indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--check", action="store_true", help="fail if the file is out of date")
    args = parser.parse_args(argv)
    expected = schema_text()
    if args.check:
        current = SCHEMA_PATH.read_text(encoding="utf-8") if SCHEMA_PATH.exists() else ""
        if current != expected:
            print(f"{SCHEMA_PATH} is out of date: run python -m xai.contract.plan_schema", file=sys.stderr)
            return 1
        return 0
    SCHEMA_PATH.write_text(expected, encoding="utf-8")
    print(f"wrote {SCHEMA_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
