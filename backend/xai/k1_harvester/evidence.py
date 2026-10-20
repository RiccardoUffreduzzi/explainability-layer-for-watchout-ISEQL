"""The ``entities`` and ``intervals`` sections: the evidence pertinent to the row.

WatchOut does not store which intervals a rule used, so K1 reports the pertinent
ones, without saying they were used: intervals of the predicates of the row's
branch and, for the visual ones, with at least one entity of the row when the row
has entities. The criterion goes to ``harvest_report`` as ``selection_basis``.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from xai.contract.ids import audio_interval_id, canonical_row, entity_id, visual_interval_id
from xai.contract.model import Entity, EventRecord, IntervalRecord, Note, ReidEvidence
from xai.contract.primitives import Source, SourceRef, Stage, Unavailable
from xai.contract.reasons import NoteCode, Reason
from xai.k1_harvester.context import HarvestContext
from xai.k1_harvester.gaps import REID, VISUAL_CONFIDENCE
from xai.k1_harvester.ports import AudioIntervalRow, ParticipantRow, VisualIntervalRow
from xai.k1_harvester.predicates import branch_predicates, is_audio
from xai.k1_harvester.resource_data import PipelineConstants


@dataclass(frozen=True)
class OrderedArgs:
    participants: tuple[ParticipantRow, ...]
    ordered: bool
    """True when the signature has a different class in each slot and fixes the order."""


def order_args(participants: Sequence[ParticipantRow], slots: Sequence[Sequence[str]] | None) -> OrderedArgs:
    """The participants in the order of the predicate's signature, when the signature decides it.

    ``VisualParticipant`` has no position column: with a class per slot the order
    is the signature's; with two slots of the same class (``(PersonID, PersonID)``)
    or participants that do not fit the slots, the order is by ``ClassID`` and
    ``ordered`` is false.
    """
    by_class_id = tuple(sorted(participants, key=lambda p: p.class_id))
    if not slots:
        return OrderedArgs(by_class_id, False)
    classes = [set(slot) for slot in slots]
    if any(a & b for i, a in enumerate(classes) for b in classes[i + 1 :]):
        return OrderedArgs(by_class_id, False)
    remaining = list(by_class_id)
    ordered = []
    for slot in classes:
        fitting = [p for p in remaining if p.class_name in slot]
        if len(fitting) != 1:
            return OrderedArgs(by_class_id, False)
        ordered.append(fitting[0])
        remaining.remove(fitting[0])
    if remaining:
        return OrderedArgs(by_class_id, False)
    return OrderedArgs(tuple(ordered), True)


def confidence_source(
    constants: PipelineConstants, provider: str | None, row: AudioIntervalRow
) -> dict[str, Source] | None:
    """Source of ``confidence`` when it is the value WatchOut's code writes for the provider.

    The value stays as read; the source says that it comes from the code and not from
    the audio model. K2 decides what that means for the explanation.
    """
    fixed = constants.constant_audio_confidence
    if provider not in fixed.providers or row.confidence != fixed.value:
        return None
    return {
        "confidence": SourceRef(
            stage=Stage.CODE, store=constants.store, record_id="constant_audio_confidence", mode="read"
        )
    }


class EvidenceHarvester:
    def __init__(self, constants: PipelineConstants) -> None:
        self.constants = constants

    def harvest(
        self, ctx: HarvestContext, event: EventRecord
    ) -> tuple[list[Entity], list[IntervalRecord], list[Note]]:
        predicates = [p for b in ctx.origin.branches for p in branch_predicates(b)]
        predicates = list(dict.fromkeys(predicates))
        visual = [p for p in predicates if not is_audio(p, ctx.vocabulary)]
        audio = [p for p in predicates if is_audio(p, ctx.vocabulary)]
        row_entities = {int(a.entity_id[len("ent_") :]): a.class_ for a in event.arguments}

        visual_rows = ctx.records.visual_intervals(ctx.analysis.analysis_id, set(visual)) if visual else []
        participants = ctx.records.participants([r.relation_id for r in visual_rows]) if visual_rows else []
        by_relation: dict[int, list[ParticipantRow]] = {}
        for p in participants:
            by_relation.setdefault(p.relation_id, []).append(p)
        if row_entities:
            visual_rows = [
                r
                for r in visual_rows
                if any(p.class_id in row_entities for p in by_relation.get(r.relation_id, []))
            ]
        audio_rows = ctx.records.audio_intervals(ctx.analysis.analysis_id, set(audio)) if audio else []

        intervals = [self._audio(ctx, r) for r in audio_rows]
        intervals += [self._visual(ctx, r, by_relation.get(r.relation_id, [])) for r in visual_rows]
        intervals.sort(key=lambda i: (i.interval_id[3], int(i.interval_id[4:])))
        reported = [p for r in visual_rows for p in by_relation.get(r.relation_id, [])]
        entities = self._entities(ctx, row_entities, reported)

        notes = [Note(code=NoteCode.SELECTION_BASIS, detail=self._basis(ctx, visual, audio, row_entities))]
        return entities, intervals, notes

    def _visual(
        self, ctx: HarvestContext, row: VisualIntervalRow, participants: list[ParticipantRow]
    ) -> IntervalRecord:
        signature = ctx.vocabulary.signatures.get(row.relation_type)
        args = order_args(participants, ctx.vocabulary.slots.get(row.relation_type))
        timed = ctx.timebase.from_frames(row.start_frame, row.end_frame, "anchor")
        sources: dict[str, Source] = {}
        if participants:
            sources["args"] = SourceRef(
                stage=Stage.REID,
                store="VisualParticipant",
                record_id=",".join(
                    f"{p.relation_id}:{p.class_id}" for p in sorted(participants, key=lambda p: p.class_id)
                ),
                mode="read",
            )
        if args.ordered and signature is not None:
            sources["args_order"] = SourceRef(
                stage=Stage.CONFIG,
                store="AppConfig",
                record_id=f"relation_vocab.relation_classids[{row.relation_type}] = {signature}",
                mode="read",
            )
        return IntervalRecord(
            interval_id=visual_interval_id(row.relation_id),
            source="VisualPerInterval",
            predicate=row.relation_type,
            args=[entity_id(p.class_id) for p in args.participants],
            args_ordered=args.ordered,
            anchor=timed.anchor,
            confidence=None,
            source_ref=SourceRef(
                stage=Stage.IAD, store="VisualPerInterval", record_id=str(row.relation_id), mode="read"
            ),
            sources=sources or None,
            unavailable={"confidence": VISUAL_CONFIDENCE, **timed.unavailable},
        )

    def _audio(self, ctx: HarvestContext, row: AudioIntervalRow) -> IntervalRecord:
        timed = ctx.timebase.from_frames(row.start_frame, row.end_frame, "anchor")
        unavailable: dict[str, Unavailable] = dict(timed.unavailable)
        if row.confidence is None:
            unavailable["confidence"] = Unavailable(
                reason=Reason.ANALYSIS_RECORD_MISSING,
                detail=f"AudioPerInterval {row.interval_id} has no Confidence",
            )
        return IntervalRecord(
            interval_id=audio_interval_id(row.interval_id),
            source="AudioPerInterval",
            predicate=row.audio_class,
            args=[],
            args_ordered=True,
            anchor=timed.anchor,
            confidence=row.confidence,
            source_ref=SourceRef(
                stage=Stage.AUDIO, store="AudioPerInterval", record_id=str(row.interval_id), mode="read"
            ),
            sources=confidence_source(self.constants, ctx.analysis.audio_provider, row),
            unavailable=unavailable or None,
        )

    @staticmethod
    def _entities(
        ctx: HarvestContext, row_entities: dict[int, str], participants: list[ParticipantRow]
    ) -> list[Entity]:
        first: dict[int, ParticipantRow] = {}
        for p in sorted(participants, key=lambda p: (p.relation_id, p.class_id)):
            first.setdefault(p.class_id, p)
        row_source = SourceRef(
            stage=Stage.ISEQL, store=ctx.detection.store, record_id=canonical_row(ctx.row.values), mode="read"
        )
        entities = []
        for class_id in sorted(set(first) | set(row_entities)):
            participant = first.get(class_id)
            if participant is not None:
                name = participant.class_name
                source = SourceRef(
                    stage=Stage.REID,
                    store="VisualParticipant",
                    record_id=f"{participant.relation_id}:{participant.class_id}",
                    mode="read",
                )
            else:
                name, source = row_entities[class_id], row_source
            entities.append(
                Entity(
                    entity_id=entity_id(class_id),
                    class_=name,
                    reid_evidence=ReidEvidence(
                        status="not_available", gallery_match_id=None, similarity=None
                    ),
                    source_ref=source,
                    unavailable={"reid_evidence": REID},
                )
            )
        return entities

    @staticmethod
    def _basis(ctx: HarvestContext, visual: list[str], audio: list[str], row_entities: dict[int, str]) -> str:
        names = [b.name for b in ctx.origin.branches]
        where = f"branch {names[0]}" if len(names) == 1 else f"branches {', '.join(names)}"
        parts = []
        if visual:
            part = f"predicates of {where} {{{', '.join(visual)}}}"
            if row_entities:
                ids = ", ".join(str(i) for i in sorted(row_entities))
                part += f" and intervals with at least one entity of the row {{{ids}}}"
            parts.append(part)
        if audio:
            parts.append(f"audio classes of {where} {{{', '.join(audio)}}}")
        return "pertinence_filter: " + "; ".join(parts)
