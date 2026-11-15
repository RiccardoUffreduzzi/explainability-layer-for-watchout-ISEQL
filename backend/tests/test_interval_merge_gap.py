from __future__ import annotations

from service.impl.interval_service_impl import IntervalServiceImpl
from utils.database import setup_database


def _seed_relation_points(conn, frames: list[int]) -> None:
    for frame in frames:
        conn.execute(
            "INSERT INTO VisualPerFrame "
            "(AnalysisID, Frame, ClassID, Class, Block, Description) "
            "VALUES ('pilot', ?, 1, 'person', 1, 'person')",
            (frame,),
        )
        conn.execute(
            "INSERT INTO VisualRelation "
            "(AnalysisID, Frame, RelationID, RelationType, ClassID) "
            "VALUES ('pilot', ?, 1, 'running', 1)",
            (frame,),
        )
    conn.commit()


def test_explicit_merge_gap_is_independent_of_sampling_stride(tmp_path) -> None:
    conn, _ = setup_database(tmp_path / "pilot.db")
    _seed_relation_points(conn, [0, 48])

    list(
        IntervalServiceImpl().build_visual_and_save(
            conn,
            sampling_rate=6,
            analysis_id="pilot",
            merge_gap_frames=48,
        )
    )

    rows = conn.execute(
        "SELECT StartFrame, EndFrame FROM VisualPerInterval WHERE AnalysisID = 'pilot'"
    ).fetchall()
    assert [tuple(row) for row in rows] == [(0, 48)]
    conn.close()


def test_legacy_merge_rule_is_unchanged_without_override(tmp_path) -> None:
    conn, _ = setup_database(tmp_path / "legacy.db")
    _seed_relation_points(conn, [0, 48])

    list(
        IntervalServiceImpl().build_visual_and_save(
            conn,
            sampling_rate=24,
            analysis_id="pilot",
        )
    )

    rows = conn.execute(
        "SELECT StartFrame, EndFrame FROM VisualPerInterval WHERE AnalysisID = 'pilot'"
    ).fetchall()
    assert [tuple(row) for row in rows] == [(0, 48)]
    conn.close()
