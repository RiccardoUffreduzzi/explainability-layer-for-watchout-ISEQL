"""The plans of the example drafts of K1, byte for byte.

``tests/data/k4/plan/<name>.json`` is the plan K4 writes for the example draft ``<name>``
(through K2, in memory). Regenerate them with ``XAI_UPDATE_GOLDEN=1 pytest tests/golden`` and
review the diff: a change of a plan is a change of what Reports 1 and 2 will say.
"""

import os

import pytest

from xai.contract.plan import dump_plan
from xai.k4_planner.stage import PLAN_INDENT
from xai.tests.k4_plan_support import plan_of
from xai.tests.k4_support import GOLDEN_NAMES, K4_DATA_DIR

PLAN_DIR = K4_DATA_DIR / "plan"
UPDATE = os.environ.get("XAI_UPDATE_GOLDEN") == "1"


@pytest.mark.parametrize("name", GOLDEN_NAMES)
def test_the_plan_is_the_golden_one(name: str) -> None:
    text = dump_plan(plan_of(name), indent=PLAN_INDENT) + "\n"
    golden = PLAN_DIR / f"{name}.json"
    if UPDATE:
        PLAN_DIR.mkdir(parents=True, exist_ok=True)
        golden.write_text(text, encoding="utf-8")

    assert golden.read_text(encoding="utf-8") == text
