"""Where the batch writes: ``<out>/<analysis_id>/``.

- ``<event>/<event_id>.json``: one draft per row (keys sorted, indented);
- ``index.json``: the outcome of every rule and row, written last: its presence
  marks the analysis as done;
- ``.lock``: held while a run works on the analysis, so two runs never write the
  same folder;
- ``pipeline.log``: the pipeline's log (written by the CLI).

Every file is written to a temporary name and then renamed, so a reader never
sees half a file.
"""

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from xai.contract.model import CONTRACT_VERSION
from xai.contract.serialization import dump_draft
from xai.k1_harvester.batch import AnalysisOutcome, RuleOutcome
from xai.k1_harvester.result import HarvestResult

INDEX_FILE = "index.json"
LOCK_FILE = ".lock"
LOG_FILE = "pipeline.log"
DRAFT_INDENT = 2


class FolderLocked(Exception):
    """Another run holds the lock of the analysis."""


class AnalysisFolder:
    def __init__(self, root: Path, analysis_id: str) -> None:
        if not analysis_id or analysis_id in (".", "..") or any(c in analysis_id for c in "/\\"):
            raise ValueError(f"analysis id {analysis_id!r} cannot name a folder")
        self.path = root / analysis_id
        self.index_path = self.path / INDEX_FILE
        self.lock_path = self.path / LOCK_FILE
        self.log_path = self.path / LOG_FILE

    def draft_path(self, event_type: str, ev_id: str) -> Path:
        return self.path / event_type / f"{ev_id}.json"

    def is_done(self) -> bool:
        return self.index_path.is_file()

    @contextmanager
    def lock(self) -> Iterator[None]:
        """Hold ``.lock`` for the duration of the block; ``FolderLocked`` if another run holds it.

        A lock left by a run that was killed stays: delete the file once no run is active.
        """
        self.path.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise FolderLocked(f"{self.lock_path} exists: another run is working on this analysis") from exc
        try:
            os.write(fd, f"{os.getpid()}\n".encode())
            os.close(fd)
            yield
        finally:
            self.lock_path.unlink(missing_ok=True)

    def clear(self) -> None:
        """Remove what an earlier run wrote: ``index.json`` first, then the drafts."""
        self.index_path.unlink(missing_ok=True)
        if not self.path.is_dir():
            return
        for folder in sorted(p for p in self.path.iterdir() if p.is_dir()):
            for draft in folder.glob("ev_*.json"):
                draft.unlink()
            if not any(folder.iterdir()):
                folder.rmdir()

    def write(self, outcome: AnalysisOutcome) -> None:
        """One file per draft, then ``index.json``."""
        for _, result in outcome.drafts():
            assert result.draft is not None
            path = self.draft_path(result.draft.event.label, result.event_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            _write_text(path, dump_draft(result.draft, indent=DRAFT_INDENT) + "\n")
        _write_text(self.index_path, _json(index_data(outcome)) + "\n")


def index_data(outcome: AnalysisOutcome) -> dict[str, Any]:
    """``index.json``: the outcome of each rule and each row, in output order."""
    events = [_rule_entry(rule) for rule in outcome.rules]
    results = [r for rule in outcome.rules for r in rule.results]
    return {
        "analysis_id": outcome.analysis_id,
        "condition": outcome.condition,
        "params": outcome.params_mode,
        "params_origin": outcome.params_origin,
        "contract_version": CONTRACT_VERSION,
        "extracted_at": outcome.extracted_at.isoformat().replace("+00:00", "Z"),
        "events": events,
        "summary": {
            "events": len(outcome.rules),
            "events_failed": sum(1 for e in events if e["status"] != "ok"),
            "rows": len(results),
            "drafts": sum(1 for r in results if r.draft is not None),
            "rows_failed": sum(1 for r in results if r.failure is not None or r.engine_error is not None),
            "duplicates": sum(1 for r in results if r.duplicate_of is not None),
        },
    }


def _rule_entry(rule: RuleOutcome) -> dict[str, Any]:
    status = "ok"
    if rule.failure is not None:
        status = "failed"
    elif rule.engine_error is not None:
        status = "engine_error"
    return {
        "event_type": rule.event_type,
        "rule_ref": rule.rule_ref,
        "status": status,
        "rows_returned": rule.rows_returned,
        "failure": rule.failure.to_data() if rule.failure is not None else None,
        "engine_error": rule.engine_error,
        "rows": [_row_entry(rule, r) for r in rule.results],
    }


def _row_entry(rule: RuleOutcome, result: HarvestResult) -> dict[str, Any]:
    if result.draft is not None:
        status = "draft"
    elif result.duplicate_of is not None:
        status = "duplicate"
    elif result.failure is not None:
        status = "failed"
    else:
        status = "engine_error"
    return {
        "index": result.index,
        "event_id": result.event_id,
        "status": status,
        "draft": f"{rule.event_type}/{result.event_id}.json" if result.draft is not None else None,
        "duplicate_of": result.duplicate_of,
        "failure": result.failure.to_data() if result.failure is not None else None,
        "engine_error": result.engine_error,
        "row": dict(result.row),
    }


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def _write_text(path: Path, text: str) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temporary, path)
