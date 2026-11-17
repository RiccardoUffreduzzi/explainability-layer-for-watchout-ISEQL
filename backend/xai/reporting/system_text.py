"""The sections the system writes itself (``SectionSpec.by_system``): facts with a fixed sentence.

The sentences come from ``resources/sentences/<name>.yaml`` and cite values by name, as the
LLM's text does, so they are rendered the same way and keep their steps and values. A step of
these sections without a sentence, or a sentence citing a value the table does not have, is
``ReportFailure``.
"""

from collections.abc import Iterable, Iterator, Sequence

from xai.contract.plan import PlanStep, StepType
from xai.reporting.catalogue import SystemSentences
from xai.reporting.failure import ReportFailure
from xai.reporting.llm_input import ReportInput
from xai.reporting.profile import ReportProfile
from xai.reporting.reading import NAME, ParsedSection, ParsedSentence, markers

MISSING_FIELDS = "#/harvest_report/missing_fields"
"""The pointer a limit cites when it says which data the system does not save."""


def system_sections(
    profile: ReportProfile, report_input: ReportInput, sentences: SystemSentences
) -> tuple[ParsedSection, ...]:
    """The sections of the profile the system writes, in order, each with its sentences."""
    writer = _SystemWriter(report_input, sentences)
    return tuple(
        ParsedSection(title=section.title, sentences=tuple(writer.section(steps)), written_by="system")
        for section, steps in profile.layout(report_input.system_steps)
        if section.by_system and steps
    )


class _SystemWriter:
    def __init__(self, report_input: ReportInput, sentences: SystemSentences) -> None:
        self._input = report_input
        self._sentences = sentences
        self._names = report_input.table.names()
        self._steps = {step.step_id: step for step in report_input.plan.steps}

    def section(self, steps: Sequence[PlanStep]) -> Iterator[ParsedSentence]:
        """One paragraph with a sentence for each step; then the limits, by the steps they concern:
        a sentence that says which, then each limit as a list item."""
        paragraph = [step for step in steps if step.type is not StepType.LIMIT]
        for step in paragraph:
            yield self._sentence(self._text_of(step), (step.step_id,), block=0)
        block = 1 if paragraph else 0
        for depends_on, limits in _by_dependence(step for step in steps if step.type is StepType.LIMIT):
            yield self._sentence(self._concern(depends_on), tuple(s.step_id for s in limits), block)
            for limit in limits:
                block += 1
                yield self._sentence(f"{{{limit.step_id}.fixed_text}}", (limit.step_id,), block, True)
                if MISSING_FIELDS in limit.refs:
                    yield self._sentence(
                        self._sentences.limits["missing_fields"], (limit.step_id,), block, True
                    )
            block += 1

    def _text_of(self, step: PlanStep) -> str:
        text = self._sentences.steps.get(step.step_id)
        if text is None:
            raise ReportFailure("UNSUPPORTED_REF", f"the system has no sentence for the step {step.step_id}")
        return text.replace("<bindings>", self._bindings())

    def _bindings(self) -> str:
        """Each variable of the rule with the intervals it was bound to."""
        return _join(
            self._sentences.bindings[binding.status.value]
            .replace("<variable>", binding.variable)
            .replace("<intervals>", _join([self._interval(i) for i in binding.interval_ids]))
            for binding in self._input.plan.bindings
        )

    def _interval(self, interval_id: str) -> str:
        if f"{interval_id}.at" in self._names:
            return self._sentences.intervals["at"].replace("<at>", f"{{{interval_id}.at}}")
        return (
            self._sentences.intervals["span"]
            .replace("<start>", f"{{{interval_id}.start}}")
            .replace("<end>", f"{{{interval_id}.end}}")
        )

    def _concern(self, depends_on: tuple[str, ...]) -> str:
        """The steps the limits concern: the whole detection, or the constructs of the steps."""
        concerned = [self._steps[step_id] for step_id in depends_on if step_id in self._steps]
        constructs = [
            f"{{{step.construct_}.text}}"
            for step in concerned
            if step.type is not StepType.CONCLUSION and step.construct_ is not None
        ]
        if not constructs:
            return self._sentences.limits["whole_detection"]
        return self._sentences.limits["constructs"].replace("<constructs>", _join(constructs))

    def _sentence(
        self, body: str, step_ids: tuple[str, ...], block: int, list_item: bool = False
    ) -> ParsedSentence:
        names = tuple(dict.fromkeys(NAME.findall(body)))
        missing = [name for name in names if name not in self._names]
        if missing:
            raise ReportFailure(
                "UNSUPPORTED_REF",
                f"the sentence of the system for {step_ids[0]} cites {missing}, not in the table of values",
            )
        return ParsedSentence(
            llm_text=f"{body} {markers(step_ids)}",
            body=body,
            step_ids=step_ids,
            names=names,
            entities=(),
            block=block,
            list_item=list_item,
        )


def _by_dependence(limits: Iterable[PlanStep]) -> list[tuple[tuple[str, ...], list[PlanStep]]]:
    """The limits grouped by the steps they concern, in the order of their first limit."""
    groups: dict[tuple[str, ...], list[PlanStep]] = {}
    for limit in limits:
        groups.setdefault(tuple(limit.depends_on), []).append(limit)
    return list(groups.items())


def _join(parts: Iterable[str]) -> str:
    """``a``, ``a and b``, ``a, b and c``."""
    words = list(parts)
    return words[0] if len(words) == 1 else f"{', '.join(words[:-1])} and {words[-1]}"
