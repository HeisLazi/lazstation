"""Evidence-bounded AI succession and recruitment decisions (P15c)."""

from __future__ import annotations

from dataclasses import dataclass
import math
from enum import Enum

from games.touchline.esb.economy.market import (
    MarketBook, OfferedRole, TransferOffer, offer_cost, offer_status,
    submit_offer, OfferStatus,
)
from games.touchline.esb.ids import derive_id, validate_id
from games.touchline.esb.knowledge.scouting import Recommendation, RoleSearchReport
from games.touchline.esb.model import DataProvenance
from games.touchline.esb.people import ReadinessSnapshot
from games.touchline.esb.time import WorldDate

_BPS = 10_000


@dataclass(frozen=True)
class SquadRoleNeed:
    role_id: str
    current_count: int
    target_count: int
    priority_bps: int = _BPS

    def __post_init__(self) -> None:
        validate_id(self.role_id, kind="AI squad role ID")
        for label, value in (("current role count", self.current_count),
                             ("target role count", self.target_count)):
            if type(value) is not int or value < 0:
                raise ValueError(f"{label} must be a non-negative integer")
        if type(self.priority_bps) is not int or not 1 <= self.priority_bps <= _BPS:
            raise ValueError("role priority must be basis points in [1, 10000]")

    @property
    def gap(self) -> int:
        return max(0, self.target_count - self.current_count)


@dataclass(frozen=True)
class AIRecruitmentPolicy:
    club_id: str
    destination_place_id: str
    currency: str
    transfer_budget_minor: int
    weekly_wage_cap_minor: int
    contract_weeks: int
    club_reputation_bps: int
    total_commitment_cap_minor: int | None = None
    club_policy_tags: tuple[str, ...] = ()
    role_fit_weight_bps: int = 5_000
    readiness_weight_bps: int = 2_500
    evidence_confidence_weight_bps: int = 2_500
    minimum_score_bps: int = 6_000
    minimum_confidence_bps: int = 4_000
    maximum_evidence_age_days: int = 180

    def __post_init__(self) -> None:
        validate_id(self.club_id, kind="AI recruitment club ID")
        validate_id(self.destination_place_id, kind="AI destination place ID")
        if not isinstance(self.currency, str) or len(self.currency) != 3 or not self.currency.isascii() or not self.currency.isalpha() or self.currency.upper() != self.currency:
            raise ValueError("AI recruitment currency must be a three-letter uppercase code")
        for label, value in (("transfer budget", self.transfer_budget_minor),
                             ("weekly wage cap", self.weekly_wage_cap_minor)):
            if type(value) is not int or value < 0:
                raise ValueError(f"{label} must be non-negative minor units")
        if (self.total_commitment_cap_minor is not None
                and (type(self.total_commitment_cap_minor) is not int
                     or self.total_commitment_cap_minor < 0)):
            raise ValueError("total commitment cap must be non-negative minor units")
        if type(self.contract_weeks) is not int or self.contract_weeks <= 0:
            raise ValueError("AI recruitment contract term must be positive weeks")
        if type(self.club_reputation_bps) is not int or not 0 <= self.club_reputation_bps <= _BPS:
            raise ValueError("club reputation must be basis points in [0, 10000]")
        if not isinstance(self.club_policy_tags, tuple):
            raise TypeError("AI club policy tags must be an immutable tuple")
        for tag in self.club_policy_tags:
            validate_id(tag, kind="club policy tag")
        if len(self.club_policy_tags) != len(set(self.club_policy_tags)):
            raise ValueError("club policy tags cannot repeat")
        weights = (self.role_fit_weight_bps, self.readiness_weight_bps,
                   self.evidence_confidence_weight_bps)
        if any(type(value) is not int or value < 0 for value in weights) or sum(weights) != _BPS:
            raise ValueError("AI role/readiness/evidence weights must total 10000 basis points")
        for label, value in (("minimum score", self.minimum_score_bps),
                             ("minimum evidence confidence", self.minimum_confidence_bps)):
            if type(value) is not int or not 0 <= value <= _BPS:
                raise ValueError(f"{label} must be basis points in [0, 10000]")
        if type(self.maximum_evidence_age_days) is not int or self.maximum_evidence_age_days < 0:
            raise ValueError("evidence age limit must be a non-negative number of days")


