"""Deterministic player kinematics and pitch-plane bounds for Touchline."""

from __future__ import annotations

import math
from dataclasses import dataclass

from games.touchline.esb.ids import PlayerId, validate_id
from games.touchline.esb.model import Position2D
from games.touchline.esb.people import PlayerProfile


@dataclass(frozen=True)
class Pitch:
    """Rectangular pitch in metres; x is length and y is width."""

    length_m: float = 105.0
    width_m: float = 68.0

    def __post_init__(self) -> None:
        for label, value in (("length", self.length_m), ("width", self.width_m)):
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"pitch {label} must be positive finite metres")

    def contains(self, position: Position2D) -> bool:
        return 0.0 <= position.x_m <= self.length_m and 0.0 <= position.y_m <= self.width_m

    def clamp(self, position: Position2D) -> Position2D:
        return Position2D(
            min(self.length_m, max(0.0, position.x_m)),
            min(self.width_m, max(0.0, position.y_m)),
        )


@dataclass(frozen=True)
class MotionLimits:
    maximum_speed_mps: float
    acceleration_mps2: float
    turn_rate_rps: float = 4.2

    def __post_init__(self) -> None:
        for label, value in (
            ("maximum speed", self.maximum_speed_mps),
            ("acceleration", self.acceleration_mps2),
            ("turn rate", self.turn_rate_rps),
        ):
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{label} must be positive and finite")


def limits_from_profile(profile: PlayerProfile, *, turn_rate_rps: float = 4.2) -> MotionLimits:
    """Read explicit speed/acceleration measurements; never infer an overall rating."""

    if not isinstance(profile, PlayerProfile):
        raise TypeError("motion limits require a PlayerProfile")
    measurements = {item.name: item for item in profile.capabilities.measurements}
    maximum_speed = measurements.get("maximum_speed")
    acceleration = measurements.get("acceleration")
    if maximum_speed is None or maximum_speed.unit != "m/s":
        raise ValueError(f"{profile.display_name} requires an explicit maximum_speed measurement in m/s")
    if acceleration is None or acceleration.unit != "m/s^2":
        raise ValueError(f"{profile.display_name} requires an explicit acceleration measurement in m/s^2")
    return MotionLimits(maximum_speed.value, acceleration.value, turn_rate_rps)


@dataclass(frozen=True)
class PlayerMotion:
    player_id: PlayerId
    team_id: str
    position: Position2D
    velocity_x_mps: float
    velocity_y_mps: float
    facing_radians: float
    limits: MotionLimits

    def __post_init__(self) -> None:
        validate_id(self.player_id, kind="motion player ID")
        validate_id(self.team_id, kind="motion team ID")
        if not isinstance(self.position, Position2D) or not isinstance(self.limits, MotionLimits):
            raise TypeError("player motion requires a position and explicit motion limits")
        for label, value in (
            ("x velocity", self.velocity_x_mps),
            ("y velocity", self.velocity_y_mps),
            ("facing", self.facing_radians),
        ):
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError(f"player {label} must be finite")
        speed = math.hypot(self.velocity_x_mps, self.velocity_y_mps)
        if speed > self.limits.maximum_speed_mps + 1e-9:
            raise ValueError("player velocity cannot exceed the explicit maximum speed")


@dataclass(frozen=True)
class MovementIntent:
    player_id: PlayerId
    target_position: Position2D
    facing_target: Position2D | None = None

    def __post_init__(self) -> None:
        validate_id(self.player_id, kind="movement intent player ID")
        if not isinstance(self.target_position, Position2D):
            raise TypeError("movement intent requires a target position")
        if self.facing_target is not None and not isinstance(self.facing_target, Position2D):
            raise TypeError("facing target must be a position when supplied")


def _valid_step(step_seconds: float) -> float:
    if type(step_seconds) not in (int, float) or not math.isfinite(step_seconds) or not 0 < step_seconds <= 0.25:
        raise ValueError("simulation step must be finite and in (0, 0.25] seconds")
    return float(step_seconds)


def _approach(x: float, y: float, target_x: float, target_y: float, max_delta: float) -> tuple[float, float]:
    delta_x = target_x - x
    delta_y = target_y - y
    distance = math.hypot(delta_x, delta_y)
    if distance <= max_delta or distance == 0.0:
        return target_x, target_y
    scale = max_delta / distance
    return x + delta_x * scale, y + delta_y * scale


