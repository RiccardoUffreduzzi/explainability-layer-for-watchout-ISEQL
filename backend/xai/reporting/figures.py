"""The key frame of the detection in a report: its image and the caption the system writes.

The image is the frame WatchOut shows; the frame is named by the source of truth
(``event.key_frame``). The LLM writes a sentence on the key frame from its time and its frame,
but never sees the image nor the caption: they are added to the report after its text is rendered.
"""

import hashlib
from dataclasses import dataclass
from typing import Final, Literal

from xai.contract.model import KeyFrame
from xai.contract.report import Figure
from xai.contract.source_of_truth import SourceOfTruth
from xai.reporting.catalogue import SystemSentences, TimeFormat
from xai.reporting.ports import FrameImages, FrameUnavailable
from xai.reporting.values import clock

KEY_FRAME_POINTER: Final = "#/event/key_frame"


@dataclass(frozen=True)
class KeyFrameFigure:
    figure: Figure
    jpeg: bytes | None
    """The bytes of ``figure.file``; None when the figure is not shown."""


def image_name(event_id: str) -> str:
    """The file of the image, beside the report: ``<ev_id>.jpg``."""
    return f"{event_id}.jpg"


def key_frame_figure(
    document: SourceOfTruth,
    frames: FrameImages,
    sentences: SystemSentences,
    time_format: TimeFormat = "m:ss",
) -> KeyFrameFigure | None:
    """The figure of the key frame; None when the source of truth has no key frame."""
    key_frame = document.event.key_frame
    if key_frame is None:
        return None
    try:
        jpeg = frames.image(key_frame)
    except FrameUnavailable as missing:
        caption = _fill(sentences.figure["not_available"], frame=key_frame.frame_index, reason=str(missing))
        return KeyFrameFigure(_figure(key_frame, "not_available", caption), None)
    figure = _figure(
        key_frame,
        "shown",
        _caption(key_frame, sentences, time_format),
        file=image_name(document.event.event_id),
        sha256=hashlib.sha256(jpeg).hexdigest(),
    )
    return KeyFrameFigure(figure, jpeg)


def _caption(key_frame: KeyFrame, sentences: SystemSentences, time_format: TimeFormat) -> str:
    if key_frame.t_s is None:
        return _fill(sentences.figure["shown_without_time"], frame=key_frame.frame_index)
    return _fill(
        sentences.figure["shown"], frame=key_frame.frame_index, time=clock(key_frame.t_s, time_format)
    )


def _figure(
    key_frame: KeyFrame,
    status: Literal["shown", "not_available"],
    caption: str,
    file: str | None = None,
    sha256: str | None = None,
) -> Figure:
    return Figure(
        keyframe_id=key_frame.keyframe_id,
        frame_index=key_frame.frame_index,
        ref=KEY_FRAME_POINTER,
        status=status,
        caption=caption,
        file=file,
        sha256=sha256,
    )


def _fill(template: str, **slots: object) -> str:
    for name, value in slots.items():
        template = template.replace(f"<{name}>", str(value))
    return template
