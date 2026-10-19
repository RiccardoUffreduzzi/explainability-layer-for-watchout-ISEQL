"""``AnalysisHarvester``: every row of every event of an analysis.

For each rule of the analysis's condition it runs the detection once and calls
``StageHarvester`` on each row, reusing the rule, the configuration, the rows and
the A and B detections already read.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime

from xai.contract.ids import event_id
from xai.contract.model import Condition
from xai.k1_harvester.context import AnalysisReadings
from xai.k1_harvester.ports import EngineError, ParamsOrigin, RuleSnapshot
from xai.k1_harvester.request import HarvestRequest, ParamsMode
from xai.k1_harvester.result import HarvestFailure, HarvestResult
from xai.k1_harvester.service import StageHarvester


@dataclass(frozen=True)
class RuleOutcome:
    """What the batch made of one rule: its rows, or why it has none.

    ``failure`` (an input error such as ``ROW_SCHEMA_AMBIGUOUS``) or ``engine_error``
    (WatchOut's engine failed on the rule) is set when the rule could not be harvested.
    """

    event_type: str
    rule_ref: str
    rows_returned: int | None
    """None when the detection did not run."""
    results: tuple[HarvestResult, ...] = ()
    failure: HarvestFailure | None = None
    engine_error: str | None = None


@dataclass(frozen=True)
class AnalysisOutcome:
    analysis_id: str
    condition: Condition
    params_mode: ParamsMode
    params_origin: ParamsOrigin
    extracted_at: datetime
    rules: tuple[RuleOutcome, ...]

    def drafts(self) -> Iterator[tuple[RuleOutcome, HarvestResult]]:
        """The rows with a draft, in output order (event, then row)."""
        for rule in self.rules:
            for result in rule.results:
                if result.draft is not None:
                    yield rule, result


class AnalysisHarvester:
    def __init__(self, stage: StageHarvester) -> None:
        self.stage = stage

    def harvest(
        self, analysis_id: str, condition: Condition | None = None, params: ParamsMode = "defaults"
    ) -> AnalysisOutcome:
        """The drafts of every row; ``params = defaults`` at the end of an analysis."""
        readings = self.stage.readings(analysis_id, params)
        condition = self.stage.condition(readings, condition)
        extracted_at = self.stage.clock.now()
        rules = sorted(readings.reader.rules(condition), key=lambda r: r.event_type)
        return AnalysisOutcome(
            analysis_id=analysis_id,
            condition=condition,
            params_mode=params,
            params_origin=readings.params.origin,
            extracted_at=extracted_at,
            rules=tuple(self._rule(readings, rule, params, extracted_at) for rule in rules),
        )

    def _rule(
        self, readings: AnalysisReadings, rule: RuleSnapshot, params: ParamsMode, extracted_at: datetime
    ) -> RuleOutcome:
        try:
            prepared = self.stage.prepare(readings, rule)
        except HarvestFailure as failure:
            return RuleOutcome(rule.event_type, rule.ref, None, failure=failure)
        except EngineError as exc:
            return RuleOutcome(rule.event_type, rule.ref, None, engine_error=str(exc))

        analysis_id = readings.analysis.analysis_id
        rows = prepared.detection.rows
        ids = [event_id(analysis_id, rule.event_type, rule.condition, row.values) for row in rows]
        # Rows with the same event_id are copies of one row: the first gets the draft.
        copies: dict[str, list[int]] = {}
        for index, ev_id in enumerate(ids):
            copies.setdefault(ev_id, []).append(index)
        results: list[HarvestResult] = []
        for index, row in enumerate(rows):
            ev_id = ids[index]
            matches = copies[ev_id]
            if matches[0] != index:
                results.append(HarvestResult(index, row.values, ev_id, duplicate_of=matches[0]))
                continue
            request = HarvestRequest(analysis_id, rule.event_type, row.values, rule.condition, params)
            try:
                draft = self.stage.harvest_row(request, readings, prepared, matches, extracted_at)
            except HarvestFailure as failure:
                results.append(HarvestResult(index, row.values, ev_id, failure=failure))
            except EngineError as exc:
                results.append(HarvestResult(index, row.values, ev_id, engine_error=str(exc)))
            else:
                results.append(HarvestResult(index, row.values, ev_id, draft=draft))
        return RuleOutcome(rule.event_type, rule.ref, len(rows), tuple(results))
