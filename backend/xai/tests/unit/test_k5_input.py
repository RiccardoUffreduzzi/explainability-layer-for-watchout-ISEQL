"""The input of the LLM: the plan, the values it cites, the glossary phrases; checked as a pair."""

import json
from typing import Any

import pytest

from xai.contract.plan import ExplanationPlan, StepType
from xai.k5_report1.profile import REPORT1
from xai.reporting.failure import ReportFailure
from xai.reporting.llm_input import build_input, read_plan, read_source
from xai.reporting.profile import ReportProfile, SectionSpec
from xai.tests.k5_support import LABELS, NAMES, input_of, pair_of

REPORT2_LIKE = ReportProfile(
    number=2, name="report2", only_in_report2=True, sections=(SectionSpec("Text", tuple(StepType)),)
)


@pytest.mark.parametrize("name", NAMES)
def test_report_1_receives_the_plan_as_k4_wrote_it_without_the_steps_the_system_writes(name: str) -> None:
    report_input = input_of(name)
    by_system = {step.step_id for step in report_input.system_steps}
    plan = report_input.plan.model_dump(mode="json")
    plan["steps"] = [step for step in plan["steps"] if step["step_id"] not in by_system]

    data = report_input.to_data()

    assert data["plan"] == plan
    assert {step.type for step in report_input.system_steps} == {StepType.PROVENANCE, StepType.LIMIT}
    assert {"s_prov_sampling", "s_prov_bindings", "s_lim_temporal_resolution"} <= by_system
    assert not [
        name for name in data["values"] if name.startswith(("pipeline_config.", "s_lim_", "contract_hash"))
    ]
    assert {value.name for value in report_input.table.values} > set(data["values"])


@pytest.mark.parametrize("name", NAMES)
def test_a_report_2_profile_receives_only_the_steps_in_report_2(name: str) -> None:
    plan, document = pair_of(name)

    report_input = build_input(plan, document, REPORT2_LIKE, LABELS)

    steps = report_input.to_data()["plan"]["steps"]
    assert steps and all(s["in_report2"] for s in steps)
    assert not any(
        v.name.endswith(".fixed_text") and v.name.startswith("s_lim_") for v in report_input.table.values
    )


def test_the_glossary_has_the_cited_terms_and_their_alternatives() -> None:
    glossary = input_of("gunshot_or_explosion_s7_A").glossary

    assert set(glossary) == {
        "g_predicate_explosion_visible",
        "g_predicate_gunshot_visible",
        "g_event_model_gunshot_or_explosion",
    }
    assert glossary["g_predicate_gunshot_visible"]["phrase"] == "{arg1} holds or fires a gun"


def test_the_codes_of_the_bindings_are_explained() -> None:
    assert input_of("handoff_s21_A").codes == {
        "engine_lineage": LABELS.codes["engine_lineage"],
        "attributed": LABELS.codes["attributed"],
    }


def test_a_plan_changed_after_its_hash_is_refused() -> None:
    plan, document = pair_of("handoff_s21_A")
    data = plan.model_dump(mode="json")
    data["steps"] = data["steps"][1:]
    changed = ExplanationPlan.model_validate_json(json.dumps(data))

    with pytest.raises(ReportFailure) as caught:
        build_input(changed, document, REPORT1, LABELS)

    assert caught.value.code == "PLAN_HASH_MISMATCH"


def test_a_plan_of_another_source_of_truth_is_refused() -> None:
    plan, _ = pair_of("handoff_s21_A")
    _, other = pair_of("fight_s5_A")

    with pytest.raises(ReportFailure) as caught:
        build_input(plan, other, REPORT1, LABELS)

    assert caught.value.code == "CONTRACT_HASH_MISMATCH"


def test_missing_and_invalid_files_are_refused(tmp_path: Any) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("{}", encoding="utf-8")

    for read, code in ((read_plan, "PLAN"), (read_source, "SOURCE")):
        with pytest.raises(ReportFailure) as missing:
            read(tmp_path / "none.json")
        with pytest.raises(ReportFailure) as invalid:
            read(broken)
        assert (missing.value.code, invalid.value.code) == (f"{code}_NOT_FOUND", f"{code}_INVALID")
