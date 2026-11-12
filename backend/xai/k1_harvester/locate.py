"""``EventLocator``: from a request to the located detection row.

It reads the analysis, the configuration, the parameters and the rule, re-obtains
the rows from WatchOut's detection on the read-only connection and finds the requested
one. Every refusal is a ``HarvestFailure`` of stage ``input`` with its code.
"""

from collections.abc import Callable
from datetime import datetime
from typing import TypeVar

from xai.contract.ids import event_id
from xai.contract.model import Condition, RowMatch
from xai.contract.reasons import InputError
from xai.k1_harvester.context import AnalysisReadings, HarvestContext, PreparedRule
from xai.k1_harvester.modality import resolve_origin
from xai.k1_harvester.ports import (
    DetectedRow,
    DetectionNotPossible,
    ParamsMissing,
    ParamsSnapshot,
    RuleNotSupported,
    RuleSnapshot,
    WatchOutReader,
)
from xai.k1_harvester.request import HarvestRequest, ParamsMode
from xai.k1_harvester.result import HarvestFailure
from xai.k1_harvester.rows import extent_anchor, row_columns, row_matches

CONDITIONS: tuple[Condition, ...] = ("A", "B", "C")
DONE = "done"

T = TypeVar("T")


class EventLocator:
    def __init__(self, reader: WatchOutReader) -> None:
        self.reader = reader

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

    def prepare(self, readings: AnalysisReadings, rule: RuleSnapshot) -> PreparedRule:
        """The rule's detection with the analysis parameters"""
        return PreparedRule(rule, self._engine(lambda: readings.detection(rule), rule.ref))

    # row level

    def locate(
        self, request: HarvestRequest, readings: AnalysisReadings, extracted_at: datetime
    ) -> HarvestContext:
        """The context of the requested row (single request, ``harvest``)."""
        condition = self.condition(readings, request.condition)
        rule = self.rule(readings, request.event_type, condition)
        prepared = self.prepare(readings, rule)
        rows = prepared.detection.rows
        matches = [i for i, row in enumerate(rows) if row_matches(request.row, row)]
        if not matches:
            raise HarvestFailure.input(
                InputError.EVENT_NOT_REPRODUCIBLE,
                f"{rule.ref} returns {len(rows)} row(s) on {readings.analysis.analysis_id} "
                f"with the {readings.params.origin} parameters, none equal to the requested row",
            )
        return self.context(request, readings, prepared, matches, extracted_at)

    def context(
        self,
        request: HarvestRequest,
        readings: AnalysisReadings,
        prepared: PreparedRule,
        matches: list[int],
        extracted_at: datetime,
    ) -> HarvestContext:
        """The context of a row already found: ``matches`` are its index and those of its copies."""
        rule, detection = prepared.rule, prepared.detection
        row: DetectedRow = detection.rows[matches[0]]
        columns = row_columns(detection.layout, row)
        interval = extent_anchor(row.values, columns.extent, readings.timebase, "interval")
        if interval is None:
            raise HarvestFailure.input(
                InputError.UNSUPPORTED_CONSTRUCT,
                f"{rule.ref}: the rows have no start and end column, so the event has no interval",
            )
        origin = self._engine(
            lambda: resolve_origin(readings, detection, row), f"{rule.event_type} (rules A and B)"
        )
        return HarvestContext(
            request=request,
            condition=rule.condition,
            readings=readings,
            rule=rule,
            detection=detection,
            row=row,
            row_columns=columns,
            row_match=RowMatch(
                rows_returned=len(detection.rows), matches=len(matches), matched_index=matches[0]
            ),
            event_id=event_id(readings.analysis.analysis_id, rule.event_type, rule.condition, row.values),
            interval=interval,
            origin=origin,
            extracted_at=extracted_at,
        )

    @staticmethod
    def _engine(call: Callable[[], T], what: str) -> T:
        """Run a detection; the problems WatchOut meets with the request become input errors."""
        try:
            return call()
        except ParamsMissing as exc:
            raise HarvestFailure.input(
                InputError.ANALYSIS_PARAMS_MISSING,
                f"{what}: the parameters lack {', '.join(exc.missing)}",
            ) from exc
        except DetectionNotPossible as exc:
            raise HarvestFailure.input(InputError.EVENT_NOT_REPRODUCIBLE, f"{what}: {exc}") from exc
        except RuleNotSupported as exc:
            raise HarvestFailure.input(InputError.UNSUPPORTED_CONSTRUCT, str(exc)) from exc
