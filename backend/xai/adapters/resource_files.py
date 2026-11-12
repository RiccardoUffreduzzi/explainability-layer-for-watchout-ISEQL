"""Loads the glossary file"""

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from xai.k1_harvester.resource_data import Glossary, GlossaryText, ParameterReadingText

RESOURCES_DIR = Path(__file__).resolve().parents[1] / "resources"
GLOSSARY_PATH = RESOURCES_DIR / "glossary.yaml"

_GLOSSARY_SECTIONS = ("predicates", "audio_classes", "operators", "events", "comparisons")
_DEFINED_BY_WATCHOUT = ("predicates", "audio_classes", "events")
"""Sections whose definitions K1 reads from WatchOut: the file has only their report phrases."""


def load_glossary(path: Path = GLOSSARY_PATH) -> Glossary:
    raw = path.read_bytes()
    data = _mapping(yaml.safe_load(raw), str(path))
    sections = {name: _entries(data.get(name) or {}, f"{path.name}:{name}") for name in _GLOSSARY_SECTIONS}
    for name in _DEFINED_BY_WATCHOUT:
        defined = sorted(term for term, text in sections[name].items() if text.definition is not None)
        if defined:
            raise ValueError(f"{path.name}:{name}: definitions are read from WatchOut, remove: {defined}")
    text = raw.replace(b"\r\n", b"\n")
    return Glossary(
        version=str(_required(data, "version", path.name)),
        sha12=hashlib.sha256(text).hexdigest()[:12],
        predicates=sections["predicates"],
        audio_classes=sections["audio_classes"],
        operators=sections["operators"],
        events=sections["events"],
        comparisons=sections["comparisons"],
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
        entries[str(term)] = GlossaryText(
            plain_template=str(_required(entry, "plain_template", f"{where}.{term}")),
            definition=None if definition is None else str(definition),
            parameter_readings=readings,
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
