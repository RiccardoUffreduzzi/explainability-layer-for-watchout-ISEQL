"""Ablation databases: old schema, no ``AppConfig``, F3 rules, a whole dataset.

The ablation databases have no ``Analyses`` rows: K1 refuses them with
``ANALYSIS_NOT_FOUND``. The other tests add the rows, in the
columns the old table has, to read the rest. With the parameters the GUI pre-fills
WatchOut cannot run their rules (``'inf'`` defaults from the F3 rules): K1 records
the engine's error for every rule. With usable parameters the F3 rows are read by
side and every row gets a draft.
"""

import sqlite3
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

import pytest

from xai.cli import pipeline as pipeline_cli
from xai.contract.reasons import InputError, NoteCode
from xai.k1_harvester.batch import AnalysisHarvester, AnalysisOutcome
from xai.k1_harvester.result import HarvestFailure
from xai.tests.harness import make_batch, open_reader
from xai.tests.support import (
    ABLATION_DB,
    add_analyses,
    build_ablation_db,
    consolidated_copy,
    copy_db,
    scene,
)

F3_EVENTS = ("fight", "gunshot_or_explosion", "vehicle_collision", "vehicle_escape")
S15 = scene(15)


@pytest.fixture(scope="module")
def ablation_db(seed_db: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Shaped like an ablation database: no Analyses or AppConfig rows."""
    return build_ablation_db(tmp_path_factory.mktemp("ablation") / "ablation.db")


@pytest.fixture(scope="module")
def ablation_with_analyses(ablation_db: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    db = copy_db(ablation_db, tmp_path_factory.mktemp("ablation_rows"))
    add_analyses(db)
    return db


@pytest.fixture
def batch_on_ablation(ablation_with_analyses: Path, seed_db: Path) -> Iterator[AnalysisHarvester]:
    conn, reader = open_reader(ablation_with_analyses, seed_db)
    yield make_batch(reader)
    conn.close()


def _analyses(db: Path) -> list[str]:
    conn = sqlite3.connect(f"{db.as_uri()}?mode=ro", uri=True)
    try:
        return [row[0] for row in conn.execute("SELECT ID FROM Analyses ORDER BY ID")]
    finally:
        conn.close()


# ----------------------------------------------------------------------------- as the ablation databases are


def test_an_analysis_without_its_row_is_refused(ablation_db: Path, seed_db: Path, tmp_path: Path) -> None:
    argv = ["run", "--analysis", S15, "--db", str(ablation_db), "--config-db", str(seed_db)]

    assert pipeline_cli.main([*argv, "--out", str(tmp_path)]) == 2
    log = (tmp_path / S15 / "pipeline.log").read_text(encoding="utf-8")
    assert InputError.ANALYSIS_NOT_FOUND.value in log


def test_without_config_db_the_configuration_is_missing(ablation_with_analyses: Path) -> None:
    conn, reader = open_reader(ablation_with_analyses)
    try:
        with pytest.raises(HarvestFailure) as failure:
            make_batch(reader).harvest(S15, "C")
    finally:
        conn.close()

    assert failure.value.code == InputError.CONFIG_MISSING


def test_the_old_analyses_table_is_read(ablation_with_analyses: Path, seed_db: Path) -> None:
    conn, reader = open_reader(ablation_with_analyses, seed_db)
    try:
        analysis = reader.analysis(S15)
    finally:
        conn.close()

    assert analysis is not None
    assert (analysis.sampling_rate, analysis.audio_window, analysis.audio_hop) == (24, None, None)


# ----------------------------------------------------------------------------- with the GUI's defaults


def test_with_the_gui_defaults_every_rule_records_the_engine_error(
    batch_on_ablation: AnalysisHarvester, ablation_with_analyses: Path
) -> None:
    """``default_deltas_for`` gives ``'inf'`` to every key of a legacy F3 rule, ζ and ρ too;
    the GUI merges the C rules last, so ``_resolve_deltas`` refuses every condition."""
    errors: Counter[str] = Counter()
    for analysis_id in _analyses(ablation_with_analyses):
        for condition in ("A", "B", "C"):
            outcome = batch_on_ablation.harvest(analysis_id, condition, "defaults")
            for rule in outcome.rules:
                assert rule.failure is None and rule.results == ()
                assert (
                    rule.engine_error is not None and "invalid strictness operator 'inf'" in rule.engine_error
                )
                errors[rule.rule_ref] += 1

    assert len(errors) == 16
    assert set(errors.values()) == {30}


# ----------------------------------------------------------------------------- with usable parameters


@pytest.fixture(scope="module")
def outcomes(ablation_rules_db: Path) -> Iterator[dict[tuple[str, str], AnalysisOutcome]]:
    conn, reader = open_reader(ablation_rules_db)
    batch = make_batch(reader)
    yield {
        (analysis_id, condition): batch.harvest(analysis_id, condition, "saved")
        for analysis_id in _analyses(ablation_rules_db)
        for condition in ("A", "B", "C")
    }
    conn.close()


def test_every_row_gets_a_draft(outcomes: dict[tuple[str, str], AnalysisOutcome]) -> None:
    drafts = 0
    for outcome in outcomes.values():
        assert outcome.params_origin == "saved_by_gui"
        for rule in outcome.rules:
            assert (rule.failure, rule.engine_error) == (None, None), rule.rule_ref
            for result in rule.results:
                assert result.draft is not None or result.duplicate_of is not None, (rule.rule_ref, result)
                drafts += result.draft is not None

    assert drafts >= 100


def test_f3_rows_are_the_rows_of_their_modality_rules(
    outcomes: dict[tuple[str, str], AnalysisOutcome],
) -> None:
    """Each C row of an F3 rule is read as one side and found among the rows of Evento_A or Evento_B."""
    by_origin: Counter[tuple[str, str | None]] = Counter()
    own: Counter[tuple[str, str]] = Counter()
    for (_, condition), outcome in outcomes.items():
        for rule in outcome.rules:
            event_type = rule.event_type
            if event_type not in F3_EVENTS:
                continue
            if condition == "C":
                for draft in (r.draft for r in rule.results if r.draft is not None):
                    assert draft.rule.model_form == "F3"
                    by_origin[event_type, draft.event.modality_origin] += 1
            else:
                own[event_type, "visual" if condition == "A" else "audio"] += rule.rows_returned or 0

    assert all(origin is not None for _, origin in by_origin)
    assert {k: v for k, v in by_origin.items() if v} == {k: v for k, v in own.items() if v}


def test_a_visual_f3_row_has_its_vehicle_in_the_st_column(
    outcomes: dict[tuple[str, str], AnalysisOutcome],
) -> None:
    rule = next(r for r in outcomes[S15, "C"].rules if r.rule_ref == "vehicle_collision/C")
    rows = {r.row["st"]: r.draft for r in rule.results}
    audio, visual = rows[0.0], rows[12.0]
    assert audio is not None and visual is not None

    assert audio.event.modality_origin == "audio"
    assert audio.event.origin_basis is not None and audio.event.origin_basis.branch == "left"
    assert audio.event.arguments == []
    assert (audio.event.interval.start_s, audio.event.interval.end_s) == (0.0, 7.5)

    assert visual.event.modality_origin == "visual"
    assert visual.event.origin_basis is not None and visual.event.origin_basis.branch == "right"
    [argument] = visual.event.arguments
    assert (argument.column, argument.role, argument.class_, argument.entity_id) == (
        "st",
        "M1.arg1",
        "vehicle",
        "ent_12",
    )
    assert (visual.event.interval.start_s, visual.event.interval.end_s) == (6.0, 10.0)
    notes = [n.detail for n in visual.harvest_report.notes if n.code == NoteCode.C_LABELS_BY_KIND]
    assert notes and "read by position as its right side" in notes[0]


# ----------------------------------------------------------------------------- a whole ablation dataset


def test_a_whole_ablation_dataset_without_unhandled_exceptions(seed_db: Path, tmp_path: Path) -> None:
    """Every analysis of the database the fixtures come from, every condition."""
    if not ABLATION_DB.is_file() or not ABLATION_DB.read_bytes()[:16].startswith(b"SQLite format 3"):
        pytest.skip(f"ablation database not available: {ABLATION_DB}")
    db = consolidated_copy(ABLATION_DB, tmp_path / ABLATION_DB.name)
    analyses = add_analyses(db)
    conn, reader = open_reader(db, seed_db)
    try:
        batch = make_batch(reader)
        outcomes = [batch.harvest(a, c, "defaults") for a in analyses for c in ("A", "B", "C")]
    finally:
        conn.close()

    assert len(analyses) >= 30
    assert [len(o.rules) for o in outcomes[:3]] == [6, 4, 6]
