"""ISEQL compiler: compiles a Gea-style ISEQL event model into executable SQL.

The model JSON is the same shape the ISEQL-GUI builder consumes (intervals with
predicates, temporal operators between consecutive intervals, cross-conditions,
projections, groups, query-refs, set operations). This emitter maps it onto our
pipeline tables (VisualPerInterval/VisualParticipant/AudioPerInterval) through
the iseql.helpers temporal operators, producing one SQL query per event.

Compilation happens at detection time (compile-at-detect): operator thresholds
are resolved from the per-detect ``deltas`` dict via an optional model
``delta_map``, so the frontend's per-detect delta editing keeps working.

The interval model and temporal-operator detection are app-owned (adapted from
the ISEQL-GUI core); no vendored code is imported. Predicates and participant
classes match stored values literally: variants are written as ``∨`` ORs in the
query itself, and a predicate is treated as audio iff it is in the configured
``audio_predicates`` (from ``audio_taxonomy.classes``).
"""
from __future__ import annotations

import json
import re
import sqlite3
from typing import Optional

from iseql.helpers import (
    ALL_PARAMS,
    OPERATOR_HELPERS,
    apply_manual_override,
    detect_operator,
    Interval,
    Predicate,
    sql_threshold,
)
from iseql.plan import (
    BranchPlan,
    ColumnPlan,
    CompiledEvent,
    CompiledPlan,
    ConditionPlan,
    ExtentPlan,
    FieldPlan,
    IntervalPlan,
    OperatorPlan,
    ParamPlan,
    SelectionPlan,
    SetNode,
)
from utils.api_logger import get_logger

log = get_logger(__name__)

_VISUAL_SOURCE = "visual"
_AUDIO_SOURCE = "audio"

_STRICTNESS_OPS = ("<", "<=", ">", ">=")


class ModelValidationError(ValueError):
    pass


# ---------------------------------------------------------------------------
# model parsing / validation
# ---------------------------------------------------------------------------

def _load_model(model_json: str | dict) -> dict:
    if isinstance(model_json, str):
        try:
            model = json.loads(model_json)
        except json.JSONDecodeError as e:
            raise ModelValidationError(f"invalid model JSON: {e}")
    elif isinstance(model_json, dict):
        model = model_json
    else:
        raise ModelValidationError("model_json must be a dict or JSON string")
    if not isinstance(model, dict):
        raise ModelValidationError("model must be a JSON object")
    return model


def validate_model(model_json: str | dict) -> dict:
    """Validate/normalize a model; raises ModelValidationError on structural errors."""
    model = _load_model(model_json)
    intervals = model.get("intervals")
    if not isinstance(intervals, list) or not intervals:
        raise ModelValidationError("model.intervals must be a non-empty list")
    for i, iv in enumerate(intervals):
        if not isinstance(iv, dict):
            raise ModelValidationError(f"interval[{i}] must be an object")
        pred = iv.get("pred")
        if not isinstance(pred, dict) or not pred.get("name"):
            raise ModelValidationError(f"interval[{i}].pred.name is required")
        for key in ("ts", "te"):
            if key in iv and not isinstance(iv[key], int):
                raise ModelValidationError(f"interval[{i}].{key} must be an integer")
    cc = model.get("cross_conditions", [])
    if not isinstance(cc, list):
        raise ModelValidationError("model.cross_conditions must be a list")
    for c in cc:
        for key in ("left_alias", "left_attr", "op", "right_alias", "right_attr"):
            if not isinstance(c, dict) or key not in c:
                raise ModelValidationError(f"cross-condition missing '{key}': {c}")
    set_operator = model.get("set_operator")
    if set_operator is not None and set_operator not in ("\\", "∪", "∩"):
        raise ModelValidationError(f"unsupported set_operator '{set_operator}'")
    has_set_side = any(iv.get("set_side") for iv in intervals)
    if set_operator and not has_set_side:
        raise ModelValidationError("set_operator present but no interval has set_side")
    se = model.get("set_expression")
    if se is not None:
        _validate_expression(se)
        if has_set_side:
            raise ModelValidationError("model mixes set_expression with set_side intervals")
    for i, iv in enumerate(intervals):
        g = iv.get("group")
        if g is not None and not isinstance(g, str):
            raise ModelValidationError(f"interval[{i}].group must be a string or null")
    return model


def _validate_expression(node, depth: int = 0) -> None:
    """Validate a set_expression tree node (leaf references a group name)."""
    if depth > 64:
        raise ModelValidationError("set_expression is nested too deeply")
    if not isinstance(node, dict):
        raise ModelValidationError("set_expression nodes must be objects")
    if "group" in node:
        g = node.get("group")
        if g is not None and not isinstance(g, str):
            raise ModelValidationError("set_expression group must be a string or null")
        proj = node.get("projection")
        if proj is not None and (
                not isinstance(proj, list)
                or any(not isinstance(f, str) for f in proj)):
            raise ModelValidationError("set_expression projection must be a list of strings")
        return
    op = node.get("op")
    if op not in ("\\", "∪", "∩"):
        raise ModelValidationError(f"unsupported set_expression op '{op}'")
    children = node.get("children")
    if not isinstance(children, list) or not children:
        raise ModelValidationError("set_expression internal node requires a non-empty 'children' list")
    for c in children:
        _validate_expression(c, depth + 1)


def _normalized_model(model: dict) -> dict:
    out = dict(model)
    out.setdefault("cross_conditions", [])
    out.setdefault("operator_overrides", [])
    out.setdefault("group_cross_conditions", {})
    out.setdefault("custom_projection", None)
    out.setdefault("left_projection", None)
    out.setdefault("right_projection", None)
    out.setdefault("set_operator", None)
    out.setdefault("set_expression", None)
    out.setdefault("delta_map", {})
    return out


# ---------------------------------------------------------------------------
# predicate -> CTE
# ---------------------------------------------------------------------------

def _predicate_source(pred_name: str, audio_predicates: set[str]) -> str:
    return _AUDIO_SOURCE if pred_name in audio_predicates else _VISUAL_SOURCE


def _selection_source(preds: list[str], audio_predicates: set[str]) -> str:
    """Source table for an interval selection that may name several predicates."""
    audio = [p for p in preds if p in audio_predicates]
    visual = [p for p in preds if p not in audio_predicates]
    if audio and visual:
        raise ModelValidationError(
            f"interval mixes audio and visual predicates: {', '.join(preds)}"
        )
    return _AUDIO_SOURCE if audio else _VISUAL_SOURCE


def _class_filter_multi(alias: str, classes: list[str]) -> str:
    """Participant class condition: the arg labels match stored Class values literally."""
    values = list(dict.fromkeys(classes))
    if len(values) == 1:
        return f"{alias}.Class = '{values[0]}'"
    quoted = ", ".join(f"'{v}'" for v in values)
    return f"{alias}.Class IN ({quoted})"


def _relation_values(preds: list[str], source: str) -> str:
    """Predicate condition: pred names match stored RelationType/AudioClass literally."""
    column = "AudioClass" if source == _AUDIO_SOURCE else "RelationType"
    values = list(dict.fromkeys(preds))
    if len(values) == 1:
        return f"{column} = '{values[0]}'"
    quoted = ", ".join(f"'{v}'" for v in values)
    return f"{column} IN ({quoted})"


def _temporal_selects(prefix: str, temporal: set[str], fps: int | str) -> list[str]:
    """SQL column expressions for the temporal columns a query actually uses.

    ``temporal`` is the set of referenced columns (sf/ef/st/et). Frame columns
    are raw ``StartFrame AS sf`` / ``EndFrame AS ef``; time columns are the
    fps-divided casts ``CAST(StartFrame AS REAL)/{fps} AS st`` etc., where fps
    is only known after video analysis (preview: ``__fps__`` placeholder).
    """
    _fps = fps if isinstance(fps, str) else max(int(fps or 1), 1)
    exprs = {
        "sf": f"{prefix}StartFrame AS sf",
        "ef": f"{prefix}EndFrame AS ef",
        "st": f"CAST({prefix}StartFrame AS REAL)/{_fps} AS st",
        "et": f"CAST({prefix}EndFrame AS REAL)/{_fps} AS et",
    }
    return [exprs[c] for c in ("sf", "ef", "st", "et") if c in temporal]


def _lineage_selects(source: str, positions) -> list[str]:
    """Columns a lineage query adds to a predicate: the id of the interval
    row and, for a visual interval, the class of each participant."""
    if source == _AUDIO_SOURCE:
        return ["API.AudioIntervalID AS __rid"]
    return ["VPI.RelationID AS __rid"] + [f"VP_{k}.Class AS __arg{k}_class" for k in positions]


