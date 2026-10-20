"""The JSON schema and the model accept the same drafts.

Each case changes one thing in an example draft and validates the result twice: with
the schema, as a consumer that is not K1 would (K2, a tool in another language), and
with the model reading the JSON text. The two must agree, except for the cases in
``KNOWN_GAPS``: rules JSON Schema cannot express, where only the model rejects.
"""

import copy
from collections.abc import Callable, Iterator
from typing import Any

import jsonschema
import pytest
from pydantic import ValidationError

from xai.contract import json_schema, load_draft
from xai.contract.canonical import canonical_json

Draft = dict[str, Any]


def _params(draft: Draft) -> Iterator[dict[str, Any]]:
    for node in draft["rule"]["constraints"]:
        if node["kind"] == "temporal_operator":
            yield from node["payload"]["params"]


def _threshold(draft: Draft) -> dict[str, Any]:
    return next(p for p in _params(draft) if "unit" in p)


def _strictness(draft: Draft) -> dict[str, Any]:
    return next(p for p in _params(draft) if p["name"] in ("ζ", "η"))


def _check(draft: Draft) -> dict[str, Any]:
    check: dict[str, Any] = draft["harvest_report"]["checks"][0]
    return check


def _violation(draft: Draft) -> dict[str, str]:
    return {
        "check": _check(draft)["name"],
        "element_path": "intervals[0].confidence",
        "detail": "null without a reason",
    }


def _anchor(draft: Draft) -> dict[str, Any]:
    anchor: dict[str, Any] = draft["event"]["interval"]
    return anchor


def _row_match(draft: Draft) -> dict[str, Any]:
    row_match: dict[str, Any] = draft["harvest_report"]["row_match"]
    return row_match


def _node(draft: Draft, kind: str) -> dict[str, Any]:
    return next(n for n in draft["rule"]["constraints"] if n["kind"] == kind)


def _snapshot(draft: Draft) -> dict[str, Any]:
    snapshot: dict[str, Any] = draft["contract_meta"]["source_snapshot"]
    return snapshot


Mutation = Callable[[Draft], None]

# name -> (change, whether the result is a valid draft)
CASES: dict[str, tuple[Mutation, bool]] = {
    "unchanged": (lambda d: None, True),
    # Anchor: the pair named by read_as is required, the other may be null.
    "anchor read as frames without start_frame": (
        lambda d: _anchor(d).update(read_as="frames", start_frame=None),
        False,
    ),
    "anchor read as seconds without end_s": (lambda d: _anchor(d).update(end_s=None), False),
    "anchor converted pair null": (lambda d: _anchor(d).update(start_frame=None, end_frame=None), True),
    # CheckResult: passed exactly when there are no violations.
    "check passed with a violation": (lambda d: _check(d).update(violations=[_violation(d)]), False),
    "check failed without violations": (lambda d: _check(d).update(passed=False), False),
    "check failed with a violation": (
        lambda d: _check(d).update(passed=False, violations=[_violation(d)]),
        True,
    ),
    # RowMatch: a draft answers one row that was found.
    "no row matched": (lambda d: _row_match(d).update(matches=0), False),
    "no row returned": (lambda d: _row_match(d).update(rows_returned=0), False),
    # Strict types: no number or boolean written as text.
    "fps written as text": (
        lambda d: d["contract_meta"]["pipeline_config"]["sampling"].update(source_fps="24"),
        False,
    ),
    "flag written as text": (lambda d: d["intervals"][0].update(args_ordered="true"), False),
    "float field written as an integer": (lambda d: _anchor(d).update(start_s=1), True),
    # Optional fields are left out, never null.
    "optional map written as null": (
        lambda d: d["contract_meta"]["pipeline_config"].update(sources=None),
        False,
    ),
    # Version identity.
    "another contract version": (lambda d: d["contract_meta"].update(contract_version="0.2.0"), False),
    # Timestamps: RFC 3339 text with an offset.
    "timestamp without offset": (lambda d: _snapshot(d).update(extracted_at="2026-10-06T20:00:00"), False),
    "timestamp with an offset": (
        lambda d: _snapshot(d).update(extracted_at="2026-10-06T22:00:00+02:00"),
        True,
    ),
    "timestamp as a number": (lambda d: _snapshot(d).update(extracted_at=1791000000), False),
    # Closed catalogs, IDs and shapes.
    "reason outside the catalog": (
        lambda d: d["unavailable"]["actions"].update(reason="not_implemented_yet"),
        False,
    ),
    "constraint ID without prefix": (
        lambda d: d["rule"]["constraints"][0].update(constraint_id="x_1"),
        False,
    ),
    "empty key in an unavailable map": (
        lambda d: d["unavailable"].update({"": {"reason": "fps_not_recorded", "detail": "x"}}),
        False,
    ),
    "payload of another kind": (lambda d: _node(d, "projection").update(kind="selection"), False),
    "unknown key": (lambda d: d["rule"].update(unknown=1), False),
    "K2 field": (lambda d: d["contract_meta"].update(contract_hash="abc"), False),
    "required nullable field left out": (lambda d: d["intervals"][0].pop("confidence"), False),
}

