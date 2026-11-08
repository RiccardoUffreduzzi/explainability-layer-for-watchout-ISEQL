"""The explanation plan (scaletta) produced by K4 and read by K5, K6 and K7.

A plan is a function of one source of truth only: it has no clock and no free text. Every
step names the construct it comes from and cites facts of the contract by ID or by JSON
pointer; the only sentences in it are copies of sentences of the contract (``fixed_text``,
the parameter readings) and the English notes of ``plan_report``.

The top part of ``PlanStep`` is the step of the guidelines (``step_id``, ``type``,
``construct``, ``refs``, ``role``, ``depends_on``, ``t_order``, ``in_report2``); the other
fields are declared extensions (K4-A5, K4-A2, K4-D5 of the K4 vision).
"""

import hashlib
import json
from collections.abc import Mapping
from enum import Enum
from typing import Annotated, Any, Final, Literal, get_args

from pydantic import Field, StringConstraints
from typing_extensions import TypeAliasType

from xai.contract.canonical import canonical_json
from xai.contract.ids import (
    CONSTRAINT_ID_PATTERN,
    ENTITY_ID_PATTERN,
    EVENT_ID_PATTERN,
    INTERVAL_ID_PATTERN,
    STEP_ID_PATTERN,
    TERM_ID_PATTERN,
)
from xai.contract.model import ConstraintId, ContractVersion, EventId, IntervalId, TermId
from xai.contract.primitives import ContractModel, NonEmptyStr, absent_if_none
from xai.contract.source_of_truth import ContractHash, LimitCode, SourceOfTruthVersion

PlanVersion = Literal["0.1.0-k4"]
PLAN_VERSION: Final[str] = get_args(PlanVersion)[0]
"""Version of the plan format; the JSON schema is bound to it (``$id`` and ``const``)."""

KEYFRAME_ID_PATTERN = r"^kf_[A-Za-z0-9_]+$"
ACTION_ID_PATTERN = r"^ac_[A-Za-z0-9_]+$"
JSON_POINTER_PATTERN = r"^#/.*$"
"""A JSON pointer into the source of truth, for the parts that have no ID (e.g. a threshold)."""


def _alternatives(*patterns: str) -> str:
    return "^(?:" + "|".join(p.removeprefix("^").removesuffix("$") for p in patterns) + ")$"


REF_PATTERN = _alternatives(
    INTERVAL_ID_PATTERN,
    ENTITY_ID_PATTERN,
    CONSTRAINT_ID_PATTERN,
    TERM_ID_PATTERN,
    EVENT_ID_PATTERN,
    KEYFRAME_ID_PATTERN,
    ACTION_ID_PATTERN,
    JSON_POINTER_PATTERN,
)
"""A fact of the source of truth: an ID of the contract or a JSON pointer.

IDs of intervals, entities, rule nodes, glossary entries and the event; ``kf_`` and ``ac_``
are already admitted, their constructors come with I7 (UC-K4-15).
"""

StepId = TypeAliasType(
    "StepId",
    Annotated[
        str,
        StringConstraints(pattern=STEP_ID_PATTERN),
        Field(description="ID of a step: s_ + the rule node without c_ (s_s1_op1), s_lim_<code>, ..."),
    ],
)
Ref = TypeAliasType(
    "Ref",
    Annotated[
        str,
        StringConstraints(pattern=REF_PATTERN),
        Field(description="A fact of the source of truth: an ID of the contract or a JSON pointer (#/...)."),
    ],
)
SlotValue = TypeAliasType(
    "SlotValue",
    Annotated[
        StepId | Ref | None,
        Field(description="What fills a placeholder: a fact, another step, or null (generic wording)."),
    ],
)
PlanHash = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class StepType(str, Enum):
    """What a step explains, with the names of the guidelines (``provenance``: K4-D5)."""

    OBSERVATION = "observation"
    CONDITION = "condition"
    TEMPORAL = "temporal"
    IDENTITY = "identity"
    CONCLUSION = "conclusion"
    CONTEXT = "context"
    LIMIT = "limit"
    REINFORCEMENT = "reinforcement"
    PROVENANCE = "provenance"


class StepRole(str, Enum):
    """Why the step is in the explanation. The conclusion has none (K4-A5)."""

    BECAUSE = "because"
    CONTEXT = "context"
    LIMIT = "limit"


class TOrderBasis(str, Enum):
    """Where ``t_order`` comes from (K4-A3): an interval today, a key frame with I7."""

    INTERVAL = "interval"
    KEYFRAME = "keyframe"
    NONE = "none"


class BindingStatus(str, Enum):
    """Outcome of the association of a variable with the intervals of the contract (K4-A2)."""

    ATTRIBUTED = "attributed"
    AMBIGUOUS = "ambiguous"
    NOT_FOUND = "not_found"


class ExclusionReason(str, Enum):
    """Why a rule node has no step (K4-A8)."""

    OTHER_BRANCH = "other_branch"
    SET_OPERATION = "set_operation"


class PlanNoteCode(str, Enum):
    """The closed catalogue of the notes of ``plan_report``."""

    RHO_NOT_ZERO = "rho_not_zero"


IN_REPORT2: Final[Mapping[StepType, bool]] = {
    StepType.OBSERVATION: True,
    StepType.CONDITION: False,
    StepType.TEMPORAL: False,
    StepType.IDENTITY: False,
    StepType.CONCLUSION: True,
    StepType.CONTEXT: True,
    StepType.LIMIT: False,
    StepType.REINFORCEMENT: True,
    StepType.PROVENANCE: False,
}
"""``in_report2`` by step type: Report 2 says what was seen, what was flagged and the reinforcement."""


