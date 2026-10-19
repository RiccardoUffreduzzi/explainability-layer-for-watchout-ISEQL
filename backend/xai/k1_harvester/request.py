"""What K1 is asked to explain: one row of one detection."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from xai.contract.ids import RowValue
from xai.contract.model import Condition

ParamsMode = Literal["auto", "saved", "defaults"]
"""``saved``: ``Analyses.DeltasJson``; ``defaults``: the rules' defaults; ``auto``: saved if present."""


@dataclass(frozen=True)
class HarvestRequest:
    analysis_id: str
    event_type: str
    row: Mapping[str, RowValue]
    """The row's values, as the engine returns them or as the GUI shows them."""
    condition: Condition | None = None
    """None: the condition of the analysis."""
    params: ParamsMode = "auto"
