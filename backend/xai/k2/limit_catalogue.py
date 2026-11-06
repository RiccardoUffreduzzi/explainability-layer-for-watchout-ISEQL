"""The fixed sentences of the limits of knowledge (Report 1)."""

from xai.contract.source_of_truth import KnowledgeLimit, LimitCode

SENTENCES: dict[LimitCode, str] = {
    LimitCode.VISUAL_CONFIDENCE_UNAVAILABLE: "The system does not record a confidence value for visual detections.",
    LimitCode.PERCEPTUAL_ATTRIBUTION_UNAVAILABLE: (
        "The system does not record what in the images led to each visual detection."
    ),
    LimitCode.TEMPORAL_RESOLUTION: "Times are approximate: they depend on the sampling rate of the video analysis.",
    LimitCode.REID_DEPENDENCE: "The rule relies on matching the same person across frames (Re-ID).",
    LimitCode.REID_EVIDENCE_UNAVAILABLE: "The evidence behind the Re-ID matches is not saved by the system.",
    LimitCode.AUDIO_WITHOUT_PARTICIPANTS: "An audio detection does not say who or what produced the sound.",
    LimitCode.KEYFRAME_SELECTION_UNDOCUMENTED: "The criterion used to select the key frames is not documented.",
    LimitCode.GLOSSARY_ENTRY_MISSING: "Some terms used in this explanation have no definition in the glossary.",
    LimitCode.DATA_NOT_AVAILABLE: "Some information is not saved by the system and is reported as not available.",
}


def knowledge_limit(code: LimitCode) -> KnowledgeLimit:
    return KnowledgeLimit(code=code, sentence=SENTENCES[code])
