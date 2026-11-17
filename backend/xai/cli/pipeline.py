"""``python -m xai.cli.pipeline run --analysis <id>``: the report pipeline ran by command line.

WatchOut starts it also when an analysis is done; it can be run by hand to recover an
analysis left without reports. It uses the rules' default parameters and logs
to ``<out>/<analysis_id>/pipeline.log``
"""

import argparse
import logging
import sys
from collections.abc import Sequence

from xai.adapters.report_resources import load_report_config
from xai.cli.common import (
    EXIT_OK,
    add_database_options,
    add_out_option,
    logging_to,
    open_stage,
    run_command,
)
from xai.cli.reports import configured_llm, report_writer
from xai.k1_harvester.batch import AnalysisHarvester
from xai.k1_harvester.output import AnalysisFolder
from xai.k5_report1.stage import K5Stage
from xai.pipeline.runner import REPORT_STAGES, ReportPipeline, ReportStage
from xai.reporting.catalogue import ReportConfig
from xai.reporting.ports import LanguageModel, LlmUnavailable

log = logging.getLogger("xai.cli.pipeline")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m xai.cli.pipeline", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="run the report pipeline on a finished analysis")
    run.add_argument("--analysis", required=True, help="Analyses.ID")
    run.add_argument("--force", action="store_true", help="run again on an analysis that has index.json")
    add_database_options(run)
    add_out_option(run)
    return parser


def report_stages(
    config: ReportConfig | None = None, llm: LanguageModel | None = None
) -> tuple[ReportStage, ...]:
    """K2 and K4, then K5 when an LLM is configured (S9)."""
    if config is None:
        config = load_report_config()
    try:
        model = llm if llm is not None else configured_llm(config)
    except LlmUnavailable as error:
        log.warning("%s: the pipeline stops at K4 and writes no report", error)
        return REPORT_STAGES
    return (*REPORT_STAGES, K5Stage(report_writer(1, config, model)))


def run(args: argparse.Namespace) -> int:
    stages = report_stages()
    with open_stage(args) as stage:
        pipeline = ReportPipeline(AnalysisHarvester(stage), stages)
        result = pipeline.run(args.analysis, args.out, force=args.force, params="defaults")
    if result.status == "done":
        print(result.folder.index_path)
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    with logging_to(AnalysisFolder(args.out, args.analysis).log_path):
        return run_command(run, args)


if __name__ == "__main__":
    sys.exit(main())