@dataclass(frozen=True)
class RecruitmentEvidence:
    player_id: str
    role_id: str
    role_fit_bps: int
    readiness_bps: int
    confidence_bps: int
    report_as_of: WorldDate
    readiness_sampled_on: WorldDate
    readiness_provenance: DataProvenance
    observation_ids: tuple[str, ...]
    source_report_id: str
    source_club_id: str
    source_event_ids: tuple[str, ...]
    scout_recommendation: Recommendation
    offered_role: OfferedRole
    requested_weekly_wage_minor: int
    internal_candidate: bool = False

    def __post_init__(self) -> None:
        validate_id(self.player_id, kind="recruitment candidate ID")
        validate_id(self.role_id, kind="recruitment candidate role ID")
        for label, value in (("role fit", self.role_fit_bps), ("readiness", self.readiness_bps),
                             ("scouting confidence", self.confidence_bps)):
            if type(value) is not int or not 0 <= value <= _BPS:
                raise ValueError(f"{label} must be basis points in [0, 10000]")
        if (not isinstance(self.report_as_of, WorldDate)
                or not isinstance(self.readiness_sampled_on, WorldDate)):
            raise TypeError("recruitment evidence requires distinct P10 and P09 dates")
        if self.readiness_sampled_on > self.report_as_of:
            raise ValueError("recruitment readiness cannot postdate its scouting report")
        if not isinstance(self.readiness_provenance, DataProvenance):
            raise TypeError("recruitment evidence requires P09 readiness provenance")
        if not isinstance(self.observation_ids, tuple) or not self.observation_ids:
            raise ValueError("recruitment evidence requires source observation IDs")
        for observation_id in self.observation_ids:
            validate_id(observation_id, kind="recruitment evidence observation ID")
        if len(self.observation_ids) != len(set(self.observation_ids)):
            raise ValueError("recruitment evidence cannot repeat an observation")
        validate_id(self.source_report_id, kind="source scouting report ID")
        validate_id(self.source_club_id, kind="source scouting club ID")
        if not isinstance(self.source_event_ids, tuple) or not self.source_event_ids:
            raise ValueError("recruitment evidence requires source match event IDs")
        for source_event_id in self.source_event_ids:
            validate_id(source_event_id, kind="recruitment source event ID")
        if len(self.source_event_ids) != len(set(self.source_event_ids)):
            raise ValueError("recruitment evidence cannot repeat source events")
        if not isinstance(self.scout_recommendation, Recommendation):
            raise TypeError("recruitment evidence requires its scouting recommendation")
        if not isinstance(self.offered_role, OfferedRole):
            raise TypeError("recruitment offer role must be registered")
        if type(self.requested_weekly_wage_minor) is not int or self.requested_weekly_wage_minor < 0:
            raise ValueError("candidate weekly wage request must be non-negative minor units")
        if type(self.internal_candidate) is not bool:
            raise TypeError("internal candidate marker must be boolean")

    @property
    def observed_on(self) -> WorldDate:
        """Oldest top-level source date used for conservative freshness gating."""
        return min(self.report_as_of, self.readiness_sampled_on)


class RecruitmentRoute(str, Enum):
    INTERNAL_SUCCESSION = "internal_succession"
    EXTERNAL_OFFER = "external_offer"
    NO_ACTION = "no_action"


