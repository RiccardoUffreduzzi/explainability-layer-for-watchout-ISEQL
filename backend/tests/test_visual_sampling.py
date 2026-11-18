import pytest
from pydantic import ValidationError

from models.analysis import AnalysisStartRequest, frame_step_for


@pytest.mark.parametrize(
    ("frame_rate", "sampling_rate", "expected_step"),
    [
        (24.0, 0.5, 48),
        (24.0, 1.0, 24),
        (24.0, 2.0, 12),
        (25.0, 2.0, 13),
        (29.97, 0.5, 60),
        (29.97, 1.0, 30),
        (29.97, 2.0, 15),
        (1.0, 2.0, 1),
    ],
)
def test_frame_step_for_supported_sampling_rates(frame_rate, sampling_rate, expected_step):
    assert frame_step_for(frame_rate, sampling_rate) == expected_step


@pytest.mark.parametrize("sampling_rate", [0, 0.25, 4])
def test_frame_step_rejects_unsupported_sampling_rates(sampling_rate):
    with pytest.raises(ValueError, match="sampling_rate"):
        frame_step_for(24.0, sampling_rate)


@pytest.mark.parametrize("sampling_rate", [0.5, 1, 2])
def test_analysis_start_model_accepts_supported_sampling_rates(sampling_rate):
    assert AnalysisStartRequest(sampling_rate=sampling_rate).sampling_rate == sampling_rate


def test_analysis_start_model_rejects_four_hz():
    with pytest.raises(ValidationError):
        AnalysisStartRequest(sampling_rate=4)
