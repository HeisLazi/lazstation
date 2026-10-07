"""Mechanism proofs for P06 tactical movement, coordination and counterplay."""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace

from games.touchline.esb.content.proof_roster import PROOF_SQUADS
from games.touchline.esb.content.proof_tactics import (
    COMPACT_BLOCK_COUNTER, DIRECT_SECOND_BALL, FLUID_COMBINATION,
    KICKOFF_TOUCHLINE_TRAP, MAN_ORIENTED_PRESS, POSITIONAL_POSSESSION,
    P06_PROOF_TACTICS, SPARE_DEFENDER, VERTICAL_COMBINATION, WIDE_ISOLATION,
)
from games.touchline.esb.ids import MatchId
from games.touchline.esb.match.ball import BALL_RADIUS_M, BallState
from games.touchline.esb.match.engine import (
    MatchPhase, TeamSheet, create_match, step_match,
)
from games.touchline.esb.match.possession import (
    PlayerState, create_state, step_open_play,
)
from games.touchline.esb.match.rules import STANDARD_RULES
from games.touchline.esb.match.spatial import PlayerMotion, limits_from_profile
from games.touchline.esb.match.tactics import TacticalRuntime
from games.touchline.esb.model import Position2D
from games.touchline.esb.randomness import RandomStreams
from games.touchline.esb.tactics import (
    AnchorReference, CoordinatedRelationship, IndividualInstruction,
    MarkingBehavior, PhasePlan, RelationshipKind, TacticalAction,
    TacticalPhase, TacticDefinition, Trigger, new_tactic_id, validate_tactic,
)


SLOT_INDEX = {
    "GK": 0, "LCB": 2, "RCB": 3, "LB": 5, "RB": 6,
    "DM": 8, "LCM": 10, "RCM": 11, "LW": 12, "RW": 13, "ST": 14,
}
HOME_POSITIONS = {
    "GK": (5.0, 34.0), "LCB": (20.0, 20.0), "RCB": (20.0, 48.0),
    "LB": (27.0, 8.0), "RB": (27.0, 60.0), "DM": (37.0, 34.0),
    "LCM": (43.0, 23.0), "RCM": (43.0, 45.0), "LW": (52.0, 8.0),
    "RW": (52.0, 60.0), "ST": (59.0, 34.0),
}
AWAY_POSITIONS = {
    "GK": (100.0, 34.0), "LCB": (88.0, 20.0), "RCB": (88.0, 48.0),
    "LB": (78.0, 8.0), "RB": (78.0, 60.0), "DM": (67.0, 34.0),
    "LCM": (61.0, 23.0), "RCM": (61.0, 45.0), "LW": (58.0, 8.0),
    "RW": (58.0, 60.0), "ST": (56.0, 34.0),
}
KICKOFF_HOME_POSITIONS = {
    "GK": (5.0, 34.0), "LCB": (18.0, 20.0), "RCB": (18.0, 48.0),
    "LB": (27.0, 7.0), "RB": (27.0, 61.0), "DM": (35.0, 34.0),
    "LCM": (40.0, 24.0), "RCM": (40.0, 44.0), "LW": (46.0, 7.0),
    "RW": (46.0, 61.0), "ST": (52.5, 34.0),
}
KICKOFF_AWAY_POSITIONS = {
    "GK": (100.0, 34.0), "LCB": (90.0, 20.0), "RCB": (90.0, 48.0),
    "LB": (80.0, 7.0), "RB": (80.0, 61.0), "DM": (72.0, 34.0),
    "LCM": (65.0, 24.0), "RCM": (65.0, 44.0), "LW": (62.0, 7.0),
    "RW": (62.0, 61.0), "ST": (63.0, 34.0),
}


def _player(profile, team_id: str, position: tuple[float, float]) -> PlayerState:
    motion = PlayerMotion(profile.player_id, team_id, Position2D(*position),
                          0.0, 0.0, 0.0, limits_from_profile(profile))
    return PlayerState(profile, motion, team_id)


