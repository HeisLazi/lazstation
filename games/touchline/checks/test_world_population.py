"""Mechanism tests for P16d-a player lifecycle and roster continuity."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

from games.touchline.checks.world_population_probe import (
    CLUB_ID,
    START,
    authored_profile,
    candidate_for,
    initial_population,
    population_policy,
)
from games.touchline.esb.content.proof_roster import PROOF_SQUADS
from games.touchline.esb.ids import PlayerId
from games.touchline.esb.model import DataProvenance, PlayerIdentity, ProvenanceKind
from games.touchline.esb.people import PrimaryRole
from games.touchline.esb.time import WorldDate
from games.touchline.esb.world.population import (
    CandidateOutcome,
    IntakeCandidate,
    PlayerPopulationRecord,
    PopulationEventKind,
    PopulationPolicy,
    RetirementHazard,
    WorldPopulationState,
    advance_population,
    create_population_state,
    player_age,
)


ROOT = Path(__file__).resolve().parents[3]
NEXT = WorldDate(date(2027, 10, 1))


def _policy(
    *,
    minimum_squad_size=0,
    minimum_role_counts=(),
    maximum_intake=3,
    maximum_pending=32,
    maximum_candidate_lifetime=3650,
):
    return PopulationPolicy(
        retirement_hazards=(
            RetirementHazard(30, 0.05),
            RetirementHazard(35, 0.20),
            RetirementHazard(39, 0.50),
        ),
        guaranteed_retirement_age=40,
        minimum_intake_age=16,
        maximum_intake_age=23,
        minimum_squad_size=minimum_squad_size,
        minimum_role_counts=tuple(sorted(minimum_role_counts, key=lambda row: row[0].value)),
        maximum_intake_per_club=maximum_intake,
        maximum_pending_candidates_per_club=maximum_pending,
        maximum_candidate_lifetime_days=maximum_candidate_lifetime,
    )


def _record(template, key, born_on, *, propensity=1.0):
    profile = authored_profile(template, key, born_on)
    return PlayerPopulationRecord(profile, START, propensity)


def _candidate(template, key, born_on, *, rank, available=NEXT, expires=None, propensity=1.0):
    profile = authored_profile(template, key, born_on)
    return IntakeCandidate(
        candidate_id=f"candidate:p16d-test:{key}",
        profile=profile,
        available_on=available,
        expires_on=expires or WorldDate(date(2029, 10, 1)),
        selection_rank=rank,
        retirement_propensity=propensity,
    )


class WorldPopulationTests(unittest.TestCase):
    def test_age_uses_completed_calendar_years_and_leap_day_rule(self):
        born_on = date(2004, 2, 29)
        self.assertEqual(player_age(born_on, WorldDate(date(2025, 2, 27))), 20)
        self.assertEqual(player_age(born_on, WorldDate(date(2025, 2, 28))), 21)
        self.assertEqual(player_age(born_on, WorldDate(date(2024, 2, 28))), 19)
        with self.assertRaises(TypeError):
            player_age(datetime(2004, 2, 29), WorldDate(date(2025, 2, 28)))
        with self.assertRaisesRegex(ValueError, "cannot follow"):
            player_age(date(2030, 1, 1), WorldDate(date(2029, 12, 31)))

    def test_population_rejects_missing_and_future_birth_facts(self):
        profile = authored_profile(PROOF_SQUADS[0].players[0], "missing-dob", date(1990, 1, 1))
        missing = replace(profile, identity=PlayerIdentity(profile.player_id))
        with self.assertRaisesRegex(ValueError, "sourced birth date"):
            PlayerPopulationRecord(missing, START)

        future_profile = authored_profile(
            PROOF_SQUADS[0].players[0], "future-dob", date(2030, 1, 1),
        )
        with self.assertRaisesRegex(ValueError, "cannot join before birth"):
            PlayerPopulationRecord(future_profile, START)

    def test_initial_population_rejects_non_authored_profile_evidence(self):
        profile = authored_profile(
            PROOF_SQUADS[0].players[0], "observed-initial", date(1990, 1, 1),
        )
        observed = replace(
            profile,
            provenance=DataProvenance(ProvenanceKind.OBSERVED, "test:observed", START),
        )
        with self.assertRaisesRegex(ValueError, "requires an authored player profile"):
            PlayerPopulationRecord(observed, START)

    def test_intake_rejects_profiles_without_complete_match_capabilities(self):
        profile = authored_profile(
            PROOF_SQUADS[0].players[2], "incomplete-profile", date(2008, 1, 1),
        )
        incomplete = replace(
            profile,
            capabilities=replace(profile.capabilities, capabilities=()),
        )
        with self.assertRaisesRegex(ValueError, "match-ready player profile"):
            IntakeCandidate(
                "candidate:p16d-test:incomplete",
                incomplete,
                NEXT,
                WorldDate(date(2029, 10, 1)),
                1,
            )

    def test_only_next_anniversary_can_advance_and_exact_retry_is_idempotent(self):
        state = initial_population()
        policy = _policy()
        with self.assertRaisesRegex(ValueError, "next annual anniversary"):
            advance_population(state, WorldDate(date(2028, 10, 1)), policy=policy)
        advanced = advance_population(state, NEXT, policy=policy)
        draws_after = advanced.population_random.draws
        self.assertEqual(state.population_random.draws, 0)
        self.assertEqual(draws_after, len(state.players))
        self.assertIs(advance_population(advanced, NEXT, policy=policy), advanced)
        self.assertEqual(advanced.population_random.draws, draws_after)
        with self.assertRaisesRegex(ValueError, "same-date.*conflicts"):
            advance_population(
                advanced, NEXT,
                policy=replace(policy, maximum_intake_per_club=policy.maximum_intake_per_club + 1),
            )

    def test_boundary_receipt_seal_covers_request_source_decisions_and_coverage(self):
        result = advance_population(initial_population(), NEXT, policy=_policy())
        receipt = result.transitions[-1]
        decision = receipt.retirement_decisions[0]
        row = receipt.coverage[0]
        altered_row = replace(
            row,
            active_player_count=row.active_player_count + 1,
            squad_shortfall=max(0, row.minimum_squad_size - row.active_player_count - 1),
        )
        changes = (
            {"request_sha256": "0" * 64},
            {"source_population_sha256": "0" * 64},
            {"retirement_decisions": (replace(decision, age=decision.age + 1),)
             + receipt.retirement_decisions[1:]},
            {"coverage": (altered_row,) + receipt.coverage[1:]},
        )
        for change in changes:
            with self.subTest(change=tuple(change)):
                with self.assertRaisesRegex(ValueError, "sealed evidence"):
                    replace(receipt, **change)

    def test_retirement_probability_records_age_hazard_propensity_and_draw(self):
        low = _record(
            PROOF_SQUADS[0].players[0], "hazard-low", date(1991, 6, 1), propensity=0.5,
        )
        high = _record(
            PROOF_SQUADS[0].players[2], "hazard-high", date(1991, 6, 1), propensity=1.5,
        )
        state = create_population_state(
            "world:p16d-hazard",
            as_of=START,
            seed=112233,
            players=(low, high),
        )
        result = advance_population(state, NEXT, policy=_policy())
        decisions = {item.player_id: item for item in result.transitions[-1].retirement_decisions}
        for record, expected_probability in ((low, 0.10), (high, 0.30)):
            decision = decisions[record.player_id]
            self.assertEqual(decision.age, 36)
            self.assertEqual(decision.base_hazard, 0.20)
            self.assertEqual(decision.retirement_propensity, record.retirement_propensity)
            self.assertAlmostEqual(decision.probability, expected_probability)
            self.assertGreaterEqual(decision.draw, 0.0)
            self.assertLess(decision.draw, 1.0)
            self.assertEqual(decision.retired, decision.draw < expected_probability)
        for event in result.events:
            if event.kind is PopulationEventKind.RETIREMENT:
                self.assertEqual(event.source_id, result.transitions[-1].boundary_id)
                self.assertEqual(event.source_sha256, result.transitions[-1].source_population_sha256)

    def test_guaranteed_retirement_is_recorded_once_and_never_reenters(self):
        old = _record(PROOF_SQUADS[0].players[0], "old-gk", date(1986, 1, 1), propensity=0.0)
        state = create_population_state(
            "world:p16d-retire",
            as_of=START,
            seed=7,
            players=(old,),
        )
        result = advance_population(state, NEXT, policy=_policy())
        retired = next(item for item in result.players if item.player_id == old.player_id)
        self.assertFalse(retired.active)
        self.assertEqual(retired.retired_on, NEXT)
        decision = result.transitions[-1].retirement_decisions[0]
        self.assertEqual(decision.retirement_propensity, 0.0)
        self.assertEqual(decision.probability, 1.0)
        self.assertTrue(decision.retired)
        self.assertEqual(len([event for event in result.events
                              if event.kind is PopulationEventKind.RETIREMENT]), 1)
        reentry = _candidate(
            PROOF_SQUADS[0].players[0], "reentry", date(1986, 1, 1),
            rank=1,
        )
        reentry_player_id = PlayerId(old.player_id)
        reused_identity = replace(reentry.profile.identity, player_id=PlayerId(old.player_id))
        reused_capabilities = replace(
            reentry.profile.capabilities, player_id=PlayerId(old.player_id),
        )
        reused_preference = replace(reentry.profile.preference, player_id=PlayerId(old.player_id))
        reused_readiness = replace(reentry.profile.readiness, player_id=PlayerId(old.player_id))
        reused_tendencies = replace(reentry.profile.tendencies, player_id=PlayerId(old.player_id))
        reentry = replace(
            reentry,
            profile=replace(
                reentry.profile,
                player_id=reentry_player_id,
                identity=reused_identity,
                capabilities=reused_capabilities,
                preference=reused_preference,
                readiness=reused_readiness,
                tendencies=reused_tendencies,
            ),
        )
        with self.assertRaisesRegex(ValueError, "already exists in population history"):
            advance_population(result, WorldDate(date(2028, 10, 1)),
                              policy=_policy(), new_candidates=(reentry,))

    def test_intake_fills_role_need_before_higher_ranked_general_candidate(self):
        keeper = _record(PROOF_SQUADS[0].players[0], "roster-gk", date(2000, 1, 1))
        midfielder = _record(PROOF_SQUADS[0].players[10], "roster-cm", date(2000, 1, 1))
        state = create_population_state(
            "world:p16d-intake",
            as_of=START,
            seed=3,
            players=(keeper, midfielder),
        )
        striker = _candidate(
            PROOF_SQUADS[0].players[14], "rank-one-striker", date(2008, 1, 1), rank=1,
        )
        defender = _candidate(
            PROOF_SQUADS[0].players[2], "rank-two-defender", date(2008, 1, 1), rank=2,
        )
        policy = _policy(
            minimum_squad_size=3,
            minimum_role_counts=(
                (PrimaryRole.CENTER_BACK, 1),
                (PrimaryRole.GOALKEEPER, 1),
            ),
            maximum_intake=1,
        )
        result = advance_population(
            state, NEXT, policy=policy, new_candidates=(striker, defender),
        )
        receipt = result.transitions[-1]
        decisions = {item.candidate_id: item for item in receipt.intake_decisions}
        self.assertEqual(decisions[defender.candidate_id].outcome, CandidateOutcome.ACCEPTED)
        self.assertEqual(decisions[defender.candidate_id].reason, "fills_role_minimum")
        self.assertEqual(decisions[striker.candidate_id].outcome, CandidateOutcome.DEFERRED)
        self.assertEqual(decisions[striker.candidate_id].reason, "annual_intake_cap")
        self.assertIn(striker, result.pending_candidates)
        accepted = next(item for item in result.players if item.player_id == defender.player_id)
        self.assertTrue(accepted.active)
        self.assertEqual(accepted.joined_on, NEXT)
        coverage = next(item for item in receipt.coverage if item.club_id == CLUB_ID)
        self.assertEqual(coverage.active_player_count, 3)
        self.assertEqual(coverage.squad_shortfall, 0)
        self.assertEqual(dict(coverage.role_counts)[PrimaryRole.CENTER_BACK], 1)

    def test_insufficient_intake_is_reported_as_squad_and_role_shortfall(self):
        keeper = _record(PROOF_SQUADS[0].players[0], "retiring-gk", date(1986, 1, 1))
        defender = _record(PROOF_SQUADS[0].players[2], "remaining-cb", date(2000, 1, 1))
        state = create_population_state(
            "world:p16d-shortfall",
            as_of=START,
            seed=9,
            players=(keeper, defender),
        )
        policy = _policy(
            minimum_squad_size=2,
            minimum_role_counts=(
                (PrimaryRole.CENTER_BACK, 1),
                (PrimaryRole.GOALKEEPER, 1),
            ),
            maximum_intake=1,
        )
        result = advance_population(state, NEXT, policy=policy)
        coverage = next(item for item in result.transitions[-1].coverage if item.club_id == CLUB_ID)
        self.assertEqual(coverage.active_player_count, 1)
        self.assertEqual(coverage.squad_shortfall, 1)
        self.assertEqual(dict(coverage.role_shortfalls)[PrimaryRole.GOALKEEPER], 1)
        self.assertEqual(len(result.players), 2)

    def test_candidate_rank_ties_and_consumed_candidates_reject(self):
        keeper = _record(PROOF_SQUADS[0].players[0], "rank-initial-gk", date(2000, 1, 1))
        state = create_population_state(
            "world:p16d-rank",
            as_of=START,
            seed=9,
            players=(keeper,),
        )
        first = _candidate(PROOF_SQUADS[0].players[2], "rank-first", date(2008, 1, 1), rank=1)
        second = _candidate(PROOF_SQUADS[0].players[10], "rank-second", date(2008, 1, 1), rank=1)
        with self.assertRaisesRegex(ValueError, "ranks must be unique"):
            advance_population(state, NEXT, policy=_policy(), new_candidates=(first, second))
        with self.assertRaisesRegex(ValueError, "repeated in the intake request"):
            advance_population(state, NEXT, policy=_policy(), new_candidates=(first, first))

        intake_state = create_population_state(
            "world:p16d-consumed",
            as_of=START,
            seed=9,
            players=(keeper,),
        )
        candidate = _candidate(PROOF_SQUADS[0].players[2], "consumed", date(2008, 1, 1), rank=1)
        intake_policy = _policy(minimum_squad_size=2)
        accepted = advance_population(
            intake_state, NEXT, policy=intake_policy, new_candidates=(candidate,),
        )
        with self.assertRaisesRegex(ValueError, "already consumed"):
            advance_population(
                accepted,
                WorldDate(date(2028, 10, 1)),
                policy=intake_policy,
                new_candidates=(candidate,),
            )

    def test_expired_candidate_id_cannot_be_reused_for_another_player(self):
        keeper = _record(PROOF_SQUADS[0].players[0], "expired-id-gk", date(2000, 1, 1))
        state = create_population_state(
            "world:p16d-expired-id",
            as_of=START,
            seed=19,
            players=(keeper,),
        )
        original = _candidate(
            PROOF_SQUADS[0].players[2],
            "expired-id-original",
            date(2008, 1, 1),
            rank=1,
            expires=WorldDate(date(2028, 9, 30)),
        )
        first = advance_population(
            state, NEXT, policy=_policy(), new_candidates=(original,),
        )
        second = advance_population(
            first, WorldDate(date(2028, 10, 1)), policy=_policy(),
        )
        self.assertEqual(second.pending_candidates, ())
        replacement = _candidate(
            PROOF_SQUADS[0].players[10],
            "expired-id-replacement",
            date(2009, 1, 1),
            rank=1,
            available=WorldDate(date(2028, 10, 1)),
            expires=WorldDate(date(2029, 10, 1)),
        )
        replacement = replace(replacement, candidate_id=original.candidate_id)
        with self.assertRaisesRegex(ValueError, "already recorded in population history"):
            advance_population(
                second, WorldDate(date(2029, 10, 1)), policy=_policy(),
                new_candidates=(replacement,),
            )

    def test_candidate_pool_limits_reject_before_random_draws(self):
        state = initial_population()
        first = _candidate(
            PROOF_SQUADS[0].players[2], "pool-first", date(2008, 1, 1), rank=1,
        )
        second = _candidate(
            PROOF_SQUADS[0].players[10], "pool-second", date(2008, 1, 1), rank=2,
        )
        policy = _policy(maximum_pending=1)
        with self.assertRaisesRegex(ValueError, "pool exceeds"):
            advance_population(
                state, NEXT, policy=policy, new_candidates=(first, second),
            )
        self.assertEqual(state.population_random.draws, 0)

        long_lived = _candidate(
            PROOF_SQUADS[0].players[2],
            "pool-long-lived",
            date(2008, 1, 1),
            rank=1,
            expires=WorldDate(date(2038, 10, 1)),
        )
        with self.assertRaisesRegex(ValueError, "expiry exceeds"):
            advance_population(
                state, NEXT, policy=_policy(), new_candidates=(long_lived,),
            )

    def test_candidate_dates_and_profile_readiness_must_be_valid(self):
        candidate = _candidate(
            PROOF_SQUADS[0].players[2], "backdated", date(2008, 1, 1),
            rank=1, available=WorldDate(date(2026, 9, 30)),
        )
        with self.assertRaisesRegex(ValueError, "cannot be backdated"):
            advance_population(
                initial_population(), NEXT, policy=_policy(), new_candidates=(candidate,),
            )
        with self.assertRaisesRegex(ValueError, "expires before availability"):
            IntakeCandidate(
                "candidate:p16d:test-bad-window",
                candidate.profile,
                NEXT,
                WorldDate(date(2027, 1, 1)),
                1,
            )

    def test_versioned_round_trip_reconciles_events_and_stream_state(self):
        state = initial_population()
        policy = population_policy()
        candidate = candidate_for(
            PrimaryRole.GOALKEEPER,
            boundary=NEXT,
            season_index=1,
            selection_rank=1,
        )
        result = advance_population(
            state, NEXT, policy=policy, new_candidates=(candidate,),
        )
        encoded = result.to_json()
        restored = WorldPopulationState.from_json(encoded)
        self.assertEqual(restored, result)
        self.assertEqual(restored.to_json(), encoded)
        tampered = result.events[0]
        with self.assertRaises(ValueError):
            replace(result, events=(replace(tampered, age=tampered.age + 1),) + result.events[1:])

    def test_30_season_probe_is_deterministic_viable_and_import_is_headless(self):
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONPYCACHEPREFIX"] = "/tmp/touchline-p16d-test-probe-cache"
        command = [sys.executable, "-m", "games.touchline.checks.world_population_probe"]
        first = subprocess.run(
            command, cwd=ROOT, env=env, text=True, capture_output=True, check=True,
        ).stdout
        second = subprocess.run(
            command, cwd=ROOT, env=env, text=True, capture_output=True, check=True,
        ).stdout
        self.assertEqual(first, second)
        result = json.loads(first)
        self.assertEqual(result["seasons"], 30)
        annual = result["annual"]
        self.assertEqual(len(annual), 30)
        self.assertGreater(result["total_retirements"], 0)
        self.assertGreater(result["total_intakes"], 0)
        self.assertTrue(all(row["squad_shortfall"] == 0 for row in annual))
        self.assertTrue(all(row["role_shortfalls"] == 0 for row in annual))
        self.assertIn("no fixtures", result["evidence_boundary"])
        script = (
            "import builtins\n"
            "def blocked(*args, **kwargs):\n"
            "    raise AssertionError('import attempted filesystem I/O')\n"
            "builtins.open = blocked\n"
            "import games.touchline.esb.world.population\n"
        )
        subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )


if __name__ == "__main__":
    unittest.main()
