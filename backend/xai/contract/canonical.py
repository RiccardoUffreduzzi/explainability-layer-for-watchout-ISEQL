"""Canonical JSON: the single text form used for IDs, row references and hashing."""

import json
from typing import Any


def canonical_json(value: Any) -> str:
    """Serialize ``value`` deterministically.

    Keys sorted, no whitespace, non-ASCII characters kept as they are, floats
    written with Python's ``repr`` (the ``json`` module default).
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
