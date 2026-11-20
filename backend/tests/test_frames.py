"""Tests of ``utils.frames.extract_frame_jpeg`` and of the thumbnail endpoint that uses it.

The video is generated here: 10 frames, each filled with a different grey level, so a
decoded thumbnail tells which frame was read.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from fastapi import HTTPException

from api.analysis_controller import AnalysisThumbnailController
from utils.frames import (
    THUMBNAIL_WIDTH,
    FrameOutOfRange,
    VideoNotFound,
    VideoUnreadable,
    extract_frame_jpeg,
)

FRAMES = 10
WIDTH, HEIGHT = 64, 48


def _grey(index: int) -> int:
    return 20 + index * 20


@pytest.fixture
def video(tmp_path):
    path = tmp_path / "clip.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 24, (WIDTH, HEIGHT))
    assert writer.isOpened()
    for index in range(FRAMES):
        writer.write(np.full((HEIGHT, WIDTH, 3), _grey(index), dtype=np.uint8))
    writer.release()
    return path


def _decode(jpeg: bytes) -> np.ndarray:
    image = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image is not None
    return image


@pytest.mark.parametrize("frame", [0, 4, FRAMES - 1])
def test_the_requested_frame_is_returned_at_the_thumbnail_width(video, frame):
    image = _decode(extract_frame_jpeg(video, frame))
    assert image.shape[1] == THUMBNAIL_WIDTH
    assert image.shape[0] == round(HEIGHT * THUMBNAIL_WIDTH / WIDTH)
    assert abs(float(image.mean()) - _grey(frame)) < 6


def test_the_width_can_be_chosen(video):
    assert _decode(extract_frame_jpeg(video, 0, width=32)).shape[1] == 32


def test_a_frame_past_the_end_is_out_of_range(video):
    with pytest.raises(FrameOutOfRange, match="outside the video range"):
        extract_frame_jpeg(video, FRAMES)


def test_a_missing_video_is_not_found(tmp_path):
    with pytest.raises(VideoNotFound, match="video file not found"):
        extract_frame_jpeg(tmp_path / "missing.mp4", 0)


def test_a_file_that_is_not_a_video_cannot_be_opened(tmp_path):
    path = tmp_path / "notes.mp4"
    path.write_text("not a video")
    with pytest.raises(VideoUnreadable, match="could not be opened"):
        extract_frame_jpeg(path, 0)


def _controller(video_path) -> AnalysisThumbnailController:
    service = SimpleNamespace(get_run=lambda analysis_id: SimpleNamespace(video_path=str(video_path)))
    return AnalysisThumbnailController(service)


def test_the_endpoint_serves_the_same_bytes_with_the_same_headers(video):
    response = asyncio.run(_controller(video).on_get("a1", frame=3))
    assert response.body == extract_frame_jpeg(video, 3)
    assert response.media_type == "image/jpeg"
    assert response.headers["cache-control"] == "private, max-age=3600"


@pytest.mark.parametrize(
    ("frame", "missing", "status", "detail"),
    [
        (FRAMES, False, 416, "frame is outside the video range"),
        (0, True, 404, "video file not found for this analysis"),
    ],
)
def test_the_endpoint_keeps_its_status_codes(video, tmp_path, frame, missing, status, detail):
    path = tmp_path / "missing.mp4" if missing else video
    with pytest.raises(HTTPException) as raised:
        asyncio.run(_controller(path).on_get("a1", frame=frame))
    assert raised.value.status_code == status
    assert raised.value.detail == detail
