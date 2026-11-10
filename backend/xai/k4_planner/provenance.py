"""Provenance: the steps that say how the detection was obtained.

One step for each voice the contract has, in a fixed order (F2-1), each citing where in the
source of truth the fact is. They carry no text and come after everything else in the plan.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from xai.contract.plan import IN_REPORT2, Binding, PlanStep, StepRole, StepType, TOrderBasis
from xai.k4_planner.view import SourceOfTruthView

PROVENANCE_STEP_PREFIX = "s_prov_"


@dataclass(frozen=True)
class ProvenanceRule:
    view: SourceOfTruthView

    def steps(self, bindings: Sequence[Binding], *, reinforcement: bool) -> tuple[PlanStep, ...]:
        """The provenance steps, in the fixed order of the voices.

        ``reinforcement`` tells whether the plan has a reinforcement step: the voice on how the
        modalities were associated is there only then. The voices on the variables and on the
        confidences are there only when the contract has something to cite (F2-2).
        """
        view = self.view
        config = view.document.contract_meta.pipeline_config
        meta = ("contract_meta", "pipeline_config")
        voices: list[tuple[str, list[str]]] = [("sampling", [view.source_pointer(*meta, "sampling")])]
        if config.merge_tolerance_s is not None:
            voices.append(("merge_tolerance", [view.source_pointer(*meta, "merge_tolerance_s")]))
        voices.append(("determinism", [view.source_pointer(*meta, "determinism")]))
        voices.append(("detection_mode", [view.source_pointer(*meta, "detection_mode")]))
        voices.append(("params_origin", [view.source_pointer("contract_meta", "params_origin")]))
        if reinforcement:
            voices.append(("modality_association", [view.source_pointer("event", "reinforcement")]))
        candidates = _candidates(bindings)
        if candidates:
            voices.append(("bindings", candidates))
        measured = [i.interval_id for i in view.intervals if i.confidence is not None]
        if measured:
            voices.append(("confidences", measured))
        voices.append(("contract_hash", [view.source_pointer("contract_meta", "contract_hash")]))
        return tuple(_step(name, refs) for name, refs in voices)


def _candidates(bindings: Sequence[Binding]) -> list[str]:
    """The intervals every variable could be bound to, in rule order, each once."""
    seen: dict[str, None] = {}
    for binding in bindings:
        for interval_id in binding.interval_ids:
            seen.setdefault(interval_id)
    return list(seen)


def _step(name: str, refs: list[str]) -> PlanStep:
    return PlanStep(
        step_id=f"{PROVENANCE_STEP_PREFIX}{name}",
        type=StepType.PROVENANCE,
        refs=refs,
        role=StepRole.CONTEXT,
        depends_on=[],
        t_order=None,
        t_order_basis=TOrderBasis.NONE,
        in_report2=IN_REPORT2[StepType.PROVENANCE],
    )
