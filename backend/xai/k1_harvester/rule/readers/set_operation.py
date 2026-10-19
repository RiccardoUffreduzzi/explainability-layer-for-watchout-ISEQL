"""``set_operation`` nodes: the union, intersection or difference of branches."""

from dataclasses import dataclass

from xai.contract.ids import projection_id, set_operation_id
from xai.contract.model import ConstraintNode, SetOperationNode, SetOperationPayload
from xai.contract.reasons import InputError
from xai.k1_harvester.ports import RuleLayout, SetOperationLayout
from xai.k1_harvester.predicates import branch_modality
from xai.k1_harvester.result import HarvestFailure
from xai.k1_harvester.rule.scope import RuleScope

SET_OPERATORS = ("∪", "∩", "\\")


@dataclass(frozen=True)
class NumberedSetOperation:
    node: SetOperationLayout
    constraint_id: str
    parent: str | None
    children: tuple[str, ...]
    """IDs of the children: nested set operations or branch projections."""
    branches: tuple[str, ...]
    """Names of every branch under this operation."""


def numbered_set_operations(layout: RuleLayout) -> list[NumberedSetOperation]:
    """The set operations of the rule in pre-order, numbered from 1 (``c_set<n>``)."""
    found: list[NumberedSetOperation] = []

    def visit(node: SetOperationLayout, parent: str | None) -> tuple[str, tuple[str, ...]]:
        own = set_operation_id(len(found) + 1)
        slot = len(found)
        found.append(NumberedSetOperation(node, own, parent, (), ()))
        children: list[str] = []
        branches: list[str] = []
        for child in node.children:
            if isinstance(child, SetOperationLayout):
                child_id, child_branches = visit(child, own)
                children.append(child_id)
                branches.extend(child_branches)
            else:
                children.append(projection_id(child))
                branches.append(child)
        found[slot] = NumberedSetOperation(node, own, parent, tuple(children), tuple(branches))
        return own, tuple(branches)

    if layout.set_operation is not None:
        visit(layout.set_operation, None)
    return found


def projection_parents(layout: RuleLayout) -> dict[str, str]:
    """Branch name -> ID of the set operation that directly combines it."""
    parents: dict[str, str] = {}
    for numbered in numbered_set_operations(layout):
        for child in numbered.node.children:
            if isinstance(child, str):
                parents[child] = numbered.constraint_id
    return parents


class SetOperationReader:
    def read(self, scope: RuleScope) -> list[ConstraintNode]:
        if scope.branch is not None:
            return []
        branches = {b.name: b for b in scope.layout.branches}
        nodes: list[ConstraintNode] = []
        for numbered in numbered_set_operations(scope.layout):
            op = numbered.node.op
            if op not in SET_OPERATORS:
                raise HarvestFailure.input(
                    InputError.UNSUPPORTED_CONSTRUCT, f"{scope.rule.ref}: set operator {op!r}"
                )
            modalities = {branch_modality(branches[name], scope.ctx.vocabulary) for name in numbered.branches}
            nodes.append(
                SetOperationNode(
                    constraint_id=numbered.constraint_id,
                    kind="set_operation",
                    branch=None,
                    modality=modalities.pop() if len(modalities) == 1 else "mixed",
                    variables=[],
                    parent=numbered.parent,
                    payload=SetOperationPayload(op=op, children=list(numbered.children)),  # type: ignore[arg-type]
                    text=op,
                    source_ref=scope.rule.source(numbered.node.pointer),
                )
            )
        return nodes
