"""glossary.yaml has a definition and a phrase for every condition between variables."""

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
