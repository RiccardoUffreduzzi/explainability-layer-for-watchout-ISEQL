"""``ReportFailure``: no report is written"""

from typing import Any

from xai.contract.report import ReportTrace


class ReportFailure(Exception):
    """The report cannot be written: the input does not hold together, or the LLM gave no usable text.

    Codes: ``PLAN_NOT_FOUND``, ``PLAN_INVALID``, ``SOURCE_NOT_FOUND``, ``SOURCE_INVALID``,
    ``PLAN_HASH_MISMATCH``, ``CONTRACT_HASH_MISMATCH``, ``EVENT_MISMATCH``, ``UNSUPPORTED_REF``,
    ``LLM_UNAVAILABLE``, ``TEXT_NOT_RENDERABLE``.
    """

    def __init__(self, code: str, message: str, trace: ReportTrace | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.trace = trace
        """The calls made before the failure, when the LLM was called."""

    def to_data(self) -> dict[str, Any]:
        return {"stage": "report", "code": self.code, "message": self.message}
