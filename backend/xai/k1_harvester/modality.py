"""The ``event`` section: the detection, its arguments and the detections per modality.

``resolve_origin`` reads where the located row comes from in its lineage; ``EventLocator``
calls it, because the rule and evidence sections need the row's branches too.
``ModalityHarvester`` writes the section.
"""

from xai.contract.ids import canonical_row
from xai.contract.model import (
    Argument,
    Condition,
    EventRecord,
    Modality,
    ModalityDetection,
    ModalityRules,
    Note,
    OriginBasis,
    OriginMatch,
    RuleRef,
)
from xai.contract.primitives import SourceRef, Stage, Unavailable
from xai.contract.reasons import InputError, Reason
from xai.k1_harvester.context import (
    MODALITY_CONDITIONS,
    AnalysisReadings,
    HarvestContext,
    OriginMatchRow,
    RowOrigin,
)
from xai.k1_harvester.ports import DetectedRow, DetectionRecord, EngineError, ResultColumn
from xai.k1_harvester.result import HarvestFailure
from xai.k1_harvester.rows import class_id, extent_anchor, row_branches, row_columns

CONDITION_MODALITY: dict[Condition, Modality] = {"A": "visual", "B": "audio"}

LINEAGE_METHOD = "engine_lineage"
"""``origin_basis.method``: the witnesses of the row in WatchOut's lineage query."""

TABLE_MODALITY: dict[str, Modality] = {"VisualPerInterval": "visual", "AudioPerInterval": "audio"}


def row_source(detection: DetectionRecord, row: DetectedRow) -> SourceRef:
    """SourceRef of a detection row: the row in canonical JSON."""
    return SourceRef(
        stage=Stage.ISEQL, record_id=f"{detection.record}/{canonical_row(row.values)}", mode="read"
    )


def resolve_origin(readings: AnalysisReadings, detection: DetectionRecord, row: DetectedRow) -> RowOrigin:
    """Modality and branches of the row, read from its witnesses.

    A condition C row is also matched with the rows of Evento_A and Evento_B that the
    same interval rows produce
    """
    rule = detection.rule
    absent = tuple(
        modality
        for modality, condition in MODALITY_CONDITIONS.items()
        if readings.rule(rule.event_type, condition) is None
    )
    branches = row_branches(detection.layout, row)
    if rule.condition in CONDITION_MODALITY:
        return RowOrigin(
            modality=CONDITION_MODALITY[rule.condition],
            branches=branches,
            modality_sets=(detection,),
            absent_modalities=absent,
        )
    modalities = {TABLE_MODALITY[i.table] for w in row.witnesses for i in w.intervals}
    present = [m for m in MODALITY_CONDITIONS if m not in absent]
    sets = tuple(_modality_detection(readings, rule.event_type, m) for m in present)
    produced_by = {w.keys for w in row.witnesses}
    matched = tuple(
        OriginMatchRow(modality=modality, detection=detection, row=other)
        for modality, detection in zip(present, sets, strict=True)
        for other in detection.rows
        if any(w.keys in produced_by for w in other.witnesses)
    )
    return RowOrigin(
        modality="both" if len(modalities) == 2 else modalities.pop(),
        branches=branches,
        modality_sets=sets,
        absent_modalities=absent,
        matched=matched,
    )


def _modality_detection(readings: AnalysisReadings, event_type: str, modality: Modality) -> DetectionRecord:
    rule = readings.rule(event_type, MODALITY_CONDITIONS[modality])
    assert rule is not None
    return readings.detection(rule)


def _argument_class(ctx: HarvestContext, branch: str, field: str) -> str | None:
    """The class of the entity in an argument field (``M1.arg2``), as the witness reads it."""
    alias, _, position = field.partition(".arg")
    for witness in ctx.row.witnesses:
        if witness.branch != branch:
            continue
        for interval in witness.intervals:
            if interval.alias != alias:
                continue
            for arg in interval.args:
                if str(arg.position) == position and arg.class_name:
                    return arg.class_name
    return None


class ModalityHarvester:
    def harvest(self, ctx: HarvestContext) -> tuple[EventRecord, list[Note]]:
        origin = ctx.origin
        unavailable: dict[str, Unavailable] = {}
        unavailable.update(ctx.interval.unavailable)

        rules: dict[Modality, RuleRef | None] = {}
        for modality, condition in MODALITY_CONDITIONS.items():
            if modality in origin.absent_modalities:
                rules[modality] = None
                unavailable[f"modality_rules.{modality}"] = Unavailable(
                    reason=Reason.MODALITY_RULE_ABSENT,
                    detail=f"EventSpec has no {ctx.rule.event_type}/{condition}",
                )
            else:
                rules[modality] = RuleRef(rule_ref=f"{ctx.rule.event_type}/{condition}")

        origin_basis = None
        if ctx.condition == "C":
            origin_basis = OriginBasis(
                branch=", ".join(b.name for b in origin.branches),
                matched=[
                    OriginMatch(modality=m.modality, source_ref=row_source(m.detection, m.row))
                    for m in origin.matched
                ],
                method=LINEAGE_METHOD,
            )

        event = EventRecord(
            event_id=ctx.event_id,
            model_id=ctx.rule.ref,
            label=ctx.rule.event_type,
            modality_origin=origin.modality,
            origin_basis=origin_basis,
            interval=ctx.interval.anchor,
            arguments=self._arguments(ctx),
            modality_rules=ModalityRules(visual=rules["visual"], audio=rules["audio"]),
            modality_detections=self._detections(ctx),
            source_ref=row_source(ctx.detection, ctx.row),
            unavailable=unavailable or None,
        )
        return event, []

    @staticmethod
    def _arguments(ctx: HarvestContext) -> list[Argument]:
        """The argument columns of the row, each with the field of the row's branch that fills it."""
        branch = ctx.origin.branches[0]
        arguments = []
        for column in ctx.row_columns.columns:
            if not column.kind.startswith("arg"):
                continue
            entity = class_id(ctx.row.values.get(column.label))
            if entity is None:
                continue
            role = column.fields.get(branch.name)
            if role is None:
                raise EngineError(
                    f"{ctx.rule.ref}: column {column.label} has no field in branch {branch.name}"
                )
            arguments.append(
                Argument(
                    role=role,
                    class_=_argument_class(ctx, branch.name, role) or _named_class(ctx, column),
                    entity_id=f"ent_{entity}",
                    column=column.label,
                )
            )
        return arguments

    @staticmethod
    def _detections(ctx: HarvestContext) -> list[ModalityDetection]:
        detections = []
        for detection in ctx.origin.modality_sets:
            modality = CONDITION_MODALITY[detection.rule.condition]
            for index, row in enumerate(detection.rows):
                timed = extent_anchor(
                    row.values, row_columns(detection.layout, row).extent, ctx.timebase, "interval"
                )
                if timed is None:
                    raise HarvestFailure.input(
                        InputError.UNSUPPORTED_CONSTRUCT,
                        f"{detection.rule.ref}: row {index} has no start and end",
                    )
                detections.append(
                    ModalityDetection(
                        modality=modality,
                        interval=timed.anchor,
                        source_ref=row_source(detection, row),
                        unavailable=timed.unavailable or None,
                    )
                )
        return detections


def _named_class(ctx: HarvestContext, column: ResultColumn) -> str:
    if column.arg_class is None:
        raise EngineError(f"{ctx.rule.ref}: the lineage and the plan name no class for column {column.label}")
    return column.arg_class