def _predicate_cte(alias: str, iv: dict, analysis_id: str,
                   audio_predicates: set[str], fps: int | str = 1,
                   temporal: set[str] = ("sf", "ef"), lineage: bool = False) -> str:
    """Render one predicate interval as a CTE.

    ``lineage`` adds the columns of ``_lineage_selects`` (lineage query only).

    The CTE exposes only the temporal columns the query references
    (``temporal``): frame domain ``sf``/``ef`` are raw frame columns, time
    domain ``st``/``et`` are fps-divided (``st = StartFrame/fps``).

    Intervals authored from ISEQL text carry a ``selection`` ({preds, args}, or
    {branches: [{preds, args}...]} for OR selections; each branch keeps its own
    pred + argument combination). Intervals from the model seed / GUI fall back
    to ``pred.name`` + arguments (a single conjunction via join class filters).
    """
    pred = iv["pred"]
    a = f"AND AnalysisID = '{analysis_id}'"
    _fps = fps if isinstance(fps, str) else max(int(fps or 1), 1)
    selection = iv.get("selection")
    if selection:
        branches = selection.get("branches") or [
            {"preds": list(selection.get("preds") or [pred["name"]]),
             "args": {str(k): list(v) for k, v in (selection.get("args") or {}).items()}}
        ]
        all_preds = [p for b in branches for p in (b.get("preds") or [])]
        source = _selection_source(all_preds, audio_predicates)
        slots: set[int] = set()
        for b in branches:
            for k in (b.get("args") or {}):
                slots.add(int(k))
        if source == _AUDIO_SOURCE:
            selects: list[str] = []
            maxarg = max(slots) if slots else 0
            for k in range(1, maxarg + 1):
                selects.append(f"NULL AS arg{k}")
            selects += _temporal_selects("", temporal, fps)
            if lineage:
                selects += _lineage_selects(source, ())
            conds = [_relation_values(b["preds"], source) for b in branches]
            where = "(" + " OR ".join(f"({c})" for c in conds) + ")"
            return (
                f"{alias} AS (\n"
                f"    SELECT {', '.join(selects)}\n"
                f"    FROM AudioPerInterval API\n"
                f"    WHERE {where} AND Confidence >= 0.0 {a}\n"
                f")"
            )
        selects: list[str] = []
        for k in sorted(slots):
            selects.append(f"VP_{k}.ClassID AS arg{k}")
        selects += _temporal_selects("VPI.", temporal, fps)
        if lineage:
            selects += _lineage_selects(source, sorted(slots))
        joins = [f"JOIN VisualParticipant VP_{k} ON VPI.RelationID = VP_{k}.RelationID"
                 for k in sorted(slots)]
        branch_sqls = []
        for b in branches:
            conds = [_relation_values(b["preds"], source)]
            for k in sorted(slots):
                classes = (b.get("args") or {}).get(str(k))
                if classes:
                    conds.append(_class_filter_multi(f"VP_{k}", classes))
            branch_sqls.append("(" + " AND ".join(conds) + ")")
        where = "(" + " OR ".join(branch_sqls) + ")"
        joins_sql = "\n".join("    " + j for j in joins)
        return (
            f"{alias} AS (\n"
            f"    SELECT {', '.join(selects)}\n"
            f"    FROM VisualPerInterval VPI\n"
            f"{joins_sql}\n"
            f"    WHERE {where} {a}\n"
            f")"
        )

    # Non-selection path (model seed / GUI): a single conjunction expressed via
    # participant-join class filters.
    pred_name = pred["name"]
    source = _predicate_source(pred_name, audio_predicates)
    args = {k: [v] for k, v in enumerate(pred.get("arguments", []), start=1)}

    if source == _AUDIO_SOURCE:
        selects: list[str] = []
        for k in range(1, len(args) + 1):
            selects.append(f"NULL AS arg{k}")
        selects += _temporal_selects("", temporal, fps)
        if lineage:
            selects += _lineage_selects(source, ())
        return (
            f"{alias} AS (\n"
            f"    SELECT {', '.join(selects)}\n"
            f"    FROM AudioPerInterval API\n"
            f"    WHERE {_relation_values([pred_name], source)} AND Confidence >= 0.0 {a}\n"
            f")"
        )

    selects: list[str] = []
    joins = []
    for k in sorted(args):
        j_alias = f"VP_{k}"
        selects.append(f"{j_alias}.ClassID AS arg{k}")
        joins.append(
            f"JOIN VisualParticipant {j_alias} ON VPI.RelationID = {j_alias}.RelationID "
            f"AND {_class_filter_multi(j_alias, args[k])}"
        )
    selects += _temporal_selects("VPI.", temporal, fps)
    if lineage:
        selects += _lineage_selects(source, sorted(args))
    joins_sql = "\n".join("    " + j for j in joins)
    return (
        f"{alias} AS (\n"
        f"    SELECT {', '.join(selects)}\n"
        f"    FROM VisualPerInterval VPI\n"
        f"{joins_sql}\n"
        f"    WHERE {_relation_values([pred_name], source)} {a}\n"
        f")"
    )


# ---------------------------------------------------------------------------
# operator resolution
# ---------------------------------------------------------------------------

def _resolve(value, deltas: dict):
    """Resolve a param spec: string keys look up the resolved per-detect value."""
    if isinstance(value, str) and deltas is not None and value in deltas:
        return deltas[value]
    return value


def _operator_kwargs(helper, params: dict) -> dict:
    """Pass only the keyword params the helper actually accepts."""
    import inspect
    sig = inspect.signature(helper)
    return {name: params[name] for name in sig.parameters if name in params}


_OP_TRANSLATION = {"≠": "!=", "≤": "<=", "≥": ">=", "⩽": "<=", "⩾": ">="}


def _alias_inner_fields(fields: list[str]) -> list[str]:
    """Alias inner chain projection fields so a group CTE exposes safe columns
    (M1.arg1 -> M1_arg1). Fields already aliased are left unchanged."""
    out = []
    for f in fields:
        if " AS " in f:
            out.append(f)
        elif "." in f:
            base, col = f.split(".", 1)
            out.append(f"{f} AS {base}_{col}")
        else:
            out.append(f)
    return out


def _proj_col(ref: str, col: str | None, name: str) -> str:
    if col:
        return f"{ref}.{col}_{name}"
    if name in ("sf", "start"):
        return f'{ref}.sf AS "{ref}.sf"'
    if name in ("ef", "end"):
        return f'{ref}.ef AS "{ref}.ef"'
    if name in ("st",):
        return f'{ref}.st AS "{ref}.st"'
    if name in ("et",):
        return f'{ref}.et AS "{ref}.et"'
    return f"{ref}.{name}"


def _attr_col(alias: str, attr: str, alias_map: dict[str, tuple[str, str | None]]) -> str:
    ref, col = alias_map.get(alias, (alias, None))
    if col:
        return f"{ref}.{col}_{attr}"
    if attr in ("sf", "start", "StartFrame"):
        return f"{ref}.sf"
    if attr in ("ef", "end", "EndFrame"):
        return f"{ref}.ef"
    if attr in ("st", "StartTime"):
        return f"{ref}.st"
    if attr in ("et", "EndTime"):
        return f"{ref}.et"
    return f"{ref}.{attr}"


def _cross_condition_sql(c: dict, alias_map: dict[str, tuple[str, str | None]]) -> str:
    if c.get("type") == "duration":
        start = _attr_col(c["right_alias"], c["right_attr"], alias_map)
        end = _attr_col(c["left_alias"], c["left_attr"], alias_map)
        op = _OP_TRANSLATION.get(c["op"], c["op"])
        return f"({end} - {start}) {op} {c['value']}"
    left = _attr_col(c["left_alias"], c["left_attr"], alias_map)
    right = _attr_col(c["right_alias"], c["right_attr"], alias_map)
    op = _OP_TRANSLATION.get(c["op"], c["op"])
    return f"({left} {op} {right})"


def _unit_domain(model: dict) -> tuple[str, str]:
    """Temporal domain implied by the model's ``delta_unit`` (no authored projection).

    ``seconds`` -> (``st``, ``et``); otherwise (frames) -> (``sf``, ``ef``).
    """
    return ("st", "et") if model.get("delta_unit") == "seconds" else ("sf", "ef")


def _domain_cols(model: dict) -> tuple[str, str]:
    """Which temporal column domain the event uses.

    When an authored projection (``custom_projection`` / ``left_projection`` /
    ``right_projection``) is present, its attributes decide the domain
    (``sf``/``ef`` => frames, ``st``/``et`` => seconds; mixing raises). Otherwise
    the model's ``delta_unit`` decides, so a set-less flat model respects the
    Seconds/Frames toggle exactly like a single-set model.
    """
    fields = (model.get("custom_projection") or
              model.get("left_projection") or
              model.get("right_projection") or [])
    if not fields:
        return _unit_domain(model)
    frame = time_ = False
    for f in fields:
        attr = f.split(".")[-1]
        if attr in ("sf", "ef"):
            frame = True
        elif attr in ("st", "et"):
            time_ = True
    if frame and time_:
        raise ModelValidationError(
            "query mixes frame (sf/ef) and time (st/et) attributes; "
            "use one domain consistently"
        )
    return ("st", "et") if time_ else ("sf", "ef")


def _needed_temporal(model: dict) -> frozenset[str]:
    """The set of temporal columns (sf/ef/st/et) the query actually references.

    Collects from the operator domain (``_domain_cols``), the projection fields,
    the default projection (event extent uses ``sf``/``ef`` when no projection is
    authored), and every cross-condition attribute. Only these columns are
    emitted by the predicate CTEs, so ``__fps__`` casts appear exactly when the
    query operates in the time domain.
    """
    needed = set(_domain_cols(model))
    for key in ("custom_projection", "left_projection", "right_projection"):
        for f in model.get(key) or []:
            needed.update(_projection_temporal_attrs(f))
    if not (model.get("custom_projection") or
            model.get("left_projection") or
            model.get("right_projection")):
        needed.update(_unit_domain(model))
    for c in model.get("cross_conditions") or []:
        needed.update(_condition_temporal_attrs(c))
    for ccs in (model.get("group_cross_conditions") or {}).values():
        for c in ccs or []:
            needed.update(_condition_temporal_attrs(c))
    return frozenset(needed)


def _projection_temporal_attrs(field: str) -> set[str]:
    attr = field.split(".")[-1]
    return {attr} if attr in ("sf", "ef", "st", "et") else set()


def _condition_temporal_attrs(c: dict) -> set[str]:
    return {attr for attr in (c.get("left_attr"), c.get("right_attr"))
            if attr in ("sf", "ef", "st", "et")}


# ---------------------------------------------------------------------------
# projection
# ---------------------------------------------------------------------------

def _interval_arg_class(iv: dict, k: int) -> str:
    """Participant class for arg slot ``k`` of an interval (e.g. 'person')."""
    sel = iv.get("selection")
    if sel:
        args = sel.get("args")
        if args is None and sel.get("branches"):
            vals = []
            for b in sel["branches"]:
                v = (b.get("args") or {}).get(str(k))
                if v:
                    vals.extend(v)
            if vals:
                return str(vals[0])
        elif args:
            vals = args.get(str(k))
            if vals:
                return str(vals[0])
    pred = iv.get("pred") or {}
    arguments = pred.get("arguments") or []
    if 1 <= k <= len(arguments):
        return str(arguments[k - 1])
    return f"arg{k}"


_ALIAS_RE = re.compile(r"^M(\d+)$")


def _alias_index(alias: str) -> int | None:
    m = _ALIAS_RE.match(alias)
    return int(m.group(1)) - 1 if m else None


def _classify_projection_fields(fields: list[str], ivs: list[dict]) -> list[str]:
    """Alias each projected arg field with its participant class.

    ``M1.arg1`` (class person) becomes ``M1.arg1 AS M1_person``. Duplicate
    classes on the same interval get a position suffix (M1_person, M1_person2).
    sf/ef and already-aliased fields are left unchanged.
    """
    counts: dict[tuple[str, str], int] = {}
    out = []
    for f in fields:
        parts = f.split(".")
        if len(parts) == 2 and parts[0].startswith("M"):
            attr = parts[1]
            m = re.match(r"^arg(\d+)$", attr)
            if m:
                i = _alias_index(parts[0])
                if i is not None and i < len(ivs):
                    cls = _interval_arg_class(ivs[i], int(m.group(1)))
                    key = (parts[0], cls)
                    counts[key] = counts.get(key, 0) + 1
                    n = counts[key]
                    suffix = "" if n == 1 else str(n)
                    out.append(f"{f} AS {parts[0]}_{cls}{suffix}")
                    continue
        out.append(f)
    return out


