"""Fixed-step ball translation, flight, bounce, ground roll and settling."""

from __future__ import annotations

import math
from dataclasses import dataclass

from games.touchline.esb.model import Position2D

BALL_RADIUS_M = 0.11
DEFAULT_STEP_SECONDS = 0.02


@dataclass(frozen=True)
class BallState:
    position: Position2D
    height_m: float
    velocity_x_mps: float
    velocity_y_mps: float
    velocity_z_mps: float

    def __post_init__(self) -> None:
        if not isinstance(self.position, Position2D):
            raise TypeError("ball state requires a pitch-plane position")
        for label, value in (
            ("height", self.height_m),
            ("x velocity", self.velocity_x_mps),
            ("y velocity", self.velocity_y_mps),
            ("z velocity", self.velocity_z_mps),
        ):
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError(f"ball {label} must be finite")
        if self.height_m < BALL_RADIUS_M - 1e-9:
            raise ValueError("ball centre cannot be below the ground plane")

    @property
    def horizontal_speed_mps(self) -> float:
        return math.hypot(self.velocity_x_mps, self.velocity_y_mps)

    @property
    def speed_mps(self) -> float:
        return math.sqrt(
            self.velocity_x_mps * self.velocity_x_mps
            + self.velocity_y_mps * self.velocity_y_mps
            + self.velocity_z_mps * self.velocity_z_mps
        )

    @property
    def is_airborne(self) -> bool:
        return self.height_m > BALL_RADIUS_M + 1e-9 or abs(self.velocity_z_mps) > 1e-9


@dataclass(frozen=True)
class BallPhysics:
    """Authored provisional physics constants; time step is simulation-owned."""

    step_seconds: float = DEFAULT_STEP_SECONDS
    gravity_mps2: float = 9.81
    air_drag_per_s: float = 0.015
    ground_friction_mps2: float = 0.55
    bounce_restitution: float = 0.44
    minimum_bounce_speed_mps: float = 0.65
    stop_speed_mps: float = 0.12

    def __post_init__(self) -> None:
        if (
            type(self.step_seconds) not in (int, float)
            or not math.isfinite(self.step_seconds)
            or not 0 < self.step_seconds <= 0.25
        ):
            raise ValueError("ball simulation step must be finite and in (0, 0.25] seconds")
        for label, value in (
            ("air drag", self.air_drag_per_s),
            ("ground friction", self.ground_friction_mps2),
            ("minimum bounce speed", self.minimum_bounce_speed_mps),
            ("stop speed", self.stop_speed_mps),
        ):
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError(f"ball {label} must be finite and non-negative")
        if (
            type(self.gravity_mps2) not in (int, float)
            or not math.isfinite(self.gravity_mps2)
            or self.gravity_mps2 <= 0
        ):
            raise ValueError("ball gravity must be positive and finite")
        if (
            type(self.bounce_restitution) not in (int, float)
            or not math.isfinite(self.bounce_restitution)
            or not 0 <= self.bounce_restitution <= 1
        ):
            raise ValueError("bounce restitution must be in [0, 1]")


DEFAULT_BALL_PHYSICS = BallPhysics()


def _ground_step(ball: BallState, physics: BallPhysics, dt: float) -> BallState:
    speed = ball.horizontal_speed_mps
    if speed <= physics.stop_speed_mps:
        return BallState(ball.position, BALL_RADIUS_M, 0.0, 0.0, 0.0)
    next_speed = max(0.0, speed - physics.ground_friction_mps2 * dt)
    mean_speed = (speed + next_speed) * 0.5
    distance = mean_speed * dt
    dx = ball.velocity_x_mps / speed * distance
    dy = ball.velocity_y_mps / speed * distance
    return BallState(
        Position2D(ball.position.x_m + dx, ball.position.y_m + dy),
        BALL_RADIUS_M,
        ball.velocity_x_mps * (next_speed / speed),
        ball.velocity_y_mps * (next_speed / speed),
        0.0,
    )


def advance_ball(ball: BallState, physics: BallPhysics = DEFAULT_BALL_PHYSICS) -> BallState:
    """Advance exactly one fixed physics step; no rendering clock is consulted."""

    if not isinstance(ball, BallState) or not isinstance(physics, BallPhysics):
        raise TypeError("ball integration requires BallState and BallPhysics")
    dt = physics.step_seconds
    if not ball.is_airborne:
        return _ground_step(ball, physics, dt)

    drag_scale = max(0.0, 1.0 - physics.air_drag_per_s * dt)
    vx = ball.velocity_x_mps * drag_scale
    vy = ball.velocity_y_mps * drag_scale
    x = ball.position.x_m + (ball.velocity_x_mps + vx) * 0.5 * dt
    y = ball.position.y_m + (ball.velocity_y_mps + vy) * 0.5 * dt
    z = ball.height_m + ball.velocity_z_mps * dt - 0.5 * physics.gravity_mps2 * dt * dt
    vz = ball.velocity_z_mps - physics.gravity_mps2 * dt

    if z <= BALL_RADIUS_M:
        impact_speed = math.sqrt(
            max(0.0, ball.velocity_z_mps * ball.velocity_z_mps
                + 2.0 * physics.gravity_mps2 * (ball.height_m - BALL_RADIUS_M))
        )
        rebound = impact_speed * physics.bounce_restitution
        if rebound <= physics.minimum_bounce_speed_mps:
            return BallState(Position2D(x, y), BALL_RADIUS_M, vx, vy, 0.0)
        return BallState(Position2D(x, y), BALL_RADIUS_M, vx, vy, rebound)

    return BallState(Position2D(x, y), z, vx, vy, vz)


def simulate_ball_ticks(
    initial: BallState,
    ticks: int,
    physics: BallPhysics = DEFAULT_BALL_PHYSICS,
) -> tuple[BallState, ...]:
    """Return the initial state and every deterministic fixed-step state."""

    if not isinstance(initial, BallState) or not isinstance(physics, BallPhysics):
        raise TypeError("ball trace requires BallState and BallPhysics")
    if type(ticks) is not int or ticks < 0:
        raise ValueError("ball tick count must be a non-negative integer")
    states = [initial]
    current = initial
    for _ in range(ticks):
        current = advance_ball(current, physics)
        states.append(current)
    return tuple(states)


def ticks_for_duration(duration_s: float, step_seconds: float) -> int:
    if type(duration_s) not in (int, float) or not math.isfinite(duration_s) or duration_s < 0:
        raise ValueError("simulation duration must be finite and non-negative")
    if type(step_seconds) not in (int, float) or not math.isfinite(step_seconds) or not 0 < step_seconds <= 0.25:
        raise ValueError("simulation step must be finite and in (0, 0.25] seconds")
    if duration_s == 0:
        return 0
    return max(1, math.ceil(duration_s / step_seconds - 1e-12))


__all__ = [
    "BALL_RADIUS_M",
    "DEFAULT_BALL_PHYSICS",
    "DEFAULT_STEP_SECONDS",
    "BallPhysics",
    "BallState",
    "advance_ball",
    "simulate_ball_ticks",
    "ticks_for_duration",
]
