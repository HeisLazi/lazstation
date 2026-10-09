"""Evidence-backed shared-context opportunities and voluntary social offers.

This P13 slice records opportunities and consent only. An accepted mentoring
offer is not active mentorship and creates no lesson, learning, relationship
change, or personal-state change. All proposal thresholds are explicit
provisional rules rather than calibrated psychology.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import timedelta
from enum import Enum
from itertools import combinations
from typing import NewType

from games.touchline.esb.ids import EventId, derive_id, validate_id
from games.touchline.esb.people.relationships import (
    PersonId,
    RelationshipDimension,
    RelationshipEdge,
    WorldMoment,
)
from games.touchline.esb.time import WorldDate

OpportunityId = NewType("OpportunityId", str)
SocialChoiceId = NewType("SocialChoiceId", str)
SocialOfferId = NewType("SocialOfferId", str)

MIN_SHARED_CONTEXT_MINUTES = 15
MAX_SHARED_CONTEXT_GROUP_SIZE = 32
FRIENDSHIP_PROPOSAL_THRESHOLD = 0.60
FRIENDSHIP_RESPONSE_THRESHOLD = 0.60
MENTOR_TRUST_THRESHOLD = 0.55
MENTOR_PROPOSAL_THRESHOLD = 0.55
MENTOR_RESPONSE_THRESHOLD = 0.60
SOCIAL_OFFER_VALID_DAYS = 7
MENTOR_CONSENT_RESERVATION_DAYS = 7


class SessionOutcome(str, Enum):
    COMPLETED = "completed"
    SKIPPED = "skipped"


class OfferKind(str, Enum):
    FRIENDSHIP = "friendship"
    MENTORSHIP = "mentorship"


class SocialChoiceOutcome(str, Enum):
    OFFERED = "offered"
    NO_OFFER = "no_offer"
    CAPACITY_FULL = "capacity_full"


class OfferStatus(str, Enum):
    OFFERED = "offered"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    CAPACITY_UNAVAILABLE = "capacity_unavailable"
    EXPIRED = "expired"


def _fraction(value: float, label: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"{label} must be finite and normalized to [0, 1]")
    return float(value)


def _same_number(value: float, expected: float) -> bool:
    return math.isclose(float(value), float(expected), rel_tol=0.0, abs_tol=1e-10)


def _after_days(moment: WorldMoment, days: int) -> WorldMoment:
    return WorldMoment(WorldDate(moment.on.day + timedelta(days=days)), 0)


@dataclass(frozen=True)
class SessionParticipant:
    person_id: PersonId
    group_id: str
    attended_minutes: int
    arrival_minute: int = 0

    def __post_init__(self) -> None:
        validate_id(self.person_id, kind="session participant ID")
        validate_id(self.group_id, kind="shared session group ID")
        if type(self.attended_minutes) is not int or self.attended_minutes < 0:
            raise ValueError("session attendance must be non-negative whole minutes")
        if type(self.arrival_minute) is not int or self.arrival_minute < 0:
            raise ValueError("session arrival must be a non-negative whole minute")


@dataclass(frozen=True)
class SharedSession:
    """A source event with explicit attendance and shared small-group context."""

    event_id: EventId
    at: WorldMoment
    outcome: SessionOutcome
    participants: tuple[SessionParticipant, ...]

    def __post_init__(self) -> None:
        validate_id(self.event_id, kind="shared session source event ID")
        if not isinstance(self.at, WorldMoment):
            raise TypeError("shared session requires a world moment")
        if not isinstance(self.outcome, SessionOutcome):
            raise TypeError("shared session outcome must be explicit")
        if not isinstance(self.participants, tuple) or any(
            not isinstance(item, SessionParticipant) for item in self.participants
        ):
            raise TypeError("shared session participants must be an immutable tuple")
        person_ids = [item.person_id for item in self.participants]
        if len(person_ids) != len(set(person_ids)):
            raise ValueError("a person can appear once in a shared session")
        group_sizes: dict[str, int] = {}
        for item in self.participants:
            group_sizes[item.group_id] = group_sizes.get(item.group_id, 0) + 1
        if any(size > MAX_SHARED_CONTEXT_GROUP_SIZE for size in group_sizes.values()):
            raise ValueError(
                f"shared context groups are limited to {MAX_SHARED_CONTEXT_GROUP_SIZE} participants"
            )


@dataclass(frozen=True)
class ContactOpportunity:
    opportunity_id: OpportunityId
    source_event_id: EventId
    at: WorldMoment
    group_id: str
    participants: tuple[PersonId, PersonId]
    shared_minutes: int

    def __post_init__(self) -> None:
        validate_id(self.opportunity_id, kind="contact opportunity ID")
        validate_id(self.source_event_id, kind="contact opportunity source event ID")
        if not isinstance(self.at, WorldMoment):
            raise TypeError("contact opportunity requires a world moment")
        validate_id(self.group_id, kind="contact opportunity group ID")
        if not isinstance(self.participants, tuple) or len(self.participants) != 2:
            raise TypeError("contact opportunity requires an immutable pair")
        for participant in self.participants:
            validate_id(participant, kind="contact opportunity participant ID")
        if self.participants[0] == self.participants[1]:
            raise ValueError("contact opportunity participants must be different")
        if tuple(sorted(self.participants, key=str)) != self.participants:
            raise ValueError("contact opportunity participants must be canonicalized")
        if type(self.shared_minutes) is not int or self.shared_minutes < MIN_SHARED_CONTEXT_MINUTES:
            raise ValueError("contact opportunity requires meaningful shared minutes")
        expected_id = OpportunityId(derive_id(
            "opportunity", "touchline-shared-session-v1",
            str(self.source_event_id), self.group_id,
            str(self.participants[0]), str(self.participants[1]),
        ))
        if self.opportunity_id != expected_id:
            raise ValueError("contact opportunity ID does not match its source and participants")


def _opportunities_for_session(session: SharedSession) -> tuple[ContactOpportunity, ...]:
    if session.outcome is SessionOutcome.SKIPPED:
        return ()
    groups: dict[str, list[SessionParticipant]] = {}
    for participant in session.participants:
        if participant.attended_minutes >= MIN_SHARED_CONTEXT_MINUTES:
            groups.setdefault(participant.group_id, []).append(participant)
    opportunities: list[ContactOpportunity] = []
    for group_id in sorted(groups):
        attendees = sorted(groups[group_id], key=lambda item: str(item.person_id))
        for left, right in combinations(attendees, 2):
            shared_minutes = min(
                left.arrival_minute + left.attended_minutes,
                right.arrival_minute + right.attended_minutes,
            ) - max(left.arrival_minute, right.arrival_minute)
            if shared_minutes < MIN_SHARED_CONTEXT_MINUTES:
                continue
            pair = (left.person_id, right.person_id)
            opportunity_id = OpportunityId(derive_id(
                "opportunity", "touchline-shared-session-v1",
                str(session.event_id), group_id, str(pair[0]), str(pair[1]),
            ))
            opportunities.append(ContactOpportunity(
                opportunity_id=opportunity_id,
                source_event_id=session.event_id,
                at=session.at,
                group_id=group_id,
                participants=pair,
                shared_minutes=shared_minutes,
            ))
    return tuple(sorted(opportunities, key=lambda item: (item.at, str(item.opportunity_id))))


@dataclass(frozen=True)
class SocialDisposition:
    """Player-specific social choices; these are not inferred from age or role."""

    person_id: PersonId
    friendship_initiative: float = 0.5
    friendship_receptivity: float = 0.5
    mentoring_willingness: float = 0.5
    mentoring_receptivity: float = 0.5
    mentoring_interest: float = 0.5

    def __post_init__(self) -> None:
        validate_id(self.person_id, kind="social disposition person ID")
        for label in (
            "friendship initiative", "friendship receptivity",
            "mentoring willingness", "mentoring receptivity", "mentoring interest",
        ):
            _fraction(getattr(self, label.replace(" ", "_")), label)


@dataclass(frozen=True)
class MentorCapacity:
    """Current finite mentor availability, including commitments from other systems."""

    person_id: PersonId
    concurrent_slots: int
    external_commitments: int = 0

    def __post_init__(self) -> None:
        validate_id(self.person_id, kind="mentor capacity person ID")
        if type(self.concurrent_slots) is not int or self.concurrent_slots < 0:
            raise ValueError("mentor capacity must be a non-negative integer")
        if type(self.external_commitments) is not int or self.external_commitments < 0:
            raise ValueError("external mentor commitments must be non-negative")


@dataclass(frozen=True)
class SocialChoice:
    """One once-only proposal decision, including a recorded no-action result."""

    choice_id: SocialChoiceId
    opportunity_id: OpportunityId
    source_event_id: EventId
    kind: OfferKind
    initiator_id: PersonId
    recipient_id: PersonId
    at: WorldMoment
    initiator_disposition: SocialDisposition
    recipient_disposition: SocialDisposition
    relationship_dimension: RelationshipDimension | None
    relationship_value: float | None
    relationship_evidence_event_ids: tuple[EventId, ...]
    mentor_capacity: MentorCapacity | None
    outcome: SocialChoiceOutcome
    score: float
    threshold: float
    reason: str
    offer_id: SocialOfferId | None

    def __post_init__(self) -> None:
        validate_id(self.choice_id, kind="social choice ID")
        validate_id(self.opportunity_id, kind="social choice opportunity ID")
        validate_id(self.source_event_id, kind="social choice source event ID")
        if not isinstance(self.kind, OfferKind) or not isinstance(self.outcome, SocialChoiceOutcome):
            raise TypeError("social choice kind and outcome must be explicit")
        validate_id(self.initiator_id, kind="social choice initiator ID")
        validate_id(self.recipient_id, kind="social choice recipient ID")
        if self.initiator_id == self.recipient_id:
            raise ValueError("a person cannot initiate a social offer to themself")
        if not isinstance(self.at, WorldMoment):
            raise TypeError("social choice requires a world moment")
        if self.initiator_disposition.person_id != self.initiator_id:
            raise ValueError("initiator disposition does not match social choice")
        if self.recipient_disposition.person_id != self.recipient_id:
            raise ValueError("recipient disposition does not match social choice")
        if self.relationship_dimension is not None and not isinstance(
            self.relationship_dimension, RelationshipDimension
        ):
            raise TypeError("social choice relationship dimension must be explicit")
        if self.relationship_value is not None:
            _fraction(self.relationship_value, "social choice relationship value")
        if not isinstance(self.relationship_evidence_event_ids, tuple):
            raise TypeError("relationship evidence references must be an immutable tuple")
        for event_id in self.relationship_evidence_event_ids:
            validate_id(event_id, kind="social choice relationship evidence ID")
        if len(set(self.relationship_evidence_event_ids)) != len(self.relationship_evidence_event_ids):
            raise ValueError("social choice relationship evidence cannot be repeated")
        if self.relationship_dimension is None and self.relationship_value is not None:
            raise ValueError("relationship value requires a named dimension")
        if self.relationship_value is None and self.relationship_evidence_event_ids:
            raise ValueError("unknown relationship value cannot claim supporting evidence")
        if self.kind is OfferKind.MENTORSHIP:
            if self.mentor_capacity is None or self.mentor_capacity.person_id != self.initiator_id:
                raise ValueError("mentoring choice requires the initiator's capacity snapshot")
            if self.relationship_dimension is not RelationshipDimension.TRUST:
                raise ValueError("mentoring choice must record its trust factor")
        elif self.mentor_capacity is not None:
            raise ValueError("friendship choice cannot reserve mentor capacity")
        _fraction(self.score, "social choice score")
        _fraction(self.threshold, "social choice threshold")
        validate_id(self.reason, kind="social choice reason")
        if self.kind is OfferKind.FRIENDSHIP:
            affinity = 0.5 if self.relationship_value is None else self.relationship_value
            expected_score = self.initiator_disposition.friendship_initiative * (0.5 + 0.5 * affinity)
            expected_outcome = (
                SocialChoiceOutcome.OFFERED
                if expected_score >= FRIENDSHIP_PROPOSAL_THRESHOLD
                else SocialChoiceOutcome.NO_OFFER
            )
            expected_reason = "friendship_interest" if expected_outcome is SocialChoiceOutcome.OFFERED else "initiative_below_threshold"
            if self.relationship_dimension is not RelationshipDimension.AFFINITY:
                raise ValueError("friendship choice must record its affinity factor")
            if not _same_number(self.score, expected_score) or self.threshold != FRIENDSHIP_PROPOSAL_THRESHOLD:
                raise ValueError("friendship choice score does not match its explicit inputs")
            if self.outcome is not expected_outcome or self.reason != expected_reason:
                raise ValueError("friendship choice outcome does not match its score")
        else:
            if self.threshold != MENTOR_PROPOSAL_THRESHOLD:
                raise ValueError("mentoring proposal threshold is not supported")
            if self.relationship_value is None or self.relationship_value < MENTOR_TRUST_THRESHOLD:
                expected_score = 0.0
                expected_outcome = SocialChoiceOutcome.NO_OFFER
                expected_reason = "trust_not_established"
            else:
                expected_score = (
                    self.initiator_disposition.mentoring_willingness
                    * self.recipient_disposition.mentoring_interest
                    * self.relationship_value
                )
                base_outcome = (
                    SocialChoiceOutcome.OFFERED
                    if expected_score >= MENTOR_PROPOSAL_THRESHOLD
                    else SocialChoiceOutcome.NO_OFFER
                )
                expected_outcome = base_outcome
                expected_reason = (
                    "willing_trusted_mentor"
                    if base_outcome is SocialChoiceOutcome.OFFERED
                    else "mentoring_interest_below_threshold"
                )
                if self.outcome is SocialChoiceOutcome.CAPACITY_FULL:
                    expected_outcome = SocialChoiceOutcome.CAPACITY_FULL
                    expected_reason = "mentor_capacity_full"
            if not _same_number(self.score, expected_score):
                raise ValueError("mentoring choice score does not match its explicit inputs")
            if self.outcome is not expected_outcome or self.reason != expected_reason:
                raise ValueError("mentoring choice outcome does not match its score and trust evidence")
        if self.outcome is SocialChoiceOutcome.OFFERED:
            if self.offer_id is None:
                raise ValueError("an offered choice must identify its offer")
            validate_id(self.offer_id, kind="social choice offer ID")
            expected_offer_id = SocialOfferId(derive_id(
                "social-offer", "touchline-social-offer-v1",
                str(self.opportunity_id), self.kind.value,
                str(self.initiator_id), str(self.recipient_id),
            ))
            if self.offer_id != expected_offer_id:
                raise ValueError("social choice offer ID does not match its participants")
        elif self.offer_id is not None:
            raise ValueError("a non-offered choice cannot identify an offer")
        expected_id = SocialChoiceId(derive_id(
            "social-choice", "touchline-social-choice-v1",
            str(self.opportunity_id), self.kind.value,
            str(self.initiator_id), str(self.recipient_id),
        ))
        if self.choice_id != expected_id:
            raise ValueError("social choice ID does not match its opportunity and participants")


@dataclass(frozen=True)
class SocialOffer:
    offer_id: SocialOfferId
    choice_id: SocialChoiceId
    opportunity_id: OpportunityId
    source_event_id: EventId
    kind: OfferKind
    initiator_id: PersonId
    recipient_id: PersonId
    offered_at: WorldMoment
    expires_at: WorldMoment
    status: OfferStatus = OfferStatus.OFFERED
    response_event_id: EventId | None = None
    responded_at: WorldMoment | None = None
    recipient_disposition: SocialDisposition | None = None
    response_relationship_dimension: RelationshipDimension | None = None
    response_relationship_value: float | None = None
    response_relationship_evidence_event_ids: tuple[EventId, ...] = ()
    response_capacity: MentorCapacity | None = None
    reservation_until: WorldMoment | None = None
    response_score: float | None = None
    response_threshold: float | None = None
    response_reason: str | None = None

    def __post_init__(self) -> None:
        for value, label in (
            (self.offer_id, "social offer ID"), (self.choice_id, "social offer choice ID"),
            (self.opportunity_id, "social offer opportunity ID"),
            (self.source_event_id, "social offer source event ID"),
            (self.initiator_id, "social offer initiator ID"),
            (self.recipient_id, "social offer recipient ID"),
        ):
            validate_id(value, kind=label)
        if not isinstance(self.kind, OfferKind) or not isinstance(self.status, OfferStatus):
            raise TypeError("social offer kind and status must be explicit")
        if self.initiator_id == self.recipient_id:
            raise ValueError("a social offer requires two different people")
        if not isinstance(self.offered_at, WorldMoment):
            raise TypeError("social offer requires a world moment")
        expected_id = SocialOfferId(derive_id(
            "social-offer", "touchline-social-offer-v1",
            str(self.opportunity_id), self.kind.value,
            str(self.initiator_id), str(self.recipient_id),
        ))
        if self.offer_id != expected_id:
            raise ValueError("social offer ID does not match its source opportunity and participants")
        expected_choice = SocialChoiceId(derive_id(
            "social-choice", "touchline-social-choice-v1",
            str(self.opportunity_id), self.kind.value,
            str(self.initiator_id), str(self.recipient_id),
        ))
        if self.choice_id != expected_choice:
            raise ValueError("social offer choice does not match its participants")
        if not isinstance(self.expires_at, WorldMoment) or self.expires_at != _after_days(
            self.offered_at, SOCIAL_OFFER_VALID_DAYS
        ):
            raise ValueError("social offer must retain the versioned seven-day expiry")
        has_response = self.status in (
            OfferStatus.ACCEPTED,
            OfferStatus.DECLINED,
            OfferStatus.CAPACITY_UNAVAILABLE,
        )
        expired = self.status is OfferStatus.EXPIRED
        response_fields = (
            self.response_event_id, self.responded_at, self.response_reason,
        )
        if (has_response or expired) != all(value is not None for value in response_fields):
            raise ValueError("resolved social offers require a complete resolution record")
        if has_response:
            validate_id(self.response_event_id, kind="social offer response event ID")
            expected_response_id = EventId(derive_id(
                "event", "touchline-social-offer-response-v1", str(self.offer_id)
            ))
            if self.response_event_id != expected_response_id:
                raise ValueError("social offer response event ID does not match its offer")
            if (
                not isinstance(self.responded_at, WorldMoment)
                or self.responded_at <= self.offered_at
                or self.responded_at >= self.expires_at
            ):
                raise ValueError("social offer response must precede its seven-day expiry")
            if self.recipient_disposition.person_id != self.recipient_id:
                raise ValueError("response disposition does not match social offer recipient")
            _fraction(self.response_score, "social offer response score")
            _fraction(self.response_threshold, "social offer response threshold")
            validate_id(self.response_reason, kind="social offer response reason")
        elif expired:
            expected_expiry_id = EventId(derive_id(
                "event", "touchline-social-offer-expired-v1", str(self.offer_id)
            ))
            if self.response_event_id != expected_expiry_id:
                raise ValueError("expired offer event ID does not match its offer")
            if not isinstance(self.responded_at, WorldMoment) or self.responded_at < self.expires_at:
                raise ValueError("social offer cannot expire before its seven-day deadline")
            if self.response_reason != "offer_expired":
                raise ValueError("expired offer requires the offer_expired reason")
            if any(value is not None for value in (
                self.recipient_disposition, self.response_capacity,
                self.reservation_until, self.response_score, self.response_threshold,
                self.response_relationship_dimension, self.response_relationship_value,
            )) or self.response_relationship_evidence_event_ids:
                raise ValueError("offer expiry cannot invent a response or capacity reservation")
        elif any(value is not None for value in response_fields) or self.response_capacity is not None:
            raise ValueError("pending social offer cannot contain a response")
        if not has_response and any(value is not None for value in (
            self.recipient_disposition, self.response_score, self.response_threshold,
        )):
            raise ValueError("offer expiry cannot invent a recipient response")
        if not has_response and self.response_relationship_evidence_event_ids:
            raise ValueError("unanswered or expired offers cannot cite response evidence")
        if self.response_relationship_dimension is not None and not isinstance(
            self.response_relationship_dimension, RelationshipDimension
        ):
            raise TypeError("response relationship dimension must be explicit")
        if self.response_relationship_value is not None:
            _fraction(self.response_relationship_value, "response relationship value")
        if self.response_relationship_dimension is None and self.response_relationship_value is not None:
            raise ValueError("response relationship value requires a named dimension")
        if self.response_relationship_value is None and self.response_relationship_evidence_event_ids:
            raise ValueError("unknown response relationship value cannot claim supporting evidence")
        if not isinstance(self.response_relationship_evidence_event_ids, tuple):
            raise TypeError("response relationship evidence must be an immutable tuple")
        for event_id in self.response_relationship_evidence_event_ids:
            validate_id(event_id, kind="response relationship evidence ID")
        if self.kind is OfferKind.MENTORSHIP:
            if has_response and (
                self.response_capacity is None
                or self.response_capacity.person_id != self.initiator_id
            ):
                raise ValueError("mentoring response must record rechecked mentor capacity")
        elif self.response_capacity is not None:
            raise ValueError("friendship response cannot reserve mentor capacity")
        if has_response:
            if self.kind is OfferKind.FRIENDSHIP:
                if self.response_relationship_dimension is not RelationshipDimension.AFFINITY:
                    raise ValueError("friendship response must record its affinity decision stage")
                affinity = 0.5 if self.response_relationship_value is None else self.response_relationship_value
                expected_score = self.recipient_disposition.friendship_receptivity * (0.5 + 0.5 * affinity)
                expected_threshold = FRIENDSHIP_RESPONSE_THRESHOLD
                expected_status = (
                    OfferStatus.ACCEPTED if expected_score >= expected_threshold else OfferStatus.DECLINED
                )
                expected_reason = (
                    "friendship_offer_accepted"
                    if expected_status is OfferStatus.ACCEPTED
                    else "friendship_receptivity_below_threshold"
                )
                if self.status is OfferStatus.CAPACITY_UNAVAILABLE:
                    raise ValueError("friendship response cannot fail mentor capacity")
            else:
                if (
                    self.response_relationship_dimension is not None
                    or self.response_relationship_value is not None
                    or self.response_relationship_evidence_event_ids
                ):
                    raise ValueError("mentoring response uses receptivity; trust was assessed at proposal")
                expected_score = self.recipient_disposition.mentoring_receptivity
                expected_threshold = MENTOR_RESPONSE_THRESHOLD
                expected_status = (
                    OfferStatus.ACCEPTED if expected_score >= expected_threshold else OfferStatus.DECLINED
                )
                expected_reason = (
                    "mentoring_offer_accepted"
                    if expected_status is OfferStatus.ACCEPTED
                    else "mentoring_receptivity_below_threshold"
                )
            if not _same_number(self.response_score, expected_score):
                raise ValueError("social response score does not match recipient disposition")
            if self.response_threshold != expected_threshold:
                raise ValueError("social response threshold is not supported")
            if self.status is not OfferStatus.CAPACITY_UNAVAILABLE and self.status is not expected_status:
                raise ValueError("social response outcome does not match its score")
            if self.status is OfferStatus.CAPACITY_UNAVAILABLE:
                expected_reason = "mentor_capacity_changed"
            if self.response_reason != expected_reason:
                raise ValueError("social response reason does not match its outcome")
        elif not expired and any(value is not None for value in (
            self.response_relationship_dimension, self.response_relationship_value,
            self.reservation_until,
        )):
            raise ValueError("unanswered offer cannot contain response-stage state")
        expected_reservation_until = (
            _after_days(self.responded_at, MENTOR_CONSENT_RESERVATION_DAYS)
            if self.status is OfferStatus.ACCEPTED and self.kind is OfferKind.MENTORSHIP
            else None
        )
        if self.reservation_until != expected_reservation_until:
            raise ValueError("mentor consent reservation must expire seven days after acceptance")


@dataclass(frozen=True)
class SocialIntroduction:
    event_id: EventId
    offer_id: SocialOfferId
    opportunity_id: OpportunityId
    source_event_id: EventId
    participants: tuple[PersonId, PersonId]
    at: WorldMoment

    def __post_init__(self) -> None:
        for value, label in (
            (self.event_id, "social introduction event ID"),
            (self.offer_id, "social introduction offer ID"),
            (self.opportunity_id, "social introduction opportunity ID"),
            (self.source_event_id, "social introduction source event ID"),
        ):
            validate_id(value, kind=label)
        if not isinstance(self.participants, tuple) or len(self.participants) != 2:
            raise TypeError("social introduction requires an immutable participant pair")
        for participant in self.participants:
            validate_id(participant, kind="social introduction participant ID")
        if self.participants[0] == self.participants[1]:
            raise ValueError("social introduction requires two different people")
        if not isinstance(self.at, WorldMoment):
            raise TypeError("social introduction requires a world moment")
        expected_id = EventId(derive_id(
            "event", "touchline-social-introduction-v1", str(self.offer_id)
        ))
        if self.event_id != expected_id:
            raise ValueError("social introduction ID does not match its accepted offer")


@dataclass(frozen=True)
class SocialLedger:
    """Immutable event-sourced subset for social context, choices and consent."""

    sessions: tuple[SharedSession, ...] = ()
    opportunities: tuple[ContactOpportunity, ...] = ()
    choices: tuple[SocialChoice, ...] = ()
    offers: tuple[SocialOffer, ...] = ()
    introductions: tuple[SocialIntroduction, ...] = ()

    def __post_init__(self) -> None:
        for field_name, value, expected_type in (
            ("sessions", self.sessions, SharedSession),
            ("opportunities", self.opportunities, ContactOpportunity),
            ("choices", self.choices, SocialChoice),
            ("offers", self.offers, SocialOffer),
            ("introductions", self.introductions, SocialIntroduction),
        ):
            if not isinstance(value, tuple) or any(not isinstance(item, expected_type) for item in value):
                raise TypeError(f"social ledger {field_name} must be an immutable record tuple")
        session_ids = [item.event_id for item in self.sessions]
        if len(session_ids) != len(set(session_ids)):
            raise ValueError("social ledger cannot repeat a source session event")
        if tuple(sorted(self.sessions, key=lambda item: (item.at, str(item.event_id)))) != self.sessions:
            raise ValueError("social sessions must retain event chronology")
        expected_opportunities = tuple(sorted(
            (opportunity for session in self.sessions for opportunity in _opportunities_for_session(session)),
            key=lambda item: (item.at, str(item.opportunity_id)),
        ))
        if self.opportunities != expected_opportunities:
            raise ValueError("social opportunities must match completed shared-session evidence")
        opportunity_map = {item.opportunity_id: item for item in self.opportunities}
        choice_ids = [item.choice_id for item in self.choices]
        if len(choice_ids) != len(set(choice_ids)):
            raise ValueError("social opportunity choices cannot be replayed with conflicting content")
        if tuple(sorted(self.choices, key=lambda item: (item.at, str(item.choice_id)))) != self.choices:
            raise ValueError("social choices must retain event chronology")
        choice_map = {item.choice_id: item for item in self.choices}
        for choice in self.choices:
            opportunity = opportunity_map.get(choice.opportunity_id)
            if opportunity is None or choice.source_event_id != opportunity.source_event_id:
                raise ValueError("social choice must cite an existing session opportunity")
            if set(opportunity.participants) != {choice.initiator_id, choice.recipient_id}:
                raise ValueError("social choice participants must share its opportunity")
            if choice.at <= opportunity.at:
                raise ValueError("social choice must follow its shared context")
        offer_ids = [item.offer_id for item in self.offers]
        if len(offer_ids) != len(set(offer_ids)):
            raise ValueError("social offers cannot be duplicated")
        if tuple(sorted(self.offers, key=lambda item: (item.offered_at, str(item.offer_id)))) != self.offers:
            raise ValueError("social offers must retain event chronology")
        offer_map = {item.offer_id: item for item in self.offers}
        for choice in self.choices:
            if choice.outcome is SocialChoiceOutcome.OFFERED:
                if choice.offer_id not in offer_map:
                    raise ValueError("offered social choice must have its corresponding offer")
        for offer in self.offers:
            choice = choice_map.get(offer.choice_id)
            opportunity = opportunity_map.get(offer.opportunity_id)
            if choice is None or choice.outcome is not SocialChoiceOutcome.OFFERED:
                raise ValueError("social offer must cite an offered choice")
            if opportunity is None or offer.source_event_id != opportunity.source_event_id:
                raise ValueError("social offer must retain its shared-session source")
            if (
                choice.offer_id != offer.offer_id
                or choice.opportunity_id != offer.opportunity_id
                or choice.kind is not offer.kind
                or choice.initiator_id != offer.initiator_id
                or choice.recipient_id != offer.recipient_id
                or choice.at != offer.offered_at
            ):
                raise ValueError("social offer participants and timing must match their choice")
        event_moments = [item.at for item in self.sessions]
        event_moments.extend(item.at for item in self.choices)
        event_moments.extend(
            item.responded_at for item in self.offers if item.responded_at is not None
        )
        if len(event_moments) != len(set(event_moments)):
            raise ValueError("distinct social events require distinct world moments")
        for choice in self.choices:
            if choice.kind is not OfferKind.MENTORSHIP or choice.outcome not in (
                SocialChoiceOutcome.OFFERED,
                SocialChoiceOutcome.CAPACITY_FULL,
            ):
                continue
            capacity = choice.mentor_capacity
            used = capacity.external_commitments + _reserved_mentor_slots(
                self, choice.initiator_id, choice.at, excluding=choice.offer_id
            )
            capacity_was_full = used >= capacity.concurrent_slots
            if (choice.outcome is SocialChoiceOutcome.CAPACITY_FULL) != capacity_was_full:
                raise ValueError("mentoring proposal outcome does not match capacity at its event time")
        for offer in self.offers:
            if (
                offer.kind is not OfferKind.MENTORSHIP
                or offer.status not in (
                    OfferStatus.ACCEPTED,
                    OfferStatus.DECLINED,
                    OfferStatus.CAPACITY_UNAVAILABLE,
                )
            ):
                continue
            capacity = offer.response_capacity
            used = capacity.external_commitments + 1 + _reserved_mentor_slots(
                self, offer.initiator_id, offer.responded_at, excluding=offer.offer_id
            )
            capacity_unavailable = used > capacity.concurrent_slots
            if (offer.status is OfferStatus.CAPACITY_UNAVAILABLE) != capacity_unavailable:
                raise ValueError("mentoring response outcome does not match its capacity snapshot")
        introduction_ids = [item.event_id for item in self.introductions]
        introduction_offer_ids = [item.offer_id for item in self.introductions]
        if len(introduction_ids) != len(set(introduction_ids)) or len(introduction_offer_ids) != len(set(introduction_offer_ids)):
            raise ValueError("accepted social offers can create only one introduction")
        if tuple(sorted(self.introductions, key=lambda item: (item.at, str(item.event_id)))) != self.introductions:
            raise ValueError("social introductions must retain event chronology")
        introductions_by_offer = {item.offer_id: item for item in self.introductions}
        for offer in self.offers:
            introduction = introductions_by_offer.get(offer.offer_id)
            if (offer.status is OfferStatus.ACCEPTED) != (introduction is not None):
                raise ValueError("only accepted offers can create an introduction")
            if introduction is not None and (
                introduction.opportunity_id != offer.opportunity_id
                or introduction.source_event_id != offer.source_event_id
                or set(introduction.participants) != {offer.initiator_id, offer.recipient_id}
                or introduction.at != offer.responded_at
            ):
                raise ValueError("introduction must retain its accepted offer lineage")


@dataclass(frozen=True)
class OfferDecision:
    choice: SocialChoice
    offer: SocialOffer | None

    def __post_init__(self) -> None:
        if not isinstance(self.choice, SocialChoice):
            raise TypeError("offer decision requires a persisted social choice")
        if self.choice.outcome is SocialChoiceOutcome.OFFERED:
            if not isinstance(self.offer, SocialOffer) or self.choice.offer_id != self.offer.offer_id:
                raise ValueError("offered decision must include its persisted offer")
        elif self.offer is not None:
            raise ValueError("no-offer decisions cannot include a social offer")


def record_shared_session(ledger: SocialLedger, session: SharedSession) -> SocialLedger:
    """Persist one dated session and derive opportunities from actual co-attendance."""

    if not isinstance(ledger, SocialLedger) or not isinstance(session, SharedSession):
        raise TypeError("shared-session recording requires a social ledger and session")
    prior = next((item for item in ledger.sessions if item.event_id == session.event_id), None)
    if prior is not None:
        if prior != session:
            raise ValueError("shared session event ID was replayed with conflicting content")
        return ledger
    if ledger.sessions and session.at <= ledger.sessions[-1].at:
        raise ValueError("shared sessions must be recorded in world chronology")
    sessions = ledger.sessions + (session,)
    opportunities = tuple(sorted(
        ledger.opportunities + _opportunities_for_session(session),
        key=lambda item: (item.at, str(item.opportunity_id)),
    ))
    return SocialLedger(
        sessions=sessions,
        opportunities=opportunities,
        choices=ledger.choices,
        offers=ledger.offers,
        introductions=ledger.introductions,
    )


def _relationship_value(
    edge: RelationshipEdge | None,
    source_id: PersonId,
    target_id: PersonId,
    dimension: RelationshipDimension,
    *,
    as_of: WorldMoment | None = None,
) -> tuple[float | None, tuple[EventId, ...]]:
    if edge is None:
        return None, ()
    if not isinstance(edge, RelationshipEdge):
        raise TypeError("social choice relationship input must be a RelationshipEdge")
    if edge.source_person_id != source_id or edge.target_person_id != target_id:
        raise ValueError("social choice requires the initiator-to-recipient relationship direction")
    value = next((item for item in edge.dimensions if item.dimension is dimension), None)
    if value is None:
        return None, ()
    if as_of is not None:
        evidence_by_id = {item.event_id: item for item in edge.evidence}
        if any(evidence_by_id[event_id].at > as_of for event_id in value.supporting_event_ids):
            raise ValueError("social decision cannot use relationship evidence from the future")
    return float(value.value), value.supporting_event_ids


def _choice_id(opportunity_id: OpportunityId, kind: OfferKind,
               initiator_id: PersonId, recipient_id: PersonId) -> SocialChoiceId:
    return SocialChoiceId(derive_id(
        "social-choice", "touchline-social-choice-v1",
        str(opportunity_id), kind.value, str(initiator_id), str(recipient_id),
    ))


def _offer_id(opportunity_id: OpportunityId, kind: OfferKind,
              initiator_id: PersonId, recipient_id: PersonId) -> SocialOfferId:
    return SocialOfferId(derive_id(
        "social-offer", "touchline-social-offer-v1",
        str(opportunity_id), kind.value, str(initiator_id), str(recipient_id),
    ))


def _reserves_mentor_slot(offer: SocialOffer, at: WorldMoment) -> bool:
    if offer.status is OfferStatus.OFFERED:
        return offer.offered_at < at < offer.expires_at
    if offer.status is OfferStatus.ACCEPTED:
        return offer.responded_at <= at < offer.reservation_until
    if offer.status in (OfferStatus.DECLINED, OfferStatus.CAPACITY_UNAVAILABLE):
        return offer.offered_at < at < offer.responded_at
    if offer.status is OfferStatus.EXPIRED:
        return offer.offered_at < at < offer.expires_at
    return False


def _reserved_mentor_slots(ledger: SocialLedger, person_id: PersonId, at: WorldMoment,
                           *, excluding: SocialOfferId | None = None) -> int:
    return sum(
        1 for offer in ledger.offers
        if offer.kind is OfferKind.MENTORSHIP
        and offer.initiator_id == person_id
        and offer.offer_id != excluding
        and _reserves_mentor_slot(offer, at)
    )


def propose_autonomous_offer(
    ledger: SocialLedger,
    *,
    opportunity_id: OpportunityId,
    kind: OfferKind,
    initiator: SocialDisposition,
    recipient: SocialDisposition,
    at: WorldMoment,
    relationship: RelationshipEdge | None = None,
    mentor_capacity: MentorCapacity | None = None,
) -> tuple[SocialLedger, OfferDecision]:
    """Record one explainable player-originated offer choice for an opportunity."""

    if not isinstance(ledger, SocialLedger):
        raise TypeError("autonomous social offer requires a SocialLedger")
    if not isinstance(kind, OfferKind):
        raise TypeError("social offer kind must be explicit")
    if not isinstance(initiator, SocialDisposition) or not isinstance(recipient, SocialDisposition):
        raise TypeError("social offer choice requires both players' social dispositions")
    if not isinstance(at, WorldMoment):
        raise TypeError("social offer choice requires a world moment")
    opportunity = next((item for item in ledger.opportunities if item.opportunity_id == opportunity_id), None)
    if opportunity is None:
        raise ValueError("social offer requires a recorded shared-context opportunity")
    if {initiator.person_id, recipient.person_id} != set(opportunity.participants):
        raise ValueError("social offer participants must be present in the opportunity")
    if at <= opportunity.at:
        raise ValueError("social offer must follow its shared context")
    if kind is OfferKind.MENTORSHIP:
        if not isinstance(mentor_capacity, MentorCapacity):
            raise TypeError("mentoring proposal requires a current capacity record")
        if mentor_capacity.person_id != initiator.person_id:
            raise ValueError("mentor capacity must belong to the offer initiator")
        relationship_dimension = RelationshipDimension.TRUST
        relationship_value, evidence_ids = _relationship_value(
            relationship, initiator.person_id, recipient.person_id,
            relationship_dimension, as_of=at,
        )
        if relationship_value is None or relationship_value < MENTOR_TRUST_THRESHOLD:
            score = 0.0
            threshold = MENTOR_PROPOSAL_THRESHOLD
            outcome = SocialChoiceOutcome.NO_OFFER
            reason = "trust_not_established"
        else:
            score = initiator.mentoring_willingness * recipient.mentoring_interest * relationship_value
            threshold = MENTOR_PROPOSAL_THRESHOLD
            outcome = SocialChoiceOutcome.OFFERED if score >= threshold else SocialChoiceOutcome.NO_OFFER
            reason = "willing_trusted_mentor" if outcome is SocialChoiceOutcome.OFFERED else "mentoring_interest_below_threshold"
        capacity_snapshot = mentor_capacity
    else:
        if mentor_capacity is not None:
            raise ValueError("friendship offer cannot consume mentor capacity")
        relationship_dimension = RelationshipDimension.AFFINITY
        relationship_value, evidence_ids = _relationship_value(
            relationship, initiator.person_id, recipient.person_id,
            relationship_dimension, as_of=at,
        )
        affinity = 0.5 if relationship_value is None else relationship_value
        score = initiator.friendship_initiative * (0.5 + 0.5 * affinity)
        threshold = FRIENDSHIP_PROPOSAL_THRESHOLD
        outcome = SocialChoiceOutcome.OFFERED if score >= threshold else SocialChoiceOutcome.NO_OFFER
        reason = "friendship_interest" if outcome is SocialChoiceOutcome.OFFERED else "initiative_below_threshold"
        capacity_snapshot = None

    candidate_offer_id = _offer_id(opportunity_id, kind, initiator.person_id, recipient.person_id)
    if outcome is SocialChoiceOutcome.OFFERED and kind is OfferKind.MENTORSHIP:
        used = mentor_capacity.external_commitments + _reserved_mentor_slots(
            ledger, initiator.person_id, at, excluding=candidate_offer_id
        )
        if used >= mentor_capacity.concurrent_slots:
            outcome = SocialChoiceOutcome.CAPACITY_FULL
            reason = "mentor_capacity_full"
    choice = SocialChoice(
        choice_id=_choice_id(opportunity_id, kind, initiator.person_id, recipient.person_id),
        opportunity_id=opportunity_id,
        source_event_id=opportunity.source_event_id,
        kind=kind,
        initiator_id=initiator.person_id,
        recipient_id=recipient.person_id,
        at=at,
        initiator_disposition=initiator,
        recipient_disposition=recipient,
        relationship_dimension=relationship_dimension,
        relationship_value=relationship_value,
        relationship_evidence_event_ids=evidence_ids,
        mentor_capacity=capacity_snapshot,
        outcome=outcome,
        score=score,
        threshold=threshold,
        reason=reason,
        offer_id=candidate_offer_id if outcome is SocialChoiceOutcome.OFFERED else None,
    )
    previous = next((item for item in ledger.choices if item.choice_id == choice.choice_id), None)
    if previous is not None:
        if previous != choice:
            raise ValueError("social choice ID was replayed with conflicting inputs")
        existing_offer = next((item for item in ledger.offers if item.offer_id == candidate_offer_id), None)
        return ledger, OfferDecision(previous, existing_offer)

    choices = tuple(sorted(ledger.choices + (choice,), key=lambda item: (item.at, str(item.choice_id))))
    if outcome is not SocialChoiceOutcome.OFFERED:
        updated = SocialLedger(ledger.sessions, ledger.opportunities, choices, ledger.offers, ledger.introductions)
        return updated, OfferDecision(choice, None)
    offer = SocialOffer(
        offer_id=candidate_offer_id,
        choice_id=choice.choice_id,
        opportunity_id=opportunity_id,
        source_event_id=opportunity.source_event_id,
        kind=kind,
        initiator_id=initiator.person_id,
        recipient_id=recipient.person_id,
        offered_at=at,
        expires_at=_after_days(at, SOCIAL_OFFER_VALID_DAYS),
    )
    offers = tuple(sorted(ledger.offers + (offer,), key=lambda item: (item.offered_at, str(item.offer_id))))
    updated = SocialLedger(ledger.sessions, ledger.opportunities, choices, offers, ledger.introductions)
    return updated, OfferDecision(choice, offer)


def expire_offer(
    ledger: SocialLedger,
    *,
    offer_id: SocialOfferId,
    at: WorldMoment,
) -> tuple[SocialLedger, SocialOffer]:
    """Expire an unanswered offer at or after its explicit seven-day deadline."""

    if not isinstance(ledger, SocialLedger) or not isinstance(at, WorldMoment):
        raise TypeError("social offer expiry requires a ledger and world moment")
    offer_index = next((index for index, item in enumerate(ledger.offers) if item.offer_id == offer_id), None)
    if offer_index is None:
        raise ValueError("cannot expire an unknown social offer")
    offer = ledger.offers[offer_index]
    if offer.status is OfferStatus.EXPIRED:
        if offer.responded_at == at:
            return ledger, offer
        raise ValueError("offer expiry was replayed with a conflicting world moment")
    if offer.status is not OfferStatus.OFFERED:
        raise ValueError("only unanswered offers can expire")
    if at < offer.expires_at:
        raise ValueError("social offer has not reached its seven-day expiry")
    expired = replace(
        offer,
        status=OfferStatus.EXPIRED,
        response_event_id=EventId(derive_id(
            "event", "touchline-social-offer-expired-v1", str(offer.offer_id)
        )),
        responded_at=at,
        response_reason="offer_expired",
    )
    offers = list(ledger.offers)
    offers[offer_index] = expired
    updated = SocialLedger(
        ledger.sessions, ledger.opportunities, ledger.choices,
        tuple(offers), ledger.introductions,
    )
    return updated, expired


def respond_to_offer(
    ledger: SocialLedger,
    *,
    offer_id: SocialOfferId,
    recipient: SocialDisposition,
    at: WorldMoment,
    relationship: RelationshipEdge | None = None,
    mentor_capacity: MentorCapacity | None = None,
) -> tuple[SocialLedger, SocialOffer]:
    """Record the recipient's autonomous consent decision and linked introduction."""

    if not isinstance(ledger, SocialLedger):
        raise TypeError("offer response requires a SocialLedger")
    offer_index = next((index for index, item in enumerate(ledger.offers) if item.offer_id == offer_id), None)
    if offer_index is None:
        raise ValueError("cannot respond to an unknown social offer")
    offer = ledger.offers[offer_index]
    if not isinstance(recipient, SocialDisposition) or recipient.person_id != offer.recipient_id:
        raise ValueError("only the named offer recipient can respond")
    if not isinstance(at, WorldMoment):
        raise TypeError("offer response requires a world moment")
    if offer.status is OfferStatus.EXPIRED:
        if offer.responded_at == at:
            return ledger, offer
        raise ValueError("expired offer cannot be accepted")
    if offer.status is not OfferStatus.OFFERED:
        response_value = None
        evidence_ids: tuple[EventId, ...] = ()
        dimension = None
        if offer.kind is OfferKind.FRIENDSHIP and relationship is not None:
            dimension = RelationshipDimension.AFFINITY
            response_value, evidence_ids = _relationship_value(
                relationship, offer.initiator_id, offer.recipient_id,
                dimension, as_of=at,
            )
        elif offer.kind is OfferKind.MENTORSHIP and relationship is not None:
            raise ValueError("mentoring response uses the recipient's receptivity; trust was assessed at proposal")
        if (
            offer.recipient_disposition == recipient
            and offer.responded_at == at
            and offer.response_relationship_dimension == dimension
            and offer.response_relationship_value == response_value
            and offer.response_relationship_evidence_event_ids == evidence_ids
            and offer.response_capacity == mentor_capacity
        ):
            return ledger, offer
        raise ValueError("social offer response was replayed with conflicting inputs")
    if at <= offer.offered_at:
        raise ValueError("offer response must follow the offer chronologically")
    if at >= offer.expires_at:
        updated, expired = expire_offer(ledger, offer_id=offer_id, at=at)
        return updated, expired

    if offer.kind is OfferKind.MENTORSHIP:
        if relationship is not None:
            raise ValueError("mentoring response uses the recipient's receptivity; trust was assessed at proposal")
        if not isinstance(mentor_capacity, MentorCapacity) or mentor_capacity.person_id != offer.initiator_id:
            raise ValueError("mentoring response requires a current capacity check for the mentor")
        dimension = None
        relationship_value = None
        evidence_ids = ()
        threshold = MENTOR_RESPONSE_THRESHOLD
        score = recipient.mentoring_receptivity
        used = (
            mentor_capacity.external_commitments
            + _reserved_mentor_slots(ledger, offer.initiator_id, at, excluding=offer.offer_id)
            + 1
        )
        if used > mentor_capacity.concurrent_slots:
            status = OfferStatus.CAPACITY_UNAVAILABLE
            reason = "mentor_capacity_changed"
        elif score >= threshold:
            status = OfferStatus.ACCEPTED
            reason = "mentoring_offer_accepted"
        else:
            status = OfferStatus.DECLINED
            reason = "mentoring_receptivity_below_threshold"
        capacity_snapshot = mentor_capacity
    else:
        if mentor_capacity is not None:
            raise ValueError("friendship response cannot consume mentor capacity")
        dimension = RelationshipDimension.AFFINITY
        relationship_value, evidence_ids = _relationship_value(
            relationship, offer.initiator_id, offer.recipient_id,
            dimension, as_of=at,
        )
        affinity = 0.5 if relationship_value is None else relationship_value
        threshold = FRIENDSHIP_RESPONSE_THRESHOLD
        score = recipient.friendship_receptivity * (0.5 + 0.5 * affinity)
        status = OfferStatus.ACCEPTED if score >= threshold else OfferStatus.DECLINED
        reason = "friendship_offer_accepted" if status is OfferStatus.ACCEPTED else "friendship_receptivity_below_threshold"
        capacity_snapshot = None

    response_event_id = EventId(derive_id(
        "event", "touchline-social-offer-response-v1", str(offer.offer_id)
    ))
    responded = SocialOffer(
        offer_id=offer.offer_id,
        choice_id=offer.choice_id,
        opportunity_id=offer.opportunity_id,
        source_event_id=offer.source_event_id,
        kind=offer.kind,
        initiator_id=offer.initiator_id,
        recipient_id=offer.recipient_id,
        offered_at=offer.offered_at,
        expires_at=offer.expires_at,
        status=status,
        response_event_id=response_event_id,
        responded_at=at,
        recipient_disposition=recipient,
        response_relationship_dimension=dimension,
        response_relationship_value=relationship_value,
        response_relationship_evidence_event_ids=evidence_ids,
        response_capacity=capacity_snapshot,
        reservation_until=(
            _after_days(at, MENTOR_CONSENT_RESERVATION_DAYS)
            if status is OfferStatus.ACCEPTED and offer.kind is OfferKind.MENTORSHIP
            else None
        ),
        response_score=score,
        response_threshold=threshold,
        response_reason=reason,
    )
    offers = list(ledger.offers)
    offers[offer_index] = responded
    introductions = ledger.introductions
    if status is OfferStatus.ACCEPTED:
        participants = tuple(sorted((offer.initiator_id, offer.recipient_id), key=str))
        introductions = tuple(sorted(
            introductions + (SocialIntroduction(
                event_id=EventId(derive_id(
                    "event", "touchline-social-introduction-v1", str(offer.offer_id)
                )),
                offer_id=offer.offer_id,
                opportunity_id=offer.opportunity_id,
                source_event_id=offer.source_event_id,
                participants=participants,
                at=at,
            ),),
            key=lambda item: (item.at, str(item.event_id)),
        ))
    updated = SocialLedger(
        ledger.sessions, ledger.opportunities, ledger.choices,
        tuple(offers), introductions,
    )
    return updated, responded


__all__ = [
    "ContactOpportunity",
    "MENTOR_CONSENT_RESERVATION_DAYS",
    "FRIENDSHIP_PROPOSAL_THRESHOLD",
    "FRIENDSHIP_RESPONSE_THRESHOLD",
    "MIN_SHARED_CONTEXT_MINUTES",
    "MENTOR_PROPOSAL_THRESHOLD",
    "MENTOR_RESPONSE_THRESHOLD",
    "MENTOR_TRUST_THRESHOLD",
    "MentorCapacity",
    "OfferDecision",
    "OfferKind",
    "OfferStatus",
    "OpportunityId",
    "SessionOutcome",
    "SessionParticipant",
    "SharedSession",
    "SocialChoice",
    "SocialChoiceId",
    "SocialChoiceOutcome",
    "SocialDisposition",
    "SocialIntroduction",
    "SocialLedger",
    "SocialOffer",
    "SocialOfferId",
    "SOCIAL_OFFER_VALID_DAYS",
    "expire_offer",
    "propose_autonomous_offer",
    "record_shared_session",
    "respond_to_offer",
]
