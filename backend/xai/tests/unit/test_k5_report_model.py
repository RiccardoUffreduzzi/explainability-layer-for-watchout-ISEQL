"""The report file: its JSON schema, generated from the model, and the files of the goldens."""

import copy
import json
from collections.abc import Callable
from typing import Any

import jsonschema
import pytest
from pydantic import ValidationError

from xai.contract.report import REPORT_VERSION, Report, dump_report, load_report
from xai.contract.report_schema import SCHEMA_ID, SCHEMA_PATH, main, report_schema, schema_text
from xai.tests.k5_support import NAMES, REPORT_DIR, read

Data = dict[str, Any]


@pytest.fixture(scope="module")
def validator() -> jsonschema.Draft202012Validator:
    return jsonschema.Draft202012Validator(report_schema())


def _golden(name: str = "handoff_s21_A") -> Data:
    data: Data = json.loads(read(REPORT_DIR / f"{name}.json"))
    return data


def _sentence(report: Data) -> Data:
    sentence: Data = report["sections"][0]["sentences"][0]
    return sentence


@pytest.mark.parametrize("name", NAMES)
def test_every_golden_report_is_valid(validator: jsonschema.Draft202012Validator, name: str) -> None:
    data = _golden(name)
    validator.validate(data)
    assert dump_report(load_report(json.dumps(data))) == read(REPORT_DIR / f"{name}.json")


Mutation = Callable[[Data], None]

CASES: dict[str, tuple[Mutation, bool]] = {
    "unchanged": (lambda r: None, True),
    "unknown key": (lambda r: r["report_meta"].update(unknown=1), False),
    "another report version": (lambda r: r["report_meta"].update(report_version="0.1.0-k5"), False),
    "section without author": (lambda r: r["sections"][0].pop("written_by"), False),
    "section of another author": (lambda r: r["sections"][0].update(written_by="human"), False),
    "report 3": (lambda r: r["report_meta"].update(report=3), False),
    "verification run": (lambda r: r["report_meta"].update(verification="passed"), False),
    "no attempt": (lambda r: r["report_meta"].update(attempts=0), False),
    "plan hash too short": (lambda r: r["report_meta"].update(plan_hash="0" * 12), False),
    "sentence without steps": (lambda r: _sentence(r).update(step_ids=[]), False),
    "section without sentences": (lambda r: r["sections"][0].update(sentences=[]), False),
    "report without sections": (lambda r: r.update(sections=[]), False),
    "value form outside the catalogue": (
        lambda r: _sentence(r).update(
            values=[{"name": "x", "ref": "#/event/start", "text": "0:02", "form": "bold"}]
        ),
        False,
    ),
    "entity without ID prefix": (
        lambda r: _sentence(r).update(entities=[{"entity_id": "3", "text": "person 1"}]),
        False,
    ),
}


@pytest.mark.parametrize("case", list(CASES))
def test_schema_and_model_agree(validator: jsonschema.Draft202012Validator, case: str) -> None:
    mutate, valid = CASES[case]
    report = copy.deepcopy(_golden())
    mutate(report)
    try:
        load_report(json.dumps(report))
        model_ok = True
    except ValidationError:
        model_ok = False

    assert (validator.is_valid(report), model_ok) == (valid, valid)


def test_the_schema_is_bound_to_the_version() -> None:
    assert report_schema()["$id"] == SCHEMA_ID == f"urn:watchout-xai:report:{REPORT_VERSION}"


def test_the_schema_file_is_up_to_date() -> None:
    assert SCHEMA_PATH.read_text(encoding="utf-8") == schema_text()
    assert main(["--check"]) == 0


def test_the_model_is_the_one_the_schema_describes() -> None:
    assert report_schema()["title"] == Report.__name__
