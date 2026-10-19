"""One row: the refusals with their codes, saved parameters, the command."""

import json
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from xai.cli import k1 as k1_cli
from xai.contract.model import Violation
from xai.contract.reasons import CheckName, InputError
from xai.k1_harvester.request import HarvestRequest
from xai.k1_harvester.result import HarvestFailure
from xai.k1_harvester.service import StageHarvester
from xai.tests.harness import GOLDEN_CASES, make_stage, open_reader
from xai.tests.support import scene

HANDOFF = GOLDEN_CASES[0]
assert HANDOFF.name == "handoff_s21_A"
S21 = scene(21)


def _change(db: Path, *statements: tuple[str, tuple[Any, ...]]) -> None:
    conn = sqlite3.connect(db)
    with conn:
        for sql, args in statements:
            conn.execute(sql, args)
    conn.close()


def _harvest_on(db: Path, request: HarvestRequest) -> Any:
    conn, reader = open_reader(db)
    try:
        return make_stage(reader).harvest(request)
    finally:
        conn.close()


def _refusal(call: Callable[[], object]) -> InputError | None:
    with pytest.raises(HarvestFailure) as failure:
        call()
    assert failure.value.stage == "input"
    return failure.value.code


# ----------------------------------------------------------------------------- refusals on the test database


@pytest.mark.parametrize(
    ("request_", "code"),
    [
        (HarvestRequest("no_such_analysis", "handoff", HANDOFF.row, "A"), InputError.ANALYSIS_NOT_FOUND),
        (HarvestRequest(S21, "no_such_event", HANDOFF.row, "A"), InputError.RULE_NOT_FOUND),
        (HarvestRequest(S21, "suspicious_near_vehicle", {}, "B"), InputError.RULE_NOT_FOUND),
        (
            HarvestRequest(S21, "handoff", {**HANDOFF.row, "M1_object": 7}, "A"),
            InputError.EVENT_NOT_REPRODUCIBLE,
        ),
        (HarvestRequest(S21, "handoff", {"M1_person": 3}, "A"), InputError.EVENT_NOT_REPRODUCIBLE),
        (HarvestRequest(S21, "handoff", HANDOFF.row, "A", "saved"), InputError.ANALYSIS_PARAMS_MISSING),
    ],
    ids=["analysis", "event", "no B rule", "other value", "missing column", "no saved params"],
)
def test_refusals(stage: StageHarvester, request_: HarvestRequest, code: InputError) -> None:
    assert _refusal(lambda: stage.harvest(request_)) == code


@pytest.mark.parametrize("stage_value", ["running", "failed", "stopped"])
def test_an_analysis_not_done_is_not_ready(watchout_db_copy: Path, stage_value: str) -> None:
    _change(watchout_db_copy, ("UPDATE Analyses SET Stage = ? WHERE ID = ?", (stage_value, S21)))

    assert _refusal(lambda: _harvest_on(watchout_db_copy, HANDOFF.request)) == InputError.ANALYSIS_NOT_READY


def test_a_grouped_rule_is_unsupported(watchout_db_copy: Path) -> None:
    conn = sqlite3.connect(watchout_db_copy)
    (model_json,) = conn.execute(
        "SELECT model_json FROM EventSpec WHERE id = 'handoff' AND condition = 'A'"
    ).fetchone()
    conn.close()
    model = json.loads(model_json)
    model["intervals"][0]["group_id"] = "g1"  # form F4
    _change(
        watchout_db_copy,
        (
            "UPDATE EventSpec SET model_json = ? WHERE id = 'handoff' AND condition = 'A'",
            (json.dumps(model),),
        ),
    )

    assert (
        _refusal(lambda: _harvest_on(watchout_db_copy, HANDOFF.request)) == InputError.UNSUPPORTED_CONSTRUCT
    )


def test_without_the_configuration_k1_stops(watchout_db_copy: Path) -> None:
    _change(watchout_db_copy, ("DELETE FROM AppConfig WHERE key = 'relation_vocab'", ()))

    assert _refusal(lambda: _harvest_on(watchout_db_copy, HANDOFF.request)) == InputError.CONFIG_MISSING


