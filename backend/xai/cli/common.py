"""What the commands share: database options, wiring, logging and exit codes."""

import argparse
import json
import logging
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from xai.adapters.clock import SystemClock
from xai.adapters.resource_files import load_glossary, load_pipeline_constants
from xai.adapters.watchout.connection import default_db_path, open_read_only
from xai.adapters.watchout.reader import SqliteWatchOutReader
from xai.k1_harvester.ports import Clock
from xai.k1_harvester.result import HarvestFailure
from xai.k1_harvester.service import StageHarvester

EXIT_OK = 0
EXIT_INFRASTRUCTURE = 1
EXIT_INPUT = 2
EXIT_CHECKS = 3

DEFAULT_OUT = Path(__file__).resolve().parents[1] / "output"
"""``backend/xai/output``: a folder of ``xai``, never one of WatchOut's."""

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

log = logging.getLogger("xai.cli")


def add_database_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--db", type=Path, default=None, help="WatchOut's database (default: data.db_path of its config)"
    )
    parser.add_argument(
        "--config-db",
        type=Path,
        default=None,
        help="database to read AppConfig from, for ablation databases without it",
    )


def add_out_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--out", type=Path, default=DEFAULT_OUT, help=f"output folder (default: {DEFAULT_OUT})"
    )


@contextmanager
def open_stage(args: argparse.Namespace, clock: Clock | None = None) -> Iterator[StageHarvester]:
    """K1 over a read-only connection to the database the options name, closed on exit."""
    db = args.db if args.db is not None else default_db_path()
    conn = open_read_only(db, args.config_db)
    try:
        yield StageHarvester(
            SqliteWatchOutReader(conn), clock or SystemClock(), load_glossary(), load_pipeline_constants()
        )
    finally:
        conn.close()


@contextmanager
def logging_to(log_file: Path | None = None) -> Iterator[None]:
    """Send the ``xai`` logger to standard error and, when given, to ``log_file``.

    The handlers are removed and closed on exit, so the log file is not left open.
    """
    logger = logging.getLogger("xai")
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    formatter = logging.Formatter(LOG_FORMAT)
    for handler in handlers:
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    level = logger.level
    logger.setLevel(logging.INFO)
    try:
        yield
    finally:
        for handler in handlers:
            logger.removeHandler(handler)
            handler.close()
        logger.setLevel(level)


def failure_exit(failure: HarvestFailure) -> int:
    """Print the failure as JSON on standard error; its exit code."""
    print(json.dumps(failure.to_data(), ensure_ascii=False, indent=2), file=sys.stderr)
    return EXIT_INPUT if failure.stage == "input" else EXIT_CHECKS


def run_command(command: Callable[[argparse.Namespace], int], args: argparse.Namespace) -> int:
    """Run a command: K1's refusals become exit 2 or 3, anything else exit 1 with its trace in the log."""
    try:
        return command(args)
    except HarvestFailure as failure:
        log.error("%s", failure)
        return failure_exit(failure)
    except Exception:
        log.exception("infrastructure error")
        return EXIT_INFRASTRUCTURE
