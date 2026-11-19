"""WatchOut and the report pipeline on analyses written with the visual sampling in Hz.

The test database holds rows written before WatchOut split the frame rate from the sampling
rate (``FrameRate`` empty, ``SamplingRate`` = fps). Here two scenes are written as WatchOut
writes them now, for a 30 fps video analysed at 0.5 Hz: the GUI and K1 must show the same rows,
in video time, and the drafts, the plans and the reports must say 30 fps, one frame every 60
and a 2 s merge tolerance.
"""

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from xai.k1_harvester.ports import EngineError
from xai.k1_harvester.timebase import round_ms
from xai.k5_report1.stage import K5Stage
from xai.pipeline.paths import K2_FOLDER, K4_FOLDER, K5_FOLDER
from xai.pipeline.runner import REPORT_STAGES, ReportPipeline
from xai.tests.harness import make_batch, open_reader
from xai.tests.k5_support import EchoModel, writer
from xai.tests.support import scene

FRAME_RATE = 30.0
SAMPLING_HZ = 0.5
SCENES = (scene(21), scene(15))
"""Condition A (one branch) and condition C (a branch per modality)."""


@pytest.fixture
def db_at_half_hertz(watchout_db_copy: Path) -> Path:
    conn = sqlite3.connect(watchout_db_copy)
    try:
        conn.executemany(
            "UPDATE Analyses SET FrameRate = ?, SamplingRate = ? WHERE ID = ?",
            [(FRAME_RATE, SAMPLING_HZ, analysis_id) for analysis_id in SCENES],
        )
        conn.commit()
    finally:
        conn.close()
    return watchout_db_copy


def test_the_gui_and_k1_show_the_same_rows_in_video_time(
    db_at_half_hertz: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from service.impl.analysis_service_impl import AnalysisServiceImpl
    from service.impl.events_service_impl import format_time
    from utils.config import Config

    monkeypatch.setitem(Config.get().data, "db_path", str(db_at_half_hertz))
    service = AnalysisServiceImpl()
    conn, reader = open_reader(db_at_half_hertz)
    params = reader.default_params()
    compared, timed = 0, 0
    try:
        for analysis_id in SCENES:
            analysis = reader.analysis(analysis_id)
            assert analysis is not None
            assert (analysis.frame_rate, analysis.sampling_hz, analysis.fps_column) == (30, 0.5, "FrameRate")
            for condition in ("A", "B", "C"):
                for rule in reader.rules(condition):
                    gui: list[dict[str, Any]] = service.detect_event(
                        analysis_id=analysis_id,
                        event_type=rule.event_type,
                        condition=condition,
                        deltas=dict(params.values),
                        unit="seconds",
                    )["rows"]
                    try:
                        ours = [dict(r.gui_values) for r in reader.detection(rule, analysis, params).rows]
                    except EngineError:
                        ours = []  # detect_event drops the engine's ERROR lines: the GUI shows no rows
                    assert ours == gui, f"{rule.ref}@{analysis_id}"
                    compared += len(gui)
                    for row in gui:
                        for alias in ("M1", "M2"):
                            if f"{alias}.sf" in row and f"{alias}.st" in row:
                                assert row[f"{alias}.st"] == format_time(row[f"{alias}.sf"] / FRAME_RATE)
                                timed += 1
    finally:
        conn.close()

    assert compared >= 1 and timed >= 1


@pytest.mark.parametrize("analysis_id", SCENES, ids=["condition_A", "condition_C"])
def test_the_report_pipeline_uses_the_frame_rate_and_the_sampling_rate(
    db_at_half_hertz: Path, tmp_path: Path, analysis_id: str
) -> None:
    conn, reader = open_reader(db_at_half_hertz)
    try:
        pipeline = ReportPipeline(make_batch(reader), (*REPORT_STAGES, K5Stage(writer(EchoModel()))))
        run = pipeline.run(analysis_id, tmp_path)
    finally:
        conn.close()

    assert run.status == "done"
    drafts = sorted(run.folder.path.glob("*/*.json"))
    assert drafts
    anchors = 0
    for path in drafts:
        draft = json.loads(path.read_text(encoding="utf-8"))
        config = draft["contract_meta"]["pipeline_config"]
        assert config["sampling"] == {"source_fps": 30.0, "sample_every_n": 60, "effective_hz": 0.5}
        assert config["merge_tolerance_s"] == 2.0
        assert config["sources"]["sampling.source_fps"]["record_id"] == f"Analyses/{analysis_id}/FrameRate"
        for interval in draft["intervals"]:
            anchor = interval["anchor"]
            if anchor["read_as"] == "frames":
                assert anchor["start_s"] == round_ms(anchor["start_frame"] / FRAME_RATE)
                assert anchor["end_s"] == round_ms(anchor["end_frame"] / FRAME_RATE)
                anchors += 1
        relative = path.relative_to(run.folder.path)
        for stage in (K2_FOLDER, K4_FOLDER, K5_FOLDER):
            assert (run.folder.path / stage / relative).exists(), f"{stage}/{relative}"
    assert anchors >= 1
