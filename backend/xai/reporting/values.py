"""The table of the values a plan cites, read from the source of truth.

The plan has only IDs and JSON pointers. For every ``ref`` of the steps the table has the values
the LLM may cite, each with a name made of
the reference and the field (``iv_v59.start``, ``c_s1_op1.δ``), the text the renderer writes
for it and the JSON pointer it is read from.
The entities are a table of their own: the LLM names them with VLM description.
The key frame (``kf_``) has two values, its time (``kf_108.at``) and its frame
(``kf_108.frame``): the LLM cites them, while its image is shown by the system (``figures``).
"""

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from xai.contract.ids import (
    CONSTRAINT_ID_PATTERN,
    ENTITY_ID_PATTERN,
    EVENT_ID_PATTERN,
    INTERVAL_ID_PATTERN,
    KEYFRAME_ID_PATTERN,
    STEP_ID_PATTERN,
    TERM_ID_PATTERN,
)
from xai.contract.plan import PlanStep
from xai.contract.report import ValueForm
from xai.contract.source_of_truth import SourceOfTruth, source_of_truth_to_data
from xai.reporting.catalogue import TimeFormat, ValueLabels
from xai.reporting.failure import ReportFailure

INFINITE: Final = "inf"
NOT_AVAILABLE: Final = "not available"
"""What the reader sees for a value the source of truth does not have."""

_EVENT = re.compile(EVENT_ID_PATTERN)
_INTERVAL = re.compile(INTERVAL_ID_PATTERN)
_ENTITY = re.compile(ENTITY_ID_PATTERN)
_CONSTRAINT = re.compile(CONSTRAINT_ID_PATTERN)
_TERM = re.compile(TERM_ID_PATTERN)
_STEP = re.compile(STEP_ID_PATTERN)
KEY_FRAME = re.compile(KEYFRAME_ID_PATTERN)
_LIMIT_POINTER = re.compile(r"^#/knowledge_limits/\d+$")
_CONSTRAINT_POINTER = re.compile(r"^#/rule/constraints/(\d+)/payload/(.+)$")

DEFINITION_FORM: Final[Mapping[str, ValueForm]] = {
    "predicate": "quote",
    "audio_class": "quote",
    "operator": "code",
    "comparison": "code",
    "event_model": "block",
}
"""How a definition of the glossary is shown"""


@dataclass(frozen=True)
class Value:
    """One value the LLM may cite as ``{name}``."""

    name: str
    step_ref: str
    """The reference of the plan the value belongs to: an ID or a JSON pointer of a step."""
    pointer: str
    """Where the value is in the source of truth."""
    text: str | None
    """What the reader sees; null when the source of truth has no value."""
    form: ValueForm
    label: str | None = None
    """What the value is"""
    reason: str | None = None
    """Why there is no value, in words, when ``text`` is null."""

    @property
    def written(self) -> str:
        """The text the renderer writes in place of the name."""
        return NOT_AVAILABLE if self.text is None else self.text

    def for_llm(self) -> str | dict[str, Any]:
        if self.text is None:
            return {"value": None, "reason": self.reason or NOT_AVAILABLE}
        if self.label is not None:
            return {"value": self.text, "label": self.label}
        return self.text


@dataclass(frozen=True)
class EntityRow:
    entity_id: str
    class_: str
    description: str | None
    """The VLM's description of the entity"""
    label: str
    """What the reader sees when the LLM cites ``{ent_3}``: the class and its number, e.g. ``person 1``."""
    roles: tuple[str, ...]
    """The fields of the detection row the entity fills, e.g. ``M1.arg1``."""
    pointer: str

    def for_llm(self) -> dict[str, Any]:
        return {
            "class": self.class_,
            "description": self.description,
            "label": self.label,
            "roles": list(self.roles),
        }


@dataclass(frozen=True)
class ValueTable:
    values: tuple[Value, ...]
    """In the order the steps cite them."""
    entities: tuple[EntityRow, ...]

    def value(self, name: str) -> Value | None:
        return next((v for v in self.values if v.name == name), None)

    def entity(self, entity_id: str) -> EntityRow | None:
        return next((e for e in self.entities if e.entity_id == entity_id), None)

    def names(self) -> frozenset[str]:
        return frozenset(v.name for v in self.values)


