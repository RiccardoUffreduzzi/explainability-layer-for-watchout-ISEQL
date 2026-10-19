"""``SqliteWatchOutReader``: the ``WatchOutReader`` port over WatchOut's database and code.

Where WatchOut has a reading function that accepts a connection, the reader uses it
with the read-only connection; WatchOut's functions that open a connection of their
own (``_get_db_conn``, ``_config_conn``, ``_registry_conn``, ``setup_database``) are
never called.
"""

import ast
import inspect
import json
import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import Any, TypeGuard

from service.impl.config_store_service_impl import ConfigStoreServiceImpl
from service.impl.event_registry_service_impl import EventRegistryServiceImpl
from service.impl.events_service_impl import default_deltas_for, derive_delta_fields
from service.relation_vocab import signature_slots
from utils.vlm_client import VLMClient

from xai.adapters.watchout import engine, queries
from xai.contract.model import Condition, TimeUnit
from xai.contract.primitives import SourceRef, Stage
from xai.k1_harvester.ports import (
    AnalysisSnapshot,
    AudioIntervalRow,
    BackendVersion,
    Branch,
    Detection,
    EngineError,
    ModelForm,
    ParamsSnapshot,
    ParamValue,
    ParticipantRow,
    ResolvedOperator,
    RuleLayout,
    RuleSnapshot,
    VisualIntervalRow,
    VlmDefaults,
    Vocabulary,
)

BACKEND_DIR = Path(__file__).resolve().parents[3]
"""``backend``: this file is ``backend/xai/adapters/watchout/reader.py``."""

CONDITIONS: tuple[Condition, ...] = ("A", "B", "C")


