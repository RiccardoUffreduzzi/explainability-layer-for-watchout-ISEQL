"""The two ports of K1 and the snapshot types they return.

The core sees WatchOut only through ``WatchOutReader`` and the time only through
``Clock``. The types below are plain
immutable values: the core can be tested with snapshots built by hand, and only
``xai.adapters.watchout`` knows how they are read from WatchOut.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol, Union

from xai.contract.ids import RowValue
from xai.contract.model import Condition, TimeUnit
from xai.contract.primitives import SourceRef, Stage

ModelForm = Literal["F1", "F2", "F3"]
"""How a rule is stored: F1 flat chain, F2 ``set_expression`` of groups, F3 ``set_side`` intervals."""

ParamsOrigin = Literal["rule_defaults", "saved_by_gui"]
ParamValue = int | float | str
"""A detection parameter as written: a number, ``inf`` or a strictness operator."""

ParamName = Literal["delta", "epsilon", "zeta", "eta", "rho"]
ParamOrigin = Literal["literal", "named_key", "template_geometry", "engine_default"]


# --------------------------------------------------------------------------- analysis and rules


@dataclass(frozen=True)
class AnalysisSnapshot:
    """One ``Analyses`` row. Columns that the table does not have (older databases) are None."""

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
        """``store`` of the SourceRefs that point to this row."""
        return f"Analyses:{self.analysis_id}"

    @property
    def fps(self) -> int | None:
        """The declared fps, or None when ``SamplingRate`` is missing or zero."""
        return self.sampling_rate if self.sampling_rate else None


@dataclass(frozen=True)
class RuleSnapshot:
    """One ``EventSpec`` row with its model already parsed."""

    event_type: str
    condition: Condition
    model: Mapping[str, Any]

    @property
    def ref(self) -> str:
        """``<event>/<condition>``, e.g. ``handoff/A``."""
        return f"{self.event_type}/{self.condition}"

    def pointer(self, path: str) -> str:
        """``record_id`` of a part of the model: ``handoff/A#/intervals/0``."""
        return f"{self.ref}#{path}"

    def source(self, path: str | None = None) -> SourceRef:
        """SourceRef of the rule (``path`` None) or of a part of its model."""
        record_id = self.ref if path is None else self.pointer(path)
        return SourceRef(stage=Stage.ISEQL, store="EventSpec", record_id=record_id, mode="read")


@dataclass(frozen=True)
class ParamsSnapshot:
    """The parameters of a detection, as written before WatchOut converts them.

    ``rule_defaults``: the union of ``default_deltas_for`` over every rule, merged as
    the GUI does (later rules win). ``saved_by_gui``: ``Analyses.DeltasJson``.
    """

    origin: ParamsOrigin
    unit: TimeUnit
    """Unit of the numeric values; WatchOut converts seconds to frames before compiling."""
    values: Mapping[str, ParamValue]
    analysis_id: str | None = None
    """Analysis whose ``DeltasJson`` was read (``saved_by_gui`` only)."""
    rule_defaults: Mapping[str, Mapping[str, ParamValue]] = field(default_factory=dict)
    """Rule ref -> that rule's own defaults (``rule_defaults`` only)."""
    provider: Mapping[str, str] = field(default_factory=dict)
    """Key -> ref of the rule whose default the merge kept (``rule_defaults`` only)."""

    def source_for(self, key: str, rule_ref: str) -> SourceRef:
        """Where the value of a named key was read, seen from the rule being explained.

        For defaults it is the explained rule's own text when that text gives the
        merged value, otherwise the text of the rule the merge took it from.
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
    """Relation -> signature as stored, e.g. ``(PersonID, ObjectID)``."""
    slots: Mapping[str, tuple[tuple[str, ...], ...]]
    """Relation -> argument slots, read with WatchOut's ``signature_slots``."""
    descriptions: Mapping[str, str]
    """Relation -> description given to the VLM."""
    audio_classes: tuple[str, ...]
    relation_vocab_updated_at: str | None


@dataclass(frozen=True)
class VlmDefaults:
    """Defaults of ``VLMClient.__init__``, the values the analysis uses."""

    temperature: float
    seed: int


@dataclass(frozen=True)
class BackendVersion:
    text: str
    source: SourceRef


# --------------------------------------------------------------------------- rule structure


@dataclass(frozen=True)
class SelectionAlternative:
    """One alternative of a selection: predicates and admitted classes per argument slot."""

    predicates: tuple[str, ...]
    arg_classes: Mapping[str, tuple[str, ...]]
    """Argument slot (``"1"``, ``"2"``) -> admitted classes."""


@dataclass(frozen=True)
class BranchInterval:
    """An interval (selection) of a branch."""

    index: int
    """Position in ``model.intervals``."""
    alias: str
    """Variable local to the branch, ``M1``..``Mn``, as the compiler assigns it."""
    selection: tuple[SelectionAlternative, ...]
    """The selection as the compiler reads it; several alternatives are a disjunction."""
    text: str
    """Fragment rendered by WatchOut's renderer, e.g. ``σ_{pred="carrying"}(M1)``."""


