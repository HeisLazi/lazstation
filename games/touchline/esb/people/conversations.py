"""Private, voluntary support conversations built on P13 personal history.

The records contain topic codes and requested support modes, never transcript
text. Accepting a practical-help offer records the agreed mode; it does not
claim that a later task was carried out. Personal experiences remain pending
for the existing, explicit P13a appraisal step.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta
from enum import Enum
from typing import NewType

from games.touchline.esb.ids import EventId, derive_id, validate_id
from games.touchline.esb.people.relationships import (
    AwarenessBasis,
    ExperienceId,
    PersonalHistory,
    PersonId,
    WorldMoment,
    new_personal_experience,
    record_personal_experience,
)
from games.touchline.esb.time import WorldDate

ConversationId = NewType("ConversationId", str)
SUPPORT_REQUEST_VALID_DAYS = 7


class ConversationTopic(str, Enum):
    PERSONAL = "personal"
    ROLE_CHANGE = "role_change"
    PLACE_SETTLEMENT = "place_settlement"
    POLICY_CHANGE = "policy_change"
    HEALTH_OR_RECOVERY = "health_or_recovery"


class SupportMode(str, Enum):
    LISTEN = "listen"
    ADVICE = "advice"
    PRACTICAL_HELP_OFFER = "practical_help_offer"


class ConversationStatus(str, Enum):
    OPEN = "open"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    EXPIRED = "expired"


class ConversationDecision(str, Enum):
    ACCEPT = "accept"
    DECLINE = "decline"


def _after_days(moment: WorldMoment, days: int) -> WorldMoment:
    return WorldMoment(WorldDate(moment.on.day + timedelta(days=days)), 0)


def _request_event_id(conversation_id: ConversationId) -> EventId:
    return EventId(derive_id(
        "event", "p13-support-request-v1", str(conversation_id)
    ))


def _resolution_event_id(
    conversation_id: ConversationId, status: ConversationStatus
) -> EventId:
    return EventId(derive_id(
        "event", "p13-support-resolution-v1", str(conversation_id), status.value
    ))


@dataclass(frozen=True)
class SupportConversation:
    """One private request and its single recipient decision."""

    conversation_id: ConversationId
    request_event_id: EventId
    source_event_id: EventId
    source_experience_id: ExperienceId
    source_at: WorldMoment
    source_awareness_at: WorldMoment
    requester_id: PersonId
    recipient_id: PersonId
    topic: ConversationTopic
    requested_mode: SupportMode
    opened_at: WorldMoment
    expires_at: WorldMoment
    status: ConversationStatus = ConversationStatus.OPEN
    resolution_event_id: EventId | None = None
    resolved_at: WorldMoment | None = None

    def __post_init__(self) -> None:
        validate_id(self.conversation_id, kind="support conversation ID")
        validate_id(self.request_event_id, kind="support request event ID")
        validate_id(self.source_event_id, kind="support source event ID")
        validate_id(self.source_experience_id, kind="support source experience ID")
        validate_id(self.requester_id, kind="support requester ID")
        validate_id(self.recipient_id, kind="support recipient ID")
        if self.requester_id == self.recipient_id:
            raise ValueError("a support conversation requires two different people")
        if (
            not isinstance(self.source_at, WorldMoment)
            or not isinstance(self.source_awareness_at, WorldMoment)
            or not isinstance(self.opened_at, WorldMoment)
        ):
            raise TypeError("support conversation source and request require world moments")
        if not self.source_at <= self.source_awareness_at < self.opened_at:
            raise ValueError("a support request must follow the requester's source awareness")
        if not isinstance(self.topic, ConversationTopic) or not isinstance(self.requested_mode, SupportMode):
            raise TypeError("support conversation topic and mode must be explicit")
        if self.expires_at != _after_days(self.opened_at, SUPPORT_REQUEST_VALID_DAYS):
            raise ValueError("support conversation must use the documented seven-day window")
        if not isinstance(self.status, ConversationStatus):
            raise TypeError("support conversation status must be explicit")
        expected_id = ConversationId(derive_id(
            "conversation", "p13-support-conversation-v1",
            str(self.source_event_id), str(self.source_experience_id),
            str(self.requester_id), str(self.recipient_id),
        ))
        if self.conversation_id != expected_id:
            raise ValueError("support conversation ID does not match its source and participants")
        if self.request_event_id != _request_event_id(self.conversation_id):
            raise ValueError("support request event ID does not match its conversation")

        unresolved = self.status is ConversationStatus.OPEN
        if unresolved != (self.resolution_event_id is None and self.resolved_at is None):
            raise ValueError("resolved support conversations require one complete resolution")
        if unresolved:
            return
        validate_id(self.resolution_event_id, kind="support resolution event ID")  # type: ignore[arg-type]
        if not isinstance(self.resolved_at, WorldMoment):
            raise TypeError("support resolution requires its world moment")
        if self.resolution_event_id != _resolution_event_id(self.conversation_id, self.status):
            raise ValueError("support resolution event ID does not match its outcome")
        if self.status is ConversationStatus.EXPIRED:
            if self.resolved_at < self.expires_at:
                raise ValueError("support request cannot expire before its deadline")
        elif not self.opened_at < self.resolved_at < self.expires_at:
            raise ValueError("support response must occur inside its valid window")


@dataclass(frozen=True)
class ConversationLedger:
    """Chronological private-conversation records for a synthetic world."""

    conversations: tuple[SupportConversation, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.conversations, tuple) or any(
            not isinstance(item, SupportConversation) for item in self.conversations
        ):
            raise TypeError("support conversations must be an immutable tuple")
        ids = [item.conversation_id for item in self.conversations]
        request_events = [item.request_event_id for item in self.conversations]
        resolution_events = [
            item.resolution_event_id for item in self.conversations
            if item.resolution_event_id is not None
        ]
        if len(ids) != len(set(ids)):
            raise ValueError("support conversation IDs cannot repeat")
        event_ids = request_events + resolution_events
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("support conversation event IDs cannot repeat")
        source_events = [item.source_event_id for item in self.conversations]
        if set(event_ids) & set(source_events):
            raise ValueError("support source and conversation activity event IDs must be distinct")
        keys = tuple((item.opened_at, str(item.conversation_id)) for item in self.conversations)
        if tuple(sorted(keys)) != keys:
            raise ValueError("support conversations must retain request chronology")
        moment_events: dict[WorldMoment, EventId] = {}
        event_moments: dict[EventId, WorldMoment] = {}
        for item in self.conversations:
            events = [
                (item.source_event_id, item.source_at),
                (item.request_event_id, item.opened_at),
            ]
            if item.resolution_event_id is not None and item.resolved_at is not None:
                events.append((item.resolution_event_id, item.resolved_at))
            for event_id, at in events:
                previous_at = event_moments.get(event_id)
                if previous_at is not None and previous_at != at:
                    raise ValueError("a support event ID cannot occupy multiple world moments")
                previous_event = moment_events.get(at)
                if previous_event is not None and previous_event != event_id:
                    raise ValueError("support events need distinct world moments")
                event_moments[event_id] = at
                moment_events[at] = event_id


@dataclass(frozen=True)
class SupportResolution:
    """Atomic result of a recipient decision and its personal-history effects."""

    conversation_id: ConversationId
    ledger: ConversationLedger
    requester_history: PersonalHistory
    recipient_history: PersonalHistory

    def __post_init__(self) -> None:
        validate_id(self.conversation_id, kind="support resolution conversation ID")
        if not isinstance(self.ledger, ConversationLedger):
            raise TypeError("support resolution requires a conversation ledger")
        if not isinstance(self.requester_history, PersonalHistory) or not isinstance(
            self.recipient_history, PersonalHistory
        ):
            raise TypeError("support resolution requires both personal histories")
        conversation = next((item for item in self.ledger.conversations
                             if item.conversation_id == self.conversation_id), None)
        if conversation is None:
            raise ValueError("support resolution conversation must be in its ledger")
        if (
            self.requester_history.person_id != conversation.requester_id
            or self.recipient_history.person_id != conversation.recipient_id
        ):
            raise ValueError("support resolution histories must match its participants")
        _verify_source_history(conversation, self.requester_history)
        if conversation.status is ConversationStatus.OPEN:
            raise ValueError("support resolution must contain a completed recipient decision")
        if conversation.status is ConversationStatus.ACCEPTED:
            if conversation.resolution_event_id is None or conversation.resolved_at is None:
                raise ValueError("accepted support resolution is missing its response evidence")
            for person_id, person_history in (
                (conversation.requester_id, self.requester_history),
                (conversation.recipient_id, self.recipient_history),
            ):
                expected = new_personal_experience(
                    person_id,
                    conversation.resolution_event_id,
                    conversation.resolved_at,
                    AwarenessBasis.DIRECT,
                    conversation.resolved_at,
                )
                existing = next((item for item in person_history.experiences
                                 if item.experience_id == expected.experience_id), None)
                if existing is None or not _same_experience_lineage(existing, expected):
                    raise ValueError("accepted support resolution must retain both participant experiences")
        else:
            if conversation.resolution_event_id is None:
                raise ValueError("resolved support conversation is missing its response evidence")
            if any(
                item.cause_event_id == conversation.resolution_event_id
                for person_history in (self.requester_history, self.recipient_history)
                for item in person_history.experiences
            ):
                raise ValueError("declined or expired support cannot create contact experiences")


def new_support_conversation(
    *,
    source_event_id: EventId,
    requester_history: PersonalHistory,
    requester_id: PersonId,
    recipient_id: PersonId,
    topic: ConversationTopic,
    requested_mode: SupportMode,
    opened_at: WorldMoment,
) -> SupportConversation:
    """Create an explicit request without assuming it is accepted."""

    validate_id(source_event_id, kind="support source event ID")
    validate_id(requester_id, kind="support requester ID")
    validate_id(recipient_id, kind="support recipient ID")
    if not isinstance(requester_history, PersonalHistory):
        raise TypeError("support request requires the requester's personal history")
    if requester_history.person_id != requester_id:
        raise ValueError("support source history belongs to another requester")
    if not isinstance(opened_at, WorldMoment):
        raise TypeError("support request requires a world moment")
    source_experience = next((item for item in requester_history.experiences
                              if item.cause_event_id == source_event_id), None)
    if source_experience is None:
        raise ValueError("support source event must exist in the requester's personal history")
    if not source_experience.awareness_at < opened_at:
        raise ValueError("requester must be aware of the source before requesting support")
    conversation_id = ConversationId(derive_id(
        "conversation", "p13-support-conversation-v1",
        str(source_event_id), str(source_experience.experience_id),
        str(requester_id), str(recipient_id),
    ))
    return SupportConversation(
        conversation_id=conversation_id,
        request_event_id=_request_event_id(conversation_id),
        source_event_id=source_event_id,
        source_experience_id=source_experience.experience_id,
        source_at=source_experience.occurred_at,
        source_awareness_at=source_experience.awareness_at,
        requester_id=requester_id,
        recipient_id=recipient_id,
        topic=topic,
        requested_mode=requested_mode,
        opened_at=opened_at,
        expires_at=_after_days(opened_at, SUPPORT_REQUEST_VALID_DAYS),
    )


def record_support_conversation(
    ledger: ConversationLedger,
    conversation: SupportConversation,
    *,
    requester_history: PersonalHistory,
) -> ConversationLedger:
    """Append a request once; conflicting reuse of its stable key is rejected."""

    if not isinstance(ledger, ConversationLedger) or not isinstance(conversation, SupportConversation):
        raise TypeError("recording support requires a ledger and conversation")
    _verify_source_history(conversation, requester_history)
    if conversation.status is not ConversationStatus.OPEN:
        raise ValueError("a new support request must enter the ledger as open")
    prior = next((item for item in ledger.conversations
                  if item.conversation_id == conversation.conversation_id), None)
    if prior is not None:
        if prior == conversation:
            return ledger
        raise ValueError("support conversation ID was reused with conflicting content")
    if ledger.conversations and conversation.opened_at <= ledger.conversations[-1].opened_at:
        raise ValueError("support requests must be recorded in world chronology")
    return replace(ledger, conversations=ledger.conversations + (conversation,))


def _verify_source_history(
    conversation: SupportConversation, requester_history: PersonalHistory
) -> None:
    if not isinstance(requester_history, PersonalHistory):
        raise TypeError("support conversation requires the requester's personal history")
    if requester_history.person_id != conversation.requester_id:
        raise ValueError("support source history belongs to another requester")
    source = next((item for item in requester_history.experiences
                   if item.cause_event_id == conversation.source_event_id), None)
    if source is None:
        raise ValueError("support source event is absent from the requester's personal history")
    if (
        source.experience_id != conversation.source_experience_id
        or source.occurred_at != conversation.source_at
        or source.awareness_at != conversation.source_awareness_at
    ):
        raise ValueError("support source experience does not match its personal history lineage")


def respond_to_support_request(
    ledger: ConversationLedger,
    conversation_id: ConversationId,
    *,
    recipient_id: PersonId,
    decision: ConversationDecision,
    at: WorldMoment,
    requester_history: PersonalHistory,
    recipient_history: PersonalHistory,
) -> SupportResolution:
    """Record the choice and any pending experiences as one immutable result."""

    if not isinstance(ledger, ConversationLedger):
        raise TypeError("support response requires a conversation ledger")
    if not isinstance(requester_history, PersonalHistory) or not isinstance(
        recipient_history, PersonalHistory
    ):
        raise TypeError("support response requires both personal histories")
    validate_id(conversation_id, kind="support conversation ID")
    validate_id(recipient_id, kind="support responder ID")
    if not isinstance(decision, ConversationDecision) or not isinstance(at, WorldMoment):
        raise TypeError("support response requires an explicit decision and world moment")
    index = next((i for i, item in enumerate(ledger.conversations)
                  if item.conversation_id == conversation_id), None)
    if index is None:
        raise ValueError("support request must be recorded before response")
    conversation = ledger.conversations[index]
    if recipient_id != conversation.recipient_id:
        raise ValueError("only the named recipient can respond to a support request")
    if requester_history.person_id != conversation.requester_id:
        raise ValueError("requester personal history belongs to another person")
    if recipient_history.person_id != conversation.recipient_id:
        raise ValueError("recipient personal history belongs to another person")
    _verify_source_history(conversation, requester_history)
    if decision is ConversationDecision.ACCEPT:
        status = ConversationStatus.ACCEPTED
    else:
        status = ConversationStatus.DECLINED
    if conversation.status is not ConversationStatus.OPEN:
        if conversation.status is status and conversation.resolved_at == at:
            updated_ledger = ledger
        else:
            raise ValueError("support request was already resolved with different inputs")
    else:
        if at >= conversation.expires_at:
            raise ValueError("support request has expired; expire it before responding")
        if at <= conversation.opened_at:
            raise ValueError("support response must follow its request")
        resolved = replace(
            conversation,
            status=status,
            resolution_event_id=_resolution_event_id(conversation.conversation_id, status),
            resolved_at=at,
        )
        updated = ledger.conversations[:index] + (resolved,) + ledger.conversations[index + 1:]
        updated_ledger = replace(ledger, conversations=updated)
    resolved_conversation = next(
        item for item in updated_ledger.conversations
        if item.conversation_id == conversation_id
    )
    updated_requester, updated_recipient = _record_support_experiences(
        resolved_conversation, requester_history, recipient_history
    )
    return SupportResolution(
        conversation_id,
        updated_ledger,
        updated_requester,
        updated_recipient,
    )


def expire_support_request(
    ledger: ConversationLedger, conversation_id: ConversationId, *, at: WorldMoment
) -> ConversationLedger:
    """Close an unanswered request at a supplied moment on/after its deadline."""

    if not isinstance(ledger, ConversationLedger):
        raise TypeError("support expiry requires a conversation ledger")
    validate_id(conversation_id, kind="support conversation ID")
    if not isinstance(at, WorldMoment):
        raise TypeError("support expiry requires its processing world moment")
    index = next((i for i, item in enumerate(ledger.conversations)
                  if item.conversation_id == conversation_id), None)
    if index is None:
        raise ValueError("support request must be recorded before expiry")
    conversation = ledger.conversations[index]
    if conversation.status is ConversationStatus.EXPIRED:
        if conversation.resolved_at == at:
            return ledger
        raise ValueError("support request was already expired at a different moment")
    if conversation.status is not ConversationStatus.OPEN:
        raise ValueError("a resolved support request cannot later expire")
    if at < conversation.expires_at:
        raise ValueError("support request cannot expire before its deadline")
    expired = replace(
        conversation,
        status=ConversationStatus.EXPIRED,
        resolution_event_id=_resolution_event_id(
            conversation.conversation_id, ConversationStatus.EXPIRED
        ),
        resolved_at=at,
    )
    updated = ledger.conversations[:index] + (expired,) + ledger.conversations[index + 1:]
    return replace(ledger, conversations=updated)


def private_conversation_for(
    ledger: ConversationLedger,
    conversation_id: ConversationId,
    viewer_id: PersonId,
) -> SupportConversation | None:
    """Return a conversation only to one of its two participants."""

    if not isinstance(ledger, ConversationLedger):
        raise TypeError("private conversation access requires a ledger")
    validate_id(conversation_id, kind="support conversation ID")
    validate_id(viewer_id, kind="conversation viewer ID")
    conversation = next((item for item in ledger.conversations
                         if item.conversation_id == conversation_id), None)
    if conversation is None or viewer_id not in (
        conversation.requester_id, conversation.recipient_id
    ):
        return None
    return conversation


def private_conversations_for(
    ledger: ConversationLedger, viewer_id: PersonId
) -> tuple[SupportConversation, ...]:
    """List only private requests where the viewer is a participant."""

    if not isinstance(ledger, ConversationLedger):
        raise TypeError("private conversation access requires a ledger")
    validate_id(viewer_id, kind="conversation viewer ID")
    return tuple(
        item for item in ledger.conversations
        if viewer_id in (item.requester_id, item.recipient_id)
    )


def _same_experience_lineage(existing, expected) -> bool:
    return (
        existing.experience_id == expected.experience_id
        and existing.person_id == expected.person_id
        and existing.cause_event_id == expected.cause_event_id
        and existing.occurred_at == expected.occurred_at
        and existing.awareness == expected.awareness
        and existing.awareness_at == expected.awareness_at
    )


def _record_support_experiences(
    conversation: SupportConversation,
    requester_history: PersonalHistory,
    recipient_history: PersonalHistory,
) -> tuple[PersonalHistory, PersonalHistory]:
    """Record, or preserve, direct experiences for an accepted support contact.

    No appraisal, relationship change or learning is applied here. Replaying
    the accepted contact returns the same histories through P13a's stable
    person/cause experience IDs, even after later P13a appraisal.
    """

    if not isinstance(conversation, SupportConversation):
        raise TypeError("support experience recording requires a conversation")
    if not isinstance(requester_history, PersonalHistory) or not isinstance(
        recipient_history, PersonalHistory
    ):
        raise TypeError("support experience recording requires both personal histories")
    if requester_history.person_id != conversation.requester_id:
        raise ValueError("requester personal history belongs to another person")
    if recipient_history.person_id != conversation.recipient_id:
        raise ValueError("recipient personal history belongs to another person")
    if conversation.status is not ConversationStatus.ACCEPTED:
        return requester_history, recipient_history
    if conversation.resolution_event_id is None or conversation.resolved_at is None:
        raise ValueError("accepted support conversation is missing its resolution evidence")
    resolution_event_id = conversation.resolution_event_id
    resolved_at = conversation.resolved_at

    def ensure_experience(history: PersonalHistory, person_id: PersonId) -> PersonalHistory:
        expected = new_personal_experience(
            person_id,
            resolution_event_id,
            resolved_at,
            AwarenessBasis.DIRECT,
            resolved_at,
        )
        existing = next((item for item in history.experiences
                         if item.experience_id == expected.experience_id), None)
        if existing is not None:
            if _same_experience_lineage(existing, expected):
                return history
            raise ValueError("support experience ID conflicts with its original cause or awareness")
        return record_personal_experience(history, expected)

    return (
        ensure_experience(requester_history, conversation.requester_id),
        ensure_experience(recipient_history, conversation.recipient_id),
    )
