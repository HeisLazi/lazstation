"""Synthetic deterministic updates used only to prove P01 checkpoint contracts."""

from __future__ import annotations

import json
from datetime import date

from games.touchline.esb.events import EventEnvelope
from games.touchline.esb.ids import new_club_id, new_event_id, new_match_id
from games.touchline.esb.model import MatchState
from games.touchline.esb.randomness import RandomStreams
from games.touchline.esb.state import SimulationState
from games.touchline.esb.time import MatchClock, WorldDate


def new_replay_state(seed: int = 481516) -> SimulationState:
    match_id = new_match_id("p01-core-01", seed)
    return SimulationState(
        match=MatchState(
            match_id=match_id,
            home_club_id=new_club_id("p01-core-01", "home"),
            away_club_id=new_club_id("p01-core-01", "away"),
            clock=MatchClock(tick=0, tick_duration_ms=250),
            phase="synthetic_contract_run",
        ),
        random_streams=RandomStreams.seeded(seed),
    )


def read_synthetic_report(state: SimulationState) -> int:
    """Represent a report query; it draws only from the reporting stream."""
    return state.random_streams.stream("reporting").randbelow(1_000_000)


def advance_synthetic(state: SimulationState) -> None:
    """Advance one test-only state update and append its deterministic event."""
    sequence = state.next_event_sequence
    match = state.match
    draw = state.random_streams.stream("football").randbelow(10_000)
    world_draw = (
        state.random_streams.stream("world").randbelow(1_000)
        if sequence % 3 == 0 else None
    )
    scored = draw < 1_500
    previous = state.events[-1].event_id if state.events else None
    event = EventEnvelope(
        event_id=new_event_id("p01-core-01", str(match.match_id), sequence),
        aggregate_type="match",
        aggregate_id=str(match.match_id),
        sequence=sequence,
        kind="synthetic_contract_update",
        match_id=match.match_id,
        match_tick=match.clock.tick,
        world_date=WorldDate(date(2026, 9, 24)),
        cause_event_id=previous,
        parent_event_id=previous,
        payload_json=json.dumps({"synthetic_index": sequence}, separators=(",", ":")),
        outcome_json=json.dumps(
            {"draw": draw, "scored": scored, "world_draw": world_draw},
            separators=(",", ":"),
        ),
    )
    state.events.append(event)
    if scored:
        match.home_score += 1
    match.clock = match.clock.advance()
    match.revision += 1
    state.next_event_sequence += 1


def run_synthetic_updates(state: SimulationState, count: int) -> SimulationState:
    if type(count) is not int or count < 0:
        raise ValueError("update count must be non-negative")
    for _ in range(count):
        advance_synthetic(state)
        if state.next_event_sequence % 2 == 0:
            read_synthetic_report(state)
    return state
