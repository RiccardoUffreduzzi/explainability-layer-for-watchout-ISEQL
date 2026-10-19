"""Golden drafts: whole drafts compared with the expected files.

The expected files are the examples of ``tests/data``, which the contract tests also
validate against the model and the schema. After a deliberate change regenerate them
with ``XAI_UPDATE_GOLDEN=1 pytest tests/golden`` and review the diff: the ``$comment``
of each file is kept.
"""

import json
import os
from typing import Any

import pytest

from xai.contract.model import ContractDraft
from xai.contract.serialization import draft_to_data, dump_draft
from xai.tests.harness import GOLDEN_CASES, GoldenCase, make_stage, open_reader
from xai.tests.support import load_example

UPDATE = os.environ.get("XAI_UPDATE_GOLDEN") == "1"


DATABASE_FIXTURES = {"test": "watchout_db", "ablation_rules": "ablation_rules_db"}


def _harvest(request: pytest.FixtureRequest, case: GoldenCase) -> ContractDraft:
    conn, reader = open_reader(request.getfixturevalue(DATABASE_FIXTURES[case.database]))
    try:
        return make_stage(reader).harvest(case.request)
    finally:
        conn.close()


@pytest.mark.parametrize("case", GOLDEN_CASES, ids=lambda c: c.name)
def test_draft_equals_the_expected_file(request: pytest.FixtureRequest, case: GoldenCase) -> None:
    data = draft_to_data(_harvest(request, case))
    if UPDATE:
        _write(case, data)

    assert data == load_example(case.path)


@pytest.mark.parametrize("case", GOLDEN_CASES, ids=lambda c: c.name)
def test_two_runs_give_the_same_text(request: pytest.FixtureRequest, case: GoldenCase) -> None:
    texts = [dump_draft(_harvest(request, case)) for _ in range(2)]

    assert texts[0] == texts[1]


def _write(case: GoldenCase, data: dict[str, Any]) -> None:
    comment = f"Golden case: {case.why}."
    if case.path.is_file():
        comment = json.loads(case.path.read_text(encoding="utf-8")).get("$comment", comment)
    text = json.dumps({"$comment": comment, **data}, ensure_ascii=False, indent=2)
    case.path.write_text(text + "\n", encoding="utf-8", newline="\n")
