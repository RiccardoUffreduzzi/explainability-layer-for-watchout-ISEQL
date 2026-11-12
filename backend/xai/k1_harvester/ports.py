"""K1's ports and the snapshot types they return.

The core reaches WatchOut only through ``WatchOutReader`` and time only through ``Clock``.
``WatchOutReader`` bundles three ports: ``WatchOutRecords`` (database rows),
``DetectionSource`` (WatchOut's detections, with the compiled rule and the lineage of
each row) and ``CodeFacts`` (values that live only in WatchOut's code).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol, Union

from xai.contract.ids import RowValue
from xai.contract.model import Condition, Modality, TimeUnit
from xai.contract.primitives import SourceRef, Stage

ModelForm = Literal["F1", "F2", "F3"]
"""How a rule is stored: F1 flat chain, F2 ``set_expression`` over groups, F3 ``set_side`` intervals."""

ParamsOrigin = Literal["rule_defaults", "saved_by_gui"]
ParamValue = int | float | str
"""A parameter as written: a number, ``inf`` or a strictness operator."""

ParamName = Literal["delta", "epsilon", "zeta", "eta", "rho"]
ParamOrigin = Literal["literal", "named_key", "template_geometry", "engine_default"]

IntervalTable = Literal["VisualPerInterval", "AudioPerInterval"]


# analysis and rules


@dataclass(frozen=True)
class AnalysisSnapshot:
    """One ``Analyses`` row. Columns missing in older databases are None."""

    analysis_id: str
    condition: str
    stage: str
    vlm_provider: str | None
    model: str | None
    audio_provider: str | None
    audio_model: str | None
    audio_quantization: str | None
    sampling_rate: int | None
    audio_window: float | None
    audio_hop: float | None

    @property
    def record(self) -> str:
        """``record_id`` prefix of the SourceRefs pointing to this row: ``Analyses/<id>``."""
        return f"Analyses/{self.analysis_id}"

    @property
    def fps(self) -> int | None:
        return self.sampling_rate if self.sampling_rate else None


@dataclass(frozen=True)
class RuleSnapshot:
    """One ``EventSpec`` row, with its model already parsed."""

    event_type: str
    condition: Condition
    model: Mapping[str, Any]

    @property
    def ref(self) -> str:
        """``<event>/<condition>``, e.g. ``handoff/A``."""
        return f"{self.event_type}/{self.condition}"

    def pointer(self, path: str) -> str:
        """The rule and a part of its model, e.g. ``handoff/A#/intervals/0``."""
        return f"{self.ref}#{path}"

    def source(self, path: str | None = None) -> SourceRef:
        """SourceRef of the whole rule, or of the model part at ``path``."""
        record = self.ref if path is None else self.pointer(path)
        return SourceRef(stage=Stage.ISEQL, record_id=f"EventSpec/{record}", mode="read")


@dataclass(frozen=True)
class ParamsSnapshot:
    """Detection parameters as written, before WatchOut converts them.

    ``rule_defaults`` merges every rule's ``default_deltas_for`` the way the GUI does
    (later rules win); ``saved_by_gui`` comes from ``Analyses.DeltasJson``.
    """

    origin: ParamsOrigin
    unit: TimeUnit
    """Unit of the numbers; WatchOut turns seconds into frames before compiling."""
    values: Mapping[str, ParamValue]
    analysis_id: str | None = None
    """Analysis whose ``DeltasJson`` was read (``saved_by_gui`` only)."""
    rule_defaults: Mapping[str, Mapping[str, ParamValue]] = field(default_factory=dict)
    """Rule ref -> that rule's own defaults (``rule_defaults`` only)."""
    provider: Mapping[str, str] = field(default_factory=dict)
    """Key -> ref of the rule whose default won the merge (``rule_defaults`` only)."""

    def source_for(self, key: str, rule_ref: str) -> SourceRef:
        """Where a named key's value comes from, as seen by the rule being explained.

        For defaults: the rule's own text if it yields the merged value,
        otherwise the text of the rule that won the merge.
        """
        if self.origin == "saved_by_gui":
            return SourceRef(
                stage=Stage.CONFIG,
                record_id=f"Analyses/{self.analysis_id}/DeltasJson/deltas.{key}",
                mode="read",
            )
        own = self.rule_defaults.get(rule_ref, {})
        ref = rule_ref if key in own and own[key] == self.values.get(key) else self.provider[key]
        return SourceRef(stage=Stage.ISEQL, record_id=f"EventSpec/{ref}#/iseql_text", mode="read")

    def origin_source(self, rule_ref: str) -> SourceRef:
        """Source of ``contract_meta.params_origin``."""
        if self.origin == "saved_by_gui":
            return SourceRef(
                stage=Stage.CONFIG, record_id=f"Analyses/{self.analysis_id}/DeltasJson", mode="read"
            )
        return SourceRef(stage=Stage.ISEQL, record_id=f"EventSpec/{rule_ref}#/iseql_text", mode="read")


