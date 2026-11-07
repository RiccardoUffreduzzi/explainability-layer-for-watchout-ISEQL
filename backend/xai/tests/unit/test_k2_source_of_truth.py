"""The source of truth: the K1 draft kept as it is, plus what K2 adds."""

import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from xai.contract import ContractDraft, draft_to_data
from xai.contract.source_of_truth import (
    LimitCode,
    SourceOfTruth,
    compute_contract_hash,
    dump_source_of_truth,
    load_source_of_truth,
    source_of_truth_to_data,
    verify_contract_hash,
)
from xai.contract.source_of_truth_schema import SCHEMA_PATH, schema_text, source_of_truth_schema
from xai.k2.limit_catalogue import SENTENCES
from xai.k2.source_of_truth import build_source_of_truth
from xai.k2.stage import K2Stage, k2_path
from xai.tests.support import EXAMPLES_DIR, from_json_data, load_example

EXAMPLES = sorted(Path(EXAMPLES_DIR).glob("*.bozza.json"))


def _draft(path: Path) -> ContractDraft:
    return from_json_data(ContractDraft, load_example(path))


def _without_k2_fields(data: dict[str, Any]) -> dict[str, Any]:
    data = json.loads(json.dumps(data))
    data.pop("knowledge_limits")
    data["event"].pop("reinforcement", None)
    data["contract_meta"].pop("source_of_truth_version")
    data["contract_meta"].pop("contract_hash")
    return data


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_it_only_adds_to_the_draft(path: Path) -> None:
    draft = _draft(path)

    document = build_source_of_truth(draft)

    assert _without_k2_fields(source_of_truth_to_data(document)) == draft_to_data(draft)


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_the_hash_matches_the_content(path: Path) -> None:
    assert verify_contract_hash(build_source_of_truth(_draft(path)))


def test_a_change_breaks_the_hash() -> None:
    document = build_source_of_truth(_draft(EXAMPLES[0]))
    data = source_of_truth_to_data(document)
    data["knowledge_limits"] = data["knowledge_limits"][:-1]

    tampered = load_source_of_truth(json.dumps(data))

    assert not verify_contract_hash(tampered)
    assert compute_contract_hash(data) != document.contract_meta.contract_hash


def test_two_runs_give_the_same_text() -> None:
    draft = _draft(EXAMPLES[0])

    first = dump_source_of_truth(build_source_of_truth(draft))
    second = dump_source_of_truth(build_source_of_truth(draft))
    assert first == second


def test_it_survives_a_round_trip() -> None:
    document = build_source_of_truth(_draft(EXAMPLES[0]))

    assert load_source_of_truth(dump_source_of_truth(document, indent=2)) == document


def test_every_limit_of_the_catalogue_has_a_sentence() -> None:
    assert set(SENTENCES) == set(LimitCode)


def test_the_k1_models_still_reject_the_k2_fields() -> None:
    data = source_of_truth_to_data(build_source_of_truth(_draft(EXAMPLES[0])))

    with pytest.raises(ValueError):
        from_json_data(ContractDraft, data)


def test_the_schema_file_is_up_to_date() -> None:
    assert SCHEMA_PATH.read_text(encoding="utf-8") == schema_text()


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_the_document_agrees_with_the_schema(path: Path) -> None:
    document = build_source_of_truth(_draft(path))

    jsonschema.validate(source_of_truth_to_data(document), source_of_truth_schema())


def test_the_stage_writes_in_its_own_folder_and_leaves_k1_alone(tmp_path: Path) -> None:
    draft_path = tmp_path / "an_1" / "vehicle_collision" / "ev_0123456789ab.json"
    draft_path.parent.mkdir(parents=True)
    draft_path.write_bytes(EXAMPLES[0].read_bytes())
    before = draft_path.read_bytes()

    K2Stage().process(_draft(EXAMPLES[0]), draft_path)

    written = k2_path(draft_path)
    assert written == tmp_path / "an_1" / "k2" / "vehicle_collision" / "ev_0123456789ab.json"
    assert isinstance(load_source_of_truth(written.read_text(encoding="utf-8")), SourceOfTruth)
    assert draft_path.read_bytes() == before
    assert sorted(p.name for p in draft_path.parent.parent.glob("*/*.json")) == ["ev_0123456789ab.json"]
    assert not list(written.parent.glob("*.tmp"))
