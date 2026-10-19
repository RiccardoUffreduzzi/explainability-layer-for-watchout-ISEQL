"""What K1 returns: ``HarvestFailure`` when it refuses,
``HarvestResult`` for each row of the end-of-analysis batch."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from xai.contract.ids import RowValue
from xai.contract.model import ContractDraft, Violation
from xai.contract.reasons import InputError

FailureStage = Literal["input", "checks"]


class HarvestFailure(Exception):
    """K1 could not write a faithful draft; nothing is written.
    if ``stage = input``: the request cannot be answered.
    if ``stage = checks``: the draft broke an invariant (``violations``).
    """

    def __init__(
        self,
        stage: FailureStage,
        detail: str,
        code: InputError | None = None,
        violations: tuple[Violation, ...] = (),
    ) -> None:
        super().__init__(f"{code.value if code else stage}: {detail}")
        self.stage: FailureStage = stage
        self.code = code
        self.detail = detail
        self.violations = violations

    @classmethod
    def input(cls, code: InputError, detail: str) -> "HarvestFailure":
        return cls("input", detail, code=code)

    @classmethod
    def checks(cls, violations: tuple[Violation, ...]) -> "HarvestFailure":
        detail = f"{len(violations)} violation(s) of the closing checks"
        return cls("checks", detail, violations=violations)

    def to_data(self) -> dict[str, object]:
        """The failure as JSON data"""
        return {
            "stage": self.stage,
            "code": self.code.value if self.code else None,
            "detail": self.detail,
            "violations": [v.model_dump(mode="json") for v in self.violations],
        }


@dataclass(frozen=True)
class HarvestResult:
    """What the batch made of one row of a detection: a draft, a failure or a duplicate."""

    index: int
    """Position of the row among the rows the engine returned."""
    row: Mapping[str, RowValue]
    event_id: str
    draft: ContractDraft | None = None
    failure: HarvestFailure | None = None
    engine_error: str | None = None
    """WatchOut's engine failed on a rule the row needs (the A or B rule of a C row)."""
    duplicate_of: int | None = None
    """The engine returned the same row earlier, at this index: one draft for both."""
