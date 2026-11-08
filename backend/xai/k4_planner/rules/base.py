"""What every translation rule receives and returns, and the pieces they share.

A rule turns one rule node into one step. It reads facts only through the view and the
bindings, writes IDs and pointers only (no text), and copies names of events, predicates
and classes into IDs without ever using them to decide (NFR-K4-03).
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Protocol, TypeVar

from xai.contract.model import ConstraintNode
from xai.contract.plan import PlanNote, PlanStep, TOrderBasis, UnmatchedReading
from xai.k4_planner.bindings import VariableBinding
from xai.k4_planner.view import SourceOfTruthView

NodeT = TypeVar("NodeT")


@dataclass(frozen=True)
class RuleContext:
    view: SourceOfTruthView
    branch: str
    bindings: Mapping[str, VariableBinding]
    """Variable -> its binding."""
    observation_of: Mapping[str, str]
    """Variable -> ``step_id`` of its observation."""
    t_orders: Mapping[str, float | None]
    """``step_id`` -> ``t_order``, for the steps made so far."""
    leaves: tuple[str, ...] = ()
    """The steps of the branch no other step depends on: used by the projection only."""


@dataclass(frozen=True)
class RuleResult:
    step: PlanStep
    unmatched_readings: tuple[UnmatchedReading, ...] = ()
    notes: tuple[PlanNote, ...] = ()


class TranslationRule(Protocol):
    def translate(self, node: ConstraintNode, ctx: RuleContext) -> RuleResult: ...


def expect(node: ConstraintNode, kind: type[NodeT]) -> NodeT:
    """The node as the type its rule handles; the registry dispatches on ``kind``."""
    if not isinstance(node, kind):
        raise TypeError(f"{node.constraint_id} is a {node.kind} node, not {kind.__name__}")
    return node


def unique(values: Iterable[str | None]) -> list[str]:
    """The values without None and repeats, in their first order."""
    return list(dict.fromkeys(v for v in values if v is not None))


def observations(variables: Iterable[str], ctx: RuleContext) -> list[str]:
    """The observation steps of the variables, in the order of ``variables``."""
    return unique(ctx.observation_of[v] for v in variables)


def t_order_after(depends_on: Iterable[str], ctx: RuleContext) -> tuple[float | None, TOrderBasis]:
    """A step is explained once its operands are: the latest ``t_order`` of its dependencies (K4-A3)."""
    known = [t for t in (ctx.t_orders[d] for d in depends_on) if t is not None]
    return (max(known), TOrderBasis.INTERVAL) if known else (None, TOrderBasis.NONE)


def entity_of(variable: str, position: int, ctx: RuleContext) -> str | None:
    """The entity of argument N of a variable.

    First the value the engine projected in the row (``Mk.argN``), then argument N of the
    attributed interval when its order is meaningful, otherwise unknown (null): K4 does
    not assign roles (A7 of K1).
    """
    argument = ctx.view.argument(f"{variable}.arg{position}")
    if argument is not None:
        return argument.entity_id
    binding = ctx.bindings.get(variable)
    interval_id = binding.interval_id if binding is not None else None
    if interval_id is None:
        return None
    interval = ctx.view.interval(interval_id)
    if interval.args_ordered and len(interval.args) >= position:
        return interval.args[position - 1]
    return None


def argument_position(side: str) -> int | None:
    """N for a side ``Mk.argN`` of a comparison; None if the side is not an argument."""
    _, _, attribute = side.partition(".")
    if not attribute.startswith("arg") or not attribute[3:].isdigit() or int(attribute[3:]) < 1:
        return None
    return int(attribute[3:])


def side_entity(side: str, ctx: RuleContext) -> str | None:
    """The entity of a side ``Mk.argN`` of a comparison; None if it is not an argument or not known."""
    position = argument_position(side)
    return None if position is None else entity_of(side.partition(".")[0], position, ctx)
