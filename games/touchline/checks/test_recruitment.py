from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path

from games.touchline.esb.economy.market import (
    MarketBook, MarketCandidate, OfferedRole, PlayerMarketProfile,
    add_candidate, add_player_profile, offer_status,
)
from games.touchline.esb.economy.recruitment import (
    AIRecruitmentPolicy, RecruitmentEvidence, RecruitmentRoute, SquadRoleNeed,
    RecruitmentTerms, plan_ai_recruitment, recruitment_evidence_from_report,
)
from games.touchline.esb.ids import ClubId, EventId, MatchId, PlayerId
from games.touchline.esb.knowledge.scouting import (
    CandidateFinding, EvidenceSlice, Recommendation, RoleProfile, RoleSearchReport,
)
from games.touchline.esb.model import DataProvenance, ProvenanceKind
from games.touchline.esb.people import ReadinessSnapshot
from games.touchline.esb.time import WorldDate

ROOT = Path(__file__).resolve().parents[3]


def day(month: int, value: int) -> WorldDate:
    return WorldDate(date(2026, month, value))


def market(*, fee: int = 20_000, candidate_id: str = "player:target") -> MarketBook:
    state = add_candidate(MarketBook(), MarketCandidate(
        candidate_id, "club:seller", "contract:target", fee, "GBP",
        day(1, 1), day(12, 31),
    ))
    return add_player_profile(state, PlayerMarketProfile(
        candidate_id, 6_000, 8_000, 26, 52, OfferedRole.REGULAR,
        preferred_place_ids=("place:home",), required_policy_tags=("policy:fair",),
        wage_weight_bps=2_000, security_weight_bps=1_500,
        role_weight_bps=2_000, place_weight_bps=1_000,
        policy_weight_bps=1_500, reputation_weight_bps=2_000,
        acceptance_threshold_bps=6_500,
    ))


def policy(**changes: object) -> AIRecruitmentPolicy:
    values: dict[str, object] = {
        "club_id": "club:buyer", "destination_place_id": "place:home",
        "currency": "GBP", "transfer_budget_minor": 30_000,
        "weekly_wage_cap_minor": 10_000, "contract_weeks": 52,
        "club_reputation_bps": 8_000,
        "total_commitment_cap_minor": 500_000,
        "club_policy_tags": ("policy:fair",),
        "minimum_score_bps": 6_000, "minimum_confidence_bps": 4_000,
    }
    values.update(changes)
    return AIRecruitmentPolicy(**values)  # type: ignore[arg-type]


def scouting_inputs(*, as_of: WorldDate, candidate_id: str = "player:target",
                    internal: bool = False, observed: WorldDate | None = None,
                    fit: int = 9_000, readiness: int = 8_500,
                    confidence: int = 9_000, wage: int = 8_000,
                    recommendation: Recommendation = Recommendation.SHORTLIST
                    ) -> tuple[RoleSearchReport, ReadinessSnapshot, RecruitmentTerms]:
    observed_on = observed or day(1, 10)
    rate = fit / 10_000
    attempts = 10
    successes = round(rate * attempts)
    interval_width = (10_000 - confidence) / 10_000
    lower = max(0.0, min(rate - interval_width / 2, 1.0 - interval_width))
    upper = lower + interval_width
    observation_ids = tuple(f"observation:{candidate_id}:{index}" for index in range(attempts))
    event_ids = (EventId(f"event:{candidate_id}:pass-a"), EventId(f"event:{candidate_id}:pass-b"))
    sample = EvidenceSlice(
        MatchId(f"match:{candidate_id}"), observed_on, "staff:buyer-scout",
        successes, attempts, observation_ids, event_ids,
    )
    finding = CandidateFinding(
        candidate_id, successes, attempts, rate, lower, upper, 1,
        (sample,), recommendation, (),
    )
    report = RoleSearchReport(
        f"report:club-buyer:{candidate_id}", ClubId("club:buyer"),
        RoleProfile("role:central-midfielder", "Central midfielder",
                    "metric:pass-completion", 0.7, 8, 1),
        as_of, 180, "observed pass completion", (finding,),
    )
    snapshot = ReadinessSnapshot(
        PlayerId(candidate_id), observed_on, readiness / 10_000, 0.1,
        DataProvenance(ProvenanceKind.MEASURED, "medical:readiness", observed_on),
    )
    terms = RecruitmentTerms(candidate_id, OfferedRole.REGULAR, wage, internal)
    return report, snapshot, terms


