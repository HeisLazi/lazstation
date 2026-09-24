"""Pass execution, first touch and physically reachable interception windows."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from games.touchline.esb.ids import PlayerId, validate_id
from games.touchline.esb.match.ball import (
    BALL_RADIUS_M,
    DEFAULT_BALL_PHYSICS,
    BallPhysics,
    BallState,
    advance_ball,
    simulate_ball_ticks,
    ticks_for_duration,
)
from games.touchline.esb.match.spatial import (
    MovementIntent,
    Pitch,
    PlayerMotion,
    advance_player,
)
from games.touchline.esb.model import Position2D
from games.touchline.esb.people import PlayerProfile
from games.touchline.esb.randomness import RandomStream


class PassKind(str, Enum):
    DRIVEN = "driven"
    CHIPPED = "chipped"
    FLOATED = "floated"


class TouchOutcome(str, Enum):
    NO_CONTACT = "no_contact"
    CONTROLLED = "controlled"
    KNOCKDOWN = "knockdown"
    DEFLECTION = "deflection"


@dataclass(frozen=True)
class PassIntent:
    kind: PassKind
    target_position: Position2D
    intended_receiver_id: PlayerId | None = None
    intended_area_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, PassKind):
            raise TypeError("pass intent requires a supported delivery type")
        if not isinstance(self.target_position, Position2D):
            raise TypeError("pass intent requires a target position")
        if (self.intended_receiver_id is None) == (self.intended_area_id is None):
            raise ValueError("pass must name exactly one intended receiver or target area")
        if self.intended_receiver_id is not None:
            validate_id(self.intended_receiver_id, kind="intended receiver ID")
        if self.intended_area_id is not None:
            validate_id(self.intended_area_id, kind="intended pass area ID")


@dataclass(frozen=True)
class PassDelivery:
    passer_id: PlayerId
    kind: PassKind
    intended_receiver_id: PlayerId | None
    intended_area_id: str | None
    intended_target: Position2D
    actual_target: Position2D
    target_error_m: float
    execution_quality: float
    origin_state: BallState
    launch_state: BallState
    planned_travel_time_s: float
    physics: BallPhysics

    def __post_init__(self) -> None:
        validate_id(self.passer_id, kind="passer ID")
        if not isinstance(self.kind, PassKind):
            raise TypeError("pass delivery requires a supported type")
        if (self.intended_receiver_id is None) == (self.intended_area_id is None):
            raise ValueError("pass delivery must preserve exactly one receiver/area intent")
        if self.intended_receiver_id is not None:
            validate_id(self.intended_receiver_id, kind="intended receiver ID")
        if self.intended_area_id is not None:
            validate_id(self.intended_area_id, kind="intended pass area ID")
        if not isinstance(self.intended_target, Position2D) or not isinstance(self.actual_target, Position2D):
            raise TypeError("pass delivery targets must be positions")
        if not isinstance(self.origin_state, BallState) or not isinstance(self.launch_state, BallState):
            raise TypeError("pass delivery requires its origin and actual launch ball states")
        if not isinstance(self.physics, BallPhysics):
            raise TypeError("pass delivery requires the physics constants used to create it")
        for label, value in (
            ("target error", self.target_error_m),
            ("execution quality", self.execution_quality),
            ("planned travel time", self.planned_travel_time_s),
        ):
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError(f"pass {label} must be finite")
        if self.target_error_m < 0 or not 0.0 <= self.execution_quality <= 1.0:
            raise ValueError("pass error must be non-negative and execution quality normalized")
        if self.planned_travel_time_s <= 0:
            raise ValueError("pass travel time must be positive")


def _capability(profile: PlayerProfile, name: str) -> float:
    values = {item.name: item.normalized_value for item in profile.capabilities.capabilities}
    if name not in values:
        raise ValueError(f"{profile.display_name} has no explicit {name} capability")
    return values[name]


def _ground_travel_time(distance_m: float, initial_speed_mps: float, friction_mps2: float) -> float:
    discriminant = initial_speed_mps * initial_speed_mps - 2.0 * friction_mps2 * distance_m
    if discriminant <= 0.0:
        return initial_speed_mps / max(friction_mps2, 1e-9)
    return 2.0 * distance_m / (initial_speed_mps + math.sqrt(discriminant))


def execute_pass(
    passer: PlayerProfile,
    ball: BallState,
    intent: PassIntent,
    random_stream: RandomStream,
    *,
    physics: BallPhysics = DEFAULT_BALL_PHYSICS,
) -> PassDelivery:
    """Produce an explicit, replayable delivery; authored error is provisional."""

    if not isinstance(passer, PlayerProfile) or not isinstance(ball, BallState) or not isinstance(intent, PassIntent):
        raise TypeError("pass execution requires a profile, ball snapshot and intent")
    if not isinstance(random_stream, RandomStream):
        raise TypeError("pass execution requires an explicit deterministic random stream")
    if not isinstance(physics, BallPhysics):
        raise TypeError("pass execution requires explicit ball physics")
    if ball.height_m > BALL_RADIUS_M + 0.12 or abs(ball.velocity_z_mps) > 0.5:
        raise ValueError("pass execution currently requires a grounded, foot-playable ball")

    dx = intent.target_position.x_m - ball.position.x_m
    dy = intent.target_position.y_m - ball.position.y_m
    distance = math.hypot(dx, dy)
    if distance <= 0.1:
        raise ValueError("pass target must be more than 0.1 metres from the ball")
    ux, uy = dx / distance, dy / distance
    perpendicular_x, perpendicular_y = -uy, ux

    technique_name = "short_passing" if intent.kind is PassKind.DRIVEN else "long_passing"
    technique = _capability(passer, technique_name)
    distribution = _capability(passer, "distribution")
    quality = 0.55 * technique + 0.45 * distribution

    # Difference-of-uniforms gives a bounded, zero-centred triangular error.
    # Coefficients are exposed scenario defaults, not real-player calibration.
    longitudinal_noise = random_stream.random() - random_stream.random()
    lateral_noise = random_stream.random() - random_stream.random()
    longitudinal_error = longitudinal_noise * max(0.04, distance * (0.012 + 0.065 * (1.0 - quality)))
    lateral_error = lateral_noise * (0.08 + 0.18 * distance * (1.0 - quality))
    actual_target = Position2D(
        intent.target_position.x_m + ux * longitudinal_error + perpendicular_x * lateral_error,
        intent.target_position.y_m + uy * longitudinal_error + perpendicular_y * lateral_error,
    )
    target_error = math.hypot(longitudinal_error, lateral_error)
    actual_distance = math.hypot(actual_target.x_m - ball.position.x_m, actual_target.y_m - ball.position.y_m)
    direction_x = (actual_target.x_m - ball.position.x_m) / actual_distance
    direction_y = (actual_target.y_m - ball.position.y_m) / actual_distance

    if intent.kind is PassKind.DRIVEN:
        speed = min(24.0, max(4.0, 5.5 + actual_distance * 0.38 + (distribution - 0.5) * 2.0))
        velocity_x = direction_x * speed
        velocity_y = direction_y * speed
        velocity_z = 0.0
        travel_time = _ground_travel_time(actual_distance, speed, physics.ground_friction_mps2)
    else:
        angle = math.radians(28.0 if intent.kind is PassKind.CHIPPED else 43.0)
        required_speed = math.sqrt(actual_distance * physics.gravity_mps2 / math.sin(2.0 * angle))
        speed = min(28.0, required_speed)
        velocity_x = direction_x * speed * math.cos(angle)
        velocity_y = direction_y * speed * math.cos(angle)
        velocity_z = speed * math.sin(angle)
        travel_time = 2.0 * velocity_z / physics.gravity_mps2

    launch = BallState(
        ball.position,
        ball.height_m,
        velocity_x,
        velocity_y,
        velocity_z,
    )
    return PassDelivery(
        passer.player_id,
        intent.kind,
        intent.intended_receiver_id,
        intent.intended_area_id,
        intent.target_position,
        actual_target,
        target_error,
        quality,
        ball,
        launch,
        travel_time,
        physics,
    )


def trace_pass(delivery: PassDelivery, *, physics: BallPhysics | None = None) -> tuple[BallState, ...]:
    """Replay every fixed-step ball state for a previously executed delivery."""

    if not isinstance(delivery, PassDelivery):
        raise TypeError("pass trace requires a PassDelivery")
    selected = delivery.physics if physics is None else physics
    if selected != delivery.physics:
        raise ValueError("pass trace physics must match the recorded pass physics")
    ticks = ticks_for_duration(delivery.planned_travel_time_s, selected.step_seconds)
    return (delivery.origin_state,) + simulate_ball_ticks(delivery.launch_state, ticks, selected)


@dataclass(frozen=True)
class TouchResult:
    player_id: PlayerId
    outcome: TouchOutcome
    ball_after: BallState
    control_margin: float | None
    explanation: str

    def __post_init__(self) -> None:
        validate_id(self.player_id, kind="touching player ID")
        if not isinstance(self.outcome, TouchOutcome) or not isinstance(self.ball_after, BallState):
            raise TypeError("touch result requires an explicit outcome and ball state")
        if self.control_margin is not None and (
            type(self.control_margin) not in (int, float) or not math.isfinite(self.control_margin)
        ):
            raise ValueError("touch control margin must be finite when present")
        if not isinstance(self.explanation, str) or not self.explanation.strip():
            raise ValueError("touch result requires an explanation")


def receive_ball(
    receiver: PlayerProfile,
    body: PlayerMotion,
    ball: BallState,
    random_stream: RandomStream,
    *,
    touch_direction_radians: float | None = None,
    contact_radius_m: float = 0.75,
    maximum_contact_height_m: float = 2.0,
) -> TouchResult:
    """Resolve an actual local touch without assigning lasting possession."""

    if (
        not isinstance(receiver, PlayerProfile)
        or not isinstance(body, PlayerMotion)
        or not isinstance(ball, BallState)
    ):
        raise TypeError("receiving requires a profile, player motion and ball state")
    if receiver.player_id != body.player_id:
        raise ValueError("receiver profile and body must have the same player ID")
    if not isinstance(random_stream, RandomStream):
        raise TypeError("receiving requires an explicit deterministic random stream")
    for label, value in (("contact radius", contact_radius_m), ("maximum contact height", maximum_contact_height_m)):
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"{label} must be positive and finite")
    if touch_direction_radians is not None and (
        type(touch_direction_radians) not in (int, float) or not math.isfinite(touch_direction_radians)
    ):
        raise ValueError("touch direction must be a finite angle")

    separation = math.hypot(ball.position.x_m - body.position.x_m, ball.position.y_m - body.position.y_m)
    if separation > contact_radius_m or ball.height_m > maximum_contact_height_m:
        reason = "Ball outside reach radius." if separation > contact_radius_m else "Ball above legal contact height."
        return TouchResult(receiver.player_id, TouchOutcome.NO_CONTACT, ball, None, reason)

    first_touch = _capability(receiver, "first_touch")
    receiving = _capability(receiver, "receiving")
    technique = 0.58 * first_touch + 0.42 * receiving
    speed_penalty = min(0.45, ball.speed_mps * 0.022)
    height_penalty = max(0.0, ball.height_m - 0.25) * 0.055
    ball_bearing = math.atan2(
        ball.position.y_m - body.position.y_m,
        ball.position.x_m - body.position.x_m,
    )
    facing_error = abs(math.remainder(ball_bearing - body.facing_radians, 2.0 * math.pi))
    orientation_penalty = 0.14 * (1.0 - max(0.0, math.cos(facing_error)))
    bounded_variation = (random_stream.random() - random_stream.random()) * 0.07
    margin = technique - 0.48 - speed_penalty - height_penalty - orientation_penalty + bounded_variation

    direction = body.facing_radians if touch_direction_radians is None else touch_direction_radians
    direction_x, direction_y = math.cos(direction), math.sin(direction)
    if margin >= 0.0:
        if ball.height_m > BALL_RADIUS_M + 1e-6 or abs(ball.velocity_z_mps) > 1.2:
            horizontal_speed = min(3.0, max(1.0, ball.horizontal_speed_mps * 0.35))
            ball_after = BallState(
                ball.position,
                ball.height_m,
                direction_x * horizontal_speed,
                direction_y * horizontal_speed,
                -max(1.0, abs(ball.velocity_z_mps) * 0.65),
            )
            return TouchResult(
                receiver.player_id,
                TouchOutcome.KNOCKDOWN,
                ball_after,
                margin,
                "Controlled aerial contact redirects the ball downward; it remains live at the contact point.",
            )
        touch_speed = min(2.2, 0.35 + ball.horizontal_speed_mps * 0.18)
        ball_after = BallState(
            ball.position,
            BALL_RADIUS_M,
            direction_x * touch_speed,
            direction_y * touch_speed,
            0.0,
        )
        return TouchResult(
            receiver.player_id,
            TouchOutcome.CONTROLLED,
            ball_after,
            margin,
            "Controlled cushioned first touch keeps the ball close for the next action; "
            "possession is not assigned here.",
        )

    horizontal_speed = ball.horizontal_speed_mps
    if horizontal_speed <= 1e-9:
        incoming_x, incoming_y = direction_x, direction_y
    else:
        incoming_x, incoming_y = ball.velocity_x_mps / horizontal_speed, ball.velocity_y_mps / horizontal_speed
    rotation = (random_stream.random() - random_stream.random()) * 0.65
    cos_rotation, sin_rotation = math.cos(rotation), math.sin(rotation)
    deflected_x = incoming_x * cos_rotation - incoming_y * sin_rotation
    deflected_y = incoming_x * sin_rotation + incoming_y * cos_rotation
    remaining_speed = max(0.8, horizontal_speed * (0.62 + 0.18 * random_stream.random()))
    vertical_velocity = ball.velocity_z_mps
    if ball.height_m > 0.32:
        vertical_velocity = -max(0.8, abs(ball.velocity_z_mps) * 0.35)
    else:
        vertical_velocity = 0.0
    ball_after = BallState(
        ball.position,
        ball.height_m,
        deflected_x * remaining_speed,
        deflected_y * remaining_speed,
        vertical_velocity,
    )
    return TouchResult(
        receiver.player_id,
        TouchOutcome.DEFLECTION,
        ball_after,
        margin,
        "The contact is uncontrolled; the ball deflects from this location and remains live.",
    )


@dataclass(frozen=True)
class InterceptionWindow:
    player_id: PlayerId
    arrival_time_s: float
    player_position: Position2D
    ball_position: Position2D
    ball_height_m: float
    reach_radius_m: float

    def __post_init__(self) -> None:
        validate_id(self.player_id, kind="interception player ID")
        if not isinstance(self.player_position, Position2D) or not isinstance(self.ball_position, Position2D):
            raise TypeError("interception window requires resolved positions")
        for label, value in (
            ("arrival time", self.arrival_time_s),
            ("ball height", self.ball_height_m),
            ("reach radius", self.reach_radius_m),
        ):
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError(f"interception {label} must be finite and non-negative")


def find_interception_window(
    player: PlayerMotion,
    ball: BallState,
    *,
    max_time_s: float,
    physics: BallPhysics = DEFAULT_BALL_PHYSICS,
    pitch: Pitch = Pitch(),
    reach_radius_m: float = 0.65,
    legal_height_m: float = 1.8,
) -> InterceptionWindow | None:
    """Chase the evolving ball from a shared snapshot; never place a player at it."""

    if not isinstance(player, PlayerMotion) or not isinstance(ball, BallState):
        raise TypeError("interception search requires player and ball snapshots")
    if not isinstance(physics, BallPhysics) or not isinstance(pitch, Pitch):
        raise TypeError("interception search requires fixed-step physics and pitch bounds")
    for label, value in (
        ("time horizon", max_time_s),
        ("reach radius", reach_radius_m),
        ("legal height", legal_height_m),
    ):
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"interception {label} must be positive and finite")
    if not pitch.contains(player.position):
        raise ValueError("interception player must begin within the pitch")

    current_player = player
    current_ball = ball
    dt = physics.step_seconds
    max_ticks = int(max_time_s / dt + 1e-12)
    for tick in range(max_ticks + 1):
        separation = math.hypot(
            current_player.position.x_m - current_ball.position.x_m,
            current_player.position.y_m - current_ball.position.y_m,
        )
        if current_ball.height_m <= legal_height_m and separation <= reach_radius_m:
            return InterceptionWindow(
                player.player_id,
                tick * dt,
                current_player.position,
                current_ball.position,
                current_ball.height_m,
                reach_radius_m,
            )
        if tick == max_ticks:
            break
        current_ball = advance_ball(current_ball, physics)
        if not pitch.contains(current_ball.position):
            break
        current_player = advance_player(
            current_player,
            MovementIntent(player.player_id, current_ball.position),
            dt,
            pitch,
        )
    return None


@dataclass(frozen=True)
class InterceptionContest:
    winner_id: PlayerId | None
    windows: tuple[InterceptionWindow, ...]
    tied_player_ids: tuple[PlayerId, ...]
    explanation: str

    def __post_init__(self) -> None:
        if self.winner_id is not None:
            validate_id(self.winner_id, kind="interception winner ID")
        if not isinstance(self.windows, tuple) or not isinstance(self.tied_player_ids, tuple):
            raise TypeError("contest evidence must be immutable tuples")
        if self.winner_id is not None and self.winner_id not in {item.player_id for item in self.windows}:
            raise ValueError("interception winner must have a reachable window")
        if self.winner_id is None and self.tied_player_ids:
            raise ValueError("an unresolved contest cannot list tied candidates")
        if not isinstance(self.explanation, str) or not self.explanation.strip():
            raise ValueError("interception contest requires an explanation")


def resolve_interception_contest(
    players: tuple[PlayerMotion, ...],
    ball: BallState,
    random_stream: RandomStream,
    *,
    max_time_s: float,
    physics: BallPhysics = DEFAULT_BALL_PHYSICS,
    pitch: Pitch = Pitch(),
    reach_radius_m: float = 0.65,
    legal_height_m: float = 1.8,
) -> InterceptionContest:
    """Evaluate all players before resolving the earliest arrival and exact tie."""

    if not isinstance(players, tuple):
        raise TypeError("contest players must be an immutable shared snapshot")
    if not isinstance(random_stream, RandomStream):
        raise TypeError("contest tie handling requires an explicit deterministic stream")
    if not isinstance(physics, BallPhysics) or not isinstance(pitch, Pitch):
        raise TypeError("contest resolution requires fixed-step physics and pitch bounds")
    for label, value in (
        ("time horizon", max_time_s),
        ("reach radius", reach_radius_m),
        ("legal height", legal_height_m),
    ):
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"interception {label} must be positive and finite")
    ids = [item.player_id for item in players]
    if len(ids) != len(set(ids)):
        raise ValueError("interception contest cannot repeat a player")
    windows = tuple(
        window
        for item in players
        if (window := find_interception_window(
            item,
            ball,
            max_time_s=max_time_s,
            physics=physics,
            pitch=pitch,
            reach_radius_m=reach_radius_m,
            legal_height_m=legal_height_m,
        )) is not None
    )
    windows = tuple(sorted(windows, key=lambda item: (item.arrival_time_s, str(item.player_id))))
    if not windows:
        return InterceptionContest(
            None,
            (),
            (),
            "No player can arrive at the ball while it is at a legal contact height.",
        )

    earliest = windows[0].arrival_time_s
    tied = tuple(sorted(
        (item.player_id for item in windows if math.isclose(item.arrival_time_s, earliest, abs_tol=1e-9)),
        key=str,
    ))
    if len(tied) == 1:
        winner = tied[0]
        explanation = f"{winner} arrives first at {earliest:.3f}s; other reachable windows are later."
    else:
        winner = tied[random_stream.randbelow(len(tied))]
        explanation = (
            f"{len(tied)} players share the earliest {earliest:.3f}s window; "
            f"a seeded tie-break chose {winner}."
        )
    return InterceptionContest(winner, windows, tied, explanation)


__all__ = [
    "InterceptionContest",
    "InterceptionWindow",
    "PassDelivery",
    "PassIntent",
    "PassKind",
    "TouchOutcome",
    "TouchResult",
    "execute_pass",
    "find_interception_window",
    "receive_ball",
    "resolve_interception_contest",
    "trace_pass",
]