class SqliteWatchOutReader:
    """Reads WatchOut database through a connection from ``open_read_only``."""

    def __init__(self, conn: sqlite3.Connection, backend_dir: Path = BACKEND_DIR) -> None:
        self.conn = conn
        self.backend_dir = backend_dir
        self._registry = EventRegistryServiceImpl()
        self._config = ConfigStoreServiceImpl()

    # Analyses (own SQL)

    def analysis(self, analysis_id: str) -> AnalysisSnapshot | None:
        row = queries.analysis_row(self.conn, analysis_id)
        if row is None:
            return None
        return AnalysisSnapshot(
            analysis_id=str(row["ID"]),
            condition=str(row["Condition"]),
            stage=str(row["Stage"]),
            vlm_provider=_text(row["VLMProvider"]),
            model=_text(row["Model"]),
            audio_provider=_text(row["AudioProvider"]),
            audio_model=_text(row["AudioModel"]),
            audio_quantization=_text(row["AudioQuantization"]),
            sampling_rate=None if row["SamplingRate"] is None else int(row["SamplingRate"]),
            audio_window=None if row["AudioWindow"] is None else float(row["AudioWindow"]),
            audio_hop=None if row["AudioHop"] is None else float(row["AudioHop"]),
        )

    # EventSpec (registry)

    def rule(self, event_type: str, condition: Condition) -> RuleSnapshot | None:
        spec = self._registry.get_event(self.conn, event_type, condition)
        return None if spec is None or not spec.model_json else _snapshot(spec.id, condition, spec.model_json)

    def rules(self, condition: Condition) -> list[RuleSnapshot]:
        """The rules WatchOut compiles for a condition, in its order (condition, id)."""
        specs = self._registry.list_events(self.conn, condition=condition)
        return [_snapshot(s.id, condition, s.model_json) for s in specs if s.model_json]

    # parameters

    def saved_params(self, analysis_id: str) -> ParamsSnapshot | None:
        """``Analyses.DeltasJson`` as ``detect_event`` wrote it: ``{"deltas": …, "unit": …}``."""
        text, column_unit = queries.saved_params_row(self.conn, analysis_id)
        if not text:
            return None
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None
        deltas = data.get("deltas") if isinstance(data, dict) else None
        if not isinstance(deltas, dict):
            return None
        unit = data.get("unit") or column_unit or "seconds"
        return ParamsSnapshot(
            origin="saved_by_gui",
            unit=_unit(unit),
            values={str(k): v for k, v in deltas.items() if _is_param_value(v)},
            analysis_id=analysis_id,
        )

    def default_params(self) -> ParamsSnapshot:
        """ The defaults the GUI pre-fills: ``default_deltas_for`` of every rule """
        merged: dict[str, ParamValue] = {}
        per_rule: dict[str, dict[str, ParamValue]] = {}
        provider: dict[str, str] = {}
        for condition in CONDITIONS:
            for spec in self._registry.list_events(self.conn, condition=condition):
                if not spec.model_json:
                    continue
                fields = {f: k for f, k in derive_delta_fields(spec.model_json).items() if k}
                defaults = {
                    str(k): v
                    for k, v in default_deltas_for(spec.model_json, spec.id, fields).items()
                    if _is_param_value(v)
                }
                ref = f"{spec.id}/{condition}"
                per_rule[ref] = defaults
                for key, value in defaults.items():
                    merged[key] = value
                    provider[key] = ref
        return ParamsSnapshot(
            origin="rule_defaults", unit="seconds", values=merged, rule_defaults=per_rule, provider=provider
        )

    # AppConfig

    def vocabulary(self) -> Vocabulary | None:
        relations = self._config.get_section(self.conn, "relation_vocab")
        audio = self._config.get_section(self.conn, "audio_taxonomy")
        if relations is None or audio is None:
            return None
        signatures = {str(name): str(sig) for name, sig in relations.get("relation_classids") or []}
        return Vocabulary(
            signatures=signatures,
            slots={
                name: tuple(tuple(slot) for slot in signature_slots(sig)) for name, sig in signatures.items()
            },
            descriptions={str(k): str(v) for k, v in (relations.get("relation_descriptions") or {}).items()},
            audio_classes=tuple(str(c) for c in audio.get("classes") or []),
            relation_vocab_updated_at=queries.appconfig_updated_at(self.conn, "relation_vocab"),
        )

    #  ISEQL+ engine

    def detect(self, rule: RuleSnapshot, analysis: AnalysisSnapshot, params: ParamsSnapshot) -> Detection:
        return engine.detect(self.conn, rule, analysis, params)

    def rule_layout(self, rule: RuleSnapshot, form: ModelForm) -> RuleLayout:
        return engine.rule_layout(rule, form)

    def resolve_operator(
        self,
        rule: RuleSnapshot,
        form: ModelForm,
        branch: Branch,
        pair_index: int,
        params: ParamsSnapshot,
        fps: int | None,
    ) -> ResolvedOperator:
        return engine.resolve_operator(self.conn, rule, form, branch, pair_index, params, fps)

    def render_rule(self, rule: RuleSnapshot, params: ParamsSnapshot) -> str:
        return engine.render_rule(rule, params)

    #  interval tables

    def visual_intervals(self, analysis_id: str, predicates: set[str]) -> list[VisualIntervalRow]:
        return [
            VisualIntervalRow(
                relation_id=int(r["RelationID"]),
                start_frame=int(r["StartFrame"]),
                end_frame=int(r["EndFrame"]),
                relation_type=str(r["RelationType"]),
            )
            for r in queries.visual_intervals(self.conn, analysis_id, sorted(predicates))
        ]

    def participants(self, relation_ids: Sequence[int]) -> list[ParticipantRow]:
        return [
            ParticipantRow(
                relation_id=int(r["RelationID"]), class_id=int(r["ClassID"]), class_name=str(r["Class"])
            )
            for r in queries.participants(self.conn, sorted(set(relation_ids)))
        ]

    def audio_intervals(self, analysis_id: str, classes: set[str]) -> list[AudioIntervalRow]:
        return [
            AudioIntervalRow(
                interval_id=int(r["AudioIntervalID"]),
                start_frame=int(r["StartFrame"]),
                end_frame=int(r["EndFrame"]),
                audio_class=str(r["AudioClass"]),
                confidence=None if r["Confidence"] is None else float(r["Confidence"]),
            )
            for r in queries.audio_intervals(self.conn, analysis_id, sorted(classes))
        ]

    # values that only exist in code

    def vlm_defaults(self) -> VlmDefaults:
        """Defaults of ``VLMClient.__init__``, which the analysis creates without them."""
        parameters = inspect.signature(VLMClient.__init__).parameters
        temperature = parameters["temperature"].default
        seed = parameters["seed"].default
        if isinstance(temperature, bool) or not isinstance(temperature, int | float):
            raise EngineError(f"VLMClient temperature default is not a number: {temperature!r}")
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise EngineError(f"VLMClient seed default is not an integer: {seed!r}")
        return VlmDefaults(temperature=float(temperature), seed=seed)

    def backend_version(self) -> BackendVersion | None:
        """``__app_name__`` and ``__version__`` of ``backend/src/__init__.py``, plus the git commit."""
        names = _assigned_strings(self.backend_dir / "src" / "__init__.py", ("__app_name__", "__version__"))
        commit = _git_head(self.backend_dir)
        version = " ".join(names[n] for n in ("__app_name__", "__version__") if n in names)
        if "__version__" not in names:
            if commit is None:
                return None
            return BackendVersion(
                text=f"git {commit[:12]}",
                source=SourceRef(stage=Stage.CODE, store=".git", record_id="HEAD", mode="read"),
            )
        record_id = ", ".join(n for n in ("__app_name__", "__version__") if n in names)
        if commit is not None:
            version = f"{version} (git {commit[:12]})"
            record_id = f"{record_id}; .git HEAD"
        return BackendVersion(
            text=version,
            source=SourceRef(
                stage=Stage.CODE, store="backend/src/__init__.py", record_id=record_id, mode="read"
            ),
        )


