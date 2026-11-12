"""Which ``VisualPerFrame`` row becomes the description of an entity, and the record made of it."""

from collections.abc import Sequence
from types import SimpleNamespace
from typing import cast

from xai.contract.primitives import SourceRef, Stage
from xai.contract.reasons import Reason
from xai.k1_harvester.context import HarvestContext
from xai.k1_harvester.descriptions import Window, choose_description
from xai.k1_harvester.evidence import EvidenceHarvester, Participant, describe_entity
from xai.k1_harvester.ports import FrameDescriptionRow
from xai.k1_harvester.timebase import TimeBase

S21 = "gemini_3_6_flash_qwen2_audio_s21"


def _row(
    frame: int, block: int = 1, text: str = "man in a blue jacket", class_id: int = 3
) -> FrameDescriptionRow:
    return FrameDescriptionRow(frame=frame, class_id=class_id, block=block, description=text)


# ----------------------------------------------------------------------------- the row


def test_the_first_frame_inside_a_window_is_chosen() -> None:
    rows = [_row(0), _row(24), _row(48), _row(120)]

    chosen = choose_description(rows, [Window(24, 96)], reference_frame=0)

    assert chosen is not None
    assert (chosen.row.frame, chosen.in_evidence) == (24, True)


def test_both_ends_of_a_window_are_inside() -> None:
    start = choose_description([_row(24)], [Window(24, 96)], None)
    end = choose_description([_row(96)], [Window(24, 96)], None)

    assert start is not None and start.in_evidence
    assert end is not None and end.in_evidence


def test_in_the_same_frame_the_lowest_block_is_chosen() -> None:
    rows = [_row(24, block=6), _row(24, block=2), _row(24, block=5)]

    chosen = choose_description(rows, [Window(24, 96)], None)

    assert chosen is not None
    assert (chosen.row.frame, chosen.row.block) == (24, 2)


def test_with_several_windows_the_lowest_frame_in_any_of_them_is_chosen() -> None:
    rows = [_row(0), _row(100), _row(130), _row(200)]

    chosen = choose_description(rows, [Window(120, 192), Window(190, 240)], None)

    assert chosen is not None
    assert (chosen.row.frame, chosen.in_evidence) == (130, True)


def test_a_row_in_a_later_window_wins_over_a_nearer_row_outside() -> None:
    rows = [_row(22), _row(200)]

    chosen = choose_description(rows, [Window(24, 48), Window(192, 240)], None)

    assert chosen is not None
    assert (chosen.row.frame, chosen.in_evidence) == (200, True)


def test_without_a_row_inside_the_nearest_to_the_first_window_is_chosen() -> None:
    rows = [_row(0), _row(72), _row(240)]

    chosen = choose_description(rows, [Window(96, 120), Window(300, 320)], reference_frame=0)

    assert chosen is not None
    assert (chosen.row.frame, chosen.in_evidence) == (72, False)


def test_at_the_same_distance_the_older_frame_then_the_lowest_block() -> None:
    rows = [_row(120, block=1), _row(72, block=7), _row(72, block=4)]

    chosen = choose_description(rows, [Window(96, 96)], None)

    assert chosen is not None
    assert (chosen.row.frame, chosen.row.block, chosen.in_evidence) == (72, 4, False)


def test_an_entity_without_windows_is_measured_from_the_reference_frame() -> None:
    rows = [_row(0), _row(144), _row(168)]

    chosen = choose_description(rows, [], reference_frame=150)

    assert chosen is not None
    assert (chosen.row.frame, chosen.in_evidence) == (144, False)


def test_without_windows_and_reference_the_first_row_is_chosen() -> None:
    rows = [_row(48, block=3), _row(24, block=5), _row(24, block=2)]

    chosen = choose_description(rows, [], reference_frame=None)

    assert chosen is not None
    assert (chosen.row.frame, chosen.row.block, chosen.in_evidence) == (24, 2, False)


def test_without_rows_there_is_no_description() -> None:
    assert choose_description([], [Window(24, 96)], reference_frame=24) is None


def test_the_row_is_returned_as_read() -> None:
    row = _row(24, text="man in dark blue hoodie carrying a box")

    chosen = choose_description([row], [Window(24, 96)], None)

    assert chosen is not None
    assert chosen.row is row


# ----------------------------------------------------------------------------- the record


def test_the_description_copies_the_row_and_points_to_it() -> None:
    rows = [_row(24, block=5, text="man in dark blue hoodie carrying a box"), _row(48)]

    description, missing = describe_entity(S21, TimeBase(24), 3, rows, [Window(24, 96)], None)

    assert missing == {}
    assert description is not None
    assert description.text == "man in dark blue hoodie carrying a box"
    assert description.in_evidence
    assert description.anchor.model_dump() == {
        "start_frame": 24,
        "end_frame": 24,
        "start_s": 1.0,
        "end_s": 1.0,
        "read_as": "frames",
    }
    assert description.source_ref == SourceRef(
        stage=Stage.VLM, record_id=f"VisualPerFrame/{S21}:24:3:5", mode="read"
    )


