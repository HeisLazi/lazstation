"""Fresh-process replay probe for P13c mentorship and contact learning."""

from __future__ import annotations

import json
from datetime import date

from games.touchline.esb.content.proof_roster import PROOF_SQUADS
from games.touchline.esb.ids import EventId
from games.touchline.esb.people.mentorship import (
    DemonstratedBehavior,
    FocusAgreement,
    MentorshipFocus,
    MentorshipLedger,
    MentorTimeBudget,
    activate_mentorship,
    record_mentorship_contact,
    record_mentorship_review,
)
from games.touchline.esb.people.relationships import (
    PersonId,
    RelationshipDimension,
    WorldMoment,
    record_relationship_evidence,
)
from games.touchline.esb.people.social import (
    MentorCapacity,
    OfferKind,
    SessionOutcome,
    SessionParticipant,
    SharedSession,
    SocialDisposition,
    SocialLedger,
    propose_autonomous_offer,
    record_shared_session,
    respond_to_offer,
)
from games.touchline.esb.serialization import dumps
from games.touchline.esb.time import WorldDate


def run_probe() -> dict[str, object]:
    today = WorldDate(date(2026, 10, 6))

    def at(sequence: int) -> WorldMoment:
        return WorldMoment(today, sequence)

    mentor_profile, mentee_profile = PROOF_SQUADS[0].players[:2]
    mentor = PersonId(str(mentor_profile.player_id))
    mentee = PersonId(str(mentee_profile.player_id))
    session = SharedSession(
        EventId("event:mentorship-probe-session"), at(1), SessionOutcome.COMPLETED,
        (
            SessionParticipant(mentor, "group:mentorship-probe", 30),
            SessionParticipant(mentee, "group:mentorship-probe", 30),
        ),
    )
    social = record_shared_session(SocialLedger(), session)
    edge = record_relationship_evidence(
        None, source_person_id=mentor, target_person_id=mentee,
        dimension=RelationshipDimension.TRUST, delta=0.0,
        event_id=EventId("event:mentorship-probe-trust"), at=at(2),
        direct_contact=True, initial_value=0.75,
    )
    capacity = MentorCapacity(mentor, concurrent_slots=1)
    mentor_disposition = SocialDisposition(mentor, mentoring_willingness=0.95)
    mentee_disposition = SocialDisposition(
        mentee, mentoring_interest=0.90, mentoring_receptivity=0.95,
    )
    social, offer_decision = propose_autonomous_offer(
        social,
        opportunity_id=social.opportunities[0].opportunity_id,
        kind=OfferKind.MENTORSHIP,
        initiator=mentor_disposition,
        recipient=mentee_disposition,
        at=at(3),
        relationship=edge,
        mentor_capacity=capacity,
    )
    if offer_decision.offer is None:
        raise AssertionError("deterministic mentorship probe did not produce an offer")
    social, offer = respond_to_offer(
        social,
        offer_id=offer_decision.offer.offer_id,
        recipient=mentee_disposition,
        at=at(4),
        mentor_capacity=capacity,
    )
    agreement = FocusAgreement(
        focus=MentorshipFocus.PASSING,
        mentor_id=mentor,
        mentee_id=mentee,
        mentor_evidence_id=EventId("event:mentorship-probe-mentor-focus"),
        mentee_evidence_id=EventId("event:mentorship-probe-mentee-interest"),
        mentor_competence=0.82,
        mentee_interest=0.88,
        assessed_at=at(5),
    )
    ledger, mentorship = activate_mentorship(
        social,
        MentorshipLedger(),
        offer_id=str(offer.offer_id),
        at=at(6),
        actor_id=mentor,
        focus_agreements=(agreement,),
        mentor_capacity=capacity,
        relationships=(edge,),
    )
    ledger = record_mentorship_contact(
        ledger,
        mentorship_id=mentorship.mentorship_id,
        contact_id=EventId("event:mentorship-probe-contact"),
        at=at(8),
        focus=MentorshipFocus.PASSING,
        duration_minutes=20,
        examples=(DemonstratedBehavior(
            EventId("event:mentorship-probe-demonstration"),
            at(7),
            MentorshipFocus.PASSING,
            (mentor, mentee),
            12,
        ),),
        mentor_clarity=0.80,
        mentee_usefulness=0.60,
        mentor_trust_feedback=0.75,
        mentee_trust_feedback=0.50,
        mentee_profile=mentee_profile,
        time_budget=MentorTimeBudget(mentor, today, 60, 10),
    )
    ledger, review = record_mentorship_review(
        ledger, mentorship_id=mentorship.mentorship_id, at=at(9),
    )
    return {
        "status": mentorship.status.value,
        "contact_count": len(ledger.contacts),
        "learning_value": ledger.focus_learning[0].value,
        "review_id": str(review.review_id),
        "encoded_ledger": json.loads(dumps(ledger)),
    }


def main() -> None:
    print(json.dumps(run_probe(), ensure_ascii=False, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
