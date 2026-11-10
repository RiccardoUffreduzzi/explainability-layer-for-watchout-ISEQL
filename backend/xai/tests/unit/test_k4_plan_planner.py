"""The planner: plan_meta, bindings, plan_report, hash; and the reading of the file of K2."""

import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from xai.contract.canonical import canonical_json
from xai.contract.plan import (
    PLAN_VERSION,
    compute_plan_hash,
    dump_plan,
    load_plan,
    plan_to_data,
)
from xai.contract.plan_schema import plan_schema
from xai.contract.source_of_truth import compute_contract_hash, dump_source_of_truth, source_of_truth_to_data
from xai.k4_planner.planner import ExplanationPlanner, PlanFailure, read_source
from xai.tests.k4_plan_support import plan_of, source_and_plan, translation_of
from xai.tests.k4_support import GOLDEN_NAMES, golden_source


@pytest.mark.parametrize("name", GOLDEN_NAMES)
def test_the_plan_meta_copies_the_source(name: str) -> None:
    document, plan = source_and_plan(name)
    meta = plan.plan_meta

    assert meta.plan_version == PLAN_VERSION
    assert meta.contract_hash == document.contract_meta.contract_hash
    assert meta.source_of_truth_version == document.contract_meta.source_of_truth_version
    assert meta.contract_version == document.contract_meta.contract_version
    assert (meta.event_id, meta.model_id, meta.label) == (
        document.event.event_id,
        document.event.model_id,
        document.event.label,
    )


@pytest.mark.parametrize("name", GOLDEN_NAMES)
def test_with_the_expected_translation_the_planner_gives_the_same_plan(name: str) -> None:
    # The planner does not depend on the rule readers: a translation made by hand gives the same plan.
    document = golden_source(name)
    translation = translation_of(name)

    by_hand = ExplanationPlanner(lambda view: translation).plan(document)

    assert dump_plan(by_hand) == dump_plan(ExplanationPlanner().plan(document))


@pytest.mark.parametrize("name", GOLDEN_NAMES)
def test_bindings_and_report_are_the_ones_of_the_translation(name: str) -> None:
    plan = plan_of(name)
    translation = translation_of(name)

    assert plan.bindings == [b for branch in translation.branches for b in branch.bindings]
    assert plan.plan_report.excluded_constructs == list(translation.excluded)
    assert plan.plan_report.unbound_intervals == list(translation.unbound_intervals)
    assert plan.plan_report.unmatched_readings == list(translation.unmatched_readings)
    assert plan.plan_report.notes == list(translation.notes)
    assert plan.plan_meta.branches == [branch.branch for branch in translation.branches]


@pytest.mark.parametrize("name", GOLDEN_NAMES)
def test_the_hash_is_the_one_of_the_content(name: str) -> None:
    plan = plan_of(name)

    assert compute_plan_hash(plan_to_data(plan)) == plan.plan_meta.plan_hash


@pytest.mark.parametrize("name", GOLDEN_NAMES)
def test_the_plan_agrees_with_its_schema_and_survives_a_round_trip(name: str) -> None:
    plan = plan_of(name)

    jsonschema.validate(plan_to_data(plan), plan_schema())
    assert load_plan(dump_plan(plan, indent=2)) == plan


@pytest.mark.parametrize("name", GOLDEN_NAMES)
def test_two_runs_give_the_same_text(name: str) -> None:
    document = golden_source(name)

    assert dump_plan(ExplanationPlanner().plan(document)) == dump_plan(ExplanationPlanner().plan(document))


def test_a_change_of_the_source_changes_the_hash() -> None:
    first = plan_of("fight_s5_A")
    other = plan_of("gunshot_or_explosion_s7_A")

    assert first.plan_meta.plan_hash != other.plan_meta.plan_hash


def _write(path: Path, data: dict[str, Any]) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _source_data(name: str = "fight_s5_A") -> dict[str, Any]:
    return source_of_truth_to_data(golden_source(name))


def test_a_valid_file_is_read(tmp_path: Path) -> None:
    document = golden_source("fight_s5_A")
    path = tmp_path / "source.json"
    path.write_text(dump_source_of_truth(document, indent=2), encoding="utf-8")

    assert read_source(path) == document


def test_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(PlanFailure) as failure:
        read_source(tmp_path / "absent.json")

    assert failure.value.code == "SOURCE_NOT_FOUND"


@pytest.mark.parametrize("text", ["not json", "{}"])
def test_a_file_that_is_not_a_source_of_truth(tmp_path: Path, text: str) -> None:
    path = tmp_path / "source.json"
    path.write_text(text, encoding="utf-8")

    with pytest.raises(PlanFailure) as failure:
        read_source(path)

    assert failure.value.code == "SOURCE_INVALID"
    assert failure.value.violations


def test_a_hash_that_does_not_match(tmp_path: Path) -> None:
    data = _source_data()
    data["contract_meta"]["contract_hash"] = "1" * 64

    with pytest.raises(PlanFailure) as failure:
        read_source(_write(tmp_path / "source.json", data))

    assert failure.value.code == "CONTRACT_HASH_MISMATCH"


def test_checks_of_k1_that_did_not_pass(tmp_path: Path) -> None:
    data = _source_data()
    data["harvest_report"]["checks"][0].update(
        passed=False,
        violations=[{"check": "completeness", "element_path": "rule.constraints[0]", "detail": "x"}],
    )
    data["contract_meta"]["contract_hash"] = compute_contract_hash(data)

    with pytest.raises(PlanFailure) as failure:
        read_source(_write(tmp_path / "source.json", data))

    assert failure.value.code == "K1_CHECKS_NOT_PASSED"
    assert [(v.check, v.element) for v in failure.value.violations] == [
        ("completeness", "rule.constraints[0]")
    ]


def test_a_failure_describes_itself() -> None:
    with pytest.raises(PlanFailure) as failure:
        read_source(Path("/nonexistent/source.json"))

    data = failure.value.to_data()

    assert data["stage"] == "input"
    assert data["code"] == "SOURCE_NOT_FOUND"
    assert canonical_json(data)