def make_plan(policy_value: AIRecruitmentPolicy, needs: tuple[SquadRoleNeed, ...],
              market_value: MarketBook, on: WorldDate, expiry: WorldDate,
              **candidate_options: object):
    report, readiness, terms = scouting_inputs(as_of=on, **candidate_options)  # type: ignore[arg-type]
    return plan_ai_recruitment(
        policy_value, needs, (report,), (readiness,), (terms,), market_value, on, expiry,
    )


class AIRecruitmentTests(unittest.TestCase):
    def test_planner_requires_sourced_typed_reports_and_rejects_future_reports(self) -> None:
        report, readiness, terms = scouting_inputs(as_of=day(1, 12))
        with self.assertRaisesRegex(ValueError, "report from the future"):
            plan_ai_recruitment(
                policy(), (SquadRoleNeed("role:central-midfielder", 1, 2),),
                (replace(report, as_of=day(2, 1)),), (readiness,), (terms,),
                market(), day(1, 12), day(1, 20),
            )

        manually_constructed = RecruitmentEvidence(
            "player:target", "role:central-midfielder", 9_000, 8_500, 9_000,
            day(1, 10), day(1, 9),
            DataProvenance(ProvenanceKind.MEASURED, "medical:readiness", day(1, 9)),
            ("observation:forged",), "report:forged", "club:buyer",
            ("event:forged",), Recommendation.SHORTLIST, OfferedRole.REGULAR, 8_000,
        )
        with self.assertRaisesRegex(TypeError, "RoleSearchReport"):
            plan_ai_recruitment(
                policy(), (SquadRoleNeed("role:central-midfielder", 1, 2),),
                (manually_constructed,), (), (), market(), day(1, 12), day(1, 20),
            )

    def test_external_need_creates_one_visible_market_offer_under_budget(self) -> None:
        before = market()
        plan, updated = make_plan(
            policy(), (SquadRoleNeed("role:central-midfielder", 1, 3, 9_000),),
            before, day(1, 12), day(1, 20),
        )
        self.assertEqual(plan.route, RecruitmentRoute.EXTERNAL_OFFER)
        self.assertEqual(plan.chosen_player_id, "player:target")
        self.assertEqual(plan.considered[0].priority_adjusted_score_bps, 7_987)
        self.assertEqual(plan.considered[0].total_guaranteed_cost_minor, 436_000)
        self.assertEqual(len(updated.offers), 1)
        offer = updated.offers[0]
        self.assertEqual((offer.transfer_fee_minor, offer.weekly_wage_minor, offer.contract_weeks),
                         (20_000, 8_000, 52))
        self.assertEqual(offer_status(updated, offer.offer_id).value, "open")
        self.assertEqual(updated.player_profiles, before.player_profiles)

    def test_internal_candidate_can_be_selected_as_successor_without_a_transfer_offer(self) -> None:
        plan, updated = make_plan(
            policy(), (SquadRoleNeed("role:central-midfielder", 1, 2),),
            MarketBook(), day(1, 12), day(1, 20),
            candidate_id="player:academy", internal=True,
        )
        self.assertEqual(plan.route, RecruitmentRoute.INTERNAL_SUCCESSION)
        self.assertEqual(plan.chosen_player_id, "player:academy")
        self.assertIsNone(plan.offer_id)
        self.assertEqual(updated, MarketBook())

    def test_need_evidence_confidence_and_transfer_wage_budget_are_real_gates(self) -> None:
        no_gap, same_market = make_plan(
            policy(), (SquadRoleNeed("role:central-midfielder", 3, 3),),
            market(), day(1, 12), day(1, 20),
        )
        self.assertEqual(no_gap.route, RecruitmentRoute.NO_ACTION)
        self.assertEqual(same_market.offers, ())

        low_confidence, _ = make_plan(
            policy(), (SquadRoleNeed("role:central-midfielder", 1, 2),),
            market(), day(1, 12), day(1, 20), confidence=1_000,
        )
        self.assertEqual(low_confidence.route, RecruitmentRoute.NO_ACTION)
        self.assertIn("insufficient_evidence_confidence", low_confidence.considered[0].reasons)

        stale, _ = make_plan(
            policy(), (SquadRoleNeed("role:central-midfielder", 1, 2),),
            market(), day(12, 1), day(12, 10), observed=day(3, 1),
        )
        self.assertEqual(stale.route, RecruitmentRoute.NO_ACTION)
        self.assertIn("stale_evidence", stale.considered[0].reasons)

        over_budget, no_offer = make_plan(
            policy(transfer_budget_minor=19_999),
            (SquadRoleNeed("role:central-midfielder", 1, 2),),
            market(), day(1, 12), day(1, 20),
        )
        self.assertEqual(over_budget.route, RecruitmentRoute.NO_ACTION)
        self.assertIn("transfer_budget_exceeded", over_budget.considered[0].reasons)
        self.assertEqual(no_offer.offers, ())

        wage_limited, _ = make_plan(
            policy(weekly_wage_cap_minor=7_999),
            (SquadRoleNeed("role:central-midfielder", 1, 2),),
            market(), day(1, 12), day(1, 20),
        )
        self.assertIn("weekly_wage_cap_exceeded", wage_limited.considered[0].reasons)

    def test_ai_budget_offer_and_competing_existing_offer_are_respected(self) -> None:
        low_term_policy = policy(contract_weeks=20)
        low_term, low_term_book = make_plan(
            low_term_policy, (SquadRoleNeed("role:central-midfielder", 1, 2),),
            market(), day(1, 12), day(1, 20),
        )
        self.assertEqual(low_term.route, RecruitmentRoute.EXTERNAL_OFFER)
        from games.touchline.esb.economy.market import resolve_player_choice, seller_respond
        low_term_market = seller_respond(
            low_term_book, low_term.offer_id, "club:seller", accept=True, on=day(1, 13),
        )
        low_term_market, choice = resolve_player_choice(
            low_term_market, "player:target", day(1, 14),
        )
        self.assertIsNone(choice.chosen_offer_id)
        self.assertIn("term_too_short", choice.appraisals[0].reasons)

        occupied = market()
        from games.touchline.esb.economy.market import TransferOffer, submit_offer
        occupied = submit_offer(occupied, TransferOffer(
            "offer:already-live", "player:target", "club:buyer", "club:seller",
            day(1, 11), day(1, 15), "GBP", 20_000, 8_000, 52,
            OfferedRole.REGULAR, "place:home", ("policy:fair",), 8_000,
        ))
        duplicate, unchanged = make_plan(
            policy(), (SquadRoleNeed("role:central-midfielder", 1, 2),),
            occupied, day(1, 12), day(1, 20),
        )
        self.assertEqual(duplicate.route, RecruitmentRoute.NO_ACTION)
        self.assertIn("buyer_has_unresolved_offer", duplicate.considered[0].reasons)
        self.assertEqual(unchanged, occupied)

    def test_ai_uses_club_scoped_scouting_not_private_player_preferences(self) -> None:
        state = add_candidate(MarketBook(), MarketCandidate(
            "player:target", "club:seller", "contract:target", 20_000,
            "GBP", day(1, 1), day(12, 31),
        ))
        state = add_player_profile(state, PlayerMarketProfile(
            "player:target", 11_000, 12_000, 60, 70, OfferedRole.KEY_PLAYER,
            required_policy_tags=("policy:family-first",),
            wage_weight_bps=3_000, security_weight_bps=2_000,
            role_weight_bps=2_000, place_weight_bps=1_000,
            policy_weight_bps=1_000, reputation_weight_bps=1_000,
        ))
        plan, updated = make_plan(
            policy(), (SquadRoleNeed("role:central-midfielder", 1, 2),),
            state, day(1, 12), day(1, 20),
        )
        self.assertEqual(plan.route, RecruitmentRoute.EXTERNAL_OFFER)
        self.assertEqual(len(updated.offers), 1)
        from games.touchline.esb.economy.market import resolve_player_choice, seller_respond
        updated = seller_respond(updated, plan.offer_id, "club:seller", accept=True, on=day(1, 13))
        declined, choice = resolve_player_choice(updated, "player:target", day(1, 14))
        self.assertIsNone(choice.chosen_offer_id)
        self.assertIn("below_minimum_wage", choice.appraisals[0].reasons)
        self.assertEqual(offer_status(declined, plan.offer_id).value, "player_rejected")

    def test_scouting_report_and_readiness_are_projected_with_full_lineage(self) -> None:
        source_slice = EvidenceSlice(
            MatchId("match:scouting"), day(1, 8), "staff:analyst", 9, 10,
            tuple(f"observation:pass-{index}" for index in range(10)),
            (EventId("event:pass-a"), EventId("event:pass-b")),
        )
        finding = CandidateFinding(
            "player:target", 9, 10, 0.9, 0.595, 0.982, 1,
            (source_slice,), Recommendation.SHORTLIST, (),
        )
        role = RoleProfile("role:central-midfielder", "Central midfielder",
                           "metric:pass-completion", 0.7, 8, 1)
        report = RoleSearchReport(
            "report:club-scouting", ClubId("club:buyer"), role, day(1, 10),
            30, "permitted observed pass completion", (finding,),
        )
        readiness = ReadinessSnapshot(
            PlayerId("player:target"), day(1, 9), 0.85, 0.1,
            DataProvenance(ProvenanceKind.MEASURED, "medical:readiness", day(1, 9)),
        )
        built = recruitment_evidence_from_report(
            report, (readiness,),
            (RecruitmentTerms("player:target", OfferedRole.REGULAR, 8_000),),
        )
        self.assertEqual(len(built), 1)
        self.assertEqual(built[0].role_fit_bps, 9_000)
        self.assertEqual(built[0].readiness_bps, 8_500)
        self.assertEqual(built[0].source_report_id, "report:club-scouting")
        self.assertEqual(built[0].observation_ids, source_slice.source_observation_ids)
        self.assertEqual(built[0].source_event_ids, ("event:pass-a", "event:pass-b"))
        self.assertEqual(built[0].confidence_bps, 6_130)
        self.assertEqual(built[0].observed_on, day(1, 9))
        self.assertEqual(built[0].report_as_of, day(1, 10))
        self.assertEqual(built[0].readiness_sampled_on, day(1, 9))
        self.assertEqual(built[0].readiness_provenance, readiness.provenance)

        selected, _ = make_plan(
            policy(), (SquadRoleNeed("role:central-midfielder", 1, 2),),
            market(), day(1, 12), day(1, 20),
        )
        decision = selected.considered[0]
        self.assertEqual(decision.source_report_as_of, day(1, 12))
        self.assertEqual(decision.readiness_sampled_on, day(1, 10))
        self.assertEqual(decision.readiness_provenance.source, "medical:readiness")

    def test_fresh_process_probe_is_deterministic_and_p15c_import_is_headless(self) -> None:
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        command = [sys.executable, "-m", "games.touchline.checks.recruitment_probe"]
        first = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, check=True)
        second = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, check=True)
        self.assertEqual(first.stdout, second.stdout)
        result = json.loads(first.stdout)
        self.assertEqual(result["route"], "external_offer")
        self.assertEqual(result["player_id"], "player:recruitment-probe")
        self.assertEqual(result["total_cost_minor"], 434_500)

        code = """\\
import builtins
import io
import pathlib
import sys
def blocked(*args, **kwargs):
    raise AssertionError('P15c domain import attempted file access')
builtins.open = blocked
io.open = blocked
pathlib.Path.open = blocked
pathlib.Path.read_text = blocked
pathlib.Path.read_bytes = blocked
import games.touchline.esb.economy.loans
import games.touchline.esb.economy.recruitment
import games.touchline.esb.people.medical_clearance
import games.touchline.esb.world.registration
assert 'curses' not in sys.modules
assert 'termstation_ui' not in sys.modules
"""
        subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, check=True)


if __name__ == "__main__":
    unittest.main()