@dataclass(frozen=True)
class CandidateDecision:
    player_id: str
    role_id: str
    source_report_id: str
    source_observation_ids: tuple[str, ...]
    source_event_ids: tuple[str, ...]
    source_report_as_of: WorldDate
    readiness_sampled_on: WorldDate
    readiness_provenance: DataProvenance
    raw_score_bps: int
    priority_adjusted_score_bps: int
    total_guaranteed_cost_minor: int
    evidence_age_days: int
    internal_candidate: bool
    eligible: bool
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        validate_id(self.player_id, kind="recruitment decision player ID")
        validate_id(self.role_id, kind="recruitment decision role ID")
        validate_id(self.source_report_id, kind="decision source report ID")
        if (not isinstance(self.source_observation_ids, tuple) or not self.source_observation_ids
                or not isinstance(self.source_event_ids, tuple) or not self.source_event_ids):
            raise ValueError("recruitment decision must retain observation and event lineage")
        for value in self.source_observation_ids + self.source_event_ids:
            validate_id(value, kind="recruitment decision source ID")
        if (not isinstance(self.source_report_as_of, WorldDate)
                or not isinstance(self.readiness_sampled_on, WorldDate)):
            raise TypeError("recruitment decision must retain distinct P10 and P09 dates")
        if not isinstance(self.readiness_provenance, DataProvenance):
            raise TypeError("recruitment decision must retain P09 readiness provenance")
        for label, value in (("raw decision score", self.raw_score_bps),
                             ("priority-adjusted decision score", self.priority_adjusted_score_bps)):
            if type(value) is not int or not 0 <= value <= _BPS:
                raise ValueError(f"{label} must be basis points in [0, 10000]")
        if type(self.total_guaranteed_cost_minor) is not int or self.total_guaranteed_cost_minor < 0:
            raise ValueError("recruitment guaranteed cost must be non-negative minor units")
        if type(self.evidence_age_days) is not int or self.evidence_age_days < 0:
            raise ValueError("recruitment evidence age must be non-negative days")
        if type(self.internal_candidate) is not bool:
            raise TypeError("recruitment decision must state whether the player is internal")
        if type(self.eligible) is not bool or not isinstance(self.reasons, tuple):
            raise TypeError("recruitment decision requires eligibility and immutable reason codes")
        if self.eligible != (not self.reasons):
            raise ValueError("eligible recruitment decisions cannot contain blocking reasons")


@dataclass(frozen=True)
class AIRecruitmentPlan:
    plan_id: str
    club_id: str
    planned_on: WorldDate
    route: RecruitmentRoute
    chosen_player_id: str | None
    chosen_role_id: str | None
    offer_id: str | None
    considered: tuple[CandidateDecision, ...]
    reason: str

    def __post_init__(self) -> None:
        validate_id(self.plan_id, kind="AI recruitment plan ID")
        validate_id(self.club_id, kind="AI recruitment club ID")
        if not isinstance(self.planned_on, WorldDate) or not isinstance(self.route, RecruitmentRoute):
            raise TypeError("AI recruitment plan requires a date and route")
        for value, label in ((self.chosen_player_id, "chosen player ID"),
                             (self.chosen_role_id, "chosen role ID"), (self.offer_id, "offer ID")):
            if value is not None:
                validate_id(value, kind=label)
        if not isinstance(self.considered, tuple) or any(not isinstance(item, CandidateDecision) for item in self.considered):
            raise TypeError("AI recruitment evidence must be an immutable decision tuple")
        if len({item.player_id for item in self.considered}) != len(self.considered):
            raise ValueError("AI recruitment plan cannot repeat a player decision")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("AI recruitment plan requires an explanation")
        if self.route is RecruitmentRoute.NO_ACTION:
            if (self.chosen_player_id is not None or self.chosen_role_id is not None
                    or self.offer_id is not None or any(item.eligible for item in self.considered)):
                raise ValueError("no-action plans cannot omit an eligible choice")
            expected_plan_id = derive_id(
                "ai-recruitment-plan", "p15c-recruitment-v1",
                self.club_id, self.planned_on.isoformat, "none",
            )
        else:
            if self.chosen_player_id is None or self.chosen_role_id is None:
                raise ValueError("recruitment choice needs a player and role")
            selected = next((item for item in self.considered
                             if item.player_id == self.chosen_player_id), None)
            if (selected is None or not selected.eligible or selected.role_id != self.chosen_role_id
                    or selected.internal_candidate != (self.route is RecruitmentRoute.INTERNAL_SUCCESSION)):
                raise ValueError("recruitment plan choice does not match an eligible candidate")
            expected_plan_id = derive_id(
                "ai-recruitment-plan", "p15c-recruitment-v1",
                self.club_id, self.planned_on.isoformat, self.chosen_player_id,
            )
            if self.route is RecruitmentRoute.EXTERNAL_OFFER:
                expected_offer_id = derive_id(
                    "transfer-offer", "p15c-ai-recruitment-v1", self.club_id,
                    self.chosen_player_id, self.planned_on.isoformat, self.chosen_role_id,
                )
                if self.offer_id != expected_offer_id:
                    raise ValueError("external recruitment plan offer ID does not match its selected player")
        if self.plan_id != expected_plan_id:
            raise ValueError("recruitment plan ID does not match its selected decision")
        if self.route is RecruitmentRoute.EXTERNAL_OFFER and self.offer_id is None:
            raise ValueError("external recruitment plan requires an offer reference")
        if self.route is not RecruitmentRoute.EXTERNAL_OFFER and self.offer_id is not None:
            raise ValueError("only an external recruitment plan can contain an offer")


