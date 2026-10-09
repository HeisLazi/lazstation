from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import math
import os
import subprocess
import sys
import unittest

from games.touchline.esb.content.proof_roster import PLAYER_DECISION_PAIR, PROOF_SQUADS
from games.touchline.esb.ids import PlayerId
from games.touchline.esb.match.actions import (
    PassIntent,
    PassKind,
    TouchOutcome,
    execute_pass,
    find_interception_window,
    receive_ball,
    resolve_interception_contest,
    trace_pass,
)
from games.touchline.esb.match.ball import (
    BALL_RADIUS_M,
    BallPhysics,
    BallState,
    advance_ball,
    simulate_ball_ticks,
)
from games.touchline.esb.match.spatial import (
    MovementIntent,
    MotionLimits,
    Pitch,
    PlayerMotion,
    advance_player,
    limits_from_profile,
    resolve_movement_snapshot,
)
from games.touchline.esb.match.scenarios import PassScenario, replay_pass_scenario
from games.touchline.esb.model import Position2D
from games.touchline.esb.randomness import RandomStreams
from games.touchline.esb.serialization import dumps, loads


def player(
    player_id: str,
    *,
    x: float = 0.0,
    y: float = 0.0,
    speed: float = 8.0,
    acceleration: float = 6.0,
    turn_rate: float = 4.0,
    vx: float = 0.0,
    vy: float = 0.0,
    facing: float = 0.0,
) -> PlayerMotion:
    return PlayerMotion(
        PlayerId(player_id),
        "club:test",
        Position2D(x, y),
        vx,
        vy,
        facing,
        MotionLimits(speed, acceleration, turn_rate),
    )


class MotionTests(unittest.TestCase):
    def test_profile_motion_limits_use_named_unit_measurements(self) -> None:
        profile = PLAYER_DECISION_PAIR[0]
        limits = limits_from_profile(profile)
        values = {item.name: item.value for item in profile.capabilities.measurements}
        expected_factor = (
            (0.80 + 0.20 * profile.readiness.match_readiness)
            * (1.0 - 0.25 * profile.readiness.accumulated_fatigue)
        )
        self.assertAlmostEqual(limits.condition_factor, expected_factor)
        self.assertAlmostEqual(limits.maximum_speed_mps, values["maximum_speed"] * expected_factor)
        self.assertAlmostEqual(limits.acceleration_mps2, values["acceleration"] * expected_factor)
        self.assertGreater(limits.turn_rate_rps, 0.0)

    def test_movement_bounds_acceleration_turning_and_distance(self) -> None:
        current = player("player:mover", facing=math.pi)
        dt = 0.02
        moved = advance_player(
            current,
            MovementIntent(current.player_id, Position2D(0.0, 10.0)),
            dt,
            Pitch(),
        )
        acceleration = math.hypot(moved.velocity_x_mps, moved.velocity_y_mps) / dt
        self.assertLessEqual(acceleration, current.limits.acceleration_mps2 + 1e-9)
        self.assertLessEqual(math.hypot(moved.velocity_x_mps, moved.velocity_y_mps), current.limits.maximum_speed_mps)
        travel = math.dist((moved.position.x_m, moved.position.y_m), (0.0, 0.0))
        self.assertLessEqual(travel, current.limits.maximum_speed_mps * dt)
        facing_change = abs(math.remainder(moved.facing_radians - current.facing_radians, 2 * math.pi))
        self.assertLessEqual(facing_change, current.limits.turn_rate_rps * dt + 1e-9)

    def test_boundary_is_clamped_and_outward_velocity_removed(self) -> None:
        pitch = Pitch(length_m=10.0, width_m=8.0)
        current = player("player:edge", x=9.95, y=4.0, vx=4.0)
        moved = advance_player(
            current,
            MovementIntent(current.player_id, Position2D(10.0, 4.0)),
            0.1,
            pitch,
        )
        self.assertEqual(moved.position, Position2D(10.0, 4.0))
        self.assertEqual(moved.velocity_x_mps, 0.0)

    def test_simultaneous_movement_is_input_order_independent_and_mirrors(self) -> None:
        pitch = Pitch(length_m=40.0, width_m=24.0)
        first = player("player:a", x=4.0, y=6.0, facing=0.3)
        second = player("player:b", x=11.0, y=17.0, facing=-0.8)
        intents = (
            MovementIntent(first.player_id, Position2D(15.0, 8.0)),
            MovementIntent(second.player_id, Position2D(3.0, 20.0)),
        )
        forward = resolve_movement_snapshot((first, second), intents, 0.1, pitch)
        reverse = resolve_movement_snapshot((second, first), tuple(reversed(intents)), 0.1, pitch)
        self.assertEqual(forward, reverse)

        mirrored_players = tuple(
            replace(
                item,
                position=Position2D(pitch.length_m - item.position.x_m, item.position.y_m),
                velocity_x_mps=-item.velocity_x_mps,
                facing_radians=math.remainder(math.pi - item.facing_radians, 2 * math.pi),
            )
            for item in (first, second)
        )
        mirrored_intents = tuple(
            MovementIntent(
                item.player_id,
                Position2D(pitch.length_m - item.target_position.x_m, item.target_position.y_m),
                None if item.facing_target is None else Position2D(
                    pitch.length_m - item.facing_target.x_m,
                    item.facing_target.y_m,
                ),
            )
            for item in intents
        )
        result = resolve_movement_snapshot(mirrored_players, mirrored_intents, 0.1, pitch)
        for original, reflected in zip(forward, result):
            self.assertEqual(original.player_id, reflected.player_id)
            self.assertAlmostEqual(reflected.position.x_m, pitch.length_m - original.position.x_m, places=10)
            self.assertAlmostEqual(reflected.position.y_m, original.position.y_m, places=10)
            self.assertAlmostEqual(reflected.velocity_x_mps, -original.velocity_x_mps, places=10)
            self.assertAlmostEqual(reflected.velocity_y_mps, original.velocity_y_mps, places=10)
            expected_facing = math.remainder(math.pi - original.facing_radians, 2 * math.pi)
            self.assertAlmostEqual(reflected.facing_radians, expected_facing, places=10)


