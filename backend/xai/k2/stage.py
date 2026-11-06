"""``K2Stage``: the stage that ``ReportPipeline`` runs on each draft after K1.

K1's file is never touched. The source of truth is written in a folder of its own::

    <analysis_id>/<event type>/<ev_id>.json        K1's draft
    <analysis_id>/k2/<event type>/<ev_id>.json     K2's source of truth
"""

import os
from pathlib import Path

from xai.contract.model import ContractDraft
from xai.contract.source_of_truth import dump_source_of_truth
from xai.k2.source_of_truth import build_source_of_truth


def k2_path(draft_path: Path) -> Path:
    """Where the source of truth of the draft at ``draft_path`` is written."""
    event_dir = draft_path.parent
    return event_dir.parent / "k2" / event_dir.name / draft_path.name


class K2Stage:
    """Satisfies ``xai.pipeline.runner.ReportStage``."""

    name = "k2"

    def process(self, draft: ContractDraft, draft_path: Path) -> None:
        text = dump_source_of_truth(build_source_of_truth(draft), indent=2) + "\n"
        target = k2_path(draft_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".tmp")
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, target)
