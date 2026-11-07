"""K2's modality check, on the example drafts of ``tests/data``."""

from typing import Any

import pytest

from xai.contract import Anchor, ContractDraft
from xai.contract.source_of_truth import Reinforcement
from xai.k2.modality_check import modality_check, overlaps
from xai.k2.stage import K2Stage
from xai.pipeline.runner import ReportStage
from xai.tests.support import EXAMPLES_DIR, from_json_data, load_example

_MULTIMODAL = "vehicle_collision_s15_C_audio.bozza.json"


def _data(name: str) -> dict[str, Any]:
    return load_example(EXAMPLES_DIR / name)


def _draft(name: str) -> ContractDraft:
    return from_json_data(ContractDraft, _data(name))


def _frames(start: int | None, end: int | None) -> Anchor:
    return Anchor(start_frame=start, end_frame=end, start_s=None, end_s=None, read_as="frames")


def _outcome(data: dict[str, Any]) -> Reinforcement | None:
    return modality_check(from_json_data(ContractDraft, data))


def _only(modality: str) -> dict[str, Any]:
    data = _data(_MULTIMODAL)
    detections = data["event"]["modality_detections"]
    data["event"]["modality_detections"] = [d for d in detections if d["modality"] == modality]
    return data


def test_a_multimodal_draft_with_overlapping_detections() -> None:
    # Audio 0-180 against video 120-120 and 144-240 (document 05, example 2).
    assert modality_check(_draft(_MULTIMODAL)) is Reinforcement.BOTH_OVERLAPPING


def test_a_visual_only_draft_says_nothing() -> None:
    assert modality_check(_draft("handoff_s21_A.bozza.json")) is None


def test_no_audio_rule_says_nothing_even_if_multimodal() -> None:
    data = _data(_MULTIMODAL)
    data["event"]["modality_rules"]["audio"] = None

    assert _outcome(data) is None


def test_detections_in_one_modality_only() -> None:
    assert _outcome(_only("visual")) is Reinforcement.VISUAL_ONLY
    assert _outcome(_only("audio")) is Reinforcement.AUDIO_ONLY


def test_no_detections_at_all_says_nothing() -> None:
    data = _data(_MULTIMODAL)
    data["event"]["modality_detections"] = []

    assert _outcome(data) is None


def test_both_modalities_but_no_overlap() -> None:
    data = _data(_MULTIMODAL)
    for detection in data["event"]["modality_detections"]:
        if detection["modality"] == "audio":
            detection["interval"].update(start_frame=0, end_frame=100, start_s=0.0, end_s=100 / 24)
        else:
            detection["interval"].update(start_frame=200, end_frame=240, start_s=200 / 24, end_s=240 / 24)

    assert _outcome(data) is Reinforcement.BOTH_NOT_OVERLAPPING


def test_not_comparable_when_a_frame_is_missing() -> None:
    data = _data(_MULTIMODAL)
    for detection in data["event"]["modality_detections"]:
        if detection["modality"] == "audio":
            detection["interval"] = {
                "start_frame": None,
                "end_frame": None,
                "start_s": 0.0,
                "end_s": 7.5,
                "read_as": "seconds",
            }
        else:
            detection["interval"].update(start_frame=200, end_frame=240, start_s=200 / 24, end_s=240 / 24)

    assert _outcome(data) is Reinforcement.NOT_COMPARABLE


def test_overlap_in_whole_frames() -> None:
    assert overlaps(_frames(0, 180), _frames(144, 240)) is True
    assert overlaps(_frames(0, 180), _frames(120, 120)) is True  # a one-frame span inside
    assert overlaps(_frames(0, 100), _frames(101, 200)) is False
    # Sharing one frame counts (ISEQL+ Before, gap 0).
    assert overlaps(_frames(0, 100), _frames(100, 200)) is True


def test_no_comparison_when_a_frame_is_missing() -> None:
    seconds_only = Anchor(start_frame=None, end_frame=None, start_s=0.0, end_s=7.5, read_as="seconds")

    assert overlaps(seconds_only, _frames(0, 180)) is None


def test_the_stage_satisfies_the_pipeline_protocol() -> None:
    stage: ReportStage = K2Stage()

    assert stage.name == "k2"


@pytest.mark.parametrize("outcome", list(Reinforcement))
def test_every_outcome_has_a_value_in_snake_case(outcome: Reinforcement) -> None:
    assert outcome.value == outcome.name.lower()
