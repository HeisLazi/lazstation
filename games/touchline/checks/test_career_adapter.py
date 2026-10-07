"""Mechanism tests for versioned career migration and spatial fixture bridging."""

from __future__ import annotations

import copy
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from unittest import mock

from games.touchline.checks.career_adapter_probe import build_scenario
from games.touchline.esb.career_adapter import (
    LEGACY_ENGINE_ID,
    SPATIAL_ENGINE_ID,
    VersionedCareerSave,
    advance_spatial_career_match,
    migrate_v2_file,
    migrate_v2_save,
    resume_spatial_career_match,
    run_spatial_career_match,
    settle_spatial_career_match,
    start_spatial_career_match,
    _lineage,
)
from games.touchline.esb.match.engine import (
    MatchPhase,
    RestartKind,
    _award_restart,
    _emit,
    substitute,
)
from games.touchline.esb.match.rules import STANDARD_RULES
from games.touchline.esb.model import Position2D


def start(legacy=None, *, half_ticks=8, seed=41,
          home_sheet=None, away_sheet=None, rules=None):
    if legacy is None:
        legacy, default_home, default_away, default_rules = build_scenario(
            seed=seed, half_ticks=half_ticks)
        home_sheet = home_sheet or default_home
        away_sheet = away_sheet or default_away
        rules = rules or default_rules
    else:
        _, default_home, default_away, default_rules = build_scenario(
            seed=seed, half_ticks=half_ticks)
        home_sheet = home_sheet or default_home
        away_sheet = away_sheet or default_away
        rules = rules or default_rules
    versioned = migrate_v2_save(legacy)
    return start_spatial_career_match(
        versioned,
        home_sheet=home_sheet,
        away_sheet=away_sheet,
        seed=seed,
        rules=rules,
    )


def sdk_loaded_shape(save):
    value = json.loads(save.to_json())
    value.setdefault("version", 2)
    value.setdefault("career", None)
    return value


