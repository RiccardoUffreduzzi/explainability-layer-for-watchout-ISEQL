"""End of an analysis: the report pipeline on the test database."""

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from xai.cli import pipeline as pipeline_cli
from xai.contract.plan import load_plan
from xai.contract.reasons import InputError
from xai.contract.source_of_truth import load_source_of_truth, verify_contract_hash
from xai.k1_harvester.output import AnalysisFolder
from xai.k1_harvester.result import HarvestFailure
from xai.pipeline.paths import K2_FOLDER, K4_FOLDER
from xai.pipeline.runner import ReportPipeline
from xai.tests.harness import make_batch, open_reader
from xai.tests.support import EXAMPLES_DIR, load_example, scene

S21 = scene(21)
S15 = scene(15)
"""Condition A (one branch) and condition C (a branch per modality, with the reinforcement)."""


@pytest.fixture
def pipeline(watchout_db: Path) -> Iterator[ReportPipeline]:
    conn, reader = open_reader(watchout_db)
    yield ReportPipeline(make_batch(reader))
    conn.close()


def test_a_draft_per_row_and_the_index_last(pipeline: ReportPipeline, tmp_path: Path) -> None:
    run = pipeline.run(S21, tmp_path)

    assert run.status == "done"
    index = json.loads(run.folder.index_path.read_text(encoding="utf-8"))
    assert (index["condition"], index["params"], index["params_origin"]) == ("A", "defaults", "rule_defaults")
    assert [e["rule_ref"] for e in index["events"]] == [
        "fight/A",
        "gunshot_or_explosion/A",
        "handoff/A",
        "suspicious_near_vehicle/A",
        "vehicle_collision/A",
        "vehicle_escape/A",
    ]
    rows = [r for e in index["events"] for r in e["rows"]]
    drafts = sorted(p.relative_to(run.folder.path).as_posix() for p in run.folder.path.glob("*/*.json"))
    assert drafts == sorted(r["draft"] for r in rows if r["status"] == "draft")
    assert index["summary"]["drafts"] == len(drafts) == len(rows) >= 1
    newest_draft = max((run.folder.path / d).stat().st_mtime_ns for d in drafts)
    assert run.folder.index_path.stat().st_mtime_ns >= newest_draft


def test_k2_writes_a_source_of_truth_for_each_draft(pipeline: ReportPipeline, tmp_path: Path) -> None:
    run = pipeline.run(S21, tmp_path)

    index = json.loads(run.folder.index_path.read_text(encoding="utf-8"))
    drafts = sorted(r["draft"] for e in index["events"] for r in e["rows"] if r["status"] == "draft")
    k2_dir = run.folder.path / "k2"
    written = sorted(p.relative_to(k2_dir).as_posix() for p in k2_dir.glob("*/*.json"))
    assert written == drafts
    for draft in drafts:
        document = load_source_of_truth((k2_dir / draft).read_text(encoding="utf-8"))
        assert verify_contract_hash(document)
        assert f"{document.event.label}/{document.event.event_id}.json" == draft
    assert not list(k2_dir.rglob("*.tmp"))


@pytest.mark.parametrize("analysis_id", [S21, S15], ids=["condition_A", "condition_C"])
def test_k4_writes_a_plan_for_each_source_of_truth(
    pipeline: ReportPipeline, tmp_path: Path, analysis_id: str
) -> None:
    # The pipeline only logs a stage that fails: a missing plan is the only sign (UC-K4-11).
    run = pipeline.run(analysis_id, tmp_path)

    k2_dir = run.folder.path / K2_FOLDER
    k4_dir = run.folder.path / K4_FOLDER
    sources = sorted(p.relative_to(k2_dir).as_posix() for p in k2_dir.glob("*/*.json"))
    written = sorted(p.relative_to(k4_dir).as_posix() for p in k4_dir.glob("*/*.json"))
    assert written == sources != []
    for name in written:
        plan = load_plan((k4_dir / name).read_text(encoding="utf-8"))
        source = load_source_of_truth((k2_dir / name).read_text(encoding="utf-8"))
        assert plan.plan_meta.contract_hash == source.contract_meta.contract_hash
        assert f"{plan.plan_meta.label}/{plan.plan_meta.event_id}.json" == name
    assert not list(k4_dir.rglob("*.tmp"))