def _age_days(now: WorldDate, then: WorldDate) -> int:
    return (now.day - then.day).days


@dataclass(frozen=True)
class RecruitmentTerms:
    player_id: str
    offered_role: OfferedRole
    requested_weekly_wage_minor: int
    internal_candidate: bool = False

    def __post_init__(self) -> None:
        validate_id(self.player_id, kind="candidate offer-terms player ID")
        if not isinstance(self.offered_role, OfferedRole):
            raise TypeError("candidate offer terms require a registered squad role")
        if type(self.requested_weekly_wage_minor) is not int or self.requested_weekly_wage_minor < 0:
            raise ValueError("candidate wage request must be non-negative minor units")
        if type(self.internal_candidate) is not bool:
            raise TypeError("internal candidate marker must be boolean")


def recruitment_evidence_from_report(
    report: RoleSearchReport,
    readiness: tuple[ReadinessSnapshot, ...],
    terms: tuple[RecruitmentTerms, ...],
) -> tuple[RecruitmentEvidence, ...]:
    """Project only source-backed P10 role findings and dated P09 readiness.

    The role-fit component is that report's observed metric rate, not hidden
    ability or a generalized talent score. Confidence is a documented precision
    proxy derived from the report's uncertainty interval.
    """
    if not isinstance(report, RoleSearchReport):
        raise TypeError("AI recruitment evidence must come from a RoleSearchReport")
    if not isinstance(readiness, tuple) or any(not isinstance(item, ReadinessSnapshot) for item in readiness):
        raise TypeError("AI recruitment readiness must use dated P09 snapshots")
    if not isinstance(terms, tuple) or any(not isinstance(item, RecruitmentTerms) for item in terms):
        raise TypeError("AI recruitment terms must be immutable RecruitmentTerms records")
    readiness_by_player = {str(item.player_id): item for item in readiness}
    terms_by_player = {item.player_id: item for item in terms}
    if len(readiness_by_player) != len(readiness) or len(terms_by_player) != len(terms):
        raise ValueError("recruitment evidence inputs cannot repeat player IDs")
    result: list[RecruitmentEvidence] = []
    for finding in report.candidates:
        if finding.value is None or finding.lower_bound is None or finding.upper_bound is None:
            continue
        observation_ids = finding.source_observation_ids
        event_ids = tuple(str(item) for item in finding.source_event_ids)
        snapshot = readiness_by_player.get(finding.player_id)
        candidate_terms = terms_by_player.get(finding.player_id)
        if not observation_ids or not event_ids or snapshot is None or candidate_terms is None:
            continue
        if snapshot.sampled_on > report.as_of:
            raise ValueError("recruitment report cannot use future readiness")
        fit_bps = int(math.floor(finding.value * _BPS + 0.5))
        interval_width = finding.upper_bound - finding.lower_bound
        confidence_bps = int(math.floor((1.0 - interval_width) * _BPS + 0.5))
        readiness_bps = int(math.floor(snapshot.match_readiness * _BPS + 0.5))
        result.append(RecruitmentEvidence(
            finding.player_id, report.role.role_id, fit_bps, readiness_bps,
            confidence_bps, report.as_of, snapshot.sampled_on, snapshot.provenance, observation_ids,
            report.report_id, str(report.club_id), event_ids, finding.recommendation,
            candidate_terms.offered_role, candidate_terms.requested_weekly_wage_minor,
            candidate_terms.internal_candidate,
        ))
    return tuple(result)


