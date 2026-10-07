"""Time-bound transfer offers and explicit player/agent choice (P15b).

This is a negotiation record, not a completed transfer. It compares guaranteed
fee/wage/agent costs and models player preferences with visible, provisional
inputs. Roster ownership, governance authorization, cash settlement, medical
clearance and competition registration remain later transaction boundaries.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from games.touchline.esb.ids import derive_id, validate_id
from games.touchline.esb.time import WorldDate

_BPS = 10_000
_CURRENCY_RE = re.compile(r"[A-Z]{3}\Z")


def _validate_currency(value: str, label: str) -> None:
    if not isinstance(value, str) or not _CURRENCY_RE.fullmatch(value):
        raise ValueError(f"{label} must be a three-letter uppercase ASCII code")


class OfferedRole(str, Enum):
    PROSPECT = "prospect"
    ROTATION = "rotation"
    REGULAR = "regular"
    KEY_PLAYER = "key_player"


_ROLE_RANK = {
    OfferedRole.PROSPECT: 0,
    OfferedRole.ROTATION: 1,
    OfferedRole.REGULAR: 2,
    OfferedRole.KEY_PLAYER: 3,
}


class OfferStatus(str, Enum):
    OPEN = "open"
    SELLER_ACCEPTED = "seller_accepted"
    SELLER_REJECTED = "seller_rejected"
    PLAYER_ACCEPTED = "player_accepted_in_principle"
    PLAYER_REJECTED = "player_rejected"
    EXPIRED = "expired"
    WITHDRAWN = "withdrawn"
    SUPERSEDED = "superseded"
    CLOSED_COMPETITOR = "closed_by_competing_choice"


class MarketEventKind(str, Enum):
    SELLER_ACCEPTED = "seller_accepted"
    SELLER_REJECTED = "seller_rejected"
    PLAYER_ACCEPTED = "player_accepted_in_principle"
    PLAYER_REJECTED = "player_rejected"
    EXPIRED = "expired"
    WITHDRAWN = "withdrawn"
    SUPERSEDED = "superseded"
    CLOSED_COMPETITOR = "closed_by_competing_choice"


@dataclass(frozen=True)
class MarketCandidate:
    """One listed player; no contract ID means an unattached free agent."""

    player_id: str
    current_club_id: str | None
    contract_id: str | None
    asking_fee_minor: int
    currency: str
    available_on: WorldDate
    expires_on: WorldDate

    def __post_init__(self) -> None:
        validate_id(self.player_id, kind="market player ID")
        if self.current_club_id is not None:
            validate_id(self.current_club_id, kind="market current club ID")
        if self.contract_id is not None:
            validate_id(self.contract_id, kind="market contract ID")
        if (self.current_club_id is None) != (self.contract_id is None):
            raise ValueError("a contracted candidate needs both current club and contract references")
        if type(self.asking_fee_minor) is not int or self.asking_fee_minor < 0:
            raise ValueError("asking fee must be a non-negative integer minor-unit amount")
        if self.contract_id is None and self.asking_fee_minor != 0:
            raise ValueError("free agents cannot have a transfer fee")
        _validate_currency(self.currency, "market currency")
        if not isinstance(self.available_on, WorldDate) or not isinstance(self.expires_on, WorldDate):
            raise TypeError("market availability requires explicit calendar dates")
        if self.expires_on < self.available_on:
            raise ValueError("market listing expiry cannot precede availability")


@dataclass(frozen=True)
class PlayerMarketProfile:
    """Explicit personal contract/role preferences used by the P15b model."""

    player_id: str
    minimum_weekly_wage_minor: int
    target_weekly_wage_minor: int
    minimum_contract_weeks: int
    target_contract_weeks: int
    desired_role: OfferedRole
    preferred_place_ids: tuple[str, ...] = ()
    required_policy_tags: tuple[str, ...] = ()
    preferred_policy_tags: tuple[str, ...] = ()
    avoided_policy_tags: tuple[str, ...] = ()
    minimum_club_reputation_bps: int = 0
    wage_weight_bps: int = 3_000
    security_weight_bps: int = 1_500
    role_weight_bps: int = 2_500
    place_weight_bps: int = 1_000
    policy_weight_bps: int = 1_000
    reputation_weight_bps: int = 1_000
    acceptance_threshold_bps: int = 6_000

    def __post_init__(self) -> None:
        validate_id(self.player_id, kind="market preference player ID")
        for label, amount in (
            ("minimum weekly wage", self.minimum_weekly_wage_minor),
            ("target weekly wage", self.target_weekly_wage_minor),
            ("minimum contract weeks", self.minimum_contract_weeks),
            ("target contract weeks", self.target_contract_weeks),
        ):
            if type(amount) is not int or amount <= 0:
                raise ValueError(f"{label} must be a positive integer")
        if self.target_weekly_wage_minor < self.minimum_weekly_wage_minor:
            raise ValueError("target wage cannot be below the hard minimum")
        if self.target_contract_weeks < self.minimum_contract_weeks:
            raise ValueError("target contract term cannot be below its hard minimum")
        if not isinstance(self.desired_role, OfferedRole):
            raise TypeError("desired squad role must use a registered role")
        for label, values in (
            ("preferred places", self.preferred_place_ids),
            ("required policy tags", self.required_policy_tags),
            ("preferred policy tags", self.preferred_policy_tags),
            ("avoided policy tags", self.avoided_policy_tags),
        ):
            if not isinstance(values, tuple):
                raise TypeError(f"{label} must be an immutable tuple")
            for value in values:
                validate_id(value, kind=label)
            if len(values) != len(set(values)):
                raise ValueError(f"{label} cannot repeat values")
        if set(self.required_policy_tags) & set(self.avoided_policy_tags):
            raise ValueError("a policy tag cannot be both required and avoided")
        if type(self.minimum_club_reputation_bps) is not int or not 0 <= self.minimum_club_reputation_bps <= _BPS:
            raise ValueError("minimum club reputation must be basis points in [0, 10000]")
        weights = (
            self.wage_weight_bps, self.security_weight_bps, self.role_weight_bps,
            self.place_weight_bps, self.policy_weight_bps, self.reputation_weight_bps,
        )
        if any(type(value) is not int or value < 0 for value in weights) or sum(weights) != _BPS:
            raise ValueError("offer preference weights must be non-negative and sum to 10000 basis points")
        if type(self.acceptance_threshold_bps) is not int or not 0 <= self.acceptance_threshold_bps <= _BPS:
            raise ValueError("offer acceptance threshold must be basis points in [0, 10000]")


@dataclass(frozen=True)
class AgentMandate:
    """Dated, bounded permission for an agent to accept terms for a player."""

    mandate_id: str
    agent_id: str
    player_id: str
    starts_on: WorldDate
    expires_on: WorldDate
    may_accept: bool
    may_decline: bool
    minimum_weekly_wage_minor: int
    minimum_contract_weeks: int
    maximum_commission_bps: int

    def __post_init__(self) -> None:
        validate_id(self.mandate_id, kind="agent mandate ID")
        validate_id(self.agent_id, kind="agent ID")
        validate_id(self.player_id, kind="agent client ID")
        if not isinstance(self.starts_on, WorldDate) or not isinstance(self.expires_on, WorldDate):
            raise TypeError("agent mandate requires explicit dates")
        if self.expires_on < self.starts_on:
            raise ValueError("agent mandate expiry cannot precede its start")
        if type(self.may_accept) is not bool or type(self.may_decline) is not bool:
            raise TypeError("agent authority must state acceptance and decline permission")
        if not self.may_accept and not self.may_decline:
            raise ValueError("agent mandate must authorize at least one decision")
        if type(self.minimum_weekly_wage_minor) is not int or self.minimum_weekly_wage_minor <= 0:
            raise ValueError("agent wage limit must be a positive minor-unit amount")
        if type(self.minimum_contract_weeks) is not int or self.minimum_contract_weeks <= 0:
            raise ValueError("agent minimum term must be positive weeks")
        if type(self.maximum_commission_bps) is not int or not 0 <= self.maximum_commission_bps <= _BPS:
            raise ValueError("agent commission limit must be basis points in [0, 10000]")

    def active_on(self, on: WorldDate) -> bool:
        if not isinstance(on, WorldDate):
            raise TypeError("agent mandate check requires a WorldDate")
        return self.starts_on <= on <= self.expires_on

    def covers(self, offer: TransferOffer) -> bool:
        return (
            offer.agent_id in (None, self.agent_id)
            and self.player_id == offer.player_id
            and self.minimum_weekly_wage_minor <= offer.weekly_wage_minor
            and self.minimum_contract_weeks <= offer.contract_weeks
            and offer.agency_commission_bps <= self.maximum_commission_bps
        )


@dataclass(frozen=True)
class TransferOffer:
    """One immutable fee and employment-terms submission."""

    offer_id: str
    player_id: str
    buyer_club_id: str
    seller_club_id: str | None
    submitted_on: WorldDate
    expires_on: WorldDate
    currency: str
    transfer_fee_minor: int
    weekly_wage_minor: int
    contract_weeks: int
    role: OfferedRole
    destination_place_id: str
    club_policy_tags: tuple[str, ...]
    club_reputation_bps: int
    agent_id: str | None = None
    agency_commission_bps: int = 0
    supersedes_offer_id: str | None = None

    def __post_init__(self) -> None:
        validate_id(self.offer_id, kind="transfer offer ID")
        validate_id(self.player_id, kind="transfer offer player ID")
        validate_id(self.buyer_club_id, kind="transfer buyer club ID")
        if self.seller_club_id is not None:
            validate_id(self.seller_club_id, kind="transfer seller club ID")
        validate_id(self.destination_place_id, kind="offer destination place ID")
        if self.seller_club_id is not None and self.buyer_club_id == self.seller_club_id:
            raise ValueError("transfer offer buyer and seller must differ")
        if not isinstance(self.submitted_on, WorldDate) or not isinstance(self.expires_on, WorldDate):
            raise TypeError("transfer offer requires explicit dates")
        if self.expires_on < self.submitted_on:
            raise ValueError("offer expiry cannot precede submission")
        _validate_currency(self.currency, "offer currency")
        if type(self.transfer_fee_minor) is not int or self.transfer_fee_minor < 0:
            raise ValueError("transfer fee must be non-negative integer minor units")
        if self.seller_club_id is None and self.transfer_fee_minor != 0:
            raise ValueError("free-agent offers cannot include a transfer fee")
        if type(self.weekly_wage_minor) is not int or self.weekly_wage_minor <= 0:
            raise ValueError("weekly wage must be positive integer minor units")
        if type(self.contract_weeks) is not int or self.contract_weeks <= 0:
            raise ValueError("contract duration must be positive whole weeks")
        if not isinstance(self.role, OfferedRole):
            raise TypeError("offer role must use a registered squad role")
        if not isinstance(self.club_policy_tags, tuple):
            raise TypeError("club policy tags must be immutable")
        for tag in self.club_policy_tags:
            validate_id(tag, kind="offer club policy tag")
        if len(self.club_policy_tags) != len(set(self.club_policy_tags)):
            raise ValueError("offer club policy tags cannot repeat")
        if type(self.club_reputation_bps) is not int or not 0 <= self.club_reputation_bps <= _BPS:
            raise ValueError("club reputation must be basis points in [0, 10000]")
        if self.agent_id is not None:
            validate_id(self.agent_id, kind="offer agent ID")
        if type(self.agency_commission_bps) is not int or not 0 <= self.agency_commission_bps <= _BPS:
            raise ValueError("agency commission must be basis points in [0, 10000]")
        if self.agent_id is None and self.agency_commission_bps != 0:
            raise ValueError("agent commission requires an identified agent")
        if self.supersedes_offer_id is not None:
            validate_id(self.supersedes_offer_id, kind="superseded offer ID")
            if self.supersedes_offer_id == self.offer_id:
                raise ValueError("an offer cannot supersede itself")


@dataclass(frozen=True)
class OfferCost:
    offer_id: str
    currency: str
    transfer_fee_minor: int
    guaranteed_wages_minor: int
    agent_commission_minor: int
    total_guaranteed_cost_minor: int

    def __post_init__(self) -> None:
        validate_id(self.offer_id, kind="offer cost ID")
        _validate_currency(self.currency, "offer cost currency")
        values = (self.transfer_fee_minor, self.guaranteed_wages_minor,
                  self.agent_commission_minor, self.total_guaranteed_cost_minor)
        if any(type(value) is not int or value < 0 for value in values):
            raise ValueError("offer cost values must be non-negative integer minor units")
        if self.total_guaranteed_cost_minor != sum(values[:3]):
            raise ValueError("total offer cost must reconcile to fee, wages and agent commission")


@dataclass(frozen=True)
class OfferAppraisal:
    offer_id: str
    player_id: str
    wage_score_bps: int
    security_score_bps: int
    role_score_bps: int
    place_score_bps: int
    policy_score_bps: int
    reputation_score_bps: int
    overall_score_bps: int
    acceptable: bool
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        validate_id(self.offer_id, kind="appraised offer ID")
        validate_id(self.player_id, kind="appraised player ID")
        scores = (self.wage_score_bps, self.security_score_bps, self.role_score_bps,
                  self.place_score_bps, self.policy_score_bps, self.reputation_score_bps,
                  self.overall_score_bps)
        if any(type(value) is not int or not 0 <= value <= _BPS for value in scores):
            raise ValueError("appraisal components must be basis points in [0, 10000]")
        if type(self.acceptable) is not bool or not isinstance(self.reasons, tuple):
            raise TypeError("appraisal must retain an explicit choice and reasons")
        if any(not isinstance(item, str) or not item for item in self.reasons):
            raise ValueError("appraisal reason codes must be non-empty strings")
        if self.acceptable != (len(self.reasons) == 0):
            raise ValueError("appraisal acceptance must agree with its reason codes")
        if len(self.reasons) != len(set(self.reasons)):
            raise ValueError("appraisal reason codes cannot repeat")


@dataclass(frozen=True)
class MarketEvent:
    event_id: str
    offer_id: str
    actor_id: str
    at: WorldDate
    kind: MarketEventKind
    appraisal: OfferAppraisal | None = None
    related_offer_id: str | None = None

    def __post_init__(self) -> None:
        validate_id(self.event_id, kind="market event ID")
        validate_id(self.offer_id, kind="market event offer ID")
        validate_id(self.actor_id, kind="market event actor ID")
        if not isinstance(self.at, WorldDate) or not isinstance(self.kind, MarketEventKind):
            raise TypeError("market event requires a calendar date and registered kind")
        if self.appraisal is not None and not isinstance(self.appraisal, OfferAppraisal):
            raise TypeError("player market response requires a typed appraisal")
        if self.related_offer_id is not None:
            validate_id(self.related_offer_id, kind="related offer ID")
        needs_appraisal = self.kind in (MarketEventKind.PLAYER_ACCEPTED, MarketEventKind.PLAYER_REJECTED)
        if needs_appraisal != (self.appraisal is not None):
            raise ValueError("only player-choice events require an appraisal")
        needs_related_offer = self.kind in (
            MarketEventKind.SUPERSEDED, MarketEventKind.CLOSED_COMPETITOR,
        )
        if needs_related_offer != (self.related_offer_id is not None):
            raise ValueError("linked market events must identify the related offer")


@dataclass(frozen=True)
class MarketBook:
    candidates: tuple[MarketCandidate, ...] = ()
    player_profiles: tuple[PlayerMarketProfile, ...] = ()
    agent_mandates: tuple[AgentMandate, ...] = ()
    offers: tuple[TransferOffer, ...] = ()
    events: tuple[MarketEvent, ...] = ()

    def __post_init__(self) -> None:
        groups = (
            ("candidates", self.candidates, MarketCandidate),
            ("player profiles", self.player_profiles, PlayerMarketProfile),
            ("agent mandates", self.agent_mandates, AgentMandate),
            ("offers", self.offers, TransferOffer),
            ("events", self.events, MarketEvent),
        )
        for label, records, kind in groups:
            if not isinstance(records, tuple) or any(not isinstance(item, kind) for item in records):
                raise TypeError(f"market {label} must be immutable {kind.__name__} records")
        candidates = {item.player_id: item for item in self.candidates}
        profiles = {item.player_id: item for item in self.player_profiles}
        mandates = {item.mandate_id: item for item in self.agent_mandates}
        offers = {item.offer_id: item for item in self.offers}
        if len(candidates) != len(self.candidates):
            raise ValueError("market can list a player only once")
        if len(profiles) != len(self.player_profiles):
            raise ValueError("market player profiles must be unique")
        if len(mandates) != len(self.agent_mandates):
            raise ValueError("agent mandate IDs must be unique")
        if len(offers) != len(self.offers):
            raise ValueError("offer IDs must be unique")
        if any(player_id not in candidates for player_id in profiles):
            raise ValueError("market preference requires a listed candidate")
        if any(item.player_id not in candidates or item.player_id not in profiles
               for item in self.agent_mandates):
            raise ValueError("agent mandate requires a listed player with explicit preferences")
        for index, left in enumerate(self.agent_mandates):
            for right in self.agent_mandates[index + 1:]:
                if (left.player_id == right.player_id and left.agent_id == right.agent_id
                        and max(left.starts_on, right.starts_on) <= min(left.expires_on, right.expires_on)):
                    raise ValueError("the same agent cannot hold overlapping mandates for a player")
        if [item.submitted_on for item in self.offers] != sorted(item.submitted_on for item in self.offers):
            raise ValueError("offers must retain submission chronology")
        for offer in self.offers:
            candidate = candidates.get(offer.player_id)
            if (candidate is None or offer.player_id not in profiles
                    or offer.seller_club_id != candidate.current_club_id):
                raise ValueError("offer does not match a listed player's current seller")
            if (
                offer.submitted_on < candidate.available_on
                or offer.expires_on > candidate.expires_on
                or offer.currency != candidate.currency
            ):
                raise ValueError("offer date or currency falls outside the market listing")
            if candidate.contract_id is None and offer.transfer_fee_minor != 0:
                raise ValueError("free agents cannot receive transfer-fee offers")
            if offer.agent_id is not None:
                if not any(mandate.agent_id == offer.agent_id and mandate.player_id == offer.player_id
                           and mandate.active_on(offer.submitted_on)
                           and offer.agency_commission_bps <= mandate.maximum_commission_bps
                           for mandate in self.agent_mandates):
                    raise ValueError("offer agency commission lacks an active matching mandate")
            if offer.supersedes_offer_id is not None:
                parent = offers.get(offer.supersedes_offer_id)
                if parent is None or (
                    parent.player_id != offer.player_id
                    or parent.buyer_club_id != offer.buyer_club_id
                    or parent.seller_club_id != offer.seller_club_id
                    or parent.submitted_on >= offer.submitted_on
                ):
                    raise ValueError("replacement offer must revise an earlier offer for the same parties")

        if [item.at for item in self.events] != sorted(item.at for item in self.events):
            raise ValueError("market events must retain calendar order")
        if len({item.event_id for item in self.events}) != len(self.events):
            raise ValueError("market event IDs must be unique")
        status: dict[str, OfferStatus] = {offer_id: OfferStatus.OPEN for offer_id in offers}
        accepted_event_by_candidate: dict[str, MarketEvent] = {}
        for event in self.events:
            offer = offers.get(event.offer_id)
            if offer is None:
                raise ValueError("market event references an absent offer")
            if event.event_id != _market_event_id(
                event.kind, event.offer_id, event.actor_id, event.at, event.related_offer_id
            ):
                raise ValueError("market event ID does not match its action lineage")
            current = status[event.offer_id]
            if event.at < offer.submitted_on:
                raise ValueError("market response cannot precede offer submission")
            if event.kind in (MarketEventKind.SELLER_ACCEPTED, MarketEventKind.SELLER_REJECTED):
                if (current is not OfferStatus.OPEN or offer.seller_club_id is None
                        or event.actor_id != offer.seller_club_id):
                    raise ValueError("seller response requires an open offer and its listed seller")
                if event.at > offer.expires_on:
                    raise ValueError("seller response arrived after the offer expired")
                status[event.offer_id] = (
                    OfferStatus.SELLER_ACCEPTED if event.kind is MarketEventKind.SELLER_ACCEPTED
                    else OfferStatus.SELLER_REJECTED
                )
            elif event.kind in (MarketEventKind.PLAYER_ACCEPTED, MarketEventKind.PLAYER_REJECTED):
                candidate = candidates[offer.player_id]
                allowed_status = (
                    OfferStatus.OPEN if candidate.current_club_id is None
                    else OfferStatus.SELLER_ACCEPTED
                )
                if current is not allowed_status or event.at > offer.expires_on:
                    raise ValueError("player choice requires a seller-approved, live offer")
                if event.appraisal != appraise_offer(profiles[offer.player_id], offer):
                    raise ValueError("player choice appraisal does not match the recorded offer profile")
                if event.kind is MarketEventKind.PLAYER_ACCEPTED:
                    if not event.appraisal.acceptable:
                        raise ValueError("player cannot accept terms below their recorded constraints")
                    if offer.player_id in accepted_event_by_candidate:
                        raise ValueError("a player cannot accept more than one competing agreement")
                    accepted_event_by_candidate[offer.player_id] = event
                    status[event.offer_id] = OfferStatus.PLAYER_ACCEPTED
                else:
                    status[event.offer_id] = OfferStatus.PLAYER_REJECTED
                if event.actor_id != offer.player_id:
                    mandate = next((item for item in self.agent_mandates
                                    if item.agent_id == event.actor_id
                                    and item.player_id == offer.player_id
                                    and item.active_on(event.at)), None)
                    if mandate is None:
                        raise ValueError("agent player response lacks an active client mandate")
                    if event.kind is MarketEventKind.PLAYER_ACCEPTED:
                        if not mandate.may_accept or not mandate.covers(offer):
                            raise ValueError("agent cannot accept beyond their dated mandate limits")
                    elif not mandate.may_decline:
                        raise ValueError("agent cannot decline outside their dated mandate")
            elif event.kind is MarketEventKind.EXPIRED:
                if (current not in (OfferStatus.OPEN, OfferStatus.SELLER_ACCEPTED)
                        or event.actor_id != "system:market" or event.at <= offer.expires_on):
                    raise ValueError("only an unresolved offer can expire after its deadline")
                status[event.offer_id] = OfferStatus.EXPIRED
            elif event.kind is MarketEventKind.WITHDRAWN:
                if (current not in (OfferStatus.OPEN, OfferStatus.SELLER_ACCEPTED)
                        or event.actor_id != offer.buyer_club_id or event.at > offer.expires_on):
                    raise ValueError("only the offer buyer can withdraw an unresolved offer")
                status[event.offer_id] = OfferStatus.WITHDRAWN
            elif event.kind is MarketEventKind.SUPERSEDED:
                replacement = offers.get(event.related_offer_id or "")
                if (
                    current not in (OfferStatus.OPEN, OfferStatus.SELLER_REJECTED, OfferStatus.PLAYER_REJECTED)
                    or event.actor_id != offer.buyer_club_id
                    or replacement is None
                    or replacement.supersedes_offer_id != offer.offer_id
                    or replacement.submitted_on != event.at
                    or event.at > offer.expires_on
                ):
                    raise ValueError("offer supersession must link an unresolved/rejected offer to its revision")
                status[event.offer_id] = OfferStatus.SUPERSEDED
            elif event.kind is MarketEventKind.CLOSED_COMPETITOR:
                winner_event = accepted_event_by_candidate.get(offer.player_id)
                winner = offers.get(winner_event.offer_id if winner_event is not None else "")
                if (
                    current not in (OfferStatus.OPEN, OfferStatus.SELLER_ACCEPTED)
                    or winner is None or winner.offer_id == offer.offer_id
                    or event.related_offer_id != winner.offer_id
                    or winner_event is None or event.actor_id != winner_event.actor_id
                    or event.at < winner_event.at or event.at > offer.expires_on
                ):
                    raise ValueError("competing offer can close only after the player's other acceptance")
                status[event.offer_id] = OfferStatus.CLOSED_COMPETITOR
        for offer in self.offers:
            if offer.supersedes_offer_id is not None and not any(
                event.kind is MarketEventKind.SUPERSEDED
                and event.offer_id == offer.supersedes_offer_id
                and event.related_offer_id == offer.offer_id
                for event in self.events
            ):
                raise ValueError("replacement offer is missing its supersession event")
        for player_id, accepted_event in accepted_event_by_candidate.items():
            if any(
                offer.player_id == player_id
                and status[offer.offer_id] in (OfferStatus.OPEN, OfferStatus.SELLER_ACCEPTED)
                for offer in self.offers
            ):
                raise ValueError("a player acceptance must resolve all competing live offers")
            if any(offer.player_id == player_id and offer.submitted_on > accepted_event.at
                   for offer in self.offers):
                raise ValueError("offers cannot be submitted after the player's acceptance")
        unresolved_by_buyer: set[tuple[str, str]] = set()
        for offer_id, current in status.items():
            if current not in (OfferStatus.OPEN, OfferStatus.SELLER_ACCEPTED):
                continue
            offer = offers[offer_id]
            key = (offer.player_id, offer.buyer_club_id)
            if key in unresolved_by_buyer:
                raise ValueError("a buyer cannot keep multiple unresolved offers for one player")
            unresolved_by_buyer.add(key)


@dataclass(frozen=True)
class MarketChoice:
    player_id: str
    chosen_offer_id: str | None
    appraisals: tuple[OfferAppraisal, ...]

    def __post_init__(self) -> None:
        validate_id(self.player_id, kind="market choice player ID")
        if self.chosen_offer_id is not None:
            validate_id(self.chosen_offer_id, kind="chosen offer ID")
        if not isinstance(self.appraisals, tuple) or any(not isinstance(item, OfferAppraisal) for item in self.appraisals):
            raise TypeError("market choice requires immutable typed appraisals")
        if self.chosen_offer_id is not None and self.chosen_offer_id not in {item.offer_id for item in self.appraisals}:
            raise ValueError("chosen offer must appear in the inspected appraisals")


def _market_event_id(
    kind: MarketEventKind,
    offer_id: str,
    actor_id: str,
    at: WorldDate,
    related_offer_id: str | None,
) -> str:
    return derive_id(
        "market-event", "p15b-offer-decision-v1", kind.value, offer_id,
        actor_id, at.isoformat, related_offer_id,
    )


def _event(
    kind: MarketEventKind,
    offer_id: str,
    actor_id: str,
    at: WorldDate,
    *,
    appraisal: OfferAppraisal | None = None,
    related_offer_id: str | None = None,
) -> MarketEvent:
    return MarketEvent(
        _market_event_id(kind, offer_id, actor_id, at, related_offer_id),
        offer_id, actor_id, at, kind, appraisal, related_offer_id,
    )


def _statuses(book: MarketBook) -> dict[str, OfferStatus]:
    status = {offer.offer_id: OfferStatus.OPEN for offer in book.offers}
    for event in book.events:
        if event.kind is MarketEventKind.SELLER_ACCEPTED:
            status[event.offer_id] = OfferStatus.SELLER_ACCEPTED
        elif event.kind is MarketEventKind.SELLER_REJECTED:
            status[event.offer_id] = OfferStatus.SELLER_REJECTED
        elif event.kind is MarketEventKind.PLAYER_ACCEPTED:
            status[event.offer_id] = OfferStatus.PLAYER_ACCEPTED
        elif event.kind is MarketEventKind.PLAYER_REJECTED:
            status[event.offer_id] = OfferStatus.PLAYER_REJECTED
        elif event.kind is MarketEventKind.EXPIRED:
            status[event.offer_id] = OfferStatus.EXPIRED
        elif event.kind is MarketEventKind.WITHDRAWN:
            status[event.offer_id] = OfferStatus.WITHDRAWN
        elif event.kind is MarketEventKind.SUPERSEDED:
            status[event.offer_id] = OfferStatus.SUPERSEDED
        elif event.kind is MarketEventKind.CLOSED_COMPETITOR:
            status[event.offer_id] = OfferStatus.CLOSED_COMPETITOR
    return status


def offer_status(book: MarketBook, offer_id: str) -> OfferStatus:
    if not isinstance(book, MarketBook):
        raise TypeError("offer status requires a MarketBook")
    validate_id(offer_id, kind="offer ID")
    if not any(item.offer_id == offer_id for item in book.offers):
        raise KeyError(f"unknown offer: {offer_id}")
    return _statuses(book)[offer_id]


def offer_cost(offer: TransferOffer) -> OfferCost:
    """Compare guaranteed commitment exactly; variable bonuses are excluded."""

    if not isinstance(offer, TransferOffer):
        raise TypeError("offer cost requires a TransferOffer")
    wage_total = offer.weekly_wage_minor * offer.contract_weeks
    commission = wage_total * offer.agency_commission_bps // _BPS
    return OfferCost(
        offer.offer_id, offer.currency, offer.transfer_fee_minor,
        wage_total, commission,
        offer.transfer_fee_minor + wage_total + commission,
    )


def appraise_offer(profile: PlayerMarketProfile, offer: TransferOffer) -> OfferAppraisal:
    """Return the versioned, inspectable preference score without random draws."""

    if not isinstance(profile, PlayerMarketProfile) or not isinstance(offer, TransferOffer):
        raise TypeError("offer appraisal requires player preferences and offer terms")
    if profile.player_id != offer.player_id:
        raise ValueError("offer and player preference subject differ")
    wage_score = min(_BPS, offer.weekly_wage_minor * _BPS // profile.target_weekly_wage_minor)
    security_score = min(_BPS, offer.contract_weeks * _BPS // profile.target_contract_weeks)
    desired_rank = _ROLE_RANK[profile.desired_role]
    offered_rank = _ROLE_RANK[offer.role]
    role_score = min(_BPS, (offered_rank + 1) * _BPS // (desired_rank + 1))
    if not profile.preferred_place_ids:
        place_score = 5_000
    else:
        place_score = _BPS if offer.destination_place_id in profile.preferred_place_ids else 0
    offer_policies = set(offer.club_policy_tags)
    required = set(profile.required_policy_tags)
    avoided = set(profile.avoided_policy_tags)
    preferred = set(profile.preferred_policy_tags)
    hard_policy_failure = bool(required - offer_policies or avoided & offer_policies)
    if hard_policy_failure:
        policy_score = 0
    elif not preferred:
        policy_score = _BPS
    else:
        policy_score = 5_000 + 5_000 * len(preferred & offer_policies) // len(preferred)
    if profile.minimum_club_reputation_bps == 0:
        reputation_score = _BPS
    else:
        reputation_score = min(
            _BPS,
            offer.club_reputation_bps * _BPS // profile.minimum_club_reputation_bps,
        )
    components = (
        (wage_score, profile.wage_weight_bps),
        (security_score, profile.security_weight_bps),
        (role_score, profile.role_weight_bps),
        (place_score, profile.place_weight_bps),
        (policy_score, profile.policy_weight_bps),
        (reputation_score, profile.reputation_weight_bps),
    )
    overall = sum(value * weight for value, weight in components) // _BPS
    reasons = []
    if offer.weekly_wage_minor < profile.minimum_weekly_wage_minor:
        reasons.append("below_minimum_wage")
    if offer.contract_weeks < profile.minimum_contract_weeks:
        reasons.append("term_too_short")
    if required - offer_policies:
        reasons.append("required_policy_missing")
    if avoided & offer_policies:
        reasons.append("avoided_policy_present")
    if offer.club_reputation_bps < profile.minimum_club_reputation_bps:
        reasons.append("club_reputation_below_minimum")
    if overall < profile.acceptance_threshold_bps:
        reasons.append("below_preference_threshold")
    return OfferAppraisal(
        offer.offer_id, offer.player_id,
        wage_score, security_score, role_score, place_score, policy_score,
        reputation_score, overall, not reasons, tuple(reasons),
    )


def add_candidate(book: MarketBook, candidate: MarketCandidate) -> MarketBook:
    if not isinstance(book, MarketBook) or not isinstance(candidate, MarketCandidate):
        raise TypeError("market listing requires a MarketBook and MarketCandidate")
    existing = next((item for item in book.candidates if item.player_id == candidate.player_id), None)
    if existing is not None:
        if existing == candidate:
            return book
        raise ValueError("player already has a different market listing")
    return MarketBook(book.candidates + (candidate,), book.player_profiles,
                      book.agent_mandates, book.offers, book.events)


def add_player_profile(book: MarketBook, profile: PlayerMarketProfile) -> MarketBook:
    if not isinstance(book, MarketBook) or not isinstance(profile, PlayerMarketProfile):
        raise TypeError("market preference requires a MarketBook and PlayerMarketProfile")
    existing = next((item for item in book.player_profiles if item.player_id == profile.player_id), None)
    if existing is not None:
        if existing == profile:
            return book
        raise ValueError("player preference ID was reused with different terms")
    return MarketBook(book.candidates, book.player_profiles + (profile,),
                      book.agent_mandates, book.offers, book.events)


def add_agent_mandate(book: MarketBook, mandate: AgentMandate) -> MarketBook:
    if not isinstance(book, MarketBook) or not isinstance(mandate, AgentMandate):
        raise TypeError("market agent authority requires a MarketBook and AgentMandate")
    existing = next((item for item in book.agent_mandates if item.mandate_id == mandate.mandate_id), None)
    if existing is not None:
        if existing == mandate:
            return book
        raise ValueError("agent mandate ID was reused with different scope")
    return MarketBook(book.candidates, book.player_profiles,
                      book.agent_mandates + (mandate,), book.offers, book.events)


def submit_offer(book: MarketBook, offer: TransferOffer) -> MarketBook:
    if not isinstance(book, MarketBook) or not isinstance(offer, TransferOffer):
        raise TypeError("market submission requires a MarketBook and TransferOffer")
    existing = next((item for item in book.offers if item.offer_id == offer.offer_id), None)
    if existing is not None:
        if existing == offer:
            return book
        raise ValueError("offer ID was reused with conflicting terms")
    book = expire_offers(book, offer.submitted_on)
    candidate = next((item for item in book.candidates if item.player_id == offer.player_id), None)
    if candidate is None or candidate.current_club_id != offer.seller_club_id:
        raise ValueError("offer does not match a listed player and current seller")
    if (offer.submitted_on < candidate.available_on or offer.submitted_on > candidate.expires_on
            or offer.expires_on > candidate.expires_on or offer.currency != candidate.currency):
        raise ValueError("offer falls outside the candidate's date or currency terms")
    if candidate.contract_id is None and offer.transfer_fee_minor != 0:
        raise ValueError("free agents cannot receive transfer-fee offers")
    if any(event.kind is MarketEventKind.PLAYER_ACCEPTED
           and next(item for item in book.offers if item.offer_id == event.offer_id).player_id == offer.player_id
           for event in book.events):
        raise ValueError("player already accepted another agreement in principle")
    if book.events and offer.submitted_on < book.events[-1].at:
        raise ValueError("offer cannot be submitted before the latest market event")
    if book.offers and offer.submitted_on < book.offers[-1].submitted_on:
        raise ValueError("offer submissions must retain calendar order")
    current_statuses = _statuses(book)
    prior_from_buyer = [item for item in book.offers
                        if item.player_id == offer.player_id
                        and item.buyer_club_id == offer.buyer_club_id]
    mandate = None
    if offer.agent_id is not None:
        mandate = next((item for item in book.agent_mandates
                        if item.agent_id == offer.agent_id and item.player_id == offer.player_id
                        and item.active_on(offer.submitted_on)), None)
        if mandate is None or offer.agency_commission_bps > mandate.maximum_commission_bps:
            raise ValueError("offer agency commission lacks an active matching mandate")
    if offer.supersedes_offer_id is not None:
        parent = next((item for item in book.offers if item.offer_id == offer.supersedes_offer_id), None)
        if parent is None:
            raise ValueError("replacement offer must reference an existing offer")
        if not prior_from_buyer or parent.offer_id != prior_from_buyer[-1].offer_id:
            raise ValueError("replacement offer must revise the buyer's latest offer")
        if (parent.player_id != offer.player_id or parent.buyer_club_id != offer.buyer_club_id
                or parent.seller_club_id != offer.seller_club_id or parent.submitted_on >= offer.submitted_on):
            raise ValueError("replacement offer must revise an earlier offer for the same parties")
        if current_statuses[parent.offer_id] not in (
            OfferStatus.OPEN, OfferStatus.SELLER_REJECTED, OfferStatus.PLAYER_REJECTED,
        ):
            raise ValueError("only an open or rejected offer can be revised")
    elif prior_from_buyer:
        latest = prior_from_buyer[-1]
        latest_status = current_statuses[latest.offer_id]
        if latest_status in (OfferStatus.OPEN, OfferStatus.SELLER_ACCEPTED):
            raise ValueError("buyer already has an unresolved offer for this player; submit a revision")
        if latest_status in (OfferStatus.SELLER_REJECTED, OfferStatus.PLAYER_REJECTED):
            raise ValueError("revised offer must retain lineage to the buyer's rejected offer")

    updated_offers = book.offers + (offer,)
    updated_events = book.events
    if offer.supersedes_offer_id is not None:
        updated_events += (_event(
            MarketEventKind.SUPERSEDED, offer.supersedes_offer_id,
            offer.buyer_club_id, offer.submitted_on,
            related_offer_id=offer.offer_id,
        ),)
    return MarketBook(book.candidates, book.player_profiles, book.agent_mandates,
                      updated_offers, updated_events)


def seller_respond(
    book: MarketBook,
    offer_id: str,
    seller_club_id: str,
    *,
    accept: bool,
    on: WorldDate,
) -> MarketBook:
    if not isinstance(book, MarketBook) or not isinstance(on, WorldDate):
        raise TypeError("seller decision requires a MarketBook and WorldDate")
    validate_id(offer_id, kind="seller response offer ID")
    validate_id(seller_club_id, kind="seller decision club ID")
    if type(accept) is not bool:
        raise TypeError("seller response must explicitly accept or reject")
    offer = next((item for item in book.offers if item.offer_id == offer_id), None)
    if offer is None:
        raise KeyError(f"unknown offer: {offer_id}")
    if offer.seller_club_id is None:
        raise ValueError("a free-agent offer has no selling club to respond")
    if seller_club_id != offer.seller_club_id:
        raise ValueError("seller response actor does not own the listed player")
    kind = MarketEventKind.SELLER_ACCEPTED if accept else MarketEventKind.SELLER_REJECTED
    candidate_event = _event(kind, offer_id, seller_club_id, on)
    existing = next((item for item in book.events if item.event_id == candidate_event.event_id), None)
    if existing is not None:
        if existing == candidate_event:
            return book
        raise ValueError("seller response retry conflicts with its recorded event")
    if any(
        item.kind is MarketEventKind.PLAYER_ACCEPTED
        and next(record for record in book.offers if record.offer_id == item.offer_id).player_id == offer.player_id
        for item in book.events
    ):
        raise ValueError("player already accepted another agreement in principle")
    if _statuses(book)[offer_id] is not OfferStatus.OPEN:
        raise ValueError("seller can respond only to an open offer")
    if on < offer.submitted_on or on > offer.expires_on:
        raise ValueError("seller response is outside the offer window")
    if book.events and on < book.events[-1].at:
        raise ValueError("seller response cannot precede the latest market event")
    return MarketBook(book.candidates, book.player_profiles, book.agent_mandates,
                      book.offers, book.events + (candidate_event,))


def withdraw_offer(
    book: MarketBook,
    offer_id: str,
    buyer_club_id: str,
    *,
    on: WorldDate,
) -> MarketBook:
    if not isinstance(book, MarketBook) or not isinstance(on, WorldDate):
        raise TypeError("offer withdrawal requires a MarketBook and WorldDate")
    validate_id(offer_id, kind="withdrawn offer ID")
    validate_id(buyer_club_id, kind="withdrawing buyer ID")
    offer = next((item for item in book.offers if item.offer_id == offer_id), None)
    if offer is None:
        raise KeyError(f"unknown offer: {offer_id}")
    if offer.buyer_club_id != buyer_club_id:
        raise ValueError("only the buyer can withdraw its offer")
    event = _event(MarketEventKind.WITHDRAWN, offer_id, buyer_club_id, on)
    existing = next((item for item in book.events if item.event_id == event.event_id), None)
    if existing is not None:
        if existing == event:
            return book
        raise ValueError("withdrawal retry conflicts with its recorded event")
    if _statuses(book)[offer_id] not in (OfferStatus.OPEN, OfferStatus.SELLER_ACCEPTED):
        raise ValueError("only an unresolved offer can be withdrawn")
    if not offer.submitted_on <= on <= offer.expires_on:
        raise ValueError("offer can be withdrawn only inside its offer window")
    if book.events and on < book.events[-1].at:
        raise ValueError("withdrawal cannot precede the latest market event")
    return MarketBook(book.candidates, book.player_profiles, book.agent_mandates,
                      book.offers, book.events + (event,))


def expire_offers(book: MarketBook, on: WorldDate) -> MarketBook:
    if not isinstance(book, MarketBook) or not isinstance(on, WorldDate):
        raise TypeError("offer expiry requires a MarketBook and WorldDate")
    if book.events and on < book.events[-1].at:
        raise ValueError("offer expiry cannot precede the latest market event")
    statuses = _statuses(book)
    expired = []
    for offer in book.offers:
        if statuses[offer.offer_id] in (OfferStatus.OPEN, OfferStatus.SELLER_ACCEPTED) and on > offer.expires_on:
            expired.append(_event(MarketEventKind.EXPIRED, offer.offer_id, "system:market", on))
    if not expired:
        return book
    return MarketBook(book.candidates, book.player_profiles, book.agent_mandates,
                      book.offers, book.events + tuple(expired))


def _active_agent_mandate(book: MarketBook, actor_id: str, player_id: str, on: WorldDate) -> AgentMandate | None:
    return next((item for item in book.agent_mandates
                 if item.agent_id == actor_id and item.player_id == player_id and item.active_on(on)), None)


def resolve_player_choice(
    book: MarketBook,
    player_id: str,
    on: WorldDate,
    *,
    actor_id: str | None = None,
) -> tuple[MarketBook, MarketChoice]:
    """Choose among seller-approved offers; acceptance is only in principle."""

    if not isinstance(book, MarketBook) or not isinstance(on, WorldDate):
        raise TypeError("player choice requires a MarketBook and WorldDate")
    validate_id(player_id, kind="market choice player ID")
    actor_id = player_id if actor_id is None else actor_id
    validate_id(actor_id, kind="market decision actor ID")
    profile = next((item for item in book.player_profiles if item.player_id == player_id), None)
    if profile is None:
        raise KeyError(f"no explicit preferences for market player: {player_id}")
    candidate = next((item for item in book.candidates if item.player_id == player_id), None)
    if candidate is None:
        raise KeyError(f"player is not listed: {player_id}")
    prior_acceptance = next((item for item in book.events
                             if item.kind is MarketEventKind.PLAYER_ACCEPTED
                             and next(offer for offer in book.offers if offer.offer_id == item.offer_id).player_id == player_id), None)
    if prior_acceptance is not None:
        prior_appraisals = tuple(
            item.appraisal for item in book.events
            if item.at == prior_acceptance.at
            and next(offer for offer in book.offers if offer.offer_id == item.offer_id).player_id == player_id
            and item.appraisal is not None
        )
        return book, MarketChoice(player_id, prior_acceptance.offer_id, prior_appraisals)

    agent_mandate = None
    if actor_id != player_id:
        agent_mandate = _active_agent_mandate(book, actor_id, player_id, on)
        if agent_mandate is None:
            raise ValueError("agent choice requires an active mandate for this player")
    if on < candidate.available_on or on > candidate.expires_on:
        raise ValueError("player choice is outside the market listing window")
    if book.events and on < book.events[-1].at:
        raise ValueError("player choice cannot precede the latest market event")

    book = expire_offers(book, on)

    statuses = _statuses(book)
    eligible_offers = [
        offer for offer in book.offers
        if offer.player_id == player_id
        and (
            statuses[offer.offer_id] is OfferStatus.SELLER_ACCEPTED
            or (candidate.current_club_id is None and statuses[offer.offer_id] is OfferStatus.OPEN)
        )
        and offer.submitted_on <= on <= offer.expires_on
    ]
    appraisals = tuple(appraise_offer(profile, offer) for offer in eligible_offers)
    if agent_mandate is not None:
        appraisals = tuple(
            appraisal for appraisal in appraisals
            if agent_mandate.covers(next(offer for offer in eligible_offers
                                         if offer.offer_id == appraisal.offer_id))
        )
    if not appraisals:
        return book, MarketChoice(player_id, None, ())
    acceptable = [item for item in appraisals if item.acceptable]
    chosen = None
    if acceptable:
        offers_by_id = {item.offer_id: item for item in eligible_offers}
        chosen_appraisal = sorted(
            acceptable,
            key=lambda item: (
                -item.overall_score_bps,
                -offers_by_id[item.offer_id].weekly_wage_minor,
                -offers_by_id[item.offer_id].contract_weeks,
                item.offer_id,
            ),
        )[0]
        chosen = offers_by_id[chosen_appraisal.offer_id]
    elif agent_mandate is not None and not agent_mandate.may_decline:
        return book, MarketChoice(player_id, None, appraisals)
    if chosen is not None and agent_mandate is not None and not agent_mandate.may_accept:
        chosen = None

    event_actor = actor_id
    updated_events = list(book.events)
    accepted_without_decline_authority = (
        chosen is not None and agent_mandate is not None and not agent_mandate.may_decline
    )
    responded_offer_ids = (
        {chosen.offer_id} if accepted_without_decline_authority and chosen is not None
        else {item.offer_id for item in appraisals}
    )
    for appraisal in appraisals:
        if chosen is not None and appraisal.offer_id == chosen.offer_id:
            updated_events.append(_event(
                MarketEventKind.PLAYER_ACCEPTED, appraisal.offer_id, event_actor, on,
                appraisal=appraisal,
            ))
        elif accepted_without_decline_authority:
            continue
        else:
            updated_events.append(_event(
                MarketEventKind.PLAYER_REJECTED, appraisal.offer_id, event_actor, on,
                appraisal=appraisal,
            ))
    if chosen is not None:
        for offer in book.offers:
            if offer.player_id == player_id and offer.offer_id != chosen.offer_id and statuses[offer.offer_id] in (
                OfferStatus.OPEN, OfferStatus.SELLER_ACCEPTED,
            ) and offer.offer_id not in responded_offer_ids:
                updated_events.append(_event(
                    MarketEventKind.CLOSED_COMPETITOR, offer.offer_id,
                    event_actor, on, related_offer_id=chosen.offer_id,
                ))
    updated = MarketBook(book.candidates, book.player_profiles, book.agent_mandates,
                         book.offers, tuple(updated_events))
    return updated, MarketChoice(player_id, chosen.offer_id if chosen else None, appraisals)
