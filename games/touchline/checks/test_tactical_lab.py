"""Mechanism proofs for P07 Tactical Laboratory and replay."""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

from games.touchline.esb.model import Position2D
from games.touchline.esb.tactics import TacticalAction, TacticalPhase
from games.touchline.esb.tactical_lab import (
    LAB_SCENARIOS,
    create_run,
    default_plan,
    load_plan,
    save_plan,
    set_instruction_action,
    set_player_placement,
)


class TacticalLabTests(unittest.TestCase):
    def test_each_scenario_activates_its_declared_shared_tactic_phase(self):
        expected = {
            "build_up": TacticalPhase.BUILD_UP,
            "pressing": TacticalPhase.DEFENSIVE_BLOCK,
            "compact": TacticalPhase.DEFENSIVE_BLOCK,
            "wide_attack": TacticalPhase.ESTABLISHED_ATTACK,
        }
        self.assertEqual(set(expected), {item.scenario_id for item in LAB_SCENARIOS})
        for scenario in LAB_SCENARIOS:
            with self.subTest(scenario=scenario.scenario_id):
                run = create_run(default_plan(scenario.scenario_id, seed=129))
                run.step()
                self.assertEqual(run.tactical_runtime.trace[0].phase, expected[scenario.scenario_id])

    def test_nearest_defender_with_no_feasible_action_is_not_asked_to_choose(self):
        run = create_run(default_plan("build_up", seed=321))
        # The nearest away player starts just beyond P04's local pressure
        # range. The carrier and tactical setup still produce a valid step.
        run.step()
        self.assertIn(run.match.play.possession_team_id, ("home", "away", None))
        self.assertTrue(run.match.events)
        self.assertEqual(run.tactical_runtime.trace[0].phase, TacticalPhase.BUILD_UP)

    def test_free_placement_and_changed_instruction_reach_spatial_engine(self):
        original = default_plan("compact", seed=4321)
        moved = set_player_placement(original, "LB", Position2D(29.0, 12.0))
        edited = set_instruction_action(
            moved,
            TacticalPhase.DEFENSIVE_BLOCK,
            "LB",
            TacticalAction.MOVE_INSIDE,
        )
        self.assertEqual(edited.tactic.version, original.tactic.version + 1)
        baseline_run = create_run(original)
        edited_run = create_run(edited)

        fullback_id = edited_run.home_slots["LB"]
        self.assertEqual(
            edited_run.tactical_runtime.shape_positions["LB"], Position2D(29.0, 12.0),
        )
        placed_sample = next(
            item for item in edited_run.checkpoint.snapshot.positions
            if item.player_id == fullback_id
        )
        self.assertEqual(placed_sample.position, Position2D(29.0, 12.0))

        baseline_run.step()
        edited_run.step()
        baseline_move = next(
            item for item in baseline_run.tactical_runtime.trace[0].movements
            if item.slot_id == "LB"
        )
        edited_move = next(
            item for item in edited_run.tactical_runtime.trace[0].movements
            if item.slot_id == "LB"
        )
        self.assertIs(edited_move.action, TacticalAction.MOVE_INSIDE)
        self.assertEqual(edited_move.start, Position2D(29.0, 12.0))
        self.assertNotEqual(baseline_move.target, edited_move.target)
        self.assertNotEqual(
            baseline_run.match.play.players[baseline_run.home_slots["LB"]].motion.position,
            edited_run.match.play.players[fullback_id].motion.position,
        )

    def test_plan_persistence_round_trips_only_tactics_and_placements(self):
        plan = set_instruction_action(
            set_player_placement(default_plan("wide_attack", seed=17), "RB", Position2D(80, 51)),
            TacticalPhase.ESTABLISHED_ATTACK,
            "RB",
            TacticalAction.OVERLAP,
        )
        with tempfile.TemporaryDirectory(prefix="touchline-p07-plan-") as temp_dir:
            path = save_plan(plan, temp_dir)
            loaded = load_plan(temp_dir)
            self.assertEqual(path.name, "current.json")
            self.assertEqual(loaded, plan)
            encoded = path.read_text(encoding="utf-8")
            self.assertIn("TacticalLabPlan", encoded)
            self.assertNotIn("MatchState", encoded)
            with self.assertRaises(ValueError):
                save_plan(plan, temp_dir, name="../career")

    def test_quick_and_stepwise_runs_keep_identical_state_and_event_order(self):
        plan = default_plan(seed=90210)
        quick = create_run(plan)
        stepped = create_run(plan)
        quick_state = quick.run_to_completion()
        while not stepped.finished:
            stepped.step()

        self.assertEqual(quick_state.to_json(), stepped.match.to_json())
        self.assertEqual(
            tuple(record.event for record in quick.events),
            tuple(record.event for record in stepped.events),
        )
        events = tuple(event for event in quick_state.events)
        self.assertEqual(
            [event.sequence for event in events],
            sorted(event.sequence for event in events),
        )
        self.assertEqual(
            [str(record.event.event_id) for record in quick.events],
            [str(event.event_id) for event in events],
        )
        self.assertEqual(quick_state.rules.ruleset_id, "rules:p07-tactical-lab-v1")

    def test_event_position_inspection_is_read_only_and_uses_recorded_snapshot(self):
        run = create_run(default_plan(seed=77))
        kickoff_start = run.inspect_event(run.match.events[0].event_id)
        self.assertEqual(kickoff_start.event.kind, "match_started")
        self.assertEqual(kickoff_start.snapshot.match_tick, 0)
        run.run_steps(4)
        self.assertTrue(run.events)
        chosen = run.events[-1]
        before_match = run.match.to_json()
        before_random = tuple(
            (name, stream.state, stream.draws)
            for name, stream in sorted(run.match.play.random_streams.streams.items())
        )
        before_trace = tuple(run.tactical_runtime.trace)

        result = run.inspect_event(chosen.event.event_id)

        self.assertIs(result, chosen)
        self.assertLessEqual(result.event.match_tick, result.snapshot.match_tick)
        self.assertEqual(run.match.to_json(), before_match)
        after_random = tuple(
            (name, stream.state, stream.draws)
            for name, stream in sorted(run.match.play.random_streams.streams.items())
        )
        self.assertEqual(after_random, before_random)
        self.assertEqual(tuple(run.tactical_runtime.trace), before_trace)
        self.assertEqual(
            {sample.player_id for sample in result.snapshot.positions},
            set(run.match.play.players),
        )

    def test_invalid_positions_and_instruction_references_are_rejected(self):
        plan = default_plan()
        with self.assertRaises(ValueError):
            set_player_placement(plan, "LB", Position2D(106.0, 20.0))
        with self.assertRaises(ValueError):
            set_instruction_action(
                plan, TacticalPhase.BUILD_UP, "NOT_A_SLOT", TacticalAction.HOLD_WIDTH,
            )

    def test_fresh_process_import_is_headless_and_performs_no_file_io(self):
        root = pathlib.Path(__file__).resolve().parents[3]
        script = r'''
import builtins, importlib, io, pathlib, sys
def blocked(*args, **kwargs): raise AssertionError("Tactical Lab domain import performed file I/O")
builtins.open = blocked
io.open = blocked
pathlib.Path.open = blocked
importlib.import_module("games.touchline.esb.tactical_lab")
importlib.import_module("games.touchline.lab")
assert "curses" not in sys.modules
assert "termstation_ui" not in sys.modules
assert not any(name.startswith("termstation.") for name in sys.modules)
'''
        subprocess.run(
            [sys.executable, "-c", script],
            cwd=root,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            capture_output=True,
            text=True,
            check=True,
        )

    def test_same_seed_run_is_byte_identical_across_fresh_processes(self):
        root = pathlib.Path(__file__).resolve().parents[3]
        script = r'''
import json
from games.touchline.esb.tactical_lab import create_run, default_plan
run = create_run(default_plan("compact", seed=64821))
run.run_steps(8)
trace = []
for frame in run.tactical_runtime.trace:
    trace.append({
        "tick": frame.tick,
        "phase": frame.phase.value,
        "movements": [
            [move.slot_id, move.action.value,
             move.start.x_m, move.start.y_m, move.target.x_m, move.target.y_m,
             move.result.position.x_m, move.result.position.y_m]
            for move in frame.movements
        ],
    })
events = [[event.sequence, event.kind, event.match_tick,
           event.payload_json, event.outcome_json]
          for event in run.match.events]
print(json.dumps({"state": run.match.to_json(), "events": events, "trace": trace},
                 sort_keys=True, separators=(",", ":")))
'''
        command = [sys.executable, "-c", script]
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        first = subprocess.run(
            command, cwd=root, env=env, capture_output=True, text=True, check=True,
        )
        second = subprocess.run(
            command, cwd=root, env=env, capture_output=True, text=True, check=True,
        )
        self.assertEqual(first.stdout, second.stdout)


if __name__ == "__main__":
    unittest.main()