def test_saved_parameters_lacking_a_key_are_missing(watchout_db_copy: Path) -> None:
    deltas = json.dumps({"deltas": {}, "unit": "seconds"})
    _change(watchout_db_copy, ("UPDATE Analyses SET DeltasJson = ? WHERE ID = ?", (deltas, S21)))

    assert _refusal(lambda: _harvest_on(watchout_db_copy, HANDOFF.request_with("auto"))) == (
        InputError.ANALYSIS_PARAMS_MISSING
    )


# ----------------------------------------------------------------------- parameters saved by the GUI


def test_saved_parameters_are_used_and_cited(watchout_db_copy: Path) -> None:
    conn, reader = open_reader(watchout_db_copy)
    values = dict(reader.default_params().values)
    conn.close()
    saved = json.dumps({"deltas": values, "unit": "seconds"})
    _change(watchout_db_copy, ("UPDATE Analyses SET DeltasJson = ? WHERE ID = ?", (saved, S21)))

    draft = _harvest_on(watchout_db_copy, HANDOFF.request_with("auto"))

    assert draft.contract_meta.params_origin == "saved_by_gui"
    sources = [
        p.source_ref
        for node in draft.rule.constraints
        if node.kind == "temporal_operator"
        for p in node.payload.params
        if p.origin == "named_key"
    ]
    assert sources
    assert {s.store for s in sources} == {f"Analyses:{S21}#DeltasJson"}


# ----------------------------------------------------------------------------- the command


def _cli(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    code = k1_cli.main(argv)
    out, err = capsys.readouterr()
    return code, out, err


def test_harvest_prints_the_draft(watchout_db: Path, capsys: pytest.CaptureFixture[str]) -> None:
    row = json.dumps(HANDOFF.row)
    argv = ["harvest", "--analysis", S21, "--event", "handoff", "--row", row, "--db", str(watchout_db)]

    code, out, _ = _cli(argv, capsys)

    assert code == 0
    assert json.loads(out)["event"]["event_id"] == "ev_beffcb6f2a6e"


def test_harvest_accepts_the_row_as_the_gui_shows_it(
    watchout_db: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    row = '{"M1_person": 3, "M2_person": 5, "M1_object": 4, "M1.st": "00:00:01.000", "M2.et": "00:00:08.000"}'
    argv = ["harvest", "--analysis", S21, "--event", "handoff", "--row", row, "--db", str(watchout_db)]

    code, out, _ = _cli(argv, capsys)

    assert code == 0
    assert json.loads(out)["event"]["event_id"] == "ev_beffcb6f2a6e"


def test_harvest_exits_2_with_the_code(watchout_db: Path, capsys: pytest.CaptureFixture[str]) -> None:
    argv = ["harvest", "--analysis", S21, "--event", "handoff", "--row", "{}", "--db", str(watchout_db)]

    code, out, err = _cli(argv, capsys)

    assert (code, out) == (2, "")
    assert '"code": "EVENT_NOT_REPRODUCIBLE"' in err


def test_harvest_exits_3_when_a_check_fails(
    watchout_db: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    broken = Violation(check=CheckName.REFERENTIAL_CLOSURE, element_path="event.label", detail="test")
    monkeypatch.setattr("xai.k1_harvester.service.check_referential_closure", lambda draft: [broken])
    argv = ["harvest", "--analysis", S21, "--event", "handoff", "--row", json.dumps(HANDOFF.row)]

    code, out, err = _cli([*argv, "--db", str(watchout_db)], capsys)

    assert (code, out) == (3, "")
    assert '"element_path": "event.label"' in err


def test_harvest_all_writes_the_drafts(
    watchout_db: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = ["harvest-all", "--analysis", scene(15), "--db", str(watchout_db), "--out", str(tmp_path)]

    code, out, _ = _cli(argv, capsys)

    assert code == 0
    index = json.loads(Path(out.strip()).read_text(encoding="utf-8"))
    assert (index["condition"], index["params"]) == ("C", "auto")
    assert index["summary"]["drafts"] == 4
