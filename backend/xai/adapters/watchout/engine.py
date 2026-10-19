"""WatchOut's ISEQL+ engine

Every function here calls WatchOut's own code (compiler, helpers, detection) so K1
reads the rule as the engine executes it and never evaluates it with code of its
own. Several of these WatchOut functions are private: if WatchOut
changes them, a conformance test of this package fails, not the core.
"""

import json
import logging
import sqlite3
from collections.abc import Mapping, Sequence
from typing import Any, cast

from iseql.compiler import (
    _OPERATOR_FULL_PARAMS,
    _STRICTNESS_OPS,
    ModelValidationError,
    _canonical_schema,
    _default_projection,
    _delta_entry,
    _domain_cols,
    _field_kind,
    _group_cross_conditions,
    _group_intervals,
    _group_model,
    _interval_arg_class,
    _normalized_model,
    _render_operand,
    _render_operator,
    _render_projection,
    _render_selection,
    _resolve,
    _side_cross_conditions,
    _side_intervals,
    _slot_bounds,
    render_iseql,
)
from iseql.helpers import OPERATOR_HELPERS, Interval, Predicate, apply_manual_override, detect_operator
from service.events_service import EventSpec
from service.impl.analysis_service_impl import _format_time, _projection_extent_aliases
from service.impl.event_registry_service_impl import EventRegistryServiceImpl
from service.impl.events_service_impl import (
    _multimodal_labels,
    _resolve_deltas,
    _result_column_labels,
    run_sql_detection,
)

from xai.contract.ids import RowValue
from xai.contract.model import TimeUnit
from xai.k1_harvester.ports import (
    AnalysisSnapshot,
    Branch,
    BranchCondition,
    BranchInterval,
    DetectedRow,
    Detection,
    DetectionNotPossible,
    EngineError,
    Extent,
    ModelForm,
    ParamName,
    ParamOrigin,
    ParamsMissing,
    ParamsSnapshot,
    ParamValue,
    ResolvedOperator,
    ResolvedParam,
    ResultColumn,
    RuleLayout,
    RuleSnapshot,
    SelectionAlternative,
    SetOperationLayout,
    SideColumns,
    SideField,
)

_LOG = logging.getLogger(__name__)

Model = dict[str, Any]
_UNBOUNDED = ("inf", "∞")


# --------------------------------------------------------------------------- layout


def rule_layout(rule: RuleSnapshot, form: ModelForm) -> RuleLayout:
    """The branches, set operations and result columns of a rule, as compiled."""
    model = _model(rule)
    set_operation: SetOperationLayout | None = None
    multiset = False
    if form == "F2":
        branches: list[Branch] = []
        tree = _expression_layout(model, model["set_expression"], "/set_expression", branches)
        if isinstance(tree, SetOperationLayout):
            set_operation, multiset = tree, True
    elif form == "F3":
        branches = [_side_branch(model, side) for side in ("left", "right")]
        set_operation = SetOperationLayout(
            op=model.get("set_operator") or "\\", pointer="/set_operator", children=("left", "right")
        )
    else:
        branches = [_flat_branch(model)]
    columns, problem = _columns(model, form, multiset, branches)
    return RuleLayout(
        form=form,
        branches=tuple(branches),
        set_operation=set_operation,
        multiset=multiset,
        columns=columns,
        columns_problem=problem,
        extent=_extent(rule),
        side_columns=_side_columns(model, branches) if form == "F3" and columns is None else {},
    )


def _expression_layout(
    model: Model, node: Model, pointer: str, branches: list[Branch]
) -> SetOperationLayout | str:
    if "group" in node:
        branch = _group_branch(model, node, pointer)
        branches.append(branch)
        return branch.name
    children = tuple(
        _expression_layout(model, child, f"{pointer}/children/{i}", branches)
        for i, child in enumerate(node["children"])
    )
    return SetOperationLayout(op=node["op"], pointer=pointer, children=children)


def _group_branch(model: Model, leaf: Model, pointer: str) -> Branch:
    group = leaf.get("group")
    branch_model, intervals = _group_operand(model, leaf)
    indices = [i for i, iv in enumerate(model["intervals"]) if (iv.get("group") or None) == group]
    conditions = []
    for index, condition in enumerate(model.get("cross_conditions") or []):
        rebased = _group_cross_conditions(dict(model, cross_conditions=[condition]), group)
        if rebased:
            conditions.append((index, rebased[0]))
    projection_pointer = f"{pointer}/projection" if leaf.get("projection") else pointer
    return _branch(group or "main", group, branch_model, intervals, indices, conditions, projection_pointer)