def cited_refs(steps: Iterable[PlanStep]) -> tuple[str, ...]:
    """Every fact the steps cite, once, in order: refs, then slot pointers, readings and alternatives."""
    seen: dict[str, None] = {}
    for step in steps:
        for ref in step.refs:
            seen.setdefault(ref)
        for slot in (step.slots or {}).values():
            if slot is not None and not _STEP.fullmatch(slot):
                seen.setdefault(slot)
        for reading in step.readings or ():
            if reading.value_ref is not None:
                seen.setdefault(reading.value_ref)
        if step.term is not None:
            seen.setdefault(step.term)
        for term in step.alternatives or ():
            seen.setdefault(term)
    return tuple(seen)


# --------------------------------------------------------------------------- formats


def number(value: int | float) -> str:
    """An integer as it is, a float as Python writes it (``1.0``, ``2.5``)."""
    return str(value) if isinstance(value, int) else repr(float(value))


def seconds(value: int | float) -> str:
    """A duration in seconds, ``2 s`` or ``2.5 s``."""
    return f"{int(value)} s" if float(value).is_integer() else f"{float(value)!r} s"


def clock(value: float, time_format: TimeFormat = "m:ss") -> str:
    """Seconds from the start of the video as ``m:ss`` (``h:mm:ss`` past one hour); decimals are kept."""
    whole = int(value)
    fraction = round(value - whole, 3)
    hours, rest = divmod(whole, 3600)
    minutes, secs = divmod(rest, 60)
    text = f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"
    if fraction:
        text += f"{fraction:.3f}".removeprefix("0").rstrip("0")
    return text


def threshold(value: object, unit: str) -> str:
    """A threshold of an operator: ``∞`` or the number with the unit the engine compares in."""
    if value == INFINITE:
        return "∞"
    assert isinstance(value, int | float), value
    singular = unit.removesuffix("s") if value == 1 else unit
    return f"{number(value)} {singular}"


def _fps(value: Any) -> str:
    """``24 fps`` for a whole frame rate as a real number"""
    return f"{int(value)} fps" if float(value).is_integer() else f"{number(value)} fps"


def _hz(value: Any) -> str:
    return f"{number(value)} Hz"


FORMATS: Final[Mapping[str, Callable[[Any], str]]] = {
    "pipeline_config.sampling.source_fps": _fps,
    "pipeline_config.sampling.effective_hz": _hz,
    "pipeline_config.merge_tolerance_s": seconds,
    "pipeline_config.audio_window.window_s": seconds,
    "pipeline_config.audio_window.hop_s": seconds,
}
"""Values with a unit; any other number is written as it is."""


# --------------------------------------------------------------------------- the reader


