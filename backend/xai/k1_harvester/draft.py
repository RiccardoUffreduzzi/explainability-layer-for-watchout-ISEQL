"""``DraftBuilder``: the sections of one detection put together into the draft."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from xai.contract.model import (
    ContractDraft,
    ContractMeta,
    Entity,
    EventRecord,
    GlossaryEntry,
    HarvestReport,
    IntervalRecord,
    Note,
    RuleRecord,
    Violation,
)
from xai.k1_harvester.checks.report import check_results, missing_fields, request_echo, sorted_notes
from xai.k1_harvester.context import HarvestContext
from xai.k1_harvester.gaps import KEYFRAMES


@dataclass
class DraftBuilder:
    """Collects the sections in the order the harvesters write them."""

    ctx: HarvestContext
    meta: ContractMeta | None = None
    event: EventRecord | None = None
    rule: RuleRecord | None = None
    entities: list[Entity] = field(default_factory=list)
    intervals: list[IntervalRecord] = field(default_factory=list)
    glossary: list[GlossaryEntry] = field(default_factory=list)
    notes: list[Note] = field(default_factory=list)

    def build(self, violations: Sequence[Violation] = ()) -> ContractDraft:
        """The immutable draft, with the results of the checks (passed when there are no violations).

        ``actions`` is null with ``keyframes_not_persisted`` until WatchOut stores key frames.
        """
        if self.meta is None or self.event is None or self.rule is None:
            raise ValueError("the draft needs contract_meta, event and rule")
        data: dict[str, Any] = {
            "contract_meta": _data(self.meta),
            "event": _data(self.event),
            "rule": _data(self.rule),
            "entities": [_data(e) for e in self.entities],
            "intervals": [_data(i) for i in self.intervals],
            "glossary": [_data(g) for g in self.glossary],
            "unavailable": {"actions": _data(KEYFRAMES)},
        }
        report = HarvestReport(
            request=request_echo(self.ctx),
            row_match=self.ctx.row_match,
            checks=check_results(violations),
            missing_fields=missing_fields(data),
            notes=sorted_notes(self.notes),
        )
        return ContractDraft(
            contract_meta=self.meta,
            event=self.event,
            rule=self.rule,
            entities=self.entities,
            intervals=self.intervals,
            actions=None,
            glossary=self.glossary,
            unavailable={"actions": KEYFRAMES},
            harvest_report=report,
        )


def _data(record: BaseModel) -> Any:
    return record.model_dump(mode="json")
