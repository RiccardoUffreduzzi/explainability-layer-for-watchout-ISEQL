"""WatchOut end to end with the visual sampling in Hz, from the kept frames to the GUI rows.

The run is simulated without a VLM, on a 30 fps video analysed at 0.5 Hz: the relations are
written on the frames the visual pipeline keeps (one every ``frame_step_for(FrameRate,
SamplingRate)``), the intervals are built with the merge gap the analysis passes
(``merge_gap_frames_for(FrameRate)``), and the detection runs as the GUI runs it. Every time
the GUI shows must be video time: frames divided by the frame rate, never by the sampling rate.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("pandas")

from models.analysis import MERGE_GAP_SECONDS, frame_step_for, merge_gap_frames_for  # noqa: E402
from service.impl.events_service_impl import EventsServiceImpl, default_params, format_time  # noqa: E402
from service.impl.interval_service_impl import IntervalServiceImpl  # noqa: E402
from utils.database import setup_database  # noqa: E402

SNAPSHOT = json.loads((Path(__file__).parent / "data" / "compile_snapshot.json").read_text(encoding="utf-8"))
RULES = {(c["condition"], c["event"]): c["model_json"] for c in SNAPSHOT["cases"]}
AID = "e2e"
FRAME_RATE = 30.0
SAMPLING_HZ = 0.5
STEP = 60          # frames between two kept frames: 30 fps / 0.5 Hz
GAP = 60           # merge gap: 2 s of a 30 fps video
SEEN_AT = (0, 60, 240)
"""Kept frames where the VLM sees a gun: 0 and 60 are 2 s apart (one interval), 240 is 6 s later."""


@pytest.fixture
def db_path(tmp_path) -> Path:
    path = tmp_path / "analysis.db"
    conn, _ = setup_database(path)
    for key, value in SNAPSHOT["app_config"].items():
        conn.execute("INSERT INTO AppConfig (key, value_json) VALUES (?, ?)", (key, json.dumps(value)))
    for (condition, event), model_json in RULES.items():
        conn.execute("INSERT INTO EventSpec (id, condition, model_json) VALUES (?, ?, ?)",
                     (event, condition, model_json))
    # the row AnalysisStartController writes: ffprobe's frame rate, the requested sampling in Hz
    conn.execute("INSERT INTO Analyses (ID, VideoPath, VideoFilename, Condition, FrameRate, SamplingRate, Stage, "
                 "CreatedAt) VALUES (?, 'v.mp4', 'v.mp4', 'A', ?, ?, 'done', '2026-01-01T00:00:00')",
                 (AID, FRAME_RATE, SAMPLING_HZ))
    # what the VLM writes on the kept frames
    for frame in range(0, 300, frame_step_for(FRAME_RATE, SAMPLING_HZ)):
        conn.execute("INSERT INTO VisualPerFrame (AnalysisID, Frame, ClassID, Class, Block, Description) "
                     "VALUES (?, ?, 1, 'person', 1, 'a person')", (AID, frame))
        if frame in SEEN_AT:
            conn.execute("INSERT INTO VisualRelation (AnalysisID, Frame, RelationID, RelationType, ClassID) "
                         "VALUES (?, ?, 1, 'gunshot_visible', 1)", (AID, frame))
    conn.commit()
    # the end of VisualServiceImpl.run_pipeline, with what the analysis passes
    list(IntervalServiceImpl().build_visual_and_save(
        conn, STEP, analysis_id=AID, log_fn=lambda _: None, merge_gap_frames=merge_gap_frames_for(FRAME_RATE)))
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def conn(db_path):
    c = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    yield c
    c.close()


def test_the_analysis_keeps_one_frame_every_two_seconds_and_merges_within_two_seconds():
    assert frame_step_for(FRAME_RATE, SAMPLING_HZ) == STEP
    assert merge_gap_frames_for(FRAME_RATE) == GAP
    assert MERGE_GAP_SECONDS == GAP / FRAME_RATE


def test_the_kept_frames_become_intervals_with_the_merge_gap(conn):
    rows = conn.execute("SELECT StartFrame, EndFrame, RelationType FROM VisualPerInterval "
                        "WHERE AnalysisID = ? ORDER BY StartFrame", (AID,)).fetchall()
    assert [tuple(r) for r in rows] == [(0, 60, "gunshot_visible"), (240, 240, "gunshot_visible")]


def test_detection_shows_video_time(conn):
    result = EventsServiceImpl().detect(conn, analysis_id=AID, event_type="gunshot_or_explosion", condition="A")

    assert result.frame_rate == FRAME_RATE
    shown = [(r.gui["M1.st"], r.gui["M1.et"], r.gui["M1.sf"], r.gui["M1.ef"]) for r in result.rows]
    assert shown == [
        (format_time(0 / FRAME_RATE), format_time(60 / FRAME_RATE), 0, 60),      # 0-2 s
        (format_time(240 / FRAME_RATE), format_time(240 / FRAME_RATE), 240, 240),  # 8 s
    ]
    assert shown[0][:2] == ("00:00:00.000", "00:00:02.000")


def test_parameters_in_seconds_become_frames_of_the_video(conn):
    result = EventsServiceImpl().detect(conn, analysis_id=AID, event_type="vehicle_escape", condition="A")

    numeric = {k: v for k, v in result.params.written.items()
               if isinstance(v, (int, float)) and not isinstance(v, bool)}
    assert numeric
    assert all(result.params.converted[k] == round(v * FRAME_RATE) for k, v in numeric.items())


def test_the_gui_path_reads_the_run_and_shows_the_same_rows(db_path, monkeypatch):
    # The backend CI installs neither (ci.yml); the xai CI runs this path in its own end-to-end test.
    pytest.importorskip("fastapi")
    pytest.importorskip("yaml")
    from service.impl.analysis_service_impl import AnalysisServiceImpl
    from utils.config import Config

    monkeypatch.setitem(Config.get().data, "db_path", str(db_path))
    service = AnalysisServiceImpl()

    run = service.get_run(AID)
    assert (run.frame_rate, run.sampling_rate) == (FRAME_RATE, SAMPLING_HZ)

    c = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    try:
        values, _, _ = default_params(c)
        direct = EventsServiceImpl().detect(c, analysis_id=AID, event_type="gunshot_or_explosion", condition="A")
    finally:
        c.close()
    gui = service.detect_event(analysis_id=AID, event_type="gunshot_or_explosion", condition="A",
                               deltas=dict(values), unit="seconds")["rows"]
    assert gui == [r.gui for r in direct.rows] and len(gui) == 2
