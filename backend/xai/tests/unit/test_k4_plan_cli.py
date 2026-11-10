"""``python -m xai.cli.k4``: plan and plan-all, and their exit codes."""

import json
from pathlib import Path

import pytest

from xai.cli.k4 import main
from xai.contract.plan import dump_plan
from xai.contract.source_of_truth import dump_source_of_truth
from xai.k1_harvester.output import AnalysisFolder
from xai.k4_planner.planner import ExplanationPlanner
from xai.pipeline.paths import k4_path
from xai.tests.k4_plan_support import plan_of
from xai.tests.k4_support import golden_source


def _write_source(folder: Path, name: str) -> Path:
    document = golden_source(name)
    path = folder / "k2" / document.event.label / f"{document.event.event_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_source_of_truth(document, indent=2), encoding="utf-8")
    return path


def test_plan_writes_the_plan_under_the_analysis_of_the_source(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    document = golden_source("handoff_s21_A")
    source = _write_source(tmp_path / "inputs", "handoff_s21_A")

    code = main(["plan", "--source", str(source), "--out", str(tmp_path / "out")])

    draft_path = AnalysisFolder(tmp_path / "out", document.contract_meta.analysis_id).draft_path(
        "handoff", document.event.event_id
    )
    target = k4_path(draft_path)
    assert code == 0
    assert capsys.readouterr().out.strip() == str(target)
    assert target.exists()
    assert target.read_text(encoding="utf-8").startswith("{")


def test_plan_of_a_missing_file_exits_with_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["plan", "--source", str(tmp_path / "absent.json"), "--out", str(tmp_path)])

    assert code == 2
    assert json.loads(capsys.readouterr().err.split("\n", 1)[-1] or "{}")["code"] == "SOURCE_NOT_FOUND"
    assert not list(tmp_path.rglob("k4"))


def test_plan_of_a_source_whose_hash_differs_exits_with_2(tmp_path: Path) -> None:
    source = _write_source(tmp_path / "inputs", "fight_s5_A")
    data = json.loads(source.read_text(encoding="utf-8"))
    data["contract_meta"]["contract_hash"] = "1" * 64
    source.write_text(json.dumps(data), encoding="utf-8")

    assert main(["plan", "--source", str(source), "--out", str(tmp_path / "out")]) == 2
    assert not (tmp_path / "out").exists()


def test_plan_all_plans_every_source_in_a_fixed_order(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    analysis = tmp_path / "an_1"
    paths = [
        _write_source(analysis, name) for name in ("handoff_s21_A", "fight_s5_A", "gunshot_or_explosion_s7_A")
    ]

    code = main(["plan-all", "--analysis", "an_1", "--out", str(tmp_path)])

    printed = capsys.readouterr().out.split()
    assert code == 0
    assert printed == sorted(
        (str(analysis / "k4" / p.parent.name / p.name) for p in paths),
        key=lambda s: (Path(s).parent.name, Path(s).name),
    )
    assert all(Path(p).exists() for p in printed)


def test_plan_all_goes_on_after_a_source_that_cannot_be_planned(tmp_path: Path) -> None:
    analysis = tmp_path / "an_1"
    bad = _write_source(analysis, "fight_s5_A")
    good = _write_source(analysis, "handoff_s21_A")
    bad.write_text("not json", encoding="utf-8")

    code = main(["plan-all", "--analysis", "an_1", "--out", str(tmp_path)])

    assert code == 2
    assert (analysis / "k4" / "handoff" / good.name).exists()
    assert not (analysis / "k4" / "fight").exists()


def test_plan_all_with_no_sources_exits_with_2(tmp_path: Path) -> None:
    assert main(["plan-all", "--analysis", "an_none", "--out", str(tmp_path)]) == 2


def test_the_plan_of_the_cli_is_the_one_of_the_planner(tmp_path: Path) -> None:
    source = _write_source(tmp_path / "inputs", "handoff_s21_A")
    main(["plan", "--source", str(source), "--out", str(tmp_path / "out")])

    written = next((tmp_path / "out").rglob("k4/*/*.json"))

    assert json.loads(written.read_text(encoding="utf-8")) == json.loads(dump_plan(plan_of("handoff_s21_A")))


def test_an_unexpected_error_exits_with_1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _write_source(tmp_path / "inputs", "handoff_s21_A")

    def broken(self: ExplanationPlanner, document: object) -> object:
        raise RuntimeError("boom")

    monkeypatch.setattr(ExplanationPlanner, "plan", broken)

    assert main(["plan", "--source", str(source), "--out", str(tmp_path / "out")]) == 1