def _translate_field(field: str) -> str:
    """Translate a GUI projection field (M1.arg1, M2.sf, Ref.M1.arg1, ...) to SQL.

    sf/ef map to the CTE frame aliases ``sf``/``ef`` (the projection stays
    ISEQL-consistent: ``M1.sf`` -> ``M1.sf``); argN pass through unchanged.
    """
    return field


def _default_projection(model: dict, ivs: list[dict],
                        alias_map: dict[str, tuple[str, str | None]] = None) -> list[str]:
    """Default flat-chain projection: each interval's argN then its temporal
    start/end in the model's unit domain (st/et for seconds, sf/ef for frames).

    This mirrors the projection a single-set leaf produces (``autoProjection``),
    so a set-less flat model renders exactly like a one-set model.
    """
    alias_map = alias_map or {f"M{i + 1}": (f"M{i + 1}", None) for i in range(len(ivs))}
    cst, ced = _unit_domain(model)
    fields: list[str] = []
    for i, iv in enumerate(ivs):
        alias = f"M{i + 1}"
        ref, col = alias_map.get(alias, (alias, None))
        if iv.get("query_ref"):
            fields.append(f"{ref}.{cst}")
            fields.append(f"{ref}.{ced}")
            continue
        for k in range(1, len(iv["pred"].get("arguments", [])) + 1):
            fields.append(_proj_col(ref, col, f"arg{k}"))
        fields.append(f"{ref}.{cst}")
        fields.append(f"{ref}.{ced}")
    return fields


# ---------------------------------------------------------------------------
# chain rendering (flat + groups + query-ref)
# ---------------------------------------------------------------------------

def _slot_bounds(iv: dict) -> tuple[int, int]:
    return int(iv.get("ts", 0)), int(iv.get("te", 0))


def _slot_span(slot_ivs: list[dict]) -> tuple[int, int]:
    ts = min(_slot_bounds(iv)[0] for iv in slot_ivs)
    te = max(_slot_bounds(iv)[1] for iv in slot_ivs)
    return ts, te


def _slots(ivs: list[dict]) -> list[list[dict]]:
    """Partition intervals into slots: single intervals or contiguous group runs."""
    slots: list[list[dict]] = []
    i = 0
    n = len(ivs)
    while i < n:
        gid = ivs[i].get("group_id")
        if gid:
            j = i
            while j < n and ivs[j].get("group_id") == gid:
                j += 1
            slots.append(ivs[i:j])
            i = j
        else:
            slots.append([ivs[i]])
            i += 1
    return slots


def _delta_map_key(model: dict, pair_idx: int, side: str | None = None) -> str | None:
    """The delta_map key of an operator pair. Set-operation sides may key entries
    as 'left.<i>' / 'right.<i>' (falls back to '<i>'); None if no entry."""
    dm = model.get("delta_map", {})
    if side is not None and f"{side}.{pair_idx}" in dm:
        return f"{side}.{pair_idx}"
    return str(pair_idx) if str(pair_idx) in dm else None


def _delta_entry(model: dict, pair_idx: int, side: str | None = None) -> dict:
    """Resolve a delta_map entry"""
    key = _delta_map_key(model, pair_idx, side)
    return (model.get("delta_map", {})[key] or {}) if key is not None else {}


def _choose_operator(model: dict, r_bounds: tuple[int, int], s_bounds: tuple[int, int],
                     pair_idx: int, side: str | None):
    """The operator between two template spans: ``detect_operator`` on the
    geometry, then the matching ``operator_overrides`` entries.

    ``pair_idx`` is the 0-based interval pair index the overrides refer to.
    """
    r = Interval(Predicate("slot", []), *r_bounds)
    s = Interval(Predicate("slot", []), *s_bounds)
    res = detect_operator(r, s)
    op = res.operator
    override_index = None
    for i, ov in enumerate(model.get("operator_overrides", [])):
        if ov.get("side") in (None, "none", side) and ov.get("pair_idx") == pair_idx + 1:
            op = ov.get("operator", op)
            override_index = i
            if op in ("SP", "EF"):
                res = apply_manual_override(op, r, s)
    return r, s, res, op, override_index


def _resolve_operators(model: dict, deltas: dict,
                       slot_bounds: list[tuple[int, int]],
                       slot_indices: list[int],
                       side: str | None = None,
                       fps: int | str = 1,
                       render=None) -> list[OperatorPlan]:
    """Resolve the operators between consecutive slots, using each slot's span.

    Operator, every threshold and its origin are fixed here once. SQL
    condition is emitted from the same values.
    ``render(pair_idx)`` gives the ISEQL text of the operator
    """
    plans: list[OperatorPlan] = []
    for k in range(len(slot_bounds) - 1):
        # map a slot pair back to the underlying interval pair index for overrides
        pair_idx = slot_indices[k]
        r, s, res, op, override_index = _choose_operator(
            model, slot_bounds[k], slot_bounds[k + 1], pair_idx, side)
        if op == "UNKNOWN":
            raise ModelValidationError(
                f"cannot determine operator between slots {k + 1} and {k + 2}; "
                "add an operator_override"
            )
        helper, param_names = OPERATOR_HELPERS[op]
        cols = _domain_cols(model)
        params: dict[str, object] = {}
        origin: dict[str, str] = {}
        time_domain = (cols == ("st", "et"))
        for p in ("delta", "epsilon"):
            if p in param_names:
                # res.delta/res.epsilon are in FRAME units from the synthesized
                # interval spans; for the time domain convert to seconds.
                val = res.delta if p == "delta" else res.epsilon
                if val is not None and time_domain and isinstance(fps, (int, float)):
                    val = val / fps
                params[p] = val
                origin[p] = "template_geometry"
        params["zeta"] = "<="
        params["eta"] = "<="
        params["rho"] = 0
        for p in ("zeta", "eta", "rho"):
            origin[p] = "engine_default"
        entry_key = _delta_map_key(model, pair_idx, side)
        entry = _delta_entry(model, pair_idx, side)
        for p in ALL_PARAMS:
            if p in entry:
                raw = entry[p]
                # Authored numeric thresholds are in the domain's own unit
                # (frames for sf/ef, seconds for st/et); named keys resolve
                # per-detect after (None in preview -> default below).
                val = _resolve(raw, deltas)
                if p in ("zeta", "eta") and val not in _STRICTNESS_OPS:
                    val = "<="
                elif p == "rho" and val is None:
                    val = 0
                params[p] = val
                named = isinstance(raw, str) and deltas is not None and raw in deltas
                origin[p] = "named_key" if named else "literal"
        a1, a2 = f"M{k + 1}", f"M{k + 2}"
        kwargs = _operator_kwargs(helper, params)
        sql = helper(a1, a2, cols=cols, **kwargs)
        if override_index is None:
            detail = f"detect_operator on template ts/te [{r.Ts},{r.Te}] and [{s.Ts},{s.Te}]"
        else:
            ov = model["operator_overrides"][override_index]
            detail = (f"operator_overrides[{override_index}]: side {ov.get('side')}, "
                      f"pair_idx {pair_idx + 1}, operator {op}")
        plans.append(OperatorPlan(
            pair=pair_idx,
            left=a1,
            right=a2,
            operator=op,
            chosen_by="geometry" if override_index is None else "override",
            override_index=override_index,
            detail=detail,
            delta_map_key=entry_key,
            domain="seconds" if time_domain else "frames",
            params=tuple(
                ParamPlan(
                    name=p,
                    origin=origin[p],
                    authored=entry[p] if p in entry else None,
                    resolved=value,
                    in_sql=sql_threshold(p, value),
                    pointer=f"/delta_map/{entry_key}/{p}" if p in entry else None,
                )
                for p, value in kwargs.items()
            ),
            sql=sql,
            text=render(pair_idx) if render is not None else "",
        ))
    return plans


def _operators_between_slots(model: dict, ivs: list[dict], deltas: dict,
                             slot_bounds: list[tuple[int, int]],
                             slot_indices: list[int],
                             side: str | None = None,
                             fps: int | str = 1) -> list[str]:
    """Operators between consecutive slots, using each slot's span."""
    return [p.sql for p in _resolve_operators(model, deltas, slot_bounds, slot_indices, side, fps)]


def _render_chain(model: dict, ivs: list[dict], analysis_id: str, deltas: dict,
                  alias_start: int = 1, side: str | None = None,
                  fps: int | str = 1, audio_predicates: set[str] | None = None,
                  lineage: bool = False
                  ) -> tuple[list[str], list[str], list[str]]:
    """Render a chain of intervals -> (ctes, projection_fields, where_conditions).

    Aliases continue from ``alias_start`` (1-based) so set-op sides don't clash.
    ``side`` prefixes delta_map lookups for set-operation operands.
    ``lineage`` adds row ids and participant classes to the predicate data.
    """
    slots = _slots(ivs)
    ctes: list[str] = []
    conditions: list[str] = []
    global_index = alias_start - 1
    slot_bounds: list[tuple[int, int]] = []
    slot_indices: list[int] = []
    alias_map: dict[str, tuple[str, str | None]] = {}
    temporal = _needed_temporal(model)

    for slot in slots:
        first = global_index
        if len(slot) == 1 and not slot[0].get("group_id"):
            iv = slot[0]
            alias = f"M{global_index + 1}"
            global_index += 1
            if iv.get("query_ref"):
                ref = _normalized_model(iv["query_ref"])
                ref_name = ref.get("event_name") or alias
                body = _render_flat_body(ref, ref["intervals"], analysis_id, deltas, fps=fps,
                                         audio_predicates=audio_predicates)
                ctes.append(f"{ref_name} AS ({body})")
                alias_map[alias] = (ref_name, None)
                ts, te = _slot_bounds(iv)
                slot_bounds.append((ts, te))
                slot_indices.append(first)
                continue
            ctes.append(_predicate_cte(alias, iv, analysis_id, audio_predicates, fps, temporal,
                                       lineage))
            alias_map[alias] = (alias, None)
            ts, te = _slot_bounds(iv)
            slot_bounds.append((ts, te))
            slot_indices.append(first)
        else:
            # group: nested subquery over the run; expose inner aliases as safe
            # columns (M1_arg1, M1_sf, ...) on the group CTE.
            run = slot
            gid = run[0].get("group_id")
            group_ivs = [dict(iv, group_id=None) for iv in run]
            inner_ctes, inner_fields, inner_conds = _render_chain(
                model, group_ivs, analysis_id, deltas, alias_start=global_index + 1,
                fps=fps, audio_predicates=audio_predicates)
            body = _build_select(inner_ctes, _alias_inner_fields(inner_fields), inner_conds)
            gccs = model.get("group_cross_conditions", {}).get(gid, [])
            if gccs:
                cc_cond = " AND ".join(_cross_condition_sql(c) for c in gccs)
                body = f"SELECT * FROM ({body}) WHERE {cc_cond}"
            alias = f"M{global_index + 1}"
            ctes.append(f"{alias} AS ({body})")
            for j, _iv in enumerate(run):
                inner_alias = f"M{first + j + 1}"
                alias_map[inner_alias] = (alias, inner_alias)
            ts, te = _slot_span(run)
            slot_bounds.append((ts, te))
            slot_indices.append(first)
            global_index += 1

    # operators between slots
    if len(slot_bounds) > 1:
        conditions.extend(_operators_between_slots(
            model, ivs, deltas, slot_bounds, slot_indices, side, fps))

    # cross-conditions (outer)
    for c in model.get("cross_conditions", []):
        conditions.append(_cross_condition_sql(c, alias_map))

    # projection
    projection = model.get("custom_projection")
    if projection:
        fields = [_translate_field(f) for f in projection]
    else:
        fields = _default_projection(model, ivs, alias_map)

    return ctes, fields, conditions