class ValueReader:
    """Builds the table of one source of truth for the steps of one plan."""

    def __init__(
        self, document: SourceOfTruth, labels: ValueLabels, time_format: TimeFormat = "m:ss"
    ) -> None:
        self.document = document
        self.labels = labels
        self.time_format = time_format
        self.data = source_of_truth_to_data(document)
        self._intervals = {r.interval_id: i for i, r in enumerate(document.intervals)}
        self._entities = {e.entity_id: i for i, e in enumerate(document.entities)}
        self._constraints = {c.constraint_id: i for i, c in enumerate(document.rule.constraints)}
        self._terms = {g.term_id: i for i, g in enumerate(document.glossary)}

    def table(self, steps: Sequence[PlanStep]) -> ValueTable:
        values: dict[str, Value] = {}
        entities: dict[str, EntityRow] = {}

        def add(found: Iterable[Value]) -> None:
            for value in found:
                values.setdefault(value.name, value)

        seen: set[str] = set()
        for step in steps:
            refs = cited_refs([step])
            if step.fixed_text is not None:
                add([self._fixed_text(step)])
                # the sentence of a limit is its fixed text: the pointer to it needs no other value
                seen.update(r for r in refs[:1] if _LIMIT_POINTER.fullmatch(r))
            for ref in refs:
                if ref in seen:
                    continue
                seen.add(ref)
                if _ENTITY.fullmatch(ref):
                    row = self._entity(ref)
                    entities.setdefault(ref, row)
                    add([Value(ref, ref, row.pointer, row.label, "plain")])
                else:
                    add(self._values_of(ref))
        return ValueTable(values=tuple(values.values()), entities=tuple(entities.values()))

    # ------------------------------------------------------------------ by kind of reference

    def _values_of(self, ref: str) -> list[Value]:
        if _EVENT.fullmatch(ref):
            return self._event(ref)
        if _INTERVAL.fullmatch(ref):
            return self._interval(ref)
        if _CONSTRAINT.fullmatch(ref):
            return self._constraint(ref)
        if _TERM.fullmatch(ref):
            return self._term(ref)
        if KEY_FRAME.fullmatch(ref):
            return self._key_frame(ref)
        if ref.startswith("#/"):
            return self._pointer(ref)
        raise ReportFailure("UNSUPPORTED_REF", f"the plan cites {ref!r}, which no report reads yet")

    def _event(self, ref: str) -> list[Value]:
        event = self.document.event
        if ref != event.event_id:
            raise ReportFailure(
                "EVENT_MISMATCH", f"the plan cites {ref}, the source of truth is {event.event_id}"
            )
        # the label of the event is the term of its event model: the LLM cites that one
        model_id = Value(
            f"{ref}.model_id",
            ref,
            "#/event/model_id",
            event.model_id,
            "code",
            self.labels.fields.get("event.model_id"),
        )
        return [model_id, *self._anchor(ref, ref, ("event", "interval"))]

    def _key_frame(self, ref: str) -> list[Value]:
        """The time and the frame of the key frame of the event"""
        key_frame = self.document.event.key_frame
        if key_frame is None or ref != key_frame.keyframe_id:
            raise ReportFailure(
                "UNSUPPORTED_REF", f"the plan cites {ref}, which is not the key frame of the event"
            )
        path = ("event", "key_frame")
        return [
            self._leaf(f"{ref}.at", ref, (*path, "t_s"), "plain", self._clock),
            self._leaf(f"{ref}.frame", ref, (*path, "frame_index"), "plain", number),
        ]

    def _interval(self, ref: str) -> list[Value]:
        index = self._index(self._intervals, ref)
        record = self.document.intervals[index]
        path = ("intervals", index)
        confidence = self._leaf(f"{ref}.confidence", ref, (*path, "confidence"), "plain", number)
        return [
            *self._anchor(ref, ref, (*path, "anchor")),
            Value(f"{ref}.predicate", ref, _pointer(*path, "predicate"), record.predicate, "code"),
            confidence,
        ]

    def _constraint(self, ref: str) -> list[Value]:
        index = self._index(self._constraints, ref)
        node = self.document.rule.constraints[index]
        path = ("rule", "constraints", index)
        values = [Value(f"{ref}.text", ref, _pointer(*path, "text"), node.text, "code")]
        if node.kind == "temporal_operator":
            for position, param in enumerate(node.payload.params):
                pointer = _pointer(*path, "payload", "params", position, "engine_value")
                form: ValueForm
                if param.name in ("ζ", "η"):
                    text, form = str(param.engine_value), "code"
                else:
                    text, form = threshold(param.engine_value, param.compare_domain), "plain"
                values.append(Value(f"{ref}.{param.name}", ref, pointer, text, form))
        elif node.kind == "duration":
            payload = node.payload
            values.append(
                Value(
                    f"{ref}.value", ref, _pointer(*path, "payload", "value"), number(payload.value), "plain"
                )
            )
            values.append(
                Value(f"{ref}.unit", ref, _pointer(*path, "payload", "unit"), payload.unit, "plain")
            )
        return values

    def _term(self, ref: str) -> list[Value]:
        index = self._index(self._terms, ref)
        entry = self.document.glossary[index]
        path = ("glossary", index)
        definition = self._leaf(
            f"{ref}.definition", ref, (*path, "definition"), DEFINITION_FORM[entry.kind], str
        )
        if definition.form == "block" and definition.text is not None and "\n" not in definition.text:
            definition = Value(definition.name, ref, definition.pointer, definition.text, "code")
        return [Value(f"{ref}.term", ref, _pointer(*path, "term"), entry.term, "code"), definition]

    def _entity(self, ref: str) -> EntityRow:
        index = self._index(self._entities, ref)
        entity = self.document.entities[index]
        same_class = [e.entity_id for e in self.document.entities if e.class_ == entity.class_]
        roles = tuple(a.role for a in self.document.event.arguments if a.entity_id == ref)
        description = entity.vlm_description.text if entity.vlm_description is not None else None
        return EntityRow(
            entity_id=ref,
            class_=entity.class_,
            description=description,
            label=f"{entity.class_} {same_class.index(ref) + 1}",
            roles=roles,
            pointer=_pointer("entities", index),
        )

    def _fixed_text(self, step: PlanStep) -> Value:
        """The sentence of a limit or of the reinforcement, as the step copied it (K56-A1)."""
        assert step.fixed_text is not None
        first = step.refs[0] if step.refs else None
        if first is not None and _LIMIT_POINTER.fullmatch(first):
            ref, pointer = first, f"{first}/sentence"
        else:
            ref, pointer = step.step_id, "#/event/reinforcement/sentence"
        return Value(f"{step.step_id}.fixed_text", ref, pointer, step.fixed_text, "plain")

    # ------------------------------------------------------------------ JSON pointers

    def _pointer(self, ref: str) -> list[Value]:
        parts = _parts(ref)
        if parts == ("harvest_report", "missing_fields"):
            return [self._missing_fields(ref)]
        if parts == ("event", "reinforcement"):
            return [self._leaf("reinforcement.status", ref, (*parts, "status"), "plain", str)]
        if len(parts) == 3 and parts[:2] == ("event", "modality_detections"):
            index = int(parts[2])
            detection = self.document.event.modality_detections[index]
            name = f"modality_detections.{index}"
            return [
                Value(f"{name}.modality", ref, _pointer(*parts, "modality"), detection.modality, "plain"),
                *self._anchor(name, ref, (*parts, "interval")),
            ]
        match = _CONSTRAINT_POINTER.fullmatch(ref)
        if match is not None:
            return [self._constraint_field(ref, int(match.group(1)), match.group(2))]
        return self._generic(ref, parts)

    def _constraint_field(self, ref: str, index: int, field: str) -> Value:
        """A slot or a reading that points into a rule node: the value of the node with that name."""
        node = self.document.rule.constraints[index]
        named = [v for v in self._constraint(node.constraint_id) if v.pointer == ref]
        if named:
            value = named[0]
            return Value(value.name, ref, value.pointer, value.text, value.form)
        raw = self._resolve(_parts(ref))
        name = f"{node.constraint_id}.{field.replace('/', '.')}"
        text = number(raw) if isinstance(raw, int | float) and not isinstance(raw, bool) else str(raw)
        return Value(name, ref, ref, text, "code")

    def _generic(self, ref: str, parts: tuple[str, ...]) -> list[Value]:
        """Every field under the pointer, named by its path without ``contract_meta``."""
        try:
            target = self._resolve(parts)
        except (KeyError, IndexError, ValueError):
            raise ReportFailure("UNSUPPORTED_REF", f"{ref} is not in the source of truth") from None
        return [self._leaf(_name(path), ref, path, "plain", None) for path in _leaves(target, parts)]

    def _missing_fields(self, ref: str) -> Value:
        """The data K1 could not read, each with why: the list ``data_not_available`` speaks of."""
        details = _details(self.data)
        items = []
        for missing in self.document.harvest_report.missing_fields:
            what = self.labels.missing_fields.get(missing.path, missing.path)
            found = details.get((missing.path, missing.reason.value), [])
            why = (
                found[0]
                if len(found) == 1
                else self.labels.reasons.get(missing.reason.value, missing.reason.value)
            )
            items.append(f"{what} ({why})")
        text = "; ".join(items) if items else "nothing"
        return Value("missing_fields", ref, ref, text, "plain", self.labels.fields.get("missing_fields"))

    # ------------------------------------------------------------------ helpers

    def _anchor(self, name: str, ref: str, path: tuple[str | int, ...]) -> list[Value]:
        """Start and end of an interval; one time (``.at``) when it is a single analysed frame."""
        anchor = self._resolve(path)
        start, end = anchor["start_s"], anchor["end_s"]
        if start is not None and start == end and anchor["start_frame"] == anchor["end_frame"]:
            return [
                self._leaf(f"{name}.at", ref, (*path, "start_s"), "plain", self._clock),
                self._leaf(f"{name}.frame", ref, (*path, "start_frame"), "plain", number),
            ]
        return [
            self._leaf(f"{name}.start", ref, (*path, "start_s"), "plain", self._clock),
            self._leaf(f"{name}.end", ref, (*path, "end_s"), "plain", self._clock),
            self._leaf(f"{name}.start_frame", ref, (*path, "start_frame"), "plain", number),
            self._leaf(f"{name}.end_frame", ref, (*path, "end_frame"), "plain", number),
        ]

    def _clock(self, value: Any) -> str:
        return clock(float(value), self.time_format)

    def _leaf(
        self,
        name: str,
        ref: str,
        path: tuple[str | int, ...],
        form: ValueForm,
        fmt: Callable[[Any], str] | None,
    ) -> Value:
        raw = self._resolve(path)
        pointer = _pointer(*path)
        label = self.labels.fields.get(name)
        if raw is None:
            reason = self._reason(path)
            words = self.labels.reasons.get(reason, reason) if reason is not None else None
            return Value(name, ref, pointer, None, form, label, words)
        coded = self.labels.values.get(name)
        if coded is not None and isinstance(raw, str):
            text = coded.get(raw, raw)
        elif fmt is not None:
            text = fmt(raw)
        elif name in FORMATS:
            text = FORMATS[name](raw)
        elif isinstance(raw, bool):
            text = str(raw).lower()
        elif isinstance(raw, int | float):
            text = number(raw)
        else:
            text = str(raw)
        return Value(name, ref, pointer, text, form, label)

    def _resolve(self, path: Sequence[str | int]) -> Any:
        node: Any = self.data
        for part in path:
            node = node[int(part)] if isinstance(node, list) else node[part]
        return node

    def _reason(self, path: tuple[str | int, ...]) -> str | None:
        """The reason of a null field, from the ``unavailable`` map of its record or of an enclosing one."""
        for cut in range(len(path) - 1, -1, -1):
            relative = [str(p) for p in path[cut:]]
            if any(isinstance(p, int) or str(p).isdigit() for p in path[cut:]):
                return None
            holder = self._resolve(path[:cut])
            reasons = holder.get("unavailable") if isinstance(holder, dict) else None
            for size in range(len(relative), 0, -1):
                found = (reasons or {}).get(".".join(relative[:size]))
                if found is not None:
                    reason: str = found["reason"]
                    return reason
        return None

    @staticmethod
    def _index(index: Mapping[str, int], ref: str) -> int:
        if ref not in index:
            raise ReportFailure(
                "UNSUPPORTED_REF", f"the plan cites {ref}, which the source of truth does not have"
            )
        return index[ref]


