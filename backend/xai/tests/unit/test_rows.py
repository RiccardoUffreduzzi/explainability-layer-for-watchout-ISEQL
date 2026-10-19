"""Values of detection rows: comparison, the row of a request, extent and entities."""

import pytest

from xai.k1_harvester.ports import DetectedRow, Extent
from xai.k1_harvester.rows import class_id, extent_anchor, row_matches, same_row, same_value
from xai.k1_harvester.timebase import TimeBase

ROW = DetectedRow(
    values={"M1_vehicle": 12.0, "M1.st": 6.0, "M2.et": 10.0},
    gui_values={
        "M1_vehicle": 12.0,
        "M1.st": "00:00:06.000",
        "M2.et": "00:00:10.000",
        "M1.sf": 144,
        "M2.ef": 240,
    },
)


@pytest.mark.parametrize(
    ("a", "b", "same"),
    [
        (3, 3.0, True),
        (None, None, True),
        ("x", "x", True),
        (None, 0, False),
        (True, 1, False),
        ("3", 3, False),
        (0.1 + 0.2, 0.3, False),
    ],
)
def test_same_value(a: object, b: object, same: bool) -> None:
    assert same_value(a, b) is same


def test_same_row_needs_the_same_columns() -> None:
    assert same_row({"a": 1, "b": None}, {"b": None, "a": 1.0})
    assert not same_row({"a": 1}, {"a": 1, "b": None})


@pytest.mark.parametrize(
    "requested",
    [
        {"M1_vehicle": 12, "M1.st": 6.0, "M2.et": 10.0},  # as the engine returns it
        {"M1_vehicle": 12, "M1.st": "00:00:06.000", "M2.et": "00:00:10.000"},  # as the GUI shows it
        {"M1_vehicle": 12, "M1.st": 6, "M2.et": "00:00:10.000", "M1.sf": 144, "M2.ef": 240},  # mixed
    ],
)
def test_a_row_is_found_as_the_engine_or_the_gui_writes_it(requested: dict[str, object]) -> None:
    assert row_matches(requested, ROW)


@pytest.mark.parametrize(
    "requested",
    [
        {"M1_vehicle": 1, "M1.st": 6.0, "M2.et": 10.0},  # another value
        {"M1_vehicle": 12, "M1.st": 6.0},  # a column missing
        {"M1_vehicle": 12, "M1.st": 6.0, "M2.et": 10.0, "M9.st": 1.0},  # a column the row does not have
        {"M1_vehicle": 12, "M1.st": "00:00:06.0", "M2.et": 10.0},  # time not as the GUI formats it
    ],
)
def test_other_rows_are_not_found(requested: dict[str, object]) -> None:
    assert not row_matches(requested, ROW)


def test_extent_from_seconds_then_from_frames() -> None:
    timebase = TimeBase(24)
    seconds = Extent(start_seconds="M1.st", end_seconds="M2.et", start_frames=None, end_frames=None)
    frames = Extent(start_seconds="M1.st", end_seconds="M2.et", start_frames="M1.sf", end_frames="M2.ef")

    by_seconds = extent_anchor(ROW.values, seconds, timebase, "interval")
    by_frames = extent_anchor({"M1.st": None, "M2.et": None, "M1.sf": 24, "M2.ef": 48}, frames, timebase, "x")

    assert by_seconds is not None and by_seconds.anchor.start_frame == 144
    assert by_frames is not None and (by_frames.anchor.start_s, by_frames.anchor.read_as) == (1.0, "frames")
    assert extent_anchor({"M1.st": None, "M2.et": 1.0}, seconds, timebase, "x") is None


@pytest.mark.parametrize(
    ("value", "expected"), [(3, 3), (3.0, 3), (3.5, None), (-1, None), ("3", None), (None, None)]
)
def test_class_id(value: object, expected: int | None) -> None:
    assert class_id(value) == expected
