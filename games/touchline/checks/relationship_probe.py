"""Fresh-process serialization probe for the first P13 people slice."""

from __future__ import annotations

import json
from datetime import date

from games.touchline.esb.ids import EventId
from games.touchline.esb.people.relationships import (
    AwarenessBasis,
    PersonalAdjustment,
    PersonalAppraisal,
    PersonalDimension,
    PersonalHistory,
    PersonalState,
    PersonalStateValue,
    PersonId,
    RelationshipDimension,
    RelationshipKnowledge,
    WorldMoment,
    appraise_personal_experience,
    new_personal_experience,
    record_personal_experience,
    record_relationship_evidence,
    record_relationship_knowledge,
)
from games.touchline.esb.serialization import dumps
from games.touchline.esb.time import WorldDate


def run_probe() -> dict[str, object]:
    day = WorldDate(date(2026, 10, 5))
    first_moment = WorldMoment(day, 1)
    source = PersonId("player:captain")
    target = PersonId("player:arrival")
    relationship_event = EventId("event:training-contact-1")
    edge = record_relationship_evidence(
        None,
        source_person_id=source,
        target_person_id=target,
        dimension=RelationshipDimension.TRUST,
        delta=0.02,
        event_id=relationship_event,
        at=first_moment,
        direct_contact=True,
        initial_value=0.50,
    )
    disclosure = RelationshipKnowledge(
        disclosure_id="knowledge:coach-view-1",
        observer_id="person:coach",
        dimension=RelationshipDimension.TRUST,
        perceived_value=0.54,
        confidence=0.60,
        at=WorldMoment(day, 2),
        supporting_event_ids=(relationship_event,),
    )
    edge = record_relationship_knowledge(edge, disclosure)

    state = PersonalState(
        target,
        tuple(PersonalStateValue(dimension, 0.50)
              for dimension in sorted(PersonalDimension, key=lambda item: item.value)),
    )
    history = PersonalHistory(target, state)
    experience = new_personal_experience(
        target,
        EventId("event:role-discussion-1"),
        WorldMoment(day, 3),
        AwarenessBasis.REPORTED,
        WorldMoment(day, 4),
    )
    history = record_personal_experience(history, experience)
    history = appraise_personal_experience(
        history,
        experience.experience_id,
        PersonalAppraisal(
            assessed_at=WorldMoment(day, 5),
            confidence=0.75,
            salience=0.80,
            adjustments=(PersonalAdjustment(PersonalDimension.BELONGING, 0.8, 0.7),),
        ),
    )
    return {
        "relationship": json.loads(dumps(edge)),
        "personal_history": json.loads(dumps(history)),
    }


def main() -> None:
    print(json.dumps(run_probe(), ensure_ascii=False, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