def _snapshot(event_type: str, condition: Condition, model_json: str) -> RuleSnapshot:
    try:
        model = json.loads(model_json)
    except json.JSONDecodeError as exc:
        raise EngineError(f"EventSpec {event_type}/{condition}: model_json is not valid JSON") from exc
    if not isinstance(model, dict):
        raise EngineError(f"EventSpec {event_type}/{condition}: model_json is not an object")
    return RuleSnapshot(event_type=event_type, condition=condition, model=model)


def _text(value: Any) -> str | None:
    return None if value is None or value == "" else str(value)


def _unit(value: Any) -> TimeUnit:
    # detect_event converts only when the unit is "seconds"; anything else is used as frames.
    return "seconds" if value == "seconds" else "frames"


def _is_param_value(value: object) -> TypeGuard[ParamValue]:
    return isinstance(value, int | float | str) and not isinstance(value, bool)


def _assigned_strings(path: Path, names: Sequence[str]) -> dict[str, str]:
    """Module-level ``NAME = "text"`` assignments, read without importing the module."""
    if not path.is_file():
        return {}
    found: dict[str, str] = {}
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in names and isinstance(node.value.value, str):
                    found[target.id] = node.value.value
    return found


def _git_head(start: Path) -> str | None:
    """The commit checked out in the repository that contains ``start``, read from ``.git``."""
    for folder in (start, *start.parents):
        git = folder / ".git"
        if git.is_file():
            pointer = git.read_text(encoding="utf-8").strip()
            if not pointer.startswith("gitdir:"):
                return None
            git = (folder / pointer[len("gitdir:") :].strip()).resolve()
        if git.is_dir():
            return _resolve_head(git)
    return None


def _resolve_head(git_dir: Path) -> str | None:
    head_file = git_dir / "HEAD"
    if not head_file.is_file():
        return None
    head = head_file.read_text(encoding="utf-8").strip()
    if not head.startswith("ref:"):
        return head or None
    ref = head[len("ref:") :].strip()
    common = git_dir
    commondir = git_dir / "commondir"
    if commondir.is_file():
        common = (git_dir / commondir.read_text(encoding="utf-8").strip()).resolve()
    for base in (git_dir, common):
        ref_file = base / ref
        if ref_file.is_file():
            return ref_file.read_text(encoding="utf-8").strip() or None
    packed = common / "packed-refs"
    if packed.is_file():
        for line in packed.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1] == ref:
                return parts[0]
    return None
