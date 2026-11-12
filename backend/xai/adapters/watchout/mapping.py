"""WatchOut's detection result copied into K1's types.

``EventsService.detect`` returns the rows, the parameters at each step and the
compiler's plan. This module copies them field by
field. The parameters as the contract writes them
(``inf``, ``<=``) and the plan's aliases as row keys (``M1.st``).
"""

from collections.abc import Mapping
from typing import Any, cast

from iseql.plan import (
    BranchPlan,
    ColumnPlan,
    CompiledPlan,
    ConditionPlan,
    IntervalPlan,
    OperatorPlan,
    ParamPlan,
    SetNode,
)
from service.events_service import DetectedRow as WatchOutRow
from service.events_service import DetectionResult, ResolvedParams
from service.events_service import Witness as WatchOutWitness

from xai.contract.model import TimeUnit
from xai.k1_harvester.ports import (
    Branch,
    BranchCondition,
    BranchInterval,
    DetectedRow,
    DetectionRecord,
    EngineError,
    Extent,
    IntervalTable,
    ParamName,
    ParamsSnapshot,
    ParamValue,
    ProjectedField,
    ResolvedOperator,
    ResolvedParam,
    ResultColumn,
    RuleLayout,
    RuleSnapshot,
    SelectionAlternative,
    SetOperationLayout,
    Witness,
    WitnessArg,
    WitnessInterval,
)

UNBOUNDED = ("inf", "∞")
STRICTNESS = ("<", "<=", ">", ">=")
_STRICTNESS_PARAMS = ("zeta", "eta")


def to_record(result: DetectionResult, rule: RuleSnapshot, requested: ParamsSnapshot) -> DetectionRecord:
    """The detection in K1's types; ``requested`` are the parameters K1 asked for."""
    plan = result.plan
    params = to_params(result.params, requested)
    return DetectionRecord(
        rule=rule,
        analysis_id=result.analysis_id,
        layout=to_layout(plan),
        operators={b.name: tuple(to_operator(o, result.params) for o in b.operators) for b in plan.branches},
        params=params,
        text=plan.text,
        rows=tuple(to_row(row) for row in result.rows),
    )


# --------------------------------------------------------------------------- layout


def to_layout(plan: CompiledPlan) -> RuleLayout:
    if plan.form not in ("F1", "F2", "F3"):
        raise EngineError(f"the plan of form {plan.form} has no layout")
    return RuleLayout(
        form=plan.form,
        branches=tuple(to_branch(b) for b in plan.branches),
        set_operation=None if plan.set_tree is None else to_set_operation(plan.set_tree),
        multiset=plan.form == "F2" and plan.set_tree is not None,
        columns=None if plan.columns is None else tuple(to_column(c) for c in plan.columns),
        columns_problem=plan.columns_problem,
        extent=alias_extent(plan.extent.start, plan.extent.end),
    )


def to_branch(branch: BranchPlan) -> Branch:
    return Branch(
        name=branch.name,
        side=branch.side,
        intervals=tuple(to_interval(i) for i in branch.intervals),
        conditions=tuple(to_condition(c) for c in branch.conditions),
        projection=tuple(f.field for f in branch.projection),
        projection_pointer=branch.projection_pointer,
        projection_text=branch.projection_text,
        fields=tuple(
            ProjectedField(field=f.field, kind=f.kind, arg_class=f.arg_class) for f in branch.projection
        ),
        extent=alias_extent(branch.extent.start, branch.extent.end),
    )


def to_interval(interval: IntervalPlan) -> BranchInterval:
    return BranchInterval(
        index=interval.index,
        alias=interval.alias,
        modality=interval.modality,
        selection=tuple(
            SelectionAlternative(
                predicates=tuple(s.predicates),
                arg_classes={str(position): tuple(classes) for position, classes in s.arg_classes},
            )
            for s in interval.selection
        ),
        text=interval.text,
    )


def to_condition(condition: ConditionPlan) -> BranchCondition:
    return BranchCondition(
        index=condition.index,
        left=condition.left,
        op=condition.op,
        right=condition.right,
        duration_value=condition.value,
        duration_unit=condition.domain,
        text=condition.text,
    )


def to_set_operation(node: SetNode) -> SetOperationLayout:
    return SetOperationLayout(
        op=node.op,
        pointer=node.pointer,
        children=tuple(c if isinstance(c, str) else to_set_operation(c) for c in node.children),
    )


def to_column(column: ColumnPlan) -> ResultColumn:
    return ResultColumn(
        label=column.label, kind=column.kind, fields=dict(column.fields), arg_class=column.arg_class
    )


