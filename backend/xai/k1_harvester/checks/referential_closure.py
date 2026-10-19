"""Referential closure: every reference in the draft resolves to an object of the draft.

Rule nodes form one tree (one root, parents that exist and contain them), node
variables belong to their branch, entities and intervals are unique and resolve,
and every term of the draft has a glossary entry.
"""

from collections import Counter
from collections.abc import Iterable

from xai.contract.ids import projection_id
from xai.contract.model import (
    ContractDraft,
    ProjectionNode,
    SelectionNode,
    SetOperationNode,
    TemporalOperatorNode,
    Violation,
)
from xai.contract.reasons import CheckName


def check_referential_closure(draft: ContractDraft) -> list[Violation]:
    found: list[Violation] = []

    def fail(path: str, detail: str) -> None:
        found.append(Violation(check=CheckName.REFERENTIAL_CLOSURE, element_path=path, detail=detail))

    nodes = draft.rule.constraints
    by_id = {n.constraint_id: n for n in nodes}
    for duplicate in _duplicates(n.constraint_id for n in nodes):
        fail("rule.constraints", f"constraint_id {duplicate} is not unique")
    roots = [n.constraint_id for n in nodes if n.parent is None]
    if len(roots) != 1:
        fail("rule.constraints", f"the rule needs exactly one root node, found {roots}")
    projections = {n.branch: n for n in nodes if isinstance(n, ProjectionNode)}
    for i, node in enumerate(nodes):
        path = f"rule.constraints[{i}]"
        if isinstance(node, SetOperationNode):
            if node.branch is not None:
                fail(f"{path}.branch", "a set operation belongs to no branch")
            for child in node.payload.children:
                target = by_id.get(child)
                if not isinstance(target, ProjectionNode | SetOperationNode):
                    fail(
                        f"{path}.payload.children",
                        f"{child} is not a projection or set operation of the rule",
                    )
                elif target.parent != node.constraint_id:
                    fail(f"{path}.payload.children", f"{child} has parent {target.parent}")
        if node.parent is not None:
            parent = by_id.get(node.parent)
            if parent is None:
                fail(f"{path}.parent", f"{node.parent} is not a node of the rule")
            elif isinstance(node, ProjectionNode | SetOperationNode) and not isinstance(
                parent, SetOperationNode
            ):
                fail(f"{path}.parent", f"{node.parent} is not a set operation")
            elif not isinstance(node, ProjectionNode | SetOperationNode) and node.parent != projection_id(
                node.branch or ""
            ):
                fail(f"{path}.parent", f"{node.parent} is not the projection of branch {node.branch}")
        if not isinstance(node, SetOperationNode):
            projection = projections.get(node.branch)
            if projection is None:
                fail(f"{path}.branch", f"branch {node.branch} has no projection node")
            elif not set(node.variables) <= set(projection.variables):
                fail(f"{path}.variables", f"{node.variables} are not all variables of branch {node.branch}")

    entity_ids = [e.entity_id for e in draft.entities]
    for duplicate in _duplicates(entity_ids):
        fail("entities", f"entity_id {duplicate} is not unique")
    for duplicate in _duplicates(i.interval_id for i in draft.intervals):
        fail("intervals", f"interval_id {duplicate} is not unique")
    for duplicate in _duplicates(g.term_id for g in draft.glossary):
        fail("glossary", f"term_id {duplicate} is not unique")
    for i, argument in enumerate(draft.event.arguments):
        if argument.entity_id not in entity_ids:
            fail(f"event.arguments[{i}].entity_id", f"{argument.entity_id} is not an entity of the draft")
    for i, interval in enumerate(draft.intervals):
        for arg in interval.args:
            if arg not in entity_ids:
                fail(f"intervals[{i}].args", f"{arg} is not an entity of the draft")
    if draft.event.origin_basis is not None:
        for name in draft.event.origin_basis.branch.split(", "):
            if name not in projections:
                fail("event.origin_basis.branch", f"{name} is not a branch of the rule")

    terms = {(g.kind, g.term) for g in draft.glossary}
    predicate_terms = {t for k, t in terms if k in ("predicate", "audio_class")}
    for i, node in enumerate(nodes):
        if isinstance(node, SelectionNode):
            for p in (p for b in node.payload.branches for p in b.predicates):
                if p not in predicate_terms:
                    fail(f"rule.constraints[{i}].payload", f"predicate {p} has no glossary entry")
        elif isinstance(node, TemporalOperatorNode) and ("operator", node.payload.name) not in terms:
            fail(f"rule.constraints[{i}].payload.name", f"operator {node.payload.name} has no glossary entry")
    for i, interval in enumerate(draft.intervals):
        if interval.predicate not in predicate_terms:
            fail(f"intervals[{i}].predicate", f"predicate {interval.predicate} has no glossary entry")
    if ("event_model", draft.event.label) not in terms:
        fail("event.label", f"event {draft.event.label} has no glossary entry")
    return found


def _duplicates(values: Iterable[str]) -> list[str]:
    return sorted(v for v, n in Counter(values).items() if n > 1)
