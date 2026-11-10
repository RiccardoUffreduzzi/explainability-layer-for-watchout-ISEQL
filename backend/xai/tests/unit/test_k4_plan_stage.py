"""``K4Stage``: reads the file of K2, writes the plan in its own folder, whole or not at all."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from xai.contract import ContractDraft
from xai.contract.plan import dump_plan, load_plan
from xai.contract.source_of_truth import dump_source_of_truth
from xai.k1_harvester.output import AnalysisFolder
from xai.k2.source_of_truth import build_source_of_truth
from xai.k2.stage import K2Stage
from xai.k4_planner.planner import ExplanationPlanner, PlanFailure
from xai.k4_planner.stage import K4Stage, write_plan
from xai.pipeline.paths import k2_path, k4_path
from xai.pipeline.runner import REPORT_STAGES, ReportPipeline, ReportStage
from xai.tests.k4_plan_support import plan_of
from xai.tests.support import EXAMPLES_DIR, from_json_data, load_example

ANALYSIS = "an_test"


def _draft(name: str) -> ContractDraft:
    return from_json_data(ContractDraft, load_example(EXAMPLES_DIR / f"{name}.bozza.json"))


def _draft_path(root: Path, draft: ContractDraft, ev_id: str = "ev_0123456789ab") -> Path:
    return root / ANALYSIS / draft.event.label / f"{ev_id}.json"


def _with_k2_file(root: Path, name: str) -> tuple[ContractDraft, Path]:
    draft = _draft(name)
    draft_path = _draft_path(root, draft)
    source = k2_path(draft_path)
    source.parent.mkdir(parents=True)
    source.write_text(dump_source_of_truth(build_source_of_truth(draft), indent=2), encoding="utf-8")
    return draft, draft_path


def test_k4_runs_after_k2() -> None:
    assert [stage.name for stage in REPORT_STAGES] == ["k2", "k4"]


def test_the_stage_satisfies_the_pipeline_protocol() -> None:
    stage: ReportStage = K4Stage()

    assert stage.name == "k4"


def test_the_plan_is_written_in_its_own_folder(tmp_path: Path) -> None:
    draft, draft_path = _with_k2_file(tmp_path, "handoff_s21_A")

    K4Stage().process(draft, draft_path)

    written = k4_path(draft_path)
    assert written == tmp_path / ANALYSIS / "k4" / "handoff" / "ev_0123456789ab.json"
    assert written.read_text(encoding="utf-8") == dump_plan(plan_of("handoff_s21_A"), indent=2) + "\n"
    assert load_plan(written.read_text(encoding="utf-8")).plan_meta.label == "handoff"
    assert not list(written.parent.glob("*.tmp"))


def test_the_other_files_are_left_alone(tmp_path: Path) -> None:
    draft, draft_path = _with_k2_file(tmp_path, "handoff_s21_A")
    draft_path.parent.mkdir(parents=True)
    draft_path.write_text("k1", encoding="utf-8")
    before = k2_path(draft_path).read_bytes()

    K4Stage().process(draft, draft_path)

    assert draft_path.read_text(encoding="utf-8") == "k1"
    assert k2_path(draft_path).read_bytes() == before
    assert sorted(p.name for p in (tmp_path / ANALYSIS).glob("*/*.json")) == ["ev_0123456789ab.json"]


def test_a_missing_source_leaves_no_plan_at_all(tmp_path: Path) -> None:
    draft = _draft("handoff_s21_A")
    draft_path = _draft_path(tmp_path, draft)

    with pytest.raises(PlanFailure) as failure:
        K4Stage().process(draft, draft_path)

    assert failure.value.code == "SOURCE_NOT_FOUND"
    assert not (tmp_path / ANALYSIS / "k4").exists()


def test_a_failure_while_planning_leaves_no_plan_and_no_temporary_file(tmp_path: Path) -> None:
    draft, draft_path = _with_k2_file(tmp_path, "handoff_s21_A")

    def broken(view: Any) -> Any:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        K4Stage(ExplanationPlanner(broken)).process(draft, draft_path)

    assert not list((tmp_path / ANALYSIS).rglob("k4/**/*"))


def test_write_plan_replaces_an_older_plan(tmp_path: Path) -> None:
    target = tmp_path / "k4" / "handoff" / "ev.json"
    target.parent.mkdir(parents=True)
    target.write_text("old", encoding="utf-8")

    write_plan(plan_of("handoff_s21_A"), target)

    assert load_plan(target.read_text(encoding="utf-8")).plan_meta.label == "handoff"


class _Boom:
    """A stage between K2 and K4 that fails on one event type."""

    name = "boom"

    def process(self, draft: ContractDraft, draft_path: Path) -> None:
        if draft.event.label == "handoff":
            raise RuntimeError("boom")


def test_a_failure_before_k4_spares_the_other_drafts(tmp_path: Path) -> None:
    drafts = [_draft("handoff_s21_A"), _draft("fight_s5_A")]
    results = [
        (i, SimpleNamespace(draft=draft, event_id=f"ev_{i:012x}")) for i, draft in enumerate(drafts, start=1)
    ]
    outcome = SimpleNamespace(drafts=lambda: results)
    pipeline = ReportPipeline(harvester=None, stages=(K2Stage(), _Boom(), K4Stage()))  # type: ignore[arg-type]

    pipeline._later_stages(outcome, AnalysisFolder(tmp_path, ANALYSIS))  # type: ignore[arg-type]

    assert not (tmp_path / ANALYSIS / "k4" / "handoff").exists()
    assert (tmp_path / ANALYSIS / "k4" / "fight" / f"ev_{2:012x}.json").exists()


def test_k2_then_k4_through_the_pipeline_loop(tmp_path: Path) -> None:
    draft = _draft("handoff_s21_A")
    outcome = SimpleNamespace(drafts=lambda: [(1, SimpleNamespace(draft=draft, event_id="ev_beffcb6f2a6e"))])
    pipeline = ReportPipeline(harvester=None)  # type: ignore[arg-type]

    pipeline._later_stages(outcome, AnalysisFolder(tmp_path, ANALYSIS))  # type: ignore[arg-type]

    plan = load_plan(
        (tmp_path / ANALYSIS / "k4" / "handoff" / "ev_beffcb6f2a6e.json").read_text(encoding="utf-8")
    )
    assert plan.plan_meta.event_id == draft.event.event_id
    assert plan.plan_meta.contract_hash == build_source_of_truth(draft).contract_meta.contract_hash
