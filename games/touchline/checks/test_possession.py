"""Mechanism-level proofs for P04 continuous open-play decisions."""

from __future__ import annotations

from dataclasses import replace
import pathlib
import subprocess
import sys
import unittest

from games.touchline.esb.content.proof_roster import PLAYER_DECISION_PAIR, PROOF_SQUADS
from games.touchline.esb.ids import MatchId
from games.touchline.esb.match.actions import PassIntent, PassKind, execute_pass
from games.touchline.esb.match.ball import BALL_RADIUS_M, BallState
from games.touchline.esb.match.possession import (
    ActionKind, Decision, FeasibleAction, PlayerState, choose_action, create_state,
    execute_action, generate_feasible_actions, perceive, step_open_play,
)
from games.touchline.esb.match.spatial import MotionLimits, Pitch, PlayerMotion
from games.touchline.esb.model import Position2D
from games.touchline.esb.randomness import RandomStreams


def actor(profile, team, x, y, *, facing=0.0):
    limits = MotionLimits(8.0, 6.0)
    motion = PlayerMotion(profile.player_id, team, Position2D(x, y), 0.0, 0.0, facing, limits)
    return PlayerState(profile, motion, team)


def scenario(seed=771):
    home, away = PROOF_SQUADS
    return create_state(
        MatchId("match:p04-test"),
        (actor(home.players[10], "home", 35, 34),
         actor(home.players[11], "home", 43, 34),
         actor(away.players[10], "away", 39, 35)),
        BallState(Position2D(35, 34), BALL_RADIUS_M, 0, 0, 0),
        home.players[10].player_id, RandomStreams.seeded(seed),
        pitch=Pitch(),
    )


