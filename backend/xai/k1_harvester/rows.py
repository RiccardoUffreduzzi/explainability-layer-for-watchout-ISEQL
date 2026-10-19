"""Values of detection rows: comparison, event extent and entities.

The engine returns rows as JSON objects; numbers may come back as ``3`` or ``3.0``
(pandas turns an integer column with NULLs into floats), so values are compared
as numbers, never as text, and booleans are never numbers.
"""

from collections.abc import Mapping
from typing import TypeGuard

from xai.contract.ids import RowValue
from xai.k1_harvester.ports import DetectedRow, Extent
from xai.k1_harvester.timebase import TimeBase, TimedAnchor


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
    (seconds formatted as ``HH:MM:SS.mmm``), so a row copied from the GUI is found.
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
