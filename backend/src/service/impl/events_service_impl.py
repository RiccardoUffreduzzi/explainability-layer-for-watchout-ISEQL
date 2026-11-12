from __future__ import annotations

import json
import sqlite3
from typing import Callable, Iterator

import pandas as pd

from utils.api_logger import get_logger
from iseql.compiler import result_column_labels, result_extent
from service.events_service import (
    DetectedRow,
    DetectionError,
    DetectionResult,
    EventsService,
    EventSpec,
    ResolvedParams,
    Witness,
    WitnessArg,
    WitnessInterval,
)

log = get_logger(__name__)

VALID_CONDITIONS = ("A", "B", "C")

_STRICTNESS_OPERATORS = {"<=", "<", ">=", ">"}


def _is_strictness_key(key: str) -> bool:
    return key.startswith("zeta_") or key.startswith("eta_")


def derive_delta_fields(model_json: str | dict) -> dict[str, str]:
    """Derive the EventSpec delta-parameter fields from a model's delta_map.

    The operator editor names the per-detect keys (e.g. ``delta_visual_handoff``,
    ``zeta_audio_fight``); their prefix decides which EventSpec field they belong
    to. Returns {field_name: key}.
    """
    import json as _json
    if isinstance(model_json, str):
        try:
            model = _json.loads(model_json)
        except _json.JSONDecodeError:
            return {}
    elif isinstance(model_json, dict):
        model = model_json
    else:
        return {}
    fields: dict[str, str] = {}
    prefixes = [
        ("delta_visual_", "delta_visual"), ("delta_audio_", "delta_audio"),
        ("epsilon_visual_", "epsilon_visual"), ("epsilon_audio_", "epsilon_audio"),
        ("eta_visual_", "eta_visual"), ("eta_audio_", "eta_audio"),
        ("zeta_visual_", "zeta_visual"), ("zeta_audio_", "zeta_audio"),
        ("rho_visual_", "rho_visual"), ("rho_audio_", "rho_audio"),
    ]
    for entry in (model.get("delta_map", {}) or {}).values():
        if not isinstance(entry, dict):
            continue
        for value in entry.values():
            if not isinstance(value, str):
                continue
            for prefix, field in prefixes:
                if value.startswith(prefix):
                    fields[field] = value
    return fields


_PREFIX_KIND = {
    "delta_visual_": "delta", "delta_audio_": "delta",
    "epsilon_visual_": "epsilon", "epsilon_audio_": "epsilon",
    "eta_visual_": "eta", "eta_audio_": "eta",
    "zeta_visual_": "zeta", "zeta_audio_": "zeta",
    "rho_visual_": "rho", "rho_audio_": "rho",
}
_PREFIX_MODALITY = {
    "delta_visual_": "visual", "delta_audio_": "audio",
    "epsilon_visual_": "visual", "epsilon_audio_": "audio",
    "eta_visual_": "visual", "eta_audio_": "audio",
    "zeta_visual_": "visual", "zeta_audio_": "audio",
    "rho_visual_": "visual", "rho_audio_": "audio",
}
# Named-key -> (kind, modality) so a generated delta name is stable per event.
_PREFIX_LOOKUP = {p: (_PREFIX_KIND[p], _PREFIX_MODALITY[p]) for p in _PREFIX_KIND}


