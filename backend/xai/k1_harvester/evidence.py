"""The ``entities`` and ``intervals`` sections: the interval rows that produce the row.

WatchOut's lineage query gives, for each row, its witnesses: the interval rows of one
branch that produce it, each bound to a variable of the branch and with the entities in
the argument positions the rule reads. K1 reports those intervals and those entities;
the criterion goes to ``harvest_report`` as ``selection_basis``.

Every entity also gets the description the VLM gave of it in one frame
(``VisualPerFrame``), chosen by ``choose_description`` and copied as saved.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field

from xai.contract.ids import audio_interval_id, canonical_row, entity_id, visual_interval_id
from xai.contract.model import (
    Entity,
    EventRecord,
    IntervalBinding,
    IntervalRecord,
    Note,
    ReidEvidence,
    VlmDescription,
)
from xai.contract.primitives import Source, SourceRef, Stage, Unavailable
from xai.contract.reasons import NoteCode, Reason
from xai.k1_harvester.context import HarvestContext
from xai.k1_harvester.descriptions import Window, choose_description
from xai.k1_harvester.gaps import REID, VISUAL_CONFIDENCE
from xai.k1_harvester.ports import (
    AudioIntervalRow,
    EngineError,
    FrameDescriptionRow,
    VisualIntervalRow,
    WitnessArg,
)
from xai.k1_harvester.timebase import TimeBase

SELECTION_BASIS = "engine_lineage"


@dataclass
class UsedInterval:
    """An interval row in the witnesses of the row with its variables and its arguments."""

    table: str
    row_id: int
    bindings: list[IntervalBinding] = field(default_factory=list)
    args: tuple[WitnessArg, ...] = ()


def used_intervals(ctx: HarvestContext) -> dict[tuple[str, int], UsedInterval]:
    """The interval rows of the row's witnesses, in witness order, each once.

    The arguments are those of the first witness that has the interval: the argument
    positions of an interval are the same in every witness of the row.
    """
    found: dict[tuple[str, int], UsedInterval] = {}
    for witness in ctx.row.witnesses:
        for interval in witness.intervals:
            used = found.setdefault(interval.key, UsedInterval(interval.table, interval.row_id))
            binding = IntervalBinding(branch=witness.branch, variable=interval.alias)
            if binding not in used.bindings:
                used.bindings.append(binding)
            if not used.args:
                used.args = tuple(sorted(interval.args, key=lambda a: a.position))
    order = {b.name: i for i, b in enumerate(ctx.layout.branches)}
    for used in found.values():
        used.bindings.sort(key=lambda b: (order.get(b.branch, len(order)), b.variable))
    return found


def confidence_source(
    constant: float | None, provider: str | None, row: AudioIntervalRow
) -> dict[str, Source] | None:
    """Source of ``confidence`` when it is the value WatchOut's code writes for the provider.

    The value stays as read; the source says that it comes from the code and not from
    the audio model.
    """
    if provider is None or constant is None or row.confidence != constant:
        return None
    return {
        "confidence": SourceRef(
            stage=Stage.CODE, record_id=f"AudioServiceImpl.constant_confidence({provider})", mode="read"
        )
    }


def describe_entity(
    analysis_id: str,
    timebase: TimeBase,
    class_id: int,
    rows: Sequence[FrameDescriptionRow],
    windows: Sequence[Window],
    reference_frame: int | None,
) -> tuple[VlmDescription | None, dict[str, Unavailable]]:
    """``vlm_description`` of one entity and the reasons for what is null in it.

    ``rows`` are the ``VisualPerFrame`` rows of the entity; the row is chosen by
    ``choose_description`` and its text is copied unchanged.
    """
    chosen = choose_description(rows, windows, reference_frame)
    if chosen is None:
        reason = Unavailable(
            reason=Reason.ENTITY_NOT_DESCRIBED,
            detail=f"VisualPerFrame has no description of ClassID {class_id} in this analysis",
        )
        return None, {"vlm_description": reason}
    row = chosen.row
    timed = timebase.from_frames(row.frame, row.frame, "vlm_description.anchor")
    description = VlmDescription(
        text=row.description,
        anchor=timed.anchor,
        in_evidence=chosen.in_evidence,
        source_ref=SourceRef(
            stage=Stage.VLM,
            record_id=f"VisualPerFrame/{analysis_id}:{row.frame}:{row.class_id}:{row.block}",
            mode="read",
        ),
    )
    return description, timed.unavailable


@dataclass(frozen=True)
class Participant:
    """An entity in an argument position of a visual interval of the witnesses."""

    relation_id: int
    class_id: int
    class_name: str


class EvidenceHarvester:
    def harvest(
        self, ctx: HarvestContext, event: EventRecord
    ) -> tuple[list[Entity], list[IntervalRecord], list[Note]]:
        used = used_intervals(ctx)
        visual_ids = [u.row_id for u in used.values() if u.table == "VisualPerInterval"]
        audio_ids = [u.row_id for u in used.values() if u.table == "AudioPerInterval"]
        visual_rows = (
            {r.relation_id: r for r in ctx.records.visual_intervals(visual_ids)} if visual_ids else {}
        )
        audio_rows = {r.interval_id: r for r in ctx.records.audio_intervals(audio_ids)} if audio_ids else {}
        missing = [i for i in visual_ids if i not in visual_rows] + [
            i for i in audio_ids if i not in audio_rows
        ]
        if missing:
            raise EngineError(f"the lineage names interval rows that the database does not have: {missing}")

        intervals: list[IntervalRecord] = []
        participants: list[Participant] = []
        for u in used.values():
            if u.table == "AudioPerInterval":
                intervals.append(self._audio(ctx, audio_rows[u.row_id], u))
                continue
            relation = visual_rows[u.row_id]
            args = [
                Participant(relation.relation_id, a.class_id, a.class_name)
                for a in u.args
                if a.class_id is not None and a.class_name is not None
            ]
            participants.extend(args)
            intervals.append(self._visual(ctx, relation, u, args))
        intervals.sort(key=lambda i: (i.interval_id[3], int(i.interval_id[4:])))

        windows: dict[int, list[Window]] = {}
        for p in sorted(participants, key=lambda p: (visual_rows[p.relation_id].start_frame, p.relation_id)):
            relation = visual_rows[p.relation_id]
            window = Window(relation.start_frame, relation.end_frame)
            if window not in windows.setdefault(p.class_id, []):
                windows[p.class_id].append(window)
        row_entities = {int(a.entity_id[len("ent_") :]): a.class_ for a in event.arguments}
        entities = self._entities(ctx, row_entities, participants, windows, event.interval.start_frame)

        notes = [Note(code=NoteCode.SELECTION_BASIS, detail=self._basis(ctx, used))]
        return entities, intervals, notes

    @staticmethod
    def _visual(
        ctx: HarvestContext, row: VisualIntervalRow, used: UsedInterval, args: list[Participant]
    ) -> IntervalRecord:
        """A visual interval with the entities in the argument positions the rule reads."""
        timed = ctx.timebase.from_frames(row.start_frame, row.end_frame, "anchor")
        sources: dict[str, Source] = {}
        if args:
            sources["args"] = SourceRef(
                stage=Stage.REID,
                record_id="VisualParticipant/" + ",".join(f"{p.relation_id}:{p.class_id}" for p in args),
                mode="read",
            )
        return IntervalRecord(
            interval_id=visual_interval_id(row.relation_id),
            source="VisualPerInterval",
            predicate=row.relation_type,
            args=[entity_id(p.class_id) for p in args],
            args_ordered=len(args) == len(used.args),
            anchor=timed.anchor,
            confidence=None,
            used_by_rule=True,
            bindings=list(used.bindings),
            source_ref=SourceRef(
                stage=Stage.IAD, record_id=f"VisualPerInterval/{row.relation_id}", mode="read"
            ),
            sources=sources or None,
            unavailable={"confidence": VISUAL_CONFIDENCE, **timed.unavailable},
        )

    @staticmethod
    def _audio(ctx: HarvestContext, row: AudioIntervalRow, used: UsedInterval) -> IntervalRecord:
        timed = ctx.timebase.from_frames(row.start_frame, row.end_frame, "anchor")
        unavailable: dict[str, Unavailable] = dict(timed.unavailable)
        if row.confidence is None:
            unavailable["confidence"] = Unavailable(
                reason=Reason.ANALYSIS_RECORD_MISSING,
                detail=f"AudioPerInterval {row.interval_id} has no Confidence",
            )
        provider = ctx.analysis.audio_provider
        constant = ctx.readings.facts.constant_audio_confidence(provider) if provider is not None else None
        return IntervalRecord(
            interval_id=audio_interval_id(row.interval_id),
            source="AudioPerInterval",
            predicate=row.audio_class,
            args=[],
            args_ordered=True,
            anchor=timed.anchor,
            confidence=row.confidence,
            used_by_rule=True,
            bindings=list(used.bindings),
            source_ref=SourceRef(
                stage=Stage.AUDIO, record_id=f"AudioPerInterval/{row.interval_id}", mode="read"
            ),
            sources=confidence_source(constant, provider, row),
            unavailable=unavailable or None,
        )

    @staticmethod
    def _entities(
        ctx: HarvestContext,
        row_entities: dict[int, str],
        participants: list[Participant],
        windows: dict[int, list[Window]],
        event_start_frame: int | None,
    ) -> list[Entity]:
        """The entities of the intervals' arguments and of the row, each with its VLM description.

        ``windows``: the frames of the intervals each entity is an argument of, in start order.
        """
        first: dict[int, Participant] = {}
        for p in sorted(participants, key=lambda p: (p.relation_id, p.class_id)):
            first.setdefault(p.class_id, p)
        class_ids = sorted(set(first) | set(row_entities))
        described: dict[int, list[FrameDescriptionRow]] = {}
        if class_ids:
            for row in ctx.records.frame_descriptions(ctx.analysis.analysis_id, class_ids):
                described.setdefault(row.class_id, []).append(row)
        row_source = SourceRef(
            stage=Stage.ISEQL,
            record_id=f"{ctx.detection.record}/{canonical_row(ctx.row.values)}",
            mode="read",
        )
        entities = []
        for class_id in class_ids:
            participant = first.get(class_id)
            if participant is not None:
                name = participant.class_name
                source = SourceRef(
                    stage=Stage.REID,
                    record_id=f"VisualParticipant/{participant.relation_id}:{participant.class_id}",
                    mode="read",
                )
            else:
                name, source = row_entities[class_id], row_source
            description, missing = describe_entity(
                ctx.analysis.analysis_id,
                ctx.timebase,
                class_id,
                described.get(class_id, []),
                windows.get(class_id, []),
                event_start_frame,
            )
            entities.append(
                Entity(
                    entity_id=entity_id(class_id),
                    class_=name,
                    reid_evidence=ReidEvidence(
                        status="not_available", gallery_match_id=None, similarity=None
                    ),
                    vlm_description=description,
                    source_ref=source,
                    unavailable={"reid_evidence": REID, **missing},
                )
            )
        return entities

    @staticmethod
    def _basis(ctx: HarvestContext, used: dict[tuple[str, int], UsedInterval]) -> str:
        """``engine_lineage``: how many witnesses, and which interval each variable took."""
        witnesses = len(ctx.row.witnesses)
        bound: dict[tuple[str, str], list[str]] = {}
        for u in used.values():
            iid = (
                visual_interval_id(u.row_id)
                if u.table == "VisualPerInterval"
                else audio_interval_id(u.row_id)
            )
            for b in u.bindings:
                bound.setdefault((b.branch, b.variable), []).append(iid)
        order = {b.name: i for i, b in enumerate(ctx.layout.branches)}
        parts = [
            f"{branch}.{variable} = {', '.join(ids)}"
            for (branch, variable), ids in sorted(
                bound.items(), key=lambda kv: (order.get(kv[0][0], len(order)), kv[0][1])
            )
        ]
        plural = "witness" if witnesses == 1 else "witnesses"
        return f"{SELECTION_BASIS}: {witnesses} {plural} in WatchOut's lineage; " + "; ".join(parts)
