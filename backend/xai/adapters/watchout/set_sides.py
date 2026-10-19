"""Rows of F3 rules whose two sides put different kinds at the same position.

WatchOut joins the sides of a ``set_side`` rule with a SQL set operator: the
columns are aligned by position, the shorter side is padded with NULLs
(``_pad_fields``) and the columns take the names of the left side. In the
ablation rules the left side projects ``(st, et)`` and the right one
``(arg1, st, et)``: a visual row arrives as ``{"st": 3, "et": 10.0, "__p1": 10.0}``,
with the vehicle in ``st``. Such a row is read by position, once its side is known.

A row fits a side when the columns past the side's own fields are null (the
padding) and the side's start and end hold a time (``StartFrame`` and
``EndFrame`` are ``NOT NULL`` in WatchOut's tables). A row that fits both sides
or neither cannot be read (``RowNotReadable``).
"""

from collections.abc import Mapping, Sequence

from xai.contract.ids import RowValue
from xai.k1_harvester.ports import (
    Branch,
    DetectedRow,
    Extent,
    ResultColumn,
    RowColumns,
    RowNotReadable,
    RuleLayout,
    SideColumns,
)
from xai.k1_harvester.rows import is_number


def row_columns(layout: RuleLayout, row: DetectedRow) -> RowColumns:
    """What each column of the row holds: the rule's columns, or those of the side the row fits."""
    if layout.columns is not None:
        return RowColumns(columns=layout.columns, extent=layout.extent)
    return read_by_side(layout, row)


def read_by_side(layout: RuleLayout, row: DetectedRow) -> RowColumns:
    """The columns and extent of the side the row comes from; ``RowNotReadable`` when not exactly one fits."""
    keys = list(row.values)
    fitting = [
        (branch, side)
        for branch in layout.branches
        if (side := layout.side_columns.get(branch.name)) is not None and fits(side, keys, row.values)
    ]
    if len(fitting) != 1:
        which = "both sides" if fitting else "neither side"
        raise RowNotReadable(
            f"{layout.columns_problem}; the row fits {which} "
            "(padding columns null, start and end present), so its columns cannot be read"
        )
    branch, side = fitting[0]
    columns = tuple(
        ResultColumn(label=key, kind=f.kind, fields={branch.name: f.field}, arg_class=f.arg_class)
        for key, f in zip(keys, side.fields, strict=False)
    )
    return RowColumns(
        columns=columns, extent=row_extent(side, keys), side=branch, method=side_method(branch, columns)
    )


def fits(side: SideColumns, keys: Sequence[str], values: Mapping[str, RowValue]) -> bool:
    """Whether a row can come from this side: its padding is null, its start and end are times."""
    if len(keys) < len(side.fields):
        return False
    if any(values[key] is not None for key in keys[len(side.fields) :]):
        return False
    extent = row_extent(side, keys)
    pairs = ((extent.start_seconds, extent.end_seconds), (extent.start_frames, extent.end_frames))
    return any(
        start is not None and end is not None and is_number(values[start]) and is_number(values[end])
        for start, end in pairs
    )


def row_extent(side: SideColumns, keys: Sequence[str]) -> Extent:
    """The side's extent fields turned into the row keys at their positions."""
    position = {f.field: i for i, f in enumerate(side.fields)}

    def key(field: str | None) -> str | None:
        if field is None or field not in position or position[field] >= len(keys):
            return None
        return keys[position[field]]

    return Extent(
        start_seconds=key(side.extent.start_seconds),
        end_seconds=key(side.extent.end_seconds),
        start_frames=key(side.extent.start_frames),
        end_frames=key(side.extent.end_frames),
    )


def side_method(branch: Branch, columns: Sequence[ResultColumn]) -> str:
    """How the row was read, for ``origin_basis.method`` and the note on labels (``RowColumns.method``)."""
    mapping = ", ".join(f"{c.label} → {c.kind} ({c.fields[branch.name]})" for c in columns)
    return (
        f"set_side rule read by position as its {branch.name} side ({mapping}): WatchOut aligns "
        "the sides by position, pads the shorter one with NULLs and names the columns after the "
        "left side; the row fits only this side (padding null, start and end present)"
    )
