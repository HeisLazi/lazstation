"""Mechanism tests for P16d-c multi-season archive composition."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path
import tempfile
import unittest

from games.touchline.checks.world_career_probe import season_schedule
from games.touchline.esb.world.archive_series import WorldArchiveSeries
from games.touchline.esb.time import WorldDate


SEED = 271828
WORLD_ID = "world:p16d-career-proof"


class ArchiveSeriesTests(unittest.TestCase):
    def test_invalid_fixture_limit_does_not_create_a_blocking_pending_season(self):
        first = season_schedule(SEED, 2026)
        following = season_schedule(SEED, 2027)
        with tempfile.TemporaryDirectory(prefix="touchline-archive-series-") as directory:
            with WorldArchiveSeries(directory) as series:
                series.initialize(WORLD_ID, SEED)
                with self.assertRaisesRegex(ValueError, "cannot be negative"):
                    series.simulate(first, maximum_fixtures=-1)
                with self.assertRaisesRegex(TypeError, "integer or None"):
                    series.simulate(first, maximum_fixtures=1.5)
                self.assertEqual(
                    series.connection.execute("SELECT COUNT(*) FROM seasons").fetchone()[0],
                    0,
                )
                self.assertEqual(series.simulate(first).pending, 0)
                self.assertEqual(series.simulate(following).pending, 0)

    def test_tampered_complete_status_cannot_skip_unarchived_fixtures(self):
        first = season_schedule(SEED, 2026)
        following = season_schedule(SEED, 2027)
        with tempfile.TemporaryDirectory(prefix="touchline-archive-series-") as directory:
            with WorldArchiveSeries(directory) as series:
                series.initialize(WORLD_ID, SEED)
                self.assertEqual(series.simulate(first, maximum_fixtures=2).pending, 2)
                series.connection.execute(
                    "UPDATE seasons SET status = 'complete' WHERE season_id = ?",
                    (first.season_id,),
                )
                with self.assertRaisesRegex(ValueError, "completed archive-series season"):
                    series.simulate(following)
                self.assertEqual(
                    series.connection.execute("SELECT COUNT(*) FROM seasons").fetchone()[0],
                    1,
                )
                self.assertEqual(series.simulate(first).pending, 0)
                self.assertEqual(series.simulate(following).pending, 0)

    def test_partial_season_resumes_and_new_season_waits_for_completion(self):
        schedule = season_schedule(SEED, 2026)
        with tempfile.TemporaryDirectory(prefix="touchline-archive-series-") as directory:
            with WorldArchiveSeries(directory) as series:
                series.initialize(WORLD_ID, SEED)
                partial = series.simulate(schedule, maximum_fixtures=2)
                self.assertEqual((partial.archived, partial.pending), (2, 2))
                saved_metrics = series.connection.execute(
                    "SELECT status, metrics_json FROM seasons WHERE season_id = ?",
                    (schedule.season_id,),
                ).fetchone()
                self.assertEqual(saved_metrics["status"], "pending")
                self.assertIn('"archived_matches":2', saved_metrics["metrics_json"])
                with self.assertRaisesRegex(ValueError, "pending season"):
                    series.simulate(season_schedule(SEED, 2027))
                resumed = series.simulate(schedule)
                self.assertEqual((resumed.archived, resumed.pending), (4, 0))
                retry = series.simulate(schedule)
                self.assertEqual((retry.archived, retry.pending), (4, 0))
                self.assertEqual(series.seasons(), ((schedule.season_id, "complete", 4, 4),))

    def test_changed_schedule_and_overlapping_or_wrong_identity_reject(self):
        first = season_schedule(SEED, 2026)
        changed_fixture = replace(
            first.fixtures[0],
            scheduled_on=WorldDate(date(2026, 10, 2)),
        )
        changed = replace(first, fixtures=(changed_fixture,) + first.fixtures[1:])
        overlapping = replace(
            season_schedule(SEED, 2027),
            season_id="season:overlapping-proof",
            fixtures=tuple(replace(
                fixture,
                scheduled_on=WorldDate(date(
                    fixture.scheduled_on.day.year - 1,
                    fixture.scheduled_on.day.month,
                    fixture.scheduled_on.day.day,
                )),
            ) for fixture in season_schedule(SEED, 2027).fixtures),
        )
        with tempfile.TemporaryDirectory(prefix="touchline-archive-series-") as directory:
            with WorldArchiveSeries(directory) as series:
                series.initialize(WORLD_ID, SEED)
                series.simulate(first)
                with self.assertRaisesRegex(ValueError, "retry conflicts"):
                    series.simulate(changed)
                with self.assertRaisesRegex(ValueError, "chronological and non-overlapping"):
                    series.simulate(overlapping)
                with self.assertRaisesRegex(ValueError, "world or root seed"):
                    series.simulate(replace(season_schedule(SEED + 1, 2027), season_id="season:wrong-seed"))
            with WorldArchiveSeries(directory) as reopened:
                with self.assertRaisesRegex(ValueError, "different world, seed"):
                    reopened.initialize("world:other", SEED)

    def test_catalog_dates_are_reconciled_and_ids_are_unique_across_seasons(self):
        first = season_schedule(SEED, 2026)
        same_ids_later = replace(
            first,
            season_id="season:reused-match-identities",
            fixtures=tuple(replace(
                fixture,
                scheduled_on=WorldDate(date(
                    fixture.scheduled_on.day.year + 1,
                    fixture.scheduled_on.day.month,
                    fixture.scheduled_on.day.day,
                )),
            ) for fixture in first.fixtures),
        )
        overlapping = replace(
            season_schedule(SEED, 2027),
            season_id="season:tampered-index-overlap",
            fixtures=tuple(replace(
                fixture,
                scheduled_on=WorldDate(date(
                    fixture.scheduled_on.day.year - 1,
                    fixture.scheduled_on.day.month,
                    fixture.scheduled_on.day.day,
                )),
            ) for fixture in season_schedule(SEED, 2027).fixtures),
        )
        with tempfile.TemporaryDirectory(prefix="touchline-archive-series-") as directory:
            with WorldArchiveSeries(directory) as series:
                series.initialize(WORLD_ID, SEED)
                series.simulate(first)
                with self.assertRaisesRegex(ValueError, "fixture IDs must be unique"):
                    series.simulate(same_ids_later)
                series.connection.execute(
                    "UPDATE seasons SET maximum_on = ? WHERE season_id = ?",
                    ("2026-09-30", first.season_id),
                )
                with self.assertRaisesRegex(ValueError, "date index differs"):
                    series.simulate(overlapping)

    def test_cumulative_analytics_and_player_career_span_seasons(self):
        schedules = (season_schedule(SEED, 2026), season_schedule(SEED, 2027))
        player_id = schedules[0].ordered_fixtures[0].home_sheet.starters[0].profile.player_id
        with tempfile.TemporaryDirectory(prefix="touchline-archive-series-") as directory:
            with WorldArchiveSeries(directory) as series:
                series.initialize(WORLD_ID, SEED)
                for schedule in schedules:
                    progress = series.simulate(schedule)
                    self.assertEqual(progress.pending, 0)
                summary = series.player_career_summary(player_id)
                metrics = series.metrics()
                self.assertEqual(metrics.seasons, 2)
                self.assertEqual(metrics.complete_seasons, 2)
                self.assertEqual(metrics.scheduled_fixtures, 8)
                self.assertEqual(metrics.archived_matches, 8)
                self.assertEqual(summary.matchday_selections, 8)
                self.assertEqual(summary.appearances, 8)
                self.assertEqual(len(series.player_match_history(player_id)), 8)
                self.assertGreater(metrics.total_recorded_events, 0)
                self.assertGreater(metrics.player_rows, 0)
                self.assertGreater(metrics.unique_players, 0)
                self.assertGreater(metrics.database_bytes, 0)
                self.assertGreater(metrics.summary_bytes, 0)
                self.assertGreater(metrics.catalog_database_bytes, 0)
                self.assertGreater(metrics.on_disk_bytes, metrics.database_bytes)
                with series.season_archive(schedules[0].season_id) as archive:
                    self.assertEqual(archive.metrics().archived_matches, 4)

    def test_catalog_only_opens_and_creates_storage_explicitly(self):
        with tempfile.TemporaryDirectory(prefix="touchline-archive-series-") as directory:
            root = Path(directory) / "not-created-yet"
            series = WorldArchiveSeries(root)
            self.assertFalse(root.exists())
            with series:
                series.initialize(WORLD_ID, SEED)
            self.assertTrue((root / "archive-series.sqlite3").is_file())


if __name__ == "__main__":
    unittest.main()
