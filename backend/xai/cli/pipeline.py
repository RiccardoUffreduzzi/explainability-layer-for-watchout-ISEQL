"""``python -m xai.cli.pipeline run --analysis <id>``: the report pipeline.

WatchOut starts it when an analysis is done; it can be run by hand to recover an
analysis left without reports. It uses the rules' default parameters and logs
to ``<out>/<analysis_id>/pipeline.log``.
"""

import argparse
import sys
from collections.abc import Sequence

from xai.cli.common import (
    EXIT_OK,
    add_database_options,
    add_out_option,
    logging_to,
    open_stage,
    run_command,
)
from xai.k1_harvester.batch import AnalysisHarvester
from xai.k1_harvester.output import AnalysisFolder
from xai.pipeline.runner import ReportPipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m xai.cli.pipeline", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="run the report pipeline on a finished analysis")
    run.add_argument("--analysis", required=True, help="Analyses.ID")
    run.add_argument("--force", action="store_true", help="run again on an analysis that has index.json")
    add_database_options(run)
    add_out_option(run)
    return parser


def run(args: argparse.Namespace) -> int:
    with open_stage(args) as stage:
        pipeline = ReportPipeline(AnalysisHarvester(stage))
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
