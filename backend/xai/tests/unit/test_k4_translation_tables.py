"""The closed tables of the translation: a new kind, operator or modality shows up here."""

from typing import get_args

import pytest

from xai.adapters.resource_files import load_glossary
from xai.contract.model import ConstraintNode, IntervalRecord, SelectionNode
from xai.k4_planner.bindings import INTERVAL_SOURCE
from xai.k4_planner.readings import READING_CONDITION
from xai.k4_planner.rules import RULES
from xai.k4_planner.rules.selection import TERM_KIND


def _kinds() -> set[str]:
    nodes = get_args(get_args(ConstraintNode)[0])
    return {kind for node in nodes for kind in get_args(node.model_fields["kind"].annotation)}


def test_every_kind_but_the_set_operation_has_a_rule() -> None:
    assert set(RULES) == _kinds() - {"set_operation"}


def test_a_selection_node_has_a_table_and_a_glossary_kind_for_each_modality() -> None:
    modalities = set(get_args(SelectionNode.model_fields["modality"].annotation)) - {"mixed"}

    assert set(INTERVAL_SOURCE) == set(TERM_KIND) == modalities
    assert set(INTERVAL_SOURCE.values()) == set(get_args(IntervalRecord.model_fields["source"].annotation))


@pytest.mark.parametrize("operator", sorted(load_glossary().operators))
def test_every_reading_of_the_glossary_follows_the_grammar(operator: str) -> None:
    conditions = [r.condition for r in load_glossary().operators[operator].parameter_readings]

    assert conditions
    assert all(READING_CONDITION.fullmatch(c) for c in conditions)