def _render_flat_body(model: dict, ivs: list[dict], analysis_id: str, deltas: dict,
                      side: str | None = None, fps: int | str = 1,
                      audio_predicates: set[str] | None = None) -> str:
    ctes, fields, conditions = _render_chain(model, ivs, analysis_id, deltas, side=side, fps=fps,
                                             audio_predicates=audio_predicates)
    return _build_inline(ctes, fields, conditions)


def _cte_body(cte: str) -> str:
    """Extract the SELECT body from a 'alias AS (SELECT ...)' CTE string."""
    prefix = " AS (\n"
    start = cte.index(prefix) + len(prefix)
    end = cte.rindex("\n)")
    return cte[start:end]


def _build_select(ctes: list[str], fields: list[str], conditions: list[str]) -> str:
    alias_names = [c.split(" AS (", 1)[0].strip() for c in ctes]
    from_clause = ", ".join(alias_names)
    where = ""
    if conditions:
        where = "\nWHERE " + "\n  AND ".join(conditions)
    cte_block = ",\n".join(ctes)
    if cte_block:
        return f"WITH {cte_block}\nSELECT {', '.join(fields)}\nFROM {from_clause}{where}"
    return f"SELECT {', '.join(fields)}\nFROM {from_clause}{where}"


# ---------------------------------------------------------------------------
# set operations (Left op Right)
# ---------------------------------------------------------------------------

def _side_intervals(model: dict, side: str) -> list[dict]:
    return [iv for iv in model["intervals"] if iv.get("set_side") == side]


def _build_inline(ctes: list[str], fields: list[str], conditions: list[str]) -> str:
    alias_names = [c.split(" AS (", 1)[0].strip() for c in ctes]
    from_clause = ", ".join(f"({_cte_body(c)}) {name}" for c, name in zip(ctes, alias_names))
    where = "\nWHERE " + "\n  AND ".join(conditions) if conditions else ""
    return f"SELECT {', '.join(fields)}\nFROM {from_clause}{where}"


def _render_inline_body(model: dict, ivs: list[dict], analysis_id: str, deltas: dict,
                        side: str | None = None, fps: int | str = 1,
                        audio_predicates: set[str] | None = None) -> str:
    """Render a chain as a plain SELECT with inline subqueries (no WITH).

    Set-operation operands need this: SQLite rejects '(... WITH ...) UNION (...)'.
    """
    ctes, fields, conditions = _render_chain(model, ivs, analysis_id, deltas, side=side, fps=fps,
                                             audio_predicates=audio_predicates)
    return _build_inline(ctes, fields, conditions)


def _pad_fields(fields: list[str], n: int) -> list[str]:
    if len(fields) >= n:
        return fields
    return fields + [f"NULL AS __p{i}" for i in range(1, n - len(fields) + 1)]


def _render_set_operation(model: dict, analysis_id: str, deltas: dict, fps: int | str = 1,
                          audio_predicates: set[str] | None = None) -> str:
    set_op = model.get("set_operator") or "\\"
    left = _side_intervals(model, "left")
    right = _side_intervals(model, "right")
    if not left:
        raise ModelValidationError("set operation requires a 'left' side interval")
    if not right:
        raise ModelValidationError("set operation requires a 'right' side interval")

    left_model = _side_model(model, "left")
    right_model = _side_model(model, "right")
    left_ctes, left_fields, left_conds = _render_chain(
        left_model, left, analysis_id, deltas, side="left", fps=fps,
        audio_predicates=audio_predicates)
    right_ctes, right_fields, right_conds = _render_chain(
        right_model, right, analysis_id, deltas, side="right", fps=fps,
        audio_predicates=audio_predicates)
    n = max(len(left_fields), len(right_fields))
    left_body = _build_inline(left_ctes, _pad_fields(left_fields, n), left_conds)
    right_body = _build_inline(right_ctes, _pad_fields(right_fields, n), right_conds)
    sql_keyword = {"\\": "EXCEPT", "∪": "UNION", "∩": "INTERSECT"}[set_op]
    return f"{left_body}\n{sql_keyword}\n{right_body}"


def _side_model(model: dict, side: str) -> dict:
    """The operand model of a set side: intervals, projection and cross-conditions rebased on M1..Mn."""
    ivs = _side_intervals(model, side)
    offset = 0 if side == "left" else len(_side_intervals(model, "left"))
    return dict(model, intervals=ivs, set_side=None,
                custom_projection=model.get(f"{side}_projection"),
                cross_conditions=_side_cross_conditions(model, len(ivs), offset))


def _side_cross_conditions(model: dict, n_intervals: int, offset: int = 0) -> list[dict]:
    """Cross-conditions whose aliases are both within this set-op side.

    ``offset`` is the number of intervals on earlier set-op sides; the side's
    intervals sit at global aliases M{1+offset}..M{n_intervals+offset} and are
    rebound to local M1..Mn in the operand model.
    """
    out = []
    for c in model.get("cross_conditions", []):
        la, ra = c["left_alias"], c["right_alias"]
        if not (isinstance(la, str) and isinstance(ra, str)
                and la.startswith("M") and la[1:].isdigit()
                and ra.startswith("M") and ra[1:].isdigit()):
            continue
        ln, rn = int(la[1:]), int(ra[1:])
        if offset < ln <= offset + n_intervals and offset < rn <= offset + n_intervals:
            out.append({**c, "left_alias": f"M{ln - offset}", "right_alias": f"M{rn - offset}"})
    return out


# ---------------------------------------------------------------------------
# set expressions (named groups + full set-operation trees)
# ---------------------------------------------------------------------------

_SET_SQL = {"\\": "EXCEPT", "∪": "UNION", "∩": "INTERSECT"}


def _group_intervals(model: dict, group: str | None) -> list[dict]:
    """Intervals that belong to ``group`` (None = ungrouped), in authored order."""
    return [iv for iv in model["intervals"] if (iv.get("group") or None) == group]


def _group_field_count(ivs: list[dict], projection: list[str] | None = None) -> int:
    """Output column count of a group's projection (default StartFrame/EndFrame
    plus each interval's argN/sf/ef, or the authored projection)."""
    if projection:
        return len(projection)
    n = 2
    for iv in ivs:
        if iv.get("query_ref"):
            n += 2
        else:
            n += len((iv.get("pred") or {}).get("arguments", [])) + 2
    return n


def _group_cross_conditions(model: dict, group: str | None) -> list[dict]:
    """Cross-conditions whose two aliases both sit inside ``group``, rebound to
    the group's local M1..Mn aliases."""
    gidx = [i + 1 for i, iv in enumerate(model["intervals"])
            if (iv.get("group") or None) == group]
    gset = set(gidx)
    local = {g: k + 1 for k, g in enumerate(sorted(gidx))}
    out = []
    for c in model.get("cross_conditions", []):
        la, ra = c.get("left_alias"), c.get("right_alias")
        if not (isinstance(la, str) and isinstance(ra, str)
                and la.startswith("M") and la[1:].isdigit()
                and ra.startswith("M") and ra[1:].isdigit()):
            continue
        ln, rn = int(la[1:]), int(ra[1:])
        if ln in gset and rn in gset:
            out.append({**c, "left_alias": f"M{local[ln]}", "right_alias": f"M{local[rn]}"})
    return out


def _group_model(model: dict, group: str | None, group_ivs: list[dict],
                 projection: list[str] | None = None) -> dict:
    """A per-group model slice: the group's intervals with rebased cross-conditions
    and no set-op metadata (delta_map stays shared so ``<group>.<pair_idx>`` keys
    resolve)."""
    return dict(
        model,
        intervals=group_ivs,
        set_side=None,
        set_operator=None,
        set_expression=None,
        custom_projection=projection,
        left_projection=None,
        right_projection=None,
        cross_conditions=_group_cross_conditions(model, group),
        group_cross_conditions={},
    )


def _render_group_body(model: dict, group: str | None, analysis_id: str, deltas: dict,
                       fps: int | str = 1,
                       audio_predicates: set[str] | None = None,
                       projection: list[str] | None = None) -> str:
    ivs = _group_intervals(model, group)
    if not ivs:
        raise ModelValidationError(f"set_expression references empty group {group!r}")
    gm = _group_model(model, group, ivs, projection)
    ctes, fields, conditions = _render_chain(
        gm, ivs, analysis_id, deltas, side=group, fps=fps,
        audio_predicates=audio_predicates)
    return _build_inline(ctes, fields, conditions)


def _expression_arity(node: dict, model: dict) -> int:
    """Maximum output column count across a set-expression subtree."""
    if "group" in node:
        return _group_field_count(_group_intervals(model, node["group"]),
                                  node.get("projection"))
    return max(_expression_arity(c, model) for c in node["children"])


def _field_kind(field: str) -> str:
    """Semantic column kind of a projection field: 'M1.arg1' -> 'arg1', 'M2.st' -> 'st'."""
    return field.rsplit(".", 1)[-1]


