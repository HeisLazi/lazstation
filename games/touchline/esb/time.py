"""Explicit match-clock and calendar-date values."""

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True, order=True)
class MatchClock:
    """Integer match ticks with an explicit duration in milliseconds."""

    tick: int
    tick_duration_ms: int

    def __post_init__(self) -> None:
        if type(self.tick) is not int or self.tick < 0:
            raise ValueError("match tick must be a non-negative integer")
        if type(self.tick_duration_ms) is not int or self.tick_duration_ms <= 0:
            raise ValueError("tick duration must be a positive integer in ms")

    @property
    def elapsed_milliseconds(self) -> int:
        return self.tick * self.tick_duration_ms

    def advance(self, ticks: int = 1) -> MatchClock:
        if type(ticks) is not int or ticks < 0:
            raise ValueError("tick advance must be a non-negative integer")
        return MatchClock(self.tick + ticks, self.tick_duration_ms)


@dataclass(frozen=True, order=True)
class WorldDate:
    """A calendar date, kept distinct from a match's simulation tick."""

    day: date

    def __post_init__(self) -> None:
        if isinstance(self.day, datetime) or not isinstance(self.day, date):
            raise TypeError("world date must be a calendar date, not a timestamp")

    @property
    def isoformat(self) -> str:
        return self.day.isoformat()
