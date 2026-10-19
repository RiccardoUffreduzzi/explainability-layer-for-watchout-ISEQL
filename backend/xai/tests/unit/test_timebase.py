"""``TimeBase``: frames and seconds agree in both directions."""

import pytest

from xai.contract.reasons import Reason
from xai.k1_harvester.timebase import TimeBase, round_ms

FRAMES = [0, 1, 7, 23, 24, 25, 120, 239, 1001, 86_399]


@pytest.mark.parametrize("fps", [24, 25, 30])
@pytest.mark.parametrize("frame", FRAMES)
def test_frames_and_seconds_agree_both_ways(fps: int, frame: int) -> None:
    timebase = TimeBase(fps)

    read_as_frames = timebase.from_frames(frame, frame, "interval").anchor
    read_as_seconds = timebase.from_seconds(frame / fps, frame / fps, "interval").anchor

    assert read_as_frames.start_s == round_ms(frame / fps)
    assert read_as_seconds.start_frame == frame
    assert read_as_seconds.start_s == read_as_frames.start_s
    assert (read_as_frames.read_as, read_as_seconds.read_as) == ("frames", "seconds")


def test_seconds_are_rounded_to_the_millisecond() -> None:
    anchor = TimeBase(24).from_frames(1, 2, "anchor").anchor

    assert (anchor.start_s, anchor.end_s) == (0.042, 0.083)


def test_frames_are_converted_before_the_seconds_are_rounded() -> None:
    # 0.0208 s * 24 = 0.4992: round() gives frame 0, while 0.021 s would give frame 1.
    anchor = TimeBase(24).from_seconds(0.0208, 0.0208, "interval").anchor

    assert anchor.start_frame == 0
    assert anchor.start_s == 0.021


@pytest.mark.parametrize("fps", [None, 0])
def test_without_fps_the_converted_pair_has_a_reason(fps: int | None) -> None:
    timebase = TimeBase(fps)

    from_frames = timebase.from_frames(24, 48, "interval")
    from_seconds = timebase.from_seconds(1.0, 2.0, "interval")

    assert (from_frames.anchor.start_s, from_frames.anchor.end_s) == (None, None)
    assert set(from_frames.unavailable) == {"interval.start_s", "interval.end_s"}
    assert set(from_seconds.unavailable) == {"interval.start_frame", "interval.end_frame"}
    assert {u.reason for u in from_frames.unavailable.values()} == {Reason.FPS_NOT_RECORDED}
    assert timebase.seconds_of(2, 24) is None


def test_seconds_of_samples() -> None:
    assert TimeBase(24).seconds_of(2, 24) == 2.0
