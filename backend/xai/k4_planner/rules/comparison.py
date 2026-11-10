"""``identity`` and ``attribute_comparison`` -> a step on the two sides of the comparison.

An identity between two or more variables is an ``identity`` step; on one variable
(``M1.arg1 ≠ M1.arg2``, two different people) it is a ``condition``. 
An attribute comparison is always a ``condition``. The glossary
entry is ``g_comparison_<kind>_<op>``
"""

from xai.contract.ids import comparison_term, step_id_of, term_id
from xai.contract.model import AttributeComparisonNode, ComparisonPayload, ConstraintNode, IdentityNode
from xai.contract.plan import IN_REPORT2, PlanStep, StepRole, StepType
from xai.k4_planner.rules.base import (
    RuleContext,
    RuleResult,
    argument_position,
    expect,
    observations,
    side_entity,
    t_order_after,
    unique,
)


def _step(
    constraint_id: str,
    kind: str,
    variables: list[str],
    payload: ComparisonPayload,
    slots: dict[str, str | None],
    step_type: StepType,
    ctx: RuleContext,
) -> PlanStep:
    term = term_id("comparison", comparison_term(kind, payload.op))
    depends_on = observations(variables, ctx)
    t_order, basis = t_order_after(depends_on, ctx)
    return PlanStep(
        step_id=step_id_of(constraint_id),
        type=step_type,
        construct_=constraint_id,
        refs=unique([constraint_id, *slots.values(), term]),
        role=StepRole.BECAUSE,
        depends_on=depends_on,
        t_order=t_order,
        t_order_basis=basis,
        in_report2=IN_REPORT2[step_type],
        term=term,
        slots=slots,
    )


def _side(side: str, place: str, constraint_id: str, ctx: RuleContext) -> str | None:
    """A side of an attribute comparison as a slot.

    An argument is its entity, null when the entity is not known; any
    other side (``M1.st``) has no ID and is cited by its place in the node.
    """
    if argument_position(side) is not None:
        return side_entity(side, ctx)
    return ctx.view.pointer(constraint_id, "payload", place)


class IdentityRule:
    def translate(self, node: ConstraintNode, ctx: RuleContext) -> RuleResult:
        identity = expect(node, IdentityNode)
        payload = identity.payload
        slots = {"left": side_entity(payload.left, ctx), "right": side_entity(payload.right, ctx)}
        step_type = StepType.IDENTITY if len(set(identity.variables)) > 1 else StepType.CONDITION
        step = _step(
            identity.constraint_id, identity.kind, identity.variables, payload, slots, step_type, ctx
        )
        return RuleResult(step=step)


class AttributeComparisonRule:
    def translate(self, node: ConstraintNode, ctx: RuleContext) -> RuleResult:
        comparison = expect(node, AttributeComparisonNode)
        payload = comparison.payload
        cid = comparison.constraint_id
        slots = {
            "left": _side(payload.left, "left", cid, ctx),
            "right": _side(payload.right, "right", cid, ctx),
        }
        step = _step(cid, comparison.kind, comparison.variables, payload, slots, StepType.CONDITION, ctx)
        return RuleResult(step=step)