def _side_branch(model: Model, side: str) -> Branch:
    side_model, intervals, offset = _side_operand(model, side)
    indices = [i for i, iv in enumerate(model["intervals"]) if iv.get("set_side") == side]
    conditions = []
    for index, condition in enumerate(model.get("cross_conditions") or []):
        rebased = _side_cross_conditions(dict(model, cross_conditions=[condition]), len(intervals), offset)
        if rebased:
            conditions.append((index, rebased[0]))
    projection_pointer = f"/{side}_projection" if model.get(f"{side}_projection") else "/intervals"
    return _branch(side, side, side_model, intervals, indices, conditions, projection_pointer)


def _group_operand(model: Model, leaf: Model) -> tuple[Model, list[Model]]:
    """The model slice the compiler renders for a group of ``set_expression``, and its intervals."""
    group = leaf.get("group")
    intervals: list[Model] = _group_intervals(model, group)
    sliced: Model = _group_model(model, group, intervals, leaf.get("projection"))
    return sliced, intervals


def _side_operand(model: Model, side: str) -> tuple[Model, list[Model], int]:
    """The operand model ``_render_set_operation`` renders for a set side, its intervals and their offset."""
    intervals: list[Model] = _side_intervals(model, side)
    offset = 0 if side == "left" else len(_side_intervals(model, "left"))
    operand = dict(
        model,
        intervals=intervals,
        set_side=None,
        custom_projection=model.get(f"{side}_projection"),
        cross_conditions=_side_cross_conditions(model, len(intervals), offset),
    )
    return operand, intervals, offset


def _flat_branch(model: Model) -> Branch:
    intervals = model["intervals"]
    conditions = list(enumerate(model.get("cross_conditions") or []))
    projection_pointer = "/custom_projection" if model.get("custom_projection") else "/intervals"
    return _branch(
        "main", None, model, intervals, list(range(len(intervals))), conditions, projection_pointer
    )


def _branch(
    name: str,
    side: str | None,
    branch_model: Model,
    intervals: Sequence[Model],
    indices: Sequence[int],
    conditions: Sequence[tuple[int, Model]],
    projection_pointer: str,
) -> Branch:
    projection = branch_model.get("custom_projection") or _default_projection(branch_model, list(intervals))
    return Branch(
        name=name,
        side=side,
        intervals=tuple(
            BranchInterval(
                index=index,
                alias=f"M{k + 1}",
                selection=_selection(iv),
                text=_render_selection(iv, f"M{k + 1}"),
            )
            for k, (index, iv) in enumerate(zip(indices, intervals, strict=True))
        ),
        conditions=tuple(
            _condition(index, c, _condition_text(branch_model, intervals, side, c)) for index, c in conditions
        ),
        projection=tuple(projection),
        projection_pointer=projection_pointer,
        projection_text=f"π_{{{_render_projection(branch_model, list(intervals))}}}",
    )


def _selection(interval: Model) -> tuple[SelectionAlternative, ...]:
    """The alternatives of a selection, read as ``_render_selection`` reads them."""
    pred = interval["pred"]
    selection = interval.get("selection")
    if selection:
        alternatives = selection.get("branches") or [
            {"preds": selection.get("preds") or [pred["name"]], "args": selection.get("args") or {}}
        ]
    else:
        arguments = pred.get("arguments") or []
        alternatives = [{"preds": [pred["name"]], "args": {str(k): [a] for k, a in enumerate(arguments, 1)}}]
    return tuple(
        SelectionAlternative(
            predicates=tuple(str(p) for p in alternative.get("preds") or []),
            arg_classes={
                str(slot): tuple(str(c) for c in classes)
                for slot, classes in sorted(
                    (alternative.get("args") or {}).items(), key=lambda kv: int(kv[0])
                )
                if classes
            },
        )
        for alternative in alternatives
    )


_FRAME_ATTRIBUTES = ("sf", "start", "StartFrame", "ef", "end", "EndFrame")
_TIME_ATTRIBUTES = ("st", "StartTime", "et", "EndTime")