def plan_ai_recruitment(
    policy: AIRecruitmentPolicy,
    needs: tuple[SquadRoleNeed, ...],
    reports: tuple[RoleSearchReport, ...],
    readiness: tuple[ReadinessSnapshot, ...],
    terms: tuple[RecruitmentTerms, ...],
    market: MarketBook,
    on: WorldDate,
    offer_expires_on: WorldDate,
) -> tuple[AIRecruitmentPlan, MarketBook]:
    """Plan from typed P10 reports, P09 readiness and explicit offer terms."""
    if not isinstance(reports, tuple) or any(not isinstance(item, RoleSearchReport) for item in reports):
        raise TypeError("AI recruitment requires immutable P10 RoleSearchReport records")
    if len({item.report_id for item in reports}) != len(reports):
        raise ValueError("AI recruitment input cannot repeat a scouting report")
    if not isinstance(on, WorldDate):
        raise TypeError("AI recruitment requires an explicit planning date")
    if any(report.as_of > on for report in reports):
        raise ValueError("AI recruitment cannot use a scouting report from the future")
    if not isinstance(readiness, tuple) or any(not isinstance(item, ReadinessSnapshot) for item in readiness):
        raise TypeError("AI recruitment requires immutable P09 readiness snapshots")
    if not isinstance(terms, tuple) or any(not isinstance(item, RecruitmentTerms) for item in terms):
        raise TypeError("AI recruitment requires immutable RecruitmentTerms")
    evidence = tuple(
        item
        for report in reports
        for item in recruitment_evidence_from_report(report, readiness, terms)
    )
    return _plan_ai_recruitment_from_evidence(
        policy, needs, evidence, market, on, offer_expires_on,
    )


