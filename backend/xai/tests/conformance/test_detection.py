"""K1's rows are the rows ``detect_event`` hands to the GUI.

``detect_event`` writes ``DeltasJson``, so it runs on a copy of the test database,
for every scene and every rule of the seed, with the parameters the GUI pre-fills.
"""

import json
from pathlib import Path

import pytest

from xai.k1_harvester.ports import EngineError
from xai.tests.harness import open_reader
from xai.tests.support import FIXTURE_PATH


def test_rows_equal_those_of_detect_event(watchout_db_copy: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from service.impl.analysis_service_impl import AnalysisServiceImpl
    from utils.config import Config

    monkeypatch.setitem(Config.get().data, "db_path", str(watchout_db_copy))
    service = AnalysisServiceImpl()
    conn, reader = open_reader(watchout_db_copy)
    analyses = list(json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["conditions"])
    params = reader.default_params()
    rows_compared, failures, engine_errors = 0, [], []
    try:
        for analysis_id in analyses:
            analysis = reader.analysis(analysis_id)
            assert analysis is not None
            for condition in ("A", "B", "C"):
                for rule in reader.rules(condition):
                    gui = service.detect_event(
                        analysis_id=analysis_id,
                        event_type=rule.event_type,
                        condition=condition,
                        deltas=dict(params.values),
                        unit="seconds",
                    )["rows"]
                    try:
                        ours = [dict(r.gui_values) for r in reader.detect(rule, analysis, params).rows]
                    except EngineError:
                        # detect_event drops the engine's ERROR lines: the GUI shows no rows.
                        engine_errors.append(f"{rule.ref}@{analysis_id}")
                        ours = []
                    rows_compared += len(gui)
                    if ours != gui:
                        failures.append(f"{rule.ref}@{analysis_id}: {ours} != {gui}")
    finally:
        conn.close()

    assert failures == []
    assert rows_compared >= 100
    assert all(e.startswith("fight/C@") for e in engine_errors), engine_errors
