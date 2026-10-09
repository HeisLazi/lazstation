"""Fresh-process replay probe for P13 shared-context social choices."""

from __future__ import annotations

import json
from datetime import date

from games.touchline.esb.ids import EventId
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
    day = WorldDate(date(2026, 10, 6))
    mentor = PersonId("player:mentor")
    newcomer = PersonId("player:newcomer")
    session_moment = WorldMoment(day, 1)
    session = SharedSession(
        EventId("event:probe-session"),
        session_moment,
        SessionOutcome.COMPLETED,
        (
            SessionParticipant(mentor, "group:pair-drill", 30),
            SessionParticipant(newcomer, "group:pair-drill", 30),
        ),
    )
    ledger = record_shared_session(SocialLedger(), session)
    opportunity = ledger.opportunities[0]
    edge = record_relationship_evidence(
        None,
        source_person_id=mentor,
        target_person_id=newcomer,
        dimension=RelationshipDimension.TRUST,
        delta=0.0,
        event_id=EventId("event:probe-trust"),
        at=WorldMoment(day, 2),
        direct_contact=True,
        initial_value=0.75,
    )
    mentor_disposition = SocialDisposition(mentor, mentoring_willingness=0.95)
    newcomer_disposition = SocialDisposition(
        newcomer, mentoring_interest=0.9, mentoring_receptivity=0.95
    )
    ledger, decision = propose_autonomous_offer(
        ledger,
        opportunity_id=opportunity.opportunity_id,
        kind=OfferKind.MENTORSHIP,
        initiator=mentor_disposition,
        recipient=newcomer_disposition,
        at=WorldMoment(day, 3),
        relationship=edge,
        mentor_capacity=MentorCapacity(mentor, concurrent_slots=1),
    )
    ledger, accepted = respond_to_offer(
        ledger,
        offer_id=decision.offer.offer_id,
        recipient=newcomer_disposition,
        at=WorldMoment(day, 4),
        mentor_capacity=MentorCapacity(mentor, concurrent_slots=1),
    )
    return {
        "choice_id": str(decision.choice.choice_id),
        "offer_status": accepted.status.value,
        "source_event_id": str(accepted.source_event_id),
        "introduction_count": len(ledger.introductions),
        "ledger": json.loads(dumps(ledger)),
    }


def main() -> None:
    print(json.dumps(run_probe(), ensure_ascii=False, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