def _condition(index: int, condition: Model, text: str) -> BranchCondition:
    """A rebased cross-condition, with the attribute domains of ``_attr_col``."""
    left = f"{condition['left_alias']}.{condition['left_attr']}"
    right = f"{condition['right_alias']}.{condition['right_attr']}"
    if condition.get("type") != "duration":
        return BranchCondition(
            index=index,
            left=left,
            op=str(condition["op"]),
            right=right,
            duration_value=None,
            duration_unit=None,
            text=text,
        )
    attributes = {condition["left_attr"], condition["right_attr"]}
    unit: TimeUnit
    if attributes <= set(_TIME_ATTRIBUTES):
        unit = "seconds"
    elif attributes <= set(_FRAME_ATTRIBUTES):
        unit = "frames"
    else:
        # The SQL would subtract a frame from a second: the duration has no unit.
        raise EngineError(f"duration condition {index} mixes frames and seconds: {left} − {right}")
    value = condition.get("value")
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise EngineError(f"duration condition {index} has the value {value!r}")
    return BranchCondition(
        index=index,
        left=left,
        op=str(condition["op"]),
        right=right,
        duration_value=value,
        duration_unit=unit,
        text=text,
    )


def _condition_text(
    branch_model: Model, intervals: Sequence[Model], side: str | None, condition: Model
) -> str:
    """The renderer's text of one cross-condition: the σ line of a one-condition operand."""
    text: str = _render_operand(dict(branch_model, cross_conditions=[condition]), list(intervals), side, 0)
    line = text.split("\n")[1].strip()
    if not (line.startswith("σ_{") and line.endswith("} (")):
        raise EngineError(f"unexpected rendering of a cross-condition: {line!r}")
    return line[len("σ_{") : -len("} (")]


def _columns(
    model: Model, form: ModelForm, multiset: bool, branches: Sequence[Branch]
) -> tuple[tuple[ResultColumn, ...] | None, str | None]:
    """How the columns of a result row map to the branches' projected fields."""
    if multiset:
        labels: list[str] = _multimodal_labels(model)
        kinds: list[str] = _canonical_schema([list(b.projection) for b in branches])
        if len(labels) != len(kinds):
            return None, "WatchOut's column labels do not match the aligned columns"
        columns = []
        for label, kind in zip(labels, kinds, strict=True):
            fields = {}
            for b in branches:
                field = next((f for f in b.projection if _field_kind(f) == kind), None)
                if field is not None:
                    fields[b.name] = field
            arg_class = label[len("M1_") :] if kind.startswith("arg") and label.startswith("M1_") else None
            columns.append(ResultColumn(label=label, kind=kind, fields=fields, arg_class=arg_class))
        return tuple(columns), None
    if form == "F3":
        left, right = branches
        problem = _positional_problem(left.projection, right.projection)
        if problem:
            return None, problem
    labels_or_none: list[str] | None = _result_column_labels(model)
    reference = branches[0]
    reference_intervals = [model["intervals"][bi.index] for bi in reference.intervals]
    if labels_or_none is None or len(labels_or_none) != len(reference.projection):
        return None, "WatchOut does not name the result columns of this rule"
    if len(set(labels_or_none)) != len(labels_or_none):
        return None, "two result columns have the same label"
    by_alias = dict(zip((bi.alias for bi in reference.intervals), reference_intervals, strict=True))
    columns = []
    for position, (label, field) in enumerate(zip(labels_or_none, reference.projection, strict=True)):
        kind = _field_kind(field)
        fields = {b.name: b.projection[position] for b in branches}
        columns.append(
            ResultColumn(label=label, kind=kind, fields=fields, arg_class=_arg_class(field, kind, by_alias))
        )
    return tuple(columns), None


def _arg_class(field: str, kind: str, by_alias: Mapping[str, Model]) -> str | None:
    """The class WatchOut names an argument column after (``_interval_arg_class``)."""
    alias = field.split(".", 1)[0]
    if not (kind.startswith("arg") and kind[3:].isdigit() and alias in by_alias):
        return None
    return str(_interval_arg_class(dict(by_alias[alias]), int(kind[3:])))


def _positional_problem(left: Sequence[str], right: Sequence[str]) -> str | None:
    """F3 pads the shorter side with NULLs: each position must hold the same kind on both sides."""
    for position in range(max(len(left), len(right))):
        lk = _field_kind(left[position]) if position < len(left) else "NULL"
        rk = _field_kind(right[position]) if position < len(right) else "NULL"
        if lk != rk:
            return (
                f"set_side rule: result column {position + 1} is {lk} in the left side "
                f"and {rk} in the right side (columns are aligned by position)"
            )
    return None