def _kind_sort_key(kind: str) -> tuple:
    m = re.match(r"^arg(\d+)$", kind)
    if m:
        return (0, int(m.group(1)))
    return (1, {"st": 0, "sf": 0, "et": 1, "ef": 1}.get(kind, 2), kind)


def _canonical_schema(leaf_fields: list[list[str]]) -> list[str]:
    """Union of field kinds across operands, in a stable order (args, then start, then end)."""
    kinds: list[str] = []
    seen: set[str] = set()
    for fields in leaf_fields:
        for f in fields:
            k = _field_kind(f)
            if k not in seen:
                seen.add(k)
                kinds.append(k)
    kinds.sort(key=_kind_sort_key)
    return kinds


def _align_fields(fields: list[str], schema: list[str]) -> list[str]:
    """Map an operand's fields onto the schema, NULL for missing kinds."""
    by_kind = {_field_kind(f): f for f in fields}
    return [by_kind.get(k, f"NULL AS {k}") for k in schema]


def _collect_leaf_fields(node: dict, model: dict, analysis_id: str, deltas: dict,
                         fps: int | str, audio_predicates: set[str]) -> list[list[str]]:
    """Projection fields of every leaf in a set-expression subtree (one list per leaf)."""
    if "group" in node:
        ivs = _group_intervals(model, node["group"])
        gm = _group_model(model, node["group"], ivs, node.get("projection"))
        _, fields, _ = _render_chain(gm, ivs, analysis_id, deltas, side=node["group"],
                                     fps=fps, audio_predicates=audio_predicates)
        return [fields]
    out: list[list[str]] = []
    for c in node.get("children", []):
        out.extend(_collect_leaf_fields(c, model, analysis_id, deltas, fps, audio_predicates))
    return out


def _render_expression(node: dict, model: dict, analysis_id: str, deltas: dict,
                       fps: int | str = 1,
                       audio_predicates: set[str] | None = None,
                       schema: list[str] | None = None) -> str:
    """Render a set_expression tree to SQL (leaves are group chains, internal
    nodes are UNION/EXCEPT/INTERSECT). Operands are aligned by field kind so
    heterogeneous projections (e.g. audio start/end vs visual arg/start/end)
    produce consistent, NULL-padded columns."""
    if "group" in node:
        ivs = _group_intervals(model, node["group"])
        if not ivs:
            raise ModelValidationError(
                f"set_expression references empty group {node['group']!r}")
        gm = _group_model(model, node["group"], ivs, node.get("projection"))
        ctes, fields, conditions = _render_chain(
            gm, ivs, analysis_id, deltas, side=node["group"], fps=fps,
            audio_predicates=audio_predicates)
        if schema is not None:
            fields = _align_fields(fields, schema)
        return _build_inline(ctes, fields, conditions)
    keyword = _SET_SQL[node["op"]]
    if schema is None:
        schema = _canonical_schema(_collect_leaf_fields(
            node, model, analysis_id, deltas, fps, audio_predicates))
    return f"\n{keyword}\n".join(
        _render_expression(c, model, analysis_id, deltas, fps=fps,
                           audio_predicates=audio_predicates, schema=schema)
        for c in node["children"]
    )


def _validate_predicates(model: dict, predicate_vocab: dict[str, list[list[str]]]) -> None:
    """Validate every predicate in a model against the configured vocabulary.

    ``predicate_vocab`` maps a predicate name to its argument slots (a list of
    lists of allowed classes; audio predicates have ``[]``). Raises
    ``ModelValidationError`` when a predicate is undefined or its arguments do
    not match its signature, so the editor can point the user at the mistake.
    """
    for iv in model["intervals"]:
        pred = iv.get("pred") or {}
        pred_name = pred.get("name")
        selection = iv.get("selection")

        if selection:
            branches = selection.get("branches") or [{
                "preds": list(selection.get("preds") or [pred_name]),
                "args": {str(k): list(v) for k, v in (selection.get("args") or {}).items()},
            }]
        else:
            branches = [{
                "preds": [pred_name],
                "args": {str(k + 1): [v] for k, v in enumerate(pred.get("arguments") or [])},
            }]

        for branch in branches:
            preds = [p for p in (branch.get("preds") or []) if p]
            for p in preds:
                if p not in predicate_vocab:
                    raise ModelValidationError(
                        f"predicate '{p}' is not defined; create it in Events Configuration"
                    )
            if len(preds) == 1:
                _validate_predicate_args(preds[0], predicate_vocab[preds[0]], branch.get("args") or {})


def _validate_predicate_args(name: str, slots: list[list[str]], args: dict[str, list[str]]) -> None:
    expected = ", ".join(" ∨ ".join(slot) for slot in slots)
    provided = sorted(int(k) for k in args if k and str(k).isdigit())
    if len(provided) != len(slots):
        raise ModelValidationError(
            f"predicate '{name}' expects {len(slots)} argument(s): {name}({expected}); "
            f"got {len(provided)}"
        )
    for idx in provided:
        allowed = slots[idx - 1]
        for cls in args[str(idx)]:
            if cls not in allowed:
                raise ModelValidationError(
                    f"predicate '{name}' arg{idx}='{cls}' is invalid; expected {name}({expected})"
                )


def _interval_pred_names(iv: dict) -> list[str]:
    pred = iv.get("pred") or {}
    sel = iv.get("selection")
    if sel:
        if sel.get("branches"):
            return [p for b in sel["branches"] for p in (b.get("preds") or []) if p]
        return [p for p in (sel.get("preds") or [pred.get("name")]) if p]
    name = pred.get("name")
    return [name] if name else []


def _interval_arg_count(iv: dict, predicate_vocab: dict[str, list[list[str]]]) -> int:
    preds = _interval_pred_names(iv)
    if not preds:
        return 0
    return max((len(predicate_vocab.get(p, [])) for p in preds), default=0)


def _validate_projection_fields(fields: list[str], ivs: list[dict],
                                predicate_vocab: dict[str, list[list[str]]]) -> None:
    n = len(ivs)
    for f in fields:
        parts = f.split(".")
        if len(parts) != 2:
            continue  # already-aliased or Ref.* fields
        alias, attr = parts[0], parts[1]
        idx = _alias_index(alias)
        if idx is None:
            continue
        if idx >= n:
            raise ModelValidationError(
                f"projection field '{f}' references interval {alias}, which does not exist"
            )
        if attr in ("sf", "ef", "st", "et"):
            continue
        m = re.match(r"^arg(\d+)$", attr)
        if not m:
            raise ModelValidationError(
                f"projection field '{f}' is invalid: unknown attribute '{attr}'"
            )
        k = int(m.group(1))
        if k > _interval_arg_count(ivs[idx], predicate_vocab):
            names = "/".join(_interval_pred_names(ivs[idx])) or "interval"
            raise ModelValidationError(
                f"projection field '{f}' is invalid: {names} has no arg{k}"
            )


def _validate_projection(model: dict, predicate_vocab: dict[str, list[list[str]]]) -> None:
    """Validate projection fields (M{n}.arg{k} / M{n}.sf/ef/st/et) against the model."""
    if model.get("custom_projection"):
        _validate_projection_fields(model["custom_projection"], model["intervals"], predicate_vocab)
    if model.get("left_projection"):
        left = [iv for iv in model["intervals"] if iv.get("set_side") == "left"]
        _validate_projection_fields(model["left_projection"], left, predicate_vocab)
    if model.get("right_projection"):
        right = [iv for iv in model["intervals"] if iv.get("set_side") == "right"]
        _validate_projection_fields(model["right_projection"], right, predicate_vocab)

    def walk(node: dict) -> None:
        if "group" in node:
            if node.get("projection"):
                _validate_projection_fields(
                    node["projection"], _group_intervals(model, node["group"]), predicate_vocab)
        else:
            for c in node.get("children", []):
                walk(c)

    if model.get("set_expression"):
        walk(model["set_expression"])


def _validate_cross_conditions(model: dict, predicate_vocab: dict[str, list[list[str]]]) -> None:
    """Validate cross-condition attribute references (M{n}.arg{k} / M{n}.sf/ef/st/et)."""
    n = len(model["intervals"])
    for cc in model.get("cross_conditions") or []:
        if not isinstance(cc, dict):
            continue
        for side in ("left", "right"):
            alias = cc.get(f"{side}_alias")
            attr = cc.get(f"{side}_attr")
            idx = _alias_index(alias) if isinstance(alias, str) else None
            if idx is None:
                continue
            if idx >= n:
                raise ModelValidationError(
                    f"cross-condition '{alias}.{attr}' references interval {alias}, which does not exist"
                )
            if attr in ("sf", "ef", "st", "et"):
                continue
            m = re.match(r"^arg(\d+)$", attr) if isinstance(attr, str) else None
            if not m:
                raise ModelValidationError(
                    f"cross-condition '{alias}.{attr}' is invalid: unknown attribute '{attr}'"
                )
            k = int(m.group(1))
            if k > _interval_arg_count(model["intervals"][idx], predicate_vocab):
                names = "/".join(_interval_pred_names(model["intervals"][idx])) or "interval"
                raise ModelValidationError(
                    f"cross-condition '{alias}.arg{k}' is invalid: {names} has no arg{k}"
                )


def _validate_predicate_modalities(model: dict, audio_predicates: set[str],
                                   condition: str | None) -> None:
    """Reject predicates whose modality doesn't match the event's condition.

    Condition A is visual-only, B is audio-only, C is multimodal. ``condition``
    of None skips the check (used when the caller doesn't know the modality).
    """
    if condition not in ("A", "B", "C"):
        return
    for iv in model["intervals"]:
        for p in _interval_pred_names(iv):
            is_audio = p in audio_predicates
            if condition == "A" and is_audio:
                raise ModelValidationError(
                    f"predicate '{p}' is an audio predicate; it cannot be used in "
                    "a visual (condition A) event"
                )
            if condition == "B" and not is_audio:
                raise ModelValidationError(
                    f"predicate '{p}' is a visual predicate; it cannot be used in "
                    "an audio (condition B) event"
                )


def compile_event(model_json: str | dict, deltas: dict, analysis_id: str,
                  fps: int | str = 1, audio_predicates: set[str] | None = None,
                  predicate_vocab: dict[str, list[list[str]]] | None = None,
                  condition: str | None = None
                  ) -> tuple[str, str]:
    """Compile a model to (iseql_text, sql). Raises ModelValidationError on invalid input.

    Same arguments as ``compile_event_plan``, which also returns the plan.
    """
    ev = compile_event_plan(model_json, deltas, analysis_id, fps=fps,
                            audio_predicates=audio_predicates,
                            predicate_vocab=predicate_vocab, condition=condition)
    return ev.iseql_text, ev.sql


