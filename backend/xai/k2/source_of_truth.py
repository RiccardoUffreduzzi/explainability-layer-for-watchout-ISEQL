"""Builds the source of truth from a K1 draft: the draft as it is, plus K2's additions."""

from typing import Any

from xai.contract.canonical import canonical_json
from xai.contract.model import ContractDraft
from xai.contract.serialization import draft_to_data
from xai.contract.source_of_truth import (
    SOURCE_OF_TRUTH_VERSION,
    SourceOfTruth,
    compute_contract_hash,
    load_source_of_truth,
)
from xai.k2.limit_catalogue import SENTENCES
from xai.k2.limits import detect_limits
from xai.k2.modality_check import modality_check


def build_source_of_truth(draft: ContractDraft) -> SourceOfTruth:
    """Nothing of the draft is changed: K2's fields are only added."""
    data: dict[str, Any] = draft_to_data(draft)
    data["knowledge_limits"] = [{"code": code.value, "sentence": SENTENCES[code]} for code in detect_limits(draft)]
    outcome = modality_check(draft)
    if outcome is not None:
        data["event"]["reinforcement"] = outcome.value
    data["contract_meta"]["source_of_truth_version"] = SOURCE_OF_TRUTH_VERSION
    data["contract_meta"]["contract_hash"] = compute_contract_hash(data)
    return load_source_of_truth(canonical_json(data))