def advance_player(
    player: PlayerMotion,
    intent: MovementIntent,
    step_seconds: float,
    pitch: Pitch = Pitch(),
) -> PlayerMotion:
    """Advance one player by one fixed step with bounded acceleration and turning."""

    dt = _valid_step(step_seconds)
    if not isinstance(player, PlayerMotion) or not isinstance(intent, MovementIntent):
        raise TypeError("player movement requires PlayerMotion and MovementIntent")
    if player.player_id != intent.player_id:
        raise ValueError("movement intent player must match the moving player")
    if not isinstance(pitch, Pitch):
        raise TypeError("movement requires explicit pitch bounds")
    if not pitch.contains(player.position) or not pitch.contains(intent.target_position):
        raise ValueError("player and movement target must be within the pitch")

    dx = intent.target_position.x_m - player.position.x_m
    dy = intent.target_position.y_m - player.position.y_m
    remaining = math.hypot(dx, dy)
    if remaining > 1e-12:
        desired_speed = min(
            player.limits.maximum_speed_mps,
            math.sqrt(2.0 * player.limits.acceleration_mps2 * remaining),
        )
        desired_vx = desired_speed * dx / remaining
        desired_vy = desired_speed * dy / remaining
    else:
        desired_vx = desired_vy = 0.0

    next_vx, next_vy = _approach(
        player.velocity_x_mps,
        player.velocity_y_mps,
        desired_vx,
        desired_vy,
        player.limits.acceleration_mps2 * dt,
    )
    speed = math.hypot(next_vx, next_vy)
    if speed > player.limits.maximum_speed_mps:
        scale = player.limits.maximum_speed_mps / speed
        next_vx *= scale
        next_vy *= scale

    # Trapezoidal integration avoids treating the new velocity as if it existed
    # for the whole step and keeps displacement within max_speed * dt.
    next_x = player.position.x_m + (player.velocity_x_mps + next_vx) * 0.5 * dt
    next_y = player.position.y_m + (player.velocity_y_mps + next_vy) * 0.5 * dt
    clamped = pitch.clamp(Position2D(next_x, next_y))
    if clamped.x_m != next_x:
        next_vx = 0.0
    if clamped.y_m != next_y:
        next_vy = 0.0
    if clamped.x_m <= 0.0 and next_vx < 0.0 or clamped.x_m >= pitch.length_m and next_vx > 0.0:
        next_vx = 0.0
    if clamped.y_m <= 0.0 and next_vy < 0.0 or clamped.y_m >= pitch.width_m and next_vy > 0.0:
        next_vy = 0.0

    face_target = intent.facing_target or intent.target_position
    face_dx = face_target.x_m - player.position.x_m
    face_dy = face_target.y_m - player.position.y_m
    if math.hypot(face_dx, face_dy) > 1e-12:
        desired_facing = math.atan2(face_dy, face_dx)
        turn = math.remainder(desired_facing - player.facing_radians, 2.0 * math.pi)
        turn = min(player.limits.turn_rate_rps * dt, max(-player.limits.turn_rate_rps * dt, turn))
        facing = math.remainder(player.facing_radians + turn, 2.0 * math.pi)
    else:
        facing = math.remainder(player.facing_radians, 2.0 * math.pi)

    return PlayerMotion(
        player.player_id,
        player.team_id,
        clamped,
        next_vx,
        next_vy,
        facing,
        player.limits,
    )


def resolve_movement_snapshot(
    players: tuple[PlayerMotion, ...],
    intents: tuple[MovementIntent, ...],
    step_seconds: float,
    pitch: Pitch = Pitch(),
) -> tuple[PlayerMotion, ...]:
    """Resolve all intents from the same immutable snapshot in canonical ID order."""

    if not isinstance(players, tuple) or not isinstance(intents, tuple):
        raise TypeError("movement snapshots and intents must be immutable tuples")
    player_ids = [item.player_id for item in players]
    intent_ids = [item.player_id for item in intents]
    if len(player_ids) != len(set(player_ids)) or len(intent_ids) != len(set(intent_ids)):
        raise ValueError("a movement snapshot cannot repeat a player or intent")
    if set(player_ids) != set(intent_ids):
        raise ValueError("each snapshot player must have exactly one movement intent")
    by_intent = {item.player_id: item for item in intents}
    return tuple(
        advance_player(player, by_intent[player.player_id], step_seconds, pitch)
        for player in sorted(players, key=lambda item: str(item.player_id))
    )


__all__ = [
    "MotionLimits",
    "MovementIntent",
    "Pitch",
    "PlayerMotion",
    "advance_player",
    "limits_from_profile",
    "resolve_movement_snapshot",
]
