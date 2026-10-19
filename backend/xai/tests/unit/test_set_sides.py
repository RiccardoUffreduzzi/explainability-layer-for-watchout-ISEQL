"""Rows of F3 rules whose sides are not aligned: read by position once their side is known."""

import pytest

from xai.contract.reasons import InputError
from xai.k1_harvester.ports import (
    Branch,
    DetectedRow,
    Extent,
    RuleLayout,
    SetOperationLayout,
    SideColumns,
    SideField,
)
from xai.k1_harvester.result import HarvestFailure
from xai.k1_harvester.set_sides import fits, read_by_side, row_extent


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


def test_a_padded_row_is_read_as_the_left_side() -> None:
    layout, branch = read_by_side("vehicle_collision/C", LAYOUT, _row({"st": 0.0, "et": 7.5, "__p1": None}))

    assert branch.name == "left"
    assert [(c.label, c.kind, c.fields) for c in layout.columns or ()] == [
        ("st", "st", {"left": "M1.st"}),
        ("et", "et", {"left": "M2.et"}),
    ]
    assert layout.extent.start_seconds == "st" and layout.extent.end_seconds == "et"


def test_a_full_row_is_read_as_the_right_side_with_the_vehicle_in_st() -> None:
    layout, branch = read_by_side("vehicle_collision/C", LAYOUT, _row({"st": 12.0, "et": 6.0, "__p1": 10.0}))

    assert branch.name == "right"
    assert [(c.label, c.kind, c.arg_class) for c in layout.columns or ()] == [
        ("st", "arg1", "vehicle"),
        ("et", "st", None),
        ("__p1", "et", None),
    ]
    assert layout.extent == Extent(start_seconds="et", end_seconds="__p1", start_frames=None, end_frames=None)
    assert layout.form == "F3" and layout.branches == LAYOUT.branches


def test_a_row_that_fits_no_side_is_ambiguous() -> None:
    with pytest.raises(HarvestFailure) as raised:
        read_by_side("vehicle_collision/C", LAYOUT, _row({"st": 3, "et": None, "__p1": 10.0}))

    assert raised.value.code == InputError.ROW_SCHEMA_AMBIGUOUS
    assert "fits neither side" in str(raised.value)


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

    with pytest.raises(HarvestFailure) as raised:
        read_by_side("r/C", layout, _row({"st": 2, "et": 5.0}))

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
