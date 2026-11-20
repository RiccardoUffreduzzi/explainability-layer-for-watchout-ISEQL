"""What the reports read from their resources: labels of the values, sentences and configuration.

The files are YAML and are read by an adapter (``xai.adapters.report_resources``)
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

TimeFormat = Literal["m:ss"]


@dataclass(frozen=True)
class ValueLabels:
    """English words for what the LLM would otherwise have to guess (``value_labels.yaml``)."""

    version: str
    fields: Mapping[str, str]
    """Value name -> what the value is"""
    values: Mapping[str, Mapping[str, str]]
    """Value name -> coded value -> words"""
    reasons: Mapping[str, str]
    """Reason of the contract (``Reason``) -> why the value is not available."""
    missing_fields: Mapping[str, str]
    """Path of ``harvest_report.missing_fields`` -> the data it names."""
    codes: Mapping[str, str]
    """Codes of the plan (binding basis and status) -> what they mean."""


@dataclass(frozen=True)
class SystemSentences:
    """The sentences the system writes in the sections the LLM does not write (``sentences/<name>.yaml``).

    ``{name}`` cites a value of the table, as in the LLM's text; ``<slot>`` is filled by the system.
    """

    version: str
    """``<name>@<first 12 hex digits of the SHA-256 of the file>``."""
    steps: Mapping[str, str]
    """Step ID -> its sentence."""
    bindings: Mapping[str, str]
    """Status of a binding -> how ``<bindings>`` names it, with ``<variable>`` and its ``<intervals>``."""
    intervals: Mapping[str, str]
    """``span`` (``<start>``, ``<end>``) and ``at`` (``<at>``, an interval of a single analysed frame)."""
    limits: Mapping[str, str]
    """``whole_detection`` and ``constructs`` (``<constructs>``): which steps the limits that follow
    concern; ``missing_fields``: the data the system does not save."""
    figure: Mapping[str, str]
    """The caption of the key frame: ``shown`` (``<time>``, ``<frame>``), ``shown_without_time``
    (``<frame>``) and ``not_available`` (``<frame>``, ``<reason>``)."""


@dataclass(frozen=True)
class LlmConfig:
    """The model that writes the reports; its key is only in the environment."""

    provider: str
    model: str
    temperature: float
    seed: int | None
    timeout_s: float
    max_tokens: int


@dataclass(frozen=True)
class ReportConfig:
    """``report_config.yaml``: ``llm`` is null when no LLM is configured"""

    llm: LlmConfig | None
    max_attempts: int
    time_format: TimeFormat
    key_frame_images: bool = True
    """True: Report 1 shows the key frame of the detection, extracted from the video."""
    image_width: int = 360
    """Width in pixels of the image of the key frame, as the GUI shows it."""
