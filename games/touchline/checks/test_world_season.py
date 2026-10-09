"""Mechanism tests for P16a fixture simulation and durable match analytics."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import json

from games.touchline.esb.content.proof_world import proof_world_schedule
from games.touchline.esb.ids import MatchId
from games.touchline.esb.serialization import SerializationError
from games.touchline.esb.time import WorldDate
from games.touchline.esb.world.archive import (
    ArchiveDetailUnavailable,
    DetailRetentionPolicy,
    MatchdayRole,
    WorldArchiveStore,
    WorldMatchRecord,
)
from games.touchline.esb.world.season import (
    WorldSeasonSchedule,
    fixture_input_sha256,
    fixture_seed,
    immutable_snapshot_json,
    simulate_fixture,
)


class WorldSeasonTests(unittest.TestCase):
    def setUp(self):
        self.schedule = proof_world_schedule()
        self.fixture = self.schedule.ordered_fixtures[0]

    def _temporary_archive(self):
        return tempfile.TemporaryDirectory(prefix="touchline-p16a-test-")

    def test_schedule_is_versioned_and_order_independent(self):
        restored = WorldSeasonSchedule.from_json(self.schedule.to_json())
        self.assertEqual(restored, self.schedule)
        self.assertEqual(
            fixture_seed(restored, restored.ordered_fixtures[0]),
            fixture_seed(self.schedule, self.fixture),
        )
        self.assertEqual(
            fixture_input_sha256(restored.ordered_fixtures[0],
                                 restored.competition(restored.ordered_fixtures[0].competition_id)),
            fixture_input_sha256(self.fixture, self.schedule.competition(self.fixture.competition_id)),
        )
        self.assertEqual(
            tuple(item.fixture_id for item in self.schedule.ordered_fixtures),
            ("fixture:proof-league-01", "fixture:proof-representative-01",
             "fixture:proof-cup-01", "fixture:proof-league-02"),
        )
        reversed_schedule = replace(self.schedule, fixtures=tuple(reversed(self.schedule.fixtures)))
        self.assertEqual(
            tuple(item.fixture_id for item in reversed_schedule.ordered_fixtures),
            tuple(item.fixture_id for item in self.schedule.ordered_fixtures),
        )
        self.assertEqual(fixture_seed(self.schedule, self.fixture), fixture_seed(reversed_schedule, self.fixture))
        self.assertNotEqual(fixture_seed(self.schedule, self.fixture), fixture_seed(
            replace(self.schedule, seed=self.schedule.seed + 1), self.fixture
        ))

    def test_exact_schedule_snapshot_preserves_negative_zero(self):
        original_starters = self.fixture.home_sheet.starters
        first = original_starters[0]
        negative_zero_position = replace(first.motion.position, x_m=-0.0)
        negative_zero_motion = replace(first.motion, position=negative_zero_position)
        negative_zero_player = replace(first, motion=negative_zero_motion)
        negative_zero_sheet = replace(
            self.fixture.home_sheet,
            starters=(negative_zero_player, *original_starters[1:]),
        )
        negative_zero_fixture = replace(self.fixture, home_sheet=negative_zero_sheet)

        self.assertNotEqual(
            immutable_snapshot_json(self.fixture),
            immutable_snapshot_json(negative_zero_fixture),
        )

    def test_schedule_rejects_cross_competition_rest_conflict(self):
        collision = replace(
            self.fixture,
            fixture_id="fixture:proof-same-day-second",
            match_id=MatchId("match:proof-same-day-second"),
            competition_id="competition:proof-representative",
            kickoff_minute=self.fixture.kickoff_minute + 20,
            home_participant_id="nation:north",
            away_participant_id="nation:south",
        )
        with self.assertRaisesRegex(ValueError, "player calendar conflict"):
            WorldSeasonSchedule(
                self.schedule.world_id,
                self.schedule.season_id,
                self.schedule.seed,
                self.schedule.competitions,
                (*self.schedule.fixtures, collision),
            )

    def test_schedule_rejects_fixture_with_unknown_competition_participant(self):
        bad_fixture = replace(self.fixture, home_participant_id="club:unregistered")
        with self.assertRaisesRegex(ValueError, "participants must belong"):
            replace(self.schedule, fixtures=(bad_fixture, *self.schedule.fixtures[1:]))

    def test_schedule_rejects_reused_fixture_or_match_ids(self):
        duplicate = replace(
            self.fixture,
            fixture_id="fixture:proof-league-duplicate",
            match_id=self.fixture.match_id,
            scheduled_on=WorldDate(self.fixture.scheduled_on.day + timedelta(days=2)),
        )
        with self.assertRaisesRegex(ValueError, "repeat fixture or match IDs"):
            replace(self.schedule, fixtures=(*self.schedule.fixtures, duplicate))

    def test_schedule_rejects_invalid_serialized_schema(self):
        text = self.schedule.to_json().replace('"schema_version":1', '"schema_version":2', 1)
        with self.assertRaises(SerializationError):
            WorldSeasonSchedule.from_json(text)

    def test_archived_record_retains_rules_state_events_and_all_matchday_players(self):
        match = simulate_fixture(self.schedule, self.fixture)
        record = WorldMatchRecord.create(self.schedule, self.fixture, match)
        restored_state = record.match_state()
        self.assertEqual(restored_state.events, match.events)
        self.assertEqual(record.event_count, len(match.events))
        self.assertEqual(len(record.player_lines), 22)
        self.assertEqual(sum(line.role is MatchdayRole.UNAVAILABLE for line in record.player_lines), 2)
        self.assertEqual(
            (record.ruleset_id, record.ruleset_version),
            (self.schedule.competition(self.fixture.competition_id).rules.ruleset_id, 1),
        )
        self.assertEqual(len(record.goal_lineage), sum(event.kind == "goal" for event in match.events))

    def test_progress_is_committed_fixture_by_fixture_and_resumes_idempotently(self):
        with self._temporary_archive() as temporary:
            path = Path(temporary) / "world.sqlite3"
            with WorldArchiveStore(path) as archive:
                first = archive.simulate(self.schedule, maximum_fixtures=2)
                self.assertEqual((first.scheduled, first.archived, first.simulated_this_run, first.pending), (4, 2, 2, 2))
            with WorldArchiveStore(path) as archive:
                resumed = archive.simulate(self.schedule)
                self.assertEqual((resumed.archived, resumed.simulated_this_run,
                                  resumed.resumed_this_run, resumed.pending), (4, 2, 2, 0))
                replay = archive.simulate(self.schedule)
                self.assertEqual((replay.simulated_this_run, replay.resumed_this_run), (0, 4))
                metrics = archive.metrics()
                self.assertEqual(metrics.archived_matches, 4)
                self.assertEqual(metrics.detailed_matches, 4)
                self.assertEqual(metrics.retained_events, metrics.total_recorded_events)
                self.assertEqual(metrics.player_rows, 4 * 22)
                self.assertEqual(metrics.unique_players, 22)
                self.assertGreater(metrics.database_bytes, 0)

    def test_full_match_event_rows_reconcile_and_player_history_crosses_competitions(self):
        with self._temporary_archive() as temporary, WorldArchiveStore(Path(temporary) / "world.sqlite3") as archive:
            archive.simulate(self.schedule)
            match_id = self.fixture.match_id
            state = archive.match_state(match_id)
            event_rows = archive.events(match_id)
            self.assertEqual(event_rows, state.events)
            self.assertEqual([item.sequence for item in event_rows], list(range(len(event_rows))))
            self.assertEqual(
                [item.match_tick for item in event_rows],
                sorted(item.match_tick for item in event_rows),
            )
            player_id = self.fixture.home_sheet.starters[0].profile.player_id
            history = archive.player_match_history(player_id)
            self.assertEqual(len(history), 4)
            self.assertEqual({item.competition_id for item in history}, {
                "competition:proof-league", "competition:proof-cup",
                "competition:proof-representative",
            })
            summary = archive.player_career_summary(player_id)
            self.assertEqual(summary.matchday_selections, 4)
            self.assertEqual(summary.appearances, 4)
            self.assertGreater(summary.total_minutes, 0)
            self.assertEqual(archive.player_career_summary(player_id, competition_id="competition:proof-cup").matchday_selections, 1)

    def test_league_table_and_competition_rules_are_taken_from_archived_fixtures(self):
        with self._temporary_archive() as temporary, WorldArchiveStore(Path(temporary) / "world.sqlite3") as archive:
            archive.simulate(self.schedule)
            table = archive.competition_table("competition:proof-league")
            self.assertEqual({row.played for row in table}, {2})
            self.assertEqual(sum(row.points for row in table), 4)
            self.assertEqual(sum(row.goals_for for row in table), sum(row.goals_against for row in table))
            cup = next(item for item in self.schedule.fixtures if item.competition_id == "competition:proof-cup")
            report = archive.match_summary(cup.match_id)
            self.assertEqual(report["ruleset_id"], "rules:p16-proof-world-cup-v1")
            self.assertTrue(report["details_available"])
            with self.assertRaisesRegex(ValueError, "league competition"):
                archive.competition_table("competition:proof-cup")

    def test_custom_rule_snapshot_survives_archive_read_resume_and_retention(self):
        custom_schedule = proof_world_schedule(seed=47, half_ticks=2)
        fixture = custom_schedule.ordered_fixtures[0]
        with self._temporary_archive() as temporary, WorldArchiveStore(Path(temporary) / "world.sqlite3") as archive:
            first = archive.simulate(custom_schedule, maximum_fixtures=1)
            self.assertEqual(first.simulated_this_run, 1)
            self.assertEqual(archive.match_state(fixture.match_id).rules.half_duration_ticks, 2)
            self.assertEqual(archive.match_summary(fixture.match_id)["ruleset_id"],
                             "rules:p16-proof-world-short-v1")
            restored_schedule = WorldSeasonSchedule.from_json(custom_schedule.to_json())
            resumed = archive.simulate(restored_schedule, maximum_fixtures=0)
            self.assertEqual((resumed.simulated_this_run, resumed.resumed_this_run), (0, 1))
            archive.apply_retention(
                DetailRetentionPolicy(maximum_detailed_matches=0),
                WorldDate(custom_schedule.ordered_fixtures[-1].scheduled_on.day + timedelta(days=1)),
            )
            self.assertFalse(archive.match_summary(fixture.match_id)["details_available"])

    def test_retention_prunes_only_full_match_detail_and_keeps_analytics(self):
        with self._temporary_archive() as temporary, WorldArchiveStore(Path(temporary) / "world.sqlite3") as archive:
            archive.simulate(self.schedule)
            before = archive.metrics()
            as_of = WorldDate(self.schedule.ordered_fixtures[-1].scheduled_on.day + timedelta(days=1))
            pruned_by_age = archive.apply_retention(
                DetailRetentionPolicy(maximum_age_days=5), as_of,
            )
            pruned_by_count = archive.apply_retention(
                DetailRetentionPolicy(maximum_detailed_matches=1), as_of,
            )
            self.assertEqual(len(pruned_by_age), 2)
            self.assertEqual(len(pruned_by_count), 1)
            self.assertEqual(archive.apply_retention(DetailRetentionPolicy(maximum_detailed_matches=1), as_of), ())
            after = archive.metrics()
            self.assertEqual(after.archived_matches, before.archived_matches)
            self.assertEqual(after.total_recorded_events, before.total_recorded_events)
            self.assertEqual(after.player_rows, before.player_rows)
            self.assertEqual(after.detailed_matches, 1)
            self.assertLess(after.retained_events, before.retained_events)
            oldest = self.schedule.ordered_fixtures[0]
            self.assertFalse(archive.match_summary(oldest.match_id)["details_available"])
            with self.assertRaises(ArchiveDetailUnavailable):
                archive.match_state(oldest.match_id)
            with self.assertRaises(ArchiveDetailUnavailable):
                archive.events(oldest.match_id)
            player_id = oldest.home_sheet.starters[0].profile.player_id
            self.assertEqual(archive.player_career_summary(player_id).matchday_selections, 4)
            self.assertEqual(len(archive.competition_table("competition:proof-league")), 2)

    def test_append_is_exactly_idempotent_and_rejects_changed_simulation(self):
        with self._temporary_archive() as temporary:
            path = Path(temporary) / "world.sqlite3"
            with WorldArchiveStore(path) as archive:
                archive.initialize(self.schedule)
                match = simulate_fixture(self.schedule, self.fixture)
                record = WorldMatchRecord.create(self.schedule, self.fixture, match)
                self.assertTrue(archive.append(record))
                self.assertFalse(archive.append(record))
                another_seed = replace(self.schedule, seed=self.schedule.seed + 1)
                changed_match = simulate_fixture(another_seed, self.fixture)
                changed_record = WorldMatchRecord.create(another_seed, self.fixture, changed_match)
                with self.assertRaisesRegex(ValueError, "simulation seed does not match"):
                    archive.append(changed_record)
                self.assertEqual(archive.connection.execute("SELECT COUNT(*) FROM archived_matches").fetchone()[0], 1)

    def test_existing_database_rejects_changed_world_schedule(self):
        with self._temporary_archive() as temporary:
            path = Path(temporary) / "world.sqlite3"
            with WorldArchiveStore(path) as archive:
                archive.initialize(self.schedule)
                changed = replace(
                    self.fixture,
                    kickoff_minute=self.fixture.kickoff_minute + 1,
                )
                changed_schedule = replace(self.schedule, fixtures=(changed, *self.schedule.fixtures[1:]))
                with self.assertRaisesRegex(ValueError, "immutable archived season inputs"):
                    archive.initialize(changed_schedule)

    def test_unplayed_competition_definition_is_checked_against_fixture_snapshots(self):
        with self._temporary_archive() as temporary, WorldArchiveStore(Path(temporary) / "world.sqlite3") as archive:
            archive.initialize(self.schedule)
            row = archive.connection.execute(
                "SELECT definition_json FROM world_competitions WHERE competition_id = ?",
                ("competition:proof-league",),
            ).fetchone()
            definition = json.loads(row["definition_json"])
            definition["payload"]["participant_ids"] = ["club:altered-home", "club:altered-away"]
            archive.connection.execute(
                "UPDATE world_competitions SET definition_json = ? WHERE competition_id = ?",
                (json.dumps(definition, sort_keys=True, separators=(",", ":")),
                 "competition:proof-league"),
            )
            with self.assertRaisesRegex(ValueError, "immutable fixture snapshots"):
                archive.competition_table("competition:proof-league")

    def test_failed_event_insert_rolls_back_the_whole_match_transaction(self):
        with self._temporary_archive() as temporary, WorldArchiveStore(Path(temporary) / "world.sqlite3") as archive:
            archive.initialize(self.schedule)
            match = simulate_fixture(self.schedule, self.fixture)
            record = WorldMatchRecord.create(self.schedule, self.fixture, match)
            archive.connection.execute(
                "CREATE TRIGGER reject_first_event BEFORE INSERT ON archived_events "
                "WHEN NEW.sequence = 0 BEGIN SELECT RAISE(ABORT, 'forced event write failure'); END"
            )
            with self.assertRaises(sqlite3.IntegrityError):
                archive.append(record)
            self.assertEqual(archive.connection.execute("SELECT COUNT(*) FROM archived_matches").fetchone()[0], 0)
            self.assertEqual(archive.connection.execute("SELECT COUNT(*) FROM player_match_lines").fetchone()[0], 0)
            self.assertEqual(archive.connection.execute("SELECT COUNT(*) FROM archived_events").fetchone()[0], 0)
            archive.connection.execute("DROP TRIGGER reject_first_event")
            self.assertTrue(archive.append(record))

    def test_event_actor_index_is_verified_against_event_payload(self):
        with self._temporary_archive() as temporary, WorldArchiveStore(Path(temporary) / "world.sqlite3") as archive:
            archive.simulate(self.schedule, maximum_fixtures=1)
            match_id = str(self.fixture.match_id)
            row = archive.connection.execute(
                "SELECT sequence FROM archived_events WHERE match_id = ? AND actor_id IS NOT NULL LIMIT 1",
                (match_id,),
            ).fetchone()
            self.assertIsNotNone(row)
            archive.connection.execute(
                "UPDATE archived_events SET actor_id = 'player:tampered' WHERE match_id = ? AND sequence = ?",
                (match_id, row["sequence"]),
            )
            with self.assertRaisesRegex(ValueError, "actor index does not reconcile"):
                archive.events(match_id)

    def test_event_rows_detect_mutation_and_match_state_hash_detects_mutation(self):
        with self._temporary_archive() as temporary, WorldArchiveStore(Path(temporary) / "world.sqlite3") as archive:
            archive.simulate(self.schedule, maximum_fixtures=1)
            match_id = str(self.fixture.match_id)
            archive.connection.execute(
                "UPDATE archived_events SET tick = tick + 1 WHERE match_id = ? AND sequence = 1",
                (match_id,),
            )
            with self.assertRaisesRegex(ValueError, "event rows do not reconcile"):
                archive.events(match_id)
            with self.assertRaisesRegex(ValueError, "event rows do not reconcile"):
                archive.apply_retention(
                    DetailRetentionPolicy(maximum_detailed_matches=0),
                    WorldDate(self.fixture.scheduled_on.day + timedelta(days=1)),
                )
            self.assertIsNotNone(archive.connection.execute(
                "SELECT match_state_json FROM archived_matches WHERE match_id = ?", (match_id,)
            ).fetchone()[0])
            archive.connection.execute(
                "UPDATE archived_matches SET match_state_json = match_state_json || ' ' WHERE match_id = ?",
                (match_id,),
            )
            with self.assertRaisesRegex(ValueError, "integrity check failed"):
                archive.match_state(match_id)

    def test_resume_rejects_corrupted_replay_instead_of_skipping_it(self):
        with self._temporary_archive() as temporary, WorldArchiveStore(Path(temporary) / "world.sqlite3") as archive:
            archive.simulate(self.schedule, maximum_fixtures=1)
            match_id = str(self.fixture.match_id)
            archive.connection.execute(
                "UPDATE archived_matches SET match_state_json = match_state_json || ' ' WHERE match_id = ?",
                (match_id,),
            )
            with self.assertRaisesRegex(ValueError, "integrity check failed"):
                archive.simulate(self.schedule, maximum_fixtures=1)

    def test_player_and_goal_projections_are_verified_when_read(self):
        with self._temporary_archive() as temporary, WorldArchiveStore(Path(temporary) / "world.sqlite3") as archive:
            archive.simulate(self.schedule, maximum_fixtures=1)
            match_id = str(self.fixture.match_id)
            player_id = str(self.fixture.home_sheet.starters[0].profile.player_id)
            archive.connection.execute(
                "UPDATE player_match_lines SET minutes = 0 WHERE match_id = ? AND player_id = ?",
                (match_id, player_id),
            )
            with self.assertRaisesRegex(ValueError, "player projections do not reconcile"):
                archive.player_career_summary(player_id)

        with self._temporary_archive() as temporary, WorldArchiveStore(Path(temporary) / "world.sqlite3") as archive:
            archive.simulate(self.schedule, maximum_fixtures=1)
            match_id = str(self.fixture.match_id)
            row = archive.connection.execute(
                "SELECT goal_lineage_json FROM archived_matches WHERE match_id = ?", (match_id,)
            ).fetchone()
            envelope = json.loads(row["goal_lineage_json"])
            envelope["payload"]["goals"] = "tampered"
            archive.connection.execute(
                "UPDATE archived_matches SET goal_lineage_json = ? WHERE match_id = ?",
                (json.dumps(envelope, sort_keys=True, separators=(",", ":")), match_id),
            )
            with self.assertRaisesRegex(ValueError, "goal projections do not reconcile"):
                archive.match_summary(match_id)

    def test_projection_integrity_survives_detail_retention(self):
        with self._temporary_archive() as temporary, WorldArchiveStore(Path(temporary) / "world.sqlite3") as archive:
            archive.simulate(self.schedule)
            archive.apply_retention(
                DetailRetentionPolicy(maximum_detailed_matches=0),
                WorldDate(self.schedule.ordered_fixtures[-1].scheduled_on.day + timedelta(days=1)),
            )
            match_id = str(self.fixture.match_id)
            player_id = str(self.fixture.home_sheet.starters[0].profile.player_id)
            archive.connection.execute(
                "UPDATE player_match_lines SET minutes = 0 WHERE match_id = ? AND player_id = ?",
                (match_id, player_id),
            )
            with self.assertRaisesRegex(ValueError, "player projections do not reconcile"):
                archive.player_career_summary(player_id)

    def test_import_is_headless_and_world_probe_is_byte_stable(self):
        root = Path(__file__).resolve().parents[3]
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        script = r'''
import builtins, importlib, io, pathlib, sys
def blocked(*args, **kwargs): raise AssertionError("world import performed file I/O")
builtins.open = blocked
io.open = blocked
pathlib.Path.open = blocked
importlib.import_module("games.touchline.esb.world.season")
importlib.import_module("games.touchline.esb.world.archive")
assert "curses" not in sys.modules
assert "termstation_ui" not in sys.modules
assert not any(name.startswith("termstation.") for name in sys.modules)
'''
        subprocess.run([sys.executable, "-c", script], cwd=root, env=env,
                       capture_output=True, text=True, check=True)
        command = [sys.executable, "-m", "games.touchline.checks.world_sim_probe", "--seed", "321"]
        first = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True, check=True)
        second = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True, check=True)
        self.assertEqual(first.stdout, second.stdout)
        self.assertIn('"progress":[4,4,0]', first.stdout)
        self.assertIn('"competition:proof-representative"', first.stdout)


if __name__ == "__main__":
    unittest.main()
