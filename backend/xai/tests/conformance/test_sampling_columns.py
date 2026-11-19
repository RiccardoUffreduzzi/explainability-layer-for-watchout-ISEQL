"""How the adapter reads the frame rate and the sampling rate of an ``Analyses`` row.

WatchOut stores the video fps in ``FrameRate`` and the requested visual sampling, in Hz,
in ``SamplingRate``. Rows written before the two were split have no FrameRate: their
SamplingRate was the fps and the stride, so one frame per second was analysed.
"""

from xai.adapters.watchout.records import _sampling


def test_a_row_with_frame_rate_reads_both_columns() -> None:
    assert _sampling(30.0, 0.5) == {"frame_rate": 30, "sampling_hz": 0.5, "fps_column": "FrameRate"}
    assert _sampling(29.97, 2.0) == {"frame_rate": 29.97, "sampling_hz": 2, "fps_column": "FrameRate"}


def test_a_legacy_row_reads_the_fps_from_sampling_rate_at_one_hertz() -> None:
    assert _sampling(None, 24) == {"frame_rate": 24, "sampling_hz": 1.0, "fps_column": "SamplingRate"}


def test_a_missing_or_zero_rate_is_none() -> None:
    assert _sampling(None, None) == {"frame_rate": None, "sampling_hz": None, "fps_column": "SamplingRate"}
    assert _sampling(None, 0) == {"frame_rate": None, "sampling_hz": None, "fps_column": "SamplingRate"}
    assert _sampling(0.0, 1.0)["frame_rate"] is None
