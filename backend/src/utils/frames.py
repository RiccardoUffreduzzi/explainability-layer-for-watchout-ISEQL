"""One frame of an analysis video as a JPEG.

``extract_frame_jpeg`` is what the thumbnail endpoint serves to the results table
(``AnalysisThumbnailController``)
"""
from __future__ import annotations

from pathlib import Path

import cv2

THUMBNAIL_WIDTH = 360
"""Width in pixels of the image the results table shows."""


class FrameError(Exception):
    """The frame cannot be returned; the message says why."""


class VideoNotFound(FrameError):
    """The video file of the analysis does not exist."""


class VideoUnreadable(FrameError):
    """OpenCV cannot open the video file."""


class FrameOutOfRange(FrameError):
    """The frame is past the last frame of the video."""


class FrameUnreadable(FrameError):
    """The frame cannot be read or has no pixels."""


class FrameNotEncoded(FrameError):
    """The frame cannot be encoded as JPEG."""


def extract_frame_jpeg(video_path: str | Path, frame: int, width: int = THUMBNAIL_WIDTH) -> bytes:
    """Frame (counted from 0) of the video, resized to ``width`` pixels, as JPEG bytes.

    The height keeps the aspect ratio. The frame is reached with ``CAP_PROP_POS_FRAMES``.
    """
    path = Path(video_path)
    if not path.is_file():
        raise VideoNotFound("video file not found for this analysis")

    cap = cv2.VideoCapture(str(path))
    try:
        if not cap.isOpened():
            raise VideoUnreadable("video file could not be opened")

        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if frame_count > 0 and frame >= frame_count:
            raise FrameOutOfRange("frame is outside the video range")

        cap.set(cv2.CAP_PROP_POS_FRAMES, frame)
        ok, image = cap.read()
        if not ok or image is None:
            raise FrameUnreadable("could not extract requested video frame")

        height, image_width = image.shape[:2]
        if image_width <= 0 or height <= 0:
            raise FrameUnreadable("extracted video frame has invalid dimensions")
        thumbnail_height = max(1, round(height * width / image_width))
        thumbnail = cv2.resize(image, (width, thumbnail_height), interpolation=cv2.INTER_AREA)
        encoded, jpeg = cv2.imencode(".jpg", thumbnail)
        if not encoded:
            raise FrameNotEncoded("could not encode thumbnail")
        return jpeg.tobytes()
    finally:
        cap.release()