class BallPhysicsTests(unittest.TestCase):
    def test_spatial_domain_imports_do_not_open_files_or_load_terminal_code(self) -> None:
        script = r'''
import builtins, importlib, io, pathlib, sys
def blocked(*args, **kwargs):
    raise AssertionError("spatial domain import attempted file I/O")
builtins.open = blocked
io.open = blocked
pathlib.Path.open = blocked
for module in (
    "games.touchline.esb.match.spatial", "games.touchline.esb.match.ball",
    "games.touchline.esb.match.actions", "games.touchline.esb.match.scenarios",
):
    importlib.import_module(module)
assert "curses" not in sys.modules
assert "termstation_ui" not in sys.modules
assert not any(name.startswith("termstation.") for name in sys.modules)
'''
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[3],
            text=True,
            capture_output=True,
            check=True,
            env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
        )
        self.assertEqual(result.stdout, "")

    def test_ball_state_rejects_non_finite_and_below_ground_values(self) -> None:
        with self.assertRaises(ValueError):
            BallState(Position2D(0.0, 0.0), float("nan"), 0.0, 0.0, 0.0)
        with self.assertRaises(ValueError):
            BallState(Position2D(0.0, 0.0), 0.0, 0.0, 0.0, 0.0)
        with self.assertRaises(ValueError):
            BallPhysics(gravity_mps2=0.0)

    def test_airborne_ball_bounces_then_settles_without_negative_height(self) -> None:
        physics = BallPhysics(step_seconds=0.02)
        ball = BallState(Position2D(20.0, 20.0), 1.0, 4.0, 0.0, 0.0)
        trace = simulate_ball_ticks(ball, 400, physics)
        self.assertTrue(all(item.height_m >= BALL_RADIUS_M for item in trace))
        self.assertTrue(any(item.velocity_z_mps > 1.0 for item in trace[1:]))
        self.assertLess(trace[-1].speed_mps, physics.stop_speed_mps)
        self.assertAlmostEqual(trace[-1].height_m, BALL_RADIUS_M)

    def test_fixed_step_resolution_converges_for_a_ballistic_flight(self) -> None:
        initial = BallState(Position2D(0.0, 0.0), 1.1, 8.0, 0.0, 0.0)
        endpoints = []
        for dt in (0.005, 0.01, 0.02, 0.05):
            physics = BallPhysics(step_seconds=dt)
            endpoints.append(simulate_ball_ticks(initial, round(0.5 / dt), physics)[-1])
        reference = endpoints[0]
        for endpoint in endpoints[1:]:
            self.assertLess(abs(endpoint.height_m - reference.height_m), 0.20)
            self.assertLess(abs(endpoint.position.x_m - reference.position.x_m), 0.10)