def _plan_ai_recruitment_from_evidence(
    policy: AIRecruitmentPolicy,
    needs: tuple[SquadRoleNeed, ...],
    evidence: tuple[RecruitmentEvidence, ...],
    market: MarketBook,
    on: WorldDate,
    offer_expires_on: WorldDate,
) -> tuple[AIRecruitmentPlan, MarketBook]:
    """Select one succession path or submit one realistic market offer.

    The selection formula is visible: weighted role fit, readiness and scout
    confidence, then role priority. It considers only current, sourced reports
    and constrains fees/wages by the AI club's supplied budgets.
    """
    if not isinstance(policy, AIRecruitmentPolicy) or not isinstance(market, MarketBook):
        raise TypeError("AI recruitment requires a policy and MarketBook")
    if not isinstance(on, WorldDate) or not isinstance(offer_expires_on, WorldDate):
        raise TypeError("AI recruitment requires explicit dates")
    if offer_expires_on < on:
        raise ValueError("AI offer expiry precedes its submission")
    if not isinstance(needs, tuple) or any(not isinstance(item, SquadRoleNeed) for item in needs):
        raise TypeError("AI role needs must be an immutable SquadRoleNeed tuple")
    if len({item.role_id for item in needs}) != len(needs):
        raise ValueError("AI recruitment role needs cannot repeat a role")
    if not isinstance(evidence, tuple) or any(not isinstance(item, RecruitmentEvidence) for item in evidence):
        raise TypeError("AI recruitment reports must be immutable RecruitmentEvidence records")
    if len({item.player_id for item in evidence}) != len(evidence):
        raise ValueError("AI recruitment input cannot repeat a player")
    active_needs = {item.role_id: item for item in needs if item.gap > 0}
    eligible_decisions: list[tuple[CandidateDecision, RecruitmentEvidence, SquadRoleNeed, int]] = []
    decisions: list[CandidateDecision] = []
    listings = {item.player_id: item for item in market.candidates}
    prepared_offers: dict[str, TransferOffer] = {}
    for candidate in evidence:
        need = active_needs.get(candidate.role_id)
        if need is None:
            continue
        age = _age_days(on, candidate.observed_on)
        raw_score = (
            candidate.role_fit_bps * policy.role_fit_weight_bps
            + candidate.readiness_bps * policy.readiness_weight_bps
            + candidate.confidence_bps * policy.evidence_confidence_weight_bps
        ) // _BPS
        adjusted = raw_score * need.priority_bps // _BPS
        reasons: list[str] = []
        if age < 0:
            reasons.append("future_dated_evidence")
        elif age > policy.maximum_evidence_age_days:
            reasons.append("stale_evidence")
        if candidate.confidence_bps < policy.minimum_confidence_bps:
            reasons.append("insufficient_evidence_confidence")
        if candidate.source_club_id != policy.club_id:
            reasons.append("evidence_from_another_club")
        if candidate.scout_recommendation is not Recommendation.SHORTLIST:
            reasons.append("scouting_report_does_not_shortlist_candidate")
        if adjusted < policy.minimum_score_bps:
            reasons.append("below_recruitment_threshold")
        listing = listings.get(candidate.player_id)
        total_cost = 0
        if candidate.internal_candidate:
            if listing is not None:
                reasons.append("internal_player_cannot_be_market_listed")
            if candidate.requested_weekly_wage_minor > policy.weekly_wage_cap_minor:
                reasons.append("weekly_wage_cap_exceeded")
            total_cost = candidate.requested_weekly_wage_minor * policy.contract_weeks
        else:
            if listing is None:
                reasons.append("external_candidate_missing_market_listing")
            else:
                if listing.currency != policy.currency:
                    reasons.append("currency_mismatch")
                if listing.current_club_id == policy.club_id:
                    reasons.append("player_already_belongs_to_club")
                if listing.asking_fee_minor > policy.transfer_budget_minor:
                    reasons.append("transfer_budget_exceeded")
                if candidate.requested_weekly_wage_minor > policy.weekly_wage_cap_minor:
                    reasons.append("weekly_wage_cap_exceeded")
                total_cost = listing.asking_fee_minor + candidate.requested_weekly_wage_minor * policy.contract_weeks
                if (policy.total_commitment_cap_minor is not None
                        and total_cost > policy.total_commitment_cap_minor):
                    reasons.append("total_commitment_budget_exceeded")
                existing_player_offers = [item for item in market.offers
                                          if item.player_id == candidate.player_id]
                statuses = [offer_status(market, item.offer_id) for item in existing_player_offers]
                if any(status is OfferStatus.PLAYER_ACCEPTED for status in statuses):
                    reasons.append("player_already_accepted_another_offer")
                elif any(item.buyer_club_id == policy.club_id and status in
                         (OfferStatus.OPEN, OfferStatus.SELLER_ACCEPTED)
                         for item, status in zip(existing_player_offers, statuses)):
                    reasons.append("buyer_has_unresolved_offer")
                candidate_expiry = min(offer_expires_on, listing.expires_on)
                if on < listing.available_on or candidate_expiry < on:
                    reasons.append("listing_not_open")
                else:
                    prepared_offers[candidate.player_id] = TransferOffer(
                        derive_id("transfer-offer", "p15c-ai-recruitment-v1", policy.club_id,
                                  candidate.player_id, on.isoformat, need.role_id),
                        candidate.player_id, policy.club_id, listing.current_club_id,
                        on, candidate_expiry, policy.currency, listing.asking_fee_minor,
                        candidate.requested_weekly_wage_minor, policy.contract_weeks,
                        candidate.offered_role, policy.destination_place_id,
                        policy.club_policy_tags, policy.club_reputation_bps,
                    )
        if (candidate.internal_candidate and policy.total_commitment_cap_minor is not None
                and total_cost > policy.total_commitment_cap_minor):
            reasons.append("total_commitment_budget_exceeded")
        ordered = tuple(dict.fromkeys(reasons))
        decision = CandidateDecision(candidate.player_id, candidate.role_id,
                                     candidate.source_report_id, candidate.observation_ids,
                                     candidate.source_event_ids, candidate.report_as_of,
                                     candidate.readiness_sampled_on, candidate.readiness_provenance,
                                     raw_score,
                                     adjusted, total_cost, max(age, 0),
                                     candidate.internal_candidate, not ordered, ordered)
        decisions.append(decision)
        if decision.eligible:
            eligible_decisions.append((decision, candidate, need, total_cost))
    ordered_eligible = sorted(eligible_decisions,
                              key=lambda item: (-item[0].priority_adjusted_score_bps,
                                                item[3], item[1].player_id))
    ordered_decisions = tuple(sorted(decisions,
                                     key=lambda item: (-item.priority_adjusted_score_bps,
                                                       item.total_guaranteed_cost_minor, item.player_id)))
    if not ordered_eligible:
        plan = AIRecruitmentPlan(
            derive_id("ai-recruitment-plan", "p15c-recruitment-v1", policy.club_id, on.isoformat, "none"),
            policy.club_id, on, RecruitmentRoute.NO_ACTION, None, None, None,
            ordered_decisions, "No current candidate satisfies the role need, evidence and budget gates.",
        )
        return plan, market
    selected, candidate, need, _ = ordered_eligible[0]
    if candidate.internal_candidate:
        plan = AIRecruitmentPlan(
            derive_id("ai-recruitment-plan", "p15c-recruitment-v1", policy.club_id,
                      on.isoformat, candidate.player_id),
            policy.club_id, on, RecruitmentRoute.INTERNAL_SUCCESSION,
            candidate.player_id, need.role_id, None, ordered_decisions,
            "The best eligible internal successor meets the configured need and evidence threshold.",
        )
        return plan, market
    offer = prepared_offers[candidate.player_id]
    offer_id = offer.offer_id
    if offer_cost(offer).total_guaranteed_cost_minor != selected.total_guaranteed_cost_minor:
        raise ValueError("AI offer cost does not reconcile with the candidate's visible fee and wage inputs")
    updated_market = submit_offer(market, offer)
    plan = AIRecruitmentPlan(
        derive_id("ai-recruitment-plan", "p15c-recruitment-v1", policy.club_id,
                  on.isoformat, candidate.player_id),
        policy.club_id, on, RecruitmentRoute.EXTERNAL_OFFER,
        candidate.player_id, need.role_id, offer_id, ordered_decisions,
        "The highest-ranked eligible external player received one budget-bounded offer.",
    )
    return plan, updated_market


__all__ = [
    "AIRecruitmentPlan", "AIRecruitmentPolicy", "CandidateDecision",
    "RecruitmentEvidence", "RecruitmentRoute", "RecruitmentTerms",
    "SquadRoleNeed", "plan_ai_recruitment", "recruitment_evidence_from_report",
]
