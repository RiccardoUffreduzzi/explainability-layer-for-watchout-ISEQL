"""The ``event`` section: the detection, its arguments and the detections per modality.

``OriginResolver`` finds where the located row comes from; ``EventLocator`` calls it,
because the rule and evidence sections need the row's branch too.
``ModalityHarvester`` writes the section. K1 reads Evento_A and Evento_B; the
comparison between the modalities (reinforcement) is K2's.
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
from xai.contract.reasons import InputError, NoteCode, Reason
from xai.k1_harvester.context import (
    MODALITY_CONDITIONS,
    AnalysisReadings,
    HarvestContext,
    ModalityDetectionSet,
    OriginMatchRow,
    RowOrigin,
)
from xai.k1_harvester.ports import (
    Branch,
    DetectedRow,
    Detection,
    ResultColumn,
    RuleLayout,
    RuleSnapshot,
)
from xai.k1_harvester.predicates import branch_modality
from xai.k1_harvester.result import HarvestFailure
from xai.k1_harvester.rows import class_id, extent_anchor, same_row, same_value
from xai.k1_harvester.set_sides import side_method

CONDITION_MODALITY: dict[Condition, Modality] = {"A": "visual", "B": "audio"}

SAME_COLUMNS_METHOD = (
    "exact match of the row with the rows of Evento_A and Evento_B (same columns and values)"
)
_MATCH_ON_KINDS = (
    "match with the rows of Evento_A and Evento_B on the kinds they project, the other kinds null"
)


def row_source(detection: Detection, row: DetectedRow) -> SourceRef:
    """SourceRef of a detection row: the row in canonical JSON."""
    return SourceRef(
        stage=Stage.ISEQL, store=detection.store, record_id=canonical_row(row.values), mode="read"
    )


class OriginResolver:
    """Where a row comes from: modality and branch."""

    def resolve(
        self,
        readings: AnalysisReadings,
        rule: RuleSnapshot,
        layout: RuleLayout,
        detection: Detection,
        row: DetectedRow,
        side: Branch | None = None,
    ) -> RowOrigin:
        """``side``: the set side an F3 row was read as (``set_sides``), when it had to be."""
        absent = tuple(
            modality
            for modality, condition in MODALITY_CONDITIONS.items()
            if readings.rule(rule.event_type, condition) is None
        )
        if rule.condition in CONDITION_MODALITY:
            modality = CONDITION_MODALITY[rule.condition]
            own = ModalityDetectionSet(modality=modality, rule=rule, layout=layout, detection=detection)
            return RowOrigin(
                modality=modality, branches=layout.branches, modality_sets=(own,), absent_modalities=absent
            )

        sets = tuple(
            self._modality_set(readings, rule.event_type, m) for m in MODALITY_CONDITIONS if m not in absent
        )
        by_kind = len(layout.branches) > 1
        matched = tuple(
            OriginMatchRow(modality=s.modality, detection=s.detection, row=other)
            for s in sets
            for other in s.detection.rows
            if (
                self._same_by_kind(row, layout, other, s.layout)
                if by_kind
                else same_row(row.values, other.values)
            )
        )
        modalities = {m.modality for m in matched}
        origin = "both" if len(modalities) == 2 else (modalities.pop() if modalities else None)
        method = self._kind_method(layout) if by_kind else SAME_COLUMNS_METHOD
        if side is not None:
            method = f"{side_method(side, layout.columns or ())}; {_MATCH_ON_KINDS}"
        return RowOrigin(
            modality=origin,
            branches=(side,) if side is not None else self._branches(readings, layout, origin),
            modality_sets=sets,
            absent_modalities=absent,
            matched=matched,
            method=method,
        )

    @staticmethod
    def _modality_set(
        readings: AnalysisReadings, event_type: str, modality: Modality
    ) -> ModalityDetectionSet:
        rule = readings.rule(event_type, MODALITY_CONDITIONS[modality])
        assert rule is not None
        _, layout = readings.layout(rule)
        return ModalityDetectionSet(
            modality=modality, rule=rule, layout=layout, detection=readings.detection(rule)
        )

    @staticmethod
    def _same_by_kind(
        row: DetectedRow, layout: RuleLayout, other: DetectedRow, other_layout: RuleLayout
    ) -> bool:
        """The C row equals the modality row on the kinds that row projects; its other kinds are null."""
        if layout.columns is None or other_layout.columns is None:
            return False
        mine = {c.kind: row.values.get(c.label) for c in layout.columns}
        theirs = {c.kind: other.values.get(c.label) for c in other_layout.columns}
        if len(theirs) != len(other_layout.columns):
            return False  # the modality rule projects two columns of the same kind
        if not theirs.keys() <= mine.keys():
            return False
        return all(same_value(mine[k], v) for k, v in theirs.items()) and all(
            mine[k] is None for k in mine.keys() - theirs.keys()
        )

    @staticmethod
    def _branches(readings: AnalysisReadings, layout: RuleLayout, origin: str | None) -> tuple[Branch, ...]:
        if origin not in ("visual", "audio") or len(layout.branches) == 1:
            return layout.branches
        same = tuple(b for b in layout.branches if branch_modality(b, readings.vocabulary) == origin)
        return same or layout.branches

    @staticmethod
    def _kind_method(layout: RuleLayout) -> str:
        kinds = ", ".join(f"{c.label} → {c.kind}" for c in layout.columns or ())
        return (
            f"result columns mapped to their kind ({kinds}) as WatchOut aligns them "
            f"(_canonical_schema, _multimodal_labels); {_MATCH_ON_KINDS}"
        )


def _argument_class(ctx: HarvestContext, column: ResultColumn, entity: int) -> str:
    """The class of the entity in an argument column.

    WatchOut names the column after the first class the selection admits for the slot
    (``_interval_arg_class``): with a disjunction of classes (``arg1 = vehicle or
    object``) the name can say ``person`` for a vehicle. Then the class is the one
    ``VisualParticipant`` records for the entity in an interval of the slot's predicates,
    as the compiler's class filter matched it (first by RelationID).
    """
    admitted: list[str] = []
    predicates: list[str] = []
    for branch in ctx.origin.branches:
        field = column.fields.get(branch.name)
        if field is None:
            continue
        alias, _, slot = field.partition(".arg")
        for interval in branch.intervals:
            if interval.alias != alias:
                continue
            for alternative in interval.selection:
                admitted.extend(c for c in alternative.arg_classes.get(slot, ()) if c not in admitted)
                predicates.extend(p for p in alternative.predicates if p not in predicates)
    assert column.arg_class is not None
    if len(admitted) <= 1 or not predicates:
        return column.arg_class
    relations = ctx.reader.visual_intervals(ctx.analysis.analysis_id, set(predicates))
    participants = ctx.reader.participants([r.relation_id for r in relations]) if relations else []
    classes = [p.class_name for p in participants if p.class_id == entity and p.class_name in admitted]
    return classes[0] if classes else column.arg_class


class ModalityHarvester:
    def harvest(self, ctx: HarvestContext) -> tuple[EventRecord, list[Note]]:
        origin = ctx.origin
        unavailable: dict[str, Unavailable] = {}
        timed = extent_anchor(ctx.row.values, ctx.layout.extent, ctx.timebase, "interval")
        if timed is None:  # EventLocator refuses such rows
            raise HarvestFailure.input(
                InputError.ROW_SCHEMA_AMBIGUOUS, f"{ctx.rule.ref}: no start and end in the row"
            )
        unavailable.update(timed.unavailable)

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
            if origin.modality is None:
                unavailable["modality_origin"] = Unavailable(
                    reason=Reason.ORIGIN_NOT_IDENTIFIABLE,
                    detail="the row matches no row of Evento_A or Evento_B: " + (origin.method or ""),
                )
            else:
                origin_basis = OriginBasis(
                    branch=", ".join(b.name for b in origin.branches),
                    matched=[
                        OriginMatch(modality=m.modality, source_ref=row_source(m.detection, m.row))
                        for m in origin.matched
                    ],
                    method=origin.method or SAME_COLUMNS_METHOD,
                )

        event = EventRecord(
            event_id=ctx.event_id,
            model_id=ctx.rule.ref,
            label=ctx.rule.event_type,
            modality_origin=origin.modality,
            origin_basis=origin_basis,
            interval=timed.anchor,
            arguments=self._arguments(ctx),
            modality_rules=ModalityRules(visual=rules["visual"], audio=rules["audio"]),
            modality_detections=self._detections(ctx),
            source_ref=row_source(ctx.detection, ctx.row),
            unavailable=unavailable or None,
        )
        notes = []
        if ctx.layout.multiset and ctx.layout.columns:
            notes.append(Note(code=NoteCode.C_LABELS_BY_KIND, detail=self._labels_note(ctx)))
        elif ctx.layout.side_columns and ctx.origin.branch is not None:
            detail = side_method(ctx.origin.branch, ctx.layout.columns or ())
            notes.append(Note(code=NoteCode.C_LABELS_BY_KIND, detail=detail))
        return event, notes

    @staticmethod
    def _arguments(ctx: HarvestContext) -> list[Argument]:
        arguments = []
        for column in ctx.layout.columns or ():
            if not column.kind.startswith("arg"):
                continue
            entity = class_id(ctx.row.values.get(column.label))
            if entity is None:
                continue
            branch = ctx.origin.branch
            role = column.fields.get(branch.name) if branch is not None else None
            role = role or next(
                (column.fields[b.name] for b in ctx.layout.branches if b.name in column.fields), None
            )
            if role is None or column.arg_class is None:
                raise HarvestFailure.input(
                    InputError.ROW_SCHEMA_AMBIGUOUS,
                    f"{ctx.rule.ref}: column {column.label} cannot be traced to an argument of a branch",
                )
            arguments.append(
                Argument(
                    role=role,
                    class_=_argument_class(ctx, column, entity),
                    entity_id=f"ent_{entity}",
                    column=column.label,
                )
            )
        return arguments

    @staticmethod
    def _detections(ctx: HarvestContext) -> list[ModalityDetection]:
        detections = []
        for modality_set in ctx.origin.modality_sets:
            for index, row in enumerate(modality_set.detection.rows):
                timed = extent_anchor(row.values, modality_set.layout.extent, ctx.timebase, "interval")
                if timed is None:
                    raise HarvestFailure.input(
                        InputError.ROW_SCHEMA_AMBIGUOUS,
                        f"{modality_set.rule.ref}: row {index} has no start and end",
                    )
                detections.append(
                    ModalityDetection(
                        modality=modality_set.modality,
                        interval=timed.anchor,
                        source_ref=row_source(modality_set.detection, row),
                        unavailable=timed.unavailable or None,
                    )
                )
        return detections

    @staticmethod
    def _labels_note(ctx: HarvestContext) -> str:
        parts = []
        for column in ctx.layout.columns or ():
            fields = ", ".join(f"{b}: {f}" for b, f in column.fields.items())
            parts.append(f"{column.label} → {column.kind} ({fields})")
        return "C columns mapped to their kind, labels from the first branch: " + "; ".join(parts)
