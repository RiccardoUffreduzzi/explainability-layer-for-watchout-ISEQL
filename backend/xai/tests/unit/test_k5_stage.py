"""``K5Stage`` and the files of a report: whole or only the failed trace, not written again if current."""

import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from xai.contract import ContractDraft
from xai.contract.report import load_report, load_trace
from xai.k1_harvester.output import AnalysisFolder
from xai.k2.stage import K2Stage
from xai.k4_planner.stage import K4Stage
from xai.k5_report1.stage import K5Stage
from xai.pipeline.paths import k2_path, k4_path, k5_path
from xai.pipeline.runner import ReportPipeline, ReportStage
from xai.reporting.failure import ReportFailure
from xai.reporting.files import ReportFiles, write_report
from xai.reporting.ports import LlmUnavailable
from xai.tests.k5_support import EchoModel, ScriptedModel, hand_text, writer
from xai.tests.support import EXAMPLES_DIR, from_json_data, load_example

ANALYSIS = "an_test"
HANDOFF = "handoff_s21_A"
EV = "ev_beffcb6f2a6e"


def _draft(name: str) -> ContractDraft:
    return from_json_data(ContractDraft, load_example(EXAMPLES_DIR / f"{name}.bozza.json"))


def _planned(root: Path, name: str = HANDOFF) -> tuple[ContractDraft, Path]:
    """The draft through K2 and K4, as the pipeline leaves it before K5."""
    draft = _draft(name)
    draft_path = AnalysisFolder(root, ANALYSIS).draft_path(draft.event.label, draft.event.event_id)
    K2Stage().process(draft, draft_path)
    K4Stage().process(draft, draft_path)
    return draft, draft_path


def test_the_stage_reads_k4_and_satisfies_the_protocol() -> None:
    stage: ReportStage = K5Stage(writer(EchoModel()))

    assert (stage.name, K5Stage.reads_from) == ("k5", "k4")


def test_report_1_is_written_in_its_own_folder(tmp_path: Path) -> None:
    draft, draft_path = _planned(tmp_path)

    K5Stage(writer(ScriptedModel([hand_text(HANDOFF)]))).process(draft, draft_path)

    files = ReportFiles.of(k5_path(draft_path))
    assert files.json == tmp_path / ANALYSIS / "k5" / "handoff" / f"{EV}.json"
    assert files.markdown.name == f"{EV}.md" and files.trace.name == f"{EV}.trace.json"
    report = load_report(files.json.read_text(encoding="utf-8"))
    assert report.report_meta.event_id == EV
    assert files.markdown.read_text(encoding="utf-8").startswith("# Detection report: handoff\n")
    assert load_trace(files.trace.read_text(encoding="utf-8")).calls[0].answer == hand_text(HANDOFF)
    assert not list(files.json.parent.glob("*.tmp"))


def test_an_up_to_date_report_does_not_call_the_llm_again(tmp_path: Path) -> None:
    _, draft_path = _planned(tmp_path)
    target = k5_path(draft_path)
    write_report(
        writer(ScriptedModel([hand_text(HANDOFF)])), k4_path(draft_path), k2_path(draft_path), target
    )
    silent = ScriptedModel([])

    status = write_report(writer(silent), k4_path(draft_path), k2_path(draft_path), target)

    assert (status, silent.prompts) == ("current", [])


def test_force_writes_an_up_to_date_report_again(tmp_path: Path) -> None:
    _, draft_path = _planned(tmp_path)
    target = k5_path(draft_path)
    llm = ScriptedModel([hand_text(HANDOFF), hand_text(HANDOFF)])
    write_report(writer(llm), k4_path(draft_path), k2_path(draft_path), target)

    status = write_report(writer(llm), k4_path(draft_path), k2_path(draft_path), target, force=True)

    assert (status, len(llm.prompts)) == ("written", 2)


def test_another_model_writes_the_report_again(tmp_path: Path) -> None:
    _, draft_path = _planned(tmp_path)
    target = k5_path(draft_path)
    write_report(
        writer(ScriptedModel([hand_text(HANDOFF)])), k4_path(draft_path), k2_path(draft_path), target
    )

    echo = EchoModel()
    status = write_report(writer(echo), k4_path(draft_path), k2_path(draft_path), target)

    assert status == "written" and len(echo.prompts) == 1
    assert load_report(target.read_text(encoding="utf-8")).report_meta.llm.model == "echo"


def test_a_failure_leaves_no_report_of_an_older_plan(tmp_path: Path) -> None:
    _, draft_path = _planned(tmp_path)
    target = k5_path(draft_path)
    write_report(
        writer(ScriptedModel([hand_text(HANDOFF)])), k4_path(draft_path), k2_path(draft_path), target
    )
    stale = target.read_text(encoding="utf-8").replace(
        load_report(target.read_text(encoding="utf-8")).report_meta.plan_hash, "0" * 64
    )
    target.write_text(stale, encoding="utf-8")

    with pytest.raises(ReportFailure):
        write_report(
            writer(ScriptedModel([LlmUnavailable("down")])), k4_path(draft_path), k2_path(draft_path), target
        )

    files = ReportFiles.of(target)
    assert [p for p in files.all() if p.exists()] == []
    assert load_trace(files.failed_trace.read_text(encoding="utf-8")).calls[0].error == "down"


