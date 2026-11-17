"""The renderer which puts the values of the table in place of the names, keeps the words of the marked
entities and drops markers and IDs. ``markdown`` writes the text for the reader
from the report alone, without tables: formal terms in code format, definitions in quotes
and the rule in a block of its own.
"""

import re
from dataclasses import dataclass

from xai.contract.report import (
    REPORT_VERSION,
    CitedEntity,
    CitedValue,
    LlmSettings,
    Report,
    ReportMeta,
    ReportNumber,
    Section,
    Sentence,
    ValueForm,
)
from xai.reporting.llm_input import ReportInput
from xai.reporting.reading import ENTITY_MARK, MARKER_RUN, NAME, ParsedSentence, ParsedText

BLOCK_INDENT = "    "
SENTENCE_END = (".", "!", "?", ":", ";")


@dataclass(frozen=True)
class Header:
    """What the report declares about how it was written."""

    prompt_version: str
    sentences_version: str
    llm: LlmSettings
    attempts: int


def render(parsed: ParsedText, report_input: ReportInput, number: ReportNumber, header: Header) -> Report:
    meta = report_input.plan.plan_meta
    return Report(
        report_meta=ReportMeta(
            report_version=REPORT_VERSION,  # type: ignore[arg-type]
            report=number,
            event_id=meta.event_id,
            model_id=meta.model_id,
            label=meta.label,
            plan_hash=meta.plan_hash,
            contract_hash=meta.contract_hash,
            prompt_version=header.prompt_version,
            sentences_version=header.sentences_version,
            llm=header.llm,
            attempts=header.attempts,
            verification="not_run",
        ),
        sections=[
            Section(
                title=section.title,
                written_by=section.written_by,
                sentences=[_sentence(s, report_input) for s in section.sentences],
            )
            for section in parsed.sections
        ],
    )


def _sentence(parsed: ParsedSentence, report_input: ReportInput) -> Sentence:
    table = report_input.table
    values = []
    for name in parsed.names:
        found = table.value(name)
        assert found is not None, name
        values.append(CitedValue(name=name, ref=found.pointer, text=found.written, form=found.form))
    entities = [CitedEntity(entity_id=entity, text=words) for words, entity in parsed.entities]
    for cited in values:
        row = table.entity(cited.name)
        if row is not None:
            entities.append(CitedEntity(entity_id=row.entity_id, text=cited.text))
    return Sentence(
        llm_text=parsed.llm_text,
        text="".join(text for text, _ in _pieces(parsed.body, values)).strip(),
        step_ids=list(parsed.step_ids),
        values=values,
        entities=entities,
        block=parsed.block,
        list_item=parsed.list_item,
    )


def _pieces(body: str, values: list[CitedValue]) -> list[tuple[str, ValueForm | None]]:
    """The sentence as pieces of text: the LLM's words (form ``None``) and the values with their form."""
    by_name = {value.name: value for value in values}
    body = ENTITY_MARK.sub(lambda m: m.group(1).strip(), body)
    pieces: list[tuple[str, ValueForm | None]] = []
    position = 0
    stop = False
    for match in NAME.finditer(body):
        pieces.append((_after(body[position : match.start()], stop), None))
        value = by_name[match.group(1)]
        pieces.append((value.text, value.form))
        stop = value.text.endswith((".", "!", "?"))
        position = match.end()
    pieces.append((_after(body[position:], stop), None))
    return _closed(pieces)


def _closed(pieces: list[tuple[str, ValueForm | None]]) -> list[tuple[str, ValueForm | None]]:
    """A sentence the LLM left without a period gets one, so that it does not run into the next.

    A sentence that ends with the rule (a block) is left as it is.
    """
    last = next(((text, form) for text, form in reversed(pieces) if text.strip()), None)
    if last is not None and last[1] != "block" and not last[0].rstrip().endswith(SENTENCE_END):
        pieces.append((".", None))
    return pieces


def _after(text: str, stop: bool) -> str:
    """The LLM's words after a value; a value that ends a sentence (a fixed text) keeps its own period."""
    return text[1:] if stop and text.startswith(".") else text


# --------------------------------------------------------------------------- Markdown


def markdown(report: Report) -> str:
    """The text for the reader, made from the report file alone."""
    meta = report.report_meta
    lines = [f"# Detection report: {meta.label.replace('_', ' ')}"]
    for section in report.sections:
        lines += ["", f"## {section.title}"]
        previous_item = False
        for block in _blocks(section.sentences):
            chunks = _block_markdown(block)
            if block[0].list_item:
                if not previous_item:
                    lines.append("")
                lines.append("- " + "\n\n".join(chunks).replace("\n", "\n  "))
                previous_item = True
            else:
                for chunk in chunks:
                    lines += ["", chunk]
                previous_item = False
    return "\n".join(lines) + "\n"


def _blocks(sentences: list[Sentence]) -> list[list[Sentence]]:
    blocks: list[list[Sentence]] = []
    for sentence in sentences:
        if blocks and blocks[-1][0].block == sentence.block:
            blocks[-1].append(sentence)
        else:
            blocks.append([sentence])
    return blocks


def _block_markdown(sentences: list[Sentence]) -> list[str]:
    """The paragraphs of a block: the sentences joined, with the rule apart when it is cited."""
    chunks: list[str] = []
    paragraph: list[str] = []
    for sentence in sentences:
        body = MARKER_RUN.sub("", sentence.llm_text).strip()
        inline = ""
        for text, form in _pieces(body, sentence.values):
            if form == "block":
                if inline.strip():
                    paragraph.append(inline.strip())
                if paragraph:
                    chunks.append(" ".join(paragraph))
                chunks.append("\n".join(BLOCK_INDENT + line for line in text.split("\n")))
                paragraph, inline = [], ""
            else:
                inline += _inline(text, form)
        if inline.strip() and not _punctuation_only(inline):
            paragraph.append(inline.strip())
    if paragraph:
        chunks.append(" ".join(paragraph))
    return chunks


def _inline(text: str, form: ValueForm | None) -> str:
    if form == "code":
        fence = "``" if "`" in text else "`"
        pad = " " if fence == "``" else ""
        return f"{fence}{pad}{text}{pad}{fence}"
    if form == "quote":
        return f'"{text}"'
    return text


def _punctuation_only(text: str) -> bool:
    return re.fullmatch(r"[\s.,;:!?]*", text) is not None
