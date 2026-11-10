"""Which interval of the contract each variable of a branch stands for .

The resolver narrows the candidates of each selection with two criteria, one after
the other, and says which ones it applied (``basis``):

1. predicate and classes: intervals of the node's modality whose predicate
   is in a branch of the selection and, for visual nodes, whose argument classes that branch
   admits;
2. projected values: the values the engine wrote in the row for this variable,
   the projected arguments ``Mk.argN`` (``event.arguments``) and, when the branch
   projection has a single ``.st`` or ``.et`` field of this variable, the frame of the row's
   start or end (``event.interval``).
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import permutations

from xai.contract.model import IntervalRecord, SelectionBranch, SelectionNode
from xai.contract.plan import Binding, BindingStatus
from xai.k4_planner.view import SourceOfTruthView

INTERVAL_SOURCE = {"visual": "VisualPerInterval", "audio": "AudioPerInterval"}
"""The table of the intervals of a selection, by the modality of its node."""

BASIS_PREDICATE = "predicate"
BASIS_ARG_CLASSES = "arg_classes"

_ROLE = re.compile(r"^(?P<variable>[A-Za-z][A-Za-z0-9_]*)\.arg(?P<position>[1-9][0-9]*)$")
_START, _END = "st", "et"


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
    endpoints = _endpoint_variables(view, branch)
    return tuple(
        _resolve(view, branch, node, endpoints)
        for node in view.nodes_of(branch)
        if isinstance(node, SelectionNode)
    )


def by_predicate_and_classes(view: SourceOfTruthView, node: SelectionNode) -> tuple[str, ...]:
    """the candidates of the guidelines, in contract order"""
    source = INTERVAL_SOURCE[node.modality]
    with_classes = node.modality == "visual"
    return tuple(
        interval.interval_id
        for interval in view.intervals
        if interval.source == source
        and any(_admits(view, option, interval, with_classes) for option in node.payload.branches)
    )


def projected_roles(view: SourceOfTruthView, variable: str) -> tuple[tuple[str, int, str], ...]:
    """``(role, position, entity_id)`` of each projected argument of a variable, in row order"""
    found = []
    for argument in view.event.arguments:
        match = _ROLE.fullmatch(argument.role)
        if match and match["variable"] == variable:
            found.append((argument.role, int(match["position"]), argument.entity_id))
    return tuple(found)


def _resolve(
    view: SourceOfTruthView, branch: str, node: SelectionNode, endpoints: dict[str, str]
) -> VariableBinding:
    variable = node.variables[0]
    candidates = [view.interval(i) for i in by_predicate_and_classes(view, node)]
    basis = [BASIS_PREDICATE] + ([BASIS_ARG_CLASSES] if node.modality == "visual" else [])

    for role, position, entity_id in projected_roles(view, variable):
        candidates = [c for c in candidates if _has_argument(c, position, entity_id)]
        basis.append(role)

    row = view.event.interval
    for end, row_frame in ((_START, row.start_frame), (_END, row.end_frame)):
        if endpoints.get(end) == variable and row_frame is not None:
            candidates = [c for c in candidates if _frame(c, end) == row_frame]
            basis.append(f"{variable}.{end}")

    return VariableBinding(
        branch=branch,
        variable=variable,
        selection=node.constraint_id,
        status=_status(len(candidates)),
        candidates=tuple(c.interval_id for c in candidates),
        basis=tuple(basis),
    )


def _admits(
    view: SourceOfTruthView, option: SelectionBranch, interval: IntervalRecord, with_classes: bool
) -> bool:
    """Whether one branch of the selection admits the interval: its predicate and, if asked, its classes"""
    if interval.predicate not in option.predicates:
        return False
    if not with_classes:
        return True
    admitted = [option.arg_classes[slot] for slot in sorted(option.arg_classes, key=int)]
    if len(interval.args) != len(admitted):
        return False
    classes = [view.entity(entity_id).class_ for entity_id in interval.args]
    orders: Iterable[tuple[str, ...]] = (tuple(classes),) if interval.args_ordered else permutations(classes)
    return any(all(c in allowed for c, allowed in zip(order, admitted, strict=True)) for order in orders)


def _has_argument(interval: IntervalRecord, position: int, entity_id: str) -> bool:
    if interval.args_ordered:
        return len(interval.args) >= position and interval.args[position - 1] == entity_id
    return entity_id in interval.args


def _endpoint_variables(view: SourceOfTruthView, branch: str) -> dict[str, str]:
    """``st``/``et`` -> the variable of the branch projection's single field of that kind.

    With no such field or more than one the criterion is not used.
    """
    found: dict[str, str] = {}
    for end in (_START, _END):
        fields = [f for f in view.projection_of(branch).payload.fields if f.endswith("." + end)]
        if len(fields) == 1:
            found[end] = fields[0].rsplit(".", 1)[0]
    return found


def _frame(interval: IntervalRecord, end: str) -> int | None:
    return interval.anchor.start_frame if end == _START else interval.anchor.end_frame


def _status(count: int) -> BindingStatus:
    if count == 1:
        return BindingStatus.ATTRIBUTED
    return BindingStatus.AMBIGUOUS if count > 1 else BindingStatus.NOT_FOUND