def _slot_players(squad) -> dict[str, object]:
    return {slot: squad.players[index].player_id for slot, index in SLOT_INDEX.items()}


def _open_play(seed: int = 6901):
    states = []
    bindings = {}
    for team, squad, positions in (
        ("home", PROOF_SQUADS[0], HOME_POSITIONS),
        ("away", PROOF_SQUADS[1], AWAY_POSITIONS),
    ):
        for slot, index in SLOT_INDEX.items():
            profile = squad.players[index]
            states.append(_player(profile, team, positions[slot]))
        bindings[team] = _slot_players(squad)
    home_pivot = bindings["home"]["DM"]
    play = create_state(
        MatchId(f"match:p06-open:{seed}"), tuple(states),
        BallState(Position2D(*HOME_POSITIONS["DM"]), BALL_RADIUS_M, 0.0, 0.0, 0.0),
        home_pivot, RandomStreams.seeded(seed),
    )
    opponent_refs = {
        "opponent:deep_playmaker": bindings["away"]["DM"],
        "opponent:center_back_left": bindings["away"]["LCB"],
        "opponent:pivot": bindings["away"]["DM"],
        "opponent:last_line": bindings["away"]["ST"],
        "opponent:throw_receiver": bindings["away"]["LW"],
        "deep_touchline_runner": bindings["away"]["LW"],
    }
    return play, bindings, opponent_refs


def _runtime(play, tactic, team: str, bindings, opponent_refs):
    return TacticalRuntime.bind(play, tactic, team, bindings[team],
                                opponent_slots=opponent_refs)


def _move(play, player_id, position: tuple[float, float]) -> None:
    item = play.players[player_id]
    motion = replace(item.motion, position=Position2D(*position),
                     velocity_x_mps=0.0, velocity_y_mps=0.0)
    play.players[player_id] = replace(item, motion=motion)


def _kickoff_match(seed: int = 8217):
    sheets = []
    bindings = {}
    for team, squad, positions in (
        ("home", PROOF_SQUADS[0], KICKOFF_HOME_POSITIONS),
        ("away", PROOF_SQUADS[1], KICKOFF_AWAY_POSITIONS),
    ):
        starters = tuple(_player(squad.players[SLOT_INDEX[slot]], team, positions[slot])
                         for slot in SLOT_INDEX)
        sheets.append(TeamSheet(team, starters))
        bindings[team] = _slot_players(squad)
    rules = STANDARD_RULES.with_overrides(
        f"rules:p06-kickoff-{seed}", half_duration_ticks=500,
        stoppage_time_ticks=0, extra_time_duration_ticks=0,
        extra_time_stoppage_ticks=0, offside_enabled=False,
        foul_probability_per_challenge=0.0)
    state = create_match(sheets[0], sheets[1], rules=rules, seed=seed,
                         match_id=MatchId(f"match:p06-kickoff:{seed}"))
    opponent_refs = {
        "opponent:deep_playmaker": bindings["away"]["DM"],
        "opponent:center_back_left": bindings["away"]["LCB"],
        "opponent:pivot": bindings["away"]["DM"],
        "opponent:last_line": bindings["away"]["ST"],
        "opponent:throw_receiver": bindings["away"]["LW"],
        "deep_touchline_runner": bindings["away"]["LW"],
    }
    return state, bindings, opponent_refs


