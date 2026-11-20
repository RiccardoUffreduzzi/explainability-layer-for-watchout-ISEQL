"""The key frame of a detection: the frame WatchOut's results table shows for the row.

The GUI that chooses the frame, and K1 harvests it. The GUI's formula is:

- start and end in seconds are the minimum of the ``st`` columns and the maximum of the
  ``et`` columns; start and end frames the minimum of ``sf`` and the maximum of ``ef``;
- with both frames the preview is ``floor((sf + ef) / 2)``, otherwise
  ``floor(((st + et) / 2) * fps)``.

The pixels are not read here: K5 extracts the frame from ``Analyses.VideoPath``.
"""

import math
import re
from collections.abc import Mapping
from typing import Final, Literal

from xai.contract.ids import RowValue, keyframe_id
from xai.contract.model import FrameImageRef, KeyFrame
from xai.contract.primitives import SourceRef, Stage, Unavailable
from xai.contract.reasons import Reason
from xai.k1_harvester.ports import AnalysisSnapshot
from xai.k1_harvester.timebase import round_ms

PREVIEW_SOURCE = SourceRef(stage=Stage.KEYFRAMES, record_id="results-table.svelte#previewFrame", mode="read")
"""The GUI code that chooses the frame: the formula is WatchOut's, K1 applies it."""

SELECTION: Final[Literal["gui_preview_midpoint"]] = "gui_preview_midpoint"

_CLOCK = re.compile(r"^(\d+):(\d{2}):(\d{2})(?:\.(\d{1,3}))?$")
_JS_DECIMAL = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$")


def preview_frame(row: Mapping[str, RowValue], fps: float | None) -> int | None:
    """The frame the GUI previews for ``row``; None when the GUI shows no preview."""
    rate = fps if fps and fps > 0 else 0.0
    start_s = end_s = start_frame = end_frame = None
    for key, raw in row.items():
        if raw is None or raw == "":
            continue
        if _suffix(key, "st"):
            value = _time_value(raw)
            if value is not None:
                start_s = value if start_s is None else min(start_s, value)
            continue
        if _suffix(key, "et"):
            value = _time_value(raw)
            if value is not None:
                end_s = value if end_s is None else max(end_s, value)
            continue
        number = _js_number(raw)
        if number is None:
            continue
        if _suffix(key, "sf"):
            start_frame = number if start_frame is None else min(start_frame, number)
        elif _suffix(key, "ef"):
            end_frame = number if end_frame is None else max(end_frame, number)
    if start_s is None and start_frame is not None and rate > 0:
        start_s = start_frame / rate
    if end_s is None and end_frame is not None and rate > 0:
        end_s = end_frame / rate
    if start_s is None or end_s is None:
        return None
    if start_frame is not None and end_frame is not None:
        return math.floor((start_frame + end_frame) / 2)
    if rate > 0:
        return math.floor(((start_s + end_s) / 2) * rate)
    return None


def harvest_key_frame(
    row: Mapping[str, RowValue], analysis: AnalysisSnapshot, fps: float | None
) -> tuple[KeyFrame | None, Unavailable | None]:
    """The key frame of the row, or None with the reason the GUI has no preview for it."""
    frame = preview_frame(row, fps)
    if frame is None or frame < 0:
        if not fps and preview_frame(row, 1.0) is not None:
            return None, Unavailable(
                reason=Reason.FPS_NOT_RECORDED,
                detail="Analyses.FrameRate is missing or zero: the GUI cannot place the preview",
            )
        return None, Unavailable(
            reason=Reason.KEYFRAME_NOT_SHOWN,
            detail="the row as the GUI receives it has no start or end the results table can read",
        )
    unavailable: dict[str, Unavailable] = {}
    t_s = round_ms(frame / fps) if fps else None
    if t_s is None:
        unavailable["t_s"] = Unavailable(
            reason=Reason.FPS_NOT_RECORDED,
            detail="Analyses.FrameRate is missing or zero: the seconds cannot be converted",
        )
    image_ref = None
    if analysis.video_path is None:
        unavailable["frame_image_ref"] = Unavailable(
            reason=Reason.ANALYSIS_RECORD_MISSING, detail=f"{analysis.record} has no VideoPath"
        )
    else:
        image_ref = FrameImageRef(
            video_path=analysis.video_path,
            source_ref=SourceRef(stage=Stage.CONFIG, record_id=f"{analysis.record}/VideoPath", mode="read"),
        )
    key_frame = KeyFrame(
        keyframe_id=keyframe_id(frame),
        frame_index=frame,
        t_s=t_s,
        selection=SELECTION,
        frame_image_ref=image_ref,
        source_ref=PREVIEW_SOURCE,
        unavailable=unavailable or None,
    )
    return key_frame, None


def _suffix(key: str, name: str) -> bool:
    return key.endswith(f".{name}") or key.endswith(f"_{name}") or key == name


def _time_value(raw: RowValue) -> float | None:
    """``parseTimeValue``: a number, a numeric string or ``H:MM:SS(.fff)``."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int | float):
        return float(raw) if math.isfinite(raw) else None
    if not isinstance(raw, str):
        return None
    value = raw.strip()
    numeric = _js_number(value)
    if numeric is not None:
        return numeric
    match = _CLOCK.match(value)
    if match is None:
        return None
    hours, minutes, seconds, fraction = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int((fraction or "").ljust(3, "0")) / 1000


def _js_number(raw: RowValue) -> float | None:
    """``Number(raw)`` when finite, for the values a detection row holds."""
    if isinstance(raw, bool) or raw is None:
        return None
    if isinstance(raw, int | float):
        return float(raw) if math.isfinite(raw) else None
    text = raw.strip()
    if text == "":
        return 0.0
    if not _JS_DECIMAL.match(text):
        return None
    number = float(text)
    return number if math.isfinite(number) else None
