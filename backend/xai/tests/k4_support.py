"""Sources of truth and expected results shared by the tests of K4.

The sources of truth are the example drafts of K1 (``tests/data/*.bozza.json``) passed through
K2 in memory, optionally changed first (``golden_source("handoff_s21_A", change)``).

The expected translations are in ``tests/data/k4/translation/<name>.json``.
"""

import json
from collections.abc import Callable, Mapping
from typing import Any

from xai.contract import ContractDraft
from xai.contract.plan import Binding, ExcludedConstruct, PlanNote, PlanStep, UnmatchedReading
from xai.contract.source_of_truth import SourceOfTruth
from xai.k2.source_of_truth import build_source_of_truth
from xai.k4_planner.translation import BranchSteps, Translation
from xai.k4_planner.view import SourceOfTruthView
from xai.tests.support import EXAMPLE_PATHS, EXAMPLES_DIR, from_json_data, load_example

K4_DATA_DIR = EXAMPLES_DIR / "k4"
TRANSLATION_DIR = K4_DATA_DIR / "translation"

GOLDEN_NAMES = tuple(p.name.removesuffix(".bozza.json") for p in EXAMPLE_PATHS)
"""``fight_s5_A``, ``gunshot_or_explosion_s7_A``, ``handoff_s21_A`` …"""

Change = Callable[[dict[str, Any]], None]


def golden_source(name: str, change: Change | None = None) -> SourceOfTruth:
    """The example draft ``name`` through K2, after ``change`` has edited its JSON data."""
    data = load_example(EXAMPLES_DIR / f"{name}.bozza.json")
    if change is not None:
        change(data)
    return build_source_of_truth(from_json_data(ContractDraft, data))


def view_of(name: str, change: Change | None = None) -> SourceOfTruthView:
    return SourceOfTruthView.of(golden_source(name, change))


def node_data(data: dict[str, Any], constraint_id: str) -> dict[str, Any]:
    """A rule node of draft data, to change it."""
    node: dict[str, Any] = next(n for n in data["rule"]["constraints"] if n["constraint_id"] == constraint_id)
    return node


def expected_translation(name: str) -> dict[str, Any]:
    """The expected translation of a golden draft, without its ``$comment``."""
    data: dict[str, Any] = json.loads((TRANSLATION_DIR / f"{name}.json").read_text(encoding="utf-8"))
    data.pop("$comment", None)
    return data


def translation_to_data(translation: Translation) -> dict[str, Any]:
    """The translation as JSON data, as the expected files of ``tests/data/k4/translation`` hold it."""
    return {
        "branches": [
            {
                "branch": b.branch,
                "steps": [step.model_dump(mode="json") for step in b.steps],
                "conclusion": b.conclusion,
                "bindings": [binding.model_dump(mode="json") for binding in b.bindings],
            }
            for b in translation.branches
        ],
        "excluded": [e.model_dump(mode="json") for e in translation.excluded],
        "unbound_intervals": list(translation.unbound_intervals),
        "unmatched_readings": [u.model_dump(mode="json") for u in translation.unmatched_readings],
        "notes": [n.model_dump(mode="json") for n in translation.notes],
    }


def translation_from_data(data: Mapping[str, Any]) -> Translation:
    """The inverse of ``translation_to_data``; the records are read as JSON, like the contract."""
    return Translation(
        branches=tuple(
            BranchSteps(
                branch=b["branch"],
                steps=tuple(PlanStep.model_validate_json(json.dumps(s)) for s in b["steps"]),
                conclusion=b["conclusion"],
                bindings=tuple(Binding.model_validate_json(json.dumps(x)) for x in b["bindings"]),
            )
            for b in data["branches"]
        ),
        excluded=tuple(ExcludedConstruct.model_validate_json(json.dumps(e)) for e in data["excluded"]),
        unbound_intervals=tuple(data["unbound_intervals"]),
        unmatched_readings=tuple(
            UnmatchedReading.model_validate_json(json.dumps(u)) for u in data["unmatched_readings"]
        ),
        notes=tuple(PlanNote.model_validate_json(json.dumps(n)) for n in data["notes"]),
    )
