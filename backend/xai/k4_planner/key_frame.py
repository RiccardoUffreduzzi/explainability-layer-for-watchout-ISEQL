"""The key frame of the detection: the ``s_key_frame`` step, only when the event has one.

The key frame is the frame WatchOut shows for the detection row in its results.
There is one key frame per detection and it does not say when each observation was seen, so it
orders nothing: its ``t_order`` is null and the reading order puts it after the conclusions and
their limits.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from xai.contract.plan import IN_REPORT2, PlanStep, StepRole, StepType, TOrderBasis
from xai.k4_planner.view import SourceOfTruthView

KEY_FRAME_STEP_ID: Final = "s_key_frame"


@dataclass(frozen=True)
class KeyFrameRule:
    view: SourceOfTruthView

    def step(self, conclusions: Sequence[str]) -> PlanStep | None:
        key_frame = self.view.event.key_frame
        if key_frame is None:
            return None
        return PlanStep(
            step_id=KEY_FRAME_STEP_ID,
            type=StepType.CONTEXT,
            refs=[key_frame.keyframe_id],
            role=StepRole.CONTEXT,
            depends_on=list(conclusions),
            t_order=None,
            t_order_basis=TOrderBasis.NONE,
            in_report2=IN_REPORT2[StepType.CONTEXT],
        )
