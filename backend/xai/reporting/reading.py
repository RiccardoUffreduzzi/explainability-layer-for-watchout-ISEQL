"""Reads the text of the LLM: sections, blocks, sentences, step markers, cited names and entities.

The text is Markdown-like. Every sentence ends with the markers of the steps
it renders. Values are cited by name in braces and an entity is named with words of its description,
marked with its ID (``[man in a hoodie](ent_3)``).

A text that fails goes back to the LLM with its problems. ``read_answer`` also wants every step
of the prompt rendered, the phrase of every term said in words, every sentence of the system cited
by its name and, when the profile asks for it, the definition of the rule.
"""

import difflib
import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from xai.contract.plan import StepType
from xai.contract.report import Author
from xai.reporting.llm_input import ReportInput
from xai.reporting.profile import ReportProfile

MARKER_RUN = re.compile(r"(?:[ \t]*\[(?:s_[A-Za-z0-9_]+)\](?!\())+")
MARKER = re.compile(r"\[(s_[A-Za-z0-9_]+)\]")
NAME = re.compile(r"\{([^{}\s]+)\}")
ENTITY_MARK = re.compile(r"\[([^\[\]]+)\]\((ent_[0-9]+)\)")
OTHER_MARK = re.compile(r"\[([^\[\]]+)\]\(((?:iv|ev|c|g|s)_[A-Za-z0-9_]+(?:\.[^\s()\[\]]+)?)\)")
BROKEN_NAME = re.compile(r"\{([^{}\s]*)\n[ \t]*([^{}\s]*)\}")
LEFT_ID = re.compile(r"\b(?:ent|iv|ev|c|g|s)_[A-Za-z0-9_]+")
CODE = re.compile(r"\b[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+\b")
PLACEHOLDER = re.compile(r"\{[^{}]*\}")
STRAY_BRACES = re.compile(r"\{[^{}]*\}|[{}]")
INTERVAL_TIME = re.compile(r"iv_[A-Za-z0-9_]+\.(?:start|end|at)")
WORD = re.compile(r"[a-z]+")
COMMON_WORDS = frozenset({"both", "each", "from", "into", "than", "that", "this", "with"})
TOKEN = re.compile(r"[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*")
HEADING = re.compile(r"^#{1,6}\s+(.*?)\s*:?\s*$")
TITLE_WITH_STEPS = re.compile(r"^(.*?)\s*[:(]\s*s_[A-Za-z0-9_]+(?:\s*,\s*s_[A-Za-z0-9_]+)*\s*\)?$")
ITEM = re.compile(r"^[-*]\s+(.*)$")
PUNCTUATION_ONLY = re.compile(r"^[\s.,;:!?)\]\"']*$")
FENCE = re.compile(r"^```[A-Za-z]*\n(.*)\n```$", re.S)


@dataclass(frozen=True)
class TextRules:
    """What a text may cite: the steps, names and entities the LLM received."""

    titles: tuple[str, ...]
    step_ids: frozenset[str]
    names: frozenset[str]
    entities: Mapping[str, str | None]
    """Entity ID -> its description, whose digits the LLM may copy."""
    rule_names: frozenset[str]
    """Names of the rule that contain digits and are not numbers (``M1``, ``arg1``, ``s1``)."""
    sections: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    """Section title -> the steps the prompt lists under it: each must be rendered."""
    fixed_texts: frozenset[str] = frozenset()
    """Steps with a sentence of the system, cited as ``{<step>.fixed_text}`` and never rewritten."""
    phrases: Mapping[str, str] = field(default_factory=dict)
    """Step -> the glossary phrase of its term, which the text says in words."""
    codes: Mapping[str, str] = field(default_factory=dict)
    """The codes of the bindings and the terms of the glossary that are codes -> what they mean:
    a code is never written in the words."""
    definition: str | None = None
    """The name of the definition of the rule, when the text must cite it."""
    event_times: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    """Conclusion step -> the times of its event: its sentences cite them, never those of an interval."""