def _side_columns(model: Model, branches: Sequence[Branch]) -> dict[str, SideColumns]:
    """F3: the fields each side puts in the result columns, in order (``_pad_fields``)."""
    sides = {}
    for branch in branches:
        by_alias = {bi.alias: model["intervals"][bi.index] for bi in branch.intervals}
        fields = []
        for field in branch.projection:
            kind = _field_kind(field)
            fields.append(SideField(field=field, kind=kind, arg_class=_arg_class(field, kind, by_alias)))
        sides[branch.name] = SideColumns(fields=tuple(fields), extent=_projection_extent(branch.projection))
    return sides


def _projection_extent(projection: Sequence[str]) -> Extent:
    """The start and end fields of a projection, read as ``_projection_extent_aliases`` reads them.

    WatchOut applies that function to the left side only (to the whole rule); here
    it is applied to each side's own projection: the first interval with a start,
    the last with an end.
    """
    start = end = None
    for field in projection:
        alias, _, attr = field.partition(".")
        if alias.startswith("M") and attr in ("sf", "st", "ef", "et"):
            if start is None and attr in ("sf", "st"):
                start = alias
            if attr in ("ef", "et"):
                end = alias
    return _alias_extent(start, end)


def _extent(rule: RuleSnapshot) -> Extent:
    start, end = _projection_extent_aliases(rule.event_type, rule.condition, [_spec(rule)])
    return _alias_extent(start, end)


def _alias_extent(start: str | None, end: str | None) -> Extent:
    """The start and end fields of the intervals that open and close the event."""
    return Extent(
        start_seconds=f"{start}.st" if start else None,
        end_seconds=f"{end}.et" if end else None,
        start_frames=f"{start}.sf" if start else None,
        end_frames=f"{end}.ef" if end else None,
    )


# --------------------------------------------------------------------------- operators


def resolve_operators(
    conn: sqlite3.Connection,
    rule: RuleSnapshot,
    form: ModelForm,
    branch: Branch,
    params: ParamsSnapshot,
    fps: int | None,
) -> tuple[ResolvedOperator, ...]:
    """The operators between consecutive intervals of a branch, in order."""
    branch_model = _branch_model(_model(rule), form, branch)
    deltas = compiler_deltas(conn, rule, params, fps)
    return tuple(
        _resolve_operator(rule, branch, branch_model, pair_index, params, fps, deltas)
        for pair_index in range(len(branch.intervals) - 1)
    )


def _resolve_operator(
    rule: RuleSnapshot,
    branch: Branch,
    branch_model: Model,
    pair_index: int,
    params: ParamsSnapshot,
    fps: int | None,
    deltas: Mapping[str, Any],
) -> ResolvedOperator:
    """The operator between intervals ``pair_index`` and ``pair_index + 1`` of a branch.

    Same steps as ``_operators_between_slots``: ``detect_operator`` on the template
    geometry, ``operator_overrides``, defaults from the geometry, then the
    ``delta_map`` entry resolved with the detection's parameters; the helpers
    finally apply ``int()`` to δ, ε and ρ.
    """
    intervals = branch_model["intervals"]
    side = branch.side
    r = Interval(Predicate("slot", []), *_slot_bounds(intervals[pair_index]))
    s = Interval(Predicate("slot", []), *_slot_bounds(intervals[pair_index + 1]))
    result = detect_operator(r, s)
    op: str = result.operator
    resolution = "geometry"
    override_index = None
    detail = f"detect_operator on template ts/te [{r.Ts},{r.Te}] and [{s.Ts},{s.Te}]"
    for index, override in enumerate(branch_model.get("operator_overrides") or []):
        if override.get("side") in (None, "none", side) and override.get("pair_idx") == pair_index + 1:
            op = override.get("operator", op)
            resolution, override_index = "override", index
            detail = (
                f"operator_overrides[{index}]: side {override.get('side')}, "
                f"pair_idx {pair_index + 1}, operator {op}"
            )
            if op in ("SP", "EF"):
                result = apply_manual_override(op, r, s)
    if op not in OPERATOR_HELPERS:
        raise EngineError(f"{rule.ref}: no operator between intervals {pair_index + 1} and {pair_index + 2}")
    _, threshold_names = OPERATOR_HELPERS[op]
    time_domain = _domain_cols(branch_model) == ("st", "et")
    domain: TimeUnit = "seconds" if time_domain else "frames"
    entry: Mapping[str, Any] = _delta_entry(branch_model, pair_index, side)
    entry_key = _delta_map_key(branch_model, pair_index, side)
    resolved = []
    for name in _OPERATOR_FULL_PARAMS[op]:
        if name in entry:
            resolved.append(
                _entry_param(name, entry[name], deltas, params, domain, f"/delta_map/{entry_key}/{name}")
            )
        elif name in ("delta", "epsilon") and name in threshold_names:
            geometry: float | None = result.delta if name == "delta" else result.epsilon
            if geometry is not None and time_domain and isinstance(fps, int | float):
                geometry = geometry / fps
            resolved.append(_param(name, "template_geometry", None, geometry, domain, geometry, None))
        elif name in ("zeta", "eta"):
            resolved.append(_param(name, "engine_default", None, "<=", None, "<=", None))
        else:
            resolved.append(_param(name, "engine_default", None, 0, domain, 0, None))
    text: str = _render_operator(branch_model, intervals, pair_index, side, written_lits(params))
    return ResolvedOperator(
        name=op,
        resolution=resolution,  # type: ignore[arg-type]
        resolution_detail=detail,
        override_index=override_index,
        delta_map_key=entry_key,
        compare_domain=domain,
        params=tuple(resolved),
        text=text,
    )


