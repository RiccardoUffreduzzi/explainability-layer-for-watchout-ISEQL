"""The readings of the thresholds of a temporal operator (K4-A13)."""

from collections.abc import Callable
from typing import Any

from xai.contract.model import TemporalOperatorNode
from xai.k4_planner.readings import ReadingChoice, choose_readings
from xai.tests.k4_support import node_data, view_of


def _choice(
    name: str, constraint_id: str, change: Callable[[dict[str, Any]], None] | None = None
) -> ReadingChoice:
    view = view_of(name, change)
    node = view.node(constraint_id)
    assert isinstance(node, TemporalOperatorNode)
    return choose_readings(view, node)


def _param(data: dict[str, Any], name: str) -> dict[str, Any]:
    param: dict[str, Any] = next(
        p for p in node_data(data, "c_s1_op1")["payload"]["params"] if p["name"] == name
    )
    return param


def test_an_unlimited_threshold() -> None:
    choice = _choice("handoff_s21_A", "c_s1_op1")

    assert [r.model_dump(mode="json") for r in choice.readings] == [
        {"param": "δ", "condition": "δ = ∞", "phrase": "at any time after"}
    ]
    assert choice.unmatched == ()
    assert choice.notes == ()


def test_the_phrase_is_copied_with_its_placeholder() -> None:
    choice = _choice("vehicle_collision_s15_C_audio", "c_s1_op1")

    assert choice.readings[0].phrase == "at any time while {r} is ongoing"


def test_a_finite_threshold_points_at_the_value_of_the_engine() -> None:
    def two_seconds(data: dict[str, Any]) -> None:
        _param(data, "δ").update(value=2, engine_value=2)

    reading = _choice("handoff_s21_A", "c_s1_op1", two_seconds).readings[0]

    assert reading.condition == "δ = d"
    assert reading.phrase == "within d seconds"
    assert reading.value_ref == "#/rule/constraints/3/payload/params/0/engine_value"


def test_rho_not_zero_is_noted() -> None:
    def rho(data: dict[str, Any]) -> None:
        _param(data, "ρ").update(value=2, engine_value=2)

    notes = _choice("handoff_s21_A", "c_s1_op1", rho).notes

    assert [(n.code.value, n.detail) for n in notes] == [("rho_not_zero", "c_s1_op1: ρ = 2")]


def test_a_reading_missing_from_the_glossary_is_reported() -> None:
    def without_finite_reading(data: dict[str, Any]) -> None:
        _param(data, "δ").update(value=2, engine_value=2)
        entry = next(g for g in data["glossary"] if g["term_id"] == "g_operator_Bef")
        entry["parameter_readings"] = [r for r in entry["parameter_readings"] if r["condition"] != "δ = d"]

    choice = _choice("handoff_s21_A", "c_s1_op1", without_finite_reading)

    assert choice.readings == ()
    assert [(u.constraint_id, u.param) for u in choice.unmatched] == [("c_s1_op1", "δ")]
