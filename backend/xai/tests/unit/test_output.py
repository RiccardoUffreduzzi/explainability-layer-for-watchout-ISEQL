"""``AnalysisFolder``: the batch's files, the lock and the index."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from xai.contract.reasons import InputError
from xai.contract.serialization import load_draft
from xai.k1_harvester.batch import AnalysisOutcome, RuleOutcome
from xai.k1_harvester.output import AnalysisFolder, FolderLocked, index_data
from xai.k1_harvester.result import HarvestFailure, HarvestResult
from xai.tests.support import EXAMPLES_DIR, load_example

ANALYSIS = "gemini_3_6_flash_qwen2_audio_s21"


def _outcome() -> AnalysisOutcome:
    data = load_example(EXAMPLES_DIR / "handoff_s21_A.bozza.json")
    draft = load_draft(json.dumps(data, ensure_ascii=False))
    row = data["harvest_report"]["request"]["row"]
    ev_id = draft.event.event_id
    failure = HarvestFailure.input(InputError.ROW_SCHEMA_AMBIGUOUS, "columns not traceable")
    return AnalysisOutcome(
        analysis_id=ANALYSIS,
        condition="A",
        params_mode="defaults",
        params_origin="rule_defaults",
        extracted_at=datetime(2026, 10, 6, 20, 0, tzinfo=timezone.utc),
        rules=(
            RuleOutcome("fight", "fight/A", None, engine_error="ERROR executing query"),
            RuleOutcome(
                "handoff",
                "handoff/A",
                2,
                (
                    HarvestResult(0, row, ev_id, draft=draft),
                    HarvestResult(1, row, ev_id, duplicate_of=0),
                ),
            ),
            RuleOutcome("vehicle_escape", "vehicle_escape/A", None, failure=failure),
        ),
    )


def test_write_puts_a_draft_per_row_and_the_index(tmp_path: Path) -> None:
    folder = AnalysisFolder(tmp_path, ANALYSIS)
    outcome = _outcome()

    folder.write(outcome)

    draft_path = folder.draft_path("handoff", outcome.rules[1].results[0].event_id)
    assert load_draft(draft_path.read_text(encoding="utf-8")) == outcome.rules[1].results[0].draft
    assert folder.is_done()
    assert folder.index_path.stat().st_mtime_ns >= draft_path.stat().st_mtime_ns
    assert sorted(p.name for p in folder.path.rglob("*")) == sorted(
        ["handoff", draft_path.name, "index.json"]
    )


def test_the_index_has_every_rule_and_row() -> None:
    index = index_data(_outcome())

    assert [(e["rule_ref"], e["status"]) for e in index["events"]] == [
        ("fight/A", "engine_error"),
        ("handoff/A", "ok"),
        ("vehicle_escape/A", "failed"),
    ]
    rows = index["events"][1]["rows"]
    assert [(r["status"], r["duplicate_of"]) for r in rows] == [("draft", None), ("duplicate", 0)]
    assert rows[0]["draft"] == f"handoff/{rows[0]['event_id']}.json"
    assert index["events"][2]["failure"]["code"] == "ROW_SCHEMA_AMBIGUOUS"
    assert index["summary"] == {
        "events": 3,
        "events_failed": 2,
        "rows": 2,
        "drafts": 1,
        "rows_failed": 0,
        "duplicates": 1,
    }
    assert index["extracted_at"] == "2026-10-06T20:00:00Z"


def test_clear_removes_the_index_and_the_drafts_only(tmp_path: Path) -> None:
    folder = AnalysisFolder(tmp_path, ANALYSIS)
    folder.write(_outcome())
    folder.log_path.write_text("log\n", encoding="utf-8")
    (folder.path / "k2").mkdir()
    (folder.path / "k2" / "notes.txt").write_text("a later stage's file\n", encoding="utf-8")

    folder.clear()

    assert not folder.is_done()
    assert sorted(p.relative_to(folder.path).as_posix() for p in folder.path.rglob("*")) == [
        "k2",
        "k2/notes.txt",
        "pipeline.log",
    ]


def test_the_lock_is_exclusive_and_released(tmp_path: Path) -> None:
    folder = AnalysisFolder(tmp_path, ANALYSIS)

    with folder.lock():
        assert folder.lock_path.is_file()
        with pytest.raises(FolderLocked), folder.lock():
            pass
        assert folder.lock_path.is_file()
    assert not folder.lock_path.exists()

    with pytest.raises(RuntimeError), folder.lock():
        raise RuntimeError("the run failed")
    assert not folder.lock_path.exists()


@pytest.mark.parametrize("analysis_id", ["", ".", "..", "a/b", "a\\b"])
def test_an_id_that_is_not_a_folder_name_is_refused(tmp_path: Path, analysis_id: str) -> None:
    with pytest.raises(ValueError):
        AnalysisFolder(tmp_path, analysis_id)
