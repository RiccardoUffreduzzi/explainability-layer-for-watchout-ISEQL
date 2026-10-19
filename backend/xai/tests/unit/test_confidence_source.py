"""Source of an audio confidence: the audio model, or WatchOut's code when the value is fixed."""

from xai.adapters.resource_files import load_pipeline_constants
from xai.contract.primitives import SourceRef, Stage
from xai.k1_harvester.evidence import confidence_source
from xai.k1_harvester.ports import AudioIntervalRow

CONSTANTS = load_pipeline_constants()
FIXED = CONSTANTS.constant_audio_confidence


def _row(confidence: float | None) -> AudioIntervalRow:
    return AudioIntervalRow(
        interval_id=21, start_frame=0, end_frame=120, audio_class="horn", confidence=confidence
    )


def test_the_fixed_value_of_the_provider_comes_from_the_code() -> None:
    sources = confidence_source(CONSTANTS, FIXED.providers[0], _row(FIXED.value))

    assert sources == {
        "confidence": SourceRef(
            stage=Stage.CODE, store=CONSTANTS.store, record_id="constant_audio_confidence", mode="read"
        )
    }


def test_another_provider_keeps_the_audio_row_as_the_only_source() -> None:
    assert confidence_source(CONSTANTS, "panns", _row(FIXED.value)) is None
    assert confidence_source(CONSTANTS, None, _row(FIXED.value)) is None


def test_a_value_other_than_the_fixed_one_comes_from_the_model() -> None:
    assert confidence_source(CONSTANTS, FIXED.providers[0], _row(0.42)) is None
    assert confidence_source(CONSTANTS, FIXED.providers[0], _row(None)) is None
