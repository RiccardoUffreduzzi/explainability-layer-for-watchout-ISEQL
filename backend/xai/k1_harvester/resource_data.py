"""Data that K1 receives as values: the glossary"""

from collections.abc import Mapping
from dataclasses import dataclass

GLOSSARY_FILE = "glossary.yaml"


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


@dataclass(frozen=True)
class Glossary:
    """``glossary.yaml``: report phrases, operators, audio classes, events and comparisons."""

    version: str
    sha12: str
    """First 12 hex digits of the sha256 of the file"""
    predicates: Mapping[str, GlossaryText]
    audio_classes: Mapping[str, GlossaryText]
    operators: Mapping[str, GlossaryText]
    events: Mapping[str, GlossaryText]
    comparisons: Mapping[str, GlossaryText]
    """Conditions between variables, by ``comparison_term``"""
    file: str = GLOSSARY_FILE
    """``record_id`` prefix of the SourceRefs pointing to an entry."""

    @property
    def label(self) -> str:
        """Version part of ``contract_meta.glossary_version``."""
        return f"glossary.yaml@{self.version}#{self.sha12}"