class Reading(ContractModel):
    """The reading of a threshold of a temporal operator, copied from the glossary (K4-A13)."""

    param: Literal["δ", "ε"]
    condition: NonEmptyStr
    """The condition of the glossary reading, e.g. ``δ = ∞`` or ``δ = d``."""
    phrase: NonEmptyStr
    """The phrase of the glossary, copied as it is (it may contain placeholders such as ``{r}``)."""
    value_ref: Ref | None = absent_if_none()
    """Pointer to ``engine_value`` of the parameter, for the ``d`` of a finite threshold."""


class PlanStep(ContractModel):
    """One step of the explanation."""

    step_id: StepId
    type: StepType
    construct_: ConstraintId | None = absent_if_none(alias="construct")
    """The rule node the step comes from; absent for limits, reinforcement and provenance.

    ``construct`` is a method of pydantic's models: the field uses an alias, like ``class``.
    """
    refs: list[Ref]
    """The facts the step cites; the first one is ``construct`` when there is one."""
    role: StepRole | None = absent_if_none()
    """Absent for the conclusion, which is the claim being explained (K4-A5)."""
    depends_on: list[StepId]
    t_order: float | None
    """Seconds from the start of the video; null with basis ``none``."""
    t_order_basis: TOrderBasis
    in_report2: bool
    term: TermId | None = absent_if_none()
    """The glossary entry that renders the step."""
    slots: dict[NonEmptyStr, SlotValue] | None = absent_if_none()
    """Placeholder of the entry -> what fills it, e.g. ``arg1`` -> ``ent_3``, ``r`` -> ``s_s1_sel1``."""
    alternatives: list[TermId] | None = absent_if_none()
    """The entries of every alternative of a disjunction in a selection (K4-A7)."""
    readings: list[Reading] | None = absent_if_none()
    """Parameter readings of a temporal operator (K4-A13)."""
    limit_code: LimitCode | None = absent_if_none()
    fixed_text: NonEmptyStr | None = absent_if_none()
    """A sentence copied verbatim from the contract (limits, reinforcement)."""


class Binding(ContractModel):
    """How the intervals of a variable were found (K4-A2, K4-D1)."""

    branch: NonEmptyStr
    variable: NonEmptyStr
    status: BindingStatus
    interval_ids: list[IntervalId]
    """The candidates, in contract order: one when ``attributed``, none when ``not_found``."""
    basis: list[NonEmptyStr]
    """The criteria applied, in order: ``predicate``, ``arg_classes``, ``M1.arg1``, ``M1.st`` ..."""


class ExcludedConstruct(ContractModel):
    constraint_id: ConstraintId
    reason: ExclusionReason


class UnmatchedReading(ContractModel):
    """A threshold whose reading is not in the glossary entry of its operator."""

    constraint_id: ConstraintId
    param: Literal["δ", "ε"]


class PlanNote(ContractModel):
    code: PlanNoteCode
    detail: NonEmptyStr
    """In English, e.g. ``c_s1_op1: ρ = 2``."""


class PlanReport(ContractModel):
    """What the plan leaves out and why: it is not a list of errors."""

    excluded_constructs: list[ExcludedConstruct]
    unbound_intervals: list[IntervalId]
    """Intervals of the contract that are no variable's only candidate (K4-A4)."""
    unmatched_readings: list[UnmatchedReading]
    notes: list[PlanNote]


class PlanMeta(ContractModel):
    plan_version: PlanVersion
    contract_hash: ContractHash
    """Copied from the source of truth: the reports declare it."""
    source_of_truth_version: SourceOfTruthVersion
    contract_version: ContractVersion
    event_id: EventId
    model_id: NonEmptyStr
    label: NonEmptyStr
    branches: Annotated[list[NonEmptyStr], Field(min_length=1)]
    """The branches explained, in rule order (K4-A8)."""
    plan_hash: PlanHash
    """SHA-256 of the canonical JSON of the plan without this field (K4-A12)."""


class ExplanationPlan(ContractModel):
    """The explanation plan of one detection."""

    plan_meta: PlanMeta
    steps: list[PlanStep]
    """Already in reading order."""
    bindings: list[Binding]
    plan_report: PlanReport


# --------------------------------------------------------------------------- serialization


def plan_to_data(plan: ExplanationPlan) -> dict[str, Any]:
    return plan.model_dump(mode="json")


def compute_plan_hash(data: Mapping[str, Any]) -> str:
    """SHA-256 of the canonical JSON of ``data`` without ``plan_meta.plan_hash``."""
    meta = {key: value for key, value in data["plan_meta"].items() if key != "plan_hash"}
    return hashlib.sha256(canonical_json({**data, "plan_meta": meta}).encode("utf-8")).hexdigest()


def dump_plan(plan: ExplanationPlan, *, indent: int | None = None) -> str:
    """JSON of the plan: the same plan always gives the same text."""
    data = plan_to_data(plan)
    if indent is None:
        return canonical_json(data)
    return json.dumps(data, sort_keys=True, ensure_ascii=False, indent=indent)


def load_plan(text: str | bytes) -> ExplanationPlan:
    return ExplanationPlan.model_validate_json(text)
