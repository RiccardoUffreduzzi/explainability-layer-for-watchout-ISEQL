"""``ReportPipeline``: what WatchOut starts when an analysis is done.

It holds the analysis's lock, skips an analysis that already has ``index.json``
(unless ``force``), runs K1 on every row of every event and then hands each draft to
the later stages (K2, K4, K5/K6, K7) in order.
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

log = logging.getLogger("xai.pipeline")


class ReportStage(Protocol):
    """A stage after K1: it reads one draft and writes its own outputs."""

    name: str

    def process(self, draft: ContractDraft, draft_path: Path) -> None: ...


REPORT_STAGES: tuple[ReportStage, ...] = ()
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

        A stage that fails on a draft stops the later stages for that draft only: they
        read its output.
        """
        for _, result in outcome.drafts():
            assert result.draft is not None
            path = folder.draft_path(result.draft.event.label, result.event_id)
            for stage in self.stages:
                try:
                    stage.process(result.draft, path)
                except Exception:
                    log.exception("stage %s failed on %s", stage.name, path)
                    break


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
