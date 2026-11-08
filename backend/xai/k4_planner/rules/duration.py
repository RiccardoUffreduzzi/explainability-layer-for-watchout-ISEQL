"""``duration`` -> a condition on how long the observation of a variable lasted."""

from xai.contract.ids import comparison_term, step_id_of, term_id
from xai.contract.model import ConstraintNode, DurationNode
from xai.contract.plan import IN_REPORT2, PlanStep, StepRole, StepType
from xai.k4_planner.rules.base import RuleContext, RuleResult, expect, observations, t_order_after


class DurationRule:
    def translate(self, node: ConstraintNode, ctx: RuleContext) -> RuleResult:
        duration = expect(node, DurationNode)
        cid = duration.constraint_id
        term = term_id("comparison", comparison_term(duration.kind, duration.payload.op))
        depends_on = observations(duration.variables, ctx)
        t_order, basis = t_order_after(depends_on, ctx)
        # {x} is one variable's observation; a duration between two variables has no entry yet.
        x = depends_on[0] if len(depends_on) == 1 else None
        step = PlanStep(
            step_id=step_id_of(cid),
            type=StepType.CONDITION,
            construct_=cid,
            refs=[cid, term],
            role=StepRole.BECAUSE,
            depends_on=depends_on,
            t_order=t_order,
            t_order_basis=basis,
            in_report2=IN_REPORT2[StepType.CONDITION],
            term=term,
            slots={
                "x": x,
                "value": ctx.view.pointer(cid, "payload", "value"),
                "unit": ctx.view.pointer(cid, "payload", "unit"),
            },
        )
        return RuleResult(step=step)