@dataclass(frozen=True)
class BranchCondition:
    """A cross-condition of a branch, with aliases local to the branch."""

    index: int
    """Position in ``model.cross_conditions``."""
    left: str
    """``<alias>.<attribute>``, e.g. ``M1.arg1``; for a duration, the end."""
    op: str
    right: str
    """For a duration, the start."""
    duration_value: int | float | None
    """``value`` of a duration condition, ``(left − right) op value``; None otherwise."""
    duration_unit: TimeUnit | None
    """Unit of ``duration_value``: the domain of the two attributes."""
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
    """Nested operations, or the names of the branches they combine."""


@dataclass(frozen=True)
class ResultColumn:
    """A column of the rows WatchOut returns for the rule."""

    label: str
    kind: str
    """``arg1``.., ``st``, ``et``, ``sf``, ``ef``."""
    fields: Mapping[str, str]
    """Branch name -> projected field that fills this column in that branch."""
    arg_class: str | None


@dataclass(frozen=True)
class Extent:
    """Row keys of the event's start and end, as ``detect_event`` finds them."""

    start_seconds: str | None
    end_seconds: str | None
    start_frames: str | None
    end_frames: str | None


@dataclass(frozen=True)
class SideField:
    """A field a set side projects, at its position in the result row."""

    field: str
    kind: str
    """``arg1``.., ``st``, ``et``, ``sf``, ``ef``."""
    arg_class: str | None


@dataclass(frozen=True)
class SideColumns:
    """How a row of one set side of an F3 rule fills the result columns.

    The compiler aligns the two sides by position and pads the shorter one with
    NULLs, and the columns take the names of the left side: a column holds a
    different kind in each side, so it is read only once the row's side is known.
    """

    fields: tuple[SideField, ...]
    """The side's projected fields, in the order of the result columns."""
    extent: Extent
    """The fields with the side's start and end (projected fields, not row keys)."""


@dataclass(frozen=True)
class RuleLayout:
    """The rule as the compiler executes it."""

    form: ModelForm
    branches: tuple[Branch, ...]
    set_operation: SetOperationLayout | None
    multiset: bool
    """Branches combined by a set operation with kind-aligned columns (F2 with ``op``)."""
    columns: tuple[ResultColumn, ...] | None
    """None when the columns cannot be traced to the branches (``columns_problem`` says why)."""
    columns_problem: str | None
    extent: Extent
    side_columns: Mapping[str, SideColumns] = field(default_factory=dict)
    """F3 with ``columns`` None: each side's columns by position; the row tells its side."""


@dataclass(frozen=True)
class ResolvedParam:
    """One operator parameter, as written and as the compiler applies it."""

    name: ParamName
    origin: ParamOrigin
    key: str | None
    """Named key, for ``named_key``."""
    value: ParamValue
    unit: TimeUnit | None
    engine_value: ParamValue
    pointer: str | None
    """JSON pointer of the ``delta_map`` entry, for ``literal`` and ``named_key``."""


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


# --------------------------------------------------------------------------- detection and evidence


@dataclass(frozen=True)
class DetectedRow:
    values: Mapping[str, RowValue]
    """The row as ``run_sql_detection`` returns it."""
    gui_values: Mapping[str, RowValue]
    """The row as ``detect_event`` hands it to the GUI (frames added, times formatted)."""


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


# --------------------------------------------------------------------------- errors the reader raises


class ParamsMissing(Exception):
    """The parameters lack keys that the rules of the condition need."""

    def __init__(self, missing: Sequence[str]) -> None:
        super().__init__(", ".join(missing))
        self.missing = tuple(missing)


class DetectionNotPossible(Exception):
    """WatchOut itself could not run this detection (e.g. seconds without an fps)."""


class EngineError(RuntimeError):
    """WatchOut's engine reported an error: an infrastructure failure, not a data gap."""


# --------------------------------------------------------------------------- ports


class WatchOutReader(Protocol):
    """Everything K1 reads from WatchOut, over one read-only connection."""

    def analysis(self, analysis_id: str) -> AnalysisSnapshot | None: ...

    def rule(self, event_type: str, condition: Condition) -> RuleSnapshot | None: ...

    def rules(self, condition: Condition) -> list[RuleSnapshot]: ...

    def saved_params(self, analysis_id: str) -> ParamsSnapshot | None: ...

    def default_params(self) -> ParamsSnapshot: ...

    def vocabulary(self) -> Vocabulary | None: ...

    def detect(self, rule: RuleSnapshot, analysis: AnalysisSnapshot, params: ParamsSnapshot) -> Detection: ...

    def rule_layout(self, rule: RuleSnapshot, form: ModelForm) -> RuleLayout: ...

    def resolve_operator(
        self,
        rule: RuleSnapshot,
        form: ModelForm,
        branch: Branch,
        pair_index: int,
        params: ParamsSnapshot,
        fps: int | None,
    ) -> ResolvedOperator: ...

    def render_rule(self, rule: RuleSnapshot, params: ParamsSnapshot) -> str: ...

    def visual_intervals(self, analysis_id: str, predicates: set[str]) -> list[VisualIntervalRow]: ...

    def participants(self, relation_ids: Sequence[int]) -> list[ParticipantRow]: ...

    def audio_intervals(self, analysis_id: str, classes: set[str]) -> list[AudioIntervalRow]: ...

    def vlm_defaults(self) -> VlmDefaults: ...

    def backend_version(self) -> BackendVersion | None: ...


class Clock(Protocol):
    def now(self) -> datetime: ...
