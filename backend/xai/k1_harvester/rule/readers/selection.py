"""``selection`` nodes: σ of one interval, with its alternatives."""

from xai.contract.ids import projection_id, selection_id
from xai.contract.model import ConstraintNode, SelectionBranch, SelectionNode, SelectionPayload
from xai.k1_harvester.rule.scope import RuleScope


class SelectionReader:
    def read(self, scope: RuleScope) -> list[ConstraintNode]:
        branch = scope.branch
        if branch is None:
            return []
        nodes: list[ConstraintNode] = []
        for position, interval in enumerate(branch.intervals, start=1):
            nodes.append(
                SelectionNode(
                    constraint_id=selection_id(branch.name, position),
                    kind="selection",
                    branch=branch.name,
                    modality=scope.modality([interval]),
                    variables=[interval.alias],
                    parent=projection_id(branch.name),
                    payload=SelectionPayload(
                        branches=[
                            SelectionBranch(
                                predicates=list(alternative.predicates),
                                arg_classes={slot: list(c) for slot, c in alternative.arg_classes.items()},
                            )
                            for alternative in interval.selection
                        ]
                    ),
                    text=interval.text,
                    source_ref=scope.rule.source(f"/intervals/{interval.index}"),
                )
            )
        return nodes
