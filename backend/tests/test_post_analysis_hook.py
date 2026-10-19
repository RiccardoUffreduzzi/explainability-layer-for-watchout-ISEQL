"""Tests of the end-of-analysis hook (``service.post_analysis_hook``).

The hook starts the configured command without waiting and never raises;
``_run_pipeline`` calls it only for analyses that are done, after the GPU release.
"""
from __future__ import annotations

import ast
import logging
import subprocess
import sys
import time
from pathlib import Path

import pytest
from munch import munchify

import service.post_analysis_hook as hook

SERVICE_IMPL = Path(__file__).resolve().parents[1] / "src" / "service" / "impl" / "analysis_service_impl.py"


class _FakePopen:
    calls: list[dict] = []

    def __init__(self, args, **kwargs):
        _FakePopen.calls.append({"args": args, **kwargs})

    def wait(self, timeout=None):  # pragma: no cover - the hook must not call it
        raise AssertionError("the hook must not wait for the command")


@pytest.fixture
def fake_popen(monkeypatch):
    _FakePopen.calls = []
    monkeypatch.setattr(hook.subprocess, "Popen", _FakePopen)
    return _FakePopen


def _cfg(command):
    return munchify({"post_analysis": {"command": command}})


def test_starts_the_command_with_the_analysis_id(fake_popen):
    hook.notify_analysis_done("abc123", _cfg(["{python}", "-m", "xai.cli.pipeline", "run", "--analysis", "{analysis_id}"]))

    assert len(fake_popen.calls) == 1
    call = fake_popen.calls[0]
    assert call["args"] == [sys.executable, "-m", "xai.cli.pipeline", "run", "--analysis", "abc123"]
    assert call["cwd"] == hook.BACKEND_DIR
    assert call["env"]["PYTHONPATH"].split(hook.os.pathsep)[0] == str(hook.SRC_DIR)
    assert call["stdout"] is subprocess.DEVNULL and call["stderr"] is subprocess.DEVNULL


@pytest.mark.parametrize("cfg", [_cfg([]), _cfg(None), munchify({"post_analysis": {}}), munchify({})])
def test_empty_or_missing_command_starts_nothing(fake_popen, cfg):
    hook.notify_analysis_done("abc123", cfg)

    assert fake_popen.calls == []


def test_a_command_that_cannot_start_is_a_warning(monkeypatch, caplog):
    def broken(*args, **kwargs):
        raise FileNotFoundError("no such program")

    monkeypatch.setattr(hook.subprocess, "Popen", broken)

    with caplog.at_level(logging.WARNING, logger=hook.log.name):
        hook.notify_analysis_done("abc123", _cfg(["missing-program", "{analysis_id}"]))

    assert "post-analysis command not started for abc123" in caplog.text


def test_a_malformed_command_is_a_warning(fake_popen, caplog):
    with caplog.at_level(logging.WARNING, logger=hook.log.name):
        hook.notify_analysis_done("abc123", _cfg(["{python}", "{unknown}"]))

    assert fake_popen.calls == []
    assert "post-analysis command not started" in caplog.text


def test_the_command_runs_without_being_awaited(tmp_path):
    marker = tmp_path / "marker.txt"
    script = "import sys, time; time.sleep(0.5); open(sys.argv[1], 'w').write(sys.argv[2])"
    started = time.monotonic()

    hook.notify_analysis_done("abc123", _cfg(["{python}", "-c", script, str(marker), "{analysis_id}"]))

    assert time.monotonic() - started < 0.5
    deadline = time.monotonic() + 20
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.1)
    assert marker.read_text() == "abc123"


def _run_pipeline_finally() -> list[ast.stmt]:
    tree = ast.parse(SERVICE_IMPL.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_run_pipeline":
            for inner in ast.walk(node):
                if isinstance(inner, ast.Try) and inner.finalbody:
                    return inner.finalbody
    raise AssertionError("_run_pipeline has no try/finally")


def test_run_pipeline_notifies_only_done_analyses_after_the_gpu_release():
    body = _run_pipeline_finally()
    sources = [ast.unparse(statement) for statement in body]
    hook_at = next(i for i, s in enumerate(sources) if "notify_analysis_done" in s)
    release_at = next(i for i, s in enumerate(sources) if ".release(lease_token)" in s)

    assert release_at < hook_at
    guard = body[hook_at]
    assert isinstance(guard, ast.If)
    assert ast.unparse(guard.test) == "run.stage == AnalysisStage.DONE"
    assert [ast.unparse(s) for s in guard.body] == ["notify_analysis_done(run.id, cfg)"]
