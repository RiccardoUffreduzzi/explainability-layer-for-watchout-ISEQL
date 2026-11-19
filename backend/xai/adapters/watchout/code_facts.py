"""``CodeFacts`` port over WatchOut's reading methods.

Each value is the one WatchOut's code uses, returned by the method next to it.
"""

from models.analysis import frame_step_for, merge_gap_frames_for
from service.impl.audio_service_impl import AudioServiceImpl
from utils.vlm_client import VLMClient

from xai.k1_harvester.ports import EngineError, VlmDefaults


class WatchOutCodeFacts:
    def vlm_defaults(self) -> VlmDefaults:
        defaults = VLMClient.generation_defaults()
        temperature, seed = defaults["temperature"], defaults["seed"]
        if isinstance(temperature, bool) or not isinstance(temperature, int | float):
            raise EngineError(f"VLMClient temperature is not a number: {temperature!r}")
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise EngineError(f"VLMClient seed is not an integer: {seed!r}")
        return VlmDefaults(temperature=float(temperature), seed=seed)

    def frame_step(self, frame_rate: float, sampling_hz: float) -> int:
        try:
            step: int = frame_step_for(frame_rate, sampling_hz)
        except ValueError as exc:
            raise EngineError(f"frame_step_for({frame_rate}, {sampling_hz}): {exc}") from exc
        return step

    def merge_gap_frames(self, frame_rate: float) -> int:
        try:
            frames: int = merge_gap_frames_for(frame_rate)
        except ValueError as exc:
            raise EngineError(f"merge_gap_frames_for({frame_rate}): {exc}") from exc
        return frames

    def constant_audio_confidence(self, provider: str) -> float | None:
        confidence: float | None = AudioServiceImpl.constant_confidence(provider)
        return confidence
