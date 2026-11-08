"""``projection`` -> the conclusion of a branch: what was flagged (K4-A5: it has no role)."""

from xai.contract.ids import step_id_of, term_id
from xai.contract.model import ConstraintNode, ProjectionNode
from xai.contract.plan import IN_REPORT2, PlanStep, StepType
from xai.k4_planner.rules.base import RuleContext, RuleResult, expect, t_order_after, unique


class ProjectionRule:
    def translate(self, node: ConstraintNode, ctx: RuleContext) -> RuleResult:
        projection = expect(node, ProjectionNode)
        event = ctx.view.event
        term = term_id("event_model", event.label)
        depends_on = list(ctx.leaves)
        t_order, basis = t_order_after(depends_on, ctx)
        step = PlanStep(
            step_id=step_id_of(projection.constraint_id),
            type=StepType.CONCLUSION,
            construct_=projection.constraint_id,
            refs=unique(
                [projection.constraint_id, event.event_id, *(a.entity_id for a in event.arguments), term]
            ),
            depends_on=depends_on,
            t_order=t_order,
            t_order_basis=basis,
            in_report2=IN_REPORT2[StepType.CONCLUSION],
            term=term,
        )
        return RuleResult(step=step)