# Cases on the parameters of a temporal operator: run on the examples that have one.
OPERATOR_CASES: dict[str, tuple[Mutation, bool]] = {
    # OperatorParam: ζ and η are strictness operators and have no unit.
    "strictness parameter with a unit": (lambda d: _strictness(d).update(unit="seconds"), False),
    "threshold parameter without a unit": (lambda d: _threshold(d).pop("unit"), True),
    # Optional fields are left out, never null.
    "optional unit written as null": (lambda d: _strictness(d).update(unit=None), False),
}

# Rules that compare two fields, or a calendar, are beyond JSON Schema: only the model checks them.
KNOWN_GAPS: dict[str, Mutation] = {
    "more matches than rows": lambda d: _row_match(d).update(rows_returned=1, matches=2),
    "matched index past the rows": lambda d: _row_match(d).update(
        matched_index=_row_match(d)["rows_returned"]
    ),
    "date that does not exist": lambda d: _snapshot(d).update(extracted_at="2026-02-30T20:00:00Z"),
    "integer field written as 24.0": lambda d: _anchor(d).update(start_frame=24.0),
}


@pytest.fixture(scope="module")
def validator() -> jsonschema.Draft202012Validator:
    return jsonschema.Draft202012Validator(json_schema.contract_draft_schema())


def _verdicts(validator: jsonschema.Draft202012Validator, draft: Draft) -> tuple[bool, bool]:
    try:
        load_draft(canonical_json(draft))
        model_ok = True
    except ValidationError:
        model_ok = False
    return validator.is_valid(draft), model_ok


@pytest.mark.parametrize("case", list(CASES))
def test_schema_and_model_agree(
    validator: jsonschema.Draft202012Validator, example: Draft, case: str
) -> None:
    mutate, valid = CASES[case]
    draft = copy.deepcopy(example)
    mutate(draft)

    assert _verdicts(validator, draft) == (valid, valid)


@pytest.mark.parametrize("case", list(OPERATOR_CASES))
def test_schema_and_model_agree_on_operator_params(
    validator: jsonschema.Draft202012Validator, operator_example: Draft, case: str
) -> None:
    mutate, valid = OPERATOR_CASES[case]
    draft = copy.deepcopy(operator_example)
    mutate(draft)

    assert _verdicts(validator, draft) == (valid, valid)


@pytest.mark.parametrize("case", list(KNOWN_GAPS))
def test_known_gaps_are_caught_by_the_model(
    validator: jsonschema.Draft202012Validator, example: Draft, case: str
) -> None:
    draft = copy.deepcopy(example)
    KNOWN_GAPS[case](draft)

    assert _verdicts(validator, draft) == (True, False)