def _pointer(*parts: str | int) -> str:
    return "#/" + "/".join(str(p).replace("~", "~0").replace("/", "~1") for p in parts)


def _parts(pointer: str) -> tuple[str, ...]:
    return tuple(p.replace("~1", "/").replace("~0", "~") for p in pointer.removeprefix("#/").split("/"))


def _name(path: Sequence[str | int]) -> str:
    """``contract_meta.pipeline_config.sampling.source_fps`` -> ``pipeline_config.sampling.source_fps``."""
    parts = [str(p) for p in path]
    if parts and parts[0] == "contract_meta":
        parts = parts[1:]
    return ".".join(parts)


def _leaves(target: Any, path: tuple[str | int, ...]) -> list[tuple[str | int, ...]]:
    """The paths of the scalar fields under ``path``; maps of sources and reasons are not values."""
    if isinstance(target, dict):
        return [
            leaf
            for key, value in target.items()
            if key not in ("sources", "unavailable")
            for leaf in _leaves(value, (*path, key))
        ]
    if isinstance(target, list):
        return [leaf for i, value in enumerate(target) for leaf in _leaves(value, (*path, i))]
    return [path]


def _details(data: Any) -> dict[tuple[str, str], list[str]]:
    """``(missing path, reason)`` -> the details K1 wrote for it"""
    found: dict[tuple[str, str], list[str]] = {}

    def walk(node: Any, pattern: str) -> None:
        if isinstance(node, dict):
            for dotted, unavailable in (node.get("unavailable") or {}).items():
                key = (f"{pattern}.{dotted}" if pattern else dotted, unavailable["reason"])
                details = found.setdefault(key, [])
                if unavailable["detail"] not in details:
                    details.append(unavailable["detail"])
            for key, value in node.items():
                if key not in ("unavailable", "sources"):
                    walk(value, f"{pattern}.{key}" if pattern else key)
        elif isinstance(node, list):
            for item in node:
                inner = f"{pattern}[*]"
                if pattern == "glossary" and isinstance(item, dict):
                    inner = f"glossary[kind={item.get('kind')}]"
                walk(item, inner)

    walk(data, "")
    return found
