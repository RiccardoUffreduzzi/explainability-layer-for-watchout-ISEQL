"""The ``glossary`` section: an entry for every term of the draft.

Visual predicates take their definition from ``AppConfig.relation_vocab``
(the text given to the VLM); audio classes, operators and events from the
file ``glossary.yaml``, which also holds every report phrase. A term the file does
not have keeps its name as phrase, with a ``not_available`` source.
"""

from collections.abc import Mapping, Sequence

from xai.contract.ids import term_id
from xai.contract.model import (
    EventRecord,
    GlossaryEntry,
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
        for node in rule.constraints:
            if isinstance(node, SelectionNode):
                predicates.extend(p for b in node.payload.branches for p in b.predicates)
            elif isinstance(node, TemporalOperatorNode):
                operators.setdefault(
                    node.payload.name,
                    node.payload.params[0].compare_domain if node.payload.params else "seconds",
                )
        predicates.extend(i.predicate for i in intervals)
        entries = []
        for term in dict.fromkeys(predicates):
            if is_audio(term, ctx.vocabulary):
                entries.append(self._audio_class(term))
            else:
                entries.append(self._predicate(term, ctx.vocabulary.descriptions))
        entries.extend(self._operator(name, unit) for name, unit in operators.items())
        entries.append(self._event(event.label))
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

    def _audio_class(self, term: str) -> GlossaryEntry:
        text = self.glossary.audio_classes.get(term)
        definition = text.definition if text else None
        return GlossaryEntry(
            term_id=term_id("audio_class", term),
            kind="audio_class",
            term=term,
            definition=definition,
            plain_template=text.plain_template if text else term,
            source=self._source("audio_classes", term, text is not None),
            source_detail=text.citation if text else None,
            unavailable=None
            if definition
            else {
                "definition": self._missing(
                    "AppConfig.audio_taxonomy only has keywords and glossary.yaml has no definition yet "
                    "(to copy from WACV Table 3)"
                )
            },
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
            source_detail=text.citation if text else None,
            unavailable=None
            if text and text.definition
            else {"definition": self._missing("glossary.yaml has no definition of this operator")},
        )

    def _event(self, label: str) -> GlossaryEntry:
        text = self.glossary.events.get(label)
        if text is None:
            return GlossaryEntry(
                term_id=term_id("event_model", label),
                kind="event_model",
                term=label,
                definition=None,
                plain_template=label,
                source=self._source("events", label, False),
                unavailable={"definition": self._missing("glossary.yaml has no entry for this event")},
            )
        return GlossaryEntry(
            term_id=term_id("event_model", label),
            kind="event_model",
            term=label,
            definition=text.definition,
            plain_template=text.plain_template,
            source="event_author",
            source_detail=f"{self.glossary.store} events.{label}"
            + (f", from {text.citation}" if text.citation else ""),
            unavailable=None
            if text.definition
            else {"definition": self._missing("glossary.yaml has no definition of this event")},
        )


def _readings(text: GlossaryText | None, unit: TimeUnit) -> list[ParameterReading] | None:
    """The parameter readings, in the unit the engine compares in."""
    if text is None or not text.parameter_readings:
        return None
    return [
        ParameterReading(condition=r.condition, phrase=r.phrase.replace("{unit}", unit))
        for r in text.parameter_readings
    ]
