"""K4 from the command line: the plan of a source of truth, or of all those of an analysis.

Run from ``backend``::

    PYTHONPATH=src python -m xai.cli.k4 plan --source <file of K2> [--out <folder>]
    PYTHONPATH=src python -m xai.cli.k4 plan-all --analysis <id> [--out <folder>]

``plan`` writes ``<out>/<analysis_id>/k4/<event type>/<ev_id>.json``. ``plan-all`` plans every
file in ``<out>/<id>/k2/`` in a fixed order (event type, then ``ev_id``) and writes the plans in
``<out>/<id>/k4/``; a source that cannot be planned does not stop the others.

Exit code: 0 on success, 1 on a failure outside K4's input, 2 when a source of truth cannot be
planned (missing, invalid, hash that does not match, checks of K1 not passed).
"""

import argparse
import json
import logging
import sys
from collections.abc import Callable
from pathlib import Path

from xai.cli.common import EXIT_INFRASTRUCTURE, EXIT_INPUT, EXIT_OK, add_out_option, logging_to
from xai.k1_harvester.output import AnalysisFolder
from xai.k4_planner.planner import ExplanationPlanner, PlanFailure, read_source
from xai.k4_planner.stage import write_plan
from xai.pipeline.paths import K2_FOLDER, k4_path, k4_path_of_source

log = logging.getLogger("xai.cli.k4")


def _plan(args: argparse.Namespace) -> int:
    document = read_source(args.source)
    folder = AnalysisFolder(args.out, document.contract_meta.analysis_id)
    target = k4_path(folder.draft_path(document.event.label, document.event.event_id))
    write_plan(ExplanationPlanner().plan(document), target)
    print(target)
    return EXIT_OK


def _plan_all(args: argparse.Namespace) -> int:
    folder = AnalysisFolder(args.out, args.analysis)
    sources = sorted((folder.path / K2_FOLDER).glob("*/*.json"), key=lambda p: (p.parent.name, p.name))
    if not sources:
        raise PlanFailure("SOURCE_NOT_FOUND", f"no source of truth in {folder.path / K2_FOLDER}")
    planner = ExplanationPlanner()
    failed = 0
    for source in sources:
        try:
            target = k4_path_of_source(source)
            write_plan(planner.plan(read_source(source)), target)
            print(target)
        except PlanFailure as failure:
            failed += 1
            _report(failure)
    return EXIT_INPUT if failed else EXIT_OK


def _report(failure: PlanFailure) -> None:
    log.error("%s", failure)
    print(json.dumps(failure.to_data(), indent=2, ensure_ascii=False), file=sys.stderr)


def _run(command: Callable[[argparse.Namespace], int], args: argparse.Namespace) -> int:
    try:
        return command(args)
    except PlanFailure as failure:
        _report(failure)
        return EXIT_INPUT
    except Exception:
        log.exception("K4 stopped on an unexpected error")
        return EXIT_INFRASTRUCTURE


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="xai.cli.k4", description=__doc__.splitlines()[0] if __doc__ else None
    )
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan", help="plan one source of truth")
    plan.add_argument("--source", type=Path, required=True, help="the file of K2")
    add_out_option(plan)
    plan_all = commands.add_parser("plan-all", help="plan every source of truth of an analysis")
    plan_all.add_argument("--analysis", required=True, help="the analysis ID")
    add_out_option(plan_all)
    return parser


COMMANDS: dict[str, Callable[[argparse.Namespace], int]] = {"plan": _plan, "plan-all": _plan_all}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    with logging_to():
        return _run(COMMANDS[args.command], args)


if __name__ == "__main__":
    sys.exit(main())
