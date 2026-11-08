"""The fixed sentences of the modality check (Report 2)."""

from xai.contract.source_of_truth import ReinforcementStatus

REINFORCEMENT_SENTENCES: dict[ReinforcementStatus, str] = {
    ReinforcementStatus.BOTH_OVERLAPPING: (
        "The event was detected by both video and audio, in the same time interval."
    ),
    ReinforcementStatus.BOTH_DISJOINT: (
        "The event was detected by both video and audio, but at different times."
    ),
    ReinforcementStatus.ONLY_VISUAL: "The event was detected only by video: the audio does not confirm it.",
    ReinforcementStatus.ONLY_AUDIO: "The event was detected only by audio: the video does not confirm it.",
    ReinforcementStatus.NOT_COMPARABLE: (
        "The event was detected by both video and audio, but the system cannot say whether "
        "at the same time: some detections have no frame numbers."
    ),
}
"""``no_counterpart`` and ``not_multimodal`` have no sentence, as in the guidelines."""
