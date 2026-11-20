"""The input of the LLM: the plan, the values it cites and the glossary phrases of its terms.

This module reads a plan and a source of truth. It checks that
they go together (the plan's hash, the same ``contract_hash``, the same detection), then gives
the LLM the k4 plan (for Report 2 only the steps with ``in_report2``) without the steps of the
sections the system writes, the values those steps cite, and the phrases of the glossary
entries they cite. Of the key frame the LLM gets the time and the frame
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from xai.contract.plan import ExplanationPlan, PlanStep, compute_plan_hash, load_plan, plan_to_data
from xai.contract.source_of_truth import SourceOfTruth, load_source_of_truth, verify_contract_hash
from xai.reporting.catalogue import TimeFormat, ValueLabels
from xai.reporting.failure import ReportFailure
from xai.reporting.profile import ReportProfile
from xai.reporting.values import ValueReader, ValueTable, cited_refs

INPUT_INDENT = 2


@dataclass(frozen=True)
class ReportInput:
    """What one report is written from"""

    plan: ExplanationPlan
    """The k4 plan"""
    document: SourceOfTruth
    steps: tuple[PlanStep, ...]
    """The steps the LLM receives"""
    system_steps: tuple[PlanStep, ...]
    """The steps of the sections the system writes."""
    table: ValueTable
    """The values of all the steps."""
    llm_names: frozenset[str]
    """The names of the values and the entities the LLM receives: those its steps cite."""
    glossary: Mapping[str, Mapping[str, str]]
    """Term ID -> ``kind``, ``term`` and ``phrase`` of every glossary entry the steps cite."""
    codes: Mapping[str, str]
    """The codes of the plan's bindings, with what they mean."""

    def step_ids(self) -> frozenset[str]:
        return frozenset(step.step_id for step in self.steps)

    def to_data(self) -> dict[str, Any]:
        """The JSON the prompt carries."""
        plan = plan_to_data(self.plan)
        kept = self.step_ids()
        plan["steps"] = [step for step in plan["steps"] if step["step_id"] in kept]
        return {
            "plan": plan,
            "values": {v.name: v.for_llm() for v in self.table.values if v.name in self.llm_names},
            "entities": {
                e.entity_id: e.for_llm() for e in self.table.entities if e.entity_id in self.llm_names
            },
            "glossary": {term: dict(entry) for term, entry in self.glossary.items()},
            "codes": dict(self.codes),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_data(), ensure_ascii=False, indent=INPUT_INDENT)


def build_input(
    plan: ExplanationPlan,
    document: SourceOfTruth,
    profile: ReportProfile,
    labels: ValueLabels,
    time_format: TimeFormat = "m:ss",
) -> ReportInput:
    """The input of one report; ``ReportFailure`` when plan and source of truth do not go together."""
    check_pair(plan, document)
    admitted = tuple(step for step in plan.steps if profile.admits(step))
    steps = tuple(step for step in admitted if not profile.by_system(step))
    reader = ValueReader(document, labels, time_format)
    table = reader.table(admitted)
    terms = {entry.term_id: entry for entry in document.glossary}
    glossary = {
        ref: {"kind": terms[ref].kind, "term": terms[ref].term, "phrase": terms[ref].plain_template}
        for ref in cited_refs(steps)
        if ref in terms
    }
    used = [code for binding in plan.bindings for code in (*binding.basis, binding.status.value)]
    codes = {code: labels.codes[code] for code in dict.fromkeys(used) if code in labels.codes}
    return ReportInput(
        plan=plan,
        document=document,
        steps=steps,
        system_steps=tuple(step for step in admitted if profile.by_system(step)),
        table=table,
        llm_names=reader.table(steps).names(),
        glossary=glossary,
        codes=codes,
    )


def check_pair(plan: ExplanationPlan, document: SourceOfTruth) -> None:
    meta = plan.plan_meta
    if compute_plan_hash(plan_to_data(plan)) != meta.plan_hash:
        raise ReportFailure("PLAN_HASH_MISMATCH", "the plan's content does not match its plan_hash")
    if not verify_contract_hash(document):
        raise ReportFailure("CONTRACT_HASH_MISMATCH", "the source of truth does not match its contract_hash")
    if meta.contract_hash != document.contract_meta.contract_hash:
        raise ReportFailure(
            "CONTRACT_HASH_MISMATCH",
            f"the plan was made from {meta.contract_hash}, the source of truth is "
            f"{document.contract_meta.contract_hash}",
        )
    if meta.event_id != document.event.event_id:
        raise ReportFailure(
            "EVENT_MISMATCH",
            f"the plan is of {meta.event_id}, the source of truth of {document.event.event_id}",
        )


def read_plan(path: Path) -> ExplanationPlan:
    try:
        return load_plan(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ReportFailure("PLAN_NOT_FOUND", f"{path} does not exist") from None
    except ValidationError as error:
        raise ReportFailure("PLAN_INVALID", f"{path}: {error.error_count()} schema violation(s)") from None


def read_source(path: Path) -> SourceOfTruth:
    try:
        return load_source_of_truth(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ReportFailure("SOURCE_NOT_FOUND", f"{path} does not exist") from None
    except ValidationError as error:
        raise ReportFailure("SOURCE_INVALID", f"{path}: {error.error_count()} schema violation(s)") from None