def default_deltas_for(model_json: str | dict, event_id: str,
                       fields: dict[str, str] | None = None) -> dict[str, object]:
    """Per-event default delta literals derived from the AUTHORED ISEQL text.

    Returns ``{ delta_name: literal }`` for every operator parameter the event's
    authored ISEQL uses. ``delta_name`` is the event's named delta key (e.g.
    ``delta_visual_handoff``) for named parameters, otherwise a generated
    ``<event>_<modality>_<kind>`` name. ``delta``/``epsilon`` unbounded defaults
    are ``inf``; unknown params fall back to the general default (delta/epsilon
    -> ``inf``, zeta/eta -> ``<=``, rho -> ``0``). ``fields`` is the event's
    delta-parameter field map ({field_name: named_key}) so column-driven named
    keys are always present. This is the single ISEQL-sourced default for the
    frontend delta editor (no hardcoded variables).
    """
    import json as _json
    if isinstance(model_json, str):
        try:
            model = _json.loads(model_json)
        except _json.JSONDecodeError:
            return {}
    elif isinstance(model_json, dict):
        model = model_json
    else:
        return {}

    def _literal(value):
        if value is None or value == "inf":
            return "inf"
        return value

    # Stored model delta_map carries the NAMED keys (e.g. `delta_audio_fight`);
    # the authored ISEQL text (parsed) carries the LITERAL defaults. Pair them
    # by operator-pair key ("0", "left.0", "right.0", ...) so each named key maps
    # to its authored literal default.
    named_dm = (model.get("delta_map") or {}) if isinstance(model, dict) else {}
    parsed_dm: dict = {}
    text = model.get("iseql_text") if isinstance(model, dict) else None
    if text:
        try:
            from iseql.parser import parse_iseql
            parsed_model = parse_iseql(text, event_id)
            parsed_dm = parsed_model.get("delta_map") or {}
        except Exception:
            parsed_dm = {}

    # A single-set model renders/parses as a flat chain, so its stored delta_map
    # keys are "<side>.<i>" while the authored text parses back to flat "<i>".
    # Rebind the flat parsed keys to the single set side so the two maps align.
    named_sides = {str(k).split(".", 1)[0] for k in named_dm if "." in str(k)}
    if len(named_sides) == 1:
        side = named_sides.pop()
        parsed_dm = {
            (f"{side}.{k}" if "." not in str(k) else str(k)): v
            for k, v in parsed_dm.items()
        }

    def _entry(dm, key):
        e = dm.get(key)
        return e if isinstance(e, dict) else {}

    def _kind_of(value):
        if isinstance(value, str):
            for prefix, (kind, _mod) in _PREFIX_LOOKUP.items():
                if value.startswith(prefix):
                    return kind
        return None

    defaults: dict[str, object] = {}
    # union of operator-pair keys across both maps (align by key)
    for key in sorted(set(named_dm) | set(parsed_dm)):
        ne = _entry(named_dm, key)
        pe = _entry(parsed_dm, key)
        for kind, named_value in ne.items():
            lit = _literal(pe.get(kind))
            if isinstance(named_value, str):
                matched = None
                for prefix, (k2, _m2) in _PREFIX_LOOKUP.items():
                    if named_value.startswith(prefix):
                        matched = (k2, named_value)
                        break
                if matched:
                    # named key present -> use its authored literal
                    defaults[named_value] = lit
                    continue
            # no named key for this param -> keep the authored literal under a
            # generated name (e.g. a literal `5` delta authored in the ISEQL).
            g = _kind_of(named_value) if isinstance(named_value, str) else kind
            gkey = f"{event_id}_{g or kind}"
            defaults[gkey] = lit

    # Ensure every EventSpec delta column's named key is present (these are the
    # keys `required_deltas` expects). Assign the general default by field kind
    # when the authored ISEQL carries no matching literal.
    _FIELD_KIND = {
        "delta_visual": "delta", "delta_audio": "delta",
        "epsilon_visual": "epsilon", "epsilon_audio": "epsilon",
        "eta_visual": "eta", "eta_audio": "eta",
        "zeta_visual": "zeta", "zeta_audio": "zeta",
        "rho_visual": "rho", "rho_audio": "rho",
    }
    _KIND_LITERAL = {"delta": "inf", "epsilon": "inf", "zeta": "<=", "eta": "<=", "rho": 0}
    for field, named_key in (fields or {}).items():
        kind = _FIELD_KIND.get(field, "delta")
        defaults.setdefault(named_key, _KIND_LITERAL.get(kind, "inf"))
    return defaults


def _require_strictness(key: str, value: str) -> str:
    """Validate a zeta/eta strictness operator; returns it unchanged."""
    if value not in _STRICTNESS_OPERATORS:
        raise ValueError(
            f"invalid strictness operator '{value}' for '{key}'; "
            f"expected one of {sorted(_STRICTNESS_OPERATORS)}"
        )
    return value


def _required_for(condition: str, conn: sqlite3.Connection) -> set[str]:
    """Delta-parameter names required by the enabled events of a condition.

    Events are user-defined in the DB registry; there are no hardcoded defaults.
    """
    if conn is None:
        raise ValueError("delta resolution requires a database connection")
    from service.impl.event_registry_service_impl import EventRegistryServiceImpl
    return EventRegistryServiceImpl().required_deltas(conn, condition)


def _require_deltas(condition: str, deltas: dict, conn: sqlite3.Connection) -> None:
    missing = _required_for(condition, conn) - set(deltas)
    if missing:
        raise ValueError(
            f"missing required delta parameter(s) for condition {condition}: "
            + ", ".join(sorted(missing))
        )


