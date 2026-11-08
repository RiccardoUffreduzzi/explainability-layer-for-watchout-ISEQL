"""Limits of knowledge: which entries of the closed catalogue apply to a draft, and why.

The codes and their causes are decided here, from what the draft says (document 05, section 10).
The fixed sentences (Report 1) come from the approved catalogue, not from this module.
"""

from collections.abc import Callable
from dataclasses import dataclass

from xai.contract.model import ContractDraft
from xai.contract.source_of_truth import LimitCode

Refs = tuple[str, ...]


@dataclass(frozen=True)
class DetectedLimit:
    """A limit that applies to the draft, with the IDs of what causes it.

    ``refs`` holds rule nodes (``c_``) or glossary entries (``g_``), in draft order.
    It is empty when the limit holds for the whole detection.
    """

    code: LimitCode
    refs: Refs = ()


Rule = Callable[[ContractDraft], Refs | None]
"""``None`` when the limit does not apply, otherwise its causes (possibly none)."""


def _whole_detection(applies: Callable[[ContractDraft], bool]) -> Rule:
    """A limit with no cause more precise than the whole detection."""

    def rule(draft: ContractDraft) -> Refs | None:
        return () if applies(draft) else None

    return rule


def _has_visual_intervals(draft: ContractDraft) -> bool:
    return any(i.source == "VisualPerInterval" for i in draft.intervals)


def _has_sampling_rate(draft: ContractDraft) -> bool:
    # TODO: the document only says the limit "uses" effective_hz; confirm it needs a value.
    return draft.contract_meta.pipeline_config.sampling.effective_hz is not None


def _identity_nodes(draft: ContractDraft) -> Refs | None:
    nodes = tuple(node.constraint_id for node in draft.rule.constraints if node.kind == "identity")
    return nodes or None


def _reid_evidence_missing(draft: ContractDraft) -> Refs | None:
    # TODO: confirm this needs identity nodes too (document 05 lists both fields in one row).
    if not any(e.reid_evidence.status == "not_available" for e in draft.entities):
        return None
    return _identity_nodes(draft)


def _audio_origin(draft: ContractDraft) -> bool:
    return draft.event.modality_origin == "audio"


def _has_actions(draft: ContractDraft) -> bool:
    # K1 always writes ``actions = null`` today, so this holds only with the key frame version.
    return draft.actions is not None


def _undefined_terms(draft: ContractDraft) -> Refs | None:
    terms = tuple(entry.term_id for entry in draft.glossary if entry.definition is None)
    return terms or None


def _has_missing_fields(draft: ContractDraft) -> bool:
    return bool(draft.harvest_report.missing_fields)


_RULES: tuple[tuple[LimitCode, Rule], ...] = (
    (LimitCode.VISUAL_CONFIDENCE_UNAVAILABLE, _whole_detection(_has_visual_intervals)),
    (LimitCode.PERCEPTUAL_ATTRIBUTION_UNAVAILABLE, _whole_detection(_has_visual_intervals)),
    (LimitCode.TEMPORAL_RESOLUTION, _whole_detection(_has_sampling_rate)),
    (LimitCode.REID_DEPENDENCE, _identity_nodes),
    (LimitCode.REID_EVIDENCE_UNAVAILABLE, _reid_evidence_missing),
    (LimitCode.AUDIO_WITHOUT_PARTICIPANTS, _whole_detection(_audio_origin)),
    (LimitCode.KEYFRAME_SELECTION_UNDOCUMENTED, _whole_detection(_has_actions)),
    (LimitCode.GLOSSARY_ENTRY_MISSING, _undefined_terms),
    (LimitCode.DATA_NOT_AVAILABLE, _whole_detection(_has_missing_fields)),
)


def detect_limits(draft: ContractDraft) -> list[DetectedLimit]:
    """The limits that apply to the draft, in catalogue order, without repeats."""
    found = ((code, rule(draft)) for code, rule in _RULES)
    return [DetectedLimit(code, refs) for code, refs in found if refs is not None]
