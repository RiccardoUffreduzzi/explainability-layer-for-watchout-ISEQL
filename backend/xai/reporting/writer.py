"""one report of one plan, through the LLM

The LLM writes the sections of the profile, but those the system writes with its own sentences
(``system_text``). A text that cannot be rendered
goes back to the LLM with its problems, up to ``max_attempts`` calls; then, or when the LLM
cannot be reached, ``ReportFailure`` is raised with the trace of the calls made. The trace keeps
every prompt and answer, so a report can be made again without calling the LLM.
"""

import logging
from dataclasses import dataclass

from xai.contract.plan import ExplanationPlan
from xai.contract.report import REPORT_VERSION, LlmCall, Report, ReportTrace
from xai.contract.source_of_truth import SourceOfTruth
from xai.reporting.catalogue import SystemSentences, TimeFormat, ValueLabels
from xai.reporting.failure import ReportFailure
from xai.reporting.llm_input import ReportInput, build_input
from xai.reporting.ports import LanguageModel, LlmUnavailable
from xai.reporting.profile import ReportProfile
from xai.reporting.prompt import PromptTemplate, compose, retry_prompt
from xai.reporting.reading import ParsedText, TextProblems, read_answer, text_rules
from xai.reporting.renderer import Header, markdown, render
from xai.reporting.system_text import system_sections

log = logging.getLogger("xai.reporting")


@dataclass(frozen=True)
class WrittenReport:
    report: Report
    markdown: str
    trace: ReportTrace


class ReportWriter:
    def __init__(
        self,
        profile: ReportProfile,
        template: PromptTemplate,
        sentences: SystemSentences,
        llm: LanguageModel,
        labels: ValueLabels,
        *,
        max_attempts: int = 3,
        time_format: TimeFormat = "m:ss",
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self.profile = profile
        self.template = template
        self.sentences = sentences
        self.llm = llm
        self.labels = labels
        self.max_attempts = max_attempts
        self.time_format = time_format

    @property
    def prompt_version(self) -> str:
        return self.template.version

    @property
    def sentences_version(self) -> str:
        return self.sentences.version

    def input_of(self, plan: ExplanationPlan, document: SourceOfTruth) -> ReportInput:
        return build_input(plan, document, self.profile, self.labels, self.time_format)

    def prompt_of(self, report_input: ReportInput) -> str:
        return compose(self.template, self.profile, report_input)

    def write(self, plan: ExplanationPlan, document: SourceOfTruth) -> WrittenReport:
        report_input = self.input_of(plan, document)
        rules = text_rules(self.profile, report_input)
        system = system_sections(self.profile, report_input, self.sentences)
        titles = [section.title for section in self.profile.sections]
        prompt = self.prompt_of(report_input)
        settings = self.llm.settings
        calls: list[LlmCall] = []

        def trace() -> ReportTrace:
            return ReportTrace(
                report_version=REPORT_VERSION,  # type: ignore[arg-type]
                report=self.profile.number,
                event_id=plan.plan_meta.event_id,
                plan_hash=plan.plan_meta.plan_hash,
                prompt_version=self.prompt_version,
                llm=settings,
                calls=calls,
            )

        current = prompt
        problems: list[str] = []
        for attempt in range(1, self.max_attempts + 1):
            try:
                answer = self.llm.complete(current)
            except LlmUnavailable as error:
                reason = str(error) or type(error).__name__
                calls.append(LlmCall(attempt=attempt, prompt=current, answer=None, error=reason, problems=[]))
                raise ReportFailure("LLM_UNAVAILABLE", reason, trace()) from error
            try:
                parsed = read_answer(answer, rules)
            except TextProblems as refused:
                problems = refused.problems
                calls.append(LlmCall(attempt=attempt, prompt=current, answer=answer, problems=problems))
                log.warning(
                    "report %d of %s, attempt %d: the text cannot be rendered: %s",
                    self.profile.number,
                    plan.plan_meta.event_id,
                    attempt,
                    "; ".join(problems),
                )
                current = retry_prompt(prompt, answer, problems)
                continue
            calls.append(LlmCall(attempt=attempt, prompt=current, answer=answer, problems=[]))
            header = Header(self.prompt_version, self.sentences_version, settings, attempt)
            whole = sorted((*parsed.sections, *system), key=lambda section: titles.index(section.title))
            report = render(ParsedText(tuple(whole)), report_input, self.profile.number, header)
            return WrittenReport(report=report, markdown=markdown(report), trace=trace())
        raise ReportFailure(
            "TEXT_NOT_RENDERABLE",
            f"no text could be rendered in {self.max_attempts} attempt(s); "
            f"last problems: {'; '.join(problems)}",
            trace(),
        )
