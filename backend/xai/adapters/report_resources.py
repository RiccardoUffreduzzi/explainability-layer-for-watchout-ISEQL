"""Loads the resources of the reports: value labels, configuration, prompt templates and sentences."""

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from xai.reporting.catalogue import LlmConfig, ReportConfig, SystemSentences, ValueLabels
from xai.reporting.prompt import PromptTemplate

RESOURCES_DIR = Path(__file__).resolve().parents[1] / "resources"
VALUE_LABELS_PATH = RESOURCES_DIR / "value_labels.yaml"
REPORT_CONFIG_PATH = RESOURCES_DIR / "report_config.yaml"
PROMPTS_DIR = RESOURCES_DIR / "prompts"
SENTENCES_DIR = RESOURCES_DIR / "sentences"

TIME_FORMATS = ("m:ss",)


def load_value_labels(path: Path = VALUE_LABELS_PATH) -> ValueLabels:
    data = _mapping(yaml.safe_load(path.read_text(encoding="utf-8")), path.name)
    values = _mapping(data.get("values") or {}, f"{path.name}:values")
    return ValueLabels(
        version=str(_required(data, "version", path.name)),
        fields=_texts(data.get("fields") or {}, f"{path.name}:fields"),
        values={str(name): _texts(coded, f"{path.name}:values.{name}") for name, coded in values.items()},
        reasons=_texts(data.get("reasons") or {}, f"{path.name}:reasons"),
        missing_fields=_texts(data.get("missing_fields") or {}, f"{path.name}:missing_fields"),
        codes=_texts(data.get("codes") or {}, f"{path.name}:codes"),
    )


def load_report_config(path: Path = REPORT_CONFIG_PATH) -> ReportConfig:
    data = _mapping(yaml.safe_load(path.read_text(encoding="utf-8")), path.name)
    llm_data = data.get("llm")
    llm = None
    if llm_data is not None:
        llm_map = _mapping(llm_data, f"{path.name}:llm")
        seed = llm_map.get("seed")
        llm = LlmConfig(
            provider=str(_required(llm_map, "provider", f"{path.name}:llm")),
            model=str(_required(llm_map, "model", f"{path.name}:llm")),
            temperature=float(llm_map.get("temperature", 0.0)),
            seed=None if seed is None else int(seed),
            timeout_s=float(llm_map.get("timeout_s", 60.0)),
            max_tokens=int(llm_map.get("max_tokens", 8192)),
        )
    attempts = int(_required(data, "max_attempts", path.name))
    if attempts < 1:
        raise ValueError(f"{path.name}: max_attempts must be at least 1")
    time_format = str(data.get("time_format", "m:ss"))
    if time_format != "m:ss":
        raise ValueError(f"{path.name}: time_format must be one of {TIME_FORMATS}")
    return ReportConfig(llm=llm, max_attempts=attempts, time_format="m:ss")


def load_prompt(name: str, folder: Path = PROMPTS_DIR) -> PromptTemplate:
    path = folder / f"{name}.txt"
    return PromptTemplate(name=name, text=path.read_text(encoding="utf-8").replace("\r\n", "\n"))


def load_sentences(name: str, folder: Path = SENTENCES_DIR) -> SystemSentences:
    path = folder / f"{name}.yaml"
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    data = _mapping(yaml.safe_load(text), path.name)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()

    def part(key: str) -> dict[str, str]:
        return _texts(_required(data, key, path.name), f"{path.name}:{key}")

    return SystemSentences(
        version=f"{name}@{digest[:12]}",
        steps=part("steps"),
        bindings=part("bindings"),
        intervals=part("intervals"),
        limits=part("limits"),
    )


def _texts(value: Any, where: str) -> dict[str, str]:
    return {str(key): str(text) for key, text in _mapping(value, where).items()}


def _mapping(value: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{where}: expected a mapping")
    return value


def _required(data: Mapping[str, Any], key: str, where: str) -> Any:
    if data.get(key) is None:
        raise ValueError(f"{where}: missing {key!r}")
    return data[key]
