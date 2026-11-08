"""The ``glossary`` section: an entry for every term of the draft.

Definitions come from WatchOut where it has them: visual predicates from
``AppConfig.relation_vocab`` (the text given to the VLM), audio classes from the
keywords of ``AppConfig.audio_taxonomy``, the event from its rule saved in ``EventSpec``.
Operators and comparisons (identity, attribute_comparison and duration nodes) are
formulas of ``glossary.yaml``, which also holds every report phrase. A term the file
does not have keeps its name as phrase, with a ``not_available`` source.
"""

from collections.abc import Mapping, Sequence

from xai.contract.ids import comparison_term, term_id
from xai.contract.model import (
    AttributeComparisonNode,
    DurationNode,
    EventRecord,
    GlossaryEntry,
    IdentityNode,
    IntervalRecord,
    ParameterReading,
    RuleRecord,
    SelectionNode,
    TemporalOperatorNode,
    TimeUnit,
)
from xai.contract.primitives import SourceRef, Stage, Unavailable
from xai.contract.reasons import Reason
from xai.k1_harvester.context import HarvestContext
from xai.k1_harvester.predicates import is_audio
from xai.k1_harvester.resource_data import Glossary, GlossaryText


class GlossaryHarvester:
    def __init__(self, glossary: Glossary) -> None:
        self.glossary = glossary

    def harvest(
        self, ctx: HarvestContext, rule: RuleRecord, intervals: Sequence[IntervalRecord], event: EventRecord
    ) -> list[GlossaryEntry]:
        predicates: list[str] = []
        operators: dict[str, TimeUnit] = {}
        comparisons: list[str] = []
        for node in rule.constraints:
            if isinstance(node, SelectionNode):
                predicates.extend(p for b in node.payload.branches for p in b.predicates)
            elif isinstance(node, TemporalOperatorNode):
                operators.setdefault(
                    node.payload.name,
                    node.payload.params[0].compare_domain if node.payload.params else "seconds",
                )
            elif isinstance(node, (IdentityNode, AttributeComparisonNode, DurationNode)):
                comparisons.append(comparison_term(node.kind, node.payload.op))
        predicates.extend(i.predicate for i in intervals)
        entries = []
        for term in dict.fromkeys(predicates):
            if is_audio(term, ctx.vocabulary):
                entries.append(self._audio_class(term, ctx.vocabulary.audio_keywords))
            else:
                entries.append(self._predicate(term, ctx.vocabulary.descriptions))
        entries.extend(self._operator(name, unit) for name, unit in operators.items())
        entries.extend(self._comparison(name) for name in dict.fromkeys(comparisons))
        entries.append(self._event(event.label, rule, ctx))
        return sorted(entries, key=lambda e: e.term_id)

    def _source(self, section: str, term: str, found: bool) -> SourceRef:
        return SourceRef(
            stage=Stage.CODE,
            store=self.glossary.store,
            record_id=f"{section}.{term}",
            mode="read" if found else "not_available",
        )

    def _missing(self, what: str) -> Unavailable:
        return Unavailable(reason=Reason.GLOSSARY_DEFINITION_NOT_IN_SYSTEM, detail=what)

    def _predicate(self, term: str, descriptions: Mapping[str, str]) -> GlossaryEntry:
        text = self.glossary.predicates.get(term)
        definition = descriptions.get(term)
        source = SourceRef(
            stage=Stage.CONFIG,
            store="AppConfig",
            record_id=f"relation_vocab.relation_descriptions.{term}",
            mode="read" if definition else "not_available",
        )
        return GlossaryEntry(
            term_id=term_id("predicate", term),
            kind="predicate",
            term=term,
            definition=definition or None,
            plain_template=text.plain_template if text else term,
            source=source,
            sources={"plain_template": self._source("predicates", term, text is not None)},
            unavailable=None
            if definition
            else {
                "definition": self._missing("AppConfig.relation_vocab has no description for this relation")
            },
        )

    def _audio_class(self, term: str, keywords: Mapping[str, Sequence[str]]) -> GlossaryEntry:
        text = self.glossary.audio_classes.get(term)
        words = keywords.get(term)
        definition = (
            f"WatchOut assigns this class when the audio model answers with one of: {', '.join(words)}."
            if words
            else None
        )
        return GlossaryEntry(
            term_id=term_id("audio_class", term),
            kind="audio_class",
            term=term,
            definition=definition,
            plain_template=text.plain_template if text else term,
            source=SourceRef(
                stage=Stage.CONFIG,
                store="AppConfig",
                record_id=f"audio_taxonomy.keywords.{term}",
                mode="read" if definition else "not_available",
            ),
            sources={"plain_template": self._source("audio_classes", term, text is not None)},
            unavailable=None
            if definition
            else {"definition": self._missing("AppConfig.audio_taxonomy has no keywords for this class")},
        )

    def _operator(self, name: str, unit: TimeUnit) -> GlossaryEntry:
        text = self.glossary.operators.get(name)
        return GlossaryEntry(
            term_id=term_id("operator", name),
            kind="operator",
            term=name,
            definition=text.definition if text else None,
            plain_template=text.plain_template if text else name,
            parameter_readings=_readings(text, unit),
            source=self._source("operators", name, text is not None),
            unavailable=None
            if text and text.definition
            else {"definition": self._missing("glossary.yaml has no definition of this operator")},
        )

    def _comparison(self, name: str) -> GlossaryEntry:
        text = self.glossary.comparisons.get(name)
        return GlossaryEntry(
            term_id=term_id("comparison", name),
            kind="comparison",
            term=name,
            definition=text.definition if text else None,
            plain_template=text.plain_template if text else name,
            source=self._source("comparisons", name, text is not None),
            unavailable=None
            if text and text.definition
            else {"definition": self._missing("glossary.yaml has no definition of this comparison")},
        )

    def _event(self, label: str, rule: RuleRecord, ctx: HarvestContext) -> GlossaryEntry:
        # The event is defined by its rule: the text saved in EventSpec, or the rendered
        # structure when the model has no iseql_text (rule.expression_saved says the same).
        text = self.glossary.events.get(label)
        saved = ctx.rule.model.get("iseql_text")
        has_saved = isinstance(saved, str) and bool(saved.strip())
        return GlossaryEntry(
            term_id=term_id("event_model", label),
            kind="event_model",
            term=label,
            definition=rule.expression_saved,
            plain_template=text.plain_template if text else label,
            source=ctx.rule.source("/iseql_text") if has_saved else rule.structure_ref,
            sources={"plain_template": self._source("events", label, text is not None)},
        )


def _readings(text: GlossaryText | None, unit: TimeUnit) -> list[ParameterReading] | None:
    """The parameter readings, in the unit the engine compares in."""
    if text is None or not text.parameter_readings:
        return None
    return [
        ParameterReading(condition=r.condition, phrase=r.phrase.replace("{unit}", unit))
        for r in text.parameter_readings
    ]