@dataclass(frozen=True)
class ParsedSentence:
    llm_text: str
    """The sentence and its markers, as its author wrote them (spaces normalized)."""
    body: str
    """The sentence without markers."""
    step_ids: tuple[str, ...]
    names: tuple[str, ...]
    entities: tuple[tuple[str, str], ...]
    """``(words, entity ID)`` of each marked entity, in order."""
    block: int
    list_item: bool


@dataclass(frozen=True)
class ParsedSection:
    title: str
    sentences: tuple[ParsedSentence, ...]
    written_by: Author = "llm"


@dataclass(frozen=True)
class ParsedText:
    sections: tuple[ParsedSection, ...]


class TextProblems(Exception):
    """The text cannot be rendered; ``problems`` say why, in words the LLM can act on."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def text_rules(profile: ReportProfile, report_input: ReportInput) -> TextRules:
    document = report_input.document
    names: set[str] = set(document.rule.projection)
    for node in document.rule.constraints:
        names.update(node.variables)
        if node.branch is not None:
            names.add(node.branch)
        payload = node.payload
        for side in ("left", "right", "start", "end"):
            value = getattr(payload, side, None)
            if isinstance(value, str):
                names.add(value)
    names.update(argument.role for argument in document.event.arguments)
    parts = {part for name in names for part in name.split(".")}
    table_names = report_input.llm_names
    glossary = report_input.glossary
    definitions = [f"{ref}.definition" for ref, entry in glossary.items() if entry["kind"] == "event_model"]
    event = document.event.event_id
    event_times = tuple(
        name for name in (f"{event}.start", f"{event}.end", f"{event}.at") if name in table_names
    )
    return TextRules(
        titles=tuple(section.title for section in profile.sections if not section.by_system),
        step_ids=report_input.step_ids(),
        names=table_names,
        entities={row.entity_id: row.description for row in report_input.table.entities},
        rule_names=frozenset(name for name in names | parts if any(c.isdigit() for c in name)),
        sections={
            section.title: tuple(step.step_id for step in steps)
            for section, steps in profile.layout(report_input.steps)
            if steps
        },
        fixed_texts=frozenset(
            step.step_id for step in report_input.steps if f"{step.step_id}.fixed_text" in table_names
        ),
        phrases={
            step.step_id: glossary[step.term]["phrase"]
            for step in report_input.steps
            if step.term is not None
            and step.term in glossary
            and glossary[step.term]["phrase"] != glossary[step.term]["term"]
        },
        # the event model last: its phrase is the meaning of a term that also names a predicate
        codes={
            **{
                entry["term"]: entry["phrase"]
                for entry in sorted(glossary.values(), key=lambda entry: entry["kind"] == "event_model")
                if CODE.fullmatch(entry["term"])
            },
            **report_input.codes,
        },
        definition=next((d for d in definitions if d in table_names), None)
        if profile.cites_rule_definition
        else None,
        event_times={
            step.step_id: event_times for step in report_input.steps if step.type == StepType.CONCLUSION
        },
    )


def read_answer(text: str, rules: TextRules) -> ParsedText:
    """``read_text``, and every step of the sections rendered: the answer the writer accepts."""
    parsed, problems = _read(text, rules)
    problems += _left_out(parsed, rules)
    if problems:
        raise TextProblems(problems)
    return parsed


def read_text(text: str, rules: TextRules) -> ParsedText:
    """The sections of the text, or ``TextProblems`` with every problem found in what it says."""
    parsed, problems = _read(text, rules)
    if problems:
        raise TextProblems(problems)
    return parsed


@dataclass
class _LeadIn:
    """A sentence that introduces a list (``These limits apply:``): it takes the markers of the list."""

    body: str
    block: int
    sentences: list[ParsedSentence]
    """The sentences of its section, where it goes at ``position`` once the list is read."""
    position: int
    step_ids: list[str] = field(default_factory=list)

    def close(self, rules: TextRules, problems: list[str]) -> None:
        if not self.step_ids:
            problems.append(f"a sentence without a step marker after it: {self.body!r}")
            return
        step_ids = tuple(dict.fromkeys(self.step_ids))
        sentence = _sentence(self.body, step_ids, self.block, False, rules, problems)
        self.sentences.insert(self.position, sentence)


def _read(text: str, rules: TextRules) -> tuple[ParsedText, list[str]]:
    problems: list[str] = []
    lines = _unwrap(text).split("\n")
    titles = {title.casefold(): title for title in rules.titles}
    sections: list[tuple[str, list[ParsedSentence]]] = []
    block = -1
    open_paragraph = False
    lead_in: _LeadIn | None = None
    for raw in lines:
        line = raw.strip()
        if not line:
            open_paragraph = False
            continue
        item = ITEM.match(line)
        if lead_in is not None and item is None:
            lead_in.close(rules, problems)
            lead_in = None
        heading = HEADING.match(line) if line.startswith("#") else None
        if heading is not None:
            title = _title(heading.group(1).strip(), titles)
            if title is None:
                problems.append(f"unknown section title {heading.group(1)!r}: use only {list(rules.titles)}")
                title = heading.group(1)
            sections.append((title, []))
            block, open_paragraph = -1, False
            continue
        if not sections:
            problems.append(f"text before the first section title: {line!r}")
            continue
        if item is not None:
            block, open_paragraph = block + 1, False
            content, list_item = item.group(1), True
        else:
            if not open_paragraph:
                block, open_paragraph = block + 1, True
            content, list_item = line, False
        found, rest = _sentences(content, block, list_item, rules, problems)
        sentences = sections[-1][1]
        sentences.extend(found)
        if lead_in is not None:
            lead_in.step_ids += [step_id for sentence in found for step_id in sentence.step_ids]
        if rest and not list_item and rest.endswith(":"):
            lead_in = _LeadIn(rest, block, sentences, len(sentences))
        elif rest:
            problems.append(f"a sentence without a step marker after it: {rest!r}")
    if lead_in is not None:
        lead_in.close(rules, problems)
    if not sections and not problems:
        problems.append("the text has no section")
    parsed = ParsedText(
        sections=tuple(ParsedSection(title, tuple(sentences)) for title, sentences in sections if sentences)
    )
    return parsed, problems


def _left_out(parsed: ParsedText, rules: TextRules) -> list[str]:
    """What the text leaves out: steps, phrases of terms, sentences of the system, the rule's definition."""
    sentences = [sentence for section in parsed.sections for sentence in section.sentences]
    rendered = {step_id for sentence in sentences for step_id in sentence.step_ids}
    cited = {
        step_id
        for sentence in sentences
        for step_id in sentence.step_ids
        if f"{step_id}.fixed_text" in sentence.names
    }
    problems = []
    for title, step_ids in rules.sections.items():
        for step_id in step_ids:
            if step_id not in rendered:
                problems.append(
                    f"the step [{step_id}] is not rendered: write a sentence about it "
                    f"in the section {title!r}, with [{step_id}] after it"
                )
            elif step_id in rules.fixed_texts and step_id not in cited:
                problems.append(
                    f"the step [{step_id}] has a sentence of the system: cite it as "
                    f"{{{step_id}.fixed_text}}, followed by [{step_id}], and do not rewrite it"
                )
    for step_id, phrase in rules.phrases.items():
        if step_id not in rendered:
            continue
        said = WORD.findall(
            " ".join(NAME.sub(" ", s.body) for s in sentences if step_id in s.step_ids).lower()
        )
        if not any(word.startswith(stem) for stem in _stems(phrase) for word in said):
            problems.append(
                f"the step [{step_id}] has a term, and its sentence does not say what it means: "
                f"write its phrase {phrase!r}, each placeholder replaced by the words for its slot"
            )
    if rules.definition is not None and not any(rules.definition in s.names for s in sentences):
        problems.append(
            f"the definition of the rule is not cited: write {{{rules.definition}}} "
            "at the end of a sentence of its own, after a colon"
        )
    return problems


