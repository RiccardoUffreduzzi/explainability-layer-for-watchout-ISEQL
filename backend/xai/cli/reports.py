"""The reports from the command line
Run from ``backend``, with the key of the provider in the environment (``GOOGLE_API_KEY`` for gemini):

    PYTHONPATH=src python -m xai.cli.reports write --plan <file of K4> [--report 1] [--force]
    PYTHONPATH=src python -m xai.cli.reports write-all --analysis <id> [--out <folder>] [--report 1] [--force]

``write`` reads the plan and the source of truth beside it and writes
``<id>/k5/<event type>/<ev_id>.json``, ``.md`` and ``.trace.json``. ``write-all`` does
it for every plan of ``<out>/<id>/k4/`` in a fixed order.
A report already written for the same plan, prompt and model is kept (``--force`` writes
it again). ``--replay <folder>`` answers with the recorded answers of the traces in the folder,
without network. ``--model <id>`` uses another model of the same provider, to compare models on
the same plans; ``--provider <name> --model <id>`` a model of another provider of WatchOut's
``VLMClient``, with the key in that provider's own environment variable.

Exit code: 0 = success, 1 = failure outside the reports' input, 2 = a plan or its source of
truth cannot be read or do not go together, 4 = the LLM is not configured, cannot be reached
or gave no text that could be rendered.
"""

import argparse
import json
import logging
import sys
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from xai.adapters.llm_replay import ReplayLanguageModel
from xai.adapters.report_resources import (
    load_prompt,
    load_report_config,
    load_sentences,
    load_value_labels,
)
from xai.adapters.watchout.llm import WatchOutLanguageModel
from xai.cli.common import EXIT_INFRASTRUCTURE, EXIT_INPUT, EXIT_OK, add_out_option, logging_to
from xai.k1_harvester.output import AnalysisFolder
from xai.k5_report1.profile import REPORT1
from xai.pipeline.paths import K2_FOLDER, K4_FOLDER, K5_FOLDER, sibling_path
from xai.reporting.catalogue import ReportConfig
from xai.reporting.failure import ReportFailure
from xai.reporting.files import write_report
from xai.reporting.ports import LanguageModel, LlmUnavailable
from xai.reporting.profile import ReportProfile
from xai.reporting.writer import ReportWriter

EXIT_NO_REPORT = 4
LLM_CODES = ("LLM_UNAVAILABLE", "TEXT_NOT_RENDERABLE")

PROFILES: dict[int, tuple[ReportProfile, str]] = {1: (REPORT1, K5_FOLDER)}
"""Report number -> its profile and the folder of its files."""

log = logging.getLogger("xai.cli.reports")


def configured_llm(config: ReportConfig) -> LanguageModel:
    """The LLM of the configuration; ``LlmUnavailable`` when there is none or it cannot be built."""
    if config.llm is None:
        raise LlmUnavailable("no LLM is configured (llm: null in report_config.yaml)")
    return WatchOutLanguageModel(config.llm)


def report_writer(number: int, config: ReportConfig, llm: LanguageModel) -> ReportWriter:
    profile, _ = PROFILES[number]
    return ReportWriter(
        profile,
        load_prompt(profile.name),
        load_sentences(profile.name),
        llm,
        load_value_labels(),
        max_attempts=config.max_attempts,
        time_format=config.time_format,
    )


def _writer(args: argparse.Namespace) -> ReportWriter:
    config = load_report_config()
    if config.llm is not None:
        chosen = replace(
            config.llm, provider=args.provider or config.llm.provider, model=args.model or config.llm.model
        )
        config = replace(config, llm=chosen)
    if args.replay is not None:
        llm: LanguageModel = ReplayLanguageModel.from_traces(sorted(args.replay.rglob("*.trace.json")))
    else:
        llm = configured_llm(config)
    return report_writer(args.report, config, llm)


def _write_one(writer: ReportWriter, number: int, plan_path: Path, force: bool) -> None:
    _, folder = PROFILES[number]
    target = sibling_path(plan_path, folder)
    status = write_report(writer, plan_path, sibling_path(plan_path, K2_FOLDER), target, force=force)
    print(target if status == "written" else f"{target} (up to date)")


def _write(args: argparse.Namespace) -> int:
    _write_one(_writer(args), args.report, args.plan, args.force)
    return EXIT_OK


def _write_all(args: argparse.Namespace) -> int:
    folder = AnalysisFolder(args.out, args.analysis)
    plans = sorted((folder.path / K4_FOLDER).glob("*/*.json"), key=lambda p: (p.parent.name, p.name))
    if not plans:
        raise ReportFailure("PLAN_NOT_FOUND", f"no plan in {folder.path / K4_FOLDER}")
    writer = _writer(args)
    codes = []
    for plan_path in plans:
        try:
            _write_one(writer, args.report, plan_path, args.force)
        except ReportFailure as failure:
            codes.append(failure.code)
            _report(failure)
    if not codes:
        return EXIT_OK
    return EXIT_NO_REPORT if all(code in LLM_CODES for code in codes) else EXIT_INPUT


def _report(failure: ReportFailure) -> None:
    log.error("%s", failure)
    print(json.dumps(failure.to_data(), indent=2, ensure_ascii=False), file=sys.stderr)


def _run(command: Callable[[argparse.Namespace], int], args: argparse.Namespace) -> int:
    try:
        return command(args)
    except LlmUnavailable as error:
        log.error("no report written: %s", error)
        return EXIT_NO_REPORT
    except ReportFailure as failure:
        _report(failure)
        return EXIT_NO_REPORT if failure.code in LLM_CODES else EXIT_INPUT
    except Exception:
        log.exception("the reports stopped on an unexpected error")
        return EXIT_INFRASTRUCTURE


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--report", type=int, choices=sorted(PROFILES), default=1, help="which report")
    parser.add_argument("--force", action="store_true", help="write the report even if it is up to date")
    parser.add_argument(
        "--replay", type=Path, default=None, help="answer with the traces in this folder, without network"
    )
    parser.add_argument(
        "--model", default=None, help="the LLM model, instead of the one of report_config.yaml"
    )
    parser.add_argument(
        "--provider",
        default=None,
        help="the LLM provider, instead of the one of report_config.yaml; needs --model",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="xai.cli.reports", description=__doc__.splitlines()[0] if __doc__ else None
    )
    commands = parser.add_subparsers(dest="command", required=True)
    write = commands.add_parser("write", help="write the report of one plan")
    write.add_argument("--plan", type=Path, required=True, help="the file of K4")
    _common(write)
    write_all = commands.add_parser("write-all", help="write the reports of every plan of an analysis")
    write_all.add_argument("--analysis", required=True, help="the analysis ID")
    add_out_option(write_all)
    _common(write_all)
    return parser


COMMANDS: dict[str, Callable[[argparse.Namespace], int]] = {"write": _write, "write-all": _write_all}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.provider is not None and args.model is None:
        parser.error("--provider needs --model: a model of that provider")
    with logging_to():
        return _run(COMMANDS[args.command], args)


if __name__ == "__main__":
    sys.exit(main())
