"""Loads the glossary and pipeline constants files """

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from xai.k1_harvester.resource_data import (
    ConstantAudioConfidence,
    Glossary,
    GlossaryText,
    MergeTolerance,
    ParameterReadingText,
    PipelineConstants,
)

RESOURCES_DIR = Path(__file__).resolve().parents[1] / "resources"
GLOSSARY_PATH = RESOURCES_DIR / "glossary.yaml"
CONSTANTS_PATH = RESOURCES_DIR / "pipeline_constants.yaml"

_GLOSSARY_SECTIONS = ("predicates", "audio_classes", "operators", "events")


def load_glossary(path: Path = GLOSSARY_PATH) -> Glossary:
    raw = path.read_bytes()
    data = _mapping(yaml.safe_load(raw), str(path))
    sections = {name: _entries(data.get(name) or {}, f"{path.name}:{name}") for name in _GLOSSARY_SECTIONS}
    text = raw.replace(b"\r\n", b"\n")
    return Glossary(
        version=str(_required(data, "version", path.name)),
        sha12=hashlib.sha256(text).hexdigest()[:12],
        predicates=sections["predicates"],
        audio_classes=sections["audio_classes"],
        operators=sections["operators"],
        events=sections["events"],
    )


def load_pipeline_constants(path: Path = CONSTANTS_PATH) -> PipelineConstants:
    data = _mapping(yaml.safe_load(path.read_bytes()), str(path))
    constants = _mapping(_required(data, "constants", path.name), f"{path.name}:constants")
    merge = _mapping(_required(constants, "merge_tolerance", path.name), "merge_tolerance")
    if merge.get("unit") != "samples":
        raise ValueError(f"{path.name}: merge_tolerance.unit must be 'samples'")
    audio = _mapping(
        _required(constants, "constant_audio_confidence", path.name), "constant_audio_confidence"
    )
    merge_origin = _mapping(_required(merge, "origin", "merge_tolerance"), "merge_tolerance.origin")
    audio_origin = _mapping(
        _required(audio, "origin", "constant_audio_confidence"), "constant_audio_confidence.origin"
    )
    return PipelineConstants(
        version=int(_required(data, "version", path.name)),
        merge_tolerance=MergeTolerance(
            samples=int(_required(merge, "value", "merge_tolerance")),
            origin_file=str(_required(merge_origin, "file", "merge_tolerance.origin")),
            origin_symbol=str(_required(merge_origin, "symbol", "merge_tolerance.origin")),
        ),
        constant_audio_confidence=ConstantAudioConfidence(
            value=float(_required(audio, "value", "constant_audio_confidence")),
            providers=tuple(str(p) for p in _required(audio, "providers", "constant_audio_confidence")),
            origin_file=str(_required(audio_origin, "file", "constant_audio_confidence.origin")),
            origin_symbol=str(_required(audio_origin, "symbol", "constant_audio_confidence.origin")),
        ),
    )


def _entries(section: Any, where: str) -> dict[str, GlossaryText]:
    entries: dict[str, GlossaryText] = {}
    for term, value in _mapping(section, where).items():
        entry = _mapping(value, f"{where}.{term}")
        readings = tuple(
            ParameterReadingText(condition=str(r["condition"]), phrase=str(r["phrase"]))
            for r in entry.get("parameter_readings") or []
        )
        definition = entry.get("definition")
        citation = entry.get("citation")
        entries[str(term)] = GlossaryText(
            plain_template=str(_required(entry, "plain_template", f"{where}.{term}")),
            definition=None if definition is None else str(definition),
            parameter_readings=readings,
            citation=None if citation is None else str(citation),
        )
    return entries


def _mapping(value: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{where}: expected a mapping")
    return value


def _required(data: Mapping[str, Any], key: str, where: str) -> Any:
    if data.get(key) is None:
        raise ValueError(f"{where}: missing {key!r}")
    return data[key]