def _stems(phrase: str) -> frozenset[str]:
    """The beginnings of the words that carry the meaning of a phrase: ``fight`` is said by ``fights``."""
    words = WORD.findall(PLACEHOLDER.sub(" ", phrase).lower())
    return frozenset(w[:4] if len(w) > 4 else w[:3] for w in words if len(w) >= 4 and w not in COMMON_WORDS)


def _title(heading: str, titles: Mapping[str, str]) -> str | None:
    """The section title of a heading; the steps the prompt lists after a title may be copied with it.

    A title with a word changed (``Why it is flagged``) is still that title: the report writes the
    title of the profile, not the one of the LLM.
    """
    with_steps = TITLE_WITH_STEPS.match(heading)
    for candidate in (heading, with_steps.group(1).strip() if with_steps is not None else None):
        if candidate is None:
            continue
        close = difflib.get_close_matches(candidate.casefold(), list(titles), n=1, cutoff=0.85)
        if close:
            return titles[close[0]]
    return None


def _unwrap(text: str) -> str:
    """The text without a code fence around it, and without a line break inside a name.

    Some models add the fence; some break a long line inside a name (``{ev_8709b27`` and
    ``746f6.end}`` on two lines), and a name has no spaces.
    """
    text = text.replace("\r\n", "\n").strip()
    fenced = FENCE.match(text)
    text = fenced.group(1) if fenced is not None else text
    return BROKEN_NAME.sub(r"{\1\2}", text)


