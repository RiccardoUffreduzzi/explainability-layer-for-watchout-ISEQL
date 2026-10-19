"""One reader per ISEQL+ construct (Strategy): a new construct is a new reader.

``RuleHarvester`` asks every reader for the nodes of the rule, then for the nodes of
each branch; the order of ``DEFAULT_READERS`` is the order of the nodes in the draft.
"""

from typing import Protocol

from xai.contract.model import ConstraintNode
from xai.k1_harvester.rule.readers.cross_condition import CrossConditionReader
from xai.k1_harvester.rule.readers.operator import OperatorReader
from xai.k1_harvester.rule.readers.projection import ProjectionReader
from xai.k1_harvester.rule.readers.selection import SelectionReader
from xai.k1_harvester.rule.readers.set_operation import SetOperationReader
from xai.k1_harvester.rule.scope import RuleScope


class NodeReader(Protocol):
    def read(self, scope: RuleScope) -> list[ConstraintNode]:
        """The nodes of this construct in the scope; empty when the scope has none."""
        ...


DEFAULT_READERS: tuple[NodeReader, ...] = (
    SetOperationReader(),
    ProjectionReader(),
    CrossConditionReader(),
    OperatorReader(),
    SelectionReader(),
)
"""Set operations first, then for each branch: projection, cross-conditions, operators, selections."""

__all__ = ["DEFAULT_READERS", "NodeReader"]
