"""The ablation rules (F3, ``set_side``) as WatchOut compiles and runs them.

The same checks as ``test_rules`` and ``test_detection``, on the test database with
the rules of an ablation database and usable parameters saved by the GUI, plus the
two facts the reading by side relies on: the compiler pads the shorter side at the
end, and WatchOut takes the extent of an F3 rule from its left side.
"""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from iseql.compiler import _pad_fields
from service.impl.events_service_impl import queries_for_condition

from xai.adapters.watchout.engine import _projection_extent, converted_deltas
from xai.k1_harvester.context import MODALITY_CONDITIONS
from xai.k1_harvester.ports import ParamsSnapshot
from xai.k1_harvester.predicates import branch_modality
from xai.tests.conformance.test_rules import CONDITIONS, FPS, _branch_facts, _fragment, _layout, _operators
from xai.tests.harness import PinnedReader, open_reader
from xai.tests.support import FIXTURE_PATH, copy_db


@pytest.fixture
def ablation_reader(ablation_rules_db: Path) -> Iterator[PinnedReader]:
    conn, reader = open_reader(ablation_rules_db)
    yield reader
    conn.close()


def _saved(reader: PinnedReader) -> ParamsSnapshot:
    analysis_id = next(iter(json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["conditions"]))
    params = reader.saved_params(analysis_id)
    assert params is not None
    return params


def test_the_f3_rules_are_read_by_side(ablation_reader: PinnedReader) -> None:
    f3 = []
    for rule in ablation_reader.rules("C"):
        form, layout = _layout(ablation_reader, rule)
        if form != "F3":
            continue
        assert layout.columns is None and layout.columns_problem
        assert set(layout.side_columns) == {"left", "right"}
        # WatchOut takes the extent of an F3 rule from its left side.
        assert _projection_extent(layout.branches[0].projection) == layout.extent
        f3.append(rule.event_type)

    assert f3 == ["fight", "gunshot_or_explosion", "vehicle_collision", "vehicle_escape"]


def test_the_compiler_pads_the_shorter_side_at_the_end() -> None:
    assert _pad_fields(["M1.st", "M2.et"], 4) == ["M1.st", "M2.et", "NULL AS __p1", "NULL AS __p2"]
    assert _pad_fields(["M1.arg1", "M1.st", "M1.et"], 3) == ["M1.arg1", "M1.st", "M1.et"]


def test_operators_of_the_ablation_rules_are_those_of_the_compiled_sql(ablation_reader: PinnedReader) -> None:
    params = _saved(ablation_reader)
    checked, failures = 0, []
    for condition in CONDITIONS:
        sql_by_event = queries_for_condition(
            condition, converted_deltas(params, FPS), "any_analysis", conn=ablation_reader.conn, fps=FPS
        )
        for rule in ablation_reader.rules(condition):
            sql = " ".join(sql_by_event[rule.event_type].split())
            _, layout = _layout(ablation_reader, rule)
            for branch in layout.branches:
                for k, operator in enumerate(_operators(ablation_reader, rule, branch, params)):
                    fragment = _fragment(operator, branch.intervals[k].alias, branch.intervals[k + 1].alias)
                    checked += 1
                    if fragment not in sql:
                        failures.append(f"{rule.ref} {branch.name} pair {k + 1}: {fragment} not in the SQL")

    assert failures == []
    assert checked >= 8


def test_each_f3_side_is_the_rule_of_its_modality(ablation_reader: PinnedReader) -> None:
    params = _saved(ablation_reader)
    vocabulary = ablation_reader.vocabulary()
    assert vocabulary is not None
    compared = []
    for rule in ablation_reader.rules("C"):
        form, layout = _layout(ablation_reader, rule)
        if form != "F3":
            continue
        for branch in layout.branches:
            modality = branch_modality(branch, vocabulary)
            assert modality in MODALITY_CONDITIONS, f"{rule.ref} {branch.name} mixes modalities"
            single = ablation_reader.rule(rule.event_type, MODALITY_CONDITIONS[modality])
            assert single is not None
            _, single_layout = _layout(ablation_reader, single)
            assert _branch_facts(ablation_reader, rule, branch, params) == _branch_facts(
                ablation_reader, single, single_layout.branches[0], params
            ), f"{rule.ref} {branch.name} differs from {single.ref}"
            compared.append(f"{rule.ref} {branch.name}")

    assert len(compared) == 8


def test_rows_equal_those_of_detect_event(
    ablation_rules_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from service.impl.analysis_service_impl import AnalysisServiceImpl
    from utils.config import Config

    db = copy_db(ablation_rules_db, tmp_path / "db")
    monkeypatch.setitem(Config.get().data, "db_path", str(db))
    service = AnalysisServiceImpl()
    conn, reader = open_reader(db)
    analyses = list(json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["conditions"])
    rows_compared, failures = 0, []
    try:
        for analysis_id in analyses:
            analysis = reader.analysis(analysis_id)
            params = reader.saved_params(analysis_id)
            assert analysis is not None and params is not None
            for condition in CONDITIONS:
                for rule in reader.rules(condition):
                    gui = service.detect_event(
                        analysis_id=analysis_id,
                        event_type=rule.event_type,
                        condition=condition,
                        deltas=dict(params.values),
                        unit=params.unit,
                    )["rows"]
                    ours = [dict(r.gui_values) for r in reader.detect(rule, analysis, params).rows]
                    rows_compared += len(gui)
                    if ours != gui:
                        failures.append(f"{rule.ref}@{analysis_id}: {ours} != {gui}")
    finally:
        conn.close()

    assert failures == []
    assert rows_compared >= 100
