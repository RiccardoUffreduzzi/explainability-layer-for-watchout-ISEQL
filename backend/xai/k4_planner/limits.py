"""Limits: one ``limit`` step for each knowledge limit K2 wrote, hooked to what it comes from.

A limit is hooked to the steps that cite its ``refs`` (K2 says which rule nodes or glossary
entries it comes from): the node of a rule step, the term of a step or one of the alternatives of
a selection step. A limit without ``refs``, or whose ``refs`` no step cites, is hooked to the
conclusions of the explained branches (K4-A9).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from xai.contract.plan import IN_REPORT2, PlanStep, StepRole, StepType
from xai.contract.source_of_truth import KnowledgeLimit
from xai.k4_planner.timing import latest_t_order
from xai.k4_planner.translation import BranchSteps
from xai.k4_planner.view import SourceOfTruthView

LIMIT_STEP_PREFIX = "s_lim_"
"""A limit step is ``s_lim_<code>``: a code appears once in ``knowledge_limits``."""


@dataclass(frozen=True)
class LimitLinker:
    view: SourceOfTruthView

    def link(self, branches: Sequence[BranchSteps]) -> tuple[PlanStep, ...]:
        """The limit steps, in the order K2 wrote the limits."""
        rule_steps = tuple(step for branch in branches for step in branch.steps)
        conclusions = tuple(branch.conclusion for branch in branches)
        t_orders = {step.step_id: step.t_order for step in rule_steps}
        steps = []
        for index, limit in enumerate(self.view.limits()):
            anchors = _anchors(limit, rule_steps) or conclusions
            steps.append(self._step(index, limit, anchors, t_orders))
        return tuple(steps)

    def _step(
        self,
        index: int,
        limit: KnowledgeLimit,
        anchors: Sequence[str],
        t_orders: Mapping[str, float | None],
    ) -> PlanStep:
        t_order, basis = latest_t_order(anchors, t_orders)
        # F2-4 (b): the pointer to the limit first, then the IDs K2 wrote.
        refs = [self.view.source_pointer("knowledge_limits", index), *(limit.refs or ())]
        return PlanStep(
            step_id=f"{LIMIT_STEP_PREFIX}{limit.code.value}",
            type=StepType.LIMIT,
            refs=refs,
            role=StepRole.LIMIT,
            depends_on=list(anchors),
            t_order=t_order,
            t_order_basis=basis,
            in_report2=IN_REPORT2[StepType.LIMIT],
            limit_code=limit.code,
            fixed_text=limit.sentence,
        )


def _anchors(limit: KnowledgeLimit, rule_steps: Sequence[PlanStep]) -> tuple[str, ...]:
    """The rule steps that cite the ``refs`` K2 wrote for the limit, in rule order.

    Only K2's ``refs`` count: the pointer the limit step adds to its own refs does not.
    """
    wanted = set(limit.refs or ())
    if not wanted:
        return ()
    return tuple(step.step_id for step in rule_steps if wanted & _cited(step))


def _cited(step: PlanStep) -> set[str]:
    """Every ID of the contract the step names: its ``refs``, its term and its alternatives."""
    cited = set(step.refs) | set(step.alternatives or ())
    if step.construct_ is not None:
        cited.add(step.construct_)
    if step.term is not None:
        cited.add(step.term)
    return cited
