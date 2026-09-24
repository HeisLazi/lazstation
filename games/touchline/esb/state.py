"""Minimal serializable owners for simulation state; no match rules live here."""

from __future__ import annotations

from dataclasses import dataclass, field

from .events import EventEnvelope
from .model import MatchState
from .randomness import RandomStreams


@dataclass
class SimulationState:
    match: MatchState
    random_streams: RandomStreams
    events: list[EventEnvelope] = field(default_factory=list)
    next_event_sequence: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.events, list):
            raise TypeError("simulation event history must be a mutable list")
        if type(self.next_event_sequence) is not int or self.next_event_sequence < 0:
            raise ValueError("next event sequence must be non-negative")
        sequences = [event.sequence for event in self.events]
        if len(sequences) != len(set(sequences)):
            raise ValueError("simulation state cannot repeat event sequences")
        if sequences != sorted(sequences):
            raise ValueError("simulation events must be stored in sequence order")
        if sequences and self.next_event_sequence <= max(sequences):
            raise ValueError("next event sequence must follow all recorded events")