def _sentences(
    line: str, block: int, list_item: bool, rules: TextRules, problems: list[str]
) -> tuple[list[ParsedSentence], str]:
    """The sentences of a line, and the words left after its last marker."""
    found: list[ParsedSentence] = []
    position = 0
    for run in MARKER_RUN.finditer(line):
        body = " ".join(line[position : run.start()].split())
        position = run.end()
        step_ids = tuple(dict.fromkeys(MARKER.findall(run.group())))
        if not body:
            problems.append(f"step markers without a sentence before them: {run.group().strip()!r}")
            continue
        found.append(_sentence(body, step_ids, block, list_item, rules, problems))
    rest = line[position:].strip()
    if rest and PUNCTUATION_ONLY.match(rest) and found:
        last = found[-1]
        found[-1] = ParsedSentence(
            llm_text=f"{last.body}{rest} {markers(last.step_ids)}",
            body=last.body + rest,
            step_ids=last.step_ids,
            names=last.names,
            entities=last.entities,
            block=last.block,
            list_item=last.list_item,
        )
        rest = ""
    return found, " ".join(rest.split())


def _sentence(
    body: str, step_ids: tuple[str, ...], block: int, list_item: bool, rules: TextRules, problems: list[str]
) -> ParsedSentence:
    for step_id in step_ids:
        if step_id not in rules.step_ids:
            problems.append(f"the marker [{step_id}] is not a step of the plan you received")
    names = tuple(dict.fromkeys(NAME.findall(body)))
    for name in names:
        if name in rules.step_ids:
            problems.append(
                f"{{{name}}} is a step, not a value: "
                f"say what the step says and put [{name}] after the sentence"
            )
        elif name not in rules.names:
            problems.append(f"{{{name}}} is not a name of the values table{_closest(name, rules.names)}")
        elif rules.entities.get(name):
            problems.append(
                f"{{{name}}} is the label of an entity that has a description: "
                f"name it with words of its description, marked with its ID, as [words]({name})"
            )
    if step_ids and all(rules.event_times.get(step_id) for step_id in step_ids):
        own = " and ".join(f"{{{time}}}" for time in rules.event_times[step_ids[0]])
        for name in names:
            if INTERVAL_TIME.fullmatch(name):
                problems.append(f"{{{name}}} is a time of an interval: the detection has its own, cite {own}")
    stray = STRAY_BRACES.search(NAME.sub(lambda match: " " * len(match.group()), body))
    if stray is not None:
        problems.append(
            f"braces that cite no name: {body[stray.start() : stray.end()]!r}; "
            "write braces only around the name of a value, as {name}"
        )
    entities = tuple((words.strip(), entity) for words, entity in ENTITY_MARK.findall(body))
    for words, entity in entities:
        if entity not in rules.entities:
            problems.append(f"{entity} is not an entity cited by the plan")
        else:
            problems.extend(_digits(words, rules, allowed_in=rules.entities[entity] or ""))
    for words, other in OTHER_MARK.findall(body):
        problems.append(
            f"[{words}]({other}) is not an entity: only an entity is marked as [words](ent_…)"
            f"{_instead(other, rules.names)}"
        )
    words_only = NAME.sub(" ", ENTITY_MARK.sub(" ", OTHER_MARK.sub(" ", body)))
    for left in dict.fromkeys(LEFT_ID.findall(words_only)):
        problems.append(
            f"the ID {left!r} is written in the words: cite a value as {{name}}, an entity as [words](ID)"
        )
    words_only = LEFT_ID.sub(" ", words_only)
    for code in dict.fromkeys(CODE.findall(words_only)):
        meaning = rules.codes.get(code)
        problems.append(
            f"the code {code!r} is written in the words: say what it means"
            + (f", {meaning!r}" if meaning is not None else "")
            + (
                ", each placeholder replaced by the words for its slot"
                if PLACEHOLDER.search(meaning or "")
                else ""
            )
        )
    problems.extend(_digits(words_only, rules))
    return ParsedSentence(
        llm_text=f"{body} {markers(step_ids)}",
        body=body,
        step_ids=step_ids,
        names=names,
        entities=entities,
        block=block,
        list_item=list_item,
    )


