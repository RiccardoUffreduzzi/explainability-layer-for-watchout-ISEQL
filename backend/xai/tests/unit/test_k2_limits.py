"""K2's limits of knowledge, on the example drafts of ``tests/data``."""

from xai.contract import ContractDraft
from xai.contract.source_of_truth import LimitCode
from xai.k2.limits import detect_limits
from xai.tests.support import EXAMPLES_DIR, from_json_data, load_example


def _limits(name: str) -> list[str]:
    draft = from_json_data(ContractDraft, load_example(EXAMPLES_DIR / name))
    return [code.value for code in detect_limits(draft)]


def test_a_visual_draft_with_identity_nodes() -> None:
    assert _limits("fight_s5_A.bozza.json") == [
        "visual_confidence_unavailable",
        "perceptual_attribution_unavailable",
        "temporal_resolution",
        "reid_dependence",
        "reid_evidence_unavailable",
        "data_not_available",
    ]


def test_a_visual_draft_without_identity_nodes_has_no_reid_limits() -> None:
    limits = _limits("gunshot_or_explosion_s7_A.bozza.json")

    assert "reid_dependence" not in limits
    assert "reid_evidence_unavailable" not in limits


def test_an_audio_origin_draft() -> None:
    limits = _limits("vehicle_collision_s15_C_audio.bozza.json")

    assert "audio_without_participants" in limits
    assert "visual_confidence_unavailable" not in limits  # only audio intervals
    assert "perceptual_attribution_unavailable" not in limits


def test_undefined_glossary_terms_are_a_limit() -> None:
    assert "glossary_entry_missing" in _limits("vehicle_collision_s15_C_visual.bozza.json")
    assert "glossary_entry_missing" not in _limits("fight_s5_A.bozza.json")


def test_no_key_frame_limit_while_actions_is_null() -> None:
    assert "keyframe_selection_undocumented" not in _limits("handoff_s21_A.bozza.json")


def test_the_limits_come_in_catalogue_order_without_repeats() -> None:
    catalogue = [code.value for code in LimitCode]
    for name in ("fight_s5_A.bozza.json", "vehicle_collision_s15_C_audio.bozza.json"):
        limits = _limits(name)

        assert len(limits) == len(set(limits))
        assert limits == sorted(limits, key=catalogue.index)
