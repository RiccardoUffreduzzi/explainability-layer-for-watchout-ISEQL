"""``ReportPipeline``: what WatchOut starts when an analysis is done.

It holds the analysis's lock, skips an analysis that already has ``index.json``
(unless ``force``).
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from xai.contract.model import Condition, ContractDraft
from xai.k1_harvester.batch import AnalysisHarvester, AnalysisOutcome
from xai.k1_harvester.output import AnalysisFolder, FolderLocked
from xai.k1_harvester.request import ParamsMode
from xai.k2.stage import K2Stage
from xai.k4_planner.stage import K4Stage

log = logging.getLogger("xai.pipeline")


class ReportStage(Protocol):
    """A stage after K1: it reads one draft and writes its own outputs.

    A stage may declare ``reads_from``, the name of the stage whose files it reads (``"k1"`` for
    the draft): it is skipped only when that stage failed or was skipped. A stage that declares
    nothing reads from every stage before it.
    """

    name: str

    def process(self, draft: ContractDraft, draft_path: Path) -> None: ...


REPORT_STAGES: tuple[ReportStage, ...] = (K2Stage(), K4Stage())
"""The stages after K1, in the order they run on each draft."""

RunStatus = Literal["done", "skipped", "locked"]


@dataclass(frozen=True)
class PipelineRun:
    status: RunStatus
    folder: AnalysisFolder
    outcome: AnalysisOutcome | None = None


class ReportPipeline:
    def __init__(self, harvester: AnalysisHarvester, stages: Sequence[ReportStage] = REPORT_STAGES) -> None:
        self.harvester = harvester
        self.stages = tuple(stages)

    def run(
        self,
        analysis_id: str,
        out_root: Path,
        *,
        force: bool = False,
        params: ParamsMode = "defaults",
        condition: Condition | None = None,
    ) -> PipelineRun:
        # Run on one analysis; ``HarvestFailure`` when the analysis itself cannot be read.
        folder = AnalysisFolder(out_root, analysis_id)
        try:
            with folder.lock():
                if folder.is_done() and not force:
                    log.info(
                        "%s already has %s: nothing to do (--force runs it again)",
                        analysis_id,
                        folder.index_path,
                    )
                    return PipelineRun("skipped", folder)
                log.info("K1 on %s (params: %s)", analysis_id, params)
                outcome = self.harvester.harvest(analysis_id, condition, params)
                folder.clear()
                folder.write(outcome)
                _log_outcome(outcome, folder)
                self._later_stages(outcome, folder)
                return PipelineRun("done", folder, outcome)
        except FolderLocked as exc:
            log.warning("%s", exc)
            return PipelineRun("locked", folder)

    def _later_stages(self, outcome: AnalysisOutcome, folder: AnalysisFolder) -> None:
        """Each stage on each draft, in order.

        A stage that fails on a draft stops, for that draft only, the stages that read its
        output: K6 does not read K5, so a failed Report 1 does not stop Report 2.
        """
        for _, result in outcome.drafts():
            assert result.draft is not None
            path = folder.draft_path(result.draft.event.label, result.event_id)
            stopped: list[str] = []
            for stage in self.stages:
                reads_from: str | None = getattr(stage, "reads_from", None)
                blocked = stopped if reads_from is None else [s for s in stopped if s == reads_from]
                if blocked:
                    log.warning(
                        "stage %s skipped on %s: %s did not write its files", stage.name, path, blocked[0]
                    )
                    stopped.append(stage.name)
                    continue
                try:
                    stage.process(result.draft, path)
                except Exception:
                    log.exception("stage %s failed on %s", stage.name, path)
                    stopped.append(stage.name)


def _log_outcome(outcome: AnalysisOutcome, folder: AnalysisFolder) -> None:
    for rule in outcome.rules:
        if rule.failure is not None:
            log.warning("%s: %s", rule.rule_ref, rule.failure)
        elif rule.engine_error is not None:
            log.warning("%s: WatchOut's engine failed: %s", rule.rule_ref, rule.engine_error)
        else:
            drafts = sum(1 for r in rule.results if r.draft is not None)
            log.info("%s: %d row(s), %d draft(s)", rule.rule_ref, rule.rows_returned or 0, drafts)
        for result in rule.results:
            if result.failure is not None:
                log.warning("%s row %d: %s", rule.rule_ref, result.index, result.failure)
            elif result.engine_error is not None:
                log.warning(
                    "%s row %d: WatchOut's engine failed: %s",
                    rule.rule_ref,
                    result.index,
                    result.engine_error,
                )
    log.info("wrote %s", folder.index_path)
