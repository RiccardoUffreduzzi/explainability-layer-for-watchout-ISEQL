"""Values of detection rows: comparison, columns, event extent and entities.

The engine returns rows as JSON objects, so values are forced to be compared as numbers.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TypeGuard

from xai.contract.ids import RowValue
from xai.k1_harvester.ports import Branch, DetectedRow, EngineError, Extent, ResultColumn, RuleLayout
from xai.k1_harvester.timebase import TimeBase, TimedAnchor


@dataclass(frozen=True)
class RowColumns:
    """What each column of a detection row holds and which keys hold its start and end"""

    columns: tuple[ResultColumn, ...]
    extent: Extent


def row_branches(layout: RuleLayout, row: DetectedRow) -> tuple[Branch, ...]:
    """The branches with a witness of the row, in rule order."""
    names = set(row.branches)
    branches = tuple(b for b in layout.branches if b.name in names)
    if not branches:
        raise EngineError("the lineage gives no witness of the row in a branch of the rule")
    return branches


def row_columns(layout: RuleLayout, row: DetectedRow) -> RowColumns:
    """The rule's columns; for an F3 rule whose sides fill a column differently.

    WatchOut aligns the two sides of an F3 rule by position and names the columns after
    the left side. The row is read as the first side of the rule with a witness of it:
    the only one after a union or a difference, the left one after an intersection,
    whose rows are equal on both sides.
    """
    if layout.columns is not None:
        return RowColumns(columns=layout.columns, extent=layout.extent)
    branch = row_branches(layout, row)[0]
    keys = list(row.values)
    position = {f.field: i for i, f in enumerate(branch.fields)}

    def key(field: str | None) -> str | None:
        if field is None or field not in position or position[field] >= len(keys):
            return None
        return keys[position[field]]

    columns = tuple(
        ResultColumn(label=label, kind=f.kind, fields={branch.name: f.field}, arg_class=f.arg_class)
        for label, f in zip(keys, branch.fields, strict=False)
    )
    side = branch.extent
    extent = Extent(
        start_seconds=key(side.start_seconds),
        end_seconds=key(side.end_seconds),
        start_frames=key(side.start_frames),
        end_frames=key(side.end_frames),
    )
    return RowColumns(columns=columns, extent=extent)


def is_number(value: object) -> TypeGuard[int | float]:
    return isinstance(value, int | float) and not isinstance(value, bool)


def same_value(a: object, b: object) -> bool:
    """Equality of two row values: numbers by value, text exactly, null only with null."""
    if a is None or b is None:
        return a is None and b is None
    if is_number(a) and is_number(b):
        return a == b
    if isinstance(a, str) and isinstance(b, str):
        return a == b
    return False


def same_row(a: Mapping[str, RowValue], b: Mapping[str, RowValue]) -> bool:
    """Same columns with the same values."""
    return a.keys() == b.keys() and all(same_value(a[k], b[k]) for k in a)


def row_matches(requested: Mapping[str, object], row: DetectedRow) -> bool:
    """Whether the requested values identify this row.

    The request names every column the engine returned, and may add the frame
    columns the GUI derives; each value equals the engine's value or the GUI's
    so a row copied from the GUI is found.
    """
    keys = set(requested)
    if not set(row.values) <= keys <= set(row.gui_values):
        return False
    return all(
        same_value(value, row.values.get(key)) or same_value(value, row.gui_values.get(key))
        for key, value in requested.items()
    )


def extent_anchor(
    values: Mapping[str, RowValue], extent: Extent, timebase: TimeBase, field: str
) -> TimedAnchor | None:
    """The event's start and end in a row, as ``detect_event`` finds them; None when not readable."""
    start_s = values.get(extent.start_seconds) if extent.start_seconds else None
    end_s = values.get(extent.end_seconds) if extent.end_seconds else None
    if is_number(start_s) and is_number(end_s):
        return timebase.from_seconds(float(start_s), float(end_s), field)
    start_f = values.get(extent.start_frames) if extent.start_frames else None
    end_f = values.get(extent.end_frames) if extent.end_frames else None
    if _is_integral(start_f) and _is_integral(end_f):
        return timebase.from_frames(int(start_f), int(end_f), field)
    return None


def class_id(value: object) -> int | None:
    """A ClassID in a row: an integer, also when written as ``3.0``; None otherwise."""
    if _is_integral(value) and value >= 0:
        return int(value)
    return None


def _is_integral(value: object) -> TypeGuard[int | float]:
    return is_number(value) and float(value).is_integer()
