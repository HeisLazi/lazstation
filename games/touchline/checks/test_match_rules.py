"""Mechanism tests for configurable P05 match rules and transitions."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
import os
import pathlib
import subprocess
import sys
import unittest

from games.touchline.esb.content.proof_roster import PLAYER_DECISION_PAIR, PROOF_SQUADS
from games.touchline.esb.events import EventEnvelope
from games.touchline.esb.ids import EventId, MatchId, PlayerId
from games.touchline.esb.match.actions import PassDelivery, PassKind
from games.touchline.esb.match.ball import BALL_RADIUS_M, BallState
from games.touchline.esb.match.engine import (
    CardKind, MatchPeriod, MatchPhase, RestartKind, TeamSheet,
    _after_events, _award_restart, _emit, _handle_out_of_play, _offside_candidates,
    _process_challenges, _process_offside, _send_off, create_match,
    run_to_completion, step_match, substitute,
)
from games.touchline.esb.match.possession import (
    PlayerState, _finish_flight, choose_action, generate_feasible_actions,
)
from games.touchline.esb.match.rules import MatchRules, STANDARD_RULES
from games.touchline.esb.match.spatial import PlayerMotion, limits_from_profile
from games.touchline.esb.model import Position2D
from games.touchline.esb.time import MatchClock


LINEUP_INDEXES = (0, 2, 3, 5, 6, 10, 13)
HOME_POSITIONS = ((4, 34), (15, 20), (15, 48), (28, 9), (28, 59),
                  (52.5, 34), (40, 34))
AWAY_POSITIONS = ((101, 34), (90, 20), (90, 48), (78, 9), (78, 59),
                  (62, 34), (70, 34))


def player_state(profile, team_id, position):
    point = Position2D(*position)
    motion = PlayerMotion(profile.player_id, team_id, point, 0.0, 0.0, 0.0,
                          limits_from_profile(profile))
    return PlayerState(profile, motion, team_id)


def sheets(*, home_count=7, away_count=7):
    result = []
    for team_id, squad, positions, count in (
        ("home", PROOF_SQUADS[0], HOME_POSITIONS, home_count),
        ("away", PROOF_SQUADS[1], AWAY_POSITIONS, away_count),
    ):
        lineup = tuple(player_state(squad.players[index], team_id, positions[offset])
                       for offset, index in enumerate(LINEUP_INDEXES[:count]))
        bench = tuple(profile for index, profile in enumerate(squad.players)
                      if index not in LINEUP_INDEXES[:count])[:3]
        unavailable = (squad.players[15].player_id,)
        result.append(TeamSheet(team_id, lineup, bench, unavailable))
    return tuple(result)


def new_match(*, rules=STANDARD_RULES, home_count=7, away_count=7, seed=881,
              match_tag="rules-test"):
    home, away = sheets(home_count=home_count, away_count=away_count)
    return create_match(home, away, rules=rules, seed=seed,
                        match_id=MatchId(f"match:{match_tag}:{seed}"))


def move_player(state, player_id, point):
    player = state.play.players[player_id]
    motion = replace(player.motion, position=point, velocity_x_mps=0.0, velocity_y_mps=0.0)
    state.play.players[player_id] = replace(player, motion=motion)


def envelope(state, sequence, kind, payload, *, tick=1, parent=None):
    return EventEnvelope(
        EventId(f"event:{state.match_id}:test:{sequence}"), "match", str(state.match_id),
        sequence, kind, match_id=state.match_id, match_tick=tick,
        parent_event_id=parent,
        payload_json=json.dumps({"actor_id": None, **payload}, sort_keys=True),
        outcome_json="{}",
    )


class MatchRuleTests(unittest.TestCase):
    def test_fresh_process_import_is_headless_and_match_probe_repeats_exactly(self):
        root = pathlib.Path(__file__).resolve().parents[3]
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        script = r'''
import builtins, importlib, io, pathlib, sys
def blocked(*args, **kwargs): raise AssertionError("P05 domain import performed file I/O")
builtins.open = blocked
io.open = blocked
pathlib.Path.open = blocked
importlib.import_module("games.touchline.esb.match.engine")
assert "curses" not in sys.modules
assert "termstation_ui" not in sys.modules
assert not any(name.startswith("termstation.") for name in sys.modules)
'''
        subprocess.run([sys.executable, "-c", script], cwd=root, env=env,
                       capture_output=True, text=True, check=True)
        command = [sys.executable, "-m", "games.touchline.checks.p05_match_probe",
                   "--seed", "9142"]
        first = subprocess.run(command, cwd=root, env=env, capture_output=True,
                               text=True, check=True)
        second = subprocess.run(command, cwd=root, env=env, capture_output=True,
                                text=True, check=True)
        self.assertEqual(first.stdout, second.stdout)
        self.assertEqual(first.stdout.count('"match_finished"'), 1)

    def test_rules_are_immutable_versioned_and_reject_unknown_or_invalid_overrides(self):
        changed = STANDARD_RULES.with_overrides(
            "rules:short-cup-v1", half_duration_ticks=30,
            extra_time_duration_ticks=10, offside_enabled=False,
            substitutions_allowed=7, foul_probability_per_challenge=0.0)
        self.assertEqual(changed.half_duration_ticks, 30)
        self.assertEqual(MatchRules.from_json(changed.to_json()), changed)
        with self.assertRaises((AttributeError, TypeError)):
            changed.half_duration_ticks = 40
        with self.assertRaisesRegex(ValueError, "unsupported"):
            STANDARD_RULES.with_overrides("rules:unknown-v1", purple_card=True)
        with self.assertRaisesRegex(ValueError, "half duration"):
            STANDARD_RULES.with_overrides("rules:bad-v1", half_duration_ticks=0)
        with self.assertRaisesRegex(ValueError, "finite"):
            STANDARD_RULES.with_overrides("rules:bad-v1", red_card_probability_per_foul=float("nan"))

    def test_start_requires_legal_kickoff_setup_and_snapshots_rule_choice(self):
        rules = STANDARD_RULES.with_overrides("rules:short-v1", half_duration_ticks=12)
        state = new_match(rules=rules)
        self.assertIs(state.rules, rules)
        self.assertEqual(state.phase, MatchPhase.RESTART_READY)
        self.assertEqual(state.restart.kind, RestartKind.KICKOFF)
        self.assertAlmostEqual(state.restart.spot.x_m, 52.5)
        self.assertEqual(state.restart.designated_player_id,
                         PROOF_SQUADS[0].players[10].player_id)
        bad_home, away = sheets()
        illegal_starters = list(bad_home.starters)
        illegal_starters[-1] = player_state(illegal_starters[-1].profile, "home", (45, 34))
        with self.assertRaisesRegex(ValueError, "center circle"):
            create_match(TeamSheet("home", tuple(illegal_starters), bad_home.substitutes,
                                   bad_home.unavailable_player_ids), away,
                         match_id=MatchId("match:illegal-kickoff"))

    def test_match_rejects_profiles_missing_mechanical_inputs_before_play(self):
        home, away = sheets()
        keeper = home.starters[0]
        capabilities = replace(keeper.profile.capabilities, capabilities=tuple(
            cap for cap in keeper.profile.capabilities.capabilities if cap.name != "scanning"))
        incomplete = replace(keeper, profile=replace(keeper.profile, capabilities=capabilities))
        lineup = (incomplete, *home.starters[1:])
        with self.assertRaisesRegex(ValueError, "lacks required match inputs: scanning"):
            create_match(TeamSheet("home", lineup, home.substitutes, home.unavailable_player_ids),
                         away, match_id=MatchId("match:incomplete-profile"))

    def test_configured_restart_spots_takers_and_clearance_are_legal(self):
        state = new_match()
        center = Position2D(52.5, 34.0)
        scenarios = (
            (RestartKind.KICKOFF, "home", center),
            (RestartKind.THROW_IN, "away", Position2D(42.0, 0.0)),
            (RestartKind.GOAL_KICK, "away", Position2D(99.5, 34.0)),
            (RestartKind.CORNER, "home", Position2D(105.0, 0.0)),
            (RestartKind.FREE_KICK, "home", Position2D(72.0, 30.0)),
            (RestartKind.PENALTY, "home", Position2D(94.0, 34.0)),
        )
        for kind, team_id, spot in scenarios:
            with self.subTest(restart=kind.value):
                if kind is RestartKind.THROW_IN:
                    home_player = next(p for p in state.play.players.values()
                                       if p.team_id == "home"
                                       and p.profile.primary_role.value != "goalkeeper")
                    move_player(state, home_player.profile.player_id, Position2D(42.5, 1.0))
                restart = _award_restart(state, kind, team_id, spot, reason="mechanism_test")
                self.assertEqual(restart.kind, kind)
                self.assertEqual(state.play.players[restart.designated_player_id].team_id, team_id)
                self.assertEqual(state.play.ball.position, restart.spot)
                if kind is RestartKind.GOAL_KICK:
                    self.assertEqual(restart.designated_player_id,
                                     PROOF_SQUADS[1].players[0].player_id)
                if kind is RestartKind.PENALTY:
                    self.assertAlmostEqual(restart.spot.x_m, 94.0)
                    defending_keeper = next(
                        p for p in state.play.players.values()
                        if p.team_id == "away" and p.profile.primary_role.value == "goalkeeper")
                    self.assertEqual(defending_keeper.motion.position, Position2D(105.0, 34.0))
                    for player in state.play.players.values():
                        if player.profile.player_id in (restart.designated_player_id,
                                                        defending_keeper.profile.player_id):
                            continue
                        distance = ((player.motion.position.x_m - restart.spot.x_m) ** 2
                                    + (player.motion.position.y_m - restart.spot.y_m) ** 2) ** 0.5
                        self.assertGreaterEqual(distance + 1e-8, state.rules.restart_clearance_m)
                if kind is RestartKind.THROW_IN:
                    self.assertAlmostEqual(restart.spot.y_m, 0.0)
                    for player in state.play.players.values():
                        if (player.team_id == "home"
                                and player.profile.player_id != restart.designated_player_id):
                            self.assertGreaterEqual(
                                ((player.motion.position.x_m - restart.spot.x_m) ** 2
                                 + (player.motion.position.y_m - restart.spot.y_m) ** 2) ** 0.5,
                                state.rules.throw_in_clearance_m - 1e-8)

    def test_taker_fallback_is_recorded_when_designated_player_is_ineligible(self):
        state = new_match()
        unavailable = PROOF_SQUADS[1].players[10].player_id
        restart = _award_restart(state, RestartKind.FREE_KICK, "home",
            Position2D(68.0, 35.0), reason="fallback_test", designated_player_id=unavailable)
        self.assertEqual(state.play.players[restart.designated_player_id].team_id, "home")
        fallback = next(event for event in state.events if event.kind == "restart_taker_fallback")
        self.assertEqual(fallback.payload["requested_player_id"], str(unavailable))

    def test_touchline_corner_goal_kick_and_goal_use_crossed_line_and_last_touch(self):
        state = new_match(match_tag="out-test")
        home_actor = PROOF_SQUADS[0].players[13].player_id
        state.last_touch_team_id = "home"
        state.last_touch_player_id = home_actor
        state.play.ball = BallState(Position2D(42.0, 0.0), BALL_RADIUS_M, 0.0, 0.0, 0.0)
        state.play.out_of_play_boundary = "touchline"
        self.assertTrue(_handle_out_of_play(state))
        self.assertEqual(state.restart.kind, RestartKind.THROW_IN)
        self.assertEqual(state.restart.team_id, "away")
        self.assertEqual(state.restart.spot, Position2D(42.0, 0.0))

        state.play.out_of_play_boundary = "goal_line"
        state.play.ball = BallState(Position2D(105.0, 0.0), BALL_RADIUS_M, 0.0, 0.0, 0.0)
        state.last_touch_team_id = "home"
        _handle_out_of_play(state)
        self.assertEqual(state.restart.kind, RestartKind.CORNER)
        self.assertEqual(state.restart.team_id, "home")
        self.assertEqual(state.restart.spot, Position2D(105.0, 0.0))

        state.play.out_of_play_boundary = "goal_line"
        state.play.ball = BallState(Position2D(105.0, 10.0), BALL_RADIUS_M, 0.0, 0.0, 0.0)
        state.last_touch_team_id = "away"
        _handle_out_of_play(state)
        self.assertEqual(state.restart.kind, RestartKind.GOAL_KICK)
        self.assertEqual(state.restart.team_id, "away")
        self.assertEqual(state.restart.spot, Position2D(99.5, 34.0))
        self.assertEqual(state.restart.designated_player_id,
                         PROOF_SQUADS[1].players[0].player_id)

        state.play.out_of_play_boundary = "goal_line"
        state.play.ball = BallState(Position2D(105.0, 34.0), BALL_RADIUS_M, 0.0, 0.0, 0.0)
        state.last_touch_team_id = "home"
        state.last_touch_player_id = home_actor
        goal_count = state.play.statistics.get("goals", 0)
        _handle_out_of_play(state)
        self.assertEqual(state.home_score, 1)
        self.assertEqual(state.play.statistics["goals"], goal_count + 1)
        goal = next(event for event in reversed(state.events) if event.kind == "goal")
        self.assertEqual(goal.payload["scoring_team_id"], "home")
        self.assertEqual(goal.payload["actor_id"], str(home_actor))
        self.assertEqual(state.restart.kind, RestartKind.KICKOFF)

    def test_live_ball_crossing_uses_first_boundary_tick_and_emits_goal_line_restart(self):
        state = new_match(match_tag="crossing-test")
        passer_id = PROOF_SQUADS[0].players[10].player_id
        passer = state.play.players[passer_id]
        origin = BallState(Position2D(104.0, 34.0), BALL_RADIUS_M, 0.0, 0.0, 0.0)
        launch = BallState(Position2D(104.8, 34.0), BALL_RADIUS_M, 12.0, 0.0, 0.0)
        delivery = PassDelivery(
            passer_id, PassKind.DRIVEN, None, "area:boundary-proof",
            Position2D(106.0, 34.0), Position2D(106.0, 34.0), 0.0, 0.6,
            origin, launch, 0.1, state.play.physics)
        state.play.players[passer_id] = replace(
            passer, motion=replace(passer.motion, position=origin.position))
        _finish_flight(state.play, delivery, passer_id)
        self.assertEqual(state.play.out_of_play_boundary, "goal_line")
        self.assertEqual(state.play.ball.position, Position2D(105.0, 34.0))
        self.assertEqual(state.play.clock.tick, 1)
        state.last_touch_team_id, state.last_touch_player_id = "home", passer_id
        self.assertTrue(_handle_out_of_play(state, origin))
        self.assertEqual(state.home_score, 1)
        self.assertEqual(state.restart.kind, RestartKind.KICKOFF)

    def test_event_projection_reconciles_goal_assist_save_and_score(self):
        state = new_match(match_tag="stat-projection")
        passer = PROOF_SQUADS[0].players[10].player_id
        shooter = PROOF_SQUADS[0].players[13].player_id
        keeper = PROOF_SQUADS[1].players[0].player_id
        pass_id = _emit(state, "pass", passer, {"receiver_id": str(shooter)},
                        {"execution_quality": 0.8})
        shot_id = _emit(state, "shot", shooter,
            {"goalkeeper_id": str(keeper), "assist_player_id": str(passer),
             "assist_event_id": str(pass_id)}, {"saved": False}, parent=pass_id)
        state.play.home_score = 1
        state.play.statistics.update({"shots": 2, "saves": 1, "goals": 1})
        _emit(state, "goal", shooter,
            {"assist_player_id": str(passer), "assist_event_id": str(pass_id),
             "shot_event_id": str(shot_id)}, {"home_score": 1, "away_score": 0},
            cause=shot_id, parent=pass_id)
        _emit(state, "shot", PROOF_SQUADS[0].players[12].player_id,
            {"goalkeeper_id": str(keeper)}, {"saved": True})
        projected = state.player_statistics
        self.assertEqual(projected[shooter]["goals"], 1)
        self.assertEqual(projected[shooter]["shots"], 1)
        self.assertEqual(projected[passer]["assists"], 1)
        self.assertEqual(projected[keeper]["saves"], 1)
        self.assertEqual(sum(stats.get("goals", 0) for stats in projected.values()),
                         state.home_score + state.away_score)
        self.assertEqual(sum(stats.get("assists", 0) for stats in projected.values()), 1)

    def test_offside_uses_touch_time_and_can_be_disabled(self):
        state = new_match(match_tag="offside-test")
        home = [p for p in state.play.players.values() if p.team_id == "home"]
        away = [p for p in state.play.players.values() if p.team_id == "away"]
        positions = {p.profile.player_id: p.motion.position for p in state.play.players.values()}
        carrier, receiver = home[0], home[-1]
        positions[carrier.profile.player_id] = Position2D(60.0, 34.0)
        positions[receiver.profile.player_id] = Position2D(90.0, 34.0)
        for index, player in enumerate(away):
            positions[player.profile.player_id] = Position2D(
                104.0 if player.profile.primary_role.value == "goalkeeper" else 78.0 + index * 0.1,
                3.0 + index * 8.0)
        candidates = _offside_candidates(state, positions, "home", Position2D(60.0, 34.0))
        self.assertIn(receiver.profile.player_id, candidates)
        pass_event = envelope(state, 0, "pass", {
            "actor_id": str(carrier.profile.player_id),
            "receiver_id": str(receiver.profile.player_id),
        }, tick=6)
        contact_event = envelope(state, 1, "ball_contact", {
            "actor_id": str(receiver.profile.player_id),
            "touch_outcome": "controlled",
        }, tick=15, parent=pass_event.event_id)
        state.play.events = [pass_event, contact_event]
        state.play.next_sequence = 2
        state.play.clock = MatchClock(15, 20)
        state.play.ball = BallState(Position2D(90.0, 34.0), BALL_RADIUS_M, 0.0, 0.0, 0.0)
        state.phase = MatchPhase.IN_PLAY
        state.restart = None
        self.assertTrue(_process_offside(state, (pass_event, contact_event), positions,
                                         Position2D(60.0, 34.0)))
        offside = next((event for event in state.events if event.kind == "offside"), None)
        self.assertIsNotNone(offside, [(event.kind, event.payload, event.match_tick)
                                       for event in state.events])
        restart = next(event for event in state.events if event.kind == "restart_awarded")
        self.assertEqual(offside.match_tick, 15)
        self.assertEqual(offside.payload["pass_event_id"], str(pass_event.event_id))
        self.assertEqual(restart.payload["kind"], RestartKind.FREE_KICK.value)

        disabled = new_match(
            rules=STANDARD_RULES.with_overrides("rules:no-offside-v1", offside_enabled=False),
            match_tag="offside-disabled")
        self.assertFalse(_process_offside(disabled, (pass_event, contact_event), positions,
                                          Position2D(60.0, 34.0)))

    def test_live_pass_stops_at_first_offside_contact_before_control(self):
        state = new_match(rules=STANDARD_RULES.with_overrides(
            "rules:live-offside-v1", half_duration_ticks=10_000),
            match_tag="live-offside")
        carrier_id = PROOF_SQUADS[0].players[10].player_id
        receiver_id = PROOF_SQUADS[0].players[13].player_id
        move_player(state, carrier_id, Position2D(60.0, 34.0))
        move_player(state, receiver_id, Position2D(90.0, 34.0))
        for player_id, player in tuple(state.play.players.items()):
            if player.team_id == "home" and player_id not in (carrier_id, receiver_id):
                move_player(state, player_id, Position2D(20.0, 58.0))
            elif player.team_id == "away":
                if player.profile.primary_role.value == "goalkeeper":
                    move_player(state, player_id, Position2D(104.0, 67.0))
                elif player_id == PROOF_SQUADS[1].players[2].player_id:
                    move_player(state, player_id, Position2D(73.0, 24.0))
                else:
                    y = 1.0 if player.motion.position.y_m < 34 else 67.0
                    move_player(state, player_id, Position2D(78.0, y))
        state.phase, state.restart = MatchPhase.IN_PLAY, None
        state.play.ball = BallState(Position2D(60.0, 34.0), BALL_RADIUS_M, 0.0, 0.0, 0.0)
        state.play.possession_id = carrier_id
        state.play.possession_team_id = "home"
        carrier = state.play.players[carrier_id]
        high_decision = PLAYER_DECISION_PAIR[1]
        high_values = {c.name: c.normalized_value
                       for c in high_decision.capabilities.capabilities}
        caps = replace(carrier.profile.capabilities, capabilities=tuple(
            replace(cap, normalized_value=high_values[cap.name])
            if cap.name in ("scanning", "anticipation", "decision_quality") else cap
            for cap in carrier.profile.capabilities.capabilities))
        state.play.players[carrier_id] = replace(
            carrier, profile=replace(carrier.profile, capabilities=caps))
        pre_positions = {player_id: p.motion.position
                         for player_id, p in state.play.players.items()}
        self.assertIn(receiver_id, _offside_candidates(state, pre_positions, "home",
                                                        state.play.ball.position))
        options = generate_feasible_actions(state.play, carrier_id)
        self.assertTrue(any(action.target_id == receiver_id for action in options),
                        [(action.kind.value, action.target_id, action.provisional_value)
                         for action in options])
        preview = deepcopy(state.play)
        nearest = min((p for p in preview.players.values() if p.team_id == "away"),
                      key=lambda p: ((p.motion.position.x_m - 60.0) ** 2
                                     + (p.motion.position.y_m - 34.0) ** 2) ** 0.5)
        choose_action(preview, nearest.profile.player_id)
        carrier_choice = choose_action(preview, carrier_id)
        self.assertEqual(carrier_choice.chosen.target_id, receiver_id,
                         [(a.kind.value, a.target_id, a.provisional_value)
                          for a in carrier_choice.feasible_actions])
        step_match(state)
        current_pass = next((event for event in reversed(state.events) if event.kind == "pass"), None)
        self.assertIsNotNone(current_pass, [(record.kind.value, record.outcome, record.actor_id)
                                            for record in state.play.action_log])
        self.assertEqual(current_pass.payload["receiver_id"], str(receiver_id))
        contact = next(event for event in state.events
                       if event.kind == "ball_contact" and event.parent_event_id == current_pass.event_id)
        offside = next((event for event in state.events if event.kind == "offside"), None)
        self.assertIsNotNone(offside, [(event.kind, event.payload, event.match_tick)
                                       for event in state.events])
        self.assertEqual(contact.payload["actor_id"], str(receiver_id))
        self.assertEqual(offside.cause_event_id, contact.event_id)
        self.assertEqual(offside.match_tick, contact.match_tick)
        self.assertEqual(state.phase, MatchPhase.RESTART_READY)
        pass_related = [event.kind for event in state.events
                        if event.event_id == contact.event_id or event.event_id == offside.event_id
                        or event.kind == "possession_controlled"]
        self.assertNotIn("possession_controlled", pass_related)

    def test_challenge_foul_advantage_recall_and_cards(self):
        rules = STANDARD_RULES.with_overrides(
            "rules:advantage-proof-v1", foul_probability_per_challenge=1.0,
            cards_enabled=False, minimum_players_to_continue=6)
        state = new_match(rules=rules, match_tag="advantage-test")
        victim = next(p for p in state.play.players.values() if p.team_id == "home")
        fouler = next(p for p in state.play.players.values() if p.team_id == "away")
        state.phase, state.restart = MatchPhase.IN_PLAY, None
        state.play.possession_id, state.play.possession_team_id = victim.profile.player_id, "home"
        state.play.ball = BallState(Position2D(94.0, 34.0), BALL_RADIUS_M, 0.0, 0.0, 0.0)
        challenge = envelope(state, state.play.next_sequence, "challenge_contest", {
            "actor_id": str(fouler.profile.player_id),
            "carrier_id": str(victim.profile.player_id),
        }, tick=1)
        _process_challenges(state, (challenge,))
        self.assertEqual(state.pending_advantage.restart_kind, RestartKind.PENALTY)
        self.assertEqual(state.phase, MatchPhase.IN_PLAY)
        state.play.possession_team_id = "away"
        before = len(state.events)
        _after_events(state, before, {}, state.play.ball, (0, 0))
        self.assertIsNone(state.pending_advantage)
        self.assertEqual(state.restart.kind, RestartKind.PENALTY)
        self.assertTrue(any(event.kind == "advantage_recalled" for event in state.events))

        card_rules = STANDARD_RULES.with_overrides(
            "rules:red-card-proof-v1", foul_probability_per_challenge=1.0,
            red_card_probability_per_foul=1.0, yellow_card_probability_per_foul=1.0,
            advantage_enabled=False, minimum_players_to_continue=6)
        card_state = new_match(rules=card_rules, match_tag="red-card-test")
        player = next(p for p in card_state.play.players.values()
                      if p.team_id == "away" and p.profile.primary_role.value != "goalkeeper")
        card_state.phase, card_state.restart = MatchPhase.IN_PLAY, None
        card_state.play.possession_team_id = "home"
        event = envelope(card_state, 90, "challenge_contest", {
            "actor_id": str(player.profile.player_id),
            "carrier_id": str(victim.profile.player_id),
        })
        _process_challenges(card_state, (event,))
        self.assertIn(player.profile.player_id, card_state.teams["away"].sent_off_ids)
        self.assertNotIn(player.profile.player_id, card_state.play.players)
        self.assertEqual(next(e for e in card_state.events if e.kind == "card").payload["card"],
                         CardKind.RED.value)
        self.assertIsNone(card_state.play.possession_id)

    def test_substitutions_are_atomic_bounded_and_replace_a_dismissed_keeper(self):
        rules = STANDARD_RULES.with_overrides(
            "rules:substitution-proof-v1", minimum_players_to_continue=6,
            substitutions_allowed=1, substitution_windows_allowed=1)
        state = new_match(rules=rules, match_tag="sub-test")
        outgoing = next(p for p in state.play.players.values()
                        if p.team_id == "home" and p.profile.primary_role.value != "goalkeeper")
        incoming_field = next(p for p in state.teams["home"].substitutes
                              if p.primary_role.value != "goalkeeper")
        snapshot = state.to_json()
        state.phase = MatchPhase.IN_PLAY
        with self.assertRaisesRegex(ValueError, "stoppage"):
            substitute(state, outgoing.profile.player_id, incoming_field.player_id, window_id="w1")
        state.phase = MatchPhase.RESTART_READY
        self.assertEqual(state.to_json(), snapshot)
        event = substitute(state, outgoing.profile.player_id, incoming_field.player_id, window_id="w1")
        self.assertEqual(event.kind, "substitution")
        self.assertNotIn(outgoing.profile.player_id, state.play.players)
        self.assertIn(incoming_field.player_id, state.play.players)
        self.assertEqual(state.teams["home"].substitutions_made, 1)
        self.assertIn("w1", state.teams["home"].substitution_windows_used)
        before = state.to_json()
        next_outgoing = next(p for p in state.play.players.values()
                             if p.team_id == "home" and p.profile.primary_role.value != "goalkeeper")
        another_bench = next(p for p in state.teams["home"].substitutes
                             if p.primary_role.value != "goalkeeper")
        with self.assertRaisesRegex(ValueError, "limit"):
            substitute(state, next_outgoing.profile.player_id, another_bench.player_id, window_id="w1")
        self.assertEqual(state.to_json(), before)

        keeper_state = new_match(rules=rules, match_tag="keeper-sub-test")
        keeper = next(p for p in keeper_state.play.players.values()
                      if p.team_id == "home" and p.profile.primary_role.value == "goalkeeper")
        _send_off(keeper_state, keeper.profile.player_id, "test_dismissal")
        self.assertEqual(keeper_state.keeper_replacement_team_id, "home")
        before_wait = keeper_state.to_json()
        self.assertIs(step_match(keeper_state), keeper_state)
        self.assertEqual(keeper_state.to_json(), before_wait)
        replacement = next(p for p in keeper_state.teams["home"].substitutes
                           if p.primary_role.value == "goalkeeper")
        outgoing_field = next(p for p in keeper_state.play.players.values()
                              if p.team_id == "home" and p.profile.primary_role.value != "goalkeeper")
        substitute(keeper_state, outgoing_field.profile.player_id, replacement.player_id,
                   window_id="keeper-cover")
        self.assertIsNone(keeper_state.keeper_replacement_team_id)
        self.assertEqual(sum(p.team_id == "home" and p.profile.primary_role.value == "goalkeeper"
                             for p in keeper_state.play.players.values()), 1)

    def test_undersized_unavailable_team_is_recorded_as_abandoned(self):
        home, away = sheets(home_count=6)
        state = create_match(home, away, rules=STANDARD_RULES,
                             match_id=MatchId("match:undersized-proof"))
        self.assertEqual(state.phase, MatchPhase.ABANDONED)
        self.assertEqual(state.finished_reason, "starting_players_below_competition_minimum")
        self.assertEqual(sum(p.team_id == "home" for p in state.play.players.values()), 6)
        self.assertFalse(set(state.teams["home"].unavailable_ids)
                         & set(state.play.players))
        self.assertFalse(any(e.kind == "restart_awarded" for e in state.events))
        self.assertEqual(state.events[-1].kind, "match_abandoned")

    def test_short_complete_match_reaches_full_time_and_tracks_playing_minutes(self):
        rules = STANDARD_RULES.with_overrides(
            "rules:short-match-v1", half_duration_ticks=4, stoppage_time_ticks=1,
            extra_time_duration_ticks=0, shootout_kicks_per_team=0)
        state = run_to_completion(new_match(rules=rules, match_tag="short-match"),
                                  maximum_transitions=40)
        self.assertEqual(state.phase, MatchPhase.FINISHED)
        self.assertIn(state.finished_reason, ("full_time", "full_time_draw"))
        self.assertEqual(sum(e.kind == "period_ended" for e in state.events), 2)
        self.assertEqual(sum(e.kind == "match_finished" for e in state.events), 1)
        ticks = [event.match_tick for event in state.events]
        self.assertEqual(ticks, sorted(ticks))
        self.assertTrue(any(value > 0 for value in state.playing_ticks.values()))
        self.assertEqual(sum(state.player_statistics.get(pid, {}).get("goals", 0)
                             for pid in state.playing_ticks),
                         state.play.home_score + state.play.away_score)
        self.assertTrue(all(minutes >= 0.0 for minutes in state.minutes_played.values()))

    def test_short_extra_time_shootout_and_restart_open_play_checkpoints_replay(self):
        rules = STANDARD_RULES.with_overrides(
            "rules:extra-time-proof-v1", half_duration_ticks=1,
            extra_time_duration_ticks=1, shootout_kicks_per_team=1)
        state = new_match(rules=rules, match_tag="extra-time")
        initial_copy = type(state).from_json(state.to_json())
        self.assertEqual(initial_copy, state)
        state = run_to_completion(state, maximum_transitions=50)
        self.assertEqual(state.phase, MatchPhase.FINISHED)
        self.assertTrue(any(e.kind == "shootout_started" for e in state.events))
        self.assertTrue(any(e.kind == "shootout_kick" for e in state.events))
        self.assertEqual(sum(e.kind == "match_finished" for e in state.events), 1)

        open_state = new_match(rules=STANDARD_RULES.with_overrides(
            "rules:checkpoint-proof-v1", half_duration_ticks=1000),
            match_tag="open-checkpoint")
        for _ in range(5):
            step_match(open_state)
            if open_state.phase is MatchPhase.IN_PLAY:
                break
        self.assertEqual(open_state.phase, MatchPhase.IN_PLAY)
        resumed = type(open_state).from_json(open_state.to_json())
        self.assertEqual(resumed, open_state)
        step_match(open_state)
        step_match(resumed)
        self.assertEqual(resumed, open_state)


if __name__ == "__main__":
    unittest.main()