def _entry_param(
    name: str, raw: Any, deltas: Mapping[str, Any], params: ParamsSnapshot, domain: TimeUnit, pointer: str
) -> ResolvedParam:
    value = _resolve(raw, dict(deltas))
    if name in ("zeta", "eta") and value not in _STRICTNESS_OPS:
        value = "<="
    elif name == "rho" and value is None:
        value = 0
    if isinstance(raw, str) and raw in deltas:
        written = params.values[raw]
        unit = None if name in ("zeta", "eta") else params.unit
        return _param(name, "named_key", raw, written, unit, value, pointer)
    unit = None if name in ("zeta", "eta") else domain
    return _param(name, "literal", None, value if raw is None else raw, unit, value, pointer)


def _param(
    name: str,
    origin: ParamOrigin,
    key: str | None,
    written: Any,
    unit: TimeUnit | None,
    compiler_value: Any,
    pointer: str | None,
) -> ResolvedParam:
    return ResolvedParam(
        name=cast(ParamName, name),
        origin=origin,
        key=key,
        value=_written_value(name, written),
        unit=unit,
        engine_value=_helper_value(name, compiler_value),
        pointer=pointer,
    )


def _helper_value(name: str, value: Any) -> ParamValue:
    """The value the SQL helper writes: ``int()`` of δ, ε and ρ; None means unbounded."""
    if name in ("zeta", "eta"):
        return str(value)
    if name == "rho":
        return int(value or 0)
    return "inf" if value is None else int(value)


def _written_value(name: str, value: Any) -> ParamValue:
    """A parameter as written, with ``∞``/null shown as ``inf``."""
    if value is None or value in _UNBOUNDED:
        return "inf" if name in ("delta", "epsilon") else (0 if name == "rho" else "<=")
    if isinstance(value, bool):
        raise EngineError(f"parameter {name} has a boolean value")
    if isinstance(value, int | float):
        return value
    text = str(value)
    if text in _STRICTNESS_OPS:
        return text
    try:
        return int(text)
    except ValueError:
        try:
            return float(text)
        except ValueError:
            raise EngineError(f"parameter {name} has the value {text!r}") from None


def _delta_map_key(branch_model: Model, pair_index: int, side: str | None) -> str | None:
    """The ``delta_map`` key ``_delta_entry`` reads."""
    delta_map = branch_model.get("delta_map") or {}
    if side is not None and f"{side}.{pair_index}" in delta_map:
        return f"{side}.{pair_index}"
    return str(pair_index) if str(pair_index) in delta_map else None


def written_lits(params: ParamsSnapshot) -> dict[str, Any]:
    """Named keys -> values for the renderer; unbounded values become None (shown as ∞)."""
    return {key: (None if value in _UNBOUNDED else value) for key, value in params.values.items()}


def converted_deltas(params: ParamsSnapshot, fps: int | None) -> dict[str, Any]:
    """The parameters as ``detect_event`` passes them on: seconds converted to frames."""
    deltas: dict[str, Any] = dict(params.values)
    if params.unit != "seconds":
        return deltas
    numeric = [k for k, v in deltas.items() if isinstance(v, int | float) and not isinstance(v, bool)]
    if numeric and not fps:
        raise DetectionNotPossible(
            "the parameters are in seconds and Analyses.SamplingRate is missing or zero: "
            "WatchOut's detect_event cannot convert them either"
        )
    return {k: (round(v * fps) if k in numeric and fps else v) for k, v in deltas.items()}


