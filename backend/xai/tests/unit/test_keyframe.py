"""``preview_frame`` repeats the GUI's preview (``results-table.svelte``); the key frame of the draft."""

from typing import Any

import pytest

from xai.contract.ids import RowValue
from xai.contract.primitives import Stage
from xai.contract.reasons import Reason
from xai.k1_harvester.keyframe import harvest_key_frame, preview_frame
from xai.k1_harvester.ports import AnalysisSnapshot

ROWS: list[tuple[str, dict[str, Any], float | None, int | None]] = [
    # what detect_event passes to the GUI: seconds as HH:MM:SS.mmm, frames added for the extent
    (
        "frames of the extent",
        {"M1.st": "00:00:01.000", "M1.sf": 24, "M2.et": "00:00:08.000", "M2.ef": 192},
        24,
        108,
    ),
    ("odd sum of frames is floored", {"M1.st": "00:00:01.000", "M1.sf": 24, "M1.et": 2, "M1.ef": 49}, 24, 36),
    ("start and end on the same frame", {"M1.sf": 48, "M1.ef": 48, "M1.st": 2.0, "M1.et": 2.0}, 24, 48),
    ("seconds only", {"st": 12.0, "et": 6.0, "__p1": 10.0}, 24, 216),
    ("seconds only, floored", {"M1.st": 0.0, "M1.et": 0.99}, 25, 12),
    ("clock with fraction", {"M1_st": "00:01:02.5", "M1_et": "00:01:03"}, 10, 627),
    ("minimum start, maximum end", {"M1.st": 4, "M2.st": 2, "M1.et": 6, "M2.et": 9}, 2, 11),
    ("frames without seconds use the fps", {"M1.sf": 10, "M1.ef": 20}, 24, 15),
    ("frames without seconds and no fps", {"M1.sf": 10, "M1.ef": 20}, None, None),
    ("frames with seconds and no fps", {"M1.st": 1, "M1.sf": 10, "M1.et": 2, "M1.ef": 20}, None, 15),
    ("seconds and no fps", {"M1.st": 1.0, "M1.et": 2.0}, 0, None),
    ("no end", {"M1.st": 1.0, "M1_person": 3}, 24, None),
    ("unreadable times are skipped", {"M1.st": "soon", "M2.st": 1.0, "M1.et": 3.0, "M1.sf": "x"}, 24, 48),
    ("empty and null values are skipped", {"M1.st": "", "M2.st": 1.0, "M1.et": 3.0, "M2.et": None}, 24, 48),
    ("argument columns are not times", {"M1_person": 3, "M1.arg1": 5, "M1.st": 0, "M1.et": 1}, 24, 12),
]


@pytest.mark.parametrize(("row", "fps", "frame"), [r[1:] for r in ROWS], ids=[r[0] for r in ROWS])
def test_preview_frame_is_the_one_of_the_gui(
    row: dict[str, Any], fps: float | None, frame: int | None
) -> None:
    assert preview_frame(row, fps) == frame


def _analysis(video_path: str | None = "/videos/a1.mp4") -> AnalysisSnapshot:
    return AnalysisSnapshot(
        analysis_id="a1",
        condition="A",
        stage="done",
        vlm_provider=None,
        model=None,
        audio_provider=None,
        audio_model=None,
        audio_quantization=None,
        frame_rate=24.0,
        sampling_hz=1.0,
        fps_column="FrameRate",
        audio_window=None,
        audio_hop=None,
        video_path=video_path,
    )


HANDOFF: dict[str, RowValue] = {"M1.st": "00:00:01.000", "M1.sf": 24, "M2.et": "00:00:08.000", "M2.ef": 192}


def test_the_key_frame_names_the_frame_its_time_and_the_video() -> None:
    key_frame, reason = harvest_key_frame(HANDOFF, _analysis(), 24.0)

    assert reason is None and key_frame is not None
    assert (key_frame.keyframe_id, key_frame.frame_index, key_frame.t_s) == ("kf_108", 108, 4.5)
    assert key_frame.selection == "gui_preview_midpoint"
    assert key_frame.source_ref.stage is Stage.KEYFRAMES
    assert key_frame.frame_image_ref is not None
    assert key_frame.frame_image_ref.video_path == "/videos/a1.mp4"
    assert key_frame.frame_image_ref.source_ref.record_id == "Analyses/a1/VideoPath"
    assert key_frame.unavailable is None


def test_without_video_path_the_image_reference_has_a_reason() -> None:
    key_frame, _ = harvest_key_frame(HANDOFF, _analysis(video_path=None), 24.0)

    assert key_frame is not None and key_frame.frame_image_ref is None
    assert key_frame.unavailable is not None
    assert key_frame.unavailable["frame_image_ref"].reason is Reason.ANALYSIS_RECORD_MISSING


def test_without_fps_the_frame_of_a_row_with_frames_has_no_time() -> None:
    key_frame, _ = harvest_key_frame(HANDOFF, _analysis(), None)

    assert key_frame is not None and key_frame.t_s is None
    assert key_frame.unavailable is not None
    assert key_frame.unavailable["t_s"].reason is Reason.FPS_NOT_RECORDED


@pytest.mark.parametrize(
    ("row", "fps", "reason"),
    [
        ({"M1.st": 1.0, "M1.et": 2.0}, None, Reason.FPS_NOT_RECORDED),
        ({"M1.st": 1.0, "M1_person": 3}, 24.0, Reason.KEYFRAME_NOT_SHOWN),
    ],
)
def test_a_row_without_preview_has_no_key_frame_and_a_reason(
    row: dict[str, RowValue], fps: float | None, reason: Reason
) -> None:
    key_frame, unavailable = harvest_key_frame(row, _analysis(), fps)

    assert key_frame is None
    assert unavailable is not None and unavailable.reason is reason
