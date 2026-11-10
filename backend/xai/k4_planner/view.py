"""The source of truth indexed by ID: the only module of K4 that knows K2's format (K4-A10).

The view decides nothing. It builds its indices once (``SourceOfTruthView.of``), so every
lookup is a dictionary access, and it exposes the reinforcement and the limits as K2
writes them. If the format of K2 changes, this is the module that changes.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field

from xai.contract.model import (
    Argument,
    ConstraintNode,
    Entity,
    GlossaryEntry,
    IntervalRecord,
    ProjectionNode,
)
from xai.contract.source_of_truth import (
    EventRecordK2,
    KnowledgeLimit,
    Reinforcement,
    SourceOfTruth,
)

ORIGIN_BRANCH_SEPARATOR = ", "
"""How K1 joins the branch names of ``event.origin_basis.branch`` (DIP-9)."""


@dataclass(frozen=True)
class SourceOfTruthView:
    """Read-only access by ID to one source of truth."""

    document: SourceOfTruth
    nodes: tuple[ConstraintNode, ...]
    """The rule nodes, in rule order (``rule.constraints``)."""
    intervals: tuple[IntervalRecord, ...]
    """The intervals, in contract order."""
    _node_index: Mapping[str, int] = field(repr=False)
    _branch_nodes: Mapping[str, tuple[ConstraintNode, ...]] = field(repr=False)
    _intervals: Mapping[str, IntervalRecord] = field(repr=False)
    _entities: Mapping[str, Entity] = field(repr=False)
    _terms: Mapping[str, GlossaryEntry] = field(repr=False)
    _arguments: Mapping[str, Argument] = field(repr=False)

    @classmethod
    def of(cls, document: SourceOfTruth) -> "SourceOfTruthView":
        nodes = tuple(document.rule.constraints)
        branch_nodes: dict[str, list[ConstraintNode]] = {}
        for node in nodes:
            if node.branch is not None:
                branch_nodes.setdefault(node.branch, []).append(node)
        return cls(
            document=document,
            nodes=nodes,
            intervals=tuple(document.intervals),
            _node_index={node.constraint_id: i for i, node in enumerate(nodes)},
            _branch_nodes={branch: tuple(members) for branch, members in branch_nodes.items()},
            _intervals={record.interval_id: record for record in document.intervals},
            _entities={entity.entity_id: entity for entity in document.entities},
            _terms={entry.term_id: entry for entry in document.glossary},
            _arguments={argument.role: argument for argument in document.event.arguments},
        )

    # ------------------------------------------------------------------ rule

    def node(self, constraint_id: str) -> ConstraintNode:
        return self.nodes[self._node_index[constraint_id]]

    def node_index(self, constraint_id: str) -> int:
        """Position of the node in ``rule.constraints``, for JSON pointers."""
        return self._node_index[constraint_id]

    def branches(self) -> tuple[str, ...]:
        """The branches of the rule, in rule order; set operations belong to none."""
        return tuple(self._branch_nodes)

    def nodes_of(self, branch: str) -> tuple[ConstraintNode, ...]:
        """The nodes of a branch, in rule order."""
        return self._branch_nodes[branch]

    def projection_of(self, branch: str) -> ProjectionNode:
        return next(node for node in self._branch_nodes[branch] if isinstance(node, ProjectionNode))

    # ------------------------------------------------------------------ evidence and glossary

    def interval(self, interval_id: str) -> IntervalRecord:
        return self._intervals[interval_id]

    def entity(self, entity_id: str) -> Entity:
        return self._entities[entity_id]

    def term(self, term_id: str) -> GlossaryEntry:
        return self._terms[term_id]

    # ------------------------------------------------------------------ event

    @property
    def event(self) -> EventRecordK2:
        return self.document.event

    def argument(self, role: str) -> Argument | None:
        """The projected argument of a role of the row, e.g. ``M1.arg1``; None if not projected."""
        return self._arguments.get(role)

    def origin_branches(self) -> tuple[str, ...]:
        """The branches named by ``event.origin_basis.branch`` (C rows only), in K1's order."""
        basis = self.document.event.origin_basis
        if basis is None:
            return ()
        return tuple(basis.branch.split(ORIGIN_BRANCH_SEPARATOR))

    def reinforcement(self) -> Reinforcement | None:
        """Status and sentence of the modality check, as K2 writes them."""
        return self.document.event.reinforcement

    def limits(self) -> tuple[KnowledgeLimit, ...]:
        """The knowledge limits in K2's order, with their ``refs``."""
        return tuple(self.document.knowledge_limits)

    # ------------------------------------------------------------------ JSON pointers

    def pointer(self, constraint_id: str, *path: str | int) -> str:
        """JSON pointer to a part of a rule node, e.g. its threshold.

        ``pointer("c_s1_op1", "payload", "params", 0, "engine_value")`` is
        ``#/rule/constraints/3/payload/params/0/engine_value`` when the node is the fourth one.
        """
        parts = ("rule", "constraints", self.node_index(constraint_id), *path)
        return "#" + "".join("/" + _escape(str(part)) for part in parts)

    def source_pointer(self, *path: str | int) -> str:
        """JSON pointer to a part of the source of truth outside the rule nodes.

        ``source_pointer("knowledge_limits", 2)`` is ``#/knowledge_limits/2``. It is how the plan
        points at ``contract_meta``, ``event`` or ``knowledge_limits``, so that no other module
        writes a pointer by hand.
        """
        return "#" + "".join("/" + _escape(str(part)) for part in path)


def _escape(token: str) -> str:
    """A reference token of a JSON pointer (RFC 6901)."""
    return token.replace("~", "~0").replace("/", "~1")
