"""What the ISEQL compiler decides for one event

``compile_event_plan`` (iseql.compiler) returns a ``CompiledPlan`` built in the
same pass that emits the SQL, from the same objects. 
The operator SQL is emitted from its ``OperatorPlan``, so the plan cannot
describe a query other than the one that runs.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal, Optional, Union

Form = Literal["F1", "F2", "F3", "F4"]
"""F1 flat chain, F2 ``set_expression`` groups, F3 ``set_side`` operands,
F4 nested groups (``group_id``) or query references (``query_ref``)."""

Domain = Literal["frames", "seconds"]
Modality = Literal["visual", "audio"]
ParamOrigin = Literal["template_geometry", "engine_default", "literal", "named_key"]


@dataclass(frozen=True)
class SelectionPlan:
    """One alternative (∨) of an interval's selection."""

    predicates: tuple[str, ...]
    arg_classes: tuple[tuple[int, tuple[str, ...]], ...]   # (argument position, allowed classes)


@dataclass(frozen=True)
class IntervalPlan:
    index: int                      # position in model["intervals"]
    alias: str                      # M1, M2, ... inside its branch
    modality: Modality              # table it reads: VisualPerInterval or AudioPerInterval
    selection: tuple[SelectionPlan, ...]
    text: str                       # ISEQL text of the selection


@dataclass(frozen=True)
class ParamPlan:
    name: str                       # delta | epsilon | zeta | eta | rho
    origin: ParamOrigin
    authored: Any                   # delta_map entry as written (named key or literal); None if absent
    resolved: Any                   # value handed to the SQL helper (None = unbounded)
    in_sql: Any                     # value as the helper writes it in the SQL (iseql.helpers.sql_threshold)
    pointer: Optional[str]          # /delta_map/<key>/<name>, when the entry has it


@dataclass(frozen=True)
class OperatorPlan:
    pair: int                       # 0-based: between intervals pair and pair + 1 of the branch
    left: str                       # M1
    right: str                      # M2
    operator: str                   # Bef, Aft, SP, EF, DJ, RDJ, LOJ, ROJ
    chosen_by: Literal["geometry", "override"]
    override_index: Optional[int]   # position in model["operator_overrides"]
    detail: str
    delta_map_key: Optional[str]    # the delta_map entry read ("0", "left.0", "s2.0")
    domain: Domain
    params: tuple[ParamPlan, ...]   # every parameter of the operator
    sql: str
    text: str                       # ISEQL text, e.g. Bef(δ:2; ζ:<=, ρ:0)


@dataclass(frozen=True)
class ConditionPlan:
    """A cross-condition of a branch, rebased on the branch's aliases."""

    index: int                      # position in model["cross_conditions"]
    left: str                       # M1.sf
    op: str
    right: str
    kind: Literal["compare", "duration"]
    value: Union[int, float, None]  # duration bound
    domain: Optional[Domain]        # domain of a duration; None for a comparison
    sql: str
    text: str


@dataclass(frozen=True)
class FieldPlan:
    field: str                      # projected field, e.g. M1.arg1 or M2.et
    kind: str                       # argN | sf | ef | st | et
    arg_class: Optional[str]        # class WatchOut names an argument column after


@dataclass(frozen=True)
class ExtentPlan:
    """Aliases of the intervals whose start and end bound the event."""

    start: Optional[str]
    end: Optional[str]


@dataclass(frozen=True)
class BranchPlan:
    name: str                       # "main", the group name, or "left" / "right"
    side: Optional[str]             # key of delta_map / operator_overrides lookups
    domain: Domain
    intervals: tuple[IntervalPlan, ...]
    operators: tuple[OperatorPlan, ...]
    conditions: tuple[ConditionPlan, ...]
    projection: tuple[FieldPlan, ...]
    projection_pointer: str
    projection_text: str
    extent: ExtentPlan


@dataclass(frozen=True)
class SetNode:
    op: str                         # ∪ | \ | ∩
    pointer: str
    children: tuple[Union["SetNode", str], ...]   # branch names at the leaves


@dataclass(frozen=True)
class ColumnPlan:
    position: int
    label: str                      # column name in the detection result
    kind: str
    fields: tuple[tuple[str, str], ...]   # (branch, field); a branch not listed fills NULL
    arg_class: Optional[str]


@dataclass(frozen=True)
class CompiledPlan:
    form: Form
    branches: tuple[BranchPlan, ...]
    set_tree: Optional[SetNode]
    columns: Optional[tuple[ColumnPlan, ...]]
    columns_problem: Optional[str]  # why the columns cannot be named, when columns is None
    extent: ExtentPlan
    text: str                       # the rule in ISEQL notation
    lineage: bool                   # whether compile_event_plan can give a lineage query

    def branch(self, name: str) -> BranchPlan:
        return next(b for b in self.branches if b.name == name)

    def to_json(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class CompiledEvent:
    iseql_text: str                 # authored text, as compile_event returns it
    sql: str                        # detection SQL, identical to compile_event
    plan: CompiledPlan
    lineage_sql: Optional[str]      # sql + a JSON "lineage" column; None for form F4
