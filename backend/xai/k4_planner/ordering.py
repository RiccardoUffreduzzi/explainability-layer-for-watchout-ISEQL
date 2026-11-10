"""Reading order: the single sequence in which the plan is read (K4-A12).

The rule steps come first. Inside a branch, a step comes only after the steps it depends on;
among the steps that are ready, the one placed earlier in time comes first, then the one of the
type observation, condition, temporal, identity, then the one of the earlier rule node, then by
``step_id``. Branches are not interleaved: they come in the order of their first ``t_order``.

Each limit goes right after the last of the steps it is hooked to, in the order K2 wrote the
limits. The reinforcement comes after the last conclusion and its limits; the provenance steps
close the plan.
"""

from collections.abc import Sequence

from xai.contract.plan import PlanStep, StepType
from xai.k4_planner.translation import BranchSteps
from xai.k4_planner.view import SourceOfTruthView

_TYPE_RANK = {
    StepType.OBSERVATION: 0,
    StepType.CONDITION: 1,
    StepType.TEMPORAL: 2,
    StepType.IDENTITY: 3,
}
_AFTER_ALL = len(_TYPE_RANK)

_Key = tuple[bool, float, int, int, str]


class ReadingOrder:
    def __init__(self, view: SourceOfTruthView) -> None:
        self._view = view

    def order(
        self,
        branches: Sequence[BranchSteps],
        limits: Sequence[PlanStep],
        reinforcement: PlanStep | None,
        provenance: Sequence[PlanStep],
    ) -> tuple[PlanStep, ...]:
        rule_steps = self._rule_steps(branches)
        position = {step.step_id: i for i, step in enumerate(rule_steps)}
        after: dict[int, list[PlanStep]] = {}
        for limit in limits:
            after.setdefault(max(position[step_id] for step_id in limit.depends_on), []).append(limit)
        ordered: list[PlanStep] = []
        for i, step in enumerate(rule_steps):
            ordered.append(step)
            ordered.extend(after.get(i, ()))
        if reinforcement is not None:
            ordered.append(reinforcement)
        ordered.extend(provenance)
        return tuple(ordered)

    def _rule_steps(self, branches: Sequence[BranchSteps]) -> list[PlanStep]:
        ordered = [self._sorted(branch.steps) for branch in branches]
        by_first_time = sorted(
            range(len(ordered)),
            key=lambda i: (*_first_time(ordered[i]), i),
        )
        return [step for i in by_first_time for step in ordered[i]]

    def _sorted(self, steps: Sequence[PlanStep]) -> list[PlanStep]:
        pending = {step.step_id: step for step in steps}
        done: set[str] = set()
        ordered: list[PlanStep] = []
        while pending:
            ready = [s for s in pending.values() if all(d in done for d in s.depends_on)]
            if not ready:
                raise ValueError(f"steps with a missing or cyclic dependency: {sorted(pending)}")
            chosen = min(ready, key=self._key)
            ordered.append(chosen)
            done.add(chosen.step_id)
            del pending[chosen.step_id]
        return ordered

    def _key(self, step: PlanStep) -> _Key:
        position = self._view.node_index(step.construct_) if step.construct_ is not None else 0
        return (
            step.t_order is None,
            step.t_order if step.t_order is not None else 0.0,
            _TYPE_RANK.get(step.type, _AFTER_ALL),
            position,
            step.step_id,
        )


def _first_time(steps: Sequence[PlanStep]) -> tuple[bool, float]:
    first = steps[0].t_order
    return first is None, first if first is not None else 0.0
