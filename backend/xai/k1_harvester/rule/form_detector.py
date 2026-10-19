"""Which of the stored forms a rule has2"""

from xai.contract.reasons import InputError
from xai.k1_harvester.ports import ModelForm, RuleSnapshot
from xai.k1_harvester.result import HarvestFailure


class ModelFormDetector:
    def detect(self, rule: RuleSnapshot) -> ModelForm:
        intervals = rule.model.get("intervals") or []
        for position, interval in enumerate(intervals):
            for key in ("group_id", "query_ref"):
                if interval.get(key):
                    raise HarvestFailure.input(
                        InputError.UNSUPPORTED_CONSTRUCT,
                        f"{rule.ref}: interval {position} has {key} (form F4)",
                    )
        if rule.model.get("set_expression") is not None:
            return "F2"
        if any(interval.get("set_side") for interval in intervals):
            return "F3"
        return "F1"