def compile_event_plan(model_json: str | dict, deltas: dict, analysis_id: str,
                       fps: int | str = 1, audio_predicates: set[str] | None = None,
                       predicate_vocab: dict[str, list[list[str]]] | None = None,
                       condition: str | None = None,
                       text_values: dict | None = None,
                       lineage: bool = False) -> CompiledEvent:
    """Compile a model to SQL and plan. Raises ModelValidationError on invalid input.

    ``fps`` converts authored δ/ε in seconds to frames (``delta_unit`` = seconds).
    ``audio_predicates`` is the set of predicate names that read from
    AudioPerInterval (from the configured audio taxonomy); None is not allowed
    (no silent defaults) - callers must resolve it. ``predicate_vocab`` (name ->
    argument slots) is optional; when provided, predicates and their arguments
    are validated against it. ``condition`` (A/B/C) restricts the allowed
    predicate modality (visual-only / audio-only / both).

    ``sql`` and ``iseql_text`` are what ``compile_event`` returns.
    ``text_values`` maps named delta keys to the values the plan's ISEQL text
    shows (default: ``deltas``). With ``lineage``, ``lineage_sql`` runs ``sql``
    and adds a JSON ``lineage`` column: for every result row, the
    interval rows that produce it (``_lineage_sql``). Form F4 has no plan
    branches and no lineage.
    """
    if audio_predicates is None:
        raise ModelValidationError(
            "audio_predicates is required (resolve audio_taxonomy.classes)"
        )
    audio_predicates = set(audio_predicates)
    model = validate_model(model_json)
    model = _normalized_model(model)
    if predicate_vocab is not None:
        _validate_predicates(model, predicate_vocab)
        _validate_projection(model, predicate_vocab)
        _validate_cross_conditions(model, predicate_vocab)
    if condition is not None:
        _validate_predicate_modalities(model, audio_predicates, condition)
    has_set_side = any(iv.get("set_side") for iv in model["intervals"])
    if model.get("set_expression") is not None:
        sql = _render_expression(model["set_expression"], model, analysis_id, deltas,
                                 fps=fps, audio_predicates=audio_predicates)
    elif has_set_side:
        sql = _render_set_operation(model, analysis_id, deltas, fps=fps,
                                    audio_predicates=audio_predicates)
    else:
        sql = _render_flat_body(model, model["intervals"], analysis_id, deltas, fps=fps,
                                audio_predicates=audio_predicates)
    plan = _compiled_plan(model, deltas, fps, audio_predicates,
                          deltas if text_values is None else text_values)
    lineage_sql = None
    if lineage and plan.lineage:
        lineage_sql = _lineage_sql(model, plan.form, sql, analysis_id, deltas, fps,
                                   audio_predicates)
    return CompiledEvent(iseql_text=model.get("iseql_text") or "", sql=sql, plan=plan,
                         lineage_sql=lineage_sql)


# ---------------------------------------------------------------------------
# ISEQL text rendering (model -> ISEQL notation). App-owned; used to prefill
# the editor for events whose stored model has no ``iseql_text``.
# ---------------------------------------------------------------------------

def _render_selection(iv: dict, alias: str) -> str:
    pred = iv["pred"]
    sel = iv.get("selection")
    if sel:
        branches = sel.get("branches") or [{
            "preds": sel.get("preds") or [pred["name"]],
            "args": sel.get("args") or {},
        }]
        parts = []
        for b in branches:
            conds = [f'pred="{p}"' for p in (b.get("preds") or [])]
            for k in sorted((b.get("args") or {}), key=int):
                vals = b["args"][k]
                if len(vals) > 1:
                    conds.append("(" + " ∨ ".join(f'arg{k}="{v}"' for v in vals) + ")")
                elif vals:
                    conds.append(f'arg{k}="{vals[0]}"')
            parts.append(" ∧ ".join(conds))
        expr = " ∨ ".join(f"({p})" for p in parts) if len(parts) > 1 else parts[0]
        return f"σ_{{{expr}}}({alias})"
    conds = [f'pred="{pred["name"]}"']
    for k, arg in enumerate(pred.get("arguments", []), start=1):
        conds.append(f'arg{k}="{arg}"')
    return f"σ_{{{' ∧ '.join(conds)}}}({alias})"


def _render_operator(model: dict, ivs: list[dict], pair_idx: int, side: str | None,
                     lits: dict | None = None) -> str:
    op = _choose_operator(model, _slot_bounds(ivs[pair_idx]), _slot_bounds(ivs[pair_idx + 1]),
                          pair_idx, side)[3]
    entry = _delta_entry(model, pair_idx, side)
    lits = lits or {}

    def lit(v):
        """Resolve a stored param value to a literal for display."""
        if isinstance(v, str) and v not in ("<=", "<", ">=", ">"):
            return lits.get(v)
        return v

    param_names = _OPERATOR_FULL_PARAMS.get(op, ("delta", "zeta", "rho"))
    distance = []
    strict = []
    for p in param_names:
        raw = entry.get(p)
        v = lit(raw)
        if p == "delta":
            part = "δ:∞" if v is None else f"δ:{v}"
        elif p == "epsilon":
            part = "ε:∞" if v is None else f"ε:{v}"
        elif p == "zeta":
            part = f"ζ:{v if v in ('<', '<=', '>', '>=') else '<='}"
        elif p == "eta":
            part = f"η:{v if v in ('<', '<=', '>', '>=') else '<='}"
        elif p == "rho":
            part = f"ρ:{v if v not in (None, 'inf') else 0}"
        else:
            continue
        if p in ("delta", "epsilon"):
            distance.append(part)
        else:
            strict.append(part)
    inner = ", ".join(distance) + ("; " + ", ".join(strict) if strict else "")
    return f"{op}({inner})" if (distance or strict) else op


_OPERATOR_FULL_PARAMS = {
    "Bef": ("delta", "zeta", "rho"),
    "Aft": ("delta", "zeta", "rho"),
    "SP": ("delta", "zeta", "rho"),
    "EF": ("epsilon", "eta", "rho"),
    "DJ": ("delta", "epsilon", "zeta", "eta", "rho"),
    "RDJ": ("delta", "epsilon", "zeta", "eta", "rho"),
    "LOJ": ("delta", "epsilon", "zeta", "eta", "rho"),
    "ROJ": ("delta", "epsilon", "zeta", "eta", "rho"),
}


def _render_projection(model: dict, ivs: list[dict]) -> str:
    proj = model.get("custom_projection")
    if proj:
        return ", ".join(proj)
    cst, ced = _unit_domain(model)
    fields = []
    for i, iv in enumerate(ivs, start=1):
        alias = f"M{i}"
        for k in range(1, len(iv["pred"].get("arguments", [])) + 1):
            fields.append(f"{alias}.arg{k}")
        fields.append(f"{alias}.{cst}")
        fields.append(f"{alias}.{ced}")
    return ", ".join(fields)


def _cross_condition_text(c: dict) -> str:
    """ISEQL text of a cross-condition (the σ of an operand)."""
    if c.get("type") == "duration":
        return (f"({c['left_alias']}.{c['left_attr']} \u2212 "
                f"{c['right_alias']}.{c['right_attr']}) {c['op']} {c['value']}")
    return f"{c['left_alias']}.{c['left_attr']}{c['op']}{c['right_alias']}.{c['right_attr']}"


def _render_operand(model: dict, ivs: list[dict], side: str | None, offset: int,
                    lits: dict | None = None) -> str:
    body = []
    for i, iv in enumerate(ivs):
        if i > 0:
            body.append(_render_operator(model, ivs, i - 1, side, lits))
        body.append(_render_selection(iv, f"M{i + 1}"))
    proj = _render_projection(model, ivs)
    ccs = _side_cross_conditions(model, len(ivs), offset)
    if ccs:
        cond = " ∧ ".join(_cross_condition_text(c) for c in ccs)
        lines = [f"π_{{{proj}}} ("]
        lines.append(f"  σ_{{{cond}}} (")
        for line in body:
            lines.append("    " + line)
        lines.append("  ))")
        return "\n".join(lines)
    lines = [f"π_{{{proj}}} ("]
    for line in body:
        lines.append("  " + line)
    lines.append(")")
    return "\n".join(lines)


def _render_expression_text(node: dict, model: dict, lits: dict | None = None) -> str:
    """Render a set_expression tree to ISEQL text. Non-leaf children are
    parenthesised so the nesting round-trips through the parser."""
    if "group" in node:
        ivs = _group_intervals(model, node["group"])
        gm = _group_model(model, node["group"], ivs, node.get("projection"))
        return _render_operand(gm, ivs, node["group"], 0, lits)
    parts = []
    for c in node["children"]:
        text = _render_expression_text(c, model, lits)
        if "op" in c:
            text = f"({text})"
        parts.append(text)
    return f"\n{node['op']}\n".join(parts)


def render_iseql(model: dict, lits: dict | None = None) -> str:
    """Render a model dict to ISEQL text (round-trips through the parser).

    ``lits`` maps named delta keys (e.g. ``rho_audio_fight``) to their literal
    values so the rendered operators always show explicit δ/ε/ζ/η/ρ.
    """
    model = _normalized_model(model)
    ivs = model["intervals"]
    if not ivs:
        return "-- No intervals."
    if model.get("set_expression") is not None:
        return _render_expression_text(model["set_expression"], model, lits)
    if any(iv.get("set_side") for iv in ivs):
        left = [iv for iv in ivs if iv.get("set_side") == "left"]
        right = [iv for iv in ivs if iv.get("set_side") == "right"]
        op = {"\\": "\\", "∪": "∪", "∩": "∩"}.get(model.get("set_operator"), "∪")
        return (f"{_render_operand(model, left, 'left', 0, lits)}\n{op}\n"
                f"{_render_operand(model, right, 'right', len(left), lits)}")
    return _render_operand(model, ivs, None, 0, lits)



# ---------------------------------------------------------------------------
# result columns: labels and extent
# ---------------------------------------------------------------------------

def set_expression_leaves(se: dict) -> list[dict]:
    """Leaf nodes of a set_expression tree, in left-to-right order."""
    leaves: list[dict] = []

    def _walk(node: dict) -> None:
        if "group" in node:
            leaves.append(node)
        else:
            for c in node.get("children", []):
                _walk(c)

    _walk(se)
    return leaves


def is_multiset(model: dict) -> bool:
    se = model.get("set_expression")
    return isinstance(se, dict) and "children" in se


