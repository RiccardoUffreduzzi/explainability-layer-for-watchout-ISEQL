"""``ExplanationPlanner``: from one source of truth to one plan.

The translation of the rule (``translate``) gives the steps of the rule and the bindings. This
module adds the limits, the reinforcement and the provenance, puts all the steps in reading
order and seals the plan with its hash. It also reads and validates the file of K2 that a plan
starts from (UC-K4-02).

There is no structural check at run time (K4-D6): K1 and K2 guarantee the input and the
properties of the plan are checked in the tests.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from pydantic import ValidationError

from xai.contract.canonical import canonical_json
from xai.contract.plan import (
    PLAN_VERSION,
    ExplanationPlan,
    PlanMeta,
    PlanReport,
    compute_plan_hash,
    load_plan,
    plan_to_data,
)
from xai.contract.source_of_truth import SourceOfTruth, load_source_of_truth, verify_contract_hash
from xai.k4_planner.limits import LimitLinker
from xai.k4_planner.ordering import ReadingOrder
from xai.k4_planner.provenance import ProvenanceRule
from xai.k4_planner.reinforcement import ReinforcementRule
from xai.k4_planner.translation import Translation, translate
from xai.k4_planner.view import SourceOfTruthView

_PLACEHOLDER_HASH: Final = "0" * 64
MAX_VIOLATIONS: Final = 20
"""How many schema violations a ``SOURCE_INVALID`` failure lists."""


@dataclass(frozen=True)
class Violation:
    check: str
    element: str
    detail: str


class PlanFailure(Exception):
    """The source of truth K4 was given cannot be planned: no plan is written, never a partial one."""

    def __init__(self, code: str, message: str, violations: Sequence[Violation] = ()) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.violations = tuple(violations)

    def to_data(self) -> dict[str, Any]:
        return {
            "stage": "input",
            "code": self.code,
            "message": self.message,
            "violations": [
                {"check": v.check, "element": v.element, "detail": v.detail} for v in self.violations
            ],
        }


def read_source(path: Path) -> SourceOfTruth:
    """The source of truth in ``path``, checked: it parses, its hash matches and K1's checks passed."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise PlanFailure("SOURCE_NOT_FOUND", f"{path} does not exist") from None
    try:
        document = load_source_of_truth(text)
    except ValidationError as error:
        violations = [
            Violation("schema", ".".join(str(part) for part in item["loc"]), item["msg"])
            for item in error.errors()[:MAX_VIOLATIONS]
        ]
        raise PlanFailure("SOURCE_INVALID", f"{path} is not a valid source of truth", violations) from None
    if not verify_contract_hash(document):
        raise PlanFailure(
            "CONTRACT_HASH_MISMATCH",
            f"{path} does not match its contract_hash",
            [Violation("contract_hash", "contract_meta.contract_hash", "the hash of the content differs")],
        )
    failed = [
        Violation(check.name, violation.element_path, violation.detail)
        for check in document.harvest_report.checks
        if not check.passed
        for violation in check.violations
    ]
    if failed:
        raise PlanFailure("K1_CHECKS_NOT_PASSED", f"the checks of K1 did not pass for {path}", failed)
    return document


class ExplanationPlanner:
    def __init__(self, translate_rule: Callable[[SourceOfTruthView], Translation] = translate) -> None:
        self._translate = translate_rule

    def plan(self, document: SourceOfTruth) -> ExplanationPlan:
        view = SourceOfTruthView.of(document)
        translation = self._translate(view)
        branches = translation.branches
        conclusions = tuple(branch.conclusion for branch in branches)
        t_orders = {step.step_id: step.t_order for branch in branches for step in branch.steps}
        bindings = [binding for branch in branches for binding in branch.bindings]

        limits = LimitLinker(view).link(branches)
        reinforcement = ReinforcementRule(view).step(conclusions, t_orders)
        provenance = ProvenanceRule(view).steps(bindings, reinforcement=reinforcement is not None)
        steps = ReadingOrder(view).order(branches, limits, reinforcement, provenance)

        meta = document.contract_meta
        unsealed = ExplanationPlan(
            plan_meta=PlanMeta.model_validate(
                {
                    "plan_version": PLAN_VERSION,
                    "contract_hash": meta.contract_hash,
                    "source_of_truth_version": meta.source_of_truth_version,
                    "contract_version": meta.contract_version,
                    "event_id": view.event.event_id,
                    "model_id": view.event.model_id,
                    "label": view.event.label,
                    "branches": [branch.branch for branch in branches],
                    "plan_hash": _PLACEHOLDER_HASH,
                }
            ),
            steps=list(steps),
            bindings=bindings,
            plan_report=PlanReport(
                excluded_constructs=list(translation.excluded),
                unbound_intervals=list(translation.unbound_intervals),
                unmatched_readings=list(translation.unmatched_readings),
                notes=list(translation.notes),
            ),
        )
        data = plan_to_data(unsealed)
        data["plan_meta"]["plan_hash"] = compute_plan_hash(data)
        return load_plan(canonical_json(data))
