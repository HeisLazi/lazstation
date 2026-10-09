"""Experimental continuous open-play possession and decision loop (P04).

This is deliberately a small headless match core. It owns perception, action
generation, choice, execution and chronological events, while reusing P03's
physics. Formal laws, restarts, out-of-play and full-match timing belong to P05.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

from games.touchline.esb.events import EventEnvelope
from games.touchline.esb.ids import EventId, MatchId, PlayerId, validate_id
from games.touchline.esb.match.actions import PassIntent, PassKind, execute_pass, receive_ball
from games.touchline.esb.match.ball import BALL_RADIUS_M, BallPhysics, BallState, advance_ball
from games.touchline.esb.match.spatial import (
    MovementIntent, Pitch, PlayerMotion, advance_player,
)
from games.touchline.esb.model import Position2D
from games.touchline.esb.people import PlayerProfile
from games.touchline.esb.randomness import RandomStreams
from games.touchline.esb.time import MatchClock


class ActionKind(str, Enum):
    CARRY = "carry"
    PASS = "pass"
    SHOT = "shot"
    MOVE = "move"
    PRESS = "press"
    CHALLENGE = "challenge"
    KEEP = "keep"


@dataclass(frozen=True)
class PerceivedPlayer:
    player_id: PlayerId
    position: Position2D
    distance_m: float
    bearing_radians: float
    team_id: str


@dataclass(frozen=True)
class Perception:
    observer_id: PlayerId
    ball: BallState
    visible_players: tuple[PerceivedPlayer, ...]
    nearest_opponent_distance_m: float | None
    goal_distance_m: float
    recognized_options: tuple[ActionKind, ...]


@dataclass(frozen=True)
class FeasibleAction:
    kind: ActionKind
    actor_id: PlayerId
    target_id: PlayerId | None = None
    target: Position2D | None = None
    intent: PassIntent | None = None
    provisional_value: float = 0.0
    explanation: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ActionKind):
            raise TypeError("feasible action requires a registered action kind")
        validate_id(self.actor_id, kind="action actor ID")
        if self.target_id is not None:
            validate_id(self.target_id, kind="action target ID")
        if self.target is not None and not isinstance(self.target, Position2D):
            raise TypeError("action target must be a position")
        if self.intent is not None and not isinstance(self.intent, PassIntent):
            raise TypeError("pass action intent must be a PassIntent")
        if type(self.provisional_value) not in (int, float) or not math.isfinite(self.provisional_value):
            raise ValueError("provisional action value must be finite")
        if not 0.0 <= self.provisional_value <= 1.0:
            raise ValueError("provisional action value must be in [0, 1]")
        if not isinstance(self.explanation, str) or not self.explanation.strip():
            raise ValueError("feasible action requires an explanation")
        if self.kind is ActionKind.PASS and self.intent is None:
            raise ValueError("pass action must carry an explicit pass intent")


@dataclass(frozen=True)
class PlayerState:
    profile: PlayerProfile
    motion: PlayerMotion
    team_id: str

    def __post_init__(self) -> None:
        validate_id(self.team_id, kind="team ID")
        if not isinstance(self.profile, PlayerProfile) or not isinstance(self.motion, PlayerMotion):
            raise TypeError("player state requires a profile and motion snapshot")
        if self.profile.player_id != self.motion.player_id or self.motion.team_id != self.team_id:
            raise ValueError("player state profile, motion and team must agree")


@dataclass(frozen=True)
class ActionRecord:
    tick: int
    sequence: int
    kind: ActionKind
    actor_id: PlayerId
    target_id: PlayerId | None
    outcome: str
    cause_event_id: EventId | None = None
    parent_event_id: EventId | None = None
    details: tuple[tuple[str, str], ...] = ()


@dataclass
class OpenPlayState:
    match_id: MatchId
    clock: MatchClock
    pitch: Pitch
    physics: BallPhysics
    players: dict[PlayerId, PlayerState]
    ball: BallState
    possession_id: PlayerId | None
    possession_team_id: str | None
    random_streams: RandomStreams
    last_pass_event_id: EventId | None = None
    last_pass_receiver_id: PlayerId | None = None
    shot_assist_event_id: EventId | None = None
    shot_assist_player_id: PlayerId | None = None
    events: list[EventEnvelope] = field(default_factory=list)
    action_log: list[ActionRecord] = field(default_factory=list)
    next_sequence: int = 0
    home_score: int = 0
    away_score: int = 0
    statistics: dict[str, int] = field(default_factory=dict)
    out_of_play_boundary: str | None = None
    attack_right_by_team: dict[str, bool] = field(
        default_factory=lambda: {"home": True, "away": False})

    def __post_init__(self) -> None:
        validate_id(self.match_id, kind="match ID")
        if not isinstance(self.clock, MatchClock) or not isinstance(self.pitch, Pitch):
            raise TypeError("open play requires a match clock and pitch")
        if not isinstance(self.physics, BallPhysics) or not isinstance(self.ball, BallState):
            raise TypeError("open play requires explicit ball physics and state")
        if not isinstance(self.random_streams, RandomStreams):
            raise TypeError("open play requires persistent named random streams")
        expected_clock_ms = self.physics.step_seconds * 1000.0
        if not math.isclose(self.clock.tick_duration_ms, expected_clock_ms, abs_tol=1e-9):
            raise ValueError("match clock tick duration must match the fixed physics step")
        if not self.players or any(key != value.profile.player_id for key, value in self.players.items()):
            raise ValueError("open play needs a consistent non-empty player map")
        if {player.team_id for player in self.players.values()} != {"home", "away"}:
            raise ValueError("P04 proof matches require both home and away team IDs")
        if any(not self.pitch.contains(player.motion.position) for player in self.players.values()):
            raise ValueError("open-play players must begin within pitch bounds")
        if self.out_of_play_boundary not in (None, "touchline", "goal_line"):
            raise ValueError("out-of-play boundary must be touchline, goal_line or unset")
        if (set(self.attack_right_by_team) != {"home", "away"}
                or any(type(value) is not bool for value in self.attack_right_by_team.values())):
            raise ValueError("open-play attack directions require home/away boolean values")
        if not self.pitch.contains(self.ball.position):
            raise ValueError("P04 open-play ball must begin within pitch bounds")
        if self.possession_id is None:
            if self.possession_team_id is not None:
                raise ValueError("uncontrolled possession cannot name a team")
        else:
            if self.possession_id not in self.players:
                raise ValueError("possessor must be a match player")
            if self.players[self.possession_id].team_id != self.possession_team_id:
                raise ValueError("possessor team must match player team")


@dataclass(frozen=True)
class Decision:
    actor_id: PlayerId
    perceived: Perception
    feasible_actions: tuple[FeasibleAction, ...]
    chosen: FeasibleAction
    rationale: str

    def __post_init__(self) -> None:
        validate_id(self.actor_id, kind="decision actor ID")
        if not isinstance(self.perceived, Perception) or not isinstance(self.feasible_actions, tuple):
            raise TypeError("decision requires immutable perception and feasible-action records")
        if not self.feasible_actions or any(item.actor_id != self.actor_id for item in self.feasible_actions):
            raise ValueError("decision actions must be non-empty and belong to its actor")
        if self.chosen not in self.feasible_actions:
            raise ValueError("chosen action must be one of the recorded feasible actions")
        if self.perceived.observer_id != self.actor_id:
            raise ValueError("decision perception must belong to its actor")
        if not isinstance(self.rationale, str) or not self.rationale.strip():
            raise ValueError("decision requires an inspectable rationale")


def _cap(profile: PlayerProfile, name: str) -> float:
    for item in profile.capabilities.capabilities:
        if item.name == name:
            return float(item.normalized_value)
    raise ValueError(f"{profile.display_name} has no explicit {name} capability")


def _tendency(profile: PlayerProfile, name: str) -> float:
    for item in profile.tendencies.values:
        if item.name == name:
            return float(item.value)
    raise ValueError(f"{profile.display_name} has no explicit {name} action tendency")


def perceive(state: OpenPlayState, observer_id: PlayerId, *, visual_range_m: float = 42.0) -> Perception:
    """Build a local observable snapshot; scanning affects range and recognition."""
    player = state.players[observer_id]
    origin = player.motion.position
    scanning = _cap(player.profile, "scanning")
    radius = visual_range_m * (0.68 + 0.64 * scanning)
    visible = []
    for other in sorted(state.players.values(), key=lambda item: str(item.profile.player_id)):
        if other.profile.player_id == observer_id:
            continue
        dx = other.motion.position.x_m - origin.x_m
        dy = other.motion.position.y_m - origin.y_m
        distance = math.hypot(dx, dy)
        if distance <= radius:
            visible.append(PerceivedPlayer(other.profile.player_id, other.motion.position, distance,
                                           math.atan2(dy, dx), other.team_id))
    opponents = [item.distance_m for item in visible if item.team_id != player.team_id]
    goal_x = state.pitch.length_m if state.attack_right_by_team[player.team_id] else 0.0
    goal_distance = math.hypot(goal_x - origin.x_m, state.pitch.width_m / 2 - origin.y_m)
    # Poor scanning can fail to recognize a low-value distant option. Physical
    # technique is deliberately absent from this stage.
    options: list[ActionKind] = [ActionKind.CARRY, ActionKind.PASS]
    if goal_distance < 32.0:
        options.append(ActionKind.SHOT)
    if any(item.team_id != player.team_id for item in visible):
        options.extend((ActionKind.PRESS, ActionKind.CHALLENGE))
    if scanning < 0.35:
        options = [option for option in options if option is not ActionKind.PASS or goal_distance < 12.0]
    return Perception(observer_id, state.ball, tuple(visible), min(opponents) if opponents else None,
                      goal_distance, tuple(options))


def generate_feasible_actions(state: OpenPlayState, actor_id: PlayerId) -> tuple[FeasibleAction, ...]:
    """Construct legal-in-P04 options using the actual local geometry."""
    actor = state.players[actor_id]
    own = actor.team_id
    origin = actor.motion.position
    perception = perceive(state, actor_id)
    choices: list[FeasibleAction] = []
    if state.possession_id == actor_id:
        pressure = perception.nearest_opponent_distance_m
        visible_player_ids = {item.player_id for item in perception.visible_players}
        carry_target = state.pitch.clamp(Position2D(
            origin.x_m + (5.0 if state.attack_right_by_team[own] else -5.0), origin.y_m))
        if ActionKind.CARRY in perception.recognized_options:
            choices.append(FeasibleAction(ActionKind.CARRY, actor_id, target=carry_target,
                provisional_value=0.43 + (0.12 if pressure is None or pressure > 3 else -0.06),
                explanation="Carry into open space; value depends on nearby pressure."))
        for target in sorted(state.players.values(), key=lambda item: str(item.profile.player_id)):
            if target.team_id != own or target.profile.player_id == actor_id:
                continue
            if target.profile.player_id not in visible_player_ids:
                continue
            d = math.dist((origin.x_m, origin.y_m), (target.motion.position.x_m, target.motion.position.y_m))
            if 4.0 <= d <= 32.0 and ActionKind.PASS in perception.recognized_options:
                nearest = min((math.dist((target.motion.position.x_m, target.motion.position.y_m),
                                        (op.motion.position.x_m, op.motion.position.y_m))
                               for op in state.players.values() if op.team_id != own), default=20.0)
                forward = ((target.motion.position.x_m - origin.x_m)
                           * (1 if state.attack_right_by_team[own] else -1))
                value = 0.48 + min(0.18, forward / 120.0) + min(0.12, nearest / 80.0)
                intent = PassIntent(PassKind.DRIVEN, target.motion.position,
                                    intended_receiver_id=target.profile.player_id)
                choices.append(FeasibleAction(ActionKind.PASS, actor_id, target.profile.player_id,
                                              target.motion.position, intent, value,
                                              "Pass to a reachable teammate; space and progress inform value."))
        if ActionKind.SHOT in perception.recognized_options:
            distance = perception.goal_distance_m
            # Explicit baseline chance estimate, independent of execution.
            q = max(0.015, min(0.55, 0.34 * math.exp(-distance / 20.0)))
            choices.append(FeasibleAction(ActionKind.SHOT, actor_id,
                target=Position2D(state.pitch.length_m if state.attack_right_by_team[own] else 0.0,
                                  state.pitch.width_m / 2), provisional_value=q,
                explanation=f"Provisional shot-quality estimate {q:.3f}; finishing is resolved separately."))
        if not choices:
            choices.append(FeasibleAction(ActionKind.KEEP, actor_id, target=origin,
                                          provisional_value=0.1, explanation="No progressive option is feasible."))
    elif state.possession_id is None:
        # Any nearby player may contest a loose ball; P03 still decides actual
        # arrival and legal contact. No possession is assigned by proximity.
        distance = math.dist((origin.x_m, origin.y_m), (state.ball.position.x_m, state.ball.position.y_m))
        if distance <= 24.0:
            kind = ActionKind.CHALLENGE if state.possession_team_id not in (None, own) else ActionKind.MOVE
            choices.append(FeasibleAction(kind, actor_id, target=state.ball.position,
                provisional_value=max(0.0, 1.0 - distance / 30.0),
                explanation="Move toward the live ball; contact and control are resolved physically."))
    elif state.possession_team_id != own:
        carrier = state.players[state.possession_id]
        distance = math.dist((origin.x_m, origin.y_m), (carrier.motion.position.x_m, carrier.motion.position.y_m))
        if distance <= 20.0:
            kind = ActionKind.CHALLENGE if distance <= 2.2 else ActionKind.PRESS
            choices.append(FeasibleAction(kind, actor_id, state.possession_id,
                carrier.motion.position, provisional_value=max(0.0, 0.8 - distance / 30.0),
                explanation=("Attempt a physical challenge; a local contest is required to regain possession."
                             if kind is ActionKind.CHALLENGE else
                             "Close the carrier; pressure does not itself change possession.")))
    else:
        # Off-ball support run makes all teammates active during open play.
        direction = 1 if state.attack_right_by_team[own] else -1
        target = state.pitch.clamp(Position2D(origin.x_m + direction * 3.0, origin.y_m))
        choices.append(FeasibleAction(ActionKind.MOVE, actor_id, target=target,
                                      provisional_value=0.25, explanation="Offer a nearby support lane."))
    return tuple(choices)


def choose_action(state: OpenPlayState, actor_id: PlayerId,
                  actions: tuple[FeasibleAction, ...] | None = None) -> Decision:
    """Choose from perceived feasible options; decision skill/tendencies act here."""
    perceived = perceive(state, actor_id)
    feasible = generate_feasible_actions(state, actor_id) if actions is None else actions
    if not feasible:
        raise ValueError("cannot choose from an empty feasible action set")
    profile = state.players[actor_id].profile
    decision = _cap(profile, "decision_quality")
    anticipation = _cap(profile, "anticipation")
    tolerance = _tendency(profile, "risk_tolerance")
    ranked = []
    for option in feasible:
        # Decision quality scales how much the player uses option value;
        # below-average players retain a wider deterministic evaluation error.
        noise = (state_random(state).random() - 0.5) * (0.22 * (1.0 - decision))
        risk_adjust = (tolerance - 0.5) * (0.12 if option.kind is ActionKind.SHOT else 0.04)
        anticipation_adjust = (anticipation - 0.5) * (0.08 if option.kind in (ActionKind.PASS, ActionKind.PRESS) else 0.0)
        evaluated_value = 0.5 + (option.provisional_value - 0.5) * (0.35 + 1.30 * decision)
        ranked.append((evaluated_value + risk_adjust + anticipation_adjust + noise,
                       option, noise, risk_adjust, anticipation_adjust))
    _, chosen, noise, risk_adjust, anticipation_adjust = max(
        ranked, key=lambda row: (row[0], row[1].kind.value, str(row[1].target_id or "")))
    rationale = (f"value={chosen.provisional_value:.3f}; decision-quality={decision:.2f}; "
                 f"evaluation-noise={noise:+.3f}; risk={risk_adjust:+.3f}; anticipation={anticipation_adjust:+.3f}")
    return Decision(actor_id, perceived, feasible, chosen, rationale)


def state_random(state: OpenPlayState):
    return state.random_streams.stream("football")


def _event(state: OpenPlayState, kind: str, actor: PlayerId | None, payload: dict,
           outcome: dict, *, cause: EventId | None = None, parent: EventId | None = None) -> EventId:
    seq = state.next_sequence
    eid = EventId(f"event:{state.match_id}:{seq:08d}")
    event = EventEnvelope(eid, "match", str(state.match_id), seq, kind,
        match_id=state.match_id, match_tick=state.clock.tick,
        cause_event_id=cause, parent_event_id=parent,
        payload_json=json.dumps({"actor_id": str(actor) if actor else None, **payload}, sort_keys=True),
        outcome_json=json.dumps(outcome, sort_keys=True))
    state.events.append(event)
    state.next_sequence += 1
    return eid


def _record(state: OpenPlayState, decision: Decision, outcome: str,
            *, cause: EventId | None = None, parent: EventId | None = None,
            details: tuple[tuple[str, str], ...] = ()) -> None:
    state.action_log.append(ActionRecord(state.clock.tick, len(state.action_log),
        decision.chosen.kind, decision.actor_id, decision.chosen.target_id,
        outcome, cause, parent, details))


def _nearest_for_team(state: OpenPlayState, ball: BallState, team: str) -> PlayerState | None:
    eligible = [state.players[key] for key in sorted(state.players, key=str)
                if state.players[key].team_id == team]
    if not eligible:
        return None
    return min(eligible, key=lambda p: (math.dist((p.motion.position.x_m, p.motion.position.y_m),
                                                   (ball.position.x_m, ball.position.y_m)),
                                        str(p.profile.player_id)))


def _finish_flight(state: OpenPlayState, delivery, passer_id: PlayerId,
                   *, stop_on_contact: Callable[[PlayerId, dict[PlayerId, Position2D], Position2D], bool]
                   | None = None) -> None:
    """Advance the pass until first real contact or settling, checking every tick."""
    ball = delivery.launch_state
    prior_team = state.possession_team_id
    state.ball = ball
    state.possession_id = None
    state.possession_team_id = None
    max_ticks = min(900, max(1, math.ceil((delivery.planned_travel_time_s + 1.2) / state.physics.step_seconds)))
    previous = state.last_pass_event_id
    receiver_id = delivery.intended_receiver_id
    launch_positions = {player_id: player.motion.position
                        for player_id, player in state.players.items()}
    for _ in range(max_ticks):
        # Every player pursues or attacks the next ball position from the shared
        # snapshot. This deliberately simple P04 movement policy is inspectable.
        previous_ball = state.ball
        next_ball = advance_ball(previous_ball, state.physics)
        if not state.pitch.contains(next_ball.position):
            # P05 owns the rule transition. Preserve the first crossed boundary
            # and interpolate the crossing point so the restart uses the right
            # line and the event tick reflects when the ball actually left.
            dx = next_ball.position.x_m - previous_ball.position.x_m
            dy = next_ball.position.y_m - previous_ball.position.y_m
            crossings = []
            if next_ball.position.y_m < 0.0 and dy < 0.0:
                crossings.append(((0.0 - previous_ball.position.y_m) / dy, 0, "touchline", "y", 0.0))
            if next_ball.position.y_m > state.pitch.width_m and dy > 0.0:
                crossings.append(((state.pitch.width_m - previous_ball.position.y_m) / dy,
                                  0, "touchline", "y", state.pitch.width_m))
            if next_ball.position.x_m < 0.0 and dx < 0.0:
                crossings.append(((0.0 - previous_ball.position.x_m) / dx,
                                  1, "goal_line", "x", 0.0))
            if next_ball.position.x_m > state.pitch.length_m and dx > 0.0:
                crossings.append(((state.pitch.length_m - previous_ball.position.x_m) / dx,
                                  1, "goal_line", "x", state.pitch.length_m))
            if not crossings:
                raise RuntimeError("out-of-bounds ball has no crossed pitch boundary")
            fraction, _, boundary, axis, edge = min(crossings, key=lambda row: (row[0], row[1]))
            position = Position2D(
                edge if axis == "x" else previous_ball.position.x_m + dx * fraction,
                edge if axis == "y" else previous_ball.position.y_m + dy * fraction,
            )
            crossing_height = max(BALL_RADIUS_M, previous_ball.height_m +
                (next_ball.height_m - previous_ball.height_m) * fraction)
            state.ball = BallState(position, crossing_height,
                next_ball.velocity_x_mps, next_ball.velocity_y_mps, next_ball.velocity_z_mps)
            state.out_of_play_boundary = boundary
            state.clock = state.clock.advance(1)
            state.possession_id = None
            state.possession_team_id = None
            return
        moved = {}
        for item in (state.players[key] for key in sorted(state.players, key=str)):
            motion = advance_player(item.motion, MovementIntent(item.profile.player_id, next_ball.position),
                                    state.physics.step_seconds, state.pitch)
            moved[item.profile.player_id] = PlayerState(item.profile, motion, item.team_id)
        state.players.update(moved)
        state.ball = next_ball
        candidates = sorted(state.players.values(), key=lambda p: (
            math.dist((p.motion.position.x_m, p.motion.position.y_m),
                      (next_ball.position.x_m, next_ball.position.y_m)),
            str(p.profile.player_id)))
        touched = None
        for item in candidates:
            if (item.profile.player_id == passer_id
                    and math.dist((next_ball.position.x_m, next_ball.position.y_m),
                                  (delivery.origin_state.position.x_m,
                                   delivery.origin_state.position.y_m)) < 1.0):
                # The kicker's foot contact is the launch action; the initial
                # outgoing ball is not a second receiving opportunity.
                continue
            result = receive_ball(item.profile, item.motion, next_ball,
                                  state_random(state), contact_radius_m=0.78,
                                  maximum_contact_height_m=1.95)
            if result.outcome.value != "no_contact":
                touched = (item, result)
                break
        state.clock = state.clock.advance(1)
        if touched:
            item, result = touched
            state.ball = result.ball_after
            eid = _event(state, "ball_contact", item.profile.player_id,
                {"touch_outcome": result.outcome.value, "explanation": result.explanation},
                {"position_x_m": state.ball.position.x_m, "position_y_m": state.ball.position.y_m,
                 "height_m": state.ball.height_m}, cause=previous, parent=previous)
            if result.outcome.value == "deflection":
                state.statistics["deflections"] = state.statistics.get("deflections", 0) + 1
            if (stop_on_contact is not None and stop_on_contact(
                    item.profile.player_id, launch_positions, delivery.origin_state.position)):
                return
            if result.outcome.value == "controlled":
                old_team = prior_team
                state.possession_id = item.profile.player_id
                state.possession_team_id = item.team_id
                if old_team is None or old_team != item.team_id:
                    state.statistics["recoveries"] = state.statistics.get("recoveries", 0) + 1
                else:
                    state.statistics["receptions"] = state.statistics.get("receptions", 0) + 1
                _event(state, "possession_regained" if old_team != item.team_id else "possession_controlled",
                       item.profile.player_id, {"from_team": old_team}, {"possession_team": item.team_id},
                       cause=eid, parent=previous)
                if item.profile.player_id == receiver_id:
                    state.last_pass_receiver_id = receiver_id
                else:
                    state.last_pass_receiver_id = None
                state.shot_assist_event_id = state.last_pass_event_id if item.profile.player_id == receiver_id else None
                state.shot_assist_player_id = passer_id if item.profile.player_id == receiver_id else None
                return
            # Uncontrolled deflection/knockdown remains live and subsequent
            # loop steps retry a real recovery; it never teleports possession.
        if state.ball.speed_mps <= state.physics.stop_speed_mps and not state.ball.is_airborne:
            break


def execute_action(state: OpenPlayState, decision: Decision,
                   *, stop_on_contact: Callable[[PlayerId, dict[PlayerId, Position2D], Position2D], bool]
                   | None = None,
                   player_already_moved: bool = False) -> None:
    """Apply one chosen action. Execution capabilities are read only here."""
    if type(player_already_moved) is not bool:
        raise TypeError("player_already_moved must be a bool")
    option = decision.chosen
    actor = state.players[decision.actor_id]
    if option.kind in (ActionKind.CARRY, ActionKind.MOVE, ActionKind.PRESS,
                       ActionKind.CHALLENGE, ActionKind.KEEP):
        target = option.target or actor.motion.position
        # A tactical frame may already have advanced this player's motion once
        # through P03 this tick; decision execution must not give them a second
        # movement budget. Carrier touch still couples the ball to that result.
        moved = (actor.motion if player_already_moved else advance_player(
            actor.motion,
            MovementIntent(actor.profile.player_id, target,
                           option.target if option.kind in (ActionKind.PRESS, ActionKind.CHALLENGE) else None),
            state.physics.step_seconds, state.pitch))
        state.players[decision.actor_id] = PlayerState(actor.profile, moved, actor.team_id)
        if state.possession_id == decision.actor_id:
            carrying = _cap(actor.profile, "ball_carrying")
            speed = min(4.8, 1.2 + carrying * 3.0)
            fx, fy = math.cos(moved.facing_radians), math.sin(moved.facing_radians)
            state.ball = BallState(Position2D(moved.position.x_m + fx * 0.45,
                                               moved.position.y_m + fy * 0.45), BALL_RADIUS_M,
                                   moved.velocity_x_mps + fx * speed * 0.15,
                                   moved.velocity_y_mps + fy * speed * 0.15, 0.0)
            eid = _event(state, "carry", actor.profile.player_id,
                         {"ball_carrying": carrying}, {"position_x_m": state.ball.position.x_m,
                         "position_y_m": state.ball.position.y_m})
        else:
            eid = _event(state, option.kind.value, actor.profile.player_id,
                         {"target_id": str(option.target_id) if option.target_id else None},
                         {"position_x_m": moved.position.x_m, "position_y_m": moved.position.y_m})
        _record(state, decision, "executed", cause=eid)
        return
    if option.kind is ActionKind.PASS and option.intent is not None:
        delivery = execute_pass(actor.profile, state.ball, option.intent,
                                state_random(state), physics=state.physics)
        eid = _event(state, "pass", actor.profile.player_id,
            {"receiver_id": (str(option.intent.intended_receiver_id)
                             if option.intent.intended_receiver_id is not None else None),
             "intended_receiver_id": (str(option.intent.intended_receiver_id)
                                      if option.intent.intended_receiver_id is not None else None),
             "intended_area_id": option.intent.intended_area_id,
             "kind": option.intent.kind.value,
             "execution_quality": delivery.execution_quality},
            {"target_error_m": delivery.target_error_m,
             "intended_x_m": delivery.intended_target.x_m, "intended_y_m": delivery.intended_target.y_m,
             "actual_x_m": delivery.actual_target.x_m, "actual_y_m": delivery.actual_target.y_m})
        state.statistics["passes"] = state.statistics.get("passes", 0) + 1
        state.last_pass_event_id = eid
        state.last_pass_receiver_id = option.target_id
        state.shot_assist_event_id = None
        state.shot_assist_player_id = None
        _record(state, decision, "launched", cause=eid)
        _finish_flight(state, delivery, actor.profile.player_id,
                       stop_on_contact=stop_on_contact)
        return
    if option.kind is ActionKind.SHOT and option.target is not None:
        distance = math.dist((state.ball.position.x_m, state.ball.position.y_m),
                             (option.target.x_m, option.target.y_m))
        finishing = _cap(actor.profile, "finishing")
        # Provisional execution dispersion; shot quality and technique remain
        # separate evidence fields. Goalkeeper capabilities act at the save.
        stream = state_random(state)
        error = (stream.random() - stream.random()) * (2.8 - 1.8 * finishing)
        miss_y = state.pitch.width_m / 2 + error
        goalkeeper = next((state.players[key] for key in sorted(state.players, key=str)
                           if state.players[key].team_id != actor.team_id
                           and state.players[key].profile.primary_role.value == "goalkeeper"), None)
        keeper_distance = (math.dist((goalkeeper.motion.position.x_m, goalkeeper.motion.position.y_m),
                                     (option.target.x_m, option.target.y_m))
                           if goalkeeper else None)
        coverage = max(0.0, 1.0 - keeper_distance / 16.0) if keeper_distance is not None else None
        q = option.provisional_value
        if abs(error) < 1.4 and distance <= 28.0:
            reaction = _cap(goalkeeper.profile, "gk_reaction") if goalkeeper else 0.5
            handling = _cap(goalkeeper.profile, "gk_handling") if goalkeeper else 0.5
            coverage_value = coverage if coverage is not None else 0.25
            save_chance = max(0.04, min(0.82,
                (0.68 * reaction + 0.32 * handling - distance / 90.0) * coverage_value))
            saved = stream.random() < save_chance
        else:
            saved = False
        shot_eid = _event(state, "shot", actor.profile.player_id,
            {"shot_quality_estimate": q, "finishing": finishing,
             "goalkeeper_id": str(goalkeeper.profile.player_id) if goalkeeper else None,
             "keeper_distance_m": keeper_distance,
             "keeper_coverage_estimate": coverage,
             "assist_player_id": str(state.shot_assist_player_id) if state.shot_assist_player_id else None,
             "assist_event_id": str(state.shot_assist_event_id) if state.shot_assist_event_id else None},
            {"saved": saved, "execution_error_m": error, "target_y_m": miss_y},
            parent=state.shot_assist_event_id)
        _record(state, decision, "shot_resolved", cause=shot_eid, parent=state.shot_assist_event_id)
        state.statistics["shots"] = state.statistics.get("shots", 0) + 1
        if saved and goalkeeper:
            state.statistics["saves"] = state.statistics.get("saves", 0) + 1
            # Rebound stays live in front of the keeper, with the shot as cause.
            rebound_x = option.target.x_m + (state.ball.position.x_m - option.target.x_m) * 0.12
            state.ball = BallState(Position2D(rebound_x, miss_y), BALL_RADIUS_M,
                                   (stream.random() - .5) * 5.0, (stream.random() - .5) * 5.0, 0.0)
            state.possession_id = None
            state.possession_team_id = None
            rebound_eid = _event(state, "rebound", goalkeeper.profile.player_id,
                {"shot_event_id": str(shot_eid)}, {"x_m": rebound_x, "y_m": miss_y},
                cause=shot_eid, parent=shot_eid)
            state.statistics["rebounds"] = state.statistics.get("rebounds", 0) + 1
            _recover_stationary_ball(state, rebound_eid)
        elif abs(error) < 1.4 and distance <= 28.0:
            state.statistics["goals"] = state.statistics.get("goals", 0) + 1
            if actor.team_id == "home": state.home_score += 1
            else: state.away_score += 1
            _event(state, "goal", actor.profile.player_id, {"shot_event_id": str(shot_eid),
                "assist_player_id": str(state.shot_assist_player_id) if state.shot_assist_player_id else None,
                "assist_event_id": str(state.shot_assist_event_id) if state.shot_assist_event_id else None},
                {"home_score": state.home_score, "away_score": state.away_score},
                cause=shot_eid, parent=state.shot_assist_event_id)
            state.possession_id = None
            state.possession_team_id = None
        else:
            state.ball = BallState(Position2D(option.target.x_m, miss_y), BALL_RADIUS_M,
                                   (stream.random() - .5) * 4.0, (stream.random() - .5) * 4.0, 0.0)
            state.possession_id = None
            state.possession_team_id = None
            miss_eid = _event(state, "shot_rebound", actor.profile.player_id,
                {"shot_event_id": str(shot_eid)}, {"x_m": state.ball.position.x_m, "y_m": state.ball.position.y_m},
                cause=shot_eid, parent=shot_eid)
            state.statistics["rebounds"] = state.statistics.get("rebounds", 0) + 1
            _recover_stationary_ball(state, miss_eid)
        state.shot_assist_event_id = None
        state.shot_assist_player_id = None
        return
    raise ValueError(f"unsupported P04 action {option.kind}")


def _recover_stationary_ball(state: OpenPlayState, cause: EventId) -> None:
    """Recovery requires a real arrival window and a controlled touch."""
    arrivals = []
    for item in (state.players[key] for key in sorted(state.players, key=str)):
        motion = item.motion
        for tick in range(1, 401):
            moved = advance_player(motion, MovementIntent(item.profile.player_id, state.ball.position),
                                   state.physics.step_seconds, state.pitch)
            motion = moved
            if math.dist((motion.position.x_m, motion.position.y_m),
                         (state.ball.position.x_m, state.ball.position.y_m)) <= 0.72:
                arrivals.append((tick, str(item.profile.player_id), item, motion))
                break
    if not arrivals:
        return
    tick, _, item, motion = min(arrivals)
    state.clock = state.clock.advance(tick)
    state.players[item.profile.player_id] = PlayerState(item.profile, motion, item.team_id)
    touch = receive_ball(item.profile, motion, state.ball, state_random(state), contact_radius_m=0.8)
    old_team = state.possession_team_id
    state.ball = touch.ball_after
    contact = _event(state, "rebound_contact", item.profile.player_id,
        {"touch_outcome": touch.outcome.value, "explanation": touch.explanation},
        {"x_m": state.ball.position.x_m, "y_m": state.ball.position.y_m},
        cause=cause, parent=cause)
    if touch.outcome.value == "controlled":
        state.possession_id = item.profile.player_id
        state.possession_team_id = item.team_id
        if old_team is None or old_team != item.team_id:
            state.statistics["recoveries"] = state.statistics.get("recoveries", 0) + 1
        _event(state, "possession_regained" if old_team != item.team_id else "possession_controlled",
            item.profile.player_id, {"from_team": old_team}, {"possession_team": item.team_id},
            cause=contact, parent=cause)
    elif touch.outcome.value == "deflection":
        state.statistics["deflections"] = state.statistics.get("deflections", 0) + 1


def step_open_play(state: OpenPlayState, *, decisions_per_tick: int = 1,
                   stop_on_contact: Callable[[PlayerId, dict[PlayerId, Position2D], Position2D], bool]
                   | None = None,
                   players_already_moved: frozenset[PlayerId] = frozenset()
                   ) -> tuple[Decision, ...]:
    """Run one bounded decision round from a common snapshot.

    The carrier chooses one action. The nearest opponent and nearest support
    player make simultaneous pressure/support decisions before execution.
    """
    if decisions_per_tick != 1:
        raise ValueError("P04 currently resolves one canonical active-player action per tick")
    if not isinstance(players_already_moved, frozenset) or not players_already_moved <= state.players.keys():
        raise ValueError("pre-moved players must be a frozenset of active player IDs")
    if state.possession_id is None:
        candidates = [choose_action(state, pid)
                      for pid in sorted(state.players, key=str)
                      if generate_feasible_actions(state, pid)]
        if candidates:
            selected = max(candidates, key=lambda d: (d.feasible_actions[0].provisional_value,
                                                       str(d.actor_id)))
            execute_action(state, selected,
                           player_already_moved=selected.actor_id in players_already_moved)
            state.clock = state.clock.advance(1)
            return (selected,)
        state.ball = advance_ball(state.ball, state.physics)
        state.clock = state.clock.advance(1)
        return ()
    carrier = state.players[state.possession_id]
    carrier_id = carrier.profile.player_id
    opposition = [state.players[key] for key in sorted(state.players, key=str)
                  if state.players[key].team_id != carrier.team_id]
    nearest = min(opposition, key=lambda p: (math.dist((p.motion.position.x_m, p.motion.position.y_m),
                                                        (carrier.motion.position.x_m, carrier.motion.position.y_m)),
                                             str(p.profile.player_id)), default=None)
    support = _nearest_for_team(state, state.ball, carrier.team_id)
    active_ids = [state.possession_id]
    if nearest: active_ids.append(nearest.profile.player_id)
    if support and support.profile.player_id not in active_ids: active_ids.append(support.profile.player_id)
    # The nearest opponent may still be outside every local action's feasible
    # range. Do not ask that player to choose an empty action set; distance is
    # already the stage boundary for PRESS/CHALLENGE candidates.
    decisions = tuple(
        choose_action(state, pid, feasible)
        for pid in sorted(active_ids, key=str)
        if (feasible := generate_feasible_actions(state, pid))
    )
    # All choices above used the same snapshot. Execute off-ball movement first,
    # then the carrier action. This fixes the actor set for the whole round.
    for decision in decisions:
        if decision.actor_id != state.possession_id:
            execute_action(state, decision,
                           player_already_moved=decision.actor_id in players_already_moved)
    carrier_decision = next(d for d in decisions if d.actor_id == state.possession_id)
    execute_action(state, carrier_decision, stop_on_contact=stop_on_contact,
                   player_already_moved=carrier_decision.actor_id in players_already_moved)
    for challenge in decisions:
        if (challenge.chosen.kind is not ActionKind.CHALLENGE
                or state.possession_id != carrier_id):
            continue
        challenger = state.players[challenge.actor_id]
        current_carrier = state.players[state.possession_id]
        separation = math.dist((challenger.motion.position.x_m, challenger.motion.position.y_m),
                               (state.ball.position.x_m, state.ball.position.y_m))
        if separation > 1.2 or challenger.team_id == current_carrier.team_id:
            continue
        tackling = _cap(challenger.profile, "defensive_positioning")
        timing = _cap(challenger.profile, "pressing_judgment")
        carrier_control = _cap(current_carrier.profile, "ball_carrying")
        contest_margin = 0.58 * tackling + 0.42 * timing - 0.55 * carrier_control
        won = state_random(state).random() < max(0.08, min(0.88, 0.50 + contest_margin * 0.65))
        contest_eid = _event(state, "challenge_contest", challenger.profile.player_id,
            {"carrier_id": str(current_carrier.profile.player_id), "defensive_positioning": tackling,
             "pressing_judgment": timing, "carrier_control": carrier_control},
            {"won": won, "separation_m": separation})
        if won:
            old_team = state.possession_team_id
            state.possession_id = challenger.profile.player_id
            state.possession_team_id = challenger.team_id
            state.statistics["tackles_won"] = state.statistics.get("tackles_won", 0) + 1
            regain_eid = _event(state, "possession_regained", challenger.profile.player_id,
                {"from_team": old_team}, {"possession_team": challenger.team_id},
                cause=contest_eid, parent=contest_eid)
            _record(state, challenge, "challenge_won", cause=regain_eid, parent=contest_eid)
        else:
            _record(state, challenge, "challenge_evaded", cause=contest_eid)
    if state.possession_id is not None:
        state.clock = state.clock.advance(1)
    return decisions


def create_state(match_id: MatchId, players: tuple[PlayerState, ...], ball: BallState,
                 possession_id: PlayerId | None, random_streams: RandomStreams,
                 *, pitch: Pitch = Pitch(), physics: BallPhysics = BallPhysics()) -> OpenPlayState:
    if not isinstance(players, tuple) or not players:
        raise TypeError("open-play players must be a non-empty tuple")
    if not isinstance(random_streams, RandomStreams) or not isinstance(physics, BallPhysics):
        raise TypeError("open play requires named randomness and ball physics")
    clock_ms = physics.step_seconds * 1000.0
    if not math.isclose(clock_ms, round(clock_ms), abs_tol=1e-9):
        raise ValueError("P04 physics steps must map to an integer millisecond match tick")
    mapping = {player.profile.player_id: player for player in players}
    if len(mapping) != len(players):
        raise ValueError("open play cannot repeat players")
    team = mapping[possession_id].team_id if possession_id is not None else None
    return OpenPlayState(match_id, MatchClock(0, round(clock_ms)), pitch, physics, mapping,
                         ball, possession_id, team, random_streams)


__all__ = ["ActionKind", "ActionRecord", "Decision", "FeasibleAction", "OpenPlayState",
           "Perception", "PerceivedPlayer", "PlayerState", "choose_action", "create_state",
           "execute_action", "generate_feasible_actions", "perceive", "step_open_play"]
