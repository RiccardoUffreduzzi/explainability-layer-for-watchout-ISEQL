"""how the core of the reports sees an LLM and the frames of the video.

Adapters satisfy these ports: ``xai.adapters.watchout.llm`` on WatchOut's ``VLMClient`` and
``xai.adapters.llm_replay`` on recorded answers for ``LanguageModel``;
``xai.adapters.watchout.frames`` on WatchOut's ``extract_frame_jpeg`` for ``FrameImages``.
"""

from typing import Protocol

from xai.contract.model import KeyFrame
from xai.contract.report import LlmSettings


class LlmUnavailable(Exception):
    """The LLM is not configured, cannot be reached or gave no answer."""


class LanguageModel(Protocol):
    @property
    def settings(self) -> LlmSettings:
        """Provider, model, temperature and seed"""
        ...

    def complete(self, prompt: str) -> str:
        """The answer to one prompt; ``LlmUnavailable`` when there is none."""
        ...


class FrameUnavailable(Exception):
    """The image of a key frame cannot be extracted"""


class FrameImages(Protocol):
    def image(self, key_frame: KeyFrame) -> bytes:
        """The JPEG of the key frame, ``FrameUnavailable`` when there is none."""
        ...
