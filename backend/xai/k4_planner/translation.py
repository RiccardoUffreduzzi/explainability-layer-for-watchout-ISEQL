"""The rule of a source of truth translated into steps.

``translate`` turns the explained branches of a source of truth into steps, one per rule
node, with their dependencies, and says what it left out so 
the planner adds and orders them, starting from a ``Translation``.

For each branch the steps are made in three rounds: the observations, then the other nodes
in rule order, then the conclusion on the steps no other step depends on.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from xai.contract.model import ConstraintNode
from xai.contract.plan import Binding, ExcludedConstruct, PlanNote, PlanStep, UnmatchedReading
from xai.k4_planner.bindings import VariableBinding, resolve_bindings
from xai.k4_planner.branches import choose_branches
from xai.k4_planner.rules import RULES, RuleContext, RuleResult
from xai.k4_planner.view import SourceOfTruthView


@dataclass(frozen=True)
class BranchSteps:
    branch: str
    steps: tuple[PlanStep, ...]
    """The observations, then the other nodes in rule order, then the conclusion"""
    conclusion: str
    """``step_id`` of the conclusion"""
    bindings: tuple[Binding, ...]


@dataclass(frozen=True)
class Translation:
    branches: tuple[BranchSteps, ...]
    """The explained branches, in rule order"""
    excluded: tuple[ExcludedConstruct, ...]
    unbound_intervals: tuple[str, ...]
    unmatched_readings: tuple[UnmatchedReading, ...]
    notes: tuple[PlanNote, ...]


def translate(view: SourceOfTruthView) -> Translation:
    choice = choose_branches(view)
    branches: list[BranchSteps] = []
    results: list[RuleResult] = []
    attributed: set[str] = set()
    for branch in choice.explained:
        bindings = resolve_bindings(view, branch)
        made = _translate_branch(view, branch, {b.variable: b for b in bindings})
        results.extend(made)
        steps = tuple(result.step for result in made)
        branches.append(
            BranchSteps(
                branch=branch,
                steps=steps,
                conclusion=steps[-1].step_id,
                bindings=tuple(b.to_binding() for b in bindings),
            )
        )
        attributed.update(b.interval_id for b in bindings if b.interval_id is not None)
    return Translation(
        branches=tuple(branches),
        excluded=choice.excluded,
        unbound_intervals=tuple(i.interval_id for i in view.intervals if i.interval_id not in attributed),
        unmatched_readings=tuple(u for result in results for u in result.unmatched_readings),
        notes=tuple(n for result in results for n in result.notes),
    )


def _translate_branch(
    view: SourceOfTruthView, branch: str, bindings: Mapping[str, VariableBinding]
) -> list[RuleResult]:
    made: list[RuleResult] = []
    observation_of: dict[str, str] = {}
    t_orders: dict[str, float | None] = {}

    def run(node: ConstraintNode, leaves: tuple[str, ...] = ()) -> RuleResult:
        ctx = RuleContext(
            view=view,
            branch=branch,
            bindings=bindings,
            observation_of=MappingProxyType(dict(observation_of)),
            t_orders=MappingProxyType(dict(t_orders)),
            leaves=leaves,
        )
        result = RULES[node.kind].translate(node, ctx)
        made.append(result)
        t_orders[result.step.step_id] = result.step.t_order
        return result

    nodes = view.nodes_of(branch)
    for node in nodes:  # 1. the observations
        if node.kind == "selection":
            observation_of[node.variables[0]] = run(node).step.step_id
    for node in nodes:  # 2. conditions, operators, identities
        if node.kind not in ("selection", "projection"):
            run(node)
    depended = {d for result in made for d in result.step.depends_on}
    leaves = tuple(r.step.step_id for r in made if r.step.step_id not in depended)
    run(view.projection_of(branch), leaves)  # 3. the conclusion
    return made


# --------------------------------------------------------------------------- JSON form


def translation_to_data(translation: Translation) -> dict[str, Any]:
    """The translation as JSON data, for the expected files of ``tests/data/k4/translation``."""
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
