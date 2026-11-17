"""An LLM that answers with recorded answers: for the tests, the examples and a rerun offline.

Answers are found by the prompt they were given: a trace of K5 or K6 records both, so a report
can be made again exactly as it was. A prompt without a recorded answer is ``LlmUnavailable``.
"""

import hashlib
from collections.abc import Iterable, Mapping
from pathlib import Path

from xai.contract.report import LlmSettings, load_trace
from xai.reporting.ports import LlmUnavailable

REPLAY_SETTINGS = LlmSettings(provider="replay", model="recorded-answers", temperature=0.0, seed=None)


def prompt_key(prompt: str) -> str:
    return hashlib.sha256(prompt.replace("\r\n", "\n").encode("utf-8")).hexdigest()


class ReplayLanguageModel:
    def __init__(self, answers: Mapping[str, str], settings: LlmSettings = REPLAY_SETTINGS) -> None:
        self._answers = {prompt_key(prompt): answer for prompt, answer in answers.items()}
        self._settings = settings

    @classmethod
    def from_traces(cls, paths: Iterable[Path]) -> "ReplayLanguageModel":
        """Every prompt of the traces with its answer; the settings are those of the last trace."""
        answers: dict[str, str] = {}
        settings = REPLAY_SETTINGS
        for path in paths:
            trace = load_trace(path.read_text(encoding="utf-8"))
            settings = trace.llm
            for call in trace.calls:
                if call.answer is not None:
                    answers[call.prompt] = call.answer
        return cls(answers, settings)

    @property
    def settings(self) -> LlmSettings:
        return self._settings

    def complete(self, prompt: str) -> str:
        answer = self._answers.get(prompt_key(prompt))
        if answer is None:
            raise LlmUnavailable("no recorded answer for this prompt")
        return answer