def _digits(words: str, rules: TextRules, allowed_in: str = "") -> list[str]:
    """Numbers the LLM wrote itself: every number must come from the table, by name (S4)."""
    allowed = set(TOKEN.findall(allowed_in))
    problems = []
    for token in TOKEN.findall(words):
        if not any(c.isdigit() for c in token) or token in allowed:
            continue
        parts = [part for part in token.split(".") if any(c.isdigit() for c in part)]
        if all(part in rules.rule_names for part in parts):
            continue
        problems.append(f"the number {token!r} is written in the text: cite every number by its {{name}}")
    return problems


def _closest(name: str, names: frozenset[str]) -> str:
    """A hint for the next attempt: the closest name of the same fact (``{missing_fields.value}``).

    Only names that start with the same ID or field are proposed, by the closest field:
    ``{iv_v99.start}`` must not become another interval.
    """
    head, _, field_name = name.partition(".")
    anchor, _, last = name.rpartition(".")
    if last in ("start", "end") and f"{anchor}.at" in names:
        return f": it is a single analysed frame, cite it as at {{{anchor}.at}}"
    same = sorted(n for n in names if n.split(".")[0] == head)
    if name == head and len(same) > 1:
        fields = [n for n in (f"{head}.start", f"{head}.end", f"{head}.at") if n in same]
        fields = fields or [n for n in (f"{head}.term", f"{head}.text") if n in same] or same[:2]
        return ": cite one of its values, such as " + " or ".join(f"{{{n}}}" for n in fields)
    if name == head and same:
        return f": {{{same[0]}}}"
    by_field = {n.partition(".")[2]: n for n in same}
    found = difflib.get_close_matches(field_name, list(by_field), n=1, cutoff=0.6)
    if found:
        return f": did you mean {{{by_field[found[0]]}}}?"
    return f": did you mean {{{head}}}?" if head in names else ""


def _instead(identifier: str, names: frozenset[str]) -> str:
    """The name to cite in place of a mark on something that is not an entity."""
    if identifier in names:
        return f"; write {{{identifier}}} instead"
    same = sorted(n for n in names if n.split(".")[0] == identifier)
    preferred = [n for n in (f"{identifier}.term", f"{identifier}.text") if n in same] or same[:1]
    return f"; write {{{preferred[0]}}} instead" if preferred else ""


def markers(step_ids: tuple[str, ...]) -> str:
    return "".join(f"[{step_id}]" for step_id in step_ids)
