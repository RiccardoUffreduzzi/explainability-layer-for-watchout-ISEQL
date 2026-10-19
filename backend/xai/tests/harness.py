"""K1 wired to the test database, with the values that change between machines pinned.

Imports WatchOut (through the adapter): only the tests that use the test database
import this module, so the contract tests run without WatchOut's dependencies.
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from xai.adapters.clock import FixedClock
from xai.adapters.resource_files import load_glossary, load_pipeline_constants
from xai.adapters.watchout.connection import open_read_only
from xai.adapters.watchout.reader import SqliteWatchOutReader
from xai.contract.model import Condition
from xai.contract.primitives import SourceRef, Stage
from xai.k1_harvester.batch import AnalysisHarvester
from xai.k1_harvester.ports import BackendVersion
from xai.k1_harvester.request import HarvestRequest, ParamsMode
from xai.k1_harvester.service import StageHarvester
from xai.tests.support import EXAMPLES_DIR, scene

FIXED_TIME = datetime(2026, 10, 6, 20, 0, tzinfo=timezone.utc)

PINNED_VERSION = BackendVersion(
    text="WATCHOUT ISEQL 0.1.0",
    source=SourceRef(
        stage=Stage.CODE, store="backend/src/__init__.py", record_id="__app_name__, __version__", mode="read"
    ),
)


class PinnedReader(SqliteWatchOutReader):
    """The reader with WatchOut's version without the git commit, which changes at every commit."""

    def backend_version(self) -> BackendVersion | None:
        return PINNED_VERSION


def open_reader(db: Path, config_db: Path | None = None) -> tuple[sqlite3.Connection, PinnedReader]:
    conn = open_read_only(db, config_db)
    return conn, PinnedReader(conn)


def make_stage(reader: SqliteWatchOutReader) -> StageHarvester:
    return StageHarvester(reader, FixedClock(FIXED_TIME), load_glossary(), load_pipeline_constants())


def make_batch(reader: SqliteWatchOutReader) -> AnalysisHarvester:
    return AnalysisHarvester(make_stage(reader))


GoldenDatabase = Literal["test", "ablation_rules"]
"""``test``: the test database (``watchout_db``); ``ablation_rules``: the same with the
ablation rules and their saved parameters (``ablation_rules_db``)."""


@dataclass(frozen=True)
class GoldenCase:
    """A row of the test database and the file with its expected draft."""

    name: str
    scene: int
    event_type: str
    condition: Condition
    row: dict[str, Any]
    why: str
    database: GoldenDatabase = "test"
    params: ParamsMode = "defaults"

    @property
    def request(self) -> HarvestRequest:
        return self.request_with(self.params)

    def request_with(self, params: ParamsMode) -> HarvestRequest:
        return HarvestRequest(scene(self.scene), self.event_type, self.row, self.condition, params)

    @property
    def path(self) -> Path:
        return EXAMPLES_DIR / f"{self.name}.bozza.json"


GOLDEN_CASES = (
    GoldenCase(
        "handoff_s21_A",
        21,
        "handoff",
        "A",
        {"M1_person": 3, "M2_person": 5, "M1_object": 4, "M1.st": 1.0, "M2.et": 8.0},
        "two selections of the same predicate, Bef from the geometry, two identity conditions, no audio rule",
    ),
    GoldenCase(
        "vehicle_collision_s15_C_audio",
        15,
        "vehicle_collision",
        "C",
        {"M1_vehicle": None, "M1.st": 0.0, "M2.et": 7.5},
        "union of branches, SP override, disjunction, audio origin, detections in both modalities",
    ),
    GoldenCase(
        "vehicle_collision_s15_C_visual",
        15,
        "vehicle_collision",
        "C",
        {"M1_vehicle": 12.0, "M1.st": 6.0, "M2.et": 10.0},
        "the same rule, visual origin, C columns with misleading labels",
    ),
    GoldenCase(
        "fight_s5_A",
        5,
        "fight",
        "A",
        {"M1_person": 1, "M1_person2": 2, "M1.st": 0.0, "M1.et": 5.0},
        "arguments of the same class (args_ordered false), symmetric rows",
    ),
    GoldenCase(
        "suspicious_near_vehicle_s18_A",
        18,
        "suspicious_near_vehicle",
        "A",
        {"M1_person": 6, "M1_vehicle": 1, "M1.st": 2.0, "M1.et": 7.0},
        "duration node",
    ),
    GoldenCase(
        "gunshot_or_explosion_s7_A",
        7,
        "gunshot_or_explosion",
        "A",
        {"M1_person": 4, "M1.st": 5.0, "M1.et": 10.0},
        "disjunction with a different class per alternative: a vehicle in the M1_person column",
    ),
    GoldenCase(
        "vehicle_collision_s15_C_F3_visual",
        15,
        "vehicle_collision",
        "C",
        {"st": 12.0, "et": 6.0, "__p1": 10.0},
        "legacy set_side rule (F3) of the ablation databases: the visual row read by position, "
        "the vehicle in the st column",
        database="ablation_rules",
        params="saved",
    ),
)
