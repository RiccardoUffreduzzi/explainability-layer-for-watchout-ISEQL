"""Records of the contract draft produced by K1.

K2's fields (``knowledge_limits``, ``event.reinforcement``, ``contract_meta.contract_hash``)
are absent from the draft, not null: the models forbid unknown keys.
"""

from typing import Annotated, Final, Literal, Union, get_args

from pydantic import (
    ConfigDict,
    Field,
    NonNegativeInt,
    PositiveInt,
    StrictFloat,
    StrictInt,
    StringConstraints,
    model_validator,
)
from typing_extensions import TypeAliasType

from xai.contract.ids import (
    CONSTRAINT_ID_PATTERN,
    ENTITY_ID_PATTERN,
    EVENT_ID_PATTERN,
    INTERVAL_ID_PATTERN,
    TERM_ID_PATTERN,
    RowValue,
)
from xai.contract.primitives import (
    Anchor,
    ContractModel,
    NonEmptyStr,
    SourceMap,
    SourceRef,
    Timestamp,
    UnavailableMap,
    absent_if_none,
)
from xai.contract.reasons import CheckName, NoteCode, Reason

ContractVersion = Literal["0.1.0-k1"]
CONTRACT_VERSION: Final[str] = get_args(ContractVersion)[0]
"""Version of the draft format; the JSON schema is bound to it (``$id`` and ``const``)."""

EventId = TypeAliasType(
    "EventId",
    Annotated[
        str,
        StringConstraints(pattern=EVENT_ID_PATTERN),
        Field(description="ID of the detection: ev_ + 12 hex digits of the request and the row."),
    ],
)
IntervalId = TypeAliasType(
    "IntervalId",
    Annotated[
        str,
        StringConstraints(pattern=INTERVAL_ID_PATTERN),
        Field(description="ID of an interval: iv_v<VisualPerInterval id> or iv_a<AudioPerInterval id>."),
    ],
)
EntityId = TypeAliasType(
    "EntityId",
    Annotated[
        str,
        StringConstraints(pattern=ENTITY_ID_PATTERN),
        Field(description="ID of an entity: ent_ + the ClassID of VisualParticipant."),
    ],
)
ConstraintId = TypeAliasType(
    "ConstraintId",
    Annotated[
        str,
        StringConstraints(pattern=CONSTRAINT_ID_PATTERN),
        Field(description="ID of a rule node: c_<branch>_proj|sel<n>|op<n>|cc<n>, or c_set<n>."),
    ],
)
TermId = TypeAliasType(
    "TermId",
    Annotated[
        str,
        StringConstraints(pattern=TERM_ID_PATTERN),
        Field(description="ID of a glossary entry: g_<kind>_<term>."),
    ],
)

Condition = Literal["A", "B", "C"]
Modality = Literal["visual", "audio"]
TimeUnit = Literal["seconds", "frames"]


# --------------------------------------------------------------------------- contract_meta


class SourceSnapshot(ContractModel):
    """Which state of WatchOut was read, and when."""

    backend_version: str | None
    extracted_at: Timestamp
    sources: SourceMap | None = absent_if_none()
    unavailable: UnavailableMap | None = absent_if_none()


class Sampling(ContractModel):
    """``SamplingRate`` is both the declared fps and the sampling stride."""

    source_fps: int | None
    sample_every_n: int | None
    effective_hz: float | None


class AudioWindow(ContractModel):
    window_s: float
    hop_s: float


class Determinism(ContractModel):
    temperature: float
    seed: int


class PipelineConfig(ContractModel):
    vlm_backend: str | None
    audio_backend: str | None
    sampling: Sampling
    audio_window: AudioWindow | None
    merge_tolerance_s: float | None
    determinism: Determinism
    detection_mode: Literal["visual", "audio", "multimodal"]
    sources: SourceMap | None = absent_if_none()
    unavailable: UnavailableMap | None = absent_if_none()


