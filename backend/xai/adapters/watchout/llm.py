"""``LanguageModel`` on WatchOut's ``VLMClient``: the same providers and keys as the VLM (S2).

The key is read by ``VLMClient`` from the provider's environment variable (``GOOGLE_API_KEY``
for gemini), never from a file of xai. A client that cannot be built (no key, unknown provider,
package missing) or a call that fails is ``LlmUnavailable``: no report is written (S9).

A call refused for a while (429 over the quota per minute, 503 high demand, 529 Anthropic
overloaded) is made again after a wait, the one the provider asks for when it says it. The HTTP
status is ``code`` in Google's errors and ``status_code`` in those of the other providers.
"""

import logging
import re
import time
from collections.abc import Callable, Sequence
from typing import Any, Protocol

from xai.contract.report import LlmSettings
from xai.reporting.catalogue import LlmConfig
from xai.reporting.ports import LlmUnavailable

log = logging.getLogger("xai.adapters.watchout.llm")

TRANSIENT_CODES = frozenset({429, 500, 503, 504, 529})
WAITS_S: tuple[float, ...] = (10.0, 30.0, 60.0)
"""The waits before each new call after a transient error; then the LLM is unavailable."""
RETRY_HINT = re.compile(r"retry in ([0-9]+(?:\.[0-9]+)?)s")


class ChatClient(Protocol):
    def chat(self, prompt: str) -> Any: ...


def new_client(config: LlmConfig) -> ChatClient:
    """WatchOut's client for the configured provider and model."""
    try:
        from utils.vlm_client import VLMClient

        client: ChatClient = VLMClient(
            provider=config.provider,
            model=config.model,
            max_tokens=config.max_tokens,
            temperature=config.temperature,
            seed=config.seed,
            timeout=config.timeout_s,
        )
    except (ValueError, ImportError) as error:
        raise LlmUnavailable(f"{config.provider}/{config.model} is not configured: {error}") from error
    return client


class WatchOutLanguageModel:
    """Satisfies ``xai.reporting.ports.LanguageModel``."""

    def __init__(
        self,
        config: LlmConfig,
        client: ChatClient | None = None,
        *,
        waits: Sequence[float] = WAITS_S,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._settings = LlmSettings(
            provider=config.provider, model=config.model, temperature=config.temperature, seed=config.seed
        )
        self._client = client if client is not None else new_client(config)
        self._waits = tuple(waits)
        self._sleep = sleep

    @property
    def settings(self) -> LlmSettings:
        return self._settings

    def complete(self, prompt: str) -> str:
        name = f"{self._settings.provider}/{self._settings.model}"
        answer = self._answer(prompt, name)
        if not isinstance(answer, str) or not answer.strip():
            raise LlmUnavailable(f"{name} answered nothing")
        return answer

    def _answer(self, prompt: str, name: str) -> Any:
        waits = list(self._waits)
        while True:
            try:
                return self._client.chat(prompt)
            except Exception as error:
                code = _status(error)
                if not waits or code not in TRANSIENT_CODES:
                    raise LlmUnavailable(f"{name}: {error}") from error
                hint = RETRY_HINT.search(str(error))
                delay = max(waits.pop(0), float(hint.group(1)) if hint is not None else 0.0)
                log.warning("%s answered %s: calling again in %.0f s", name, code, delay)
                self._sleep(delay)


def _status(error: Exception) -> int | None:
    """The HTTP status of a failed call, or ``None``; OpenAI's ``code`` is a text, not a status."""
    for field in ("status_code", "code"):
        value = getattr(error, field, None)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None
