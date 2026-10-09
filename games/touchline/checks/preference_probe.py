"""Deterministic private-preference and dated-opportunity probe."""

from __future__ import annotations

from datetime import date

from games.touchline.esb.ids import EventId
from games.touchline.esb.people.preferences import (
    OpportunityId,
    PersonalPreferenceHistory,
    PreferenceDomain,
    PreferenceFeature,
    PreferenceOpportunity,
    PreferenceStance,
    assess_opportunity_preferences,
    new_self_reported_preference,
    record_self_reported_preference,
)
from games.touchline.esb.people.relationships import PersonId, WorldMoment
from games.touchline.esb.serialization import dumps
from games.touchline.esb.time import WorldDate


def run_probe() -> dict[str, str | int]:
    day = WorldDate(date(2026, 10, 7))
    person_id = PersonId("player:preference-probe-person")
    history = PersonalPreferenceHistory(person_id)
    known_features = (
        PreferenceFeature(PreferenceDomain.PLACE, "place:windhoek"),
        PreferenceFeature(PreferenceDomain.COMPETITION, "competition:namibia-premier-league"),
        PreferenceFeature(PreferenceDomain.LIFESTYLE, "lifestyle:coastal-climate"),
    )
    statements = (
        new_self_reported_preference(
            person_id=person_id,
            source_event_id=EventId("event:preference-probe-place"),
            at=WorldMoment(day, 1),
            feature=known_features[0],
            stance=PreferenceStance.FAVOUR,
            salience=0.8,
            certainty=0.9,
        ),
        new_self_reported_preference(
            person_id=person_id,
            source_event_id=EventId("event:preference-probe-league"),
            at=WorldMoment(day, 2),
            feature=known_features[1],
            stance=PreferenceStance.OPEN,
            salience=0.4,
            certainty=0.75,
        ),
        new_self_reported_preference(
            person_id=person_id,
            source_event_id=EventId("event:preference-probe-climate"),
            at=WorldMoment(day, 3),
            feature=known_features[2],
            stance=PreferenceStance.AVOID,
            salience=0.6,
            certainty=0.85,
        ),
    )
    for item in statements:
        history = record_self_reported_preference(history, item)

    opportunity = PreferenceOpportunity(
        OpportunityId("opportunity:preference-probe"),
        WorldMoment(day, 4),
        known_features + (
            PreferenceFeature(PreferenceDomain.PLACE, "place:namibia"),
            PreferenceFeature(PreferenceDomain.CLUB_POLICY, "policy:academy-minutes"),
        ),
    )
    assessment = assess_opportunity_preferences(
        history, person_id=person_id, opportunity=opportunity
    )
    return {
        "history": dumps(history),
        "assessment": dumps(assessment),
        "known_features": sum(item.stance is not None for item in assessment.readings),
        "unknown_features": sum(item.stance is None for item in assessment.readings),
        "aggregate_score": "none",
    }


if __name__ == "__main__":
    import json

    print(json.dumps(run_probe(), sort_keys=True, separators=(",", ":")))