class PossessionDecisionTests(unittest.TestCase):
    def test_fresh_process_replay_fingerprint_is_identical(self):
        root = pathlib.Path(__file__).resolve().parents[3]
        env = {**__import__("os").environ, "PYTHONDONTWRITEBYTECODE": "1"}
        command = [sys.executable, "-m", "games.touchline.checks.p04_determinism_probe", "--seed", "9142"]
        first = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True, check=True)
        second = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True, check=True)
        self.assertEqual(first.stdout, second.stdout)

    def test_domain_import_has_no_filesystem_or_terminal_side_effect(self):
        script = r'''
import builtins, importlib, io, pathlib, sys
def blocked(*args, **kwargs): raise AssertionError("domain import performed file I/O")
builtins.open = blocked
io.open = blocked
pathlib.Path.open = blocked
importlib.import_module("games.touchline.esb.match.possession")
assert "curses" not in sys.modules
assert "termstation_ui" not in sys.modules
assert not any(name.startswith("termstation.") for name in sys.modules)
'''
        result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                                check=True, cwd=pathlib.Path(__file__).resolve().parents[3],
                                env={**__import__("os").environ, "PYTHONDONTWRITEBYTECODE": "1"})
        self.assertEqual(result.stdout, "")

    def test_perception_generation_choice_and_execution_are_distinct(self):
        state = scenario()
        pid = state.possession_id
        observation = perceive(state, pid)
        feasible = generate_feasible_actions(state, pid)
        self.assertEqual(observation.observer_id, pid)
        self.assertTrue(observation.visible_players)
        self.assertTrue(any(a.kind is ActionKind.PASS for a in feasible))
        self.assertTrue(all(a.actor_id == pid for a in feasible))
        choice = choose_action(state, pid, feasible)
        before_tick, before_events = state.clock.tick, len(state.events)
        self.assertIn(choice.chosen, feasible)
        execute_action(state, choice)
        self.assertGreaterEqual(state.clock.tick, before_tick)
        self.assertGreater(len(state.events), before_events)
        self.assertEqual(len(state.action_log), 1)

    def test_scanning_recognition_does_not_change_pass_execution_profile(self):
        skilled, limited = PLAYER_DECISION_PAIR
        self.assertEqual(
            {c.name: c.normalized_value for c in skilled.capabilities.capabilities
             if c.name not in ("scanning", "decision_quality", "anticipation")},
            {c.name: c.normalized_value for c in limited.capabilities.capabilities
             if c.name not in ("scanning", "decision_quality", "anticipation")},
        )
        intent = PassIntent(PassKind.DRIVEN, Position2D(25, 30), intended_area_id="area:p04-proof")
        ball = BallState(Position2D(15, 30), BALL_RADIUS_M, 0, 0, 0)
        delivery_a = execute_pass(skilled, ball, intent, RandomStreams.seeded(177).stream("football"))
        delivery_b = execute_pass(limited, ball, intent, RandomStreams.seeded(177).stream("football"))
        self.assertEqual(delivery_a.execution_quality, delivery_b.execution_quality)
        self.assertEqual(delivery_a.actual_target, delivery_b.actual_target)
        self.assertEqual(delivery_a.launch_state, delivery_b.launch_state)
        # Low scanning hides the pass choice when the same teammate is distant;
        # feasible action generation does not change either profile's technique.
        home = PROOF_SQUADS[0]
        receiver = home.players[12]
        peer = replace(limited, capabilities=replace(limited.capabilities, capabilities=tuple(
            replace(c, normalized_value=0.2) if c.name == "scanning" else c
            for c in limited.capabilities.capabilities)))
        state_a = create_state(MatchId("match:scan-a"),
            (actor(skilled, "home", 15, 34), actor(receiver, "home", 40, 34),
             actor(PROOF_SQUADS[1].players[10], "away", 70, 34)),
            BallState(Position2D(15, 34), BALL_RADIUS_M, 0, 0, 0), skilled.player_id,
            RandomStreams.seeded(1))
        state_b = create_state(MatchId("match:scan-b"),
            (actor(peer, "home", 15, 34), actor(receiver, "home", 40, 34),
             actor(PROOF_SQUADS[1].players[10], "away", 70, 34)),
            BallState(Position2D(15, 34), BALL_RADIUS_M, 0, 0, 0), peer.player_id,
            RandomStreams.seeded(1))
        self.assertIn(ActionKind.PASS, perceive(state_a, skilled.player_id).recognized_options)
        self.assertNotIn(ActionKind.PASS, perceive(state_b, peer.player_id).recognized_options)
        self.assertEqual(
            {c.name: c.normalized_value for c in skilled.capabilities.capabilities}["short_passing"],
            {c.name: c.normalized_value for c in peer.capabilities.capabilities}["short_passing"],
        )

    def test_decision_quality_changes_option_evaluation_not_execution(self):
        low, high = PLAYER_DECISION_PAIR
        home = PROOF_SQUADS[0]
        teammate = home.players[12]
        options = (
            FeasibleAction(ActionKind.CARRY, low.player_id, target=Position2D(18, 34),
                           provisional_value=.48, explanation="lower-value lane"),
            FeasibleAction(ActionKind.MOVE, low.player_id, target=Position2D(20, 34),
                           provisional_value=.52, explanation="higher-value lane"),
        )
        states = []
        for profile, tag in ((low, "low"), (high, "high")):
            states.append(create_state(MatchId(f"match:decision-{tag}"),
                (actor(profile, "home", 15, 34), actor(teammate, "home", 30, 34),
                 actor(PROOF_SQUADS[1].players[10], "away", 70, 34)),
                BallState(Position2D(15, 34), BALL_RADIUS_M, 0, 0, 0), profile.player_id,
                RandomStreams.seeded(550)))
        low_choice = choose_action(states[0], low.player_id, options).chosen
        high_options = tuple(replace(o, actor_id=high.player_id) for o in options)
        high_choice = choose_action(states[1], high.player_id, high_options).chosen
        self.assertEqual(high_choice.provisional_value, .52)
        self.assertEqual(
            {c.name: c.normalized_value for c in low.capabilities.capabilities}["short_passing"],
            {c.name: c.normalized_value for c in high.capabilities.capabilities}["short_passing"],
        )
        self.assertIn(low_choice, options)

    def test_player_input_order_and_replay_seed_do_not_change_step(self):
        first, second = scenario(seed=44), scenario(seed=44)
        second.players = dict(reversed(tuple(second.players.items())))
        first.random_streams = RandomStreams.seeded(99)
        second.random_streams = RandomStreams.seeded(99)
        one = step_open_play(first)
        two = step_open_play(second)
        self.assertEqual(tuple(d.chosen for d in one), tuple(d.chosen for d in two))
        self.assertEqual(first.ball, second.ball)
        self.assertEqual(first.possession_id, second.possession_id)
        self.assertEqual([(e.kind, e.match_tick, e.payload_json, e.outcome_json) for e in first.events],
                         [(e.kind, e.match_tick, e.payload_json, e.outcome_json) for e in second.events])

    def test_pass_flight_has_chronological_contact_and_regain(self):
        state = scenario(seed=24)
        passer = state.players[state.possession_id]
        receiver = next(p for p in state.players.values() if p.team_id == "home" and p.profile.player_id != passer.profile.player_id)
        # Isolate intended reception/lineage; opposition contests are exercised
        # separately through the open-play challenge stage.
        state.players = {key: value for key, value in state.players.items() if value.team_id == "home"}
        intent = PassIntent(PassKind.DRIVEN, receiver.motion.position,
                            intended_receiver_id=receiver.profile.player_id)
        action = FeasibleAction(ActionKind.PASS, passer.profile.player_id,
                                receiver.profile.player_id, receiver.motion.position, intent, .8, "test pass")
        decision = Decision(passer.profile.player_id, perceive(state, passer.profile.player_id), (action,), action, "fixed test")
        execute_action(state, decision)
        kinds = [event.kind for event in state.events]
        self.assertIn("pass", kinds)
        self.assertIn("ball_contact", kinds)
        self.assertTrue(any(kind in ("possession_regained", "possession_controlled") for kind in kinds))
        self.assertEqual([e.sequence for e in state.events], list(range(len(state.events))))
        self.assertLess(kinds.index("pass"), kinds.index("ball_contact"))
        self.assertIsNotNone(state.possession_id)
        self.assertEqual(state.statistics.get("passes"), 1)
        self.assertEqual(state.action_log[0].tick, 0)
        self.assertEqual(state.action_log[0].outcome, "launched")
        pass_event = next(e for e in state.events if e.kind == "pass")
        self.assertEqual(state.shot_assist_event_id, pass_event.event_id)
        self.assertEqual(state.shot_assist_player_id, passer.profile.player_id)
        # Move this same receiver into a near-box proof position while retaining
        # the causal pass; the shot must carry that lineage even if it misses.
        moved_profile = state.players[receiver.profile.player_id]
        moved_motion = replace(moved_profile.motion, position=Position2D(90, 34),
                               velocity_x_mps=0.0, velocity_y_mps=0.0)
        state.players[receiver.profile.player_id] = replace(moved_profile, motion=moved_motion)
        state.ball = BallState(Position2D(90, 34), BALL_RADIUS_M, 0, 0, 0)
        shot = FeasibleAction(ActionKind.SHOT, receiver.profile.player_id,
            target=Position2D(105, 34), provisional_value=.17, explanation="lineage proof")
        shot_decision = Decision(receiver.profile.player_id,
            perceive(state, receiver.profile.player_id), (shot,), shot, "lineage fixture")
        execute_action(state, shot_decision)
        shot_event = next(e for e in state.events if e.kind == "shot")
        self.assertEqual(shot_event.parent_event_id, pass_event.event_id)
        self.assertEqual(shot_event.payload["assist_event_id"], str(pass_event.event_id))
        self.assertEqual(shot_event.payload["assist_player_id"], str(passer.profile.player_id))

    def test_shot_quality_finishing_keeper_and_score_projection_reconcile(self):
        attacker = PROOF_SQUADS[0].players[14]
        keeper = PROOF_SQUADS[1].players[0]
        observed = []
        for seed in range(12):
            state = create_state(MatchId(f"match:p04-shot-{seed}"),
                (actor(attacker, "home", 90, 34), actor(keeper, "away", 103, 34)),
                BallState(Position2D(90, 34), BALL_RADIUS_M, 0, 0, 0), attacker.player_id,
                RandomStreams.seeded(seed))
            shot = FeasibleAction(ActionKind.SHOT, attacker.player_id,
                target=Position2D(105, 34), provisional_value=.18,
                explanation="fixed near-box shot-quality estimate")
            decision = Decision(attacker.player_id, perceive(state, attacker.player_id),
                                (shot,), shot, "mechanism fixture")
            execute_action(state, decision)
            shot_event = next(e for e in state.events if e.kind == "shot")
            payload, outcome = shot_event.payload, shot_event.outcome
            self.assertEqual(payload["shot_quality_estimate"], .18)
            self.assertEqual(payload["finishing"], next(
                c.normalized_value for c in attacker.capabilities.capabilities if c.name == "finishing"))
            self.assertGreater(payload["keeper_distance_m"], 0)
            self.assertEqual(outcome["saved"], state.statistics.get("saves", 0) == 1)
            self.assertEqual(state.home_score + state.away_score, state.statistics.get("goals", 0))
            self.assertEqual(state.statistics.get("shots"), 1)
            self.assertLessEqual(state.statistics.get("saves", 0), state.statistics["shots"])
            observed.append((outcome["saved"], "goal" in [e.kind for e in state.events],
                             "rebound" in [e.kind for e in state.events]))
        self.assertTrue(any(saved or goal or rebound for saved, goal, rebound in observed))

    def test_opponent_can_intercept_pass_and_continue_with_regained_possession(self):
        passer, receiver = PROOF_SQUADS[0].players[10], PROOF_SQUADS[0].players[11]
        defender = PROOF_SQUADS[1].players[10]
        state = create_state(MatchId("match:p04-intercept"),
            (actor(passer, "home", 20, 34), actor(receiver, "home", 50, 34),
             actor(defender, "away", 35, 34)),
            BallState(Position2D(20, 34), BALL_RADIUS_M, 0, 0, 0), passer.player_id,
            RandomStreams.seeded(313))
        intent = PassIntent(PassKind.DRIVEN, Position2D(50, 34),
                            intended_receiver_id=receiver.player_id)
        option = FeasibleAction(ActionKind.PASS, passer.player_id, receiver.player_id,
                                Position2D(50, 34), intent, .8, "interception fixture")
        decision = Decision(passer.player_id, perceive(state, passer.player_id),
                            (option,), option, "fixed contested pass")
        execute_action(state, decision)
        self.assertEqual(state.possession_id, defender.player_id)
        regain = next(e for e in state.events if e.kind == "possession_regained")
        self.assertEqual(regain.payload["from_team"], "home")
        self.assertEqual(regain.payload["actor_id"], str(defender.player_id))
        self.assertEqual(state.statistics.get("recoveries"), 1)

    def test_uncontrolled_ball_remains_live_for_next_decision_round(self):
        state = scenario(seed=4)
        state.possession_id = None
        state.possession_team_id = None
        state.ball = BallState(Position2D(38, 35), BALL_RADIUS_M, 2.0, 0.0, 0.0)
        original_tick = state.clock.tick
        state.random_streams = RandomStreams.seeded(98)
        decisions = step_open_play(state)
        self.assertTrue(decisions)
        self.assertGreaterEqual(state.clock.tick, original_tick)
        self.assertTrue(state.action_log)
        if state.possession_id is None:
            self.assertTrue(state.ball.speed_mps >= 0)

    def test_close_challenge_is_a_capability_based_local_contest(self):
        state = scenario(seed=21)
        away = next(p for p in state.players.values() if p.team_id == "away")
        state.players = {state.possession_id: state.players[state.possession_id], away.profile.player_id: away}
        state.players[away.profile.player_id] = replace(away, motion=replace(
            away.motion, position=Position2D(36.5, 34.0)))
        decisions = step_open_play(state)
        challenge_choice = next(d for d in decisions if d.actor_id == away.profile.player_id)
        self.assertEqual(challenge_choice.chosen.kind, ActionKind.CHALLENGE)
        challenge = next((e for e in state.events if e.kind == "challenge_contest"), None)
        self.assertIsNotNone(challenge)
        self.assertIn("defensive_positioning", challenge.payload)
        self.assertIn("pressing_judgment", challenge.payload)
        self.assertIn("carrier_control", challenge.payload)
        if challenge.outcome["won"]:
            self.assertEqual(state.possession_id, away.profile.player_id)
        else:
            self.assertEqual(state.possession_id, state.players[next(
                key for key, player in state.players.items() if player.team_id == "home")].profile.player_id)


if __name__ == "__main__":
    unittest.main()
