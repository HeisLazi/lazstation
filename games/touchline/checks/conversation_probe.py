"""Deterministic support-conversation and pending-experience probe."""

from __future__ import annotations

from datetime import date, timedelta

from games.touchline.esb.ids import EventId
from games.touchline.esb.people.conversations import (
    ConversationDecision,
    ConversationLedger,
    ConversationTopic,
    SupportMode,
    new_support_conversation,
    record_support_conversation,
    respond_to_support_request,
)
from games.touchline.esb.people.relationships import (
    AwarenessBasis,
    PersonalAppraisal,
    PersonalDimension,
    PersonalHistory,
    PersonalState,
    PersonalStateValue,
    PersonId,
    WorldMoment,
    appraise_personal_experience,
    new_personal_experience,
    record_personal_experience,
)
from games.touchline.esb.serialization import dumps
from games.touchline.esb.time import WorldDate


def run_probe() -> dict[str, str | int]:
    base = WorldDate(date(2026, 10, 7))
    source_at = WorldMoment(base, 1)
    opened_at = WorldMoment(base, 2)
    responded_at = WorldMoment(base, 3)
    requester = PersonId("player:conversation-probe-requester")
    recipient = PersonId("player:conversation-probe-recipient")
    source_event_id = EventId("event:conversation-probe-source")

    def empty_history(person_id: PersonId) -> PersonalHistory:
        state = PersonalState(
            person_id,
            tuple(PersonalStateValue(dimension, 0.5)
                  for dimension in sorted(PersonalDimension, key=lambda item: item.value)),
        )
        return PersonalHistory(person_id, state)

    requester_history = empty_history(requester)
    source = new_personal_experience(
        requester,
        source_event_id,
        WorldMoment(WorldDate(base.day - timedelta(days=1)), 1),
        AwarenessBasis.DIRECT,
        source_at,
    )
    requester_history = record_personal_experience(requester_history, source)
    requester_history = appraise_personal_experience(
        requester_history,
        source.experience_id,
        # Neutral appraisal still records that this known source was processed.
        PersonalAppraisal(source_at, 1.0, 1.0, ()),
    )
    request = new_support_conversation(
        source_event_id=source_event_id,
        requester_history=requester_history,
        requester_id=requester,
        recipient_id=recipient,
        topic=ConversationTopic.PLACE_SETTLEMENT,
        requested_mode=SupportMode.LISTEN,
        opened_at=opened_at,
    )
    ledger = record_support_conversation(
        ConversationLedger(), request, requester_history=requester_history
    )
    resolution = respond_to_support_request(
        ledger,
        request.conversation_id,
        recipient_id=recipient,
        decision=ConversationDecision.ACCEPT,
        at=responded_at,
        requester_history=requester_history,
        recipient_history=empty_history(recipient),
    )
    return {
        "ledger": dumps(resolution.ledger),
        "requester_history": dumps(resolution.requester_history),
        "recipient_history": dumps(resolution.recipient_history),
        "pending_experiences": sum(
            not item.processed
            for person_history in (resolution.requester_history, resolution.recipient_history)
            for item in person_history.experiences
        ),
        "deadline_day": str(base.day + timedelta(days=7)),
    }


if __name__ == "__main__":
    import json

    print(json.dumps(run_probe(), sort_keys=True, separators=(",", ":")))
