"""What the section harvesters read: the located detection and the analysis readings.

``AnalysisReadings`` keeps what is read once per analysis so the end-of-analysis
batch reads each rule and runs each detection once and reuses them for every row.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from xai.contract.model import Condition, Modality, RowMatch
from xai.k1_harvester.ports import (
    AnalysisSnapshot,
    Branch,
    CodeFacts,
    DetectedRow,
    DetectionRecord,
    ModelForm,
    ParamsSnapshot,
    RuleLayout,
    RuleSnapshot,
    VlmDefaults,
    Vocabulary,
    WatchOutReader,
    WatchOutRecords,
)
from xai.k1_harvester.request import HarvestRequest
from xai.k1_harvester.rows import RowColumns
from xai.k1_harvester.timebase import TimeBase, TimedAnchor

MODALITY_CONDITIONS: dict[Modality, Condition] = {"visual": "A", "audio": "B"}
"""Condition of the rule that detects an event in one modality (Evento_A, Evento_B)"""


class AnalysisReadings:
    """Readings of one analysis with one set of parameters, cached"""

    def __init__(
        self,
        reader: WatchOutReader,
        analysis: AnalysisSnapshot,
        vocabulary: Vocabulary,
        params: ParamsSnapshot,
    ) -> None:
        self.reader = reader
        self.analysis = analysis
        self.vocabulary = vocabulary
        self.params = params
        """The parameters asked as WatchOut used them."""
        self.timebase = TimeBase(analysis.fps)
        self._rules: dict[tuple[str, str], RuleSnapshot | None] = {}
        self._detections: dict[str, DetectionRecord] = {}
        self._default_params: ParamsSnapshot | None = None
        self._vlm_defaults: VlmDefaults | None = None

    def rule(self, event_type: str, condition: Condition) -> RuleSnapshot | None:
        key = (event_type, condition)
        if key not in self._rules:
            self._rules[key] = self.reader.rule(event_type, condition)
        return self._rules[key]

    def detection(self, rule: RuleSnapshot) -> DetectionRecord:
        """The rule compiled and run with the analysis parameters, rows with their lineage."""
        if rule.ref not in self._detections:
            self._detections[rule.ref] = self.reader.detection(rule, self.analysis, self.params)
        return self._detections[rule.ref]

    def default_params(self) -> ParamsSnapshot:
        """The rule defaults, also when the detection uses the parameters saved by the GUI."""
        if self.params.origin == "rule_defaults":
            return self.params
        if self._default_params is None:
            self._default_params = self.reader.default_params()
        return self._default_params

    def vlm_defaults(self) -> VlmDefaults:
        if self._vlm_defaults is None:
            self._vlm_defaults = self.reader.vlm_defaults()
        return self._vlm_defaults

    @property
    def facts(self) -> CodeFacts:
        """Values of WatchOut's code."""
        return self.reader


@dataclass(frozen=True)
class OriginMatchRow:
    """A row of Evento_A or Evento_B produced by the same interval rows as the located row."""

    modality: Modality
    detection: DetectionRecord
    row: DetectedRow


@dataclass(frozen=True)
class RowOrigin:
    """Which modality and which branches of the rule the located row comes from."""

    modality: Literal["visual", "audio", "both"]
    branches: tuple[Branch, ...]
    """The branches with a witness of the row, in rule order."""
    modality_sets: tuple[DetectionRecord, ...]
    """Evento_A and Evento_B (condition C), or the row's own detection."""
    absent_modalities: tuple[Modality, ...]
    """Modalities whose rule the event does not have."""
    matched: tuple[OriginMatchRow, ...] = ()

    @property
    def branch(self) -> Branch | None:
        """The branch of the row, when there is exactly one."""
        return self.branches[0] if len(self.branches) == 1 else None


@dataclass(frozen=True)
class PreparedRule:
    """A rule and its detection, shared by all the rows."""

    rule: RuleSnapshot
    detection: DetectionRecord


@dataclass(frozen=True)
class HarvestContext:
    """One located detection row and everything read to find it."""

    request: HarvestRequest
    condition: Condition
    readings: AnalysisReadings
    rule: RuleSnapshot
    detection: DetectionRecord
    row: DetectedRow
    row_columns: RowColumns
    """What each column of the row holds; ``layout`` stays the rule's."""
    row_match: RowMatch
    event_id: str
    interval: TimedAnchor
    """The row's start and end, as ``detect_event`` finds them."""
    origin: RowOrigin
    extracted_at: datetime

    @property
    def form(self) -> ModelForm:
        return self.detection.layout.form

    @property
    def layout(self) -> RuleLayout:
        return self.detection.layout

    @property
    def analysis(self) -> AnalysisSnapshot:
        return self.readings.analysis

    @property
    def params(self) -> ParamsSnapshot:
        """The params as WatchOut used them for this detection."""
        return self.detection.params

    @property
    def vocabulary(self) -> Vocabulary:
        return self.readings.vocabulary

    @property
    def timebase(self) -> TimeBase:
        return self.readings.timebase

    @property
    def records(self) -> WatchOutRecords:
        """Rows of WatchOut's database, for the sections that read rows of their own."""
        return self.readings.reader