def _resolve_deltas(
    condition: str, deltas: dict, conn: sqlite3.Connection
) -> dict[str, int | str | None]:
    _require_deltas(condition, deltas, conn)
    resolved: dict[str, int | str | None] = {}
    for key in _required_for(condition, conn):
        value = deltas[key]
        if _is_strictness_key(key):
            resolved[key] = _require_strictness(key, value)
        elif value in ("inf", "∞"):
            resolved[key] = None
        else:
            resolved[key] = int(value)
    return resolved


def _compile_event_sql(
    spec: EventSpec, d: dict, condition: str, analysis_id: str, fps: int = 1,
    audio_predicates: set[str] | None = None,
) -> str | None:
    """Compile one event to SQL from its user-defined ISEQL builder model
    (compile-at-detect). Events without a model cannot be compiled."""
    if not spec.model_json:
        return None
    from iseql.facade import compile_event
    _, sql = compile_event(spec.model_json, d, analysis_id, fps=fps,
                           audio_predicates=audio_predicates)
    return sql


def _rename_result_columns(df, model: dict):
    """Rename duplicate/ambiguous query result columns to class labels."""
    labels = result_column_labels(model)
    if labels is None:
        return df
    if len(labels) == len(df.columns):
        df = df.copy()
        df.columns = labels
    return df


def _events_from_db(conn: sqlite3.Connection, condition: str) -> list[EventSpec]:
    from service.impl.event_registry_service_impl import EventRegistryServiceImpl
    return EventRegistryServiceImpl().list_events(conn, condition=condition)


def _resolve_audio_predicates(conn: sqlite3.Connection) -> set[str]:
    """Predicates read from AudioPerInterval = the configured audio classes."""
    from service.impl.config_store_service_impl import ConfigStoreServiceImpl
    section = ConfigStoreServiceImpl().get_section(conn, "audio_taxonomy") or {}
    classes = section.get("classes") or []
    return set(str(c) for c in classes)


# ---------------------------------------------------------------------------
# Condition C = multimodal events authored in the registry like A and B.
# ---------------------------------------------------------------------------

def queries_for_condition(
    condition: str, deltas: dict, analysis_id: str,
    conn: sqlite3.Connection | None = None, fps: int = 1,
) -> dict[str, str]:
    if condition not in VALID_CONDITIONS:
        raise ValueError(f"unknown condition '{condition}'; expected A | B | C")
    close = False
    if conn is None:
        from service.impl.event_registry_service_impl import _registry_conn
        conn = _registry_conn()
        close = True
    try:
        d = _resolve_deltas(condition, deltas, conn)
        audio_predicates = _resolve_audio_predicates(conn)
        queries: dict[str, str] = {}
        for e in _events_from_db(conn, condition):
            sql = _compile_event_sql(e, d, condition, analysis_id, fps=fps,
                                     audio_predicates=audio_predicates)
            if sql:
                queries[e.id] = sql
        return queries
    finally:
        if close:
            conn.close()


def events_for_condition(
    condition: str, conn: sqlite3.Connection | None = None
) -> list[EventSpec]:
    if condition not in VALID_CONDITIONS:
        raise ValueError(f"unknown condition '{condition}'; expected A | B | C")
    close = False
    if conn is None:
        from service.impl.event_registry_service_impl import _registry_conn
        conn = _registry_conn()
        close = True
    try:
        return _events_from_db(conn, condition)
    finally:
        if close:
            conn.close()


def run_sql_detection(
    conn,
    event_type: str,
    deltas: dict,
    analysis_id: str,
    condition: str = "A",
    log: Callable[[str], None] = log.info,
    fps: int = 1,
) -> Iterator[str]:
    queries = queries_for_condition(condition, deltas, analysis_id, conn=conn, fps=fps)
    if event_type not in queries:
        yield f"ERROR: unknown event type '{event_type}' for condition {condition}"
        return
    sql = queries[event_type]
    log(f"Running SQL detection for '{event_type}' (condition {condition}) with deltas {deltas}")
    try:
        df = pd.read_sql_query(sql, conn)
        log(f"--- {len(df)} results ---")
        if df.empty:
            yield "No events of this type were detected."
        else:
            model = None
            for e in _events_from_db(conn, condition):
                if e.id == event_type and e.model_json:
                    try:
                        model = json.loads(e.model_json)
                    except Exception:
                        model = None
                    break
            if model is not None:
                df = _rename_result_columns(df, model)
            yield f"__RESULT__:{df.to_json(orient='records')}"
    except Exception as e:
        yield f"ERROR executing query: {e}"


# ---------------------------------------------------------------------------
# detection: one entry point for the GUI (detect_event) and the XAI pipeline
# ---------------------------------------------------------------------------