def test_a_text_that_cannot_be_rendered_leaves_its_trace_until_a_report_is_written(tmp_path: Path) -> None:
    _, draft_path = _planned(tmp_path)
    target = k5_path(draft_path)
    files = ReportFiles.of(target)

    with pytest.raises(ReportFailure) as caught:
        write_report(
            writer(ScriptedModel(["no sections", "no sections", "no sections"])),
            k4_path(draft_path),
            k2_path(draft_path),
            target,
        )

    assert caught.value.code == "TEXT_NOT_RENDERABLE"
    calls = load_trace(files.failed_trace.read_text(encoding="utf-8")).calls
    assert [(call.answer, bool(call.problems)) for call in calls] == [("no sections", True)] * 3
    assert [p for p in files.all() if p.exists()] == []

    write_report(
        writer(ScriptedModel([hand_text(HANDOFF)])), k4_path(draft_path), k2_path(draft_path), target
    )

    assert all(p.exists() for p in files.all()) and not files.failed_trace.exists()


def test_without_plan_there_is_no_report(tmp_path: Path) -> None:
    draft = _draft(HANDOFF)
    draft_path = AnalysisFolder(tmp_path, ANALYSIS).draft_path("handoff", EV)

    with pytest.raises(ReportFailure) as caught:
        K5Stage(writer(EchoModel())).process(draft, draft_path)

    assert caught.value.code == "PLAN_NOT_FOUND"
    assert not k5_path(draft_path).exists()


class _Reader:
    """A later stage that reads only K4's files, as K6 will."""

    name = "k6"
    reads_from = "k4"

    def __init__(self) -> None:
        self.seen: list[str] = []

    def process(self, draft: ContractDraft, draft_path: Path) -> None:
        self.seen.append(draft.event.label)


def test_a_failed_report_1_does_not_stop_a_stage_that_reads_k4(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    draft = _draft(HANDOFF)
    outcome = SimpleNamespace(drafts=lambda: [(1, SimpleNamespace(draft=draft, event_id=EV))])
    later = _Reader()
    unreachable = ScriptedModel([LlmUnavailable("down")])
    stages = (K2Stage(), K4Stage(), K5Stage(writer(unreachable)), later)
    pipeline = ReportPipeline(harvester=None, stages=stages)  # type: ignore[arg-type]

    with caplog.at_level(logging.ERROR, logger="xai.pipeline"):
        pipeline._later_stages(outcome, AnalysisFolder(tmp_path, ANALYSIS))  # type: ignore[arg-type]

    assert later.seen == ["handoff"]
    assert "stage k5 failed" in caplog.text
    assert [p.name for p in (tmp_path / ANALYSIS / "k5").rglob("*")] == ["handoff", f"{EV}.failed.trace.json"]


def test_a_failed_k4_skips_the_stages_that_read_it(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    class _NoPlan:
        name = "k4"
        reads_from = "k2"

        def process(self, draft: ContractDraft, draft_path: Path) -> None:
            raise RuntimeError("no plan")

    draft = _draft(HANDOFF)
    outcome = SimpleNamespace(drafts=lambda: [(1, SimpleNamespace(draft=draft, event_id=EV))])
    echo = EchoModel()
    later = _Reader()
    pipeline = ReportPipeline(harvester=None, stages=(K2Stage(), _NoPlan(), K5Stage(writer(echo)), later))  # type: ignore[arg-type]

    pipeline._later_stages(outcome, AnalysisFolder(tmp_path, ANALYSIS))  # type: ignore[arg-type]

    assert (echo.prompts, later.seen) == ([], [])
    assert "stage k5 skipped" in caplog.text


def test_k2_k4_and_k5_through_the_pipeline_loop(tmp_path: Path) -> None:
    draft = _draft(HANDOFF)
    outcome = SimpleNamespace(drafts=lambda: [(1, SimpleNamespace(draft=draft, event_id=EV))])
    stages = (K2Stage(), K4Stage(), K5Stage(writer(ScriptedModel([hand_text(HANDOFF)]))))
    pipeline = ReportPipeline(harvester=None, stages=stages)  # type: ignore[arg-type]

    pipeline._later_stages(outcome, AnalysisFolder(tmp_path, ANALYSIS))  # type: ignore[arg-type]

    report = load_report((tmp_path / ANALYSIS / "k5" / "handoff" / f"{EV}.json").read_text(encoding="utf-8"))
    assert report.report_meta.event_id == draft.event.event_id
