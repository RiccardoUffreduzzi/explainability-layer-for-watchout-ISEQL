"""the ``WatchOutRecords`` port over WatchOut's database.

If WatchOut has a reading function that accepts a connection, it is used with the
read-only connection
"""

import json
import sqlite3
from collections.abc import Sequence
from typing import Any

from service.impl.config_store_service_impl import ConfigStoreServiceImpl
from service.impl.event_registry_service_impl import EventRegistryServiceImpl
from service.impl.events_service_impl import default_params
from service.relation_vocab import signature_slots

from xai.adapters.watchout import queries
from xai.adapters.watchout.mapping import param_values
from xai.contract.model import Condition, TimeUnit
from xai.k1_harvester.ports import (
    AnalysisSnapshot,
    AudioIntervalRow,
    EngineError,
    FrameDescriptionRow,
    ParamsSnapshot,
    RuleSnapshot,
    VisualIntervalRow,
    Vocabulary,
)


class SqliteRecords:
    """Reads WatchOut's database through a connection from ``open_read_only``."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
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
            origin="saved_by_gui", unit=_unit(unit), values=param_values(deltas), analysis_id=analysis_id
        )

    def default_params(self) -> ParamsSnapshot:
        """The defaults the GUI pre-fills, merged by WatchOut's ``default_params``."""
        values, provided_by, by_rule = default_params(self.conn)
        return ParamsSnapshot(
            origin="rule_defaults",
            unit="seconds",
            values=param_values(values),
            rule_defaults={str(ref): param_values(defaults) for ref, defaults in by_rule.items()},
            provider={str(k): str(v) for k, v in provided_by.items()},
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
            audio_keywords={
                str(k): tuple(str(w) for w in words) for k, words in (audio.get("keywords") or {}).items()
            },
            relation_vocab_updated_at=queries.appconfig_updated_at(self.conn, "relation_vocab"),
            audio_taxonomy_updated_at=queries.appconfig_updated_at(self.conn, "audio_taxonomy"),
        )

    # interval tables

    def visual_intervals(self, relation_ids: Sequence[int]) -> list[VisualIntervalRow]:
        return [
            VisualIntervalRow(
                relation_id=int(r["RelationID"]),
                start_frame=int(r["StartFrame"]),
                end_frame=int(r["EndFrame"]),
                relation_type=str(r["RelationType"]),
            )
            for r in queries.visual_intervals(self.conn, sorted(set(relation_ids)))
        ]

    def audio_intervals(self, interval_ids: Sequence[int]) -> list[AudioIntervalRow]:
        return [
            AudioIntervalRow(
                interval_id=int(r["AudioIntervalID"]),
                start_frame=int(r["StartFrame"]),
                end_frame=int(r["EndFrame"]),
                audio_class=str(r["AudioClass"]),
                confidence=None if r["Confidence"] is None else float(r["Confidence"]),
            )
            for r in queries.audio_intervals(self.conn, sorted(set(interval_ids)))
        ]

    def frame_descriptions(self, analysis_id: str, class_ids: Sequence[int]) -> list[FrameDescriptionRow]:
        return [
            FrameDescriptionRow(
                frame=int(r["Frame"]),
                class_id=int(r["ClassID"]),
                block=int(r["Block"]),
                description=str(r["Description"]),
            )
            for r in queries.frame_descriptions(self.conn, analysis_id, sorted(set(class_ids)))
        ]


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
