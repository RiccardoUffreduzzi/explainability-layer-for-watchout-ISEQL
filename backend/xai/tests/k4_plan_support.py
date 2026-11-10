"""Plans and helpers shared by the tests of the limits, the order and the delivery of K4.

The plans are made from the golden sources of ``k4_support`` (the example drafts of K1 through
K2), optionally changed first. The expected translations of ``tests/data/k4/translation`` are
the input of the planner when a test wants to be independent of the rule readers.
"""

import json
from typing import Any

from xai.contract.plan import ExplanationPlan, PlanStep
from xai.contract.source_of_truth import SourceOfTruth
from xai.k4_planner.planner import ExplanationPlanner
from xai.k4_planner.translation import Translation, translation_from_data
from xai.tests.k4_support import Change, expected_translation, golden_source

AUDIO = "vehicle_collision_s15_C_audio"
AUDIO_CLASSES = (
    "g_audio_class_glass_breaking",
    "g_audio_class_horn",
    "g_audio_class_impact",
    "g_audio_class_skidding",
)
UNDEFINED = {"definition": {"reason": "glossary_definition_not_in_system", "detail": "x"}}


def source_and_plan(name: str, change: Change | None = None) -> tuple[SourceOfTruth, ExplanationPlan]:
    document = golden_source(name, change)
    return document, ExplanationPlanner().plan(document)


def plan_of(name: str, change: Change | None = None) -> ExplanationPlan:
    return source_and_plan(name, change)[1]


def translation_of(name: str) -> Translation:
    """The expected translation of a golden draft, as the planner receives it from the rule readers."""
    return translation_from_data(expected_translation(name))


def step(plan: ExplanationPlan, step_id: str) -> PlanStep:
    return next(s for s in plan.steps if s.step_id == step_id)


def step_ids(plan: ExplanationPlan) -> list[str]:
    return [s.step_id for s in plan.steps]


def reading_ids(plan: ExplanationPlan) -> list[str]:
    """The steps of the plan without the provenance steps that close it."""
    return [i for i in step_ids(plan) if not i.startswith("s_prov_")]


def undefine_terms(*term_ids: str) -> Change:
    """A change of the draft that leaves the glossary entries without a definition."""

    def change(data: dict[str, Any]) -> None:
        for entry in data["glossary"]:
            if entry["term_id"] in term_ids:
                entry["definition"] = None
                entry["unavailable"] = UNDEFINED

    return change


def both_branches(data: dict[str, Any]) -> None:
    """The row is explained by both branches of the rule."""
    data["event"]["origin_basis"]["branch"] = "left, right"


def without_audio_rule(data: dict[str, Any]) -> None:
    data["event"]["modality_rules"]["audio"] = None


def frames_missing(data: dict[str, Any]) -> None:
    """Audio read in seconds, no frame number: the modalities cannot be compared."""
    for detection in data["event"]["modality_detections"]:
        if detection["modality"] == "audio":
            detection["interval"] = {
                "start_frame": None,
                "end_frame": None,
                "start_s": 0.0,
                "end_s": 7.5,
                "read_as": "seconds",
            }
        else:
            detection["interval"].update(start_frame=200, end_frame=240, start_s=200 / 24, end_s=240 / 24)


def without_merge_tolerance(data: dict[str, Any]) -> None:
    data["contract_meta"]["pipeline_config"]["merge_tolerance_s"] = None


def resolve_pointer(data: Any, pointer: str) -> Any:
    """The part of ``data`` a ``#/a/0/b`` pointer names; ``KeyError`` or ``IndexError`` if none."""
    assert pointer.startswith("#/"), pointer
    node = data
    for token in pointer[2:].split("/"):
        key = token.replace("~1", "/").replace("~0", "~")
        node = node[int(key)] if isinstance(node, list) else node[key]
    return node


def dumps(data: Any) -> str:
    return json.dumps(data, sort_keys=True)
