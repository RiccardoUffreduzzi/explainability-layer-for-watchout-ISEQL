"""Conditions between variables: ``identity``, ``attribute_comparison`` and ``duration``."""

import re

from xai.contract.ids import cross_condition_id, projection_id
from xai.contract.model import (
    AttributeComparisonNode,
    ComparisonPayload,
    ConstraintNode,
    DurationNode,
    DurationPayload,
    IdentityNode,
)
from xai.k1_harvester.ports import BranchCondition
from xai.k1_harvester.rule.scope import RuleScope

IDENTITY_OPERATORS = ("=", "≠", "!=")
"""Equal or different entity: an identity condition."""

_ARGUMENT = re.compile(r"^arg\d+$")


def variables_of(condition: BranchCondition) -> list[str]:
    found: list[str] = []
    for side in (condition.left, condition.right):
        alias = side.split(".", 1)[0]
        if alias not in found:
            found.append(alias)
    return found


def is_identity(condition: BranchCondition) -> bool:
    attributes = (condition.left.split(".", 1)[-1], condition.right.split(".", 1)[-1])
    return condition.op in IDENTITY_OPERATORS and all(_ARGUMENT.match(a) for a in attributes)


class CrossConditionReader:
    def read(self, scope: RuleScope) -> list[ConstraintNode]:
        branch = scope.branch
        if branch is None:
            return []
        nodes: list[ConstraintNode] = []
        for position, condition in enumerate(branch.conditions, start=1):
            nodes.append(self._node(scope, branch.name, position, condition))
        return nodes

    @staticmethod
    def _node(scope: RuleScope, branch: str, position: int, condition: BranchCondition) -> ConstraintNode:
        variables = variables_of(condition)
        constraint_id = cross_condition_id(branch, position)
        modality = scope.modality(scope.intervals_of(variables))
        parent = projection_id(branch)
        source = scope.rule.source(f"/cross_conditions/{condition.index}")
        if condition.duration_value is not None and condition.duration_unit is not None:
            duration = DurationPayload(
                end=condition.left,
                start=condition.right,
                op=condition.op,
                value=condition.duration_value,
                unit=condition.duration_unit,
            )
            return DurationNode(
                constraint_id=constraint_id,
                kind="duration",
                branch=branch,
                modality=modality,
                variables=variables,
                parent=parent,
                payload=duration,
                text=condition.text,
                source_ref=source,
            )
        comparison = ComparisonPayload(left=condition.left, op=condition.op, right=condition.right)
        if is_identity(condition):
            return IdentityNode(
                constraint_id=constraint_id,
                kind="identity",
                branch=branch,
                modality=modality,
                variables=variables,
                parent=parent,
                payload=comparison,
                text=condition.text,
                source_ref=source,
            )
        return AttributeComparisonNode(
            constraint_id=constraint_id,
            kind="attribute_comparison",
            branch=branch,
            modality=modality,
            variables=variables,
            parent=parent,
            payload=comparison,
            text=condition.text,
            source_ref=source,
        )
