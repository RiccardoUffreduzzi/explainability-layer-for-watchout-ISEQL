"""Which ``VisualPerFrame`` row K1 copies into ``vlm_description`` of an entity.

The VLM describes a subject again in every sampled frame and the text changes over
time. K1 copies one row only without rewriting
"""

from collections.abc import Sequence
from dataclasses import dataclass

from xai.k1_harvester.ports import FrameDescriptionRow


@dataclass(frozen=True)
class Window:
    """Frames of a visual interval of the draft that has the entity among its args, ends included."""

    start_frame: int
    end_frame: int


@dataclass(frozen=True)
class ChosenDescription:
    row: FrameDescriptionRow
    in_evidence: bool
    """True when the row's frame lies in a window."""


def choose_description(
    rows: Sequence[FrameDescriptionRow], windows: Sequence[Window], reference_frame: int | None
) -> ChosenDescription | None:
    """The row of one entity to copy; None when the analysis has no row for it.

    ``windows`` are in start order. Inside them: the lowest frame, then the lowest
    block. Outside: the row nearest to the start of the first window, or to
    ``reference_frame`` (the start of the event) for an entity without windows; at the
    same distance the older frame, then the lowest block.
    """
    if not rows:
        return None
    inside = [r for r in rows if any(w.start_frame <= r.frame <= w.end_frame for w in windows)]
    if inside:
        return ChosenDescription(min(inside, key=lambda r: (r.frame, r.block)), in_evidence=True)
    target = windows[0].start_frame if windows else reference_frame
    if target is None:
        return ChosenDescription(min(rows, key=lambda r: (r.frame, r.block)), in_evidence=False)
    nearest = min(rows, key=lambda r: (abs(r.frame - target), r.frame, r.block))
    return ChosenDescription(nearest, in_evidence=False)
