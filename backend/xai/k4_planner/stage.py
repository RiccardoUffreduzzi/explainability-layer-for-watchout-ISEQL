"""``K4Stage``: the stage that ``ReportPipeline`` runs on each draft after K2.

It is the only module of K4 that knows where the files are. For the draft at
``<analysis_id>/<event type>/<ev_id>.json`` it reads K2's source of truth in
``<analysis_id>/k2/<event type>/<ev_id>.json`` and writes the plan in
``<analysis_id>/k4/<event type>/<ev_id>.json``. If the source cannot be planned it raises
``PlanFailure`` and writes nothing: the plan is whole or absent (UC-K4-11).
"""

import os
from pathlib import Path

from xai.contract.model import ContractDraft
from xai.contract.plan import ExplanationPlan, dump_plan
from xai.k4_planner.planner import ExplanationPlanner, read_source
from xai.pipeline.paths import k2_path, k4_path

PLAN_INDENT = 2


def write_plan(plan: ExplanationPlan, target: Path) -> None:
    """Writes the plan in ``target``, whole or not at all (a temporary file, then a rename)."""
    text = dump_plan(plan, indent=PLAN_INDENT) + "\n"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, target)


class K4Stage:
    """Satisfies ``xai.pipeline.runner.ReportStage``."""

    name = "k4"

    def __init__(self, planner: ExplanationPlanner | None = None) -> None:
        self._planner = planner if planner is not None else ExplanationPlanner()

    def process(self, draft: ContractDraft, draft_path: Path) -> None:
        # K4 does not read the draft: K2's source of truth contains it.
        document = read_source(k2_path(draft_path))
        write_plan(self._planner.plan(document), k4_path(draft_path))
