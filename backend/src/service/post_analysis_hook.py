"""End-of-analysis hook: start the command configured in ``post_analysis.command``.

WatchOut starts the command for the reports as a separate process when an
analysis is done.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from utils.api_logger import get_logger

log = get_logger(__name__)

BACKEND_DIR = Path(__file__).resolve().parents[2]
SRC_DIR = BACKEND_DIR / "src"


def notify_analysis_done(analysis_id: str, cfg) -> None:
    """Start the configured post-analysis command

    ``{python}`` in the command is this interpreter, ``{analysis_id}`` the analysis.
    """
    try:
        command = (cfg.get("post_analysis") or {}).get("command") or []
        if not command:
            return  # hook disabled
        args = [str(a).format(python=sys.executable, analysis_id=analysis_id) for a in command]
        subprocess.Popen(
            args,
            cwd=BACKEND_DIR,
            env=_env_with_src_on_path(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **_detached(),
        )
        log.info("post-analysis command started for %s: %s", analysis_id, " ".join(args))
    except Exception as exc:
        log.warning("post-analysis command not started for %s: %s", analysis_id, exc)


def _env_with_src_on_path() -> dict[str, str]:
    env = dict(os.environ)
    paths = [str(SRC_DIR)] + [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p]
    env["PYTHONPATH"] = os.pathsep.join(paths)
    return env


def _detached() -> dict:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}
