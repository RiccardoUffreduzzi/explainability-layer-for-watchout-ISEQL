"""``projection`` nodes: π of a branch, the fields the row shows."""

from xai.contract.ids import projection_id
from xai.contract.model import ConstraintNode, ProjectionNode, ProjectionPayload
from xai.k1_harvester.rule.scope import RuleScope


class ProjectionReader:
    def read(self, scope: RuleScope) -> list[ConstraintNode]:
        branch = scope.branch
        if branch is None:
            return []
        return [
            ProjectionNode(
                constraint_id=projection_id(branch.name),
                kind="projection",
                branch=branch.name,
                modality=scope.modality(branch.intervals),
                variables=[bi.alias for bi in branch.intervals],
                parent=scope.projection_parents.get(branch.name),
                payload=ProjectionPayload(fields=list(branch.projection)),
                text=branch.projection_text,
                source_ref=scope.rule.source(branch.projection_pointer),
            )
        ]
