"""Completeness: every null field has a reason, every reason a null field.

A field is null for a reason when an ``unavailable`` map of its record, or of an
enclosing record within the same list item, has the field's dotted path or a
prefix of it. A few fields are null by design and need no reason.
"""

from typing import Any

from xai.contract.model import Violation
from xai.contract.reasons import CheckName
from xai.k1_harvester.checks.paths import Path, pattern, records, render

NULL_BY_DESIGN = (
    "rule.constraints[*].parent",  # the root of the rule
    "rule.constraints[*].branch",  # a set operation combines branches
    "rule.constraints[*].payload.params[*].raw",  # a literal parameter has no key
    "harvest_report.request.row.*",  # a null column of the detection row
)


def check_completeness(data: dict[str, Any]) -> list[Violation]:
    violations = []
    for path, record in records(data):
        for key, value in record.items():
            field = (*path, key)
            if value is None and not _by_design(field) and not _covered(data, field):
                violations.append(_violation(field, "null without a reason in an unavailable map"))
        for dotted in record.get("unavailable") or {}:
            target = _resolve(record, dotted.split("."))
            if target is _MISSING:
                violations.append(
                    _violation((*path, "unavailable", dotted), "reason for a field the record does not have")
                )
            elif not _has_null(target):
                violations.append(
                    _violation((*path, "unavailable", dotted), "reason for a field that has a value")
                )
    return violations


def _by_design(field: Path) -> bool:
    """``[*]`` stands for any list position; a final ``.*`` for any key."""
    text = pattern(field)
    return any(text.startswith(p[:-1]) if p.endswith(".*") else text == p for p in NULL_BY_DESIGN)


def _covered(data: dict[str, Any], field: Path) -> bool:
    """A reason in the record's map or in an enclosing record's, without crossing a list."""
    for cut in range(len(field) - 1, -1, -1):
        relative = field[cut:]
        if any(isinstance(p, int) for p in relative):
            return False
        holder = _resolve(data, list(field[:cut]))
        if not isinstance(holder, dict):
            continue
        reasons = holder.get("unavailable") or {}
        dotted = [str(p) for p in relative]
        if any(".".join(dotted[:n]) in reasons for n in range(1, len(dotted) + 1)):
            return True
    return False


_MISSING = object()


def _resolve(data: Any, path: list[Any]) -> Any:
    for part in path:
        in_object = isinstance(data, dict) and isinstance(part, str) and part in data
        in_list = isinstance(data, list) and isinstance(part, int) and part < len(data)
        if not (in_object or in_list):
            return _MISSING
        data = data[part]
    return data


def _has_null(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, dict):
        return any(_has_null(v) for v in value.values())
    if isinstance(value, list):
        return any(_has_null(v) for v in value)
    return False


def _violation(path: Path, detail: str) -> Violation:
    return Violation(check=CheckName.COMPLETENESS, element_path=render(path), detail=detail)
