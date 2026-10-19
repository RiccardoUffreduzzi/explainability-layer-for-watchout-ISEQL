"""Deterministic identifiers of the contract draft.

IDs are the only way the outline and the reports can cite a fact, so each one is
built from the record it names and is stable across runs on the same data.
"""

import hashlib
import re
from collections.abc import Mapping

from xai.contract.canonical import canonical_json

RowValue = int | float | str | None
"""A value of a detection row as WatchOut's engine returns it."""

EVENT_ID_PATTERN = r"^ev_[0-9a-f]{12}$"
INTERVAL_ID_PATTERN = r"^iv_[va][0-9]+$"
ENTITY_ID_PATTERN = r"^ent_[0-9]+$"
CONSTRAINT_ID_PATTERN = r"^c_[A-Za-z0-9_]+$"
TERM_ID_PATTERN = r"^g_[A-Za-z0-9_]+$"

_FIELD_SEPARATOR = "|"
_EVENT_HASH_LENGTH = 12
_NAME = re.compile(r"[A-Za-z0-9_]+")


def canonical_row(row: Mapping[str, RowValue]) -> str:
    # canonical text of a detection row, also used as its record_id
    return canonical_json(dict(row))


# id generators for the contract draft
def event_id(analysis_id: str, event_type: str, condition: str, row: Mapping[str, RowValue]) -> str:
    # ev_ + the first 12 hex digits of sha256(analysis | event | condition | row).
    for name, value in (("analysis_id", analysis_id), ("event_type", event_type), ("condition", condition)):
        if not value or _FIELD_SEPARATOR in value:
            raise ValueError(f"{name} must be non-empty and must not contain {_FIELD_SEPARATOR!r}: {value!r}")
    text = _FIELD_SEPARATOR.join((analysis_id, event_type, condition, canonical_row(row)))
    return "ev_" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:_EVENT_HASH_LENGTH]


def visual_interval_id(relation_id: int) -> str:
    # iv_v<RelationID>, from VisualPerInterval
    return f"iv_v{_non_negative(relation_id, 'relation_id')}"


def audio_interval_id(audio_interval_id: int) -> str:
    # iv_a<ID>, from ``AudioPerInterval
    return f"iv_a{_non_negative(audio_interval_id, 'audio_interval_id')}"


def entity_id(class_id: int) -> str:
    # ent_<ClassID>, from VisualParticipant or from the row.
    return f"ent_{_non_negative(class_id, 'class_id')}"


def projection_id(branch: str) -> str:
    # c_<branch>_proj: the projection of a branch of the rule.
    return f"c_{_branch(branch)}_proj"


def selection_id(branch: str, position: int) -> str:
    # c_<branch>_sel<i>: the i-th selection (interval) of a branch, from 1
    return f"c_{_branch(branch)}_sel{_positive(position)}"


def operator_id(branch: str, position: int) -> str:
    # c_<branch>_op<k>: the k-th temporal operator of a branch, from 1
    return f"c_{_branch(branch)}_op{_positive(position)}"


def cross_condition_id(branch: str, position: int) -> str:
    # c_<branch>_cc<j>: the j-th condition between variables of a branch, from 1
    return f"c_{_branch(branch)}_cc{_positive(position)}"


def set_operation_id(position: int) -> str:
    # c_set<n>: the n-th set operation between branches, from 1
    return f"c_set{_positive(position)}"


def term_id(kind: str, term: str) -> str:
    # g_<kind>_<term>, e.g. ``g_operator_Bef``.
    return f"g_{_name(kind, 'kind')}_{_name(term, 'term')}"



# auxilliary functions to validate the arguments
def _non_negative(value: int, name: str) -> int:
    if isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer: {value!r}")
    return value


def _positive(position: int) -> int:
    if isinstance(position, bool) or position < 1:
        raise ValueError(f"positions start from 1: {position!r}")
    return position


def _branch(branch: str) -> str:
    return _name(branch, "branch")


def _name(value: str, name: str) -> str:
    if not _NAME.fullmatch(value):
        raise ValueError(f"{name} may only contain ASCII letters, digits and '_': {value!r}")
    return value
