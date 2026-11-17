"""The resources of the reports and the adapter on WatchOut's ``VLMClient``."""

import re
from pathlib import Path

import pytest

from xai.adapters.report_resources import (
    REPORT_CONFIG_PATH,
    load_prompt,
    load_report_config,
    load_value_labels,
)
from xai.adapters.watchout.llm import WatchOutLanguageModel
from xai.k5_report1.profile import REPORT1
from xai.reporting.catalogue import LlmConfig
from xai.reporting.ports import LlmUnavailable
from xai.reporting.prompt import INPUT_SLOT, SECTIONS_SLOT, PromptTemplate, sections_text
from xai.tests.k5_support import input_of

GEMINI = LlmConfig(
    provider="gemini",
    model="gemini-3.5-flash-lite",
    temperature=0.0,
    seed=42,
    timeout_s=60.0,
    max_tokens=8192,
)


def test_the_configuration_names_the_model_and_never_a_key() -> None:
    config = load_report_config()

    assert config.llm is not None
    assert (config.llm.provider, config.llm.temperature, config.llm.seed) == ("gemini", 0.0, 42)
    assert (config.max_attempts, config.time_format, config.llm.timeout_s) == (3, "m:ss", 60.0)
    text = REPORT_CONFIG_PATH.read_text(encoding="utf-8")
    assert re.search(r"^\s*[a-z_]*key\s*:", text, re.MULTILINE | re.IGNORECASE) is None


def test_a_configuration_without_llm(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("llm: null\nmax_attempts: 2\n", encoding="utf-8")

    config = load_report_config(path)

    assert (config.llm, config.max_attempts) == (None, 2)


@pytest.mark.parametrize(
    "text", ["llm: null\nmax_attempts: 0\n", "llm: null\nmax_attempts: 3\ntime_format: s\n"]
)
def test_a_wrong_configuration_is_refused(tmp_path: Path, text: str) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")

    with pytest.raises(ValueError):
        load_report_config(path)


def test_the_labels_file_loads() -> None:
    labels = load_value_labels()

    assert labels.fields["pipeline_config.merge_tolerance_s"].startswith("largest gap")
    assert labels.values["params_origin"]["rule_defaults"] == "rule defaults"


def test_the_prompt_of_report_1_has_its_slots_and_a_version() -> None:
    template = load_prompt("report1")

    assert SECTIONS_SLOT in template.text and INPUT_SLOT in template.text
    assert template.version == PromptTemplate("report1", template.text.replace("\n", "\r\n")).version


def test_the_sections_are_listed_as_items_not_as_headings() -> None:
    """A heading followed by its steps was copied as the title by gemini-3.5-flash-lite."""
    lines = sections_text(REPORT1, input_of("handoff_s21_A")).split("\n")

    assert lines[0] == '- "Event and rule": s_s1_proj'
    assert not any(line.startswith("#") for line in lines)


def test_a_template_without_slots_is_refused() -> None:
    with pytest.raises(ValueError):
        PromptTemplate("broken", "no slots")


class _Client:
    def __init__(self, answer: object) -> None:
        self.answer = answer

    def chat(self, prompt: str) -> object:
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def test_the_adapter_returns_the_answer_and_declares_its_settings() -> None:
    model = WatchOutLanguageModel(GEMINI, client=_Client("## Limits"))

    assert model.complete("prompt") == "## Limits"
    assert (model.settings.provider, model.settings.model, model.settings.seed) == (
        "gemini",
        GEMINI.model,
        42,
    )


@pytest.mark.parametrize("answer", [RuntimeError("429 quota"), "", None])
def test_a_failed_or_empty_call_is_an_unavailable_llm(answer: object) -> None:
    with pytest.raises(LlmUnavailable):
        WatchOutLanguageModel(GEMINI, client=_Client(answer)).complete("prompt")


class _ApiError(Exception):
    """Like ``google.genai.errors.APIError``: the HTTP status is in ``code``."""

    def __init__(self, code: int, message: str = "") -> None:
        super().__init__(f"{code} {message}")
        self.code = code


class _StatusError(Exception):
    """Like the errors of OpenAI, Anthropic and Mistral: the HTTP status is in ``status_code``,
    and OpenAI's ``code`` is a text."""

    def __init__(self, status_code: int, code: str | None = None) -> None:
        super().__init__(f"Error code: {status_code}")
        self.status_code = status_code
        self.code = code


class _Busy:
    """Refuses the first calls with the given errors, then answers."""

    def __init__(self, *errors: Exception) -> None:
        self.errors = list(errors)
        self.calls = 0

    def chat(self, prompt: str) -> str:
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return "## Limits"


def test_a_busy_model_is_called_again_after_a_wait() -> None:
    client = _Busy(_ApiError(503, "UNAVAILABLE"), _ApiError(429, "Please retry in 39.27s."))
    waited: list[float] = []

    model = WatchOutLanguageModel(GEMINI, client=client, waits=(10.0, 30.0), sleep=waited.append)

    assert model.complete("prompt") == "## Limits"
    assert (client.calls, waited) == (3, [10.0, 39.27])


def test_the_status_of_the_other_providers_is_read_too() -> None:
    client = _Busy(_StatusError(429, "rate_limit_exceeded"), _StatusError(529))
    waited: list[float] = []

    model = WatchOutLanguageModel(GEMINI, client=client, waits=(10.0, 30.0), sleep=waited.append)

    assert model.complete("prompt") == "## Limits"
    assert (client.calls, waited) == (3, [10.0, 30.0])


def test_after_the_last_wait_the_llm_is_unavailable() -> None:
    client = _Busy(*[_ApiError(503, "UNAVAILABLE")] * 3)
    waited: list[float] = []

    with pytest.raises(LlmUnavailable, match="503"):
        WatchOutLanguageModel(GEMINI, client=client, waits=(1.0, 2.0), sleep=waited.append).complete("p")
    assert (client.calls, waited) == (3, [1.0, 2.0])


@pytest.mark.parametrize(
    ("error", "status"), [(_ApiError(404, "NOT_FOUND"), "404"), (_StatusError(401, "invalid_api_key"), "401")]
)
def test_an_error_that_a_wait_does_not_fix_is_not_tried_again(error: Exception, status: str) -> None:
    client = _Busy(error)
    waited: list[float] = []

    with pytest.raises(LlmUnavailable, match=status):
        WatchOutLanguageModel(GEMINI, client=client, sleep=waited.append).complete("prompt")
    assert (client.calls, waited) == (1, [])


@pytest.mark.real_llm_client
def test_without_the_key_in_the_environment_the_llm_is_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    with pytest.raises(LlmUnavailable) as caught:
        WatchOutLanguageModel(GEMINI)

    assert "GOOGLE_API_KEY" in str(caught.value)


def test_the_tests_never_build_a_real_client() -> None:
    with pytest.raises(LlmUnavailable):
        WatchOutLanguageModel(GEMINI)