class ContractMeta(ContractModel):
    contract_version: ContractVersion
    analysis_id: NonEmptyStr
    source_snapshot: SourceSnapshot
    pipeline_config: PipelineConfig
    glossary_version: NonEmptyStr
    params_origin: Literal["rule_defaults", "saved_by_gui"]
    """Default parameters of the rule (end-of-analysis batch) or those saved by the GUI."""
    sources: SourceMap | None = absent_if_none()
    unavailable: UnavailableMap | None = absent_if_none()


# --------------------------------------------------------------------------- event


class Argument(ContractModel):
    role: NonEmptyStr
    """Projected field, e.g. ``M1.arg1``."""
    class_: NonEmptyStr = Field(alias="class")
    entity_id: EntityId
    column: NonEmptyStr
    """Column of the detection row, e.g. ``M1_person``."""


class RuleRef(ContractModel):
    rule_ref: NonEmptyStr
    """``EventSpec`` id and condition, e.g. ``handoff/A``."""


class ModalityRules(ContractModel):
    """The rules of the same event in each modality."""

    visual: RuleRef | None
    audio: RuleRef | None


class ModalityDetection(ContractModel):
    """A row of Evento_A or Evento_B of the same event type in the same analysis."""

    modality: Modality
    interval: Anchor
    source_ref: SourceRef
    unavailable: UnavailableMap | None = absent_if_none()


class OriginMatch(ContractModel):
    modality: Modality
    source_ref: SourceRef


class OriginBasis(ContractModel):
    """Which branch and which modality rows decided ``modality_origin`` of a C row."""

    branch: NonEmptyStr
    matched: list[OriginMatch]
    method: NonEmptyStr


class EventRecord(ContractModel):
    event_id: EventId
    model_id: NonEmptyStr
    label: NonEmptyStr
    modality_origin: Literal["visual", "audio", "both"] | None
    origin_basis: OriginBasis | None = absent_if_none()
    interval: Anchor
    arguments: list[Argument]
    modality_rules: ModalityRules
    modality_detections: list[ModalityDetection]
    source_ref: SourceRef
    unavailable: UnavailableMap | None = absent_if_none()


# --------------------------------------------------------------------------- rule

ParamValue = Union[StrictInt, StrictFloat, Literal["inf", "<=", "<", ">=", ">"]]
"""A threshold (number or ``inf``) or a strictness operator."""


class OperatorParam(ContractModel):
    """One parameter of a temporal operator, as written and as used by the engine."""

    model_config = ConfigDict(
        json_schema_extra={
            "if": {"properties": {"name": {"enum": ["ζ", "η"]}}},
            "then": {"not": {"required": ["unit"]}},
        }
    )

    name: Literal["δ", "ε", "ζ", "η", "ρ"]
    raw: str | None
    """Named key (``delta_visual_handoff``), or null for a literal written in the rule."""
    value: ParamValue
    """Value written in the rule or in the parameters."""
    unit: TimeUnit | None = absent_if_none()
    """Unit of ``value``; only thresholds (δ, ε, ρ) have one."""
    engine_value: ParamValue
    """Value passed to the SQL."""
    compare_domain: TimeUnit
    """Domain the engine compares in; spoken readings use ``engine_value`` in it."""
    origin: Literal["literal", "named_key", "template_geometry", "engine_default"]
    source_ref: SourceRef

    @model_validator(mode="after")
    def _strictness_has_no_unit(self) -> "OperatorParam":
        if self.name in ("ζ", "η") and self.unit is not None:
            raise ValueError(f"{self.name} is a strictness operator and has no unit")
        return self


class SelectionBranch(ContractModel):
    predicates: Annotated[list[NonEmptyStr], Field(min_length=1)]
    arg_classes: dict[NonEmptyStr, list[NonEmptyStr]]
    """Argument slot (``"1"``, ``"2"``) → admitted classes."""


class SelectionPayload(ContractModel):
    """A selection; several branches are a disjunction."""

    branches: Annotated[list[SelectionBranch], Field(min_length=1)]


class TemporalOperatorPayload(ContractModel):
    name: Literal["Bef", "Aft", "SP", "EF", "DJ", "RDJ", "LOJ", "ROJ"]
    resolution: Literal["override", "geometry"]
    """``operator_overrides`` of the model, or ``detect_operator`` on the template geometry."""
    resolution_detail: str | None = absent_if_none()
    params: list[OperatorParam]


