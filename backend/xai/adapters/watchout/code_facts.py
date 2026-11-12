"""``CodeFacts`` port over WatchOut's reading methods.

Each value is the one WatchOut's code uses, returned by the method next to it.
"""

from service.impl.audio_service_impl import AudioServiceImpl
from service.impl.interval_service_impl import IntervalServiceImpl
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

    def merge_tolerance_samples(self) -> int:
        samples: int = IntervalServiceImpl.merge_tolerance_samples()
        return samples

    def constant_audio_confidence(self, provider: str) -> float | None:
        confidence: float | None = AudioServiceImpl.constant_confidence(provider)
        return confidence
