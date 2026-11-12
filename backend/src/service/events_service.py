from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator, List, Optional
import sqlite3

from iseql.plan import CompiledPlan

@dataclass
class EventSpec:
    id: str
    condition: str = "A"
    model_json: str | None = None


class DetectionError(Exception):
    """A detection that compiled but cannot give rows (the query or its rows fail)."""


@dataclass(frozen=True)
class ResolvedParams:
    """The operator parameters of one detection, at each step of their resolution."""

    origin: str                     # "request" (given by the caller) | "rule_defaults"
    unit: str                       # unit of the written values: seconds | frames
    written: dict                   # as received (or the rule defaults)
    converted: dict                 # numeric values in seconds multiplied by the sampling rate
    engine: dict                    # as the compiler receives them (inf -> None, int())
    provided_by: dict = field(default_factory=dict)   # rule_defaults: key -> "<event>/<condition>" that won
    rule_defaults: dict = field(default_factory=dict)  # rule_defaults: "<event>/<condition>" -> its own defaults


@dataclass(frozen=True)
class WitnessArg:
    position: int
    class_id: Optional[int]
    class_name: Optional[str]


@dataclass(frozen=True)
class WitnessInterval:
    alias: str                      # M1, M2 ... in the branch
    table: str                      # VisualPerInterval | AudioPerInterval
    id: int                         # RelationID | AudioIntervalID
    args: tuple[WitnessArg, ...]


@dataclass(frozen=True)
class Witness:
    """One combination of interval rows that produces a result row."""

    branch: str
    intervals: tuple[WitnessInterval, ...]


@dataclass(frozen=True)
class DetectedRow:
    values: dict                    # the row under its column labels
    gui: dict                       # the row as detect_event returns it to the GUI
    witnesses: Optional[tuple[Witness, ...]]   # None when lineage was not asked


@dataclass(frozen=True)
class DetectionResult:
    analysis_id: str
    event_type: str
    condition: str
    sampling_rate: Optional[int]
    model: dict                     # EventSpec.model_json as read
    plan: CompiledPlan
    params: ResolvedParams
    sql: str                        # the detection SQL (the GUI runs exactly this)
    rows: tuple[DetectedRow, ...]
    lineage: bool


class EventsService(ABC):
    @abstractmethod
    def queries_for_condition(self, condition: str, deltas: dict, analysis_id: str) -> dict[str, str]:
        pass

    @abstractmethod
    def events_for_condition(self, condition: str) -> List[EventSpec]:
        pass

    @abstractmethod
    def run_sql_detection(
        self,
        conn: sqlite3.Connection,
        event_type: str,
        deltas: dict,
        analysis_id: str,
        condition: str = "A",
        log: Callable[[str], None] = None,
    ) -> Iterator[str]:
        pass

    @abstractmethod
    def detect(
        self,
        conn: sqlite3.Connection,
        *,
        analysis_id: str,
        event_type: str,
        condition: str,
        params: Optional[dict] = None,
        unit: str = "seconds",
        with_lineage: bool = False,
    ) -> DetectionResult:
        """One detection, the same for the GUI and the XAI pipeline. Never writes.

        ``params=None``=the defaults the GUI pre-fills. Raises ValueError for
        invalid parameters or an unknown event, DetectionError when the query or
        its rows fail.
        """
