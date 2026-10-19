"""The only place where frames and seconds are converted.

WatchOut computes seconds as ``StartFrame / fps`` (``compiler.py``) and the GUI
derives frames as ``round(seconds * fps)`` (``detect_event``). ``TimeBase`` applies
the same two formulas with ``fps = Analyses.SamplingRate`` and writes seconds
rounded to the millisecond, as ``_format_time`` shows them.
"""

from dataclasses import dataclass

from xai.contract.primitives import Anchor, Unavailable
from xai.contract.reasons import Reason


def round_ms(seconds: float) -> float:
    """Seconds rounded to the millisecond like WatchOut's ``_format_time``."""
    return round(seconds * 1000) / 1000


@dataclass(frozen=True)
class TimedAnchor:
    """An anchor and the reasons for its converted pair, keyed by ``<field>.<attribute>``."""

    anchor: Anchor
    unavailable: dict[str, Unavailable]


class TimeBase:
    def __init__(self, fps: int | None) -> None:
        self.fps = fps if fps else None

    def from_frames(self, start_frame: int, end_frame: int, field: str) -> TimedAnchor:
        """Frames read from WatchOut; seconds converted (``frame / fps``)."""
        if self.fps is None:
            anchor = Anchor(
                start_frame=start_frame, end_frame=end_frame, start_s=None, end_s=None, read_as="frames"
            )
            return TimedAnchor(anchor, self._missing(field, ("start_s", "end_s"), "seconds"))
        anchor = Anchor(
            start_frame=start_frame,
            end_frame=end_frame,
            start_s=round_ms(start_frame / self.fps),
            end_s=round_ms(end_frame / self.fps),
            read_as="frames",
        )
        return TimedAnchor(anchor, {})

    def from_seconds(self, start_s: float, end_s: float, field: str) -> TimedAnchor:
        """Seconds read from the engine; frames converted (``round(s * fps)``, before rounding s)."""
        if self.fps is None:
            anchor = Anchor(
                start_frame=None,
                end_frame=None,
                start_s=round_ms(start_s),
                end_s=round_ms(end_s),
                read_as="seconds",
            )
            return TimedAnchor(anchor, self._missing(field, ("start_frame", "end_frame"), "frames"))
        anchor = Anchor(
            start_frame=round(start_s * self.fps),
            end_frame=round(end_s * self.fps),
            start_s=round_ms(start_s),
            end_s=round_ms(end_s),
            read_as="seconds",
        )
        return TimedAnchor(anchor, {})

    def seconds_of(self, samples: int, every_n: int) -> float | None:
        """Duration of ``samples`` samples taken every ``every_n`` frames, in seconds."""
        if self.fps is None:
            return None
        return round_ms(samples * every_n / self.fps)

    @staticmethod
    def _missing(field: str, attributes: tuple[str, str], unit: str) -> dict[str, Unavailable]:
        reason = Unavailable(
            reason=Reason.FPS_NOT_RECORDED,
            detail=f"Analyses.SamplingRate is missing or zero: the {unit} cannot be converted",
        )
        return {f"{field}.{attribute}": reason for attribute in attributes}
