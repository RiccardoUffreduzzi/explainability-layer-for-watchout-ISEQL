"""glossary.yaml: a formula and a phrase for every condition between variables, and no
definition that K1 reads from WatchOut."""

from pathlib import Path

import pytest

from xai.adapters.resource_files import load_glossary
from xai.contract.ids import comparison_term

# The operators of WatchOut's cross-conditions (iseql/parser.py), for each node kind of K1.
GRAMMAR = {
    "identity": ("=", "≠"),
    "attribute_comparison": ("=", "≠", "<", "<=", ">", ">="),
    "duration": ("=", "<", "<=", ">", ">="),
}


@pytest.mark.parametrize("name", sorted({comparison_term(k, op) for k, ops in GRAMMAR.items() for op in ops}))
def test_every_comparison_has_a_definition_and_a_phrase(name: str) -> None:
    entry = load_glossary().comparisons[name]

    assert entry.definition
    assert entry.plain_template


@pytest.mark.parametrize("section", ["predicates", "audio_classes", "events"])
def test_a_definition_that_watchout_has_is_refused(tmp_path: Path, section: str) -> None:
    path = tmp_path / "glossary.yaml"
    path.write_text(
        f"version: 0.2.0\n{section}:\n  term:\n    definition: copied\n    plain_template: a term\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="read from WatchOut"):
        load_glossary(path)
