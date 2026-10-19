"""``EventLocator``: from a request to the located detection row.

It reads the analysis, the configuration, the parameters and the rule, re-obtains
the rows from WatchOut's engine on the read-only connection and finds the requested
one. Every refusal is a ``HarvestFailure`` of stage ``input`` with its code.
"""

from collections.abc import Callable
from datetime import datetime
from typing import TypeVar

from xai.contract.ids import event_id
from xai.contract.model import Condition, RowMatch
from xai.contract.reasons import InputError
from xai.k1_harvester.context import AnalysisReadings, HarvestContext
from xai.k1_harvester.modality import OriginResolver
from xai.k1_harvester.ports import (
    DetectedRow,
    Detection,
    DetectionNotPossible,
    ModelForm,
    ParamsMissing,
    ParamsSnapshot,
    RowColumns,
    RowNotReadable,
    RuleLayout,
    RuleSnapshot,
    WatchOutReader,
)
from xai.k1_harvester.request import HarvestRequest, ParamsMode
from xai.k1_harvester.result import HarvestFailure
from xai.k1_harvester.rows import extent_anchor, row_matches

CONDITIONS: tuple[Condition, ...] = ("A", "B", "C")
DONE = "done"

T = TypeVar("T")


class EventLocator:
    def __init__(self, reader: WatchOutReader) -> None:
        self.reader = reader
        self.origins = OriginResolver()

    # analysis level

    def readings(self, analysis_id: str, params: ParamsMode) -> AnalysisReadings:
        """the analysis, the configuration and the parameters."""
        analysis = self.reader.analysis(analysis_id)
        if analysis is None:
            raise HarvestFailure.input(
                InputError.ANALYSIS_NOT_FOUND, f"no Analyses row with ID {analysis_id!r}"
            )
        if analysis.stage != DONE:
            raise HarvestFailure.input(
                InputError.ANALYSIS_NOT_READY,
                f"analysis {analysis_id} is at stage {analysis.stage!r}, not 'done'",
            )
        vocabulary = self.reader.vocabulary()
        if vocabulary is None:
            raise HarvestFailure.input(
                InputError.CONFIG_MISSING, "AppConfig has no relation_vocab or no audio_taxonomy section"
            )
        return AnalysisReadings(self.reader, analysis, vocabulary, self._params(analysis_id, params))

    def _params(self, analysis_id: str, mode: ParamsMode) -> ParamsSnapshot:
        if mode == "defaults":
            return self.reader.default_params()
        saved = self.reader.saved_params(analysis_id)
        if saved is not None:
            return saved
        if mode == "saved":
            raise HarvestFailure.input(
                InputError.ANALYSIS_PARAMS_MISSING,
                f"Analyses.DeltasJson of {analysis_id} is empty: the GUI has not run a detection yet",
            )
        return self.reader.default_params()

    def condition(self, readings: AnalysisReadings, requested: Condition | None) -> Condition:
        """The requested condition, by default the analysis's own."""
        if requested is not None:
            return requested
        condition = readings.analysis.condition
        if condition not in CONDITIONS:
            raise HarvestFailure.input(
                InputError.RULE_NOT_FOUND,
                f"Analyses.Condition is {condition!r}: no rules for it (expected A, B or C)",
            )
        return condition

    # rule level

    def rule(self, readings: AnalysisReadings, event_type: str, condition: Condition) -> RuleSnapshot:
        rule = readings.rule(event_type, condition)
        if rule is None:
            raise HarvestFailure.input(
                InputError.RULE_NOT_FOUND, f"EventSpec has no {event_type}/{condition}"
            )
        return rule

    def prepare(
        self, readings: AnalysisReadings, rule: RuleSnapshot
    ) -> tuple[ModelForm, RuleLayout, Detection]:
        """The rule's form and layout, and its detection with the analysis parameters."""
        form, layout = readings.layout(rule)
        if layout.columns is None and not layout.side_columns:
            raise HarvestFailure.input(
                InputError.ROW_SCHEMA_AMBIGUOUS,
                f"{rule.ref}: {layout.columns_problem or 'columns not traceable'}",
            )
        detection = self._engine(lambda: readings.detection(rule), rule.ref)
        return form, layout, detection

    # row level

    def locate(
        self, request: HarvestRequest, readings: AnalysisReadings, extracted_at: datetime
    ) -> HarvestContext:
        """The context of the requested row (single request, ``harvest``)."""
        condition = self.condition(readings, request.condition)
        rule = self.rule(readings, request.event_type, condition)
        form, layout, detection = self.prepare(readings, rule)
        matches = [i for i, row in enumerate(detection.rows) if row_matches(request.row, row)]
        if not matches:
            raise HarvestFailure.input(
                InputError.EVENT_NOT_REPRODUCIBLE,
                f"{rule.ref} returns {len(detection.rows)} row(s) on {readings.analysis.analysis_id} "
                f"with the {readings.params.origin} parameters, none equal to the requested row",
            )
        return self.context(request, readings, rule, form, layout, detection, matches, extracted_at)

    def context(
        self,
        request: HarvestRequest,
        readings: AnalysisReadings,
        rule: RuleSnapshot,
        form: ModelForm,
        layout: RuleLayout,
        detection: Detection,
        matches: list[int],
        extracted_at: datetime,
    ) -> HarvestContext:
        """The context of a row already found among the rows of the detection."""
        row: DetectedRow = detection.rows[matches[0]]
        columns = self.row_columns(rule.ref, layout, row)
        if extent_anchor(row.values, columns.extent, readings.timebase, "interval") is None:
            raise HarvestFailure.input(
                InputError.ROW_SCHEMA_AMBIGUOUS,
                f"{rule.ref}: the start and end of the row cannot be read from its columns",
            )
        origin = self._engine(
            lambda: self.origins.resolve(readings, rule, layout, detection, row, columns),
            f"{rule.event_type} (rules A and B)",
        )
        return HarvestContext(
            request=request,
            condition=rule.condition,
            readings=readings,
            rule=rule,
            form=form,
            layout=layout,
            detection=detection,
            row=row,
            row_columns=columns,
            row_match=RowMatch(
                rows_returned=len(detection.rows), matches=len(matches), matched_index=matches[0]
            ),
            event_id=event_id(readings.analysis.analysis_id, rule.event_type, rule.condition, row.values),
            origin=origin,
            extracted_at=extracted_at,
        )

    def row_columns(self, rule_ref: str, layout: RuleLayout, row: DetectedRow) -> RowColumns:
        """What each column of the row holds, as the engine aligns the rule's columns."""
        try:
            return self.reader.row_columns(layout, row)
        except RowNotReadable as exc:
            raise HarvestFailure.input(InputError.ROW_SCHEMA_AMBIGUOUS, f"{rule_ref}: {exc}") from exc

    @staticmethod
    def _engine(call: Callable[[], T], what: str) -> T:
        """Run a detection; the parameter problems the engine meets become input errors."""
        try:
            return call()
        except ParamsMissing as exc:
            raise HarvestFailure.input(
                InputError.ANALYSIS_PARAMS_MISSING,
                f"{what}: the parameters lack {', '.join(exc.missing)}",
            ) from exc
        except DetectionNotPossible as exc:
            raise HarvestFailure.input(InputError.EVENT_NOT_REPRODUCIBLE, f"{what}: {exc}") from exc
