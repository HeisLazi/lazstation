"""Fresh-process determinism probe for P15c evidence-bounded AI recruitment."""

from __future__ import annotations

import json
from datetime import date

from games.touchline.esb.economy.market import (
    MarketBook, MarketCandidate, OfferedRole, PlayerMarketProfile,
    add_candidate, add_player_profile,
)
from games.touchline.esb.economy.recruitment import (
    AIRecruitmentPolicy, RecruitmentTerms, SquadRoleNeed, plan_ai_recruitment,
)
from games.touchline.esb.ids import ClubId, EventId, MatchId, PlayerId
from games.touchline.esb.knowledge.scouting import (
    CandidateFinding, EvidenceSlice, Recommendation, RoleProfile, RoleSearchReport,
)
from games.touchline.esb.model import DataProvenance, ProvenanceKind
from games.touchline.esb.people import ReadinessSnapshot
from games.touchline.esb.serialization import dumps
from games.touchline.esb.time import WorldDate


def run_probe() -> dict[str, object]:
    now = WorldDate(date(2026, 10, 6))
    listing = MarketCandidate(
        "player:recruitment-probe", "club:probe-seller", "contract:probe",
        18_500, "GBP", WorldDate(date(2026, 10, 1)), WorldDate(date(2026, 10, 31)),
    )
    market = add_candidate(MarketBook(), listing)
    market = add_player_profile(market, PlayerMarketProfile(
        listing.player_id, 6_000, 8_000, 26, 52, OfferedRole.REGULAR,
        preferred_place_ids=("place:probe",), required_policy_tags=("policy:fair",),
    ))
    policy = AIRecruitmentPolicy(
        "club:probe-buyer", "place:probe", "GBP", 30_000, 9_000,
        52, 8_000, 450_000, ("policy:fair",),
    )
    observations = tuple(f"observation:scout-probe:{index}" for index in range(10))
    sample = EvidenceSlice(
        MatchId("match:scout-probe"), now, "staff:probe-scout", 9, 10,
        observations, (EventId("event:scout-probe"),),
    )
    finding = CandidateFinding(
        listing.player_id, 9, 10, 0.9, 0.85, 0.95, 1, (sample,),
        Recommendation.SHORTLIST, (),
    )
    report = RoleSearchReport(
        "report:scout-probe", ClubId("club:probe-buyer"),
        RoleProfile("role:midfield", "Midfield", "metric:pass-completion", 0.7, 8, 1),
        now, 180, "observed pass completion", (finding,),
    )
    readiness = ReadinessSnapshot(
        PlayerId(listing.player_id), now, 0.85, 0.1,
        DataProvenance(ProvenanceKind.MEASURED, "medical:probe-readiness", now),
    )
    terms = RecruitmentTerms(listing.player_id, OfferedRole.REGULAR, 8_000)
    plan, result = plan_ai_recruitment(
        policy, (SquadRoleNeed("role:midfield", 1, 2, 9_000),),
        (report,), (readiness,), (terms,), market, now, WorldDate(date(2026, 10, 20)),
    )
    return {
        "route": plan.route.value,
        "player_id": plan.chosen_player_id,
        "offer_id": plan.offer_id,
        "score_bps": plan.considered[0].priority_adjusted_score_bps,
        "total_cost_minor": plan.considered[0].total_guaranteed_cost_minor,
        "market": json.loads(dumps(result)),
    }


def main() -> None:
    print(json.dumps(run_probe(), ensure_ascii=False, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
