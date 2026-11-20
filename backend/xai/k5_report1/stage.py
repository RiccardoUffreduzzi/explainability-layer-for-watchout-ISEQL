"""the stage that ``ReportPipeline`` runs on each draft after K4.

It is the only module of K5 that knows where the files are. For the draft at
``<analysis_id>/<event type>/<ev_id>.json`` it reads K4's plan and K2's source of truth and
writes Report 1 in ``<analysis_id>/k5/<event type>/<ev_id>.json`` (with ``.md``,
``.trace.json`` and the key frame ``.jpg``). If no report can be written it raises
``ReportFailure`` and writes only ``<ev_id>.failed.trace.json``, when the LLM was called.
"""

import logging
from pathlib import Path

from xai.contract.model import ContractDraft
from xai.pipeline.paths import K4_FOLDER, k2_path, k4_path, k5_path
from xai.reporting.files import write_report
from xai.reporting.writer import ReportWriter

log = logging.getLogger("xai.k5")


class K5Stage:
    """Satisfies ``xai.pipeline.runner.ReportStage``."""

    name = "k5"
    reads_from = K4_FOLDER

    def __init__(self, writer: ReportWriter, *, force: bool = False) -> None:
        self._writer = writer
        self._force = force

    def process(self, draft: ContractDraft, draft_path: Path) -> None:
        # K5 does not read the draft: the plan and the source of truth are enough.
        target = k5_path(draft_path)
        status = write_report(
            self._writer, k4_path(draft_path), k2_path(draft_path), target, force=self._force
        )
        if status == "current":
            log.info("%s is up to date: the LLM was not called", target)
