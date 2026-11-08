"""``temporal_operator`` -> a temporal step between the observations of ``r`` and ``s``."""

from xai.contract.ids import step_id_of, term_id
from xai.contract.model import ConstraintNode, TemporalOperatorNode
from xai.contract.plan import IN_REPORT2, PlanStep, StepRole, StepType
from xai.k4_planner.readings import choose_readings
from xai.k4_planner.rules.base import RuleContext, RuleResult, expect, observations, t_order_after


class TemporalOperatorRule:
    def translate(self, node: ConstraintNode, ctx: RuleContext) -> RuleResult:
        operator = expect(node, TemporalOperatorNode)
        r, s = operator.variables[0], operator.variables[1]  # as K1 reads them (K4-A1)
        term = term_id("operator", operator.payload.name)
        depends_on = observations(operator.variables, ctx)
        t_order, basis = t_order_after(depends_on, ctx)
        choice = choose_readings(ctx.view, operator)
        step = PlanStep(
            step_id=step_id_of(operator.constraint_id),
            type=StepType.TEMPORAL,
            construct_=operator.constraint_id,
            refs=[operator.constraint_id, term],
            role=StepRole.BECAUSE,
            depends_on=depends_on,
            t_order=t_order,
            t_order_basis=basis,
            in_report2=IN_REPORT2[StepType.TEMPORAL],
            term=term,
            slots={"r": ctx.observation_of[r], "s": ctx.observation_of[s]},
            readings=list(choice.readings) or None,
        )
        return RuleResult(step=step, unmatched_readings=choice.unmatched, notes=choice.notes)
