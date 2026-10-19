"""K1 alone: ``harvest-all`` (every row of an analysis) and ``harvest`` (one row).

By hand the parameters are, by default, the ones the GUI saved when there are any
(``--params auto``), so a row copied from the GUI is explained with the parameters that
produced it.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from typing import Any, cast

from xai.cli.common import (
    EXIT_INPUT,
    EXIT_OK,
    add_database_options,
    add_out_option,
    logging_to,
    open_stage,
    run_command,
)
from xai.contract.model import Condition
from xai.contract.serialization import dump_draft
from xai.k1_harvester.batch import AnalysisHarvester
from xai.k1_harvester.output import DRAFT_INDENT
from xai.k1_harvester.request import HarvestRequest, ParamsMode
from xai.pipeline.runner import ReportPipeline

PARAMS_MODES = ("auto", "saved", "defaults")
CONDITIONS = ("A", "B", "C")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m xai.cli.k1", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    every = commands.add_parser("harvest-all", help="a draft for every row of every event of an analysis")
    _add_common(every)
    every.add_argument("--force", action="store_true", help="run again on an analysis that has index.json")
    add_out_option(every)

    one = commands.add_parser("harvest", help="the draft of one row")
    _add_common(one)
    one.add_argument("--event", required=True, help="event type, e.g. handoff")
    one.add_argument("--row", required=True, help="the row as JSON, as the engine or the GUI gives it")
    one.add_argument("--output", type=argparse.FileType("w", encoding="utf-8"), default=None)
    return parser


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--analysis", required=True, help="Analyses.ID")
    parser.add_argument("--condition", choices=CONDITIONS, default=None, help="default: the analysis's")
    parser.add_argument("--params", choices=PARAMS_MODES, default="auto")
    add_database_options(parser)


def harvest_all(args: argparse.Namespace) -> int:
    with open_stage(args) as stage:
        result = ReportPipeline(AnalysisHarvester(stage), stages=()).run(
            args.analysis,
            args.out,
            force=args.force,
            params=cast(ParamsMode, args.params),
            condition=cast(Condition | None, args.condition),
        )
    if result.status == "done":
        print(result.folder.index_path)
    return EXIT_OK


def harvest(args: argparse.Namespace) -> int:
    row = _row(args.row)
    if row is None:
        print(f"--row is not a JSON object: {args.row}", file=sys.stderr)
        return EXIT_INPUT
    request = HarvestRequest(
        analysis_id=args.analysis,
        event_type=args.event,
        row=row,
        condition=cast(Condition | None, args.condition),
        params=cast(ParamsMode, args.params),
    )
    with open_stage(args) as stage:
        draft = stage.harvest(request)
    text = dump_draft(draft, indent=DRAFT_INDENT) + "\n"
    if args.output is not None:
        with args.output:
            args.output.write(text)
    else:
        sys.stdout.write(text)
    return EXIT_OK


# test if a row is a JSON object


def _row(text: str) -> dict[str, Any] | None:
    try:
        row = json.loads(text)
    except json.JSONDecodeError:
        return None
    return row if isinstance(row, dict) else None


COMMANDS = {"harvest-all": harvest_all, "harvest": harvest}


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    with logging_to():
        return run_command(COMMANDS[args.command], args)


if __name__ == "__main__":
    sys.exit(main())
