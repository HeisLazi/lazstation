"""Mechanism tests for multi-match scouting, comparison and evidence replay."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path

from games.touchline.checks.scouting_probe import (
    CLUB_ID,
    PLAYER_A,
    PLAYER_B,
    ROLE,
    UNKNOWN,
    _match,
    build_scenario,
)
from games.touchline.esb.ids import ClubId
from games.touchline.esb.knowledge.coverage import observation_task_id, record_match_observations
from games.touchline.esb.knowledge.metrics import CORE_METRICS
from games.touchline.esb.knowledge.model import (
    CoverageLevel,
    ObservationLedger,
    StaffCapacity,
    StaffRole,
    StaffSchedule,
    StaffWorkAssignment,
    assign_staff_work,
    record_observations,
)
from games.touchline.esb.knowledge.scouting import (
    ComparisonOutcome,
    DossierDimensionStatus,
    Recommendation,
    RoleProfile,
    ScoutingQuery,
    compare_candidates,
    build_recruitment_dossier,
    opposition_brief,
    replay_dossier,
    replay_role_search,
    role_search,
)
from games.touchline.esb.serialization import dumps, loads
from games.touchline.esb.time import WorldDate


REPO_ROOT = Path(__file__).resolve().parents[3]


class ScoutingTests(unittest.TestCase):
    def setUp(self):
        self.search, self.brief, self.ledger, self.grants, self.events = build_scenario()

    def test_role_search_aggregates_authorized_matches_with_denominators_and_recommendation(self):
        reliable = next(item for item in self.search.candidates if item.player_id == PLAYER_A)
        variable = next(item for item in self.search.candidates if item.player_id == PLAYER_B)
        unknown = next(item for item in self.search.candidates if item.player_id == UNKNOWN)

        self.assertEqual((reliable.successes, reliable.attempts, reliable.match_count), (14, 16, 2))
        self.assertAlmostEqual(reliable.value, 14 / 16)
        self.assertEqual(reliable.recommendation, Recommendation.SHORTLIST)
        self.assertEqual(len(reliable.slices), 2)
        self.assertEqual(len(reliable.source_observation_ids), 16)
        self.assertEqual(len(reliable.source_event_ids), 48)
        self.assertIn(PLAYER_A, self.search.shortlist_player_ids)

        self.assertEqual((variable.successes, variable.attempts, variable.match_count), (9, 16, 2))
        self.assertEqual(variable.recommendation, Recommendation.REVIEW)
        self.assertIn("match_context_rates_differ", variable.warning_codes)
        self.assertEqual(unknown.attempts, 0)
        self.assertIsNone(unknown.value)
        self.assertEqual(unknown.recommendation, Recommendation.NEEDS_MORE_EVIDENCE)
        self.assertNotIn(UNKNOWN, self.search.shortlist_player_ids)
        self.assertIn("Numerator:", self.search.context)
        self.assertIn("denominator:", self.search.context)

    def test_comparison_keeps_each_match_sample_and_does_not_overclaim_overlap(self):
        query = ScoutingQuery(
            CLUB_ID, WorldDate(date(2026, 2, 21)), (PLAYER_A, PLAYER_B), 90,
        )
        comparison = compare_candidates(query, ROLE, self.ledger, self.grants, CORE_METRICS)
        self.assertEqual(comparison.outcome, ComparisonOutcome.INCONCLUSIVE)
        self.assertEqual(comparison.first.player_id, PLAYER_A)
        self.assertEqual(comparison.second.player_id, PLAYER_B)
        self.assertEqual(len(comparison.first.slices), 2)
        self.assertEqual(len(comparison.second.slices), 2)
        self.assertIn("intervals overlap", comparison.explanation)
        self.assertTrue(comparison.first.source_event_ids)
        self.assertTrue(comparison.second.source_event_ids)

    def test_small_sample_stays_reviewable_and_never_becomes_a_numeric_zero(self):
        thin_events, thin_observations, thin_grant = _match(
            "thin", date(2026, 2, 20), {"player:thin-evidence": (True, True, True, True)},
        )
        del thin_events
        ledger = record_observations(ObservationLedger(), thin_observations)
        query = ScoutingQuery(
            CLUB_ID, WorldDate(date(2026, 2, 20)), ("player:thin-evidence", "player:absent"), 90,
        )
        report = role_search(query, ROLE, ledger, (thin_grant,), CORE_METRICS)
        thin = next(item for item in report.candidates if item.player_id == "player:thin-evidence")
        absent = next(item for item in report.candidates if item.player_id == "player:absent")
        self.assertEqual(thin.recommendation, Recommendation.NEEDS_MORE_EVIDENCE)
        self.assertEqual(thin.attempts, 4)
        self.assertEqual(thin.warning_codes, ("small_sample", "too_few_matches"))
        self.assertNotIn("player:thin-evidence", report.shortlist_player_ids)
        self.assertIsNone(absent.value)
        self.assertIsNone(absent.lower_bound)
        self.assertEqual(absent.attempts, 0)
        with self.assertRaisesRegex(ValueError, "registered metric minimum sample size"):
            role_search(query, replace(ROLE, minimum_attempts=8), ledger,
                        (thin_grant,), CORE_METRICS)

    def test_new_independent_match_evidence_changes_the_recruitment_recommendation(self):
        query = ScoutingQuery(
            CLUB_ID, WorldDate(date(2026, 2, 27)), ("player:emerging-evidence",), 90,
        )
        _, first_observations, first_grant = _match(
            "evidence-first", date(2026, 2, 20),
            {"player:emerging-evidence": (True, True, True, True)},
        )
        first_ledger = record_observations(ObservationLedger(), first_observations)
        first_report = role_search(query, ROLE, first_ledger, (first_grant,), CORE_METRICS)
        self.assertEqual(first_report.candidates[0].recommendation,
                         Recommendation.NEEDS_MORE_EVIDENCE)
        self.assertEqual(first_report.shortlist_player_ids, ())

        _, second_observations, second_grant = _match(
            "evidence-second", date(2026, 2, 27),
            {"player:emerging-evidence": (True, True, True, True,
                                           True, True, True, True)},
        )
        expanded_ledger = record_observations(first_ledger, second_observations)
        expanded_report = role_search(
            query, ROLE, expanded_ledger, (first_grant, second_grant), CORE_METRICS,
        )
        self.assertEqual(expanded_report.candidates[0].recommendation, Recommendation.SHORTLIST)
        self.assertEqual(expanded_report.shortlist_player_ids, ("player:emerging-evidence",))
        self.assertEqual((expanded_report.candidates[0].attempts,
                          expanded_report.candidates[0].match_count), (12, 2))

    def test_staff_evidence_disagreement_remains_visible(self):
        events, _, base_grant = _match(
            "staff-split", date(2026, 2, 18),
            {"player:split-scout": (True, True, True, True, True,
                                     False, False, False, False, False)},
        )
        captured = []
        grants = []
        for label, subset in (("scout-a", events[:15]), ("scout-b", events[15:])):
            grant = replace(
                base_grant,
                grant_id=f"coverage:{label}",
                method=f"separate {label} observation sample",
            )
            capacity = StaffCapacity(f"staff:{label}", CLUB_ID, (StaffRole.OBSERVER,), 8)
            world_date = WorldDate(date(2026, 2, 18))
            assignment = StaffWorkAssignment(
                f"assignment:{label}", observation_task_id(grant), capacity.staff_id,
                CLUB_ID, StaffRole.OBSERVER, world_date, 2,
            )
            schedule = assign_staff_work(StaffSchedule(), capacity, assignment)
            captured.extend(record_match_observations(
                subset, grant, assignment, capacity, schedule, world_date,
            ))
            grants.append(grant)
        ledger = record_observations(ObservationLedger(), tuple(captured))
        role = RoleProfile("role:split", "Observed passer", "pass_completion_rate", 0.5, 10, 1)
        query = ScoutingQuery(
            CLUB_ID, WorldDate(date(2026, 2, 18)), ("player:split-scout",), 90,
        )
        report = role_search(query, role, ledger, tuple(grants), CORE_METRICS)
        finding = report.candidates[0]
        self.assertEqual(finding.attempts, 10)
        self.assertEqual({item.staff_id for item in finding.slices}, {"staff:scout-a", "staff:scout-b"})
        self.assertIn("staff_sample_rates_differ", finding.warning_codes)
        self.assertEqual([item.rate for item in finding.slices], [1.0, 0.0])

    def test_as_of_access_and_expired_or_ungranted_evidence_filter_correctly(self):
        early_query = ScoutingQuery(
            CLUB_ID, WorldDate(date(2026, 2, 14)), (PLAYER_A,), 90,
        )
        early = role_search(early_query, ROLE, self.ledger, self.grants, CORE_METRICS)
        finding = early.candidates[0]
        self.assertEqual((finding.attempts, finding.match_count), (8, 1))
        self.assertEqual(finding.recommendation, Recommendation.NEEDS_MORE_EVIDENCE)
        late_ids = {
            item.observation_id for item in self.ledger.observations
            if item.match_id == self.grants[1].match_id and item.subject_id == PLAYER_A
        }
        self.assertFalse(late_ids.intersection(finding.source_observation_ids))

        no_access = role_search(early_query, ROLE, self.ledger, (), CORE_METRICS)
        self.assertEqual(no_access.candidates[0].attempts, 0)
        self.assertIsNone(no_access.candidates[0].value)

        base_observation = next(
            item for item in self.ledger.observations
            if item.club_id == CLUB_ID and item.match_id == self.grants[0].match_id
            and item.subject_id == PLAYER_A
        )
        expired_grant = replace(
            self.grants[0],
            grant_id="coverage:expired-observation-window",
            expires_on=WorldDate(date(2026, 2, 14)),
        )
        expired_observation = replace(
            base_observation,
            observation_id="observation:recorded-after-coverage-expired",
            coverage_grant_id=expired_grant.grant_id,
            recorded_on=WorldDate(date(2026, 2, 15)),
        )
        expired_ledger = record_observations(ObservationLedger(), (expired_observation,))
        expired_query = ScoutingQuery(
            CLUB_ID, WorldDate(date(2026, 2, 15)), (PLAYER_A,), 90,
        )
        expired = role_search(expired_query, ROLE, expired_ledger,
                              (expired_grant,), CORE_METRICS)
        self.assertEqual(expired.candidates[0].attempts, 0)

        other_grant = replace(
            self.grants[0], grant_id="coverage:other-club", club_id=ClubId("club:other"),
        )
        other_observation = next(
            item for item in self.ledger.observations
            if item.club_id == CLUB_ID and item.match_id == self.grants[0].match_id
            and item.subject_id == PLAYER_A
        )
        other_observation = replace(
            other_observation,
            observation_id="observation:other-club-copy",
            club_id=ClubId("club:other"),
            coverage_grant_id=other_grant.grant_id,
            staff_id="staff:other-club",
        )
        mixed = record_observations(self.ledger, (other_observation,))
        isolated = role_search(early_query, ROLE, mixed, (other_grant,), CORE_METRICS)
        self.assertEqual(isolated.candidates[0].attempts, 0)
        self.assertEqual(isolated.candidates[0].source_event_ids, ())

    def test_opposition_brief_requires_repeated_evidence_and_cites_its_pressure_hypothesis(self):
        self.assertEqual(self.brief.observed_distributor_id, PLAYER_A)
        self.assertEqual(self.brief.attempts, 16)
        self.assertEqual(self.brief.match_count, 2)
        self.assertIsNotNone(self.brief.recommendation)
        self.assertIn(PLAYER_A, self.brief.recommendation)
        self.assertIn("does not reveal", self.brief.caveat)
        self.assertEqual(len(self.brief.source_observation_ids), 16)
        self.assertEqual(len(self.brief.source_event_ids), 48)

        one_match = opposition_brief(
            ScoutingQuery(CLUB_ID, WorldDate(date(2026, 2, 14)), (PLAYER_A,), 90),
            self.ledger, self.grants, minimum_attempts=10, minimum_matches=2,
        )
        self.assertIsNone(one_match.recommendation)
        self.assertEqual(one_match.unavailable_reason, "minimum_evidence_threshold_not_met")
        self.assertEqual(one_match.leading_observed_player_id, PLAYER_A)
        self.assertEqual((one_match.attempts, one_match.match_count), (8, 1))
        self.assertTrue(one_match.source_event_ids)
        self.assertIn("denominator:", one_match.context)

    def test_recruitment_dossier_links_supported_fit_and_keeps_unsupported_dimensions_unknown(self):
        dossier = build_recruitment_dossier(self.search, PLAYER_A)
        dimensions = {item.dimension_id: item for item in dossier.dimensions}
        self.assertEqual(dossier.recommendation, Recommendation.SHORTLIST)
        self.assertEqual(dimensions["role_metric_fit"].status, DossierDimensionStatus.SUPPORTED)
        self.assertEqual(dimensions["match_rate_consistency"].status,
                         DossierDimensionStatus.SUPPORTED)
        self.assertTrue(dimensions["match_rate_consistency"].source_event_ids)
        for dimension_id in ("competitive_adaptation", "tactical_compatibility", "physical_resilience"):
            self.assertEqual(dimensions[dimension_id].status, DossierDimensionStatus.UNKNOWN)
            self.assertTrue(any(word in dimensions[dimension_id].explanation.lower()
                                for word in ("unknown", "not available", "absent", "no authorized")))
            self.assertEqual(dimensions[dimension_id].source_event_ids, ())
        self.assertIn("health", dossier.next_action)
        self.assertEqual(dossier.source_event_ids,
                         next(item for item in self.search.candidates
                              if item.player_id == PLAYER_A).source_event_ids)
        self.assertEqual(replay_dossier(dossier, self.events),
                         replay_role_search(
                             replace(self.search, candidates=(
                                 next(item for item in self.search.candidates
                                      if item.player_id == PLAYER_A),
                             )), self.events,
                         ))

        variable = build_recruitment_dossier(self.search, PLAYER_B)
        variable_dimensions = {item.dimension_id: item for item in variable.dimensions}
        self.assertEqual(variable_dimensions["match_rate_consistency"].status,
                         DossierDimensionStatus.MIXED)

    def test_replay_resolves_exact_cited_events_in_match_chronology_and_rejects_gaps(self):
        replays = replay_role_search(self.search, self.events)
        expected = {
            event_id for candidate in self.search.candidates
            for event_id in candidate.source_event_ids
        }
        actual = {event.event_id for replay in replays for event in replay.events}
        self.assertEqual(actual, expected)
        self.assertEqual(len(actual), len(expected))
        for replay in replays:
            self.assertEqual(
                [(event.match_tick, event.sequence) for event in replay.events],
                sorted((event.match_tick, event.sequence) for event in replay.events),
            )
        with self.assertRaisesRegex(KeyError, "cited replay event is missing"):
            replay_role_search(self.search, tuple(
                event for event in self.events if event.event_id != next(iter(expected))
            ))

    def test_reports_round_trip_and_fresh_process_output_is_stable_and_headless(self):
        restored = loads(dumps(self.search), type(self.search))
        self.assertEqual(restored, self.search)
        self.assertEqual(loads(dumps(self.brief), type(self.brief)), self.brief)
        self.assertEqual(
            loads(dumps(build_recruitment_dossier(self.search, PLAYER_A)),
                  type(build_recruitment_dossier(self.search, PLAYER_A))),
            build_recruitment_dossier(self.search, PLAYER_A),
        )
        with tempfile.TemporaryDirectory(prefix="touchline-p11-pycache-") as pycache:
            env = dict(os.environ)
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            env["PYTHONPYCACHEPREFIX"] = pycache
            command = [sys.executable, "-m", "games.touchline.checks.scouting_probe"]
            first = subprocess.run(command, cwd=REPO_ROOT, env=env, check=True,
                                   capture_output=True, text=True).stdout
            second = subprocess.run(command, cwd=REPO_ROOT, env=env, check=True,
                                     capture_output=True, text=True).stdout
        self.assertEqual(first, second)
        data = json.loads(first)
        candidates = data["role_search"]["payload"]["candidates"]
        self.assertTrue(any(
            item["player_id"] == PLAYER_A and item["recommendation"] == "shortlist"
            for item in candidates
        ))

        code = r'''
import builtins, importlib, io, pathlib, sys
def blocked(*args, **kwargs): raise AssertionError("scouting import performed file I/O")
builtins.open = blocked
io.open = blocked
pathlib.Path.open = blocked
importlib.import_module("games.touchline.esb.knowledge.scouting")
assert "curses" not in sys.modules
assert "termstation_ui" not in sys.modules
assert "games.touchline.main" not in sys.modules
assert not any(name.startswith("termstation.") for name in sys.modules)
'''
        child = subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT,
                               capture_output=True, text=True)
        self.assertEqual(child.returncode, 0, child.stderr)


if __name__ == "__main__":
    unittest.main()
