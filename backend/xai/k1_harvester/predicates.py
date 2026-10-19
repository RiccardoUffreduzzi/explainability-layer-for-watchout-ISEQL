"""Which modality a predicate belongs to.

The compiler reads a predicate from ``AudioPerInterval`` when it is one of the audio
classes of ``AppConfig.audio_taxonomy``, from ``VisualPerInterval`` otherwise: K1
uses the same split.
"""

from collections.abc import Iterable
from typing import Literal

from xai.k1_harvester.ports import Branch, BranchInterval, Vocabulary

NodeModality = Literal["visual", "audio", "mixed"]


def interval_predicates(interval: BranchInterval) -> list[str]:
    """The predicates of a selection, in order, each once."""
    found: list[str] = []
    for alternative in interval.selection:
        found.extend(p for p in alternative.predicates if p not in found)
    return found


def branch_predicates(branch: Branch) -> list[str]:
    found: list[str] = []
    for interval in branch.intervals:
        found.extend(p for p in interval_predicates(interval) if p not in found)
    return found


def is_audio(predicate: str, vocabulary: Vocabulary) -> bool:
    return predicate in vocabulary.audio_classes


def modality_of(predicates: Iterable[str], vocabulary: Vocabulary) -> NodeModality:
    kinds = {"audio" if is_audio(p, vocabulary) else "visual" for p in predicates}
    if kinds == {"audio"}:
        return "audio"
    if kinds == {"visual"}:
        return "visual"
    return "mixed"


def branch_modality(branch: Branch, vocabulary: Vocabulary) -> NodeModality:
    return modality_of(branch_predicates(branch), vocabulary)
