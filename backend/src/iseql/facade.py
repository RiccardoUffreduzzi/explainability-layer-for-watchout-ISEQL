"""ISEQL compiler facade used by the service/API layers.

The actual compiler (``iseql.compiler``), parser (``iseql.parser``) and SQL
operators (``iseql.helpers``) live in the ``iseql`` domain package. This module
is the thin entry point the controllers and the detection path call.
"""
from __future__ import annotations


def _resolve_audio_predicates(conn) -> set[str]:
    """Predicates that read from AudioPerInterval = the configured audio classes."""
    from service.impl.config_store_service_impl import ConfigStoreServiceImpl
    section = ConfigStoreServiceImpl().get_section(conn, "audio_taxonomy") or {}
    classes = section.get("classes") or []
    return set(str(c) for c in classes)


def _resolve_predicate_vocab(conn) -> dict[str, list[list[str]]]:
    """Predicate name -> argument slots (visual relations + audio classes)."""
    from service.impl.config_store_service_impl import ConfigStoreServiceImpl
    from service.relation_vocab import signature_slots
    store = ConfigStoreServiceImpl()
    relation_vocab = store.get_section(conn, "relation_vocab") or {}
    audio_taxonomy = store.get_section(conn, "audio_taxonomy") or {}
    vocab: dict[str, list[list[str]]] = {}
    for name, sig in (relation_vocab.get("relation_classids") or []):
        vocab[str(name)] = signature_slots(str(sig))
    for name in (audio_taxonomy.get("classes") or []):
        vocab[str(name)] = []
    return vocab


def _config_conn():
    from service.impl.config_store_service_impl import _config_conn as _conn
    return _conn()


def compile_event(model_json: str | dict, deltas: dict, analysis_id: str,
                  fps: int | str = 1, audio_predicates: set[str] | None = None
                  ) -> tuple[str, str]:
    """Compile a model to (iseql_text, sql); ``fps`` converts δ/ε seconds->frames.

    ``audio_predicates`` (predicates read from AudioPerInterval) is required;
    callers resolve it from the audio taxonomy.
    """
    from iseql.compiler import compile_event as _compile
    return _compile(model_json, deltas, analysis_id, fps=fps,
                    audio_predicates=audio_predicates)


def compile_event_plan(model_json: str | dict, deltas: dict, analysis_id: str,
                       fps: int | str = 1, audio_predicates: set[str] | None = None,
                       text_values: dict | None = None, lineage: bool = False):
    """Compile a model to its SQL, its plan and, with ``lineage``, the query that also returns the interval rows behind each row."""
    from iseql.compiler import compile_event_plan as _compile_plan
    return _compile_plan(model_json, deltas, analysis_id, fps=fps,
                         audio_predicates=audio_predicates, text_values=text_values,
                         lineage=lineage)


def validate_model(model_json: str | dict) -> dict:
    from iseql.compiler import validate_model as _validate
    return _validate(model_json)


def render_model(model_json: str | dict) -> str:
    """Render a model to ISEQL text (editor prefill for events without stored text)."""
    from iseql.compiler import _load_model, _normalized_model, render_iseql
    return render_iseql(_normalized_model(_load_model(model_json)))


_STRICTNESS = {"<=", "<", ">=", ">", "≤", "≥", "⩽", "⩾"}


def _compile_model_result(model: dict, condition: str | None = None) -> dict:
    """Compile a model (already parsed/loaded) into {iseql, sql, model}.

    Named δ/ε/ρ keys resolve per-detect; for the preview they are treated as
    unbounded (None) since no detection deltas are available.
    """
    from iseql.compiler import compile_event as _compile
    from iseql.compiler import render_iseql, _normalized_model
    named = {
        v
        for entry in (model.get("delta_map") or {}).values()
        if isinstance(entry, dict)
        for v in entry.values()
        # Named δ/ε/ρ keys resolve per-detect; strictness strings are literal.
        if isinstance(v, str) and v not in _STRICTNESS
    }
    preview_deltas = {k: None for k in named}
    conn = _config_conn()
    try:
        audio_predicates = _resolve_audio_predicates(conn)
        predicate_vocab = _resolve_predicate_vocab(conn)
    finally:
        conn.close()
    iseql, sql = _compile(model, preview_deltas, "__analysis__", fps="__fps__",
                          audio_predicates=audio_predicates,
                          predicate_vocab=predicate_vocab,
                          condition=condition)
    return {"iseql": render_iseql(_normalized_model(model)), "sql": sql, "model": model}


def compile_query(query: str, name: str = "event", delta_unit: str = "seconds",
                  condition: str | None = None) -> dict:
    """Compile an ISEQL query written as text into (iseql, sql, model).

    Raises ValueError with a human-readable message on syntax/compile errors.
    ``delta_unit`` is the unit of the authored δ/ε thresholds (seconds/frames).
    ``condition`` (A/B/C) restricts the allowed predicate modality.
    """
    from iseql.parser import parse_iseql
    model = parse_iseql(query, name=name, delta_unit=delta_unit)
    return _compile_model_result(model, condition)


def compile_model(model_json: str | dict, condition: str | None = None) -> dict:
    """Compile an event model directly into (iseql, sql, model).

    Used by the visual builder, which edits the model in place (groups,
    set-expression tree, intervals, operators) and wants the resulting
    SQL/ISEQL without round-tripping through text.
    """
    from iseql.compiler import _load_model, _normalized_model
    model = _normalized_model(_load_model(model_json))
    return _compile_model_result(model, condition)


def vocabulary() -> dict:
    """Predicate and participant-class vocabulary for the visual event builder.

    Visual predicates come from ``relation_vocab.relation_classids`` (name ->
    participant signature); audio predicates from ``audio_taxonomy.classes``.
    """
    from service.impl.config_store_service_impl import ConfigStoreServiceImpl
    from service.relation_vocab import signature_slots
    conn = _config_conn()
    try:
        store = ConfigStoreServiceImpl()
        relation_vocab = store.get_section(conn, "relation_vocab") or {}
        audio_taxonomy = store.get_section(conn, "audio_taxonomy") or {}
    finally:
        conn.close()

    predicates: list[dict] = []
    for name, sig in (relation_vocab.get("relation_classids") or []):
        predicates.append({
            "name": str(name),
            "modality": "visual",
            "args": signature_slots(str(sig)),
        })
    for name in (audio_taxonomy.get("classes") or []):
        predicates.append({"name": str(name), "modality": "audio", "args": []})

    participant_classes: set[str] = set()
    for p in predicates:
        for slot in p["args"]:
            participant_classes.update(slot)
    return {
        "predicates": predicates,
        "participant_classes": sorted(participant_classes),
    }
