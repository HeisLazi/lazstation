"""Mechanism tests for P16c league movement and qualification."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace

from games.touchline.checks.competition_progression_probe import SyntheticArchive
from games.touchline.esb.content.proof_progression import (
    CONTINENTAL_CUP,
    DOMESTIC_CUP,
    NATIONAL_FINALS,
    NEXT_TOP_LEAGUE,
    proof_next_season_schedule,
    proof_progression_plan,
    proof_progression_schedule,
)
from games.touchline.esb.time import WorldDate
from games.touchline.esb.world.archive import WorldArchiveStore
from games.touchline.esb.world.progression import (
    IncompleteCompetitionResults,
    RegistrationDeadlineMissed,
    ResultCompletionBasis,
    SeasonProgressionResult,
    UnresolvedTableTie,
    resolve_season_progression,
    validate_next_season_schedule,
)


ROOT = Path(__file__).resolve().parents[3]


class MissingFixtureArchive(SyntheticArchive):
    def __init__(self, schedule, missing_fixture_id):
        super().__init__(schedule)
        self._missing_fixture_id = missing_fixture_id

    def recorded_fixture(self, fixture_id, **kwargs):
        if fixture_id == self._missing_fixture_id:
            return None
        return super().recorded_fixture(fixture_id, **kwargs)


class ConflictingInputArchive(SyntheticArchive):
    def recorded_fixture(self, fixture_id, **kwargs):
        recorded = super().recorded_fixture(fixture_id, **kwargs)
        return ("0" * 64, recorded[1])


class DetailedCompletionArchive(SyntheticArchive):
    def match_summary(self, match_id):
        summary = super().match_summary(match_id)
        summary["details_available"] = True
        return summary

    def match_state(self, match_id):
        return SimpleNamespace(
            play=SimpleNamespace(clock=SimpleNamespace(elapsed_milliseconds=280)),
            events=(
                SimpleNamespace(kind="period_ended", payload={"period": "first_half"}),
                SimpleNamespace(kind="period_ended", payload={"period": "second_half"}),
            ),
        )


class CompetitionProgressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source_schedule = proof_progression_schedule()
        cls.plan = proof_progression_plan()
        cls.result = resolve_season_progression(
            cls.source_schedule, SyntheticArchive(cls.source_schedule), cls.plan,
        )
        cls.target_schedule = proof_next_season_schedule(cls.result, cls.plan)

    def test_PROGRESSION_01_requires_all_source_fixture_results(self):
        missing_fixture = next(
            item for item in self.source_schedule.ordered_fixtures
            if item.competition_id == self.plan.qualification_routes[-1].source_competition_id
        )
        with self.assertRaisesRegex(IncompleteCompetitionResults, missing_fixture.fixture_id):
            resolve_season_progression(
                self.source_schedule,
                MissingFixtureArchive(self.source_schedule, missing_fixture.fixture_id),
                self.plan,
            )

    def test_PROGRESSION_01_empty_sqlite_archive_does_not_advance_or_gain_rows(self):
        with tempfile.TemporaryDirectory(prefix="touchline-p16c-empty-archive-") as temporary:
            with WorldArchiveStore(Path(temporary) / "world.sqlite3") as archive:
                archive.initialize(self.source_schedule)
                before = archive.metrics()
                self.assertEqual(before.archived_matches, 0)
                with self.assertRaises(IncompleteCompetitionResults):
                    resolve_season_progression(self.source_schedule, archive, self.plan)
                self.assertEqual(archive.metrics().archived_matches, 0)

    def test_PROGRESSION_01_rejects_archive_input_fingerprint_mismatch(self):
        with self.assertRaisesRegex(ValueError, "archived result does not match"):
            resolve_season_progression(
                self.source_schedule,
                ConflictingInputArchive(self.source_schedule),
                self.plan,
            )

    def test_TABLE_01_rejects_unresolved_sporting_ties_without_identifier_order(self):
        tied_scores = {
            (item.home_participant_id, item.away_participant_id): (0, 0)
            for item in self.source_schedule.fixtures
        }
        with self.assertRaisesRegex(UnresolvedTableTie, "unresolved sporting tie"):
            resolve_season_progression(
                self.source_schedule,
                SyntheticArchive(self.source_schedule, scores=tied_scores),
                self.plan,
            )

    def test_PYRAMID_01_swaps_configured_places_and_retains_other_clubs(self):
        entrants = {item.competition_id: item.participant_ids for item in self.result.entrants}
        self.assertEqual(
            entrants["competition:proof-tier-one-2027"],
            ("club:lower-dune", "club:top-ash", "club:top-birch"),
        )
        self.assertEqual(
            entrants["competition:proof-tier-two-2027"],
            ("club:lower-elm", "club:lower-flint", "club:top-cinder"),
        )
        decisions = {
            (item.participant_id, item.destination_competition_id): item.kind.value
            for item in self.result.decisions
        }
        self.assertEqual(decisions[("club:lower-dune", "competition:proof-tier-one-2027")], "promoted")
        self.assertEqual(decisions[("club:top-cinder", "competition:proof-tier-two-2027")], "relegated")
        self.assertEqual(decisions[("club:top-birch", "competition:proof-tier-one-2027")], "retained")

    def test_QUALIFY_01_routes_domestic_continental_and_representative_places(self):
        entrants = {item.competition_id: item.participant_ids for item in self.result.entrants}
        self.assertEqual(entrants[DOMESTIC_CUP], ("club:lower-dune", "club:top-ash"))
        self.assertEqual(entrants[CONTINENTAL_CUP], ("club:top-ash", "club:top-birch"))
        self.assertEqual(entrants[NATIONAL_FINALS], ("nation:amber", "nation:birch"))
        qualification_decisions = [
            item for item in self.result.decisions if item.qualification_route_id is not None
        ]
        self.assertTrue(all(item.qualification_purpose is not None for item in qualification_decisions))
        self.assertEqual(len(qualification_decisions), 6)

    def test_DEADLINE_01_rejects_results_after_destination_registration_closes(self):
        late_plan = proof_progression_plan(
            registration_opens_on=date(2026, 10, 15),
            registration_closes_on=date(2026, 11, 4),
            starts_on=date(2026, 12, 1),
        )
        last_national_fixture = max(
            (item for item in self.source_schedule.fixtures
             if item.competition_id == self.plan.qualification_routes[-1].source_competition_id),
            key=lambda item: item.scheduled_on.day,
        )
        late_fixture = replace(last_national_fixture, kickoff_minute=23 * 60 + 50)
        late_schedule = replace(
            self.source_schedule,
            fixtures=tuple(
                late_fixture if item.fixture_id == last_national_fixture.fixture_id else item
                for item in self.source_schedule.fixtures
            ),
        )
        with self.assertRaises(RegistrationDeadlineMissed):
            resolve_season_progression(
                late_schedule,
                SyntheticArchive(late_schedule),
                late_plan,
            )

    def test_DEADLINE_01_retains_match_clock_completion_after_midnight(self):
        last_national_fixture = max(
            (item for item in self.source_schedule.fixtures
             if item.competition_id == self.plan.qualification_routes[-1].source_competition_id),
            key=lambda item: item.scheduled_on.day,
        )
        late_fixture = replace(last_national_fixture, kickoff_minute=23 * 60 + 50)
        late_schedule = replace(
            self.source_schedule,
            fixtures=tuple(
                late_fixture if item.fixture_id == last_national_fixture.fixture_id else item
                for item in self.source_schedule.fixtures
            ),
        )
        late_plan = proof_progression_plan(
            registration_opens_on=date(2026, 10, 15),
            registration_closes_on=date(2026, 11, 5),
            starts_on=date(2026, 12, 1),
        )
        result = resolve_season_progression(
            late_schedule, DetailedCompletionArchive(late_schedule), late_plan,
        )
        evidence = next(
            item for item in result.source_evidence
            if item.competition_id == self.plan.qualification_routes[-1].source_competition_id
        )
        fixture_evidence = next(
            item for item in evidence.fixtures if item.fixture_id == last_national_fixture.fixture_id
        )
        self.assertEqual(fixture_evidence.result_completed_on, WorldDate(date(2026, 11, 4)))
        self.assertIs(fixture_evidence.completion_basis, ResultCompletionBasis.MATCH_STATE)
        self.assertEqual(evidence.final_match_on, WorldDate(date(2026, 11, 4)))

    def test_NEXT_SEASON_01_validates_exact_entrants_and_calendar(self):
        validate_next_season_schedule(self.result, self.plan, self.target_schedule)

        altered = self.target_schedule.competition(NEXT_TOP_LEAGUE)
        altered = replace(
            altered,
            participant_ids=(*altered.participant_ids[:-1], "club:unqualified"),
        )
        altered_schedule = replace(
            self.target_schedule,
            competitions=tuple(
                altered if item.competition_id == NEXT_TOP_LEAGUE else item
                for item in self.target_schedule.competitions
            ),
        )
        with self.assertRaisesRegex(ValueError, "entrants do not reconcile"):
            validate_next_season_schedule(self.result, self.plan, altered_schedule)

        first = self.target_schedule.ordered_fixtures[0]
        too_early = replace(
            first,
            scheduled_on=WorldDate(date(2026, 11, 30)),
        )
        early_schedule = replace(
            self.target_schedule,
            fixtures=tuple(
                too_early if item.fixture_id == first.fixture_id else item
                for item in self.target_schedule.fixtures
            ),
        )
        with self.assertRaisesRegex(ValueError, "precedes the configured start"):
            validate_next_season_schedule(self.result, self.plan, early_schedule)

    def test_NEXT_SEASON_01_reuses_player_rest_validation_across_competitions(self):
        top_league = next(
            item for item in self.target_schedule.fixtures
            if item.competition_id == NEXT_TOP_LEAGUE
        )
        domestic_cup = next(
            item for item in self.target_schedule.fixtures
            if item.competition_id == DOMESTIC_CUP
        )
        congested_cup = replace(domestic_cup, scheduled_on=top_league.scheduled_on)
        with self.assertRaisesRegex(ValueError, "player calendar conflict"):
            replace(
                self.target_schedule,
                fixtures=tuple(
                    congested_cup if item.fixture_id == domestic_cup.fixture_id else item
                    for item in self.target_schedule.fixtures
                ),
            )

    def test_LINEAGE_01_round_trip_preserves_fixture_hashes_and_decisions(self):
        restored = SeasonProgressionResult.from_json(self.result.to_json())
        self.assertEqual(restored, self.result)
        self.assertEqual(restored.result_sha256, self.result.result_sha256)
        all_fixture_ids = {
            item.fixture_id for evidence in restored.source_evidence for item in evidence.fixtures
        }
        self.assertEqual(all_fixture_ids, {
            item.fixture_id for item in self.source_schedule.fixtures
        })
        self.assertTrue(all(len(item.input_sha256) == len(item.state_sha256) == 64
                            for evidence in restored.source_evidence for item in evidence.fixtures))
        tampered = self.result.to_json().replace(self.result.result_sha256, "0" * 64, 1)
        with self.assertRaisesRegex(ValueError, "checksum"):
            SeasonProgressionResult.from_json(tampered)
        invalid_decision = replace(self.result.decisions[0], source_position=999)
        with self.assertRaisesRegex(ValueError, "do not derive"):
            replace(self.result, decisions=(invalid_decision, *self.result.decisions[1:]))

    def test_same_immutable_inputs_produce_same_progression_ids_and_hashes(self):
        repeated = resolve_season_progression(
            self.source_schedule, SyntheticArchive(self.source_schedule), self.plan,
        )
        self.assertEqual(repeated.progression_id, self.result.progression_id)
        self.assertEqual(repeated.result_sha256, self.result.result_sha256)
        self.assertEqual(repeated.decisions, self.result.decisions)

    def test_IMPORT_01_probe_is_fresh_process_deterministic_and_domain_import_is_headless(self):
        environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        with tempfile.TemporaryDirectory(prefix="touchline-p16c-pycache-") as pycache:
            environment["PYTHONPYCACHEPREFIX"] = pycache
            command = [sys.executable, "-m", "games.touchline.checks.competition_progression_probe"]
            first = subprocess.run(
                command, cwd=ROOT, env=environment, capture_output=True, text=True, check=True,
            ).stdout
            second = subprocess.run(
                command, cwd=ROOT, env=environment, capture_output=True, text=True, check=True,
            ).stdout
        self.assertEqual(first, second)
        report = json.loads(first)
        self.assertEqual(
            report["evidence_mode"],
            "controlled archived result projections with maximum-duration fallback",
        )
        self.assertEqual(report["completion_basis_counts"], {
            "match_state": 0,
            "maximum_scheduled_duration": 12,
        })
        self.assertEqual(len(report["decisions"]), 12)
        self.assertTrue(report["target_schedule_validated"])

        script = r'''
import builtins, importlib, io, pathlib, sqlite3, sys
def blocked(*args, **kwargs): raise AssertionError("progression import performed I/O")
builtins.open = blocked
io.open = blocked
pathlib.Path.open = blocked
sqlite3.connect = blocked
importlib.import_module("games.touchline.esb.world.progression")
assert "curses" not in sys.modules
assert "termstation_ui" not in sys.modules
assert not any(name.startswith("termstation.") for name in sys.modules)
'''
        subprocess.run(
            [sys.executable, "-c", script], cwd=ROOT, env=environment,
            capture_output=True, text=True, check=True,
        )


if __name__ == "__main__":
    unittest.main()
