"""The files of a report: ``<ev_id>.json``, ``<ev_id>.md`` and ``<ev_id>.trace.json``, side by side.

The JSON file is written last: a report is there when its JSON file is. A report that cannot
be written leaves only ``<ev_id>.failed.trace.json``, with the calls made to the LLM.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from xai.contract.report import dump_report, dump_trace, load_report
from xai.reporting.failure import ReportFailure
from xai.reporting.llm_input import read_plan, read_source
from xai.reporting.writer import ReportWriter, WrittenReport

WriteStatus = Literal["written", "current"]


@dataclass(frozen=True)
class ReportFiles:
    json: Path
    markdown: Path
    trace: Path
    failed_trace: Path

    @classmethod
    def of(cls, target: Path) -> "ReportFiles":
        """The files of the report whose JSON file is ``target`` (``<ev_id>.json``)."""
        stem = target.name.removesuffix(".json")
        return cls(
            json=target,
            markdown=target.with_name(f"{stem}.md"),
            trace=target.with_name(f"{stem}.trace.json"),
            failed_trace=target.with_name(f"{stem}.failed.trace.json"),
        )

    def all(self) -> tuple[Path, Path, Path]:
        return (self.trace, self.markdown, self.json)


def write_report(
    writer: ReportWriter, plan_path: Path, source_path: Path, target: Path, *, force: bool = False
) -> WriteStatus:
    """Writes the report of the plan in ``plan_path``.

    When it cannot: ``ReportFailure``, and only the failed trace if the LLM was called.
    """
    files = ReportFiles.of(target)
    plan = read_plan(plan_path)
    current = _is_current(files, writer, plan.plan_meta.plan_hash)
    if current and not force:
        return "current"
    if not current:
        for path in files.all():
            path.unlink(missing_ok=True)
    files.failed_trace.unlink(missing_ok=True)
    document = read_source(source_path)
    try:
        written = writer.write(plan, document)
    except ReportFailure as failure:
        if failure.trace is not None:
            _replace(files.failed_trace, dump_trace(failure.trace))
        raise
    _save(written, files)
    return "written"


def _save(written: WrittenReport, files: ReportFiles) -> None:
    _replace(files.trace, dump_trace(written.trace))
    _replace(files.markdown, written.markdown)
    _replace(files.json, dump_report(written.report))


def _is_current(files: ReportFiles, writer: ReportWriter, plan_hash: str) -> bool:
    if not (files.json.is_file() and files.markdown.is_file()):
        return False
    try:
        meta = load_report(files.json.read_text(encoding="utf-8")).report_meta
    except (ValidationError, OSError):
        return False
    return (
        meta.plan_hash == plan_hash
        and meta.prompt_version == writer.prompt_version
        and meta.sentences_version == writer.sentences_version
        and meta.llm == writer.llm.settings
    )


def _replace(target: Path, text: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temporary, target)
