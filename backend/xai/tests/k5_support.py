"""Plans, inputs, LLMs and expected files shared by the tests of the reports (K5).

The texts the LLM would write are written by hand in ``tests/data/k5/text/<name>.txt`` for the
golden plans of K4; the expected inputs, prompts and reports are in ``tests/data/k5/``.
"""

import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from xai.adapters.report_resources import load_prompt, load_sentences, load_value_labels
from xai.contract.plan import ExplanationPlan
from xai.contract.report import LlmSettings
from xai.contract.source_of_truth import SourceOfTruth
from xai.k5_report1.profile import REPORT1
from xai.reporting.catalogue import ValueLabels
from xai.reporting.llm_input import ReportInput, build_input
from xai.reporting.ports import LanguageModel, LlmUnavailable
from xai.reporting.writer import ReportWriter
from xai.tests.k4_plan_support import source_and_plan
from xai.tests.k4_support import GOLDEN_NAMES, Change
from xai.tests.support import EXAMPLES_DIR

K5_DATA_DIR = EXAMPLES_DIR / "k5"
TEXT_DIR = K5_DATA_DIR / "text"
INPUT_DIR = K5_DATA_DIR / "input"
PROMPT_DIR = K5_DATA_DIR / "prompt"
REPORT_DIR = K5_DATA_DIR / "report"

NAMES = GOLDEN_NAMES
LABELS: ValueLabels = load_value_labels()
TEST_SETTINGS = LlmSettings(provider="test", model="scripted", temperature=0.0, seed=None)


def hand_text(name: str) -> str:
    """The text written by hand for the golden plan ``name``, as an LLM would answer."""
    return (TEXT_DIR / f"{name}.txt").read_text(encoding="utf-8")


def input_of(name: str, change: Change | None = None) -> ReportInput:
    document, plan = source_and_plan(name, change)
    return build_input(plan, document, REPORT1, LABELS)


def pair_of(name: str, change: Change | None = None) -> tuple[ExplanationPlan, SourceOfTruth]:
    document, plan = source_and_plan(name, change)
    return plan, document


class ScriptedModel:
    """Answers with the given texts in order; an exception in the list is raised instead."""

    def __init__(self, answers: Sequence[str | Exception], settings: LlmSettings = TEST_SETTINGS) -> None:
        self.answers = list(answers)
        self.prompts: list[str] = []
        self._settings = settings

    @property
    def settings(self) -> LlmSettings:
        return self._settings

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self.answers:
            raise LlmUnavailable("no more scripted answers")
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


SECTION_LINE = re.compile(r'^- "(.+?)": (s_\w+(?:, s_\w+)*)$', re.M)
PLACEHOLDER = re.compile(r"\{[^{}]*\}")


class EchoModel:
    """Writes the smallest text that can be rendered for any prompt: one sentence per step.

    It reads the sections, the steps and the input from the prompt, so it works on any plan: the
    pipeline tests use it on the real analyses. A step with a sentence of the system cites it, a
    step with a term says its phrase, and the conclusion gives the definition of the rule.
    """

    def __init__(self) -> None:
        self.prompts: list[str] = []

    @property
    def settings(self) -> LlmSettings:
        return LlmSettings(provider="test", model="echo", temperature=0.0, seed=None)

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        data = json.loads(prompt.rpartition("# Input")[2])
        lines = []
        for title, steps in SECTION_LINE.findall(prompt):
            lines += [f"## {title}", ""]
            lines += [self._sentence(step, data) for step in steps.split(", ")]
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _sentence(step: str, data: dict[str, Any]) -> str:
        values = data["values"]
        if f"{step}.fixed_text" in values:
            return f"{{{step}.fixed_text}} [{step}]"
        term = next(s.get("term") for s in data["plan"]["steps"] if s["step_id"] == step)
        if term is None:
            return f"The plan has this step. [{step}]"
        entry = data["glossary"][term]
        sentence = f"The plan has this step: {PLACEHOLDER.sub('it', entry['phrase'])}. [{step}]"
        if entry["kind"] == "event_model" and f"{term}.definition" in values:
            sentence += f"\nIts rule is: {{{term}.definition}} [{step}]"
        return sentence


def writer(llm: LanguageModel, max_attempts: int = 3) -> ReportWriter:
    return ReportWriter(
        REPORT1, load_prompt("report1"), load_sentences("report1"), llm, LABELS, max_attempts=max_attempts
    )


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")
