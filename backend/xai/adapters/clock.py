"""Implementations of the ``Clock`` port."""

from datetime import datetime, timezone


class SystemClock:
    """The current time in UTC, to the second (``source_snapshot.extracted_at``)."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc).replace(microsecond=0)
