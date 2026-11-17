"""``who a report is for, which steps it reads and how its sections are made."""

from collections.abc import Sequence
from dataclasses import dataclass

from xai.contract.plan import PlanStep, StepType
from xai.contract.report import ReportNumber


@dataclass(frozen=True)
class SectionSpec:
    title: str
    step_types: tuple[StepType, ...] = ()
    step_ids: tuple[str, ...] = ()
    by_system: bool = False
    """True: the system writes the section with its fixed sentences; the LLM does not receive its steps."""


@dataclass(frozen=True)
class ReportProfile:
    number: ReportNumber
    name: str
    """The prompt template, ``resources/prompts/<name>.txt``, and the sentences of the system,
    ``resources/sentences/<name>.yaml``."""
    only_in_report2: bool
    """True: the LLM receives only the steps with ``in_report2``"""
    sections: tuple[SectionSpec, ...]
    cites_rule_definition: bool = False
    """True: the text must cite the definition of the rule (``{g_event_model_….definition}``)."""

    def admits(self, step: PlanStep) -> bool:
        return step.in_report2 or not self.only_in_report2

    def by_system(self, step: PlanStep) -> bool:
        section = self.section_of(step)
        return section is not None and section.by_system

    def section_of(self, step: PlanStep) -> SectionSpec | None:
        by_id = next((s for s in self.sections if step.step_id in s.step_ids), None)
        if by_id is not None:
            return by_id
        return next((s for s in self.sections if step.type in s.step_types), None)

    def layout(self, steps: Sequence[PlanStep]) -> tuple[tuple[SectionSpec, tuple[PlanStep, ...]], ...]:
        """Each section with its steps, in plan order; a section may have none"""
        return tuple(
            (section, tuple(step for step in steps if self.section_of(step) == section))
            for section in self.sections
        )