def test_a_description_outside_the_evidence_says_so() -> None:
    description, missing = describe_entity(S21, TimeBase(24), 3, [_row(0)], [Window(24, 96)], None)

    assert missing == {}
    assert description is not None
    assert (description.anchor.start_frame, description.in_evidence) == (0, False)


def test_an_entity_without_rows_has_no_description_and_a_reason() -> None:
    description, missing = describe_entity(S21, TimeBase(24), 7, [], [Window(24, 96)], 24)

    assert description is None
    assert list(missing) == ["vlm_description"]
    assert missing["vlm_description"].reason == Reason.ENTITY_NOT_DESCRIBED
    assert (
        missing["vlm_description"].detail == "VisualPerFrame has no description of ClassID 7 in this analysis"
    )


def test_without_fps_the_seconds_of_the_frame_are_null_with_their_reason() -> None:
    description, missing = describe_entity(S21, TimeBase(None), 3, [_row(24)], [Window(24, 96)], None)

    assert description is not None
    assert (description.anchor.start_frame, description.anchor.start_s, description.anchor.end_s) == (
        24,
        None,
        None,
    )
    assert sorted(missing) == ["vlm_description.anchor.end_s", "vlm_description.anchor.start_s"]
    assert {u.reason for u in missing.values()} == {Reason.FPS_NOT_RECORDED}


# ----------------------------------------------------------------------------- the entities


class _Records:
    """The only read ``_entities`` makes: the ``VisualPerFrame`` rows of the entities."""

    def __init__(self, rows: Sequence[FrameDescriptionRow]) -> None:
        self.rows = list(rows)
        self.calls: list[tuple[str, list[int]]] = []

    def frame_descriptions(self, analysis_id: str, class_ids: Sequence[int]) -> list[FrameDescriptionRow]:
        self.calls.append((analysis_id, list(class_ids)))
        return [r for r in self.rows if r.class_id in class_ids]


def _context(records: _Records) -> HarvestContext:
    stub = SimpleNamespace(
        records=records,
        analysis=SimpleNamespace(analysis_id=S21),
        timebase=TimeBase(24),
        detection=SimpleNamespace(record=f"detection/handoff/A@{S21}"),
        row=SimpleNamespace(values={"M1_person": 3, "M1.st": 1.0}),
    )
    return cast(HarvestContext, stub)


def test_the_entities_are_described_with_one_read() -> None:
    records = _Records([_row(24, class_id=3), _row(48, class_id=4, text="cardboard box")])
    participants = [Participant(59, 3, "person"), Participant(59, 4, "object")]
    windows = {3: [Window(24, 96)], 4: [Window(24, 96)]}

    entities = EvidenceHarvester._entities(_context(records), {3: "person"}, participants, windows, 24)

    assert records.calls == [(S21, [3, 4])]
    assert [(e.entity_id, e.vlm_description.text if e.vlm_description else None) for e in entities] == [
        ("ent_3", "man in a blue jacket"),
        ("ent_4", "cardboard box"),
    ]
    assert all(sorted(e.unavailable or {}) == ["reid_evidence"] for e in entities)


def test_an_entity_only_in_the_row_is_measured_from_the_start_of_the_event() -> None:
    records = _Records([_row(0, class_id=9), _row(144, class_id=9, text="white van"), _row(240, class_id=9)])

    [entity] = EvidenceHarvester._entities(_context(records), {9: "vehicle"}, [], {}, 150)

    assert entity.source_ref.record_id.startswith(f"detection/handoff/A@{S21}/")
    assert entity.vlm_description is not None
    assert (entity.vlm_description.text, entity.vlm_description.in_evidence) == ("white van", False)
    assert entity.vlm_description.anchor.start_frame == 144


def test_an_entity_the_vlm_never_described_keeps_both_reasons() -> None:
    records = _Records([])

    [entity] = EvidenceHarvester._entities(
        _context(records), {}, [Participant(59, 3, "unknown")], {3: [Window(24, 96)]}, 24
    )

    assert entity.vlm_description is None
    assert entity.unavailable is not None
    assert sorted(entity.unavailable) == ["reid_evidence", "vlm_description"]
    assert entity.unavailable["vlm_description"].reason == Reason.ENTITY_NOT_DESCRIBED


def test_without_entities_nothing_is_read() -> None:
    records = _Records([_row(24)])

    assert EvidenceHarvester._entities(_context(records), {}, [], {}, None) == []
    assert records.calls == []
