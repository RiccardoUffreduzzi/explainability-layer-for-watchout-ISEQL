"""Which branches of the rule a plan explains, and which nodes it leaves out (UC-K4-03, K4-A8).

A rule of condition A or B has one branch, and that is the one explained. A rule of
condition C has a branch per modality joined by a set operation: the plan explains the
branches K1 names in ``event.origin_basis`` (the ones that produced this row), in rule
order. The other branches' nodes, and the set operation itself, have no step.
"""

from dataclasses import dataclass

from xai.contract.plan import ExcludedConstruct, ExclusionReason
from xai.k4_planner.view import SourceOfTruthView


@dataclass(frozen=True)
class BranchChoice:
    explained: tuple[str, ...]
    """The branches to explain, in rule order."""
    excluded: tuple[ExcludedConstruct, ...]
    """The nodes without a step, in rule order, with the reason."""


def choose_branches(view: SourceOfTruthView) -> BranchChoice:
    branches = view.branches()
    explained: tuple[str, ...]
    if len(branches) == 1:
        explained = branches
    else:
        named = set(view.origin_branches())
        explained = tuple(branch for branch in branches if branch in named)
    excluded = []
    for node in view.nodes:
        if node.branch is None:
            excluded.append(
                ExcludedConstruct(constraint_id=node.constraint_id, reason=ExclusionReason.SET_OPERATION)
            )
        elif node.branch not in explained:
            excluded.append(
                ExcludedConstruct(constraint_id=node.constraint_id, reason=ExclusionReason.OTHER_BRANCH)
            )
    return BranchChoice(explained=explained, excluded=tuple(excluded))
