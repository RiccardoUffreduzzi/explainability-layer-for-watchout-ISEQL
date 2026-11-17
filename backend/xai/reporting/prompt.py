"""The prompt of a report: the template of its profile, filled with the sections and the input.

template has two slots, ``{{sections}}`` and ``{{input}}``. The version of a prompt is the name of the
template and the first 12 hex digits of its SHA-256
"""

import hashlib
from dataclasses import dataclass

from xai.reporting.llm_input import ReportInput
from xai.reporting.profile import ReportProfile

SECTIONS_SLOT = "{{sections}}"
INPUT_SLOT = "{{input}}"


@dataclass(frozen=True)
class PromptTemplate:
    name: str
    text: str

    def __post_init__(self) -> None:
        missing = [slot for slot in (SECTIONS_SLOT, INPUT_SLOT) if slot not in self.text]
        if missing:
            raise ValueError(f"prompt {self.name!r} lacks {', '.join(missing)}")

    @property
    def version(self) -> str:
        digest = hashlib.sha256(self.text.replace("\r\n", "\n").encode("utf-8")).hexdigest()
        return f"{self.name}@{digest[:12]}"


def sections_text(profile: ReportProfile, report_input: ReportInput) -> str:
    """The sections in order, each with the steps it renders; a section without steps is left out.

    A list item, not a heading: a heading with its steps would be copied as the title.
    """
    lines = []
    for section, steps in profile.layout(report_input.steps):
        if steps:
            lines.append(f'- "{section.title}": {", ".join(step.step_id for step in steps)}')
    return "\n".join(lines)


def compose(template: PromptTemplate, profile: ReportProfile, report_input: ReportInput) -> str:
    text = template.text.replace("\r\n", "\n")
    text = text.replace(SECTIONS_SLOT, sections_text(profile, report_input))
    return text.replace(INPUT_SLOT, report_input.to_json())


def retry_prompt(prompt: str, answer: str, problems: list[str]) -> str:
    """The prompt of a new attempt: the same request, the refused text and why it was refused."""
    listed = "\n".join(f"- {problem}" for problem in problems)
    return (
        f"{prompt}\n\n"
        "# Your previous text could not be used\n\n"
        f"This is the text you wrote:\n\n{answer}\n\n"
        f"These are the problems found in it:\n\n{listed}\n\n"
        "Write the whole text again, following every rule above and fixing these problems."
    )
