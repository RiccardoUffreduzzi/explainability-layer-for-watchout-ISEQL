"""``DetectionSource`` port over WatchOut's ``EventsService.detect``.

The detection runs on the read-only connection with the lineage query, which gives
the same rows as the GUI's, in the same order, each with the interval rows behind it.
"""

import sqlite3
from collections.abc import Mapping

from iseql.compiler import render_iseql
from service.events_service import DetectionError
from service.impl.event_registry_service_impl import EventRegistryServiceImpl
from service.impl.events_service_impl import EventsServiceImpl

from xai.adapters.watchout.mapping import UNBOUNDED, to_record
from xai.k1_harvester.ports import (
    AnalysisSnapshot,
    DetectionNotPossible,
    DetectionRecord,
    EngineError,
    ParamsMissing,
    ParamsSnapshot,
    ParamValue,
    RuleNotSupported,
    RuleSnapshot,
)


class LiveDetections:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        """Opened by ``open_read_only``: WatchOut cannot write through it."""
        self._events = EventsServiceImpl()
        self._registry = EventRegistryServiceImpl()

    def detection(
        self, rule: RuleSnapshot, analysis: AnalysisSnapshot, params: ParamsSnapshot
    ) -> DetectionRecord:
        self._check_params(rule, analysis, params)
        try:
            result = self._events.detect(
                self.conn,
                analysis_id=analysis.analysis_id,
                event_type=rule.event_type,
                condition=rule.condition,
                # None: WatchOut merges the rules' defaults as the GUI pre-fills them.
                params=None if params.origin == "rule_defaults" else dict(params.values),
                unit=params.unit,
                with_lineage=True,
            )
        except (DetectionError, ValueError) as exc:
            raise EngineError(f"{rule.ref}: {exc}") from exc
        except TypeError as exc:
            if analysis.fps is None:
                raise DetectionNotPossible(
                    "Analyses.SamplingRate is missing: WatchOut cannot show the rows of this rule"
                ) from exc
            raise
        if result.plan.form == "F4":
            raise RuleNotSupported(f"{rule.ref}: {result.plan.columns_problem}")
        return to_record(result, rule, params)

    def rule_text(self, rule: RuleSnapshot, values: Mapping[str, ParamValue]) -> str:
        """``render_iseql`` with the values as named keys; unbounded values show as ∞."""
        text: str = render_iseql(
            dict(rule.model), {key: (None if value in UNBOUNDED else value) for key, value in values.items()}
        )
        return text

    def _check_params(self, rule: RuleSnapshot, analysis: AnalysisSnapshot, params: ParamsSnapshot) -> None:
        """The checks ``detect_event`` meets first, raised as the reasons K1 reports.

        For ``rule_defaults`` the values are those of ``default_params``, which WatchOut merges again.
        """
        missing = sorted(self._registry.required_deltas(self.conn, rule.condition) - set(params.values))
        if missing:
            raise ParamsMissing(missing)
        numeric = any(isinstance(v, int | float) and not isinstance(v, bool) for v in params.values.values())
        if params.unit == "seconds" and numeric and analysis.fps is None:
            raise DetectionNotPossible(
                "the parameters are in seconds and Analyses.SamplingRate is missing or zero: "
                "WatchOut's detect_event cannot convert them either"
            )
