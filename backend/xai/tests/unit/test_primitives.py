import pytest
from pydantic import ValidationError

from xai.contract import Anchor, Fact, Reading, Reason, SourceRef, Stage, Unavailable
from xai.contract.primitives import DerivedSource, RequestSource
from xai.tests.support import from_json_data


def test_source_ref_stages_include_config_and_code() -> None:
    stages = {s.value for s in Stage}

    assert stages == {"sampling", "vlm", "reid", "Λ", "iad", "audio", "iseql", "keyframes", "config", "code"}


def test_source_ref_rejects_an_unknown_stage() -> None:
    with pytest.raises(ValidationError, match="stage"):
        from_json_data(SourceRef, {"stage": "gui", "store": "x", "record_id": "1", "mode": "read"})


def test_source_ref_needs_store_and_record() -> None:
    with pytest.raises(ValidationError):
        from_json_data(SourceRef, {"stage": "iad", "store": "", "record_id": "1", "mode": "read"})


def test_unavailable_needs_a_catalog_reason_and_a_detail() -> None:
    ok = Unavailable(reason=Reason.FPS_NOT_RECORDED, detail="SamplingRate is 0")

    assert ok.model_dump(mode="json") == {"reason": "fps_not_recorded", "detail": "SamplingRate is 0"}
    with pytest.raises(ValidationError):
        from_json_data(Unavailable, {"reason": "fps_not_recorded", "detail": ""})


def test_anchor_read_as_frames_needs_frames() -> None:
    with pytest.raises(ValidationError, match="read_as='frames'"):
        Anchor(start_frame=None, end_frame=96, start_s=1.0, end_s=4.0, read_as="frames")


def test_anchor_without_fps_keeps_only_the_read_pair() -> None:
    anchor = Anchor(start_frame=24, end_frame=96, start_s=None, end_s=None, read_as="frames")

    assert anchor.model_dump(mode="json") == {
        "start_frame": 24,
        "end_frame": 96,
        "start_s": None,
        "end_s": None,
        "read_as": "frames",
    }


def test_sources_union_keeps_each_shape() -> None:
    derived = DerivedSource(derived_from=["sampling.source_fps", "sampling.sample_every_n"])
    request = RequestSource(from_request="condition", value="A")

    assert derived.model_dump() == {"derived_from": ["sampling.source_fps", "sampling.sample_every_n"]}
    assert request.model_dump() == {"from_request": "condition", "value": "A"}
    with pytest.raises(ValidationError):
        DerivedSource(derived_from=[])


def _describe(reading: Reading[int]) -> str:
    if isinstance(reading, Unavailable):
        return f"null because {reading.reason.value}"
    return f"{reading.value} from {reading.source.model_dump()}"


def test_reading_is_a_fact_or_the_reason_it_is_missing() -> None:
    ref = SourceRef(stage=Stage.CONFIG, store="Analyses:a1", record_id="SamplingRate", mode="read")

    assert _describe(Fact(value=24, source=ref)).startswith("24 from {'stage': <Stage.CONFIG")
    assert _describe(Unavailable(reason=Reason.FPS_NOT_RECORDED, detail="0")) == (
        "null because fps_not_recorded"
    )
