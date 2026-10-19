"""Paths of fields in the JSON data of a draft.

A path is a tuple of keys and list positions. ``render`` writes it with the
positions (``rule.constraints[3].parent``), ``pattern`` with ``[*]``
(``rule.constraints[*].parent``), the form ``missing_fields`` uses.
"""

from collections.abc import Iterator, Sequence
from typing import Any

Path = tuple[str | int, ...]


def render(path: Sequence[str | int]) -> str:
    text = ""
    for part in path:
        text += f"[{part}]" if isinstance(part, int) else (f".{part}" if text else part)
    return text


def pattern(path: Sequence[str | int]) -> str:
    text = ""
    for part in path:
        text += "[*]" if isinstance(part, int) else (f".{part}" if text else part)
    return text


def records(data: Any, path: Path = ()) -> Iterator[tuple[Path, dict[str, Any]]]:
    """Every JSON object of the draft with its path, parents before children."""
    if isinstance(data, dict):
        yield path, data
        for key, value in data.items():
            if key not in ("unavailable", "sources"):
                yield from records(value, (*path, key))
    elif isinstance(data, list):
        for position, item in enumerate(data):
            yield from records(item, (*path, position))
