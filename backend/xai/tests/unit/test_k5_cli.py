"""``python -m xai.cli.reports``: write and write-all, their exit codes, and the pipeline without LLM."""

import logging
from pathlib import Path

import pytest

from xai.cli import pipeline as pipeline_cli
from xai.cli import reports
from xai.contract import ContractDraft
from xai.contract.report import load_report
from xai.k1_harvester.output import AnalysisFolder
from xai.k2.stage import K2Stage
from xai.k4_planner.stage import K4Stage
from xai.k5_report1.stage import K5Stage
from xai.pipeline.paths import k4_path, k5_path
from xai.pipeline.runner import REPORT_STAGES
from xai.reporting.catalogue import ReportConfig
from xai.tests.k5_support import EchoModel, ScriptedModel, hand_text
from xai.tests.support import EXAMPLES_DIR, from_json_data, load_example

ANALYSIS = "an_test"


def _planned(out: Path, name: str) -> Path:
    """The plan of the example draft ``name`` under ``out``, with its source of truth."""
    draft = from_json_data(ContractDraft, load_example(EXAMPLES_DIR / f"{name}.bozza.json"))
    draft_path = AnalysisFolder(out, ANALYSIS).draft_path(draft.event.label, draft.event.event_id)
    K2Stage().process(draft, draft_path)
    K4Stage().process(draft, draft_path)
    return draft_path


def _use(monkeypatch: pytest.MonkeyPatch, llm: object) -> None:
    monkeypatch.setattr(reports, "configured_llm", lambda config: llm)


def test_write_writes_report_1_beside_the_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    draft_path = _planned(tmp_path, "handoff_s21_A")
    _use(monkeypatch, ScriptedModel([hand_text("handoff_s21_A")]))

    code = reports.main(["write", "--plan", str(k4_path(draft_path))])

    assert code == 0
    assert capsys.readouterr().out.strip() == str(k5_path(draft_path))
    assert load_report(k5_path(draft_path).read_text(encoding="utf-8")).report_meta.report == 1


def test_another_model_can_be_chosen_on_the_command_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    draft_path = _planned(tmp_path, "handoff_s21_A")
    chosen: list[ReportConfig] = []

    def configured(config: ReportConfig) -> ScriptedModel:
        chosen.append(config)
        return ScriptedModel([hand_text("handoff_s21_A")])

    monkeypatch.setattr(reports, "configured_llm", configured)

    assert reports.main(["write", "--plan", str(k4_path(draft_path)), "--model", "gemini-3.5-flash"]) == 0
    assert chosen[0].llm is not None and chosen[0].llm.model == "gemini-3.5-flash"


def test_another_provider_can_be_chosen_with_its_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    draft_path = _planned(tmp_path, "handoff_s21_A")
    chosen: list[ReportConfig] = []

    def configured(config: ReportConfig) -> ScriptedModel:
        chosen.append(config)
        return ScriptedModel([hand_text("handoff_s21_A")])

    monkeypatch.setattr(reports, "configured_llm", configured)
    plan = str(k4_path(draft_path))

    assert reports.main(["write", "--plan", plan, "--provider", "claude", "--model", "a-claude-model"]) == 0
    assert chosen[0].llm is not None
    assert (chosen[0].llm.provider, chosen[0].llm.model) == ("claude", "a-claude-model")


def test_a_provider_without_its_model_is_refused(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exited:
        reports.main(["write", "--plan", "plan.json", "--provider", "claude"])

    assert exited.value.code == 2
    assert "--provider needs --model" in capsys.readouterr().err


def test_an_up_to_date_report_is_said_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    draft_path = _planned(tmp_path, "handoff_s21_A")
    _use(monkeypatch, ScriptedModel([hand_text("handoff_s21_A")]))
    reports.main(["write", "--plan", str(k4_path(draft_path))])
    capsys.readouterr()

    assert reports.main(["write", "--plan", str(k4_path(draft_path))]) == 0
    assert capsys.readouterr().out.strip() == f"{k5_path(draft_path)} (up to date)"


def test_replay_makes_the_report_again_from_the_traces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    draft_path = _planned(tmp_path, "handoff_s21_A")
    _use(monkeypatch, ScriptedModel([hand_text("handoff_s21_A")]))
    reports.main(["write", "--plan", str(k4_path(draft_path))])
    first = k5_path(draft_path).read_text(encoding="utf-8")

    code = reports.main(["write", "--plan", str(k4_path(draft_path)), "--force", "--replay", str(tmp_path)])

    assert code == 0
    assert k5_path(draft_path).read_text(encoding="utf-8") == first


def test_without_a_configured_llm_no_report_and_exit_4(tmp_path: Path) -> None:
    draft_path = _planned(tmp_path, "handoff_s21_A")

    assert reports.main(["write", "--plan", str(k4_path(draft_path))]) == reports.EXIT_NO_REPORT
    assert not k5_path(draft_path).exists()


def test_a_missing_plan_exits_2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use(monkeypatch, EchoModel())

    assert reports.main(["write", "--plan", str(tmp_path / "k4" / "x" / "ev_000000000000.json")]) == 2


def test_write_all_goes_on_after_a_report_that_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fight = _planned(tmp_path, "fight_s5_A")
    handoff = _planned(tmp_path, "handoff_s21_A")
    # plans in order of event type: fight first, refused three times; then handoff
    bad = "## Limits\n\nNo marker."
    _use(monkeypatch, ScriptedModel([bad, bad, bad, hand_text("handoff_s21_A")]))

    code = reports.main(["write-all", "--analysis", ANALYSIS, "--out", str(tmp_path)])

    assert code == reports.EXIT_NO_REPORT
    assert not k5_path(fight).exists()
    assert k5_path(handoff).exists()


def test_write_all_without_plans_exits_2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use(monkeypatch, EchoModel())

    assert reports.main(["write-all", "--analysis", ANALYSIS, "--out", str(tmp_path)]) == 2


def test_without_llm_the_pipeline_stops_at_k4_and_logs_it(caplog: pytest.LogCaptureFixture) -> None:
    config = ReportConfig(llm=None, max_attempts=3, time_format="m:ss")

    with caplog.at_level(logging.WARNING, logger="xai.cli.pipeline"):
        stages = pipeline_cli.report_stages(config)

    assert stages == REPORT_STAGES
    assert "the pipeline stops at K4" in caplog.text


def test_with_an_llm_the_pipeline_writes_report_1_after_k4() -> None:
    config = ReportConfig(llm=None, max_attempts=3, time_format="m:ss")

    stages = pipeline_cli.report_stages(config, EchoModel())

    assert [stage.name for stage in stages] == ["k2", "k4", "k5"]
    assert isinstance(stages[-1], K5Stage)


def test_the_configured_llm_is_unavailable_in_the_tests() -> None:
    assert pipeline_cli.report_stages() == REPORT_STAGES