def result_fields(model: dict) -> list[str] | None:
    """Full aligned projection field list matching the emitted SQL SELECT order.

    Handles the flat (``custom_projection``), single-set (leaf ``projection``)
    and multi-set (``set_expression`` branch) forms. For a multi-set expression
    the operands are aligned by field kind (args, start, end), mirroring the
    compiler's UNION.
    """
    ivs = model.get("intervals", [])
    if not ivs:
        return None
    if any(iv.get("set_side") for iv in ivs):
        return model.get("left_projection")
    fields = model.get("custom_projection")
    if fields:
        return fields
    se = model.get("set_expression")
    if not se:
        return None
    if "group" in se:
        return se.get("projection") or None
    leaves = set_expression_leaves(se)
    if not leaves:
        return None
    leaf_fields = [l.get("projection") or [] for l in leaves]
    schema = _canonical_schema(leaf_fields)
    by_kind: dict[str, str] = {}
    for kinds in leaf_fields:
        for f in kinds:
            by_kind.setdefault(_field_kind(f), f)
    return [by_kind.get(k, f"M1.{k}") for k in schema]


def multimodal_labels(model: dict) -> list[str]:
    """Result column labels for a multimodal event.

    Matches the kind-aligned UNION columns: args become ``M1_<class>``, temporal
    fields keep the audio operand's ``M1.st``/``M2.et`` names.
    """
    leaves = set_expression_leaves(model["set_expression"])
    ivs_by_group: dict[str, list[dict]] = {}
    for iv in model.get("intervals", []):
        ivs_by_group.setdefault(iv.get("group"), []).append(iv)
    leaf_fields = [l.get("projection") or [] for l in leaves]
    schema = _canonical_schema(leaf_fields)
    labels: list[str] = []
    for kind in schema:
        m = re.match(r"^arg(\d+)$", kind)
        if m:
            k = int(m.group(1))
            cls = None
            for l in leaves:
                if any(_field_kind(f) == kind for f in (l.get("projection") or [])):
                    for iv in ivs_by_group.get(l.get("group"), []):
                        c = _interval_arg_class(iv, k)
                        if c and c != kind:
                            cls = c
                            break
                if cls:
                    break
            labels.append(f"M1_{cls}" if cls else kind)
        else:
            field = next((f for f in leaf_fields[0] if _field_kind(f) == kind), kind)
            labels.append(field)
    return labels


def result_column_labels(model: dict) -> list[str] | None:
    """Ordered result column labels for an event model's projection.

    Mirrors the projection SELECT order so duplicate ``argN`` columns can be
    renamed to class-based labels without aliasing the emitted SQL. ``sf``/``ef`` become
    ``M1.sf``/``M1.ef``. Returns ``None`` when the projection can't be resolved.
    """
    ivs = model.get("intervals", [])
    if not ivs:
        return None
    if is_multiset(model):
        return multimodal_labels(model)
    fields = result_fields(model)
    if not fields:
        return None

    iv_by_alias: dict[str, dict] = {}
    for i, iv in enumerate(ivs):
        iv_by_alias[f"M{i + 1}"] = iv

    labels: list[str] = []
    counts: dict[tuple[str, str], int] = {}
    for f in fields:
        parts = f.split(".")
        if len(parts) == 2 and parts[0].startswith("M"):
            attr = parts[1]
            iv = iv_by_alias.get(parts[0])
            if attr in ("sf", "ef"):
                labels.append(f"{parts[0]}.{attr}")
                continue
            m = re.match(r"^arg(\d+)$", attr)
            if m and iv is not None:
                cls = _interval_arg_class(iv, int(m.group(1)))
                key = (parts[0], cls)
                counts[key] = counts.get(key, 0) + 1
                n = counts[key]
                suffix = "" if n == 1 else str(n)
                labels.append(f"{parts[0]}_{cls}{suffix}")
                continue
            labels.append(_translate_field(f))
            continue
        labels.append(_translate_field(f))
    return labels


def fields_extent(fields: list[str]) -> tuple[str | None, str | None]:
    """Aliases of the first interval with a start and the last with an end."""
    start_alias = end_alias = None
    for f in fields or []:
        parts = f.split(".")
        if len(parts) == 2 and parts[0].startswith("M") and parts[1] in ("sf", "st", "ef", "et"):
            if start_alias is None and parts[1] in ("sf", "st"):
                start_alias = parts[0]
            if parts[1] in ("ef", "et"):
                end_alias = parts[0]
    return start_alias, end_alias


def result_extent(model: dict) -> tuple[str | None, str | None]:
    """(start alias, end alias) of a detection row, e.g. ("M1", "M2"); set-side
    events read it from the left operand."""
    return fields_extent(result_fields(model) or [])


# ---------------------------------------------------------------------------
# compiled plan
# ---------------------------------------------------------------------------

_FRAME_ATTRS = ("sf", "start", "StartFrame", "ef", "end", "EndFrame")
_TIME_ATTRS = ("st", "StartTime", "et", "EndTime")


def _model_form(model: dict) -> str:
    ivs = model["intervals"]
    if any(iv.get("group_id") or iv.get("query_ref") for iv in ivs):
        return "F4"
    if model.get("set_expression") is not None:
        return "F2"
    if any(iv.get("set_side") for iv in ivs):
        return "F3"
    return "F1"


def _interval_source(iv: dict, audio_predicates: set[str]) -> str:
    """Table an interval reads (the decision ``_predicate_cte`` takes)."""
    sel = iv.get("selection")
    if sel:
        branches = sel.get("branches") or [{"preds": list(sel.get("preds") or [iv["pred"]["name"]])}]
        return _selection_source([p for b in branches for p in (b.get("preds") or [])],
                                 audio_predicates)
    return _predicate_source(iv["pred"]["name"], audio_predicates)


def _cte_arg_positions(iv: dict) -> list[int]:
    """Argument positions a predicate CTE exposes as ``argK`` columns."""
    sel = iv.get("selection")
    if sel:
        branches = sel.get("branches") or [{"args": sel.get("args") or {}}]
        return sorted({int(k) for b in branches for k in (b.get("args") or {})})
    return list(range(1, len(iv["pred"].get("arguments", [])) + 1))


def _selection_plan(iv: dict) -> tuple[SelectionPlan, ...]:
    """The alternatives of a selection"""
    pred = iv["pred"]
    sel = iv.get("selection")
    if sel:
        alternatives = sel.get("branches") or [
            {"preds": sel.get("preds") or [pred["name"]], "args": sel.get("args") or {}}]
    else:
        alternatives = [{"preds": [pred["name"]],
                         "args": {str(k): [a] for k, a in enumerate(pred.get("arguments") or [], 1)}}]
    return tuple(
        SelectionPlan(
            predicates=tuple(str(p) for p in a.get("preds") or []),
            arg_classes=tuple(
                (int(k), tuple(str(c) for c in classes))
                for k, classes in sorted((a.get("args") or {}).items(), key=lambda kv: int(kv[0]))
                if classes),
        )
        for a in alternatives)


def _condition_plan(index: int, c: dict, alias_map: dict) -> ConditionPlan:
    duration = c.get("type") == "duration"
    domain = None
    if duration:
        attrs = {c["left_attr"], c["right_attr"]}
        if attrs <= set(_TIME_ATTRS):
            domain = "seconds"
        elif attrs <= set(_FRAME_ATTRS):
            domain = "frames"
    return ConditionPlan(
        index=index,
        left=f"{c['left_alias']}.{c['left_attr']}",
        op=str(c["op"]),
        right=f"{c['right_alias']}.{c['right_attr']}",
        kind="duration" if duration else "compare",
        value=c.get("value") if duration else None,
        domain=domain,
        sql=_cross_condition_sql(c, alias_map),
        text=_cross_condition_text(c),
    )


def _field_plan(field: str, ivs: list[dict]) -> FieldPlan:
    kind = _field_kind(field)
    i = _alias_index(field.split(".", 1)[0])
    arg_class = None
    if kind.startswith("arg") and kind[3:].isdigit() and i is not None and i < len(ivs):
        arg_class = str(_interval_arg_class(ivs[i], int(kind[3:])))
    return FieldPlan(field=field, kind=kind, arg_class=arg_class)


def _branch_plan(name: str, side: str | None, branch_model: dict, ivs: list[dict],
                 indices, conditions, projection_pointer: str, deltas: dict,
                 fps: int | str, audio_predicates: set[str], lits: dict | None) -> BranchPlan:
    """One operand of the rule, as ``_render_chain`` renders it"""
    alias_map = {f"M{i + 1}": (f"M{i + 1}", None) for i in range(len(ivs))}
    fields = branch_model.get("custom_projection") or _default_projection(branch_model, ivs, alias_map)
    operators: tuple[OperatorPlan, ...] = ()
    if len(ivs) > 1:
        operators = tuple(_resolve_operators(
            branch_model, deltas, [_slot_bounds(iv) for iv in ivs], list(range(len(ivs))),
            side, fps, render=lambda pair: _render_operator(branch_model, ivs, pair, side, lits)))
    return BranchPlan(
        name=name,
        side=side,
        domain="seconds" if _domain_cols(branch_model) == ("st", "et") else "frames",
        intervals=tuple(
            IntervalPlan(index=index, alias=f"M{k + 1}",
                         modality=_interval_source(iv, audio_predicates),
                         selection=_selection_plan(iv), text=_render_selection(iv, f"M{k + 1}"))
            for k, (index, iv) in enumerate(zip(indices, ivs))),
        operators=operators,
        conditions=tuple(_condition_plan(i, c, alias_map) for i, c in conditions),
        projection=tuple(_field_plan(f, ivs) for f in fields),
        projection_pointer=projection_pointer,
        projection_text=f"π_{{{_render_projection(branch_model, ivs)}}}",
        extent=ExtentPlan(*fields_extent(fields)),
    )