def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def default_params(conn: sqlite3.Connection) -> tuple[dict, dict, dict]:
    """The parameters the GUI pre-fills: (merged values, key -> rule that won,
    rule -> its own defaults). Rules are named "<event>/<condition>".

    ``default_deltas_for`` of every rule of A, then B, then C, a later rule
    overwriting an earlier one, as the frontend merges them.
    """
    values: dict = {}
    provided_by: dict = {}
    by_rule: dict = {}
    for condition in VALID_CONDITIONS:
        for spec in _events_from_db(conn, condition):
            fields = ({f: k for f, k in derive_delta_fields(spec.model_json).items() if k}
                      if spec.model_json else {})
            ref = f"{spec.id}/{condition}"
            by_rule[ref] = default_deltas_for(spec.model_json, spec.id, fields)
            for key, value in by_rule[ref].items():
                values[key] = value
                provided_by[key] = ref
    return values, provided_by, by_rule


def resolve_params(conn: sqlite3.Connection, condition: str, params: dict, unit: str,
                   sampling_rate, origin: str = "request", provided_by: dict | None = None,
                   rule_defaults: dict | None = None) -> ResolvedParams:
    """The parameters as the compiler receives them, with every step.

    With ``unit == "seconds"`` every numeric value is multiplied by the sampling
    rate and rounded, then ``_resolve_deltas`` checks the keys required by the
    maps inf to None and casts to int.
    """
    written = dict(params)
    converted = dict(written)
    if unit == "seconds":
        converted = {k: (round(v * sampling_rate) if _is_number(v) else v)
                     for k, v in written.items()}
    engine = _resolve_deltas(condition, converted, conn)
    return ResolvedParams(origin=origin, unit=unit, written=written, converted=converted,
                          engine=engine, provided_by=dict(provided_by or {}),
                          rule_defaults=dict(rule_defaults or {}))


