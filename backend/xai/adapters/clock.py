"""Implementations of the ``Clock`` port."""

from datetime import datetime, timezone


class SystemClock:
    """The current time in UTC, to the second (``source_snapshot.extracted_at``)."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc).replace(microsecond=0)


class FixedClock:
    """Always the same time: two runs on the same data give the same draft (determinism tests)."""

    def __init__(self, instant: datetime) -> None:
        if instant.tzinfo is None:
            raise ValueError("FixedClock needs a time with an offset")
        self.instant = instant

    def now(self) -> datetime:
        return self.instant
