"""``harvest_report``: request, row match, checks, missing fields and notes."""

from collections.abc import Sequence
from typing import Any

from xai.contract.model import CheckResult, MissingField, Note, RequestEcho, Violation
from xai.contract.reasons import CheckName, NoteCode, Reason
from xai.k1_harvester.checks.paths import Path, pattern, records
from xai.k1_harvester.context import HarvestContext

SECTIONS = ("contract_meta", "event", "rule", "entities", "intervals", "glossary")
"""Order of ``missing_fields``: the sections, then the top-level fields (``actions``)."""

NOTE_ORDER = list(NoteCode)


def request_echo(ctx: HarvestContext) -> RequestEcho:
    return RequestEcho(
        analysis_id=ctx.request.analysis_id,
        event_type=ctx.request.event_type,
        condition=ctx.condition,
        params=ctx.request.params,
        row=dict(ctx.request.row),
    )


def check_results(violations: Sequence[Violation]) -> list[CheckResult]:
    results = []
    for name in CheckName:
        own = [v for v in violations if v.check == name]
        results.append(CheckResult(name=name, passed=not own, violations=own))
    return results


def missing_fields(data: dict[str, Any]) -> list[MissingField]:
    """Every reason of the draft by path: list items as ``[*]``, glossary entries by kind."""
    found: dict[tuple[str, str], MissingField] = {}
    for section in SECTIONS:
        for path, record in records(data.get(section), (section,)):
            for dotted, unavailable in (record.get("unavailable") or {}).items():
                prefix = _record_path(path, data)
                key = (f"{prefix}.{dotted}" if prefix else dotted, unavailable["reason"])
                found.setdefault(key, MissingField(path=key[0], reason=Reason(key[1])))
    for dotted, unavailable in (data.get("unavailable") or {}).items():
        key = (dotted, unavailable["reason"])
        found.setdefault(key, MissingField(path=dotted, reason=Reason(key[1])))
    return list(found.values())


def _record_path(path: Path, data: dict[str, Any]) -> str:
    if len(path) >= 2 and path[0] == "glossary" and isinstance(path[1], int):
        kind = data["glossary"][path[1]]["kind"]
        rest = pattern(path[2:])
        return f"glossary[kind={kind}].{rest}" if rest else f"glossary[kind={kind}]"
    return pattern(path)


def sorted_notes(notes: Sequence[Note]) -> list[Note]:
    """Notes in the order of the catalog, each text once."""
    unique = {(n.code, n.detail): n for n in notes}
    return sorted(unique.values(), key=lambda n: NOTE_ORDER.index(n.code))