class CareerAdapterTests(unittest.TestCase):
    def test_v2_migration_preserves_live_match_and_historical_engine_labels(self):
        legacy, _home, _away, _rules = build_scenario()
        career = legacy["career"]
        career["played_ids"] = ["match:old-one", "match:old-two"]
        career["results"] = [{"id": "match:old-one", "home_goals": 1,
                               "away_goals": 0, "engine_id": "touchline.old-custom-v1"}]
        career["live_match"] = {
            "id": "match:legacy-live",
            "period": 2,
            "clock": {"minute": 51, "seconds": 3},
            "events": [{"minute": 49, "kind": "goal", "text": "Existing incident"}],
            "unknown_future_field": {"kept": [1, 2, 3]},
        }
        original = copy.deepcopy(legacy)

        migrated = migrate_v2_save(legacy)

        self.assertEqual(legacy, original)
        self.assertEqual(migrated.legacy_save, original)
        self.assertEqual(migrated.default_engine_id, LEGACY_ENGINE_ID)
        self.assertEqual(migrated.current_match_engine_id, LEGACY_ENGINE_ID)
        self.assertEqual(str(migrated.current_match_id), "match:legacy-live")
        self.assertIsNone(migrated.spatial_match_json)
        self.assertEqual(dict(migrated.historical_engine_labels), {
            "match:old-one": "touchline.old-custom-v1",
            "match:old-two": LEGACY_ENGINE_ID,
        })

    def test_atomic_file_migration_keeps_exact_backup_and_refuses_overwrite(self):
        legacy, _home, _away, _rules = build_scenario()
        original_bytes = (json.dumps(legacy, ensure_ascii=False, sort_keys=True,
                                     indent=2) + "\n").encode("utf-8")
        with tempfile.TemporaryDirectory(prefix="esb-p08-migration-") as directory:
            target = pathlib.Path(directory) / "career.json"
            target.write_bytes(original_bytes)
            original_mode = target.stat().st_mode & 0o777
            migrated, backup = migrate_v2_file(target)
            self.assertEqual(backup.read_bytes(), original_bytes)
            self.assertEqual(VersionedCareerSave.from_json(target.read_text()), migrated)
            self.assertEqual(migrated.legacy_save, legacy)
            self.assertEqual(target.stat().st_mode & 0o777, original_mode)

            unchanged = target.read_bytes()
            retry = pathlib.Path(directory) / "retry.json"
            retry.write_bytes(original_bytes)
            existing_backup = retry.with_name(retry.name + ".v2.bak")
            existing_backup.write_bytes(b"keep this backup")
            with self.assertRaises(FileExistsError):
                migrate_v2_file(retry)
            self.assertEqual(retry.read_bytes(), original_bytes)
            self.assertEqual(existing_backup.read_bytes(), b"keep this backup")
            self.assertEqual(target.read_bytes(), unchanged)

    def test_legacy_ui_load_and_persist_keep_versioned_engine_metadata(self):
        root = pathlib.Path(__file__).resolve().parents[3]
        if str(root / "sdk") not in sys.path:
            sys.path.insert(0, str(root / "sdk"))
        from games.touchline import main as legacy_game

        career = legacy_game.new_career("BRP", seed=317)
        career["live_match"] = {"id": "match:legacy-ui-resume", "finished": False,
                                "events": [{"kind": "goal", "minute": 17}]}
        legacy = json.loads(json.dumps({"version": 2, "career": career},
                                       ensure_ascii=False, sort_keys=True))
        migrated = migrate_v2_save(legacy)
        with tempfile.TemporaryDirectory(prefix="esb-p08-sdk-save-") as directory:
            with mock.patch.dict(os.environ, {"TERMSTATION_SAVE_DIR": directory}):
                legacy_game.ts.save(json.loads(migrated.to_json()))
                runtime_save = legacy_game.migrate_save(
                    legacy_game.ts.load(legacy_game.SAVE_DEFAULTS))
                self.assertEqual(runtime_save["_career_adapter_state"].current_match_engine_id,
                                 LEGACY_ENGINE_ID)
                legacy_game._persist(runtime_save, runtime_save["career"])
                persisted_runtime = legacy_game.migrate_save(
                    legacy_game.ts.load(legacy_game.SAVE_DEFAULTS))
                persisted = persisted_runtime["_career_adapter_state"]
                self.assertEqual(persisted.current_match_engine_id, LEGACY_ENGINE_ID)
                self.assertEqual(str(persisted.current_match_id), "match:legacy-ui-resume")
                self.assertEqual(persisted.legacy_save["career"]["live_match"],
                                 legacy["career"]["live_match"])

        active_spatial = start()
        resumed_runtime = legacy_game.migrate_save(sdk_loaded_shape(active_spatial))
        self.assertEqual(
            resumed_runtime["_career_adapter_state"].current_match_engine_id,
            SPATIAL_ENGINE_ID,
        )
        self.assertEqual(
            resumed_runtime["_career_adapter_state"].spatial_match_json,
            active_spatial.spatial_match_json,
        )

        partial_round = legacy_game.new_career("BRP", seed=516)
        home_id, away_id = legacy_game.current_fixture(partial_round)
        partial_round["results"].append({
            "id": "match:partial-spatial-round",
            "season": partial_round["season"],
            "round": partial_round["round"] + 1,
            "home": home_id,
            "away": away_id,
            "home_goals": 0,
            "away_goals": 0,
            "engine_id": SPATIAL_ENGINE_ID,
            "engine_version": 1,
        })
        partial_save = migrate_v2_save(json.loads(json.dumps(
            {"version": 2, "career": partial_round}, sort_keys=True)))
        with self.assertRaisesRegex(ValueError, "career round is not"):
            legacy_game.migrate_save(sdk_loaded_shape(partial_save))

    def test_input_rejections_do_not_mutate_save_and_live_legacy_match_cannot_switch(self):
        legacy, home, away, rules = build_scenario()
        base = migrate_v2_save(legacy)
        before = base.to_json()

        broken_fixture = copy.deepcopy(legacy)
        broken_fixture["career"]["fixtures"]["proof-league"][0] = [
            ("club:not-the-manager", "club:not-the-scheduled-opponent")]
        with self.assertRaisesRegex(ValueError, "exactly one fixture"):
            start(broken_fixture, home_sheet=home, away_sheet=away, rules=rules)

        unavailable = copy.deepcopy(legacy)
        starter_id = str(home.starters[0].profile.player_id)
        unavailable["career"]["players"][starter_id]["injury_until_round"] = 9
        with self.assertRaisesRegex(ValueError, "unavailable through injury"):
            start(unavailable, home_sheet=home, away_sheet=away, rules=rules)

        with self.assertRaisesRegex(ValueError, "exactly match the saved career lineup"):
            start(legacy, home_sheet=replace(home, starters=home.starters[:-1]),
                  away_sheet=away, rules=rules)

        impossible_geometry = STANDARD_RULES.with_overrides(
            "rules:p08-out-of-pitch-v1", goal_half_width_m=35.0)
        with self.assertRaisesRegex(ValueError, "cannot contain"):
            start(legacy, home_sheet=home, away_sheet=away, rules=impossible_geometry)

        live = copy.deepcopy(legacy)
        live["career"]["live_match"] = {"id": "match:old-unfinished", "period": 1}
        live_versioned = migrate_v2_save(live)
        self.assertEqual(live_versioned.current_match_engine_id, LEGACY_ENGINE_ID)
        with self.assertRaisesRegex(ValueError, "legacy match with the legacy engine"):
            start_spatial_career_match(
                live_versioned,
                home_sheet=home,
                away_sheet=away,
                seed=41,
                rules=rules,
            )
        self.assertEqual(base.to_json(), before)
        self.assertEqual(legacy["career"]["players"][starter_id]["injury_until_round"], -1)

    def test_open_play_and_non_kickoff_restart_checkpoints_resume_identically(self):
        legacy, home, away, rules = build_scenario(half_ticks=135_000)
        started = start(legacy, home_sheet=home, away_sheet=away, rules=rules)
        open_checkpoint = advance_spatial_career_match(started, transitions=1)
        open_session = resume_spatial_career_match(open_checkpoint)
        self.assertEqual(open_session.match.phase, MatchPhase.IN_PLAY)
        self.assertIsNone(open_session.match.restart)

        first_copy = VersionedCareerSave.from_json(open_checkpoint.to_json())
        second_copy = VersionedCareerSave.from_json(open_checkpoint.to_json())
        first_future = advance_spatial_career_match(first_copy, transitions=3)
        second_future = advance_spatial_career_match(second_copy, transitions=3)
        self.assertEqual(first_future.to_json(), second_future.to_json())

        restart_session = resume_spatial_career_match(open_checkpoint)
        _award_restart(restart_session.match, RestartKind.THROW_IN, "away",
                       Position2D(36.0, 0.0), reason="p08_resume_probe")
        restart_checkpoint = replace(open_checkpoint,
                                     spatial_match_json=restart_session.to_json())
        restart_loaded = VersionedCareerSave.from_json(restart_checkpoint.to_json())
        restored = resume_spatial_career_match(restart_loaded)
        self.assertEqual(restored.match.phase, MatchPhase.RESTART_READY)
        self.assertEqual(restored.match.restart.kind, RestartKind.THROW_IN)
        after_a = advance_spatial_career_match(restart_loaded, transitions=2)
        after_b = advance_spatial_career_match(
            VersionedCareerSave.from_json(restart_checkpoint.to_json()), transitions=2)
        self.assertEqual(after_a.to_json(), after_b.to_json())

    def test_spatial_checkpoint_resumes_after_matchday_substitution_updates_lineup(self):
        started = start(half_ticks=135_000)
        session = resume_spatial_career_match(started)
        team_id = "home"
        roster = session.match.teams[team_id]
        outgoing = next(
            item for item in session.match.play.players.values()
            if item.team_id == team_id
            and item.profile.primary_role.value != "goalkeeper"
            and item.profile.player_id != session.match.play.possession_id
        )
        incoming = next(item for item in roster.eligible_bench()
                        if item.primary_role.value != "goalkeeper")
        substitute(session.match, outgoing.profile.player_id, incoming.player_id,
                   window_id="sub-window:home:first-half:p17-adapter")

        legacy = copy.deepcopy(started.legacy_save)
        club_id = str(session.binding.home_club_id)
        lineup = legacy["career"]["clubs"][club_id]["lineup"]
        legacy["career"]["clubs"][club_id]["lineup"] = [
            str(incoming.player_id) if player_id == str(outgoing.profile.player_id) else player_id
            for player_id in lineup
        ]
        updated = replace(
            started,
            legacy_save_json=json.dumps(legacy, ensure_ascii=False, allow_nan=False,
                                        sort_keys=True, separators=(",", ":")),
            spatial_match_json=session.to_json(),
        )

        restored = resume_spatial_career_match(updated)
        active_ids = {str(player_id) for player_id, state in restored.match.play.players.items()
                      if state.team_id == team_id}
        self.assertEqual(active_ids, set(legacy["career"]["clubs"][club_id]["lineup"]))
        self.assertIn(incoming.player_id, restored.match.play.players)
        self.assertNotIn(outgoing.profile.player_id, restored.match.play.players)

    def test_resume_rejects_saved_lineup_that_diverges_from_match_roster(self):
        started = start()
        legacy = copy.deepcopy(started.legacy_save)
        session = resume_spatial_career_match(started)
        club_id = str(session.binding.home_club_id)
        lineup = legacy["career"]["clubs"][club_id]["lineup"]
        bench_id = str(session.match.teams["home"].substitutes[0].player_id)
        self.assertNotIn(bench_id, lineup)
        lineup[0] = bench_id
        invalid = replace(
            started,
            legacy_save_json=json.dumps(legacy, ensure_ascii=False, allow_nan=False,
                                        sort_keys=True, separators=(",", ":")),
        )
        with self.assertRaisesRegex(ValueError, "current career lineup disagrees"):
            resume_spatial_career_match(invalid)

    def test_quick_run_and_one_transition_at_a_time_have_exact_match_parity(self):
        started = start()
        quick = run_spatial_career_match(started, maximum_transitions=2_000)
        stepwise = started
        for _ in range(2_000):
            if resume_spatial_career_match(stepwise).match.phase is MatchPhase.FINISHED:
                break
            stepwise = advance_spatial_career_match(stepwise, transitions=1)
        else:
            self.fail("stepwise match exceeded its transition budget")
        self.assertEqual(quick.to_json(), stepwise.to_json())

    def test_own_goal_identity_survives_normalized_career_lineage(self):
        session = resume_spatial_career_match(start())
        own_goal_player = next(
            player_id for player_id, state in session.match.play.players.items()
            if state.team_id == "away"
        )
        event_id = _emit(
            session.match, "goal", None,
            {"own_goal_player_id": str(own_goal_player), "scoring_team_id": "home"},
            {"home_score": 1, "away_score": 0},
        )
        goal_lineages, _events = _lineage(session)
        row = next(item for item in goal_lineages
                   if item["goal_event_id"] == str(event_id))
        self.assertIsNone(row["scorer_id"])
        self.assertEqual(row["own_goal_id"], str(own_goal_player))

    def test_settlement_is_once_only_and_keeps_goal_pass_assist_lineage(self):
        started = start()
        session = resume_spatial_career_match(started)
        players = list(session.match.play.players.values())
        scorer = next(item for item in players if item.team_id == "home")
        assister = next(item for item in players
                        if item.team_id == "home" and item.profile.player_id != scorer.profile.player_id)
        pass_event = _emit(session.match, "pass_completed", assister.profile.player_id,
                           {"target_id": str(scorer.profile.player_id)}, {"completed": True})
        shot_event = _emit(session.match, "shot", scorer.profile.player_id,
                           {"assist_player_id": str(assister.profile.player_id),
                            "assist_event_id": str(pass_event)}, {"saved": False},
                           cause=pass_event, parent=pass_event)
        goal_event = _emit(session.match, "goal", scorer.profile.player_id,
                           {"assist_player_id": str(assister.profile.player_id),
                            "assist_event_id": str(pass_event),
                            "scoring_team_id": "home"}, {"home_score": 1, "away_score": 0},
                           cause=shot_event, parent=pass_event)
        session.match.play.home_score += 1
        injected = replace(started, spatial_match_json=session.to_json())
        finished_save = run_spatial_career_match(injected, maximum_transitions=2_000)
        finished_session = resume_spatial_career_match(finished_save)
        self.assertEqual(finished_session.match.phase, MatchPhase.FINISHED)

        settled, applied = settle_spatial_career_match(finished_save)
        self.assertTrue(applied)
        career = settled.legacy_save["career"]
        result = career["results"][-1]
        home_id = str(finished_session.binding.home_club_id)
        away_id = str(finished_session.binding.away_club_id)
        self.assertEqual(result["engine_id"], SPATIAL_ENGINE_ID)
        self.assertEqual(result["engine_version"], 1)
        self.assertEqual(result["ruleset_id"], finished_session.binding.ruleset_id)
        self.assertEqual(result["ruleset_version"], finished_session.binding.ruleset_version)
        self.assertEqual(result["home_goals"], finished_session.match.home_score)
        self.assertEqual(result["away_goals"], finished_session.match.away_score)
        self.assertEqual(career["table"][home_id]["played"], 1)
        self.assertEqual(career["table"][away_id]["played"], 1)
        self.assertEqual(career["round"], 0)
        self.assertEqual(dict(settled.historical_engine_labels)[result["id"]], SPATIAL_ENGINE_ID)
        self.assertEqual(result["goal_lineages"][0]["goal_event_id"], str(goal_event))
        self.assertEqual(result["goal_lineages"][0]["cause_event_id"], str(shot_event))
        self.assertEqual(result["goal_lineages"][0]["parent_event_id"], str(pass_event))
        lineage_ids = [item["event_id"] for item in result["lineage_events"]]
        lineage_sequences = [item["sequence"] for item in result["lineage_events"]]
        self.assertEqual(lineage_sequences, sorted(lineage_sequences))
        self.assertTrue({str(pass_event), str(shot_event), str(goal_event)} <= set(lineage_ids))
        self.assertEqual(result["stats"]["player"][str(scorer.profile.player_id)]["goals"], 1)
        self.assertEqual(result["stats"]["player"][str(assister.profile.player_id)]["assists"], 1)
        self.assertGreater(career["players"][str(scorer.profile.player_id)]["career_apps"], 0)
        self.assertEqual(career["players"][str(scorer.profile.player_id)]["career_goals"],
                         result["stats"]["player"][str(scorer.profile.player_id)]["goals"])
        self.assertEqual(career["players"][str(assister.profile.player_id)]["career_assists"],
                         result["stats"]["player"][str(assister.profile.player_id)]["assists"])

        repeated, was_applied = settle_spatial_career_match(settled, finished_session)
        self.assertFalse(was_applied)
        self.assertEqual(repeated.to_json(), settled.to_json())
        conflicting_match = copy.deepcopy(finished_session.match)
        conflicting_match.play.home_score += 1
        conflicting_session = replace(finished_session, match=conflicting_match)
        with self.assertRaisesRegex(ValueError, "different result"):
            settle_spatial_career_match(settled, conflicting_session)
        self.assertEqual(settled.legacy_save["career"]["table"][home_id]["played"], 1)

    def test_domain_import_is_headless_and_seeded_probe_repeats_across_processes(self):
        root = pathlib.Path(__file__).resolve().parents[3]
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        script = r'''
import builtins, importlib, io, pathlib, sys
def blocked(*args, **kwargs): raise AssertionError("P08 domain import performed file I/O")
builtins.open = blocked
io.open = blocked
pathlib.Path.open = blocked
importlib.import_module("games.touchline.esb.career_adapter")
assert "curses" not in sys.modules
assert "termstation_ui" not in sys.modules
assert not any(name.startswith("termstation.") for name in sys.modules)
'''
        subprocess.run([sys.executable, "-c", script], cwd=root, env=env,
                       capture_output=True, text=True, check=True)
        command = [sys.executable, "-m", "games.touchline.checks.career_adapter_probe",
                   "--seed", "1729"]
        first = subprocess.run(command, cwd=root, env=env, capture_output=True,
                               text=True, check=True)
        second = subprocess.run(command, cwd=root, env=env, capture_output=True,
                                text=True, check=True)
        self.assertEqual(first.stdout, second.stdout)
        self.assertEqual(json.loads(first.stdout)["engine_id"], SPATIAL_ENGINE_ID)


if __name__ == "__main__":
    unittest.main()