class ComparisonPayload(ContractModel):
    """``left op right`` between attributes of two variables, e.g. ``M1.arg1 ≠ M2.arg1``."""

    left: NonEmptyStr
    op: NonEmptyStr
    right: NonEmptyStr


class DurationPayload(ContractModel):
    """``(end − start) op value``."""

    end: NonEmptyStr
    start: NonEmptyStr
    op: NonEmptyStr
    value: StrictInt | StrictFloat
    unit: TimeUnit


class ProjectionPayload(ContractModel):
    fields: Annotated[list[NonEmptyStr], Field(min_length=1)]


class SetOperationPayload(ContractModel):
    op: Literal["∪", "∩", "\\"]
    children: Annotated[list[ConstraintId], Field(min_length=2)]


class _ConstraintNodeBase(ContractModel):
    """One node of the saved rule structure.

    ``parent`` is containment in the saved model only: nodes of a branch point to
    the branch projection, projections to the set operation. K4 decides the order.
    """

    constraint_id: ConstraintId
    branch: NonEmptyStr | None
    """Group of the model (``s1``); null for a set operation between branches."""
    modality: Literal["visual", "audio", "mixed"]
    variables: list[NonEmptyStr]
    """Variables local to the branch (``M1``, ``M2``) the node acts on."""
    parent: ConstraintId | None
    text: NonEmptyStr
    """Fragment rendered by WatchOut's renderer for this node."""
    source_ref: SourceRef
    unavailable: UnavailableMap | None = absent_if_none()


class SelectionNode(_ConstraintNodeBase):
    kind: Literal["selection"]
    payload: SelectionPayload


class TemporalOperatorNode(_ConstraintNodeBase):
    kind: Literal["temporal_operator"]
    payload: TemporalOperatorPayload


class IdentityNode(_ConstraintNodeBase):
    kind: Literal["identity"]
    payload: ComparisonPayload


class AttributeComparisonNode(_ConstraintNodeBase):
    kind: Literal["attribute_comparison"]
    payload: ComparisonPayload


class DurationNode(_ConstraintNodeBase):
    kind: Literal["duration"]
    payload: DurationPayload


class ProjectionNode(_ConstraintNodeBase):
    kind: Literal["projection"]
    payload: ProjectionPayload


class SetOperationNode(_ConstraintNodeBase):
    kind: Literal["set_operation"]
    payload: SetOperationPayload


ConstraintNode = Annotated[
    Union[
        SelectionNode,
        TemporalOperatorNode,
        IdentityNode,
        AttributeComparisonNode,
        DurationNode,
        ProjectionNode,
        SetOperationNode,
    ],
    Field(discriminator="kind"),
]
"""A rule node; ``kind`` decides the type of ``payload``."""


class RuleRecord(ContractModel):
    expression: NonEmptyStr
    """Text rendered from the executed structure with the parameters used."""
    expression_saved: NonEmptyStr
    """``iseql_text`` saved by WatchOut, unchanged."""
    structure_ref: SourceRef
    model_form: Literal["F1", "F2", "F3"]
    projection: list[NonEmptyStr]
    constraints: Annotated[list[ConstraintNode], Field(min_length=1)]
    unavailable: UnavailableMap | None = absent_if_none()


# --------------------------------------------------------------------------- evidence


class ReidEvidence(ContractModel):
    """Re-ID evidence of an entity.

    ``status`` says whether WatchOut has the evidence at all; when it is
    ``not_available`` both values are null and the entity's ``unavailable`` map
    says why under ``reid_evidence``.
    """

    status: Literal["read", "not_available"]
    gallery_match_id: str | None
    similarity: float | None


class Entity(ContractModel):
    entity_id: EntityId
    class_: NonEmptyStr = Field(alias="class")
    reid_evidence: ReidEvidence
    source_ref: SourceRef
    unavailable: UnavailableMap | None = absent_if_none()