def _branches(model: dict, form: str, deltas: dict, fps: int | str,
              audio_predicates: set[str], lits: dict | None):
    """(branch plans, set-operation tree or None) of a model in form F1, F2 or F3."""
    ccs = list(enumerate(model.get("cross_conditions") or []))
    args = (deltas, fps, audio_predicates, lits)
    if form == "F1":
        ivs = model["intervals"]
        pointer = "/custom_projection" if model.get("custom_projection") else "/intervals"
        return [_branch_plan("main", None, model, ivs, range(len(ivs)), ccs, pointer, *args)], None
    if form == "F3":
        branches = []
        for side in ("left", "right"):
            side_model = _side_model(model, side)
            ivs = side_model["intervals"]
            offset = 0 if side == "left" else len(_side_intervals(model, "left"))
            indices = [i for i, iv in enumerate(model["intervals"]) if iv.get("set_side") == side]
            conditions = [(i, rb[0]) for i, c in ccs if (rb := _side_cross_conditions(
                dict(model, cross_conditions=[c]), len(ivs), offset))]
            pointer = f"/{side}_projection" if model.get(f"{side}_projection") else "/intervals"
            branches.append(_branch_plan(side, side, side_model, ivs, indices, conditions,
                                         pointer, *args))
        tree = SetNode(op=model.get("set_operator") or "\\", pointer="/set_operator",
                       children=("left", "right"))
        return branches, tree
    branches = []

    def walk(node: dict, pointer: str):
        if "group" in node:
            group = node.get("group")
            ivs = _group_intervals(model, group)
            if not ivs:
                raise ModelValidationError(f"set_expression references empty group {group!r}")
            group_model = _group_model(model, group, ivs, node.get("projection"))
            indices = [i for i, iv in enumerate(model["intervals"]) if (iv.get("group") or None) == group]
            conditions = [(i, rb[0]) for i, c in ccs if (rb := _group_cross_conditions(
                dict(model, cross_conditions=[c]), group))]
            projection_pointer = f"{pointer}/projection" if node.get("projection") else pointer
            branches.append(_branch_plan(group or "main", group, group_model, ivs, indices,
                                         conditions, projection_pointer, *args))
            return group or "main"
        return SetNode(op=node["op"], pointer=pointer,
                       children=tuple(walk(c, f"{pointer}/children/{i}")
                                      for i, c in enumerate(node["children"])))

    root = walk(model["set_expression"], "/set_expression")
    return branches, (root if isinstance(root, SetNode) else None)


def _positional_problem(left: list[str], right: list[str]) -> str | None:
    """Set sides pad the shorter side with NULLs: each position must hold the same kind."""
    for position in range(max(len(left), len(right))):
        lk = _field_kind(left[position]) if position < len(left) else "NULL"
        rk = _field_kind(right[position]) if position < len(right) else "NULL"
        if lk != rk:
            return (f"set_side rule: result column {position + 1} is {lk} in the left side "
                    f"and {rk} in the right side (columns are aligned by position)")
    return None


def _columns(model: dict, form: str, multiset: bool, branches: list[BranchPlan]):
    """(columns, problem): what each result column holds, per branch, under its label."""
    if multiset:
        labels = multimodal_labels(model)
        kinds = _canonical_schema([[f.field for f in b.projection] for b in branches])
        if len(labels) != len(kinds):
            return None, "the column labels do not match the aligned columns"
        columns = []
        for position, (label, kind) in enumerate(zip(labels, kinds)):
            fields = []
            for b in branches:
                field = next((f.field for f in b.projection if f.kind == kind), None)
                if field is not None:
                    fields.append((b.name, field))
            arg_class = label[len("M1_"):] if kind.startswith("arg") and label.startswith("M1_") else None
            columns.append(ColumnPlan(position=position, label=label, kind=kind,
                                      fields=tuple(fields), arg_class=arg_class))
        return tuple(columns), None
    if form == "F3":
        problem = _positional_problem([f.field for f in branches[0].projection],
                                      [f.field for f in branches[1].projection])
        if problem:
            return None, problem
    labels = result_column_labels(model)
    reference = branches[0]
    if labels is None or len(labels) != len(reference.projection):
        return None, "the result columns of this rule have no labels"
    if len(set(labels)) != len(labels):
        return None, "two result columns have the same label"
    return tuple(
        ColumnPlan(position=position, label=label, kind=field.kind,
                   fields=tuple((b.name, b.projection[position].field) for b in branches),
                   arg_class=field.arg_class)
        for position, (label, field) in enumerate(zip(labels, reference.projection))
    ), None


def _compiled_plan(model: dict, deltas: dict, fps: int | str, audio_predicates: set[str],
                   lits: dict | None) -> CompiledPlan:
    form = _model_form(model)
    extent = ExtentPlan(*result_extent(model))
    text = render_iseql(model, lits)
    if form == "F4":
        return CompiledPlan(
            form="F4", branches=(), set_tree=None, columns=None,
            columns_problem="nested groups (group_id) and query references (query_ref) "
                            "are not described by the plan",
            extent=extent, text=text, lineage=False)
    branches, tree = _branches(model, form, deltas, fps, audio_predicates, lits)
    multiset = form == "F2" and tree is not None
    columns, problem = _columns(model, form, multiset, branches)
    return CompiledPlan(form=form, branches=tuple(branches), set_tree=tree, columns=columns,
                        columns_problem=problem, extent=extent, text=text, lineage=True)


# ---------------------------------------------------------------------------
# lineage: which interval rows produce each result row
# ---------------------------------------------------------------------------

# A lineage CTE is used by a correlated subquery: materialize it once (SQLite >= 3.35).
_MATERIALIZED = "MATERIALIZED " if sqlite3.sqlite_version_info >= (3, 35, 0) else ""


def _sql_text(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _operands(model: dict, form: str) -> list[tuple]:
    """Operands of the detection SQL, left to right: (keyword before it, branch
    name, branch model, intervals, side)"""
    if form == "F1":
        return [(None, "main", model, model["intervals"], None)]
    if form == "F3":
        keyword = _SET_SQL[model.get("set_operator") or "\\"]
        return [(None, "left", _side_model(model, "left"), _side_intervals(model, "left"), "left"),
                (keyword, "right", _side_model(model, "right"), _side_intervals(model, "right"),
                 "right")]
    out: list[tuple] = []

    def walk(node: dict, keyword: str | None) -> None:
        if "group" in node:
            ivs = _group_intervals(model, node["group"])
            out.append((keyword, node["group"] or "main",
                        _group_model(model, node["group"], ivs, node.get("projection")),
                        ivs, node["group"]))
            return
        for i, c in enumerate(node["children"]):
            walk(c, keyword if i == 0 else _SET_SQL[node["op"]])

    walk(model["set_expression"], None)
    return out


def _witness(name: str, ivs: list[dict], audio_predicates: set[str]) -> str:
    """JSON object naming the branch and, per interval, its table, row id and participants."""
    items = []
    for k, iv in enumerate(ivs):
        alias = f"M{k + 1}"
        if _interval_source(iv, audio_predicates) == _AUDIO_SOURCE:
            items.append(f"json_object('alias', '{alias}', 'table', 'AudioPerInterval', "
                         f"'id', {alias}.__rid, 'args', json_array())")
            continue
        args = ", ".join(
            f"json_object('position', {p}, 'class_id', {alias}.arg{p}, 'class', {alias}.__arg{p}_class)"
            for p in _cte_arg_positions(iv))
        items.append(f"json_object('alias', '{alias}', 'table', 'VisualPerInterval', "
                     f"'id', {alias}.__rid, 'args', json_array({args}))")
    return f"json_object('branch', {_sql_text(name)}, 'intervals', json_array({', '.join(items)}))"


def _lineage_sql(model: dict, form: str, sql: str, analysis_id: str, deltas: dict,
                 fps: int | str, audio_predicates: set[str]) -> str:
    """The detection SQL, unchanged, plus a ``lineage`` column: the JSON array of
    the witnesses of each row (branch and interval rows that produce it).

    ``r`` is the detection SQL; ``l`` re-runs each operand with its interval ids.
    A witness belongs to a row when its columns equal the row's. 
    After EXCEPT or INTERSECT an operand must also keep the row
    alive: a subtracted operand never contributes, and the row must belong to every
    partial result from that operand on. Rows with several witnesses are
    ambiguities of the rule.
    """
    operands = _operands(model, form)
    plain, lineage = [], []
    for _keyword, _name, branch_model, ivs, side in operands:
        plain.append(_render_chain(branch_model, ivs, analysis_id, deltas, side=side, fps=fps,
                                   audio_predicates=audio_predicates))
        lineage.append(_render_chain(branch_model, ivs, analysis_id, deltas, side=side, fps=fps,
                                     audio_predicates=audio_predicates, lineage=True))
    fields = [p[1] for p in plain]
    if form == "F3":
        n = max(len(f) for f in fields)
        aligned = [_pad_fields(f, n) for f in fields]
    elif form == "F2" and "op" in model["set_expression"]:
        schema = _canonical_schema(fields)
        aligned = [_align_fields(f, schema) for f in fields]
    else:
        aligned = fields
    keywords = [o[0] for o in operands]
    bodies = [_build_inline(p[0], a, p[2]) for p, a in zip(plain, aligned)]
    chain = bodies[0] + "".join(f"\n{keywords[j]}\n{bodies[j]}" for j in range(1, len(bodies)))
    if chain != sql:
        raise ModelValidationError("lineage operands do not rebuild the detection SQL")
    n_cols = len(aligned[0])
    names = ", ".join(f"c{i}" for i in range(n_cols))

    def match(t: str) -> str:
        return " AND ".join(f"{t}.c{i} IS r.c{i}" for i in range(n_cols))

    selects = []
    for j, ((_kw, name, _bm, ivs, _side), (ctes, _f, conds), a) in enumerate(
            zip(operands, lineage, aligned)):
        cols = [f"{f.split(' AS ')[0]} AS c{i}" for i, f in enumerate(a)]
        cols += [f"{j} AS o", f"{_witness(name, ivs, audio_predicates)} AS w"]
        selects.append(_build_inline(ctes, cols, conds))
    where = match("l")
    if any(k in ("EXCEPT", "INTERSECT") for k in keywords[1:]):
        guards = []
        for j in range(len(operands)):
            if keywords[j] == "EXCEPT":
                continue
            alive = []
            for i in range(j, len(operands) - 1):
                prefix = bodies[0] + "".join(f"\n{keywords[m]}\n{bodies[m]}" for m in range(1, i + 1))
                alive.append(f"EXISTS (WITH x({names}) AS (\n{prefix}\n) SELECT 1 FROM x WHERE "
                             + match("x") + ")")
            guards.append(f"(l.o = {j}" + "".join(f" AND {g}" for g in alive) + ")")
        where += " AND (" + (" OR ".join(guards) or "0") + ")"
    union = "\nUNION ALL\n".join(selects)
    return (f"WITH r({names}) AS (\n{sql}\n),\nl AS {_MATERIALIZED}(\n{union}\n)\n"
            f"SELECT r.*, (SELECT json_group_array(json(l.w)) FROM l WHERE {where}) AS lineage\n"
            f"FROM r")
