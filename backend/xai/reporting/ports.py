"""how the core of the reports sees an LLM.

An adapter satisfies this port (``xai.adapters.watchout.llm`` on WatchOut's ``VLMClient``,
``xai.adapters.llm_replay`` on recorded answers).
"""

from typing import Protocol

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
