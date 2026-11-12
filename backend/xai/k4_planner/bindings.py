"""Which interval of the contract each variable of a branch stands for.

K1 copies WatchOut's lineage into the contract: every interval says which variables
of which branches it satisfied (``intervals[*].bindings``). The candidates of a
variable are the intervals bound to it; ``basis`` names that criterion.

Several candidates are several witnesses of the row: each of them produces the same row.
"""

from dataclasses import dataclass

from xai.contract.model import IntervalBinding, SelectionNode
from xai.contract.plan import Binding, BindingStatus
from xai.k4_planner.view import SourceOfTruthView

BASIS_LINEAGE = "engine_lineage"


@dataclass(frozen=True)
class VariableBinding:
    """The outcome for one variable of a branch."""

    branch: str
    variable: str
    """The variable of the selection"""
    selection: str
    """``constraint_id`` of the selection node"""
    status: BindingStatus
    candidates: tuple[str, ...]
    """Interval IDs, in contract order"""
    basis: tuple[str, ...]
    """The criteria applied, in order"""

    @property
    def interval_id(self) -> str | None:
        """The only candidate, when the variable is attributed"""
        return self.candidates[0] if self.status is BindingStatus.ATTRIBUTED else None

    def to_binding(self) -> Binding:
        """The record of ``bindings`` in the plan"""
        return Binding(
            branch=self.branch,
            variable=self.variable,
            status=self.status,
            interval_ids=list(self.candidates),
            basis=list(self.basis),
        )


def resolve_bindings(view: SourceOfTruthView, branch: str) -> tuple[VariableBinding, ...]:
    """One binding per selection of the branch, in rule order"""
    return tuple(
        _resolve(view, branch, node) for node in view.nodes_of(branch) if isinstance(node, SelectionNode)
    )


def _resolve(view: SourceOfTruthView, branch: str, node: SelectionNode) -> VariableBinding:
    variable = node.variables[0]
    bound = IntervalBinding(branch=branch, variable=variable)
    candidates = tuple(i.interval_id for i in view.intervals if bound in i.bindings)
    return VariableBinding(
        branch=branch,
        variable=variable,
        selection=node.constraint_id,
        status=_status(len(candidates)),
        candidates=candidates,
        basis=(BASIS_LINEAGE,),
    )


def _status(count: int) -> BindingStatus:
    if count == 1:
        return BindingStatus.ATTRIBUTED
    return BindingStatus.AMBIGUOUS if count > 1 else BindingStatus.NOT_FOUND
