"""Modality check: do the video and audio detections of the event overlap in time?

Only for multimodal detections. It reads ``event.modality_detections`` of the draft:
K1 already collected there the detections of both modalities for the event.
"""

from xai.contract.model import ContractDraft
from xai.contract.primitives import Anchor
from xai.contract.source_of_truth import Reinforcement


def overlaps(a: Anchor, b: Anchor) -> bool | None:
    """Whether two spans share at least one frame; ``None`` if a frame is missing.

    The frames are compared as whole numbers, on closed intervals: two spans that share a
    single frame count as overlapping, for instance one ending where the other begins. This
    matches ISEQL+ Before with its default non-strict ζ (⩽) and ρ = 0, where touching
    intervals (gap 0) are valid. A one-frame span inside another overlaps too.
    """
    bounds = (a.start_frame, a.end_frame, b.start_frame, b.end_frame)
    if any(frame is None for frame in bounds):
        return None
    start_a, end_a, start_b, end_b = bounds
    assert start_a is not None and end_a is not None and start_b is not None and end_b is not None
    return start_a <= end_b and start_b <= end_a


def modality_check(draft: ContractDraft) -> Reinforcement | None:
    """The outcome of the check, or ``None`` when K2 says nothing about it.

    Nothing is said when the detection is not multimodal, when the event has no rule in
    one of the modalities, or when neither modality has a detection. Otherwise:

    - only one modality has detections: ``visual_only`` or ``audio_only``;
    - some video span overlaps some audio span: ``both_overlapping``;
    - no overlap, but a comparison was impossible (a frame is missing): ``not_comparable``;
    - no overlap in any comparison: ``both_not_overlapping``.
    """
    if draft.contract_meta.pipeline_config.detection_mode != "multimodal":
        return None
    rules = draft.event.modality_rules
    if rules.visual is None or rules.audio is None:
        return None
    detections = draft.event.modality_detections
    visual = [d.interval for d in detections if d.modality == "visual"]
    audio = [d.interval for d in detections if d.modality == "audio"]
    if not visual and not audio:
        return None
    if not audio:
        return Reinforcement.VISUAL_ONLY
    if not visual:
        return Reinforcement.AUDIO_ONLY
    comparisons = [overlaps(v, a) for v in visual for a in audio]
    if any(c is True for c in comparisons):
        return Reinforcement.BOTH_OVERLAPPING
    if any(c is None for c in comparisons):
        return Reinforcement.NOT_COMPARABLE
    return Reinforcement.BOTH_NOT_OVERLAPPING