def compiler_deltas(
    conn: sqlite3.Connection, rule: RuleSnapshot, params: ParamsSnapshot, fps: int | None
) -> dict[str, Any]:
    """The parameters as the compiler receives them (``_resolve_deltas``)."""
    deltas = converted_deltas(params, fps)
    missing = sorted(EventRegistryServiceImpl().required_deltas(conn, rule.condition) - set(deltas))
    if missing:
        raise ParamsMissing(missing)
    try:
        resolved: dict[str, Any] = _resolve_deltas(rule.condition, deltas, conn)
    except ValueError as exc:
        raise EngineError(str(exc)) from exc
    return resolved


def render_rule(rule: RuleSnapshot, params: ParamsSnapshot) -> str:
    text: str = render_iseql(dict(rule.model), written_lits(params))
    return text


# --------------------------------------------------------------------------- detection


def detect(
    conn: sqlite3.Connection, rule: RuleSnapshot, analysis: AnalysisSnapshot, params: ParamsSnapshot
) -> Detection:
    """The rows of ``detect_event`` without its write: ``run_sql_detection`` on the read-only connection."""
    fps = analysis.sampling_rate
    compiler_deltas(conn, rule, params, fps)  # same checks detect_event meets first
    deltas = converted_deltas(params, fps)
    rows: list[dict[str, RowValue]] = []
    try:
        lines = list(
            run_sql_detection(
                conn,
                rule.event_type,
                deltas,
                analysis_id=analysis.analysis_id,
                condition=rule.condition,
                log=_LOG.debug,
                fps=cast(int, fps),  # detect_event passes run.sampling_rate as it is
            )
        )
    except ValueError as exc:
        raise EngineError(str(exc)) from exc
    for line in lines:
        if line.startswith("__RESULT__:"):
            try:
                rows = json.loads(line[len("__RESULT__:") :])
            except json.JSONDecodeError as exc:
                raise EngineError(f"{rule.ref}: the engine returned rows that are not JSON") from exc
        elif line.startswith("ERROR"):
            raise EngineError(f"{rule.ref}: {line}")
    start, end = _projection_extent_aliases(rule.event_type, rule.condition, [_spec(rule)])
    return Detection(
        rule_ref=rule.ref,
        analysis_id=analysis.analysis_id,
        rows=tuple(DetectedRow(values=row, gui_values=gui_row(row, start, end, fps)) for row in rows),
    )


def gui_row(
    row: Mapping[str, RowValue], start: str | None, end: str | None, fps: int | None
) -> dict[str, RowValue]:
    """The row as ``detect_event`` returns it to the GUI: frames from seconds, times formatted."""
    out = dict(row)
    st_key = f"{start}.st" if start else None
    et_key = f"{end}.et" if end else None
    for time_key, frame_key in ((st_key, f"{start}.sf"), (et_key, f"{end}.ef")):
        if time_key is None or time_key not in out:
            continue
        value = out[time_key]
        if frame_key not in out and isinstance(value, int | float) and not isinstance(value, bool):
            if not fps:
                raise DetectionNotPossible("Analyses.SamplingRate is missing: WatchOut cannot show this row")
            out[frame_key] = round(value * fps)
        if value is not None and not isinstance(value, str):
            out[time_key] = _format_time(value)
    return out


# --------------------------------------------------------------------------- helpers


def _model(rule: RuleSnapshot) -> Model:
    model: Model = _normalized_model(dict(rule.model))
    return model


def _spec(rule: RuleSnapshot) -> EventSpec:
    return EventSpec(id=rule.event_type, condition=rule.condition, model_json=json.dumps(dict(rule.model)))


def _branch_model(model: Model, form: ModelForm, branch: Branch) -> Model:
    """The model slice the compiler renders for a branch."""
    if form == "F2":
        return _group_operand(model, _find_leaf(model["set_expression"], branch.side))[0]
    if form == "F3":
        return _side_operand(model, branch.name)[0]
    return model


def _find_leaf(node: Model, group: str | None) -> Model:
    if "group" in node:
        if node.get("group") == group:
            return node
        raise KeyError(group)
    for child in node.get("children") or []:
        try:
            return _find_leaf(child, group)
        except KeyError:
            continue
    raise KeyError(group)


__all__ = [
    "ModelValidationError",
    "compiler_deltas",
    "converted_deltas",
    "detect",
    "gui_row",
    "render_rule",
    "resolve_operators",
    "rule_layout",
    "written_lits",
]
