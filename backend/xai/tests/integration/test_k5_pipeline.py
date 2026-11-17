"""Report 1 at the end of an analysis: the pipeline on the test database, with an LLM that answers by itself.

``EchoModel`` writes one sentence per step of the prompt, so every plan of the real analyses gets
a report that can be rendered; no test calls a real LLM.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest

from xai.contract.plan import load_plan
from xai.contract.report import load_report
from xai.k5_report1.stage import K5Stage
from xai.pipeline.paths import K4_FOLDER, K5_FOLDER
from xai.pipeline.runner import REPORT_STAGES, ReportPipeline
from xai.tests.harness import make_batch, open_reader
from xai.tests.k5_support import EchoModel, writer
from xai.tests.support import scene

S21 = scene(21)
S15 = scene(15)


@pytest.fixture
def echo() -> EchoModel:
    return EchoModel()


@pytest.fixture
def pipeline(watchout_db: Path, echo: EchoModel) -> Iterator[ReportPipeline]:
    conn, reader = open_reader(watchout_db)
    yield ReportPipeline(make_batch(reader), (*REPORT_STAGES, K5Stage(writer(echo))))
    conn.close()


@pytest.mark.parametrize("analysis_id", [S21, S15], ids=["condition_A", "condition_C"])
def test_k5_writes_report_1_for_each_plan(
    pipeline: ReportPipeline, echo: EchoModel, tmp_path: Path, analysis_id: str
) -> None:
    run = pipeline.run(analysis_id, tmp_path)

    k4_dir = run.folder.path / K4_FOLDER
    k5_dir = run.folder.path / K5_FOLDER
    plans = sorted(p.relative_to(k4_dir).as_posix() for p in k4_dir.glob("*/*.json"))
    reports = sorted(
        p.relative_to(k5_dir).as_posix()
        for p in k5_dir.glob("*/*.json")
        if not p.name.endswith(".trace.json")
    )
    assert reports == plans and len(echo.prompts) == len(plans) >= 1
    for name in plans:
        plan = load_plan((k4_dir / name).read_text(encoding="utf-8"))
        report = load_report((k5_dir / name).read_text(encoding="utf-8"))
        assert report.report_meta.plan_hash == plan.plan_meta.plan_hash
        rendered = {i for section in report.sections for s in section.sentences for i in s.step_ids}
        assert rendered == {s.step_id for s in plan.steps}
        assert (k5_dir / name).with_suffix(".md").exists()
        assert (k5_dir / name.replace(".json", ".trace.json")).exists()
