"""K1's ports and the snapshot types they return.

The core reaches WatchOut only through ``WatchOutReader`` and time only through ``Clock``.
``WatchOutReader`` bundles three ports: ``WatchOutRecords`` (database rows), ``IseqlEngine``
(WatchOut's engine run on a rule) and ``CodeFacts`` (values that live only in WatchOut's code).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol, Union

from xai.contract.ids import RowValue
from xai.contract.model import Condition, TimeUnit
from xai.contract.primitives import SourceRef, Stage

ModelForm = Literal["F1", "F2", "F3"]
"""How a rule is stored: F1 flat chain, F2 ``set_expression`` over groups, F3 ``set_side`` intervals."""

ParamsOrigin = Literal["rule_defaults", "saved_by_gui"]
ParamValue = int | float | str
"""A parameter as written: a number, ``inf`` or a strictness operator."""

ParamName = Literal["delta", "epsilon", "zeta", "eta", "rho"]
ParamOrigin = Literal["literal", "named_key", "template_geometry", "engine_default"]


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
    def store(self) -> str:
        """Store name used by the SourceRefs pointing to this row."""
        return f"Analyses:{self.analysis_id}"

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
        """``record_id`` of a part of the model, e.g. ``handoff/A#/intervals/0``."""
        return f"{self.ref}#{path}"

    def source(self, path: str | None = None) -> SourceRef:
        """SourceRef of the whole rule, or of the model part at ``path``."""
        record_id = self.ref if path is None else self.pointer(path)
        return SourceRef(stage=Stage.ISEQL, store="EventSpec", record_id=record_id, mode="read")


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
                store=f"Analyses:{self.analysis_id}#DeltasJson",
                record_id=f"deltas.{key}",
                mode="read",
            )
        own = self.rule_defaults.get(rule_ref, {})
        ref = rule_ref if key in own and own[key] == self.values.get(key) else self.provider[key]
        return SourceRef(stage=Stage.ISEQL, store="EventSpec", record_id=f"{ref}#/iseql_text", mode="read")

    def origin_source(self, rule_ref: str) -> SourceRef:
        """Source of ``contract_meta.params_origin``."""
        if self.origin == "saved_by_gui":
            return SourceRef(
                stage=Stage.CONFIG, store=f"Analyses:{self.analysis_id}", record_id="DeltasJson", mode="read"
            )
        return SourceRef(
            stage=Stage.ISEQL, store="EventSpec", record_id=f"{rule_ref}#/iseql_text", mode="read"
        )


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
    relation_vocab_updated_at: str | None


@dataclass(frozen=True)
class VlmDefaults:
    """``VLMClient.__init__`` defaults, i.e. what the analysis actually uses."""

    temperature: float
    seed: int


@dataclass(frozen=True)
class BackendVersion:
    text: str
    source: SourceRef


# rule structure


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
class Extent:
    """Row keys holding the event's start and end, as ``detect_event`` finds them."""

    start_seconds: str | None
    end_seconds: str | None
    start_frames: str | None
    end_frames: str | None


@dataclass(frozen=True)
class SideField:
    """A field projected by a set side, at its position in the result row."""

    field: str
    kind: str
    """``arg1``.., ``st``, ``et``, ``sf``, ``ef``."""
    arg_class: str | None


@dataclass(frozen=True)
class SideColumns:
    """How a row from one set side of an F3 rule maps onto the result columns.

    The compiler aligns the two sides by position, pads the shorter one with NULLs
    and names the columns after the left side. So a column can hold something
    different on each side, and can only be read once the row's side is known.
    """

    fields: tuple[SideField, ...]
    """The side's projected fields, in result-column order."""
    extent: Extent
    """The side's start and end fields (projected fields, not row keys)."""


@dataclass(frozen=True)
class RuleLayout:
    """The rule as the compiler executes it."""

    form: ModelForm
    branches: tuple[Branch, ...]
    set_operation: SetOperationLayout | None
    multiset: bool
    """Branches combined by a set operation with kind-aligned columns (F2 with ``op``)."""
    columns: tuple[ResultColumn, ...] | None
    """None when the columns can't be traced back to the branches (see ``columns_problem``)."""
    columns_problem: str | None
    extent: Extent
    side_columns: Mapping[str, SideColumns] = field(default_factory=dict)
    """F3 with ``columns`` None: each side's columns by position; the row tells which side it is."""


