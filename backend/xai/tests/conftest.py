from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from xai.tests.support import (
    EXAMPLE_PATHS,
    SEED_DB,
    build_fixture_db,
    consolidated_copy,
    copy_db,
    load_example,
    use_ablation_rules,
)

if TYPE_CHECKING:
    from xai.k1_harvester.service import StageHarvester
    from xai.tests.harness import PinnedReader


@pytest.fixture(params=EXAMPLE_PATHS, ids=[p.name for p in EXAMPLE_PATHS])
def example(request: pytest.FixtureRequest) -> dict[str, Any]:
    """Each example draft of tests/data, as JSON data."""
    path: Path = request.param
    return load_example(path)


OPERATOR_EXAMPLE_PATHS = [
    p
    for p in EXAMPLE_PATHS
    if any(c["kind"] == "temporal_operator" for c in load_example(p)["rule"]["constraints"])
]


@pytest.fixture(params=OPERATOR_EXAMPLE_PATHS, ids=[p.name for p in OPERATOR_EXAMPLE_PATHS])
def operator_example(request: pytest.FixtureRequest) -> dict[str, Any]:
    """The example drafts whose rule has a temporal operator."""
    path: Path = request.param
    return load_example(path)


@pytest.fixture(scope="session")
def watchout_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The test database (seed + 30 real scenes), built once; open it read-only."""
    if not SEED_DB.is_file():
        pytest.skip(f"WatchOut's seed is missing: {SEED_DB}")
    return build_fixture_db(tmp_path_factory.mktemp("watchout") / "analysis.db")


@pytest.fixture(scope="session")
def seed_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A copy of WatchOut's seed, as ``--config-db`` for the ablation databases."""
    if not SEED_DB.is_file():
        pytest.skip(f"WatchOut's seed is missing: {SEED_DB}")
    return consolidated_copy(SEED_DB, tmp_path_factory.mktemp("seed") / SEED_DB.name)


@pytest.fixture(scope="session")
def ablation_rules_db(watchout_db: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The test database with the ablation rules (F3) and usable parameters saved as the GUI saves them."""
    return use_ablation_rules(copy_db(watchout_db, tmp_path_factory.mktemp("ablation_rules")))


@pytest.fixture
def watchout_db_copy(watchout_db: Path, tmp_path: Path) -> Path:
    """A writable copy of the test database."""
    return copy_db(watchout_db, tmp_path / "db")


@pytest.fixture
def reader(watchout_db: Path) -> Iterator["PinnedReader"]:
    from xai.tests.harness import open_reader

    conn, pinned = open_reader(watchout_db)
    yield pinned
    conn.close()


@pytest.fixture
def stage(reader: "PinnedReader") -> "StageHarvester":
    from xai.tests.harness import make_stage

    return make_stage(reader)
