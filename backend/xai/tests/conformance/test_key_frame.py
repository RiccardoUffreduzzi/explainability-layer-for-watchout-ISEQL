"""The key frame is WatchOut's: the GUI's formula, the analysis video and the thumbnail function (A2-bis).

- K1 repeats the preview formula of ``results-table.svelte``: these tests fail when the lines
  K1 repeats change upstream, so the two cannot drift apart in silence.
- K1 reads the path of the video from ``Analyses.VideoPath``.
- K5 extracts the image with ``extract_frame_jpeg``, the function behind the thumbnail endpoint.
"""

import json
import sqlite3
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pytest
from utils.frames import THUMBNAIL_WIDTH, extract_frame_jpeg

from xai.adapters.watchout.frames import WatchOutFrameImages
from xai.adapters.watchout.queries import table_columns
from xai.contract.model import KeyFrame
from xai.reporting.ports import FrameUnavailable
from xai.tests.k5_support import ScriptedModel, hand_text, pair_of, writer
from xai.tests.support import REPO_DIR

RESULTS_TABLE = REPO_DIR / "frontend" / "src" / "lib" / "components" / "results-table.svelte"

GUI_LINES = (
    "if (k.endsWith('.st') || k.endsWith('_st') || k === 'st') {",
    "if (k.endsWith('.et') || k.endsWith('_et') || k === 'et') {",
    "if (k.endsWith('.sf') || k.endsWith('_sf') || k === 'sf') {",
    "} else if (k.endsWith('.ef') || k.endsWith('_ef') || k === 'ef') {",
    "if (value !== null) startSec = startSec === null ? value : Math.min(startSec, value);",
    "if (value !== null) endSec = endSec === null ? value : Math.max(endSec, value);",
    "if (startSec === null && startFrame !== null && fps > 0) startSec = startFrame / fps;",
    "if (endSec === null && endFrame !== null && fps > 0) endSec = endFrame / fps;",
    "previewFrame = Math.floor((interval.startFrame + interval.endFrame) / 2);",
    "previewFrame = Math.floor(((interval.startSec + interval.endSec) / 2) * fps);",
    "const match = value.match(/^(\\d+):(\\d{2}):(\\d{2})(?:\\.(\\d{1,3}))?$/);",
)
"""The lines of the GUI that ``xai.k1_harvester.keyframe.preview_frame`` repeats."""

FRAMES = 120


@pytest.mark.parametrize("line", GUI_LINES)
def test_the_gui_still_chooses_the_preview_frame_as_k1_repeats_it(line: str) -> None:
    source = [text.strip() for text in RESULTS_TABLE.read_text(encoding="utf-8").splitlines()]

    assert line in source


def test_the_analyses_table_records_the_path_of_the_video(watchout_db: Path) -> None:
    conn = sqlite3.connect(watchout_db)
    try:
        assert "VideoPath" in table_columns(conn, "Analyses")
    finally:
        conn.close()


@pytest.fixture
def video(tmp_path: Path) -> Path:
    """A video of 120 frames, each a different grey level."""
    path = tmp_path / "scene.avi"
    out = cv2.VideoWriter(str(path), cv2.VideoWriter.fourcc(*"MJPG"), 24, (64, 48))
    for index in range(FRAMES):
        out.write(np.full((48, 64, 3), index * 2, dtype=np.uint8))
    out.release()
    return path


def _key_frame(video_path: Path | None, frame: int = 108) -> KeyFrame:
    image_ref: dict[str, Any] | None = None
    if video_path is not None:
        image_ref = {
            "video_path": str(video_path),
            "source_ref": {"stage": "config", "record_id": "Analyses/a1/VideoPath", "mode": "read"},
        }
    return KeyFrame.model_validate_json(
        json.dumps(
            {
                "keyframe_id": f"kf_{frame}",
                "frame_index": frame,
                "t_s": frame / 24,
                "selection": "gui_preview_midpoint",
                "frame_image_ref": image_ref,
                "source_ref": {
                    "stage": "keyframes",
                    "record_id": "results-table.svelte#previewFrame",
                    "mode": "read",
                },
            }
        )
    )


def test_the_adapter_gives_the_image_of_the_thumbnail_endpoint(video: Path) -> None:
    jpeg = WatchOutFrameImages().image(_key_frame(video))

    assert jpeg == extract_frame_jpeg(video, 108)
    image = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image.shape[1] == THUMBNAIL_WIDTH


@pytest.mark.parametrize(
    ("video_path", "frame", "reason"),
    [
        (Path("/nowhere/scene.mp4"), 0, "video file not found for this analysis"),
        (None, 0, "the analysis does not record the path of its video"),
    ],
)
def test_the_adapter_says_why_there_is_no_image(video_path: Path | None, frame: int, reason: str) -> None:
    with pytest.raises(FrameUnavailable, match=reason):
        WatchOutFrameImages().image(_key_frame(video_path, frame))


def test_a_frame_past_the_end_of_the_video_has_no_image(video: Path) -> None:
    with pytest.raises(FrameUnavailable, match="outside the video range"):
        WatchOutFrameImages().image(_key_frame(video, FRAMES))


def test_report_1_shows_the_frame_of_the_analysis_video(video: Path) -> None:
    def on_this_video(data: dict[str, Any]) -> None:
        data["event"]["key_frame"]["frame_image_ref"]["video_path"] = str(video)

    plan, document = pair_of("handoff_s21_A", on_this_video)
    written = writer(ScriptedModel([hand_text("handoff_s21_A")]), frames=WatchOutFrameImages()).write(
        plan, document
    )

    assert written.image == extract_frame_jpeg(video, 108)
    (figure,) = [s.figure for s in written.report.sections if s.figure is not None]
    assert figure.status == "shown" and figure.frame_index == 108
