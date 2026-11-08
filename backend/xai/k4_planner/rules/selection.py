"""``selection`` -> an observation step: what was seen, by which variable."""

from xai.contract.ids import step_id_of, term_id
from xai.contract.model import ConstraintNode, IntervalRecord, SelectionNode
from xai.contract.plan import IN_REPORT2, PlanStep, StepRole, StepType, TOrderBasis
from xai.k4_planner.rules.base import RuleContext, RuleResult, entity_of, expect, unique

TERM_KIND = {"visual": "predicate", "audio": "audio_class"}
"""The glossary kind of the alternatives of a selection, by the modality of its node."""


class SelectionRule:
    def translate(self, node: ConstraintNode, ctx: RuleContext) -> RuleResult:
        selection = expect(node, SelectionNode)
        variable = selection.variables[0]
        binding = ctx.bindings[variable]
        kind = TERM_KIND[selection.modality]
        predicates = unique(p for option in selection.payload.branches for p in option.predicates)

        interval = ctx.view.interval(binding.interval_id) if binding.interval_id else None
        if interval is not None:
            term: str | None = term_id(kind, interval.predicate)
        elif len(predicates) == 1:
            term = term_id(kind, predicates[0])
        else:
            term = None
        alternatives = [term_id(kind, p) for p in predicates] if len(predicates) > 1 else None

        slots: dict[str, str | None] | None = None
        if selection.modality == "visual":
            positions = sorted(
                {int(slot) for option in selection.payload.branches for slot in option.arg_classes}
            )
            slots = {f"arg{n}": entity_of(variable, n, ctx) for n in positions} or None

        interval_for_time: IntervalRecord | None
        if interval is None and binding.candidates:  # ambiguous: the first candidate (K4-A3)
            interval_for_time = ctx.view.interval(binding.candidates[0])
        else:
            interval_for_time = interval
        t_order = interval_for_time.anchor.start_s if interval_for_time is not None else None

        refs = unique(
            [
                selection.constraint_id,
                interval.interval_id if interval is not None else None,
                *(slots.values() if slots else ()),
                *([term] if term else alternatives or ()),
            ]
        )
        step = PlanStep(
            step_id=step_id_of(selection.constraint_id),
            type=StepType.OBSERVATION,
            construct_=selection.constraint_id,
            refs=refs,
            role=StepRole.BECAUSE,
            depends_on=[],
            t_order=t_order,
            t_order_basis=TOrderBasis.INTERVAL if t_order is not None else TOrderBasis.NONE,
            in_report2=IN_REPORT2[StepType.OBSERVATION],
            term=term,
            slots=slots,
            alternatives=alternatives,
        )
        return RuleResult(step=step)
