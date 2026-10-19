"""Rows of F3 rules whose sides are not aligned: read by position once their side is known."""

from dataclasses import replace
from typing import cast

import pytest

from xai.adapters.watchout.set_sides import fits, read_by_side, row_columns, row_extent
from xai.contract.reasons import InputError
from xai.k1_harvester.locate import EventLocator
from xai.k1_harvester.ports import (
    Branch,
    DetectedRow,
    Extent,
    ResultColumn,
    RowColumns,
    RowNotReadable,
    RuleLayout,
    SetOperationLayout,
    SideColumns,
    SideField,
    WatchOutReader,
)
from xai.k1_harvester.result import HarvestFailure


def _branch(name: str, projection: tuple[str, ...]) -> Branch:
    return Branch(
        name=name,
        side=name,
        intervals=(),
        conditions=(),
        projection=projection,
        projection_pointer=f"/{name}_projection",
        projection_text=", ".join(projection),
    )


def _side(*fields: tuple[str, str, str | None], start: str, end: str) -> SideColumns:
    return SideColumns(
        fields=tuple(SideField(field=f, kind=k, arg_class=c) for f, k, c in fields),
        extent=Extent(start_seconds=start, end_seconds=end, start_frames=None, end_frames=None),
    )


# The ablation vehicle_collision/C: audio on the left (st, et), visual on the right (arg1, st, et).
LEFT = _side(("M1.st", "st", None), ("M2.et", "et", None), start="M1.st", end="M2.et")
RIGHT = _side(
    ("M1.arg1", "arg1", "vehicle"), ("M1.st", "st", None), ("M1.et", "et", None), start="M1.st", end="M1.et"
)
LAYOUT = RuleLayout(
    form="F3",
    branches=(_branch("left", ("M1.st", "M2.et")), _branch("right", ("M1.arg1", "M1.st", "M1.et"))),
    set_operation=SetOperationLayout(op="∪", pointer="/set_operator", children=("left", "right")),
    multiset=False,
    columns=None,
    columns_problem="set_side rule: result column 1 is st in the left side and arg1 in the right side",
    extent=Extent(start_seconds="M1.st", end_seconds="M2.et", start_frames="M1.sf", end_frames="M2.ef"),
    side_columns={"left": LEFT, "right": RIGHT},
)


def _row(values: dict[str, float | int | None]) -> DetectedRow:
    return DetectedRow(values=values, gui_values=values)


class _SideReader:
    """The one port method the locator calls to read a row by side."""

    def row_columns(self, layout: RuleLayout, row: DetectedRow) -> RowColumns:
        return row_columns(layout, row)


def test_a_padded_row_is_read_as_the_left_side() -> None:
    read = read_by_side(LAYOUT, _row({"st": 0.0, "et": 7.5, "__p1": None}))

    assert read.side is not None and read.side.name == "left"
    assert [(c.label, c.kind, c.fields) for c in read.columns] == [
        ("st", "st", {"left": "M1.st"}),
        ("et", "et", {"left": "M2.et"}),
    ]
    assert read.extent.start_seconds == "st" and read.extent.end_seconds == "et"


def test_a_full_row_is_read_as_the_right_side_with_the_vehicle_in_st() -> None:
    read = read_by_side(LAYOUT, _row({"st": 12.0, "et": 6.0, "__p1": 10.0}))

    assert read.side is not None and read.side.name == "right"
    assert [(c.label, c.kind, c.arg_class) for c in read.columns] == [
        ("st", "arg1", "vehicle"),
        ("et", "st", None),
        ("__p1", "et", None),
    ]
    assert read.extent == Extent(start_seconds="et", end_seconds="__p1", start_frames=None, end_frames=None)
    assert read.method is not None and "as its right side" in read.method


def test_a_rule_with_columns_gives_them_to_every_row() -> None:
    columns = (ResultColumn(label="M1.st", kind="st", fields={"left": "M1.st"}, arg_class=None),)
    layout = replace(LAYOUT, columns=columns, side_columns={})

    assert row_columns(layout, _row({"M1.st": 1.0})) == RowColumns(columns=columns, extent=LAYOUT.extent)


def test_a_row_that_fits_no_side_is_ambiguous() -> None:
    with pytest.raises(RowNotReadable) as raised:
        read_by_side(LAYOUT, _row({"st": 3, "et": None, "__p1": 10.0}))

    assert "fits neither side" in str(raised.value)


def test_the_locator_refuses_a_row_it_cannot_read() -> None:
    locator = EventLocator(cast(WatchOutReader, _SideReader()))

    with pytest.raises(HarvestFailure) as raised:
        locator.row_columns("vehicle_collision/C", LAYOUT, _row({"st": 3, "et": None, "__p1": 10.0}))

    assert raised.value.code == InputError.ROW_SCHEMA_AMBIGUOUS
    assert raised.value.detail.startswith("vehicle_collision/C: set_side rule: ")
    assert "fits neither side" in raised.value.detail


def test_a_row_that_fits_both_sides_is_ambiguous() -> None:
    same_width = _side(("M1.arg1", "arg1", "person"), ("M1.st", "st", None), start="M1.st", end="M1.st")
    other = _side(("M1.st", "st", None), ("M1.et", "et", None), start="M1.st", end="M1.et")
    layout = RuleLayout(
        form="F3",
        branches=(_branch("left", ("M1.st", "M1.et")), _branch("right", ("M1.arg1", "M1.st"))),
        set_operation=None,
        multiset=False,
        columns=None,
        columns_problem="set_side rule: result column 1 is st in the left side and arg1 in the right side",
        extent=LAYOUT.extent,
        side_columns={"left": other, "right": same_width},
    )

    with pytest.raises(RowNotReadable) as raised:
        read_by_side(layout, _row({"st": 2, "et": 5.0}))

    assert "fits both sides" in str(raised.value)


@pytest.mark.parametrize(
    ("values", "left", "right"),
    [
        ({"st": 0.0, "et": 7.5, "__p1": None}, True, False),
        ({"st": 1, "et": 5.0, "__p1": 5.0}, False, True),
        ({"st": None, "et": 7.5, "__p1": None}, False, False),
        ({"st": 0.0}, False, False),
    ],
)
def test_fits(values: dict[str, float | None], left: bool, right: bool) -> None:
    keys = list(values)

    assert fits(LEFT, keys, values) is left
    assert fits(RIGHT, keys, values) is right


def test_row_extent_skips_fields_past_the_row() -> None:
    assert row_extent(RIGHT, ["st", "et"]) == Extent(
        start_seconds="et", end_seconds=None, start_frames=None, end_frames=None
    )