class IntervalRecord(ContractModel):
    interval_id: IntervalId
    source: Literal["VisualPerInterval", "AudioPerInterval"]
    """Table the interval comes from; its provenance is ``source_ref``."""
    predicate: NonEmptyStr
    args: list[EntityId]
    args_ordered: bool
    """True when the signature classes differ, so the order of ``args`` is meaningful."""
    anchor: Anchor
    confidence: float | None
    source_ref: SourceRef
    sources: SourceMap | None = absent_if_none()
    unavailable: UnavailableMap | None = absent_if_none()


# --------------------------------------------------------------------------- glossary


class ParameterReading(ContractModel):
    condition: NonEmptyStr
    phrase: NonEmptyStr


class GlossaryEntry(ContractModel):
    term_id: TermId
    kind: Literal["predicate", "audio_class", "operator", "event_model"]
    term: NonEmptyStr
    definition: str | None
    plain_template: NonEmptyStr
    parameter_readings: list[ParameterReading] | None = absent_if_none()
    source: SourceRef | Literal["event_author"]
    """Provenance of the definition: a WatchOut record or the event's author."""
    source_detail: str | None = absent_if_none()
    sources: SourceMap | None = absent_if_none()
    unavailable: UnavailableMap | None = absent_if_none()


# --------------------------------------------------------------------------- harvest_report


class RequestEcho(ContractModel):
    """The request the draft answers."""

    analysis_id: NonEmptyStr
    event_type: NonEmptyStr
    condition: Condition
    params: Literal["auto", "saved", "defaults"]
    row: dict[NonEmptyStr, RowValue]


class RowMatch(ContractModel):
    """How the request's row was found among the rows of the detection.

    ``matches <= rows_returned`` and ``matched_index < rows_returned`` compare two
    fields, which JSON Schema cannot express: only the model checks them.
    """

    rows_returned: PositiveInt
    matches: PositiveInt
    matched_index: NonNegativeInt

    @model_validator(mode="after")
    def _match_is_consistent(self) -> "RowMatch":
        if not 1 <= self.matches <= self.rows_returned:
            raise ValueError("a draft needs 1 <= matches <= rows_returned")
        if self.matched_index >= self.rows_returned:
            raise ValueError("matched_index must point to a returned row")
        return self


class Violation(ContractModel):
    check: CheckName
    element_path: NonEmptyStr
    detail: NonEmptyStr


class CheckResult(ContractModel):
    model_config = ConfigDict(
        json_schema_extra={
            "if": {"properties": {"passed": {"const": True}}},
            "then": {"properties": {"violations": {"maxItems": 0}}},
            "else": {"properties": {"violations": {"minItems": 1}}},
        }
    )

    name: CheckName
    passed: bool
    violations: list[Violation]

    @model_validator(mode="after")
    def _passed_means_no_violations(self) -> "CheckResult":
        if self.passed == bool(self.violations):
            raise ValueError("passed must be true exactly when there are no violations")
        return self


class MissingField(ContractModel):
    path: NonEmptyStr
    """Path of the null field, e.g. ``intervals[*].confidence``."""
    reason: Reason


class Note(ContractModel):
    code: NoteCode
    detail: NonEmptyStr


class HarvestReport(ContractModel):
    request: RequestEcho
    row_match: RowMatch
    checks: list[CheckResult]
    missing_fields: list[MissingField]
    """Every null field of the draft by path, with its reason: K2's main input for ``data_not_available``."""
    notes: list[Note]


# --------------------------------------------------------------------------- draft


class ContractDraft(ContractModel):
    """The draft of the Neuro-Symbolic Contract for one detection."""

    contract_meta: ContractMeta
    event: EventRecord
    rule: RuleRecord
    entities: list[Entity]
    intervals: list[IntervalRecord]
    actions: None
    """Null with ``keyframes_not_persisted`` until the key-frame version of WatchOut."""
    glossary: list[GlossaryEntry]
    unavailable: UnavailableMap | None = absent_if_none()
    """Reasons for the null top-level fields, e.g. ``actions``."""
    harvest_report: HarvestReport