@dataclass(frozen=True)
class Vocabulary:
    """``AppConfig.relation_vocab`` and ``AppConfig.audio_taxonomy``."""

    signatures: Mapping[str, str]
    """Relation -> stored signature, e.g. ``(PersonID, ObjectID)``."""
    slots: Mapping[str, tuple[tuple[str, ...], ...]]
    """Relation -> argument slots, parsed with WatchOut's ``signature_slots``."""
    descriptions: Mapping[str, str]
    """Relation -> description shown to the VLM."""
    audio_classes: tuple[str, ...]
    audio_keywords: Mapping[str, tuple[str, ...]]
    """Audio class -> the words WatchOut maps to it when it reads the audio model's answer."""
    relation_vocab_updated_at: str | None
    audio_taxonomy_updated_at: str | None


@dataclass(frozen=True)
class VlmDefaults:
    """``VLMClient.generation_defaults()``: the temperature and seed every VLM call uses."""

    temperature: float
    seed: int


# rule structure, as WatchOut's compiler plan describes it


@dataclass(frozen=True)
class SelectionAlternative:
    """One alternative of a selection: its predicates and the classes allowed per argument slot."""

    predicates: tuple[str, ...]
    arg_classes: Mapping[str, tuple[str, ...]]
    """Slot (``"1"``, ``"2"``) -> allowed classes."""


@dataclass(frozen=True)
class BranchInterval:
    """One interval (selection) of a branch."""

    index: int
    """Position in ``model.intervals``."""
    alias: str
    """Branch-local variable (``M1``..``Mn``), named as the compiler does."""
    modality: Modality
    """The table the compiler reads: ``VisualPerInterval`` (visual) or ``AudioPerInterval`` (audio)."""
    selection: tuple[SelectionAlternative, ...]
    """The selection as the compiler reads it; multiple alternatives are OR-ed."""
    text: str
    """Fragment rendered by WatchOut, e.g. ``σ_{pred="carrying"}(M1)``."""


@dataclass(frozen=True)
class BranchCondition:
    """A cross-condition of a branch, using branch-local aliases."""

    index: int
    """Position in ``model.cross_conditions``."""
    left: str
    """``<alias>.<attribute>``, e.g. ``M1.arg1``; the end, for a duration."""
    op: str
    right: str
    """The start, for a duration."""
    duration_value: int | float | None
    """``value`` in ``(left − right) op value`` for a duration; None otherwise."""
    duration_unit: TimeUnit | None
    """Unit of ``duration_value``, i.e. the domain of the two attributes."""
    text: str


@dataclass(frozen=True)
class ProjectedField:
    """A field a branch projects, at its position in the branch's result row."""

    field: str
    """``<alias>.<attribute>``, e.g. ``M1.arg1`` or ``M2.et``."""
    kind: str
    """``arg1``.., ``st``, ``et``, ``sf``, ``ef``."""
    arg_class: str | None
    """Class WatchOut names an argument column after."""


@dataclass(frozen=True)
class Extent:
    """Row keys holding the event's start and end, as ``detect_event`` finds them."""

    start_seconds: str | None
    end_seconds: str | None
    start_frames: str | None
    end_frames: str | None


