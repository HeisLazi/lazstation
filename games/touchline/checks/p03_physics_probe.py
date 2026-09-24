"""Compare fixed-step error and runtime for the same small 11-player scenario."""

from __future__ import annotations

import argparse
import json
import math
from statistics import median
from time import perf_counter

from games.touchline.esb.match.ball import BallPhysics, BallState, advance_ball
from games.touchline.esb.match.spatial import (
    MotionLimits,
    MovementIntent,
    Pitch,
    PlayerMotion,
    resolve_movement_snapshot,
)
from games.touchline.esb.model import Position2D

RESOLUTIONS = (0.005, 0.01, 0.02, 0.05)
DEFAULT_SIMULATION_SECONDS = 2.0
DEFAULT_REPEATS = 5


def _initial_state():
    pitch = Pitch()
    players = tuple(
        PlayerMotion(
            f"player:probe-{index:02d}",
            "club:probe",
            Position2D(20.0 + (index % 4) * 7.0, 8.0 + (index // 4) * 16.0),
            0.0,
            0.0,
            0.0,
            MotionLimits(7.5 + (index % 3) * 0.5, 5.0 + (index % 4) * 0.4, 4.0),
        )
        for index in range(11)
    )
    intents = tuple(
        MovementIntent(
            player.player_id,
            Position2D(77.0 - (index % 3) * 3.0, 13.0 + (index % 5) * 8.0),
        )
        for index, player in enumerate(players)
    )
    ball = BallState(Position2D(52.5, 34.0), 1.4, 8.0, 2.2, 1.5)
    return pitch, players, intents, ball


def _run(step_seconds: float, simulation_seconds: float) -> tuple[BallState, tuple[PlayerMotion, ...]]:
    pitch, players, intents, ball = _initial_state()
    physics = BallPhysics(step_seconds=step_seconds)
    steps_float = simulation_seconds / step_seconds
    steps = round(steps_float)
    if not math.isclose(steps_float, steps, abs_tol=1e-9):
        raise ValueError("simulation duration must be divisible by each probed step")
    for _ in range(steps):
        ball = advance_ball(ball, physics)
        players = resolve_movement_snapshot(players, intents, step_seconds, pitch)
    return ball, players


def run_probe(simulation_seconds: float = DEFAULT_SIMULATION_SECONDS, repeats: int = DEFAULT_REPEATS) -> dict:
    if not math.isfinite(simulation_seconds) or simulation_seconds <= 0:
        raise ValueError("simulation seconds must be positive and finite")
    if type(repeats) is not int or repeats <= 0:
        raise ValueError("repeat count must be a positive integer")

    results = {}
    reference_ball, reference_players = _run(RESOLUTIONS[0], simulation_seconds)
    for step in RESOLUTIONS:
        _run(step, simulation_seconds)
        timings = []
        for _ in range(repeats):
            started = perf_counter()
            final_ball, final_players = _run(step, simulation_seconds)
            timings.append(perf_counter() - started)
        ball_error = math.dist(
            (final_ball.position.x_m, final_ball.position.y_m, final_ball.height_m),
            (reference_ball.position.x_m, reference_ball.position.y_m, reference_ball.height_m),
        )
        player_error = median(
            math.dist(
                (actual.position.x_m, actual.position.y_m),
                (reference.position.x_m, reference.position.y_m),
            )
            for actual, reference in zip(final_players, reference_players)
        )
        results[f"{step:.3f}"] = {
            "steps": round(simulation_seconds / step),
            "median_runtime_seconds": round(median(timings), 6),
            "ball_endpoint_error_vs_0.005_m": round(ball_error, 6),
            "median_player_endpoint_error_vs_0.005_m": round(player_error, 6),
        }
    return {
        "scenario": "11 moving players plus one airborne/rolling ball",
        "simulated_seconds": simulation_seconds,
        "repeats_per_resolution": repeats,
        "default_step_seconds": BallPhysics().step_seconds,
        "default_rate_hz": round(1.0 / BallPhysics().step_seconds),
        "results": results,
        "note": (
            "Runtime is a local microbenchmark; physics constants are provisional "
            "and UI frame rate is not part of the model."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=DEFAULT_SIMULATION_SECONDS)
    parser.add_argument("--repeats", type=int, default=DEFAULT_REPEATS)
    args = parser.parse_args()
    print(json.dumps(run_probe(args.seconds, args.repeats), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
