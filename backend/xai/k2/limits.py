"""Limits of knowledge: which entries of the closed catalogue apply to a draft.

Only the codes are decided here, from what the draft says (document 05, section 10).
The fixed sentences (Report 1) come from the approved catalogue, not from this module.
"""

from collections.abc import Callable

from xai.contract.model import ContractDraft
from xai.contract.source_of_truth import LimitCode


def _has_visual_intervals(draft: ContractDraft) -> bool:
    return any(i.source == "VisualPerInterval" for i in draft.intervals)


def _has_sampling_rate(draft: ContractDraft) -> bool:
    # TODO: the document only says the limit "uses" effective_hz; confirm it needs a value.
    return draft.contract_meta.pipeline_config.sampling.effective_hz is not None


def _has_identity_nodes(draft: ContractDraft) -> bool:
    return any(node.kind == "identity" for node in draft.rule.constraints)


def _reid_evidence_missing(draft: ContractDraft) -> bool:
    # TODO: confirm this needs identity nodes too (document 05 lists both fields in one row).
    return _has_identity_nodes(draft) and any(e.reid_evidence.status == "not_available" for e in draft.entities)


def _audio_origin(draft: ContractDraft) -> bool:
    return draft.event.modality_origin == "audio"


def _has_actions(draft: ContractDraft) -> bool:
    # K1 always writes ``actions = null`` today, so this holds only with the key frame version.
    return draft.actions is not None


def _has_undefined_terms(draft: ContractDraft) -> bool:
    return any(entry.definition is None for entry in draft.glossary)


def _has_missing_fields(draft: ContractDraft) -> bool:
    return bool(draft.harvest_report.missing_fields)


_RULES: tuple[tuple[LimitCode, Callable[[ContractDraft], bool]], ...] = (
    (LimitCode.VISUAL_CONFIDENCE_UNAVAILABLE, _has_visual_intervals),
    (LimitCode.PERCEPTUAL_ATTRIBUTION_UNAVAILABLE, _has_visual_intervals),
    (LimitCode.TEMPORAL_RESOLUTION, _has_sampling_rate),
    (LimitCode.REID_DEPENDENCE, _has_identity_nodes),
    (LimitCode.REID_EVIDENCE_UNAVAILABLE, _reid_evidence_missing),
    (LimitCode.AUDIO_WITHOUT_PARTICIPANTS, _audio_origin),
    (LimitCode.KEYFRAME_SELECTION_UNDOCUMENTED, _has_actions),
    (LimitCode.GLOSSARY_ENTRY_MISSING, _has_undefined_terms),
    (LimitCode.DATA_NOT_AVAILABLE, _has_missing_fields),
)


def detect_limits(draft: ContractDraft) -> list[LimitCode]:
    """The limits that apply to the draft, in catalogue order, without repeats."""
    return [code for code, applies in _RULES if applies(draft)]
