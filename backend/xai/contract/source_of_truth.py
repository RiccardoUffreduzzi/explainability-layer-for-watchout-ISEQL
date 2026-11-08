"""The source of truth: the K1 draft kept as it is, plus what K2 adds.

K1's models are not touched. Each K2 model extends the K1 one with new fields only, so
the JSON of a source of truth is the JSON of the draft plus these keys:

- ``knowledge_limits`` (top level), each with the IDs of its causes when it has precise ones;
- ``event.reinforcement``: status of the modality check and its fixed sentence, if it has one;
- ``contract_meta.source_of_truth_version`` and ``contract_meta.contract_hash``.

``contract_meta.contract_version`` keeps naming the version of the draft format.
"""

import hashlib
import json
from collections.abc import Mapping
from enum import Enum
from typing import Annotated, Any, Final, Literal, get_args

from pydantic import Field, StringConstraints

from xai.contract.canonical import canonical_json
from xai.contract.model import ConstraintId, ContractDraft, ContractMeta, EventRecord, TermId
from xai.contract.primitives import ContractModel, NonEmptyStr, absent_if_none

SourceOfTruthVersion = Literal["0.2.0-k2"]
SOURCE_OF_TRUTH_VERSION: Final[str] = get_args(SourceOfTruthVersion)[0]
"""Version of the K2 additions; their JSON schema is bound to it."""

ContractHash = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class LimitCode(str, Enum):
    """The closed catalogue of knowledge limits, in the order they are reported."""

    VISUAL_CONFIDENCE_UNAVAILABLE = "visual_confidence_unavailable"
    PERCEPTUAL_ATTRIBUTION_UNAVAILABLE = "perceptual_attribution_unavailable"
    TEMPORAL_RESOLUTION = "temporal_resolution"
    REID_DEPENDENCE = "reid_dependence"
    REID_EVIDENCE_UNAVAILABLE = "reid_evidence_unavailable"
    AUDIO_WITHOUT_PARTICIPANTS = "audio_without_participants"
    KEYFRAME_SELECTION_UNDOCUMENTED = "keyframe_selection_undocumented"
    GLOSSARY_ENTRY_MISSING = "glossary_entry_missing"
    DATA_NOT_AVAILABLE = "data_not_available"


class ReinforcementStatus(str, Enum):
    """Outcome of the modality check, with the names of the guidelines.

    ``not_comparable`` is K2's own: both modalities detected the event, no overlap was
    found, and some comparison was impossible because a frame number is missing.
    """

    BOTH_OVERLAPPING = "both_overlapping"
    BOTH_DISJOINT = "both_disjoint"
    ONLY_VISUAL = "only_visual"
    ONLY_AUDIO = "only_audio"
    NOT_COMPARABLE = "not_comparable"
    NO_COUNTERPART = "no_counterpart"
    NOT_MULTIMODAL = "not_multimodal"


class Reinforcement(ContractModel):
    status: ReinforcementStatus
    sentence: NonEmptyStr | None = absent_if_none()
    """The fixed sentence of the catalogue, for Report 2. Left out when the status has none."""


class KnowledgeLimit(ContractModel):
    code: LimitCode
    sentence: NonEmptyStr
    """The fixed sentence of the catalogue, for Report 1."""
    refs: Annotated[list[ConstraintId | TermId], Field(min_length=1)] | None = absent_if_none()
    """What the limit comes from: rule nodes (``c_``) or glossary entries (``g_``), in draft order.

    Left out when the limit holds for the whole detection.
    """


class EventRecordK2(EventRecord):
    reinforcement: Reinforcement | None = absent_if_none()


class ContractMetaK2(ContractMeta):
    source_of_truth_version: SourceOfTruthVersion
    contract_hash: ContractHash
    """SHA-256 of the canonical JSON of the whole document, without this field."""


class SourceOfTruth(ContractDraft):
    """The K1 draft plus the K2 additions."""

    contract_meta: ContractMetaK2
    event: EventRecordK2
    knowledge_limits: list[KnowledgeLimit]


def source_of_truth_to_data(document: SourceOfTruth) -> dict[str, Any]:
    return document.model_dump(mode="json")


def compute_contract_hash(data: Mapping[str, Any]) -> str:
    """SHA-256 of the canonical JSON of ``data`` without ``contract_meta.contract_hash``."""
    meta = {key: value for key, value in data["contract_meta"].items() if key != "contract_hash"}
    return hashlib.sha256(canonical_json({**data, "contract_meta": meta}).encode("utf-8")).hexdigest()


def verify_contract_hash(document: SourceOfTruth) -> bool:
    """Whether the hash written in the document is the one of its content."""
    return compute_contract_hash(source_of_truth_to_data(document)) == document.contract_meta.contract_hash


def dump_source_of_truth(document: SourceOfTruth, *, indent: int | None = None) -> str:
    """JSON of the document: the same document always gives the same text."""
    data = source_of_truth_to_data(document)
    if indent is None:
        return canonical_json(data)
    return json.dumps(data, sort_keys=True, ensure_ascii=False, indent=indent)


def load_source_of_truth(text: str | bytes) -> SourceOfTruth:
    return SourceOfTruth.model_validate_json(text)