@dataclass(frozen=True)
class Branch:
    """One chain of the rule: a group (F2), a set side (F3) or the whole rule (F1)."""

    name: str
    side: str | None
    """Side the compiler uses to look up ``delta_map`` and ``operator_overrides``."""
    intervals: tuple[BranchInterval, ...]
    conditions: tuple[BranchCondition, ...]
    projection: tuple[str, ...]
    projection_pointer: str
    projection_text: str
    fields: tuple[ProjectedField, ...]
    """``projection`` with the kind and class of each field."""
    extent: Extent
    """The branch's own start and end fields (projected fields, not row keys)."""

    def interval(self, alias: str) -> BranchInterval | None:
        return next((bi for bi in self.intervals if bi.alias == alias), None)


@dataclass(frozen=True)
class SetOperationLayout:
    """An internal node of ``set_expression`` (or the F3 set operator)."""

    op: str
    pointer: str
    children: tuple[Union["SetOperationLayout", str], ...]
    """Nested operations, or names of the branches they combine."""


@dataclass(frozen=True)
class ResultColumn:
    """A column of the rows WatchOut returns for the rule."""

    label: str
    kind: str
    """``arg1``.., ``st``, ``et``, ``sf``, ``ef``."""
    fields: Mapping[str, str]
    """Branch name -> projected field that fills this column there."""
    arg_class: str | None


@dataclass(frozen=True)
class RuleLayout:
    """The rule as the compiler executes it."""

    form: ModelForm
    branches: tuple[Branch, ...]
    set_operation: SetOperationLayout | None
    multiset: bool
    """Branches combined by a set operation with kind-aligned columns (F2 with ``op``)."""
    columns: tuple[ResultColumn, ...] | None
    """None when a column holds a different field on each side (F3): a row is then read by its side."""
    columns_problem: str | None
    extent: Extent

    def branch(self, name: str) -> Branch:
        return next(b for b in self.branches if b.name == name)


@dataclass(frozen=True)
class ResolvedParam:
    """An operator parameter, both as written and as the compiler applies it."""

    name: ParamName
    origin: ParamOrigin
    key: str | None
    """Named key (``named_key`` only)."""
    value: ParamValue
    unit: TimeUnit | None
    engine_value: ParamValue
    pointer: str | None
    """JSON pointer to the ``delta_map`` entry (``literal`` and ``named_key`` only)."""


@dataclass(frozen=True)
class ResolvedOperator:
    name: str
    resolution: Literal["override", "geometry"]
    resolution_detail: str
    override_index: int | None
    delta_map_key: str | None
    compare_domain: TimeUnit
    params: tuple[ResolvedParam, ...]
    text: str


# detection and evidence


@dataclass(frozen=True)
class WitnessArg:
    position: int
    """The argument position the rule reads"""
    class_id: int | None
    class_name: str | None


@dataclass(frozen=True)
class WitnessInterval:
    alias: str
    """``M1``, ``M2``... in the witness's branch"""
    table: IntervalTable
    row_id: int
    """``RelationID`` or ``AudioIntervalID``"""
    args: tuple[WitnessArg, ...]

    @property
    def key(self) -> tuple[str, int]:
        return self.table, self.row_id


@dataclass(frozen=True)
class Witness:
    """One combination of interval rows of one branch that produces the row"""

    branch: str
    intervals: tuple[WitnessInterval, ...]

    @property
    def keys(self) -> frozenset[tuple[str, int]]:
        return frozenset(i.key for i in self.intervals)


@dataclass(frozen=True)
class DetectedRow:
    values: Mapping[str, RowValue]
    """The row under its column labels, as the detection returns it."""
    gui_values: Mapping[str, RowValue]
    """Row as ``detect_event`` passes it to the GUI (frames added, times formatted)."""
    witnesses: tuple[Witness, ...]
    """The interval rows behind the row: one witness per combination that produces it."""

    @property
    def branches(self) -> tuple[str, ...]:
        """Names of the branches with a witness, each once, in witness order."""
        return tuple(dict.fromkeys(w.branch for w in self.witnesses))


