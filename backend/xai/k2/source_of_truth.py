"""Builds the source of truth from a K1 draft: the draft as it is, plus K2's additions."""

from typing import Any

from xai.contract.canonical import canonical_json
from xai.contract.model import ContractDraft
from xai.contract.serialization import draft_to_data
from xai.contract.source_of_truth import (
    SOURCE_OF_TRUTH_VERSION,
    ReinforcementStatus,
    SourceOfTruth,
    compute_contract_hash,
    load_source_of_truth,
)
from xai.k2.limit_catalogue import SENTENCES
from xai.k2.limits import DetectedLimit, detect_limits
from xai.k2.modality_check import modality_check
from xai.k2.reinforcement_catalogue import REINFORCEMENT_SENTENCES


def _limit_data(limit: DetectedLimit) -> dict[str, Any]:
    """An entry of ``knowledge_limits``: ``refs`` only when the limit has precise causes."""
    data: dict[str, Any] = {"code": limit.code.value, "sentence": SENTENCES[limit.code]}
    if limit.refs:
        data["refs"] = list(limit.refs)
    return data


def _reinforcement_data(status: ReinforcementStatus) -> dict[str, str]:
    """``event.reinforcement``: the status and, when it has one, its fixed sentence."""
    data = {"status": status.value}
    if status in REINFORCEMENT_SENTENCES:
        data["sentence"] = REINFORCEMENT_SENTENCES[status]
    return data


def build_source_of_truth(draft: ContractDraft) -> SourceOfTruth:
    """Nothing of the draft is changed: K2's fields are only added."""
    data: dict[str, Any] = draft_to_data(draft)
    data["knowledge_limits"] = [_limit_data(limit) for limit in detect_limits(draft)]
    outcome = modality_check(draft)
    if outcome is not None:
        data["event"]["reinforcement"] = _reinforcement_data(outcome)
    data["contract_meta"]["source_of_truth_version"] = SOURCE_OF_TRUTH_VERSION
    data["contract_meta"]["contract_hash"] = compute_contract_hash(data)
    return load_source_of_truth(canonical_json(data))