def test_the_batch_draft_is_the_single_request_draft(pipeline: ReportPipeline, tmp_path: Path) -> None:
    run = pipeline.run(S21, tmp_path)

    index = json.loads(run.folder.index_path.read_text(encoding="utf-8"))
    handoff = next(e for e in index["events"] if e["rule_ref"] == "handoff/A")
    written = json.loads((run.folder.path / handoff["rows"][0]["draft"]).read_text(encoding="utf-8"))
    assert written == load_example(EXAMPLES_DIR / "handoff_s21_A.bozza.json")


def test_a_done_analysis_is_skipped_unless_forced(pipeline: ReportPipeline, tmp_path: Path) -> None:
    first = pipeline.run(S21, tmp_path)
    index = first.folder.index_path.read_bytes()
    stale = first.folder.path / "handoff" / "ev_000000000000.json"
    stale.write_text("{}", encoding="utf-8")

    second = pipeline.run(S21, tmp_path)
    assert second.status == "skipped"
    assert first.folder.index_path.read_bytes() == index

    forced = pipeline.run(S21, tmp_path, force=True)
    assert forced.status == "done"
    assert not stale.exists()


def test_a_held_lock_stops_the_run(pipeline: ReportPipeline, tmp_path: Path) -> None:
    folder = AnalysisFolder(tmp_path, S21)
    folder.path.mkdir(parents=True)
    folder.lock_path.write_text("4242\n", encoding="utf-8")

    run = pipeline.run(S21, tmp_path)

    assert run.status == "locked"
    assert not folder.is_done()
    assert folder.lock_path.read_text(encoding="utf-8") == "4242\n"


def test_an_analysis_not_done_is_refused(watchout_db_copy: Path, tmp_path: Path) -> None:
    with sqlite3.connect(watchout_db_copy) as conn:
        conn.execute("UPDATE Analyses SET Stage = 'running' WHERE ID = ?", (S21,))
    conn.close()
    db, reader = open_reader(watchout_db_copy)
    try:
        with pytest.raises(HarvestFailure) as failure:
            ReportPipeline(make_batch(reader)).run(S21, tmp_path)
    finally:
        db.close()

    assert failure.value.code == InputError.ANALYSIS_NOT_READY
    assert not AnalysisFolder(tmp_path, S21).is_done()


# ----------------------------------------------------------------------------- the command


def test_the_command_writes_the_index_and_the_log(
    watchout_db: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = ["run", "--analysis", S21, "--db", str(watchout_db), "--out", str(tmp_path)]

    assert pipeline_cli.main(argv) == 0
    folder = AnalysisFolder(tmp_path, S21)
    assert capsys.readouterr().out.strip() == str(folder.index_path)
    assert folder.is_done()
    assert pipeline_cli.main(argv) == 0
    log = folder.log_path.read_text(encoding="utf-8")
    assert "handoff/A: 1 row(s), 1 draft(s)" in log
    assert "nothing to do" in log


def test_the_command_exits_2_on_an_analysis_not_done(watchout_db_copy: Path, tmp_path: Path) -> None:
    with sqlite3.connect(watchout_db_copy) as conn:
        conn.execute("UPDATE Analyses SET Stage = 'failed' WHERE ID = ?", (S21,))
    conn.close()

    argv = ["run", "--analysis", S21, "--db", str(watchout_db_copy), "--out", str(tmp_path)]

    assert pipeline_cli.main(argv) == 2
    assert "ANALYSIS_NOT_READY" in AnalysisFolder(tmp_path, S21).log_path.read_text(encoding="utf-8")


def test_the_command_exits_1_without_a_database(tmp_path: Path) -> None:
    argv = ["run", "--analysis", S21, "--db", str(tmp_path / "missing.db"), "--out", str(tmp_path)]

    assert pipeline_cli.main(argv) == 1
    assert "database not found" in AnalysisFolder(tmp_path, S21).log_path.read_text(encoding="utf-8")
