"""The reports written by K5 (Report 1) and K6 (Report 2), and the trace of their LLM calls.

The file keeps, for every sentence, the text the LLM (or the system) wrote,
the text the reader sees, the steps the sentence renders and the values and
entities it cites.
"""

import json
from typing import Annotated, Final, Literal, get_args

from pydantic import Field, NonNegativeInt, PositiveInt

from xai.contract.model import EntityId, EventId
from xai.contract.plan import PlanHash, StepId
from xai.contract.primitives import ContractModel, NonEmptyStr, absent_if_none
from xai.contract.source_of_truth import ContractHash

ReportVersion = Literal["0.2.0-k5"]
REPORT_VERSION: Final[str] = get_args(ReportVersion)[0]
"""Version of the report format; the JSON schema is bound to it (``$id`` and ``const``)."""

ReportNumber = Literal[1, 2]
"""1: the analyst's report (K5); 2: the report for a reader who does not know ISEQL+ (K6)."""

ValueForm = Literal["plain", "code", "quote", "block"]
"""How the reader sees a value: as it is, as a formal term, as a quoted definition, as a block."""

Author = Literal["llm", "system"]
"""Who wrote a section: the LLM, or the system with its fixed sentences."""


class LlmSettings(ContractModel):
    """The model that wrote the text and how it was called."""

    provider: NonEmptyStr
    model: NonEmptyStr
    temperature: float
    seed: int | None


class ReportMeta(ContractModel):
    report_version: ReportVersion
    report: ReportNumber
    event_id: EventId
    model_id: NonEmptyStr
    label: NonEmptyStr
    plan_hash: PlanHash
    """The plan the report renders."""
    contract_hash: ContractHash
    """The source of truth the values come from."""
    prompt_version: NonEmptyStr
    """``<prompt name>@<first 12 hex digits of the SHA-256 of the prompt template>``."""
    sentences_version: NonEmptyStr
    """``<name>@<first 12 hex digits of the SHA-256 of the sentences of the system>``."""
    llm: LlmSettings
    attempts: PositiveInt
    """How many calls it took to get a text that could be rendered."""
    verification: Literal["not_run"]


class CitedValue(ContractModel):
    """A value the sentence cites by name; the renderer wrote ``text`` in its place."""

    name: NonEmptyStr
    """The name the LLM wrote"""
    ref: NonEmptyStr
    """Where the value is in the source of truth"""
    text: NonEmptyStr
    form: ValueForm


class CitedEntity(ContractModel):
    """An entity the sentence names, with the words the LLM chose for it."""

    entity_id: EntityId
    text: NonEmptyStr


class Sentence(ContractModel):
    llm_text: NonEmptyStr
    """The sentence as its author wrote it: names in braces, entities marked, step markers."""
    text: NonEmptyStr
    """The sentence the reader sees, without markers and IDs."""
    step_ids: Annotated[list[StepId], Field(min_length=1)]
    """The steps the sentence renders, in the order of its markers."""
    values: list[CitedValue]
    entities: list[CitedEntity]
    block: NonNegativeInt
    """Position of the paragraph or list item in the section: sentences with the same one go together."""
    list_item: bool
    """True when the block is an item of a list."""


class Section(ContractModel):
    title: NonEmptyStr
    written_by: Author
    sentences: Annotated[list[Sentence], Field(min_length=1)]


class Report(ContractModel):
    """One report of one detection."""

    report_meta: ReportMeta
    sections: Annotated[list[Section], Field(min_length=1)]


class LlmCall(ContractModel):
    """One call to the LLM: what it was asked, what it answered, why the answer was refused."""

    attempt: PositiveInt
    prompt: NonEmptyStr
    answer: str | None
    """Null when the call failed."""
    error: NonEmptyStr | None = absent_if_none()
    """Why the call failed (the LLM could not be reached or answered nothing)."""
    problems: list[NonEmptyStr]
    """Why the text could not be rendered; empty for the accepted answer."""


class ReportTrace(ContractModel):
    """Every call made for one report, in order: the last answer is the accepted one."""

    report_version: ReportVersion
    report: ReportNumber
    event_id: EventId
    plan_hash: PlanHash
    prompt_version: NonEmptyStr
    llm: LlmSettings
    calls: Annotated[list[LlmCall], Field(min_length=1)]


REPORT_INDENT: Final = 2


def dump_report(report: Report) -> str:
    """JSON of the report: the same report always gives the same text."""
    data = report.model_dump(mode="json")
    return json.dumps(data, sort_keys=True, ensure_ascii=False, indent=REPORT_INDENT) + "\n"


def load_report(text: str | bytes) -> Report:
    return Report.model_validate_json(text)


def dump_trace(trace: ReportTrace) -> str:
    data = trace.model_dump(mode="json")
    return json.dumps(data, sort_keys=True, ensure_ascii=False, indent=REPORT_INDENT) + "\n"


def load_trace(text: str | bytes) -> ReportTrace:
    return ReportTrace.model_validate_json(text)