def format_time(seconds: float) -> str:
    total_ms = int(round(seconds * 1000))
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    m = (total_s // 60) % 60
    h = (total_s // 3600) % 24
    d = total_s // 86400
    if d > 0:
        return f"{d}d {h:02d}:{m:02d}:{s:02d}.{ms:03d}"
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def extent_aliases(model_json: str | None) -> tuple[str | None, str | None]:
    """(start alias, end alias) of an event's rows; (None, None) when unreadable."""
    try:
        return result_extent(json.loads(model_json))
    except Exception:
        return None, None


def gui_row(row: dict, start_alias: str | None, end_alias: str | None, fps) -> dict:
    """A result row as the GUI shows it: frames derived from seconds, times formatted as HH:MM:SS.mmm."""
    row = dict(row)
    st_key = f"{start_alias}.st" if start_alias else None
    et_key = f"{end_alias}.et" if end_alias else None
    sf_key = f"{start_alias}.sf" if start_alias else None
    ef_key = f"{end_alias}.ef" if end_alias else None
    # seconds-frame conversion
    if start_alias and st_key in row and sf_key not in row and _is_number(row.get(st_key)):
        row[sf_key] = round(row[st_key] * fps)
    if end_alias and et_key in row and ef_key not in row and _is_number(row.get(et_key)):
        row[ef_key] = round(row[et_key] * fps)
    # time-domain: format st/et seconds -> "HH:MM:SS.mmm"
    if st_key and st_key in row and row[st_key] is not None and not isinstance(row[st_key], str):
        row[st_key] = format_time(row[st_key])
    if et_key and et_key in row and row[et_key] is not None and not isinstance(row[et_key], str):
        row[et_key] = format_time(row[et_key])
    return row


def _witnesses(payload: str) -> tuple[Witness, ...]:
    return tuple(
        Witness(branch=w["branch"], intervals=tuple(
            WitnessInterval(alias=i["alias"], table=i["table"], id=i["id"], args=tuple(
                WitnessArg(position=a["position"], class_id=a["class_id"], class_name=a["class"])
                for a in i["args"]))
            for i in w["intervals"]))
        for w in json.loads(payload))


def detect(conn: sqlite3.Connection, *, analysis_id: str, event_type: str, condition: str,
           params: dict | None = None, unit: str = "seconds",
           with_lineage: bool = False) -> DetectionResult:
    """One detection, as the GUI runs it. Reads only.

    ``params=None`` uses ``default_params``. With ``with_lineage`` the lineage
    query runs instead of the detection SQL.
    """
    from iseql.compiler import compile_event_plan

    if condition not in VALID_CONDITIONS:
        raise ValueError(f"unknown condition '{condition}'; expected A | B | C")
    analysis = conn.execute("SELECT SamplingRate FROM Analyses WHERE ID = ?",
                            (analysis_id,)).fetchone()
    if analysis is None:
        raise ValueError(f"unknown analysis_id '{analysis_id}'")
    fps = analysis[0]
    spec = next((e for e in _events_from_db(conn, condition) if e.id == event_type), None)
    if spec is None:
        raise ValueError(f"event '{event_type}' not available for condition {condition}")
    if not spec.model_json:
        raise DetectionError(f"event '{event_type}' has no model")
    if params is None:
        values, provided_by, by_rule = default_params(conn)
        resolved = resolve_params(conn, condition, values, unit, fps, "rule_defaults", provided_by,
                                  by_rule)
    else:
        resolved = resolve_params(conn, condition, params, unit, fps)
    shown = {k: (None if v in ("inf", "∞") else v) for k, v in resolved.written.items()}
    compiled = compile_event_plan(spec.model_json, resolved.engine, analysis_id, fps=fps,
                                  audio_predicates=_resolve_audio_predicates(conn),
                                  text_values=shown, lineage=with_lineage)
    lineage = with_lineage and compiled.lineage_sql is not None
    try:
        model = json.loads(spec.model_json)
    except Exception:
        model = None
    try:
        df = pd.read_sql_query(compiled.lineage_sql if lineage else compiled.sql, conn)
        payloads = None
        if lineage:
            payloads = df.pop("lineage").tolist()
            names = [d[0] for d in conn.execute(f"{compiled.sql}\nLIMIT 0").description]
            df.columns = names
        values_rows: list[dict] = []
        if not df.empty:
            if model is not None:
                df = _rename_result_columns(df, model)
            values_rows = json.loads(df.to_json(orient='records'))
    except Exception as e:
        raise DetectionError(f"executing query: {e}") from e
    start_alias, end_alias = extent_aliases(spec.model_json)
    rows = tuple(
        DetectedRow(values=row, gui=gui_row(row, start_alias, end_alias, fps),
                    witnesses=_witnesses(payloads[i]) if payloads is not None else None)
        for i, row in enumerate(values_rows))
    return DetectionResult(
        analysis_id=analysis_id, event_type=event_type, condition=condition,
        sampling_rate=fps, model=model, plan=compiled.plan, params=resolved,
        sql=compiled.sql, rows=rows, lineage=lineage)


def register_events(conn: sqlite3.Connection, models: list[dict]) -> int:
    """Upsert user-defined event definitions into the registry.

    Used by the experiment harness / notebooks to define events as data. Each
    ``model`` is: {"id", "condition", "model_json", and optional
    delta/eta/zeta/rho keys}.
    """
    from service.impl.event_registry_service_impl import EventRegistryServiceImpl
    reg = EventRegistryServiceImpl()
    count = 0
    for m in models:
        spec = _spec_from_model(m)
        existing = reg.get_event(conn, spec.id, spec.condition)
        if existing is None:
            reg.create_event(conn, spec)
        else:
            reg.update_event(conn, spec.id, spec.condition, {"model_json": spec.model_json})
        count += 1
    return count


def _spec_from_model(m: dict) -> EventSpec:
    import json as _json
    missing = [k for k in ("id", "condition", "model_json") if k not in m]
    if missing:
        raise ValueError(f"event model missing field(s): {', '.join(missing)}")
    model = m["model_json"]
    if isinstance(model, (dict, list)):
        model = _json.dumps(model)
    return EventSpec(
        id=m["id"],
        condition=m["condition"],
        model_json=model,
    )


class EventsServiceImpl(EventsService):
    def queries_for_condition(self, condition: str, deltas: dict, analysis_id: str,
                              fps: int = 1) -> dict[str, str]:
        return queries_for_condition(condition, deltas, analysis_id, fps=fps)

    def events_for_condition(self, condition: str) -> list[EventSpec]:
        return events_for_condition(condition)

    def run_sql_detection(
        self,
        conn,
        event_type: str,
        deltas: dict,
        analysis_id: str,
        condition: str = "A",
        log: Callable[[str], None] = None,
        fps: int = 1,
    ) -> Iterator[str]:
        return run_sql_detection(conn, event_type, deltas, analysis_id, condition, log or log.info, fps)

    def detect(
        self,
        conn,
        *,
        analysis_id: str,
        event_type: str,
        condition: str,
        params: dict | None = None,
        unit: str = "seconds",
        with_lineage: bool = False,
    ) -> DetectionResult:
        return detect(conn, analysis_id=analysis_id, event_type=event_type, condition=condition,
                      params=params, unit=unit, with_lineage=with_lineage)
