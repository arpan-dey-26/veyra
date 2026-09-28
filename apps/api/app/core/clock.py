"""Injectable clock. Services take a Clock instead of calling datetime.now() directly,
so time-dependent rules (expiry, eligibility intervals, alert windows) are testable."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FixedClock:
    def __init__(self, at: datetime) -> None:
        if at.tzinfo is None:
            raise ValueError("FixedClock requires a timezone-aware datetime")
        self._at = at

    def now(self) -> datetime:
        return self._at