def alias_extent(start: str | None, end: str | None) -> Extent:
    """The row keys of the start and end of the intervals that open and close the event."""
    return Extent(
        start_seconds=f"{start}.st" if start else None,
        end_seconds=f"{end}.et" if end else None,
        start_frames=f"{start}.sf" if start else None,
        end_frames=f"{end}.ef" if end else None,
    )


# --------------------------------------------------------------------------- operators


def to_operator(operator: OperatorPlan, resolved: ResolvedParams) -> ResolvedOperator:
    return ResolvedOperator(
        name=operator.operator,
        resolution=operator.chosen_by,
        resolution_detail=operator.detail,
        override_index=operator.override_index,
        delta_map_key=operator.delta_map_key,
        compare_domain=operator.domain,
        params=tuple(to_param(p, operator.domain, resolved) for p in operator.params),
        text=operator.text,
    )


def to_param(param: ParamPlan, domain: TimeUnit, resolved: ResolvedParams) -> ResolvedParam:
    """A parameter as written (named key, literal, template or engine default) and as in the SQL."""
    strictness = param.name in _STRICTNESS_PARAMS
    key = str(param.authored) if param.origin == "named_key" else None
    unit: TimeUnit | None
    if key is not None:
        written, unit = resolved.written[key], (None if strictness else _unit(resolved.unit))
    elif param.origin == "literal":
        written = param.resolved if param.authored is None else param.authored
        unit = None if strictness else domain
    elif param.origin == "template_geometry":
        written, unit = param.resolved, domain
    else:
        written, unit = param.resolved, (None if strictness else domain)
    return ResolvedParam(
        name=cast(ParamName, param.name),
        origin=param.origin,
        key=key,
        value=written_value(param.name, written),
        unit=unit,
        engine_value="inf" if param.in_sql is None else written_value(param.name, param.in_sql),
        pointer=param.pointer,
    )


def written_value(name: str, value: Any) -> ParamValue:
    """A parameter as the contract writes it: unbounded as ``inf`` (``0`` for ρ, ``<=`` for ζ, η)."""
    if value is None or value in UNBOUNDED:
        return "inf" if name in ("delta", "epsilon") else (0 if name == "rho" else "<=")
    if isinstance(value, bool):
        raise EngineError(f"parameter {name} has a boolean value")
    if isinstance(value, int | float):
        return value
    text = str(value)
    if text in STRICTNESS:
        return text
    try:
        return int(text)
    except ValueError:
        try:
            return float(text)
        except ValueError:
            raise EngineError(f"parameter {name} has the value {text!r}") from None


# --------------------------------------------------------------------------- parameters and rows


def to_params(resolved: ResolvedParams, requested: ParamsSnapshot) -> ParamsSnapshot:
    """The parameters as WatchOut used them, with the origin K1 asked for."""
    if resolved.origin == "rule_defaults":
        return ParamsSnapshot(
            origin="rule_defaults",
            unit=_unit(resolved.unit),
            values=param_values(resolved.written),
            rule_defaults={ref: param_values(values) for ref, values in resolved.rule_defaults.items()},
            provider=dict(resolved.provided_by),
        )
    return ParamsSnapshot(
        origin=requested.origin,
        unit=_unit(resolved.unit),
        values=param_values(resolved.written),
        analysis_id=requested.analysis_id,
    )


def param_values(values: Mapping[Any, Any]) -> dict[str, ParamValue]:
    """Numbers and texts only: WatchOut keeps other values but never uses them as parameters."""
    return {
        str(k): v for k, v in values.items() if isinstance(v, int | float | str) and not isinstance(v, bool)
    }


def to_row(row: WatchOutRow) -> DetectedRow:
    if row.witnesses is None:
        raise EngineError("the detection ran without lineage")
    return DetectedRow(
        values=dict(row.values), gui_values=dict(row.gui), witnesses=to_witnesses(row.witnesses)
    )


def to_witnesses(witnesses: tuple[WatchOutWitness, ...]) -> tuple[Witness, ...]:
    return tuple(
        Witness(
            branch=w.branch,
            intervals=tuple(
                WitnessInterval(
                    alias=i.alias,
                    table=cast(IntervalTable, i.table),
                    row_id=int(i.id),
                    args=tuple(
                        WitnessArg(position=a.position, class_id=a.class_id, class_name=a.class_name)
                        for a in i.args
                    ),
                )
                for i in w.intervals
            ),
        )
        for w in witnesses
    )


def _unit(value: str) -> TimeUnit:
    # detect_event converts only when the unit is "seconds"; anything else is used as frames.
    return "seconds" if value == "seconds" else "frames"
