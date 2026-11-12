"""Source of an audio confidence: the audio model, or WatchOut's code when the value is fixed."""

from xai.contract.primitives import SourceRef, Stage
from xai.k1_harvester.evidence import confidence_source
from xai.k1_harvester.ports import AudioIntervalRow

FIXED = 1.0
"""The value a provider with no score writes, as ``AudioServiceImpl.constant_confidence`` gives it."""


def _row(confidence: float | None) -> AudioIntervalRow:
    return AudioIntervalRow(
        interval_id=21, start_frame=0, end_frame=120, audio_class="horn", confidence=confidence
    )


def test_the_fixed_value_of_the_provider_comes_from_the_code() -> None:
    sources = confidence_source(FIXED, "huggingface", _row(FIXED))

    assert sources == {
        "confidence": SourceRef(
            stage=Stage.CODE, record_id="AudioServiceImpl.constant_confidence(huggingface)", mode="read"
        )
    }


def test_a_provider_with_scores_keeps_the_audio_row_as_the_only_source() -> None:
    assert confidence_source(None, "panns", _row(FIXED)) is None
    assert confidence_source(None, None, _row(FIXED)) is None


def test_a_value_other_than_the_fixed_one_comes_from_the_model() -> None:
    assert confidence_source(FIXED, "huggingface", _row(0.42)) is None
    assert confidence_source(FIXED, "huggingface", _row(None)) is None
