from __future__ import annotations

import os
import subprocess
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

from games.touchline.esb.ids import EventId
from games.touchline.esb.people.conversations import (
    ConversationDecision,
    ConversationLedger,
    ConversationStatus,
    ConversationTopic,
    SupportMode,
    expire_support_request,
    new_support_conversation,
    private_conversation_for,
    private_conversations_for,
    record_support_conversation,
    respond_to_support_request,
)
from games.touchline.esb.people.relationships import (
    AwarenessBasis,
    PersonalAdjustment,
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
from games.touchline.esb.serialization import dumps, loads
from games.touchline.esb.time import WorldDate

ROOT = Path(__file__).resolve().parents[3]
START = WorldDate(date(2026, 10, 7))
REQUESTER = PersonId("player:requester")
RECIPIENT = PersonId("player:recipient")
OUTSIDER = PersonId("player:outsider")


def moment(sequence: int, days: int = 0) -> WorldMoment:
    return WorldMoment(WorldDate(START.day + timedelta(days=days)), sequence)


def history(person_id: PersonId) -> PersonalHistory:
    state = PersonalState(
        person_id,
        tuple(PersonalStateValue(dimension, 0.5)
              for dimension in sorted(PersonalDimension, key=lambda item: item.value)),
    )
    return PersonalHistory(person_id, state)


def source_history(
    source_event_id: EventId,
    *,
    occurred_at: WorldMoment | None = None,
    awareness_at: WorldMoment | None = None,
    awareness: AwarenessBasis = AwarenessBasis.REPORTED,
) -> PersonalHistory:
    result = history(REQUESTER)
    occurred_at = occurred_at or moment(1, days=-1)
    awareness_at = awareness_at or moment(1)
    source = new_personal_experience(
        REQUESTER,
        source_event_id,
        occurred_at,
        awareness,
        awareness_at,
    )
    result = record_personal_experience(result, source)
    return appraise_personal_experience(
        result,
        source.experience_id,
        PersonalAppraisal(awareness_at, 0.8, 0.7, ()),
    )


def make_request(
    *, mode: SupportMode = SupportMode.LISTEN, suffix: str = "main", opened: WorldMoment | None = None
):
    if opened is None:
        opened = moment(2)
    source_event_id = EventId(f"event:source-{suffix}")
    return new_support_conversation(
        source_event_id=source_event_id,
        requester_history=source_history(source_event_id),
        requester_id=REQUESTER,
        recipient_id=RECIPIENT,
        topic=ConversationTopic.PERSONAL,
        requested_mode=mode,
        opened_at=opened,
    )


def open_ledger(request) -> ConversationLedger:
    return record_support_conversation(
        ConversationLedger(), request,
        requester_history=source_history(request.source_event_id),
    )


def response_histories(request) -> tuple[PersonalHistory, PersonalHistory]:
    return source_history(request.source_event_id), history(RECIPIENT)


class ConversationTests(unittest.TestCase):
    def test_request_ids_are_stable_and_records_round_trip(self) -> None:
        request = make_request(mode=SupportMode.ADVICE)
        ledger = open_ledger(request)
        self.assertIs(record_support_conversation(
            ledger,
            request,
            requester_history=source_history(request.source_event_id),
        ), ledger)
        self.assertEqual(request.source_event_id, EventId("event:source-main"))
        self.assertEqual(request.requested_mode, SupportMode.ADVICE)
        self.assertEqual(request.expires_at, moment(0, days=7))
        self.assertEqual(loads(dumps(ledger), ConversationLedger), ledger)

        changed = make_request(mode=SupportMode.PRACTICAL_HELP_OFFER)
        with self.assertRaisesRegex(ValueError, "conflicting content"):
            record_support_conversation(
                ledger,
                changed,
                requester_history=source_history(changed.source_event_id),
            )

    def test_source_must_precede_request_and_people_must_be_distinct(self) -> None:
        with self.assertRaisesRegex(ValueError, "must exist"):
            new_support_conversation(
                source_event_id=EventId("event:future"),
                requester_history=history(REQUESTER),
                requester_id=REQUESTER,
                recipient_id=RECIPIENT,
                topic=ConversationTopic.ROLE_CHANGE,
                requested_mode=SupportMode.LISTEN,
                opened_at=moment(2),
            )
        source_event_id = EventId("event:awareness-boundary")
        with self.assertRaisesRegex(ValueError, "aware of the source"):
            new_support_conversation(
                source_event_id=source_event_id,
                requester_history=source_history(source_event_id),
                requester_id=REQUESTER,
                recipient_id=RECIPIENT,
                topic=ConversationTopic.ROLE_CHANGE,
                requested_mode=SupportMode.LISTEN,
                opened_at=moment(1),
            )
        source_event_id = EventId("event:self")
        with self.assertRaisesRegex(ValueError, "two different people"):
            new_support_conversation(
                source_event_id=source_event_id,
                requester_history=source_history(source_event_id),
                requester_id=REQUESTER,
                recipient_id=REQUESTER,
                topic=ConversationTopic.PERSONAL,
                requested_mode=SupportMode.LISTEN,
                opened_at=moment(2),
            )

    def test_source_lineage_is_checked_again_when_recording_request(self) -> None:
        request = make_request()
        changed_source = history(REQUESTER)
        altered = new_personal_experience(
            REQUESTER,
            request.source_event_id,
            request.source_at,
            AwarenessBasis.DIRECT,
            request.source_at,
        )
        changed_source = record_personal_experience(changed_source, altered)
        changed_source = appraise_personal_experience(
            changed_source,
            altered.experience_id,
            PersonalAppraisal(request.source_at, 0.8, 0.7, ()),
        )
        with self.assertRaisesRegex(ValueError, "lineage"):
            record_support_conversation(
                ConversationLedger(), request, requester_history=changed_source
            )

    def test_only_named_recipient_can_respond(self) -> None:
        request = make_request()
        ledger = open_ledger(request)
        with self.assertRaisesRegex(ValueError, "named recipient"):
            respond_to_support_request(
                ledger,
                request.conversation_id,
                recipient_id=OUTSIDER,
                decision=ConversationDecision.ACCEPT,
                at=moment(3),
                requester_history=source_history(request.source_event_id),
                recipient_history=history(RECIPIENT),
            )
        self.assertEqual(ledger.conversations[0].status, ConversationStatus.OPEN)

    def test_each_support_mode_is_an_explicit_recipient_choice(self) -> None:
        for index, mode in enumerate(SupportMode, start=1):
            request = make_request(
                mode=mode,
                suffix=f"mode-{index}",
                opened=moment(index * 3),
            )
            ledger = open_ledger(request)
            resolved = respond_to_support_request(
                ledger,
                request.conversation_id,
                recipient_id=RECIPIENT,
                decision=ConversationDecision.ACCEPT,
                at=moment(index * 3 + 1),
                requester_history=source_history(request.source_event_id),
                recipient_history=history(RECIPIENT),
            )
            conversation = resolved.ledger.conversations[0]
            self.assertEqual(conversation.status, ConversationStatus.ACCEPTED)
            self.assertEqual(conversation.requested_mode, mode)
            self.assertIs(respond_to_support_request(
                resolved.ledger,
                request.conversation_id,
                recipient_id=RECIPIENT,
                decision=ConversationDecision.ACCEPT,
                at=moment(index * 3 + 1),
                requester_history=resolved.requester_history,
                recipient_history=resolved.recipient_history,
            ).ledger, resolved.ledger)
            with self.assertRaisesRegex(ValueError, "already resolved"):
                respond_to_support_request(
                    resolved.ledger,
                    request.conversation_id,
                    recipient_id=RECIPIENT,
                    decision=ConversationDecision.ACCEPT,
                    at=moment(index * 3 + 2),
                    requester_history=resolved.requester_history,
                    recipient_history=resolved.recipient_history,
                )

    def test_accepted_contact_records_two_pending_experiences_once(self) -> None:
        request = make_request(mode=SupportMode.PRACTICAL_HELP_OFFER)
        ledger = open_ledger(request)
        requester_before, recipient_before = response_histories(request)
        accepted = respond_to_support_request(
            ledger,
            request.conversation_id,
            recipient_id=RECIPIENT,
            decision=ConversationDecision.ACCEPT,
            at=moment(3),
            requester_history=requester_before,
            recipient_history=recipient_before,
        )
        conversation = accepted.ledger.conversations[0]
        requester_after = accepted.requester_history
        recipient_after = accepted.recipient_history
        self.assertEqual(requester_after.state, requester_before.state)
        self.assertEqual(recipient_after.state, recipient_before.state)
        self.assertEqual(len(requester_after.experiences), 2)
        self.assertEqual(len(recipient_after.experiences), 1)
        requester_contact = requester_after.experiences[-1]
        recipient_contact = recipient_after.experiences[0]
        for record in (requester_contact, recipient_contact):
            self.assertEqual(record.cause_event_id, conversation.resolution_event_id)
            self.assertEqual(record.occurred_at, moment(3))
            self.assertEqual(record.awareness_at, moment(3))
            self.assertEqual(record.awareness, AwarenessBasis.DIRECT)
            self.assertFalse(record.processed)
        self.assertIsNone(requester_contact.appraisal)

        replay = respond_to_support_request(
            accepted.ledger,
            request.conversation_id,
            recipient_id=RECIPIENT,
            decision=ConversationDecision.ACCEPT,
            at=moment(3),
            requester_history=requester_after,
            recipient_history=recipient_after,
        )
        self.assertEqual(replay, accepted)
        self.assertIs(replay.requester_history, requester_after)

        requester_appraised = appraise_personal_experience(
            requester_after,
            requester_contact.experience_id,
            PersonalAppraisal(
                moment(4), 1.0, 1.0,
                (PersonalAdjustment(PersonalDimension.BELONGING, 0.6, 0.5),),
            ),
        )
        recipient_appraised = appraise_personal_experience(
            recipient_after,
            recipient_contact.experience_id,
            PersonalAppraisal(
                moment(4), 1.0, 1.0,
                (PersonalAdjustment(PersonalDimension.BELONGING, -0.4, 0.5),),
            ),
        )
        replay_after_appraisal = respond_to_support_request(
            accepted.ledger,
            request.conversation_id,
            recipient_id=RECIPIENT,
            decision=ConversationDecision.ACCEPT,
            at=moment(3),
            requester_history=requester_appraised,
            recipient_history=recipient_appraised,
        )
        self.assertIs(replay_after_appraisal.requester_history, requester_appraised)
        self.assertIs(replay_after_appraisal.recipient_history, recipient_appraised)
        self.assertEqual(
            replay_after_appraisal.requester_history.experiences[-1].state_changes,
            requester_appraised.experiences[-1].state_changes,
        )
        self.assertEqual(loads(dumps(requester_after), PersonalHistory), requester_after)
        self.assertEqual(loads(dumps(recipient_after), PersonalHistory), recipient_after)

    def test_decline_and_expiry_do_not_create_personal_experiences(self) -> None:
        request = make_request(suffix="declined")
        ledger = open_ledger(request)
        requester_before, recipient_before = response_histories(request)
        declined = respond_to_support_request(
            ledger,
            request.conversation_id,
            recipient_id=RECIPIENT,
            decision=ConversationDecision.DECLINE,
            at=moment(3),
            requester_history=requester_before,
            recipient_history=recipient_before,
        )
        self.assertIs(declined.requester_history, requester_before)
        self.assertIs(declined.recipient_history, recipient_before)
        self.assertIs(respond_to_support_request(
            declined.ledger,
            request.conversation_id,
            recipient_id=RECIPIENT,
            decision=ConversationDecision.DECLINE,
            at=moment(3),
            requester_history=requester_before,
            recipient_history=recipient_before,
        ).ledger, declined.ledger)
        with self.assertRaisesRegex(ValueError, "already resolved"):
            respond_to_support_request(
                declined.ledger,
                request.conversation_id,
                recipient_id=RECIPIENT,
                decision=ConversationDecision.ACCEPT,
                at=moment(3),
                requester_history=requester_before,
                recipient_history=recipient_before,
            )

        unanswered = make_request(suffix="expired")
        unanswered_ledger = open_ledger(unanswered)
        unanswered_histories = response_histories(unanswered)
        with self.assertRaisesRegex(ValueError, "has expired"):
            respond_to_support_request(
                unanswered_ledger,
                unanswered.conversation_id,
                recipient_id=RECIPIENT,
                decision=ConversationDecision.ACCEPT,
                at=unanswered.expires_at,
                requester_history=unanswered_histories[0],
                recipient_history=unanswered_histories[1],
            )
        with self.assertRaisesRegex(ValueError, "before its deadline"):
            expire_support_request(
                unanswered_ledger, unanswered.conversation_id, at=moment(4, days=6)
            )
        expiry_moment = moment(5, days=8)
        expired = expire_support_request(
            unanswered_ledger, unanswered.conversation_id, at=expiry_moment
        )
        self.assertEqual(expired.conversations[0].status, ConversationStatus.EXPIRED)
        self.assertEqual(expired.conversations[0].resolved_at, expiry_moment)
        self.assertIs(expire_support_request(
            expired, unanswered.conversation_id, at=expiry_moment
        ), expired)
        with self.assertRaisesRegex(ValueError, "different moment"):
            expire_support_request(
                expired, unanswered.conversation_id, at=moment(6, days=8)
            )
        self.assertEqual(unanswered_histories[0].experiences[-1].cause_event_id,
                         unanswered.source_event_id)
        self.assertEqual(len(unanswered_histories[1].experiences), 0)

    def test_private_projection_is_limited_to_participants(self) -> None:
        request = make_request()
        ledger = open_ledger(request)
        self.assertEqual(
            private_conversation_for(ledger, request.conversation_id, REQUESTER), request
        )
        self.assertEqual(
            private_conversations_for(ledger, RECIPIENT), (request,)
        )
        self.assertFalse(hasattr(request, "transcript"))
        self.assertIsNone(private_conversation_for(ledger, request.conversation_id, OUTSIDER))
        self.assertEqual(private_conversations_for(ledger, OUTSIDER), ())

    def test_history_subjects_must_match_and_expiry_cannot_replace_a_response(self) -> None:
        request = make_request()
        ledger = open_ledger(request)
        with self.assertRaisesRegex(ValueError, "belongs to another person"):
            respond_to_support_request(
                ledger,
                request.conversation_id,
                recipient_id=RECIPIENT,
                decision=ConversationDecision.ACCEPT,
                at=moment(3),
                requester_history=history(OUTSIDER),
                recipient_history=history(RECIPIENT),
            )
        self.assertEqual(ledger.conversations[0].status, ConversationStatus.OPEN)
        accepted = respond_to_support_request(
            ledger,
            request.conversation_id,
            recipient_id=RECIPIENT,
            decision=ConversationDecision.ACCEPT,
            at=moment(3),
            requester_history=source_history(request.source_event_id),
            recipient_history=history(RECIPIENT),
        )
        with self.assertRaisesRegex(ValueError, "cannot later expire"):
            expire_support_request(accepted.ledger, request.conversation_id, at=moment(4))

    def test_response_returns_no_partial_state_when_history_cannot_record_experience(self) -> None:
        request = make_request()
        ledger = open_ledger(request)
        requester_history, recipient_history = response_histories(request)
        conflicting = new_personal_experience(
            REQUESTER,
            EventId("event:conflicting-moment"),
            moment(3),
            AwarenessBasis.DIRECT,
            moment(3),
        )
        requester_history = record_personal_experience(requester_history, conflicting)
        with self.assertRaisesRegex(ValueError, "distinct world moments"):
            respond_to_support_request(
                ledger,
                request.conversation_id,
                recipient_id=RECIPIENT,
                decision=ConversationDecision.ACCEPT,
                at=moment(3),
                requester_history=requester_history,
                recipient_history=recipient_history,
            )
        self.assertEqual(ledger.conversations[0].status, ConversationStatus.OPEN)
        self.assertEqual(len(recipient_history.experiences), 0)

    def test_activity_moments_cannot_collide_across_requests_and_replies(self) -> None:
        first = make_request(suffix="chronology-first", opened=moment(2))
        second_event_id = EventId("event:source-chronology-second")
        second_source = source_history(
            second_event_id,
            occurred_at=moment(2, days=-1),
            awareness_at=moment(1),
        )
        second = new_support_conversation(
            source_event_id=second_event_id,
            requester_history=second_source,
            requester_id=REQUESTER,
            recipient_id=RECIPIENT,
            topic=ConversationTopic.PERSONAL,
            requested_mode=SupportMode.LISTEN,
            opened_at=moment(4),
        )
        ledger = record_support_conversation(
            open_ledger(first), second,
            requester_history=second_source,
        )
        first_result = respond_to_support_request(
            ledger,
            first.conversation_id,
            recipient_id=RECIPIENT,
            decision=ConversationDecision.ACCEPT,
            at=moment(5),
            requester_history=source_history(first.source_event_id),
            recipient_history=history(RECIPIENT),
        )
        with self.assertRaisesRegex(ValueError, "distinct world moments"):
            respond_to_support_request(
                first_result.ledger,
                second.conversation_id,
                recipient_id=RECIPIENT,
                decision=ConversationDecision.DECLINE,
                at=moment(5),
                requester_history=second_source,
                recipient_history=history(RECIPIENT),
            )

        later_source_id = EventId("event:chronology-later-source")
        later_source = source_history(
            later_source_id,
            occurred_at=moment(5),
            awareness_at=moment(5),
            awareness=AwarenessBasis.DIRECT,
        )
        later_request = new_support_conversation(
            source_event_id=later_source_id,
            requester_history=later_source,
            requester_id=REQUESTER,
            recipient_id=PersonId("player:second-recipient"),
            topic=ConversationTopic.PERSONAL,
            requested_mode=SupportMode.LISTEN,
            opened_at=moment(6),
        )
        source_collision_ledger = record_support_conversation(
            ledger,
            later_request,
            requester_history=later_source,
        )
        with self.assertRaisesRegex(ValueError, "distinct world moments"):
            respond_to_support_request(
                source_collision_ledger,
                first.conversation_id,
                recipient_id=RECIPIENT,
                decision=ConversationDecision.ACCEPT,
                at=moment(5),
                requester_history=source_history(first.source_event_id),
                recipient_history=history(RECIPIENT),
            )
        with self.assertRaisesRegex(ValueError, "distinct world moments"):
            respond_to_support_request(
                ledger,
                first.conversation_id,
                recipient_id=RECIPIENT,
                decision=ConversationDecision.ACCEPT,
                at=moment(4),
                requester_history=source_history(first.source_event_id),
                recipient_history=history(RECIPIENT),
            )

    def test_shared_source_reference_keeps_one_event_moment(self) -> None:
        source_event_id = EventId("event:shared-support-source")
        source = source_history(source_event_id)
        first = new_support_conversation(
            source_event_id=source_event_id,
            requester_history=source,
            requester_id=REQUESTER,
            recipient_id=RECIPIENT,
            topic=ConversationTopic.PERSONAL,
            requested_mode=SupportMode.LISTEN,
            opened_at=moment(2),
        )
        second = new_support_conversation(
            source_event_id=source_event_id,
            requester_history=source,
            requester_id=REQUESTER,
            recipient_id=PersonId("player:second-recipient"),
            topic=ConversationTopic.PERSONAL,
            requested_mode=SupportMode.ADVICE,
            opened_at=moment(3),
        )
        ledger = record_support_conversation(
            open_ledger(first), second, requester_history=source
        )
        self.assertEqual(
            tuple(item.source_event_id for item in ledger.conversations),
            (source_event_id, source_event_id),
        )

    def test_probe_is_byte_stable_and_import_is_headless(self) -> None:
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        command = [sys.executable, "-m", "games.touchline.checks.conversation_probe"]
        first = subprocess.run(command, cwd=ROOT, env=env, check=True,
                               capture_output=True, text=True)
        second = subprocess.run(command, cwd=ROOT, env=env, check=True,
                                capture_output=True, text=True)
        self.assertEqual(first.stdout, second.stdout)

        headless = r"""
import builtins, io, sys
def denied(*args, **kwargs):
    raise AssertionError('domain import attempted file access')
builtins.open = denied
io.open = denied
import games.touchline.esb.people.conversations
assert 'curses' not in sys.modules
assert 'games.touchline.main' not in sys.modules
assert 'games.touchline.esb.media.publication' not in sys.modules
"""
        subprocess.run([sys.executable, "-c", headless], cwd=ROOT, env=env,
                       check=True, capture_output=True, text=True)


if __name__ == "__main__":
    unittest.main()
