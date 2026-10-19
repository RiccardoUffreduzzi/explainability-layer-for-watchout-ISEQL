"""``StageHarvester``: takes a single row in input and produces a checked draft in output.

The section harvesters run in a fixed order (Meta, Rule, Modality, Evidence,
Glossary); then both closing checks run on the whole draft, so a failure lists
every violation at once. Nothing is produced if there is a problem
"""

from xai.contract.model import ContractDraft
from xai.contract.serialization import draft_to_data
from xai.k1_harvester.checks.completeness import check_completeness
from xai.k1_harvester.checks.referential_closure import check_referential_closure
from xai.k1_harvester.context import HarvestContext
from xai.k1_harvester.draft import DraftBuilder
from xai.k1_harvester.evidence import EvidenceHarvester
from xai.k1_harvester.glossary import GlossaryHarvester
from xai.k1_harvester.locate import EventLocator
from xai.k1_harvester.meta import MetaHarvester
from xai.k1_harvester.modality import ModalityHarvester
from xai.k1_harvester.ports import Clock, WatchOutReader
from xai.k1_harvester.request import HarvestRequest
from xai.k1_harvester.resource_data import Glossary, PipelineConstants
from xai.k1_harvester.result import HarvestFailure
from xai.k1_harvester.rule.rule_harvester import RuleHarvester


class StageHarvester:
    def __init__(
        self, reader: WatchOutReader, clock: Clock, glossary: Glossary, constants: PipelineConstants
    ) -> None:
        self.locator = EventLocator(reader)
        self.clock = clock
        self.meta = MetaHarvester(glossary, constants)
        self.rule = RuleHarvester()
        self.modality = ModalityHarvester()
        self.evidence = EvidenceHarvester(constants)
        self.glossary = GlossaryHarvester(glossary)

    def harvest(self, request: HarvestRequest) -> ContractDraft:
        """The draft of the requested row; ``HarvestFailure`` when there cannot be a faithful one."""
        readings = self.locator.readings(request.analysis_id, request.params)
        return self.draft(self.locator.locate(request, readings, self.clock.now()))

    def draft(self, ctx: HarvestContext) -> ContractDraft:
        builder = DraftBuilder(ctx)
        builder.meta = self.meta.harvest(ctx)
        builder.rule, notes = self.rule.harvest(ctx)
        builder.notes.extend(notes)
        builder.event, notes = self.modality.harvest(ctx)
        builder.notes.extend(notes)
        builder.entities, builder.intervals, notes = self.evidence.harvest(ctx, builder.event)
        builder.notes.extend(notes)
        builder.glossary = self.glossary.harvest(ctx, builder.rule, builder.intervals, builder.event)
        draft = builder.build()
        violations = check_completeness(draft_to_data(draft)) + check_referential_closure(draft)
        if violations:
            raise HarvestFailure.checks(tuple(violations))
        return draft