@dataclass(frozen=True)
class DetectionRecord:
    """One rule run on one analysis: the compiled rule, the parameters and the rows."""

    rule: RuleSnapshot
    analysis_id: str
    layout: RuleLayout
    operators: Mapping[str, tuple[ResolvedOperator, ...]]
    """Branch name -> operators between consecutive intervals, in order."""
    params: ParamsSnapshot
    text: str
    """The rule in ISEQL notation with the parameters as written."""
    rows: tuple[DetectedRow, ...]

    @property
    def record(self) -> str:
        """``record_id`` prefix of the SourceRefs pointing to a row: ``detection/<rule>@<analysis>``."""
        return f"detection/{self.rule.ref}@{self.analysis_id}"


@dataclass(frozen=True)
class VisualIntervalRow:
    relation_id: int
    start_frame: int
    end_frame: int
    relation_type: str


@dataclass(frozen=True)
class FrameDescriptionRow:
    """One ``VisualPerFrame`` row: how the VLM described a subject in a frame and a cell."""

    frame: int
    class_id: int
    block: int
    description: str


@dataclass(frozen=True)
class AudioIntervalRow:
    interval_id: int
    start_frame: int
    end_frame: int
    audio_class: str
    confidence: float | None


# errors raised by the reader


class ParamsMissing(Exception):
    """The parameters lack keys required by the condition's rules."""

    def __init__(self, missing: Sequence[str]) -> None:
        super().__init__(", ".join(missing))
        self.missing = tuple(missing)


class DetectionNotPossible(Exception):
    """WatchOut itself couldn't run this detection"""


class RuleNotSupported(Exception):
    """The rule has a form K1 does not explain: nested groups or query references (F4)."""


class EngineError(RuntimeError):
    """WatchOut's engine failed: an infrastructure problem, not missing data."""


# ports


class WatchOutRecords(Protocol):
    """Rows from WatchOut's database: analyses, rules, parameters, configuration, intervals."""

    def analysis(self, analysis_id: str) -> AnalysisSnapshot | None: ...

    def rule(self, event_type: str, condition: Condition) -> RuleSnapshot | None: ...

    def rules(self, condition: Condition) -> list[RuleSnapshot]: ...

    def saved_params(self, analysis_id: str) -> ParamsSnapshot | None: ...

    def default_params(self) -> ParamsSnapshot:
        """The parameters the GUI pre-fills, as WatchOut's ``default_params`` merges them."""
        ...

    def vocabulary(self) -> Vocabulary | None: ...

    def visual_intervals(self, relation_ids: Sequence[int]) -> list[VisualIntervalRow]: ...

    def audio_intervals(self, interval_ids: Sequence[int]) -> list[AudioIntervalRow]: ...

    def frame_descriptions(self, analysis_id: str, class_ids: Sequence[int]) -> list[FrameDescriptionRow]:
        """``VisualPerFrame`` rows of those subjects that have a text, by ClassID, Frame, Block.

        Empty when the database has no such table.
        """
        ...


class DetectionSource(Protocol):
    """WatchOut's detections, with the compiled rule, the params and each row's lineage."""

    def detection(
        self, rule: RuleSnapshot, analysis: AnalysisSnapshot, params: ParamsSnapshot
    ) -> DetectionRecord:
        """The rows ``detect_event`` shows for the rule.

        Raises ``ParamsMissing``, ``DetectionNotPossible``, ``RuleNotSupported`` or ``EngineError``.
        """
        ...

    def rule_text(self, rule: RuleSnapshot, values: Mapping[str, ParamValue]) -> str:
        """The rule in ISEQL notation with these parameter values"""
        ...


class CodeFacts(Protocol):
    """Values that live only in WatchOut's code, read through its methods."""

    def vlm_defaults(self) -> VlmDefaults: ...

    def merge_tolerance_samples(self) -> int:
        """Largest gap, in sampled frames, that still merges two sightings into one interval."""
        ...

    def constant_audio_confidence(self, provider: str) -> float | None:
        """The confidence written for every interval of a provider with no score; None otherwise."""
        ...


class WatchOutReader(WatchOutRecords, DetectionSource, CodeFacts, Protocol):
    """Everything K1 reads from WatchOut, over a single read-only connection."""


class Clock(Protocol):
    def now(self) -> datetime: ...
