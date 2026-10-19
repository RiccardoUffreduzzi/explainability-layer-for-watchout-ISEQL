import json
import re
from typing import Any

import pytest

from xai.contract import ids


def test_event_id_reproduces_the_examples(example: dict[str, Any]) -> None:
    # The ID is computed on the row as the engine returns it (event.source_ref), not as
    # the request wrote it: a row copied from the GUI gets the same ID.
    request = example["harvest_report"]["request"]
    row = json.loads(example["event"]["source_ref"]["record_id"])

    computed = ids.event_id(request["analysis_id"], request["event_type"], request["condition"], row)

    assert computed == example["event"]["event_id"]


def test_event_id_does_not_depend_on_column_order() -> None:
    a = ids.event_id("an1", "handoff", "A", {"M1_person": 3, "M1.st": 1.0})
    b = ids.event_id("an1", "handoff", "A", {"M1.st": 1.0, "M1_person": 3})

    assert a == b
    assert re.fullmatch(ids.EVENT_ID_PATTERN, a)


def test_event_id_changes_with_every_input() -> None:
    base = ids.event_id("an1", "handoff", "A", {"M1.st": 1.0})

    assert ids.event_id("an2", "handoff", "A", {"M1.st": 1.0}) != base
    assert ids.event_id("an1", "fight", "A", {"M1.st": 1.0}) != base
    assert ids.event_id("an1", "handoff", "C", {"M1.st": 1.0}) != base
    assert ids.event_id("an1", "handoff", "A", {"M1.st": 1.5}) != base
    assert ids.event_id("an1", "handoff", "A", {"M1.st": 1}) != base  # 1 and 1.0 are different rows


@pytest.mark.parametrize("bad", ["", "a|b"])
def test_event_id_rejects_names_that_would_be_ambiguous(bad: str) -> None:
    with pytest.raises(ValueError, match="analysis_id"):
        ids.event_id(bad, "handoff", "A", {})


def test_detection_row_reference_is_the_canonical_row(example: dict[str, Any]) -> None:
    row = example["harvest_report"]["request"]["row"]

    assert ids.canonical_row(row) == example["event"]["source_ref"]["record_id"]


def test_record_ids() -> None:
    assert ids.visual_interval_id(59) == "iv_v59"
    assert ids.audio_interval_id(21) == "iv_a21"
    assert ids.entity_id(3) == "ent_3"
    assert ids.projection_id("s1") == "c_s1_proj"
    assert ids.selection_id("s1", 2) == "c_s1_sel2"
    assert ids.operator_id("s1", 1) == "c_s1_op1"
    assert ids.cross_condition_id("s2", 1) == "c_s2_cc1"
    assert ids.set_operation_id(1) == "c_set1"
    assert ids.term_id("operator", "Bef") == "g_operator_Bef"
    assert ids.term_id("audio_class", "glass_breaking") == "g_audio_class_glass_breaking"


@pytest.mark.parametrize(
    "call",
    [
        lambda: ids.visual_interval_id(-1),
        lambda: ids.entity_id(True),
        lambda: ids.selection_id("s1", 0),
        lambda: ids.projection_id("s 1"),
        lambda: ids.term_id("predicate", "carrying!"),
        lambda: ids.term_id("predicate", "Λ"),
    ],
)
def test_record_ids_reject_bad_parts(call: Any) -> None:
    with pytest.raises(ValueError):
        call()


def test_example_ids_follow_the_patterns(example: dict[str, Any]) -> None:
    assert re.fullmatch(ids.EVENT_ID_PATTERN, example["event"]["event_id"])
    for interval in example["intervals"]:
        assert re.fullmatch(ids.INTERVAL_ID_PATTERN, interval["interval_id"])
    for entity in example["entities"]:
        assert re.fullmatch(ids.ENTITY_ID_PATTERN, entity["entity_id"])
    for node in example["rule"]["constraints"]:
        assert re.fullmatch(ids.CONSTRAINT_ID_PATTERN, node["constraint_id"])
    for entry in example["glossary"]:
        assert re.fullmatch(ids.TERM_ID_PATTERN, entry["term_id"])