class PassAndReceivingTests(unittest.TestCase):
    def test_pass_is_explicit_reproducible_and_carries_a_traceable_travel_time(self) -> None:
        passer = PROOF_SQUADS[0].players[10]
        ball = BallState(Position2D(20.0, 30.0), BALL_RADIUS_M, 0.0, 0.0, 0.0)
        intent = PassIntent(
            PassKind.CHIPPED,
            Position2D(42.0, 35.0),
            intended_receiver_id=PROOF_SQUADS[0].players[14].player_id,
        )
        first = execute_pass(passer, ball, intent, RandomStreams.seeded(901).stream("football"))
        second = execute_pass(passer, ball, intent, RandomStreams.seeded(901).stream("football"))
        self.assertEqual(first, second)
        self.assertGreater(first.planned_travel_time_s, 0.0)
        self.assertEqual(first.intended_receiver_id, intent.intended_receiver_id)
        self.assertNotEqual(first.actual_target, intent.target_position)
        trace = trace_pass(first)
        self.assertGreater(len(trace), 2)
        self.assertEqual(trace[0], ball)
        self.assertTrue(all(item.height_m >= BALL_RADIUS_M for item in trace))
        with self.assertRaises(ValueError):
            trace_pass(first, physics=BallPhysics(step_seconds=0.02, gravity_mps2=9.7))

        low_bounce = BallState(Position2D(20.0, 30.0), 0.18, 0.0, 0.0, 0.2)
        low_delivery = execute_pass(
            passer,
            low_bounce,
            intent,
            RandomStreams.seeded(902).stream("football"),
        )
        self.assertEqual(low_delivery.launch_state.height_m, low_bounce.height_m)

    def test_pass_intent_requires_a_receiver_or_an_area(self) -> None:
        with self.assertRaises(ValueError):
            PassIntent(PassKind.DRIVEN, Position2D(10.0, 10.0))
        with self.assertRaises(ValueError):
            PassIntent(
                PassKind.DRIVEN,
                Position2D(10.0, 10.0),
                intended_receiver_id=PlayerId("player:r"),
                intended_area_id="area:box",
            )

    def test_named_passing_capabilities_reduce_seeded_execution_error(self) -> None:
        passer = PROOF_SQUADS[0].players[10]

        def with_passing_quality(value: float):
            capabilities = tuple(
                replace(item, normalized_value=value)
                if item.name in {"long_passing", "distribution"}
                else item
                for item in passer.capabilities.capabilities
            )
            return replace(passer, capabilities=replace(passer.capabilities, capabilities=capabilities))

        target = Position2D(75.0, 40.0)
        ball = BallState(Position2D(20.0, 30.0), BALL_RADIUS_M, 0.0, 0.0, 0.0)
        intent = PassIntent(PassKind.FLOATED, target, intended_area_id="area:far-side")
        weak = execute_pass(with_passing_quality(0.2), ball, intent, RandomStreams.seeded(313).stream("football"))
        strong = execute_pass(with_passing_quality(0.95), ball, intent, RandomStreams.seeded(313).stream("football"))
        self.assertGreater(weak.execution_quality, 0.0)
        self.assertGreater(strong.execution_quality, weak.execution_quality)
        self.assertLess(strong.target_error_m, weak.target_error_m)

    def test_pass_scenario_replays_delivery_flight_and_contest(self) -> None:
        passer = PROOF_SQUADS[0].players[10]
        target = Position2D(28.0, 24.0)
        scenario = PassScenario(
            744,
            passer,
            BallState(Position2D(18.0, 24.0), BALL_RADIUS_M, 0.0, 0.0, 0.0),
            PassIntent(PassKind.DRIVEN, target, intended_area_id="area:central"),
            (player("player:opponent", x=24.0, y=24.0, speed=7.0, acceleration=5.0),),
        )
        checkpoint = loads(dumps(scenario), PassScenario)
        first = replay_pass_scenario(checkpoint)
        second = replay_pass_scenario(scenario)
        self.assertEqual(first, second)
        self.assertEqual(loads(dumps(first), type(first)), first)

    def test_controlled_touch_and_knockdown_preserve_contact_position(self) -> None:
        skilled = PROOF_SQUADS[1].players[14]
        body = player(str(skilled.player_id), x=12.0, y=12.0)
        slow_ground_ball = BallState(Position2D(12.2, 12.0), BALL_RADIUS_M, 0.3, 0.0, 0.0)
        control = receive_ball(skilled, body, slow_ground_ball, RandomStreams.seeded(5).stream("football"))
        self.assertIs(control.outcome, TouchOutcome.CONTROLLED)
        self.assertEqual(control.ball_after.position, slow_ground_ball.position)
        self.assertIn("controlled", control.explanation.lower())

        facing_away = replace(body, facing_radians=math.pi)
        turned_away = receive_ball(
            skilled,
            facing_away,
            slow_ground_ball,
            RandomStreams.seeded(5).stream("football"),
        )
        assert control.control_margin is not None and turned_away.control_margin is not None
        self.assertGreater(control.control_margin, turned_away.control_margin)

        aerial = BallState(Position2D(12.2, 12.0), 1.25, 5.0, 0.0, -1.0)
        knockdown = receive_ball(skilled, body, aerial, RandomStreams.seeded(6).stream("football"))
        self.assertIs(knockdown.outcome, TouchOutcome.KNOCKDOWN)
        self.assertEqual(knockdown.ball_after.position, aerial.position)
        self.assertEqual(knockdown.ball_after.height_m, aerial.height_m)
        self.assertLess(knockdown.ball_after.velocity_z_mps, 0.0)

        low_bounce = BallState(Position2D(12.2, 12.0), 0.22, 0.6, 0.0, -0.25)
        low_touch = receive_ball(skilled, body, low_bounce, RandomStreams.seeded(7).stream("football"))
        self.assertIs(low_touch.outcome, TouchOutcome.KNOCKDOWN)
        self.assertEqual(low_touch.ball_after.height_m, low_bounce.height_m)

    def test_uncontrolled_deflection_changes_velocity_but_not_ball_location(self) -> None:
        less_skilled = PROOF_SQUADS[0].players[0]
        body = player(str(less_skilled.player_id), x=5.0, y=5.0)
        fast_ball = BallState(Position2D(5.2, 5.0), BALL_RADIUS_M, 15.0, 0.0, 0.0)
        result = receive_ball(less_skilled, body, fast_ball, RandomStreams.seeded(11).stream("football"))
        self.assertIs(result.outcome, TouchOutcome.DEFLECTION)
        self.assertEqual(result.ball_after.position, fast_ball.position)
        self.assertNotEqual(result.ball_after.velocity_x_mps, fast_ball.velocity_x_mps)

    def test_no_contact_returns_unmodified_ball_without_random_draw(self) -> None:
        profile = PROOF_SQUADS[0].players[0]
        body = player(str(profile.player_id), x=0.0, y=0.0)
        ball = BallState(Position2D(10.0, 10.0), BALL_RADIUS_M, 0.0, 0.0, 0.0)
        stream = RandomStreams.seeded(99).stream("football")
        before = replace(stream)
        result = receive_ball(profile, body, ball, stream)
        self.assertIs(result.outcome, TouchOutcome.NO_CONTACT)
        self.assertEqual(result.ball_after, ball)
        self.assertEqual(stream, before)