@dataclass(frozen=True)
class RowColumns:
    """What each column of a detection row holds: the rule's columns, or its set side's."""

    columns: tuple[ResultColumn, ...]
    extent: Extent
    side: Branch | None = None
    """The set side the row was read as, if the columns depend on the side."""
    method: str | None = None
    """How the row's side was determined; None when the rule's columns fit every row."""


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
class DetectedRow:
    values: Mapping[str, RowValue]
    """Row as returned by ``run_sql_detection``."""
    gui_values: Mapping[str, RowValue]
    """Row as ``detect_event`` passes it to the GUI (frames added, times formatted)."""


@dataclass(frozen=True)
class Detection:
    rule_ref: str
    analysis_id: str
    rows: tuple[DetectedRow, ...]

    @property
    def store(self) -> str:
        return f"detection:{self.rule_ref}@{self.analysis_id}"


@dataclass(frozen=True)
class VisualIntervalRow:
    relation_id: int
    start_frame: int
    end_frame: int
    relation_type: str


@dataclass(frozen=True)
class ParticipantRow:
    relation_id: int
    class_id: int
    class_name: str


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
    """WatchOut itself couldn't run this detection (e.g. seconds without an fps)."""


class EngineError(RuntimeError):
    """WatchOut's engine failed: an infrastructure problem, not missing data."""


class RowNotReadable(Exception):
    """Can't tell what the columns of a row hold (``ROW_SCHEMA_AMBIGUOUS``)."""


# ports


class WatchOutRecords(Protocol):
    """Rows from WatchOut's database: analyses, rules, parameters, configuration, intervals."""

    def analysis(self, analysis_id: str) -> AnalysisSnapshot | None: ...

    def rule(self, event_type: str, condition: Condition) -> RuleSnapshot | None: ...

    def rules(self, condition: Condition) -> list[RuleSnapshot]: ...

    def saved_params(self, analysis_id: str) -> ParamsSnapshot | None: ...

    def default_params(self) -> ParamsSnapshot: ...

    def vocabulary(self) -> Vocabulary | None: ...

    def visual_intervals(self, analysis_id: str, predicates: set[str]) -> list[VisualIntervalRow]: ...

    def participants(self, relation_ids: Sequence[int]) -> list[ParticipantRow]: ...

    def audio_intervals(self, analysis_id: str, classes: set[str]) -> list[AudioIntervalRow]: ...


class IseqlEngine(Protocol):
    """WatchOut's ISEQL+ engine applied to a rule: rows, layout, operators, rendering."""

    def detect(self, rule: RuleSnapshot, analysis: AnalysisSnapshot, params: ParamsSnapshot) -> Detection: ...

    def rule_layout(self, rule: RuleSnapshot, form: ModelForm) -> RuleLayout: ...

    def row_columns(self, layout: RuleLayout, row: DetectedRow) -> RowColumns:
        """What each column of the row holds; raises ``RowNotReadable`` if that can't be told."""
        ...

    def resolve_operators(
        self, rule: RuleSnapshot, form: ModelForm, branch: Branch, params: ParamsSnapshot, fps: int | None
    ) -> tuple[ResolvedOperator, ...]:
        """Operators between consecutive intervals of the branch, in order."""
        ...

    def render_rule(self, rule: RuleSnapshot, params: ParamsSnapshot) -> str: ...


class CodeFacts(Protocol):
    """Values that live only in WatchOut's code."""

    def vlm_defaults(self) -> VlmDefaults: ...

    def backend_version(self) -> BackendVersion | None: ...


class WatchOutReader(WatchOutRecords, IseqlEngine, CodeFacts, Protocol):
    """Everything K1 reads from WatchOut, over a single read-only connection."""


class Clock(Protocol):
    def now(self) -> datetime: ...
