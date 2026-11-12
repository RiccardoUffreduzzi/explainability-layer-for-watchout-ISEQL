"""The VLM description of the entities, read from ``VisualPerFrame`` of the test database.

The reader's rows first, then drafts of the handoff of scene 21 on copies of the database
where rows are removed: K1 never stops for a missing description.
"""

import json
import sqlite3
from pathlib import Path
from typing import Any

from xai.adapters.watchout.reader import SqliteWatchOutReader
from xai.contract.model import ContractDraft, Entity
from xai.contract.reasons import Reason
from xai.k1_harvester.ports import FrameDescriptionRow
from xai.tests.harness import GOLDEN_CASES, make_stage, open_reader
from xai.tests.support import FIXTURE_PATH, scene

HANDOFF = GOLDEN_CASES[0]
assert HANDOFF.name == "handoff_s21_A"
S21 = scene(21)


def _fixture_rows(analysis_id: str, class_ids: set[int]) -> list[FrameDescriptionRow]:
    rows = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["frame_descriptions"]
    found = [
        FrameDescriptionRow(frame=frame, class_id=class_id, block=block, description=text)
        for analysis, frame, class_id, _, block, text in rows
        if analysis == analysis_id and class_id in class_ids
    ]
    return sorted(found, key=lambda r: (r.class_id, r.frame, r.block))


def _change(db: Path, *statements: tuple[str, tuple[Any, ...]]) -> None:
    conn = sqlite3.connect(db)
    with conn:
        for sql, args in statements:
            conn.execute(sql, args)
    conn.close()


def _handoff_on(db: Path) -> ContractDraft:
    conn, reader = open_reader(db)
    try:
        return make_stage(reader).harvest(HANDOFF.request)
    finally:
        conn.close()


def _entity(draft: ContractDraft, entity_id: str) -> Entity:
    return next(e for e in draft.entities if e.entity_id == entity_id)


def _texts(draft: ContractDraft) -> dict[str, str | None]:
    return {e.entity_id: e.vlm_description.text if e.vlm_description else None for e in draft.entities}


# ----------------------------------------------------------------------------- the reader


def test_the_reader_gives_the_rows_of_the_subjects_in_order(reader: SqliteWatchOutReader) -> None:
    rows = reader.frame_descriptions(S21, [5, 3])

    assert rows == _fixture_rows(S21, {3, 5})
    assert len(rows) == 31
    assert rows[0] == FrameDescriptionRow(
        frame=24, class_id=3, block=1, description="man in dark blue hoodie carrying a box"
    )


def test_the_reader_keeps_to_the_analysis_and_the_subjects(reader: SqliteWatchOutReader) -> None:
    assert reader.frame_descriptions(S21, []) == []
    assert reader.frame_descriptions(S21, [999]) == []
    assert reader.frame_descriptions("no_such_analysis", [3]) == []
    assert {r.class_id for r in reader.frame_descriptions(S21, [4, 4])} == {4}


def test_rows_with_an_empty_description_are_not_read(watchout_db_copy: Path) -> None:
    # WatchOut writes '' when the VLM gives no description of a subject.
    _change(
        watchout_db_copy,
        (
            "UPDATE VisualPerFrame SET Description = ? WHERE AnalysisID = ? AND ClassID = 4 AND Frame = 24",
            ("  ", S21),
        ),
    )
    conn, reader = open_reader(watchout_db_copy)
    try:
        rows = reader.frame_descriptions(S21, [4])
    finally:
        conn.close()

    assert rows == [r for r in _fixture_rows(S21, {4}) if r.frame != 24]

    box = _entity(_handoff_on(watchout_db_copy), "ent_4").vlm_description
    assert box is not None
    assert (box.text, box.anchor.start_frame, box.in_evidence) == ("cardboard box", 48, True)


def test_without_the_table_the_reader_gives_no_rows(watchout_db_copy: Path) -> None:
    _change(watchout_db_copy, ("DROP TABLE VisualPerFrame", ()))
    conn, reader = open_reader(watchout_db_copy)
    try:
        assert reader.frame_descriptions(S21, [3, 4, 5]) == []
    finally:
        conn.close()


# ----------------------------------------------------------------------------- the drafts


def test_each_entity_has_the_description_of_its_first_frame_in_the_evidence(watchout_db: Path) -> None:
    draft = _handoff_on(watchout_db)

    assert _texts(draft) == {
        "ent_3": "man in dark blue hoodie carrying a box",
        "ent_4": "cardboard box",
        "ent_5": "man in grey jacket and dark trousers holding a box",
    }
    for entity in draft.entities:
        description = entity.vlm_description
        assert description is not None and description.in_evidence
        frame = description.anchor.start_frame
        windows = [i.anchor for i in draft.intervals if entity.entity_id in i.args]
        assert frame is not None
        assert frame == min(w.start_frame for w in windows if w.start_frame is not None)
        number = entity.entity_id.removeprefix("ent_")
        assert description.source_ref.record_id.startswith(f"VisualPerFrame/{S21}:{frame}:{number}:")


def test_without_a_row_in_the_evidence_the_nearest_one_is_copied(watchout_db_copy: Path) -> None:
    # ent_5 is in the interval of frames 120-192: without its rows there, the row of frame 96.
    _change(
        watchout_db_copy,
        (
            "DELETE FROM VisualPerFrame WHERE AnalysisID = ? AND ClassID = 5 AND Frame BETWEEN 120 AND 192",
            (S21,),
        ),
    )

    draft = _handoff_on(watchout_db_copy)

    description = _entity(draft, "ent_5").vlm_description
    assert description is not None
    assert (description.text, description.in_evidence) == ("man in grey jacket", False)
    assert description.anchor.start_frame == 96
    assert description.source_ref.record_id == f"VisualPerFrame/{S21}:96:5:3"
    assert all(check.passed for check in draft.harvest_report.checks)
    assert not [m for m in draft.harvest_report.missing_fields if "vlm_description" in m.path]


def test_an_entity_without_rows_has_a_null_description_and_a_reason(watchout_db_copy: Path) -> None:
    _change(watchout_db_copy, ("DELETE FROM VisualPerFrame WHERE AnalysisID = ? AND ClassID = 4", (S21,)))

    draft = _handoff_on(watchout_db_copy)

    assert _texts(draft) == {
        "ent_3": "man in dark blue hoodie carrying a box",
        "ent_4": None,
        "ent_5": "man in grey jacket and dark trousers holding a box",
    }
    box = _entity(draft, "ent_4")
    assert box.unavailable is not None
    assert box.unavailable["vlm_description"].reason == Reason.ENTITY_NOT_DESCRIBED
    assert "ClassID 4" in box.unavailable["vlm_description"].detail
    assert all(check.passed for check in draft.harvest_report.checks)
    assert [
        (m.path, m.reason) for m in draft.harvest_report.missing_fields if "vlm_description" in m.path
    ] == [("entities[*].vlm_description", Reason.ENTITY_NOT_DESCRIBED)]


def test_a_database_without_the_table_still_gives_the_draft(watchout_db_copy: Path) -> None:
    _change(watchout_db_copy, ("DROP TABLE VisualPerFrame", ()))

    draft = _handoff_on(watchout_db_copy)

    assert _texts(draft) == {"ent_3": None, "ent_4": None, "ent_5": None}
    for entity in draft.entities:
        assert entity.unavailable is not None
        assert entity.unavailable["vlm_description"].reason == Reason.ENTITY_NOT_DESCRIBED
    assert all(check.passed for check in draft.harvest_report.checks)
