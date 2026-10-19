"""What a ``NodeReader`` reads: the located rule and, for branch nodes, one branch."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from xai.k1_harvester.context import HarvestContext
from xai.k1_harvester.ports import Branch, BranchInterval, RuleLayout, RuleSnapshot
from xai.k1_harvester.predicates import NodeModality, interval_predicates, modality_of


@dataclass(frozen=True)
class RuleScope:
    """The rule (``branch`` None) or one of its branches."""

    ctx: HarvestContext
    branch: Branch | None
    projection_parents: Mapping[str, str]
    """Branch name -> ID of the set operation that combines it (none for a single branch)."""

    @property
    def rule(self) -> RuleSnapshot:
        return self.ctx.rule

    @property
    def layout(self) -> RuleLayout:
        return self.ctx.layout

    def intervals_of(self, variables: Sequence[str]) -> list[BranchInterval]:
        """The intervals of the branch bound to these variables."""
        assert self.branch is not None
        return [bi for bi in self.branch.intervals if bi.alias in variables]

    def modality(self, intervals: Sequence[BranchInterval]) -> NodeModality:
        predicates = [p for bi in intervals for p in interval_predicates(bi)]
        return modality_of(predicates, self.ctx.vocabulary)
