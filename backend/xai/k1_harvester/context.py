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
    BackendVersion,
    Branch,
    DetectedRow,
    Detection,
    ModelForm,
    ParamsSnapshot,
    RuleLayout,
    RuleSnapshot,
    VlmDefaults,
    Vocabulary,
    WatchOutReader,
)
from xai.k1_harvester.request import HarvestRequest
from xai.k1_harvester.rule.form_detector import ModelFormDetector
from xai.k1_harvester.timebase import TimeBase

MODALITY_CONDITIONS: dict[Modality, Condition] = {"visual": "A", "audio": "B"}
"""Condition of the rule that detects an event in one modality (Evento_A, Evento_B)."""


class AnalysisReadings:
    """Readings of one analysis with one set of parameters, cached."""

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
        self.timebase = TimeBase(analysis.fps)
        self._rules: dict[tuple[str, str], RuleSnapshot | None] = {}
        self._layouts: dict[str, tuple[ModelForm, RuleLayout]] = {}
        self._detections: dict[str, Detection] = {}
        self._default_params: ParamsSnapshot | None = None
        self._vlm_defaults: VlmDefaults | None = None
        self._backend_version: tuple[BackendVersion | None] | None = None
        self._forms = ModelFormDetector()

    def rule(self, event_type: str, condition: Condition) -> RuleSnapshot | None:
        key = (event_type, condition)
        if key not in self._rules:
            self._rules[key] = self.reader.rule(event_type, condition)
        return self._rules[key]

    def layout(self, rule: RuleSnapshot) -> tuple[ModelForm, RuleLayout]:
        """Form of the rule and its structure as the compiler executes it."""
        if rule.ref not in self._layouts:
            form = self._forms.detect(rule)
            self._layouts[rule.ref] = (form, self.reader.rule_layout(rule, form))
        return self._layouts[rule.ref]

    def detection(self, rule: RuleSnapshot) -> Detection:
        if rule.ref not in self._detections:
            self._detections[rule.ref] = self.reader.detect(rule, self.analysis, self.params)
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

    def backend_version(self) -> BackendVersion | None:
        if self._backend_version is None:
            self._backend_version = (self.reader.backend_version(),)
        return self._backend_version[0]


@dataclass(frozen=True)
class ModalityDetectionSet:
    """The rows of the rule of one modality (Evento_A or Evento_B) with the same parameters."""

    modality: Modality
    rule: RuleSnapshot
    layout: RuleLayout
    detection: Detection


@dataclass(frozen=True)
class OriginMatchRow:
    """A row of Evento_A or Evento_B equal to the located row."""

    modality: Modality
    detection: Detection
    row: DetectedRow


@dataclass(frozen=True)
class RowOrigin:
    """Which modality and which branches of the rule the located row comes from."""

    modality: Literal["visual", "audio", "both"] | None
    """None: a condition C row that matches no row of Evento_A or Evento_B."""
    branches: tuple[Branch, ...]
    """The branches the row can come from: one when it is known, all of them otherwise."""
    modality_sets: tuple[ModalityDetectionSet, ...]
    """Evento_A and Evento_B: the detections the row is compared with (condition C), or its own."""
    absent_modalities: tuple[Modality, ...]
    """Modalities whose rule the event does not have."""
    matched: tuple[OriginMatchRow, ...] = ()
    method: str | None = None
    """How a condition C row was compared; None for conditions A and B."""

    @property
    def branch(self) -> Branch | None:
        """The branch of the row, when there is exactly one."""
        return self.branches[0] if len(self.branches) == 1 else None


@dataclass(frozen=True)
class HarvestContext:
    """One located detection row and everything read to find it."""

    request: HarvestRequest
    condition: Condition
    readings: AnalysisReadings
    rule: RuleSnapshot
    form: ModelForm
    layout: RuleLayout
    detection: Detection
    row: DetectedRow
    row_match: RowMatch
    event_id: str
    origin: RowOrigin
    extracted_at: datetime

    @property
    def analysis(self) -> AnalysisSnapshot:
        return self.readings.analysis

    @property
    def params(self) -> ParamsSnapshot:
        return self.readings.params

    @property
    def vocabulary(self) -> Vocabulary:
        return self.readings.vocabulary

    @property
    def timebase(self) -> TimeBase:
        return self.readings.timebase

    @property
    def reader(self) -> WatchOutReader:
        return self.readings.reader