class InterceptionTests(unittest.TestCase):
    def test_missed_arrival_and_illegal_height_do_not_create_interceptions(self) -> None:
        slow_defender = player("player:slow", x=0.0, y=6.0, speed=5.0, acceleration=3.0)
        passing_ball = BallState(Position2D(0.0, 0.0), BALL_RADIUS_M, 18.0, 0.0, 0.0)
        self.assertIsNone(
            find_interception_window(
                slow_defender,
                passing_ball,
                max_time_s=0.5,
                physics=BallPhysics(step_seconds=0.02),
                reach_radius_m=0.4,
                legal_height_m=0.8,
            )
        )

        high_defender = player("player:high", x=0.0, y=0.0)
        high_ball = BallState(Position2D(0.0, 0.0), 3.0, 0.0, 0.0, 0.0)
        self.assertIsNone(
            find_interception_window(
                high_defender,
                high_ball,
                max_time_s=0.1,
                physics=BallPhysics(step_seconds=0.02),
                legal_height_m=1.8,
            )
        )

    def test_reachable_window_occurs_after_real_bounded_travel(self) -> None:
        chaser = player("player:chaser", x=0.0, y=0.0, speed=7.0, acceleration=6.0)
        stationary = BallState(Position2D(3.0, 0.0), BALL_RADIUS_M, 0.0, 0.0, 0.0)
        window = find_interception_window(
            chaser,
            stationary,
            max_time_s=2.0,
            physics=BallPhysics(step_seconds=0.02),
            reach_radius_m=0.5,
        )
        self.assertIsNotNone(window)
        assert window is not None
        self.assertGreater(window.arrival_time_s, 0.0)
        player_travel = math.dist(
            (chaser.position.x_m, chaser.position.y_m),
            (window.player_position.x_m, window.player_position.y_m),
        )
        ball_separation = math.dist(
            (window.player_position.x_m, window.player_position.y_m),
            (window.ball_position.x_m, window.ball_position.y_m),
        )
        self.assertLessEqual(player_travel, chaser.limits.maximum_speed_mps * window.arrival_time_s + 1e-9)
        self.assertLessEqual(ball_separation, window.reach_radius_m)

    def test_contested_tie_is_permutation_invariant_and_seed_fair(self) -> None:
        one = player("player:one", x=10.0, y=8.0, speed=7.0, acceleration=5.0)
        two = player("player:two", x=10.0, y=8.0, speed=7.0, acceleration=5.0)
        ball = BallState(Position2D(10.0, 8.0), BALL_RADIUS_M, 0.0, 0.0, 0.0)
        physics = BallPhysics(step_seconds=0.02)
        wins = {one.player_id: 0, two.player_id: 0}
        for seed in range(500):
            stream_a = RandomStreams.seeded(seed).stream("football")
            stream_b = RandomStreams.seeded(seed).stream("football")
            forward = resolve_interception_contest((one, two), ball, stream_a, max_time_s=0.5, physics=physics)
            reverse = resolve_interception_contest((two, one), ball, stream_b, max_time_s=0.5, physics=physics)
            self.assertEqual(forward, reverse)
            self.assertIn(forward.winner_id, wins)
            wins[forward.winner_id] += 1
        proportion = wins[one.player_id] / sum(wins.values())
        self.assertGreater(proportion, 0.35)
        self.assertLess(proportion, 0.65)


if __name__ == "__main__":
    unittest.main()
