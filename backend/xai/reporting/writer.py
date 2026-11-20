"""one report of one plan, through the LLM

The LLM writes the sections of the profile, but those the system writes with its own sentences
(``system_text``). A text that cannot be rendered
goes back to the LLM with its problems, up to ``max_attempts`` calls; then, or when the LLM
cannot be reached, ``ReportFailure`` is raised with the trace of the calls made. The trace keeps
every prompt and answer, so a report can be made again without calling the LLM.

With ``frames``, the section of the profile's ``figure_section`` also shows the key frame of the
detection (``figures``), added after the text is rendered.
"""

import logging
from dataclasses import dataclass

from xai.contract.plan import ExplanationPlan
from xai.contract.report import REPORT_VERSION, LlmCall, Report, ReportTrace
from xai.contract.source_of_truth import SourceOfTruth
from xai.reporting.catalogue import SystemSentences, TimeFormat, ValueLabels
from xai.reporting.failure import ReportFailure
from xai.reporting.figures import key_frame_figure
from xai.reporting.llm_input import ReportInput, build_input
from xai.reporting.ports import FrameImages, LanguageModel, LlmUnavailable
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
    image: bytes | None = None
    """The JPEG of the key frame, saved beside the report; None when the report shows none."""


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
        frames: FrameImages | None = None,
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
        self.frames = frames

    @property
    def key_frame_images(self) -> bool:
        """True when the reports show the key frame: the writer has frames and the profile a section."""
        return self.frames is not None and self.profile.figure_section is not None

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
            header = Header(
                self.prompt_version, self.sentences_version, settings, attempt, self.key_frame_images
            )
            whole = sorted((*parsed.sections, *system), key=lambda section: titles.index(section.title))
            figures, image = {}, None
            if self.frames is not None and self.profile.figure_section is not None:
                found = key_frame_figure(document, self.frames, self.sentences, self.time_format)
                if found is not None:
                    figures, image = {self.profile.figure_section: found.figure}, found.jpeg
            report = render(ParsedText(tuple(whole)), report_input, self.profile.number, header, figures)
            return WrittenReport(report=report, markdown=markdown(report), trace=trace(), image=image)
        raise ReportFailure(
            "TEXT_NOT_RENDERABLE",
            f"no text could be rendered in {self.max_attempts} attempt(s); "
            f"last problems: {'; '.join(problems)}",
            trace(),
        )
