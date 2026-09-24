"""Small reusable pass-versus-arrival scenarios for P03 replay and profiling."""

from __future__ import annotations

import math
from dataclasses import dataclass

from games.touchline.esb.match.actions import (
    InterceptionContest,
    PassDelivery,
    PassIntent,
    execute_pass,
    resolve_interception_contest,
    trace_pass,
)
from games.touchline.esb.match.ball import DEFAULT_BALL_PHYSICS, BallPhysics, BallState
from games.touchline.esb.match.spatial import Pitch, PlayerMotion
from games.touchline.esb.people import PlayerProfile
from games.touchline.esb.randomness import RandomStreams


@dataclass(frozen=True)
class PassScenario:
    seed: int
    passer: PlayerProfile
    initial_ball: BallState
    intent: PassIntent
    contenders: tuple[PlayerMotion, ...]
    maximum_search_time_s: float = 6.0
    physics: BallPhysics = DEFAULT_BALL_PHYSICS
    pitch: Pitch = Pitch()

    def __post_init__(self) -> None:
        if type(self.seed) is not int:
            raise TypeError("scenario seed must be an integer")
        if not isinstance(self.passer, PlayerProfile) or not isinstance(self.initial_ball, BallState):
            raise TypeError("pass scenario requires a passer and starting ball")
        if not isinstance(self.intent, PassIntent) or not isinstance(self.contenders, tuple):
            raise TypeError("pass scenario requires an explicit intent and immutable contender snapshot")
        if any(not isinstance(item, PlayerMotion) for item in self.contenders):
            raise TypeError("scenario contenders must be PlayerMotion records")
        if not isinstance(self.physics, BallPhysics) or not isinstance(self.pitch, Pitch):
            raise TypeError("pass scenario requires fixed-step physics and pitch bounds")
        if (
            type(self.maximum_search_time_s) not in (int, float)
            or not math.isfinite(self.maximum_search_time_s)
            or self.maximum_search_time_s <= 0
        ):
            raise ValueError("scenario search horizon must be positive and finite")
        player_ids = [item.player_id for item in self.contenders]
        if len(player_ids) != len(set(player_ids)):
            raise ValueError("scenario contender IDs must be unique")


@dataclass(frozen=True)
class PassScenarioTrace:
    delivery: PassDelivery
    ball_flight: tuple[BallState, ...]
    contest: InterceptionContest


def replay_pass_scenario(scenario: PassScenario) -> PassScenarioTrace:
    """Replay a deterministic pass and all contender windows from one seed."""

    if not isinstance(scenario, PassScenario):
        raise TypeError("scenario replay requires PassScenario")
    football = RandomStreams.seeded(scenario.seed).stream("football")
    delivery = execute_pass(
        scenario.passer,
        scenario.initial_ball,
        scenario.intent,
        football,
        physics=scenario.physics,
    )
    flight = trace_pass(delivery, physics=scenario.physics)
    contest = resolve_interception_contest(
        scenario.contenders,
        delivery.launch_state,
        football,
        max_time_s=min(scenario.maximum_search_time_s, delivery.planned_travel_time_s + 2.0),
        physics=scenario.physics,
        pitch=scenario.pitch,
    )
    return PassScenarioTrace(delivery, flight, contest)


__all__ = ["PassScenario", "PassScenarioTrace", "replay_pass_scenario"]
