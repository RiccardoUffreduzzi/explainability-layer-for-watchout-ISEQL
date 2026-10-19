"""Data that K1 receives as values: glossary and pipeline constants.

They are files of ``xai/resources``, not WatchOut data, so they are not ports:
``xai.adapters.resource_files`` loads them and the CLI passes them to the core.
"""

from collections.abc import Mapping
from dataclasses import dataclass

GLOSSARY_STORE = "backend/xai/resources/glossary.yaml"
CONSTANTS_STORE = "backend/xai/resources/pipeline_constants.yaml"


@dataclass(frozen=True)
class ParameterReadingText:
    condition: str
    phrase: str


@dataclass(frozen=True)
class GlossaryText:
    """One entry of ``glossary.yaml``."""

    plain_template: str
    definition: str | None = None
    parameter_readings: tuple[ParameterReadingText, ...] = ()
    citation: str | None = None
    """Where the text comes from, e.g. a table of the WACV paper or a WatchOut file."""


@dataclass(frozen=True)
class Glossary:
    """``glossary.yaml``: report phrases, operators, audio classes and events."""

    version: str
    sha12: str
    """First 12 hex digits of the sha256 of the file."""
    predicates: Mapping[str, GlossaryText]
    audio_classes: Mapping[str, GlossaryText]
    operators: Mapping[str, GlossaryText]
    events: Mapping[str, GlossaryText]
    store: str = GLOSSARY_STORE

    @property
    def label(self) -> str:
        """Version part of ``contract_meta.glossary_version``."""
        return f"glossary.yaml@{self.version}#{self.sha12}"


@dataclass(frozen=True)
class MergeTolerance:
    """``merge_threshold = <value> * sampling_rate`` frames in WatchOut."""

    samples: int
    origin_file: str
    origin_symbol: str


@dataclass(frozen=True)
class ConstantAudioConfidence:
    """The audio providers that write a fixed confidence instead of a model score."""

    value: float
    providers: tuple[str, ...]
    origin_file: str
    origin_symbol: str


@dataclass(frozen=True)
class PipelineConstants:
    """``pipeline_constants.yaml``: WatchOut values that K1 cannot read from code."""

    version: int
    merge_tolerance: MergeTolerance
    constant_audio_confidence: ConstantAudioConfidence
    store: str = CONSTANTS_STORE
