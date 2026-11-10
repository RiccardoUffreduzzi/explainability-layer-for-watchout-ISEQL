"""Reinforcement: the ``s_reinforcement`` step, only when K2 wrote a fixed sentence for it.

``no_counterpart`` and ``not_multimodal`` have no sentence, so they leave no step (K4-D2). Any
other status has one, and its step is the first thing after the conclusions that Report 2 reads
(K4-D3 for ``not_comparable``).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from xai.contract.plan import IN_REPORT2, PlanStep, StepRole, StepType
from xai.k4_planner.timing import latest_t_order
from xai.k4_planner.view import SourceOfTruthView

REINFORCEMENT_STEP_ID = "s_reinforcement"


@dataclass(frozen=True)
class ReinforcementRule:
    view: SourceOfTruthView

    def step(
        self,
        conclusions: Sequence[str],
        t_orders: Mapping[str, float | None],
    ) -> PlanStep | None:
        reinforcement = self.view.reinforcement()
        if reinforcement is None or reinforcement.sentence is None:
            return None
        detections = self.view.event.modality_detections
        refs = [
            self.view.event.event_id,
            *(self.view.source_pointer("event", "modality_detections", i) for i in range(len(detections))),
        ]
        t_order, basis = latest_t_order(conclusions, t_orders)
        return PlanStep(
            step_id=REINFORCEMENT_STEP_ID,
            type=StepType.REINFORCEMENT,
            refs=refs,
            role=StepRole.CONTEXT,
            depends_on=list(conclusions),
            t_order=t_order,
            t_order_basis=basis,
            in_report2=IN_REPORT2[StepType.REINFORCEMENT],
            fixed_text=reinforcement.sentence,
        )