class TacticalProofTests(unittest.TestCase):
    def test_import_remains_headless_and_does_not_read_files(self):
        root = pathlib.Path(__file__).resolve().parents[3]
        script = r'''
import builtins, importlib, io, pathlib, sys
def blocked(*args, **kwargs): raise AssertionError("domain import performed file I/O")
builtins.open = blocked
io.open = blocked
pathlib.Path.open = blocked
importlib.import_module("games.touchline.esb.match.tactics")
importlib.import_module("games.touchline.esb.match.engine")
assert "curses" not in sys.modules
assert "termstation_ui" not in sys.modules
assert not any(name.startswith("termstation.") for name in sys.modules)
'''
        subprocess.run([sys.executable, "-c", script], cwd=root,
                       env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                       capture_output=True, text=True, check=True)

    def test_tactic_01_inverted_fullback_moves_inside_and_winger_keeps_width(self):
        play, bindings, refs = _open_play()
        runtime = _runtime(play, POSITIONAL_POSSESSION, "home", bindings, refs)
        fullback_id, winger_id = bindings["home"]["LB"], bindings["home"]["LW"]
        fullback_start = play.players[fullback_id].motion.position
        winger_start = play.players[winger_id].motion.position
        for _ in range(32):
            runtime.step(play, TacticalPhase.BUILD_UP)
        fullback_end = play.players[fullback_id].motion.position
        winger_end = play.players[winger_id].motion.position
        self.assertLess(abs(fullback_end.y_m - 34.0), abs(fullback_start.y_m - 34.0))
        self.assertGreater(abs(winger_end.y_m - 34.0), 16.0)
        self.assertLessEqual(
            math_dist(fullback_start, fullback_end),
            8.8 * play.physics.step_seconds * 32 + 1e-6,
        )
        last = runtime.trace[-1]
        self.assertTrue(any(move.slot_id == "LB" and move.action is TacticalAction.UNDERLAP
                            for move in last.movements))
        self.assertTrue(any(move.slot_id == "LW" and move.action is TacticalAction.HOLD_WIDTH
                            for frame in runtime.trace for move in frame.movements))

    def test_tactic_02_handover_changes_the_marker_and_visible_cover_lane(self):
        play_a, bindings_a, refs_a = _open_play(6902)
        play_b, bindings_b, refs_b = _open_play(6902)
        target_a, target_b = refs_a["opponent:deep_playmaker"], refs_b["opponent:deep_playmaker"]
        _move(play_a, bindings_a["home"]["RCM"], (55.0, 34.0))
        _move(play_b, bindings_b["home"]["RCM"], (55.0, 34.0))
        _move(play_a, target_a, (59.0, 34.0))
        _move(play_b, target_b, (59.0, 34.0))
        strict_phase = replace(
            MAN_ORIENTED_PRESS.phases[0],
            marking=(replace(MAN_ORIENTED_PRESS.phases[0].marking[0],
                             behavior=MarkingBehavior.TRACK_WITHIN_LIMIT,
                             handover_to_slot=None),),
        )
        strict = replace(MAN_ORIENTED_PRESS, phases=(strict_phase,))
        handover_runtime = _runtime(play_a, MAN_ORIENTED_PRESS, "home", bindings_a, refs_a)
        strict_runtime = _runtime(play_b, strict, "home", bindings_b, refs_b)
        handover_runtime.step(play_a, TacticalPhase.DEFENSIVE_BLOCK,
                              triggers=(Trigger.POOR_TOUCH,))
        strict_runtime.step(play_b, TacticalPhase.DEFENSIVE_BLOCK,
                            triggers=(Trigger.POOR_TOUCH,))
        _move(play_a, target_a, (73.0, 34.0))
        _move(play_b, target_b, (73.0, 34.0))
        handed = handover_runtime.step(play_a, TacticalPhase.DEFENSIVE_BLOCK)
        held = strict_runtime.step(play_b, TacticalPhase.DEFENSIVE_BLOCK)
        self.assertTrue(any(event.code == "marking_handover" for event in handed.events))
        self.assertTrue(any(move.slot_id == "DM" and move.action is TacticalAction.TRACK_OPPONENT
                            for move in handed.movements))
        self.assertTrue(any(move.slot_id == "RCM" and move.action is TacticalAction.TRACK_OPPONENT
                            for move in held.movements))
        self.assertFalse(any(event.code == "marking_handover" for event in held.events))

    def test_tactic_03_kickoff_delivery_causes_legal_throwin_and_press_support(self):
        state, bindings, refs = _kickoff_match()
        home = TacticalRuntime.bind(state.play, KICKOFF_TOUCHLINE_TRAP, "home",
                                     bindings["home"], opponent_slots=refs)
        for _ in range(220):
            step_match(state, tactical_runtimes={"home": home})
            if state.phase is MatchPhase.RESTART_READY and state.restart.kind.value == "throw_in":
                break
        self.assertEqual(state.phase, MatchPhase.RESTART_READY)
        self.assertEqual(state.restart.kind.value, "throw_in")
        restart = next(event for event in state.events if event.kind == "restart_awarded"
                       and event.payload.get("kind") == "throw_in")
        self.assertEqual(restart.payload.get("team_id"), "away")
        initial_pass = next(event for event in state.events
                            if event.kind == "pass"
                            and str(event.payload.get("intended_area_id", "")).startswith(
                                "tactical:kickoff:"))
        self.assertGreater(float(initial_pass.outcome["intended_x_m"]), 70.0)
        step_match(state, tactical_runtimes={"home": home})
        current = home.trace[-1]
        self.assertIn(TacticalPhase.THROW_IN_RESTART, [frame.phase for frame in home.trace])
        self.assertTrue(any(event.code == "press_activated" for event in current.events))
        self.assertTrue(any(move.slot_id in ("LW", "ST", "LCM")
                            for move in current.movements))
        escaped = home.step(state.play, TacticalPhase.DEFENSIVE_BLOCK,
                            triggers=(Trigger.OPPONENT_ESCAPES_PRESS,))
        self.assertTrue(any(event.code == "press_fallback" for event in escaped.events))
        self.assertTrue(any(event.code == "conditional_fallback" for event in escaped.events))
        sequence = [event.sequence for event in state.events]
        ticks = [event.match_tick for event in state.events]
        self.assertEqual(sequence, sorted(sequence))
        self.assertEqual(ticks, sorted(ticks))
        self.assertTrue(any(event.kind == "tactic_routine_started" for event in state.events))

    def test_tactic_04_block_outlet_press_support_and_profile_speed_are_explicit(self):
        play, bindings, refs = _open_play(6904)
        runtime = _runtime(play, COMPACT_BLOCK_COUNTER, "home", bindings, refs)
        initial = play.players[bindings["home"]["ST"]].motion.position
        for _ in range(10):
            runtime.step(play, TacticalPhase.DEFENSIVE_BLOCK)
        outlet = play.players[bindings["home"]["ST"]].motion.position
        self.assertNotEqual(initial, outlet)
        self.assertTrue(any(move.action is TacticalAction.COVER_DEPTH
                            for move in runtime.trace[-1].movements))

        fast_play, fast_bindings, fast_refs = _open_play(6905)
        slow_play, slow_bindings, slow_refs = _open_play(6905)
        fast_runtime = _runtime(fast_play, MAN_ORIENTED_PRESS, "home", fast_bindings, fast_refs)
        slow_runtime = _runtime(slow_play, MAN_ORIENTED_PRESS, "home", slow_bindings, slow_refs)
        fast_winger = fast_bindings["home"]["LW"]
        slow_winger = slow_bindings["home"]["LW"]
        slow = slow_play.players[slow_winger]
        slow_profile = replace(
            slow.profile,
            capabilities=replace(slow.profile.capabilities, measurements=tuple(
                replace(item, value=item.value * .72) if item.name == "maximum_speed" else item
                for item in slow.profile.capabilities.measurements)),
        )
        slow_motion = replace(slow.motion, limits=limits_from_profile(slow_profile))
        slow_play.players[slow_winger] = replace(slow, profile=slow_profile, motion=slow_motion)
        fast_start = fast_play.players[fast_winger].motion.position
        slow_start = slow_play.players[slow_winger].motion.position
        for _ in range(70):
            fast_runtime.step(fast_play, TacticalPhase.DEFENSIVE_BLOCK,
                              triggers=(Trigger.POOR_TOUCH,))
            slow_runtime.step(slow_play, TacticalPhase.DEFENSIVE_BLOCK,
                              triggers=(Trigger.POOR_TOUCH,))
        fast_move = math_dist(fast_start, fast_play.players[fast_winger].motion.position)
        slow_move = math_dist(slow_start, slow_play.players[slow_winger].motion.position)
        self.assertGreater(fast_move, slow_move)
        self.assertTrue(all(move.priority >= 100 for move in fast_runtime.trace[-1].movements
                            if move.source.startswith(("press:", "press-support:"))))

        fast_play, fast_bindings, fast_refs = _open_play(6910)
        slow_play, slow_bindings, slow_refs = _open_play(6910)
        fast_runtime = _runtime(fast_play, DIRECT_SECOND_BALL, "home", fast_bindings, fast_refs)
        slow_runtime = _runtime(slow_play, DIRECT_SECOND_BALL, "home", slow_bindings, slow_refs)
        fast_midfielder = fast_bindings["home"]["LCM"]
        slow_midfielder = slow_bindings["home"]["LCM"]
        slow = slow_play.players[slow_midfielder]
        slow_profile = replace(
            slow.profile,
            capabilities=replace(slow.profile.capabilities, measurements=tuple(
                replace(item, value=item.value * .72) if item.name == "maximum_speed" else item
                for item in slow.profile.capabilities.measurements)),
        )
        slow_motion = replace(slow.motion, limits=limits_from_profile(slow_profile))
        slow_play.players[slow_midfielder] = replace(slow, profile=slow_profile,
                                                     motion=slow_motion)
        fast_start = fast_play.players[fast_midfielder].motion.position
        slow_start = slow_play.players[slow_midfielder].motion.position
        for _ in range(70):
            fast_runtime.step(fast_play, TacticalPhase.ATTACKING_TRANSITION)
            slow_runtime.step(slow_play, TacticalPhase.ATTACKING_TRANSITION)
        self.assertGreater(
            math_dist(fast_start, fast_play.players[fast_midfielder].motion.position),
            math_dist(slow_start, slow_play.players[slow_midfielder].motion.position),
        )

    def test_tactical_move_uses_one_p03_movement_budget_in_open_play(self):
        results = []
        for suppress_second_move in (True, False):
            play, bindings, refs = _open_play(6908)
            carrier_id = bindings["home"]["ST"]
            carrier = play.players[carrier_id]
            play.possession_id = carrier_id
            play.possession_team_id = "home"
            play.ball = replace(play.ball, position=carrier.motion.position,
                                velocity_x_mps=0.0, velocity_y_mps=0.0, velocity_z_mps=0.0)
            # Keep every other home player outside the carrier's perception so
            # carry is the selected live action while the tactic moves ST.
            for player_id, item in tuple(play.players.items()):
                if item.team_id == "home" and player_id != carrier_id:
                    _move(play, player_id, (0.0, 0.0))
            runtime = _runtime(play, COMPACT_BLOCK_COUNTER, "home", bindings, refs)
            frame = runtime.step(play, TacticalPhase.DEFENSIVE_BLOCK)
            carrier_move = next(move for move in frame.movements if move.player_id == carrier_id)
            after_tactic = play.players[carrier_id].motion.position
            self.assertEqual(after_tactic, carrier_move.result.position)
            step_open_play(play, players_already_moved=(
                frozenset(move.player_id for move in frame.movements)
                if suppress_second_move else frozenset()))
            results.append((after_tactic, play.players[carrier_id].motion.position))
        self.assertEqual(results[0][0], results[0][1])
        self.assertNotEqual(results[1][0], results[1][1])

    def test_tactic_05_six_additional_compositions_resolve_actual_movement(self):
        tactic_phases = (
            (COMPACT_BLOCK_COUNTER, TacticalPhase.DEFENSIVE_BLOCK),
            (DIRECT_SECOND_BALL, TacticalPhase.ATTACKING_TRANSITION),
            (FLUID_COMBINATION, TacticalPhase.ESTABLISHED_ATTACK),
            (VERTICAL_COMBINATION, TacticalPhase.PROGRESSION),
            (WIDE_ISOLATION, TacticalPhase.ESTABLISHED_ATTACK),
            (SPARE_DEFENDER, TacticalPhase.DEFENSIVE_BLOCK),
        )
        self.assertEqual(len(P06_PROOF_TACTICS), 9)
        for tactic, phase in tactic_phases:
            with self.subTest(tactic=tactic.name):
                issues = validate_tactic(tactic)
                self.assertFalse([item for item in issues if item.severity.value == "error"])
                play, bindings, refs = _open_play(6906)
                runtime = _runtime(play, tactic, "home", bindings, refs)
                frame = runtime.step(play, phase)
                self.assertTrue(frame.movements)

    def test_unfamiliar_shared_component_combination_composes(self):
        tactic = TacticDefinition(
            new_tactic_id("p06-proof", "custom-composition"),
            "Custom press-and-run proof", MAN_ORIENTED_PRESS.slots,
            (PhasePlan(
                TacticalPhase.DEFENSIVE_BLOCK,
                instructions=(
                    IndividualInstruction("LW", (TacticalAction.PRESS_RECEIVER,),
                        anchor=None, priority=2),
                    IndividualInstruction("ST", (TacticalAction.RUN_BEHIND,),
                        anchor=None, priority=1),
                ),
                relationships=(CoordinatedRelationship(
                    "custom-third-player", RelationshipKind.THIRD_PLAYER_RUN,
                    ("LW", "LCM", "ST"), 3),),
            ),),
        )
        issues = validate_tactic(tactic)
        self.assertFalse([item for item in issues if item.severity.value == "error"])
        play, bindings, refs = _open_play()
        frame = _runtime(play, tactic, "home", bindings, refs).step(
            play, TacticalPhase.DEFENSIVE_BLOCK)
        self.assertTrue(any(move.slot_id == "ST" and move.action is TacticalAction.RUN_BEHIND
                            for move in frame.movements))

    def test_seeded_tactical_match_and_recorded_trace_replay_exactly(self):
        def run():
            state, bindings, refs = _kickoff_match(6907)
            home = TacticalRuntime.bind(state.play, KICKOFF_TOUCHLINE_TRAP, "home",
                                        bindings["home"], opponent_slots=refs)
            away = TacticalRuntime.bind(state.play, MAN_ORIENTED_PRESS, "away",
                                        bindings["away"], opponent_slots={
                                            "opponent:deep_playmaker": bindings["home"]["DM"],
                                            "opponent:center_back_left": bindings["home"]["LCB"],
                                            "opponent:pivot": bindings["home"]["DM"],
                                            "opponent:last_line": bindings["home"]["ST"],
                                        })
            for _ in range(45):
                step_match(state, tactical_runtimes={"home": home, "away": away})
                if state.phase is MatchPhase.FINISHED:
                    break
            return state.to_json(), tuple(home.trace), tuple(away.trace)

        first, first_home, first_away = run()
        second, second_home, second_away = run()
        self.assertEqual(first, second)
        self.assertEqual(first_home, second_home)
        self.assertEqual(first_away, second_away)

    def test_tactical_probe_replays_across_fresh_processes(self):
        root = pathlib.Path(__file__).resolve().parents[3]
        command = [sys.executable, "-m", "games.touchline.checks.tactical_probe",
                   "--seed", "8217"]
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        with tempfile.TemporaryDirectory(prefix="touchline-p06-import-") as cache:
            env["PYTHONPYCACHEPREFIX"] = cache
            first = subprocess.check_output(command, cwd=root, env=env, text=True)
            second = subprocess.check_output(command, cwd=root, env=env, text=True)
        self.assertEqual(first, second)
        result = json.loads(first)
        self.assertEqual(result["ruleset_id"], "rules:p06-probe-8217")
        self.assertTrue(any(event["kind"] == "restart_awarded"
                            and json.loads(event["payload"]).get("kind") == "throw_in"
                            for event in result["events"]))
        self.assertTrue(any(event[0] == "press_activated"
                            for frame in result["tactical_trace"]["home"]
                            for event in frame["events"]))


def math_dist(left: Position2D, right: Position2D) -> float:
    return ((left.x_m - right.x_m) ** 2 + (left.y_m - right.y_m) ** 2) ** .5


if __name__ == "__main__":
    unittest.main()
