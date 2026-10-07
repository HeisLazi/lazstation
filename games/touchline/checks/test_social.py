from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

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
    OfferStatus,
    SessionOutcome,
    SessionParticipant,
    SharedSession,
    SocialChoiceOutcome,
    SocialDisposition,
    SocialLedger,
    SocialOffer,
    expire_offer,
    propose_autonomous_offer,
    record_shared_session,
    respond_to_offer,
)
from games.touchline.esb.serialization import SerializationError, dumps, loads
from games.touchline.esb.time import WorldDate

ROOT = Path(__file__).resolve().parents[3]
START = WorldDate(date(2026, 10, 6))
MENTOR = PersonId("player:mentor")
NEWCOMER = PersonId("player:newcomer")
UNRELATED = PersonId("player:unrelated")


def moment(sequence: int, days: int = 0) -> WorldMoment:
    return WorldMoment(WorldDate(START.day + timedelta(days=days)), sequence)


def completed_session(event: str = "event:session-1", at: WorldMoment | None = None) -> SharedSession:
    return SharedSession(
        event_id=EventId(event),
        at=at or moment(1),
        outcome=SessionOutcome.COMPLETED,
        participants=(
            SessionParticipant(MENTOR, "group:passing-pod-a", 30),
            SessionParticipant(NEWCOMER, "group:passing-pod-a", 25),
            SessionParticipant(UNRELATED, "group:passing-pod-b", 30),
            SessionParticipant(PersonId("player:brief-attendee"), "group:passing-pod-a", 8),
        ),
    )


def opportunity_fixture() -> tuple[SocialLedger, str]:
    ledger = record_shared_session(SocialLedger(), completed_session())
    opportunity = next(item for item in ledger.opportunities if set(item.participants) == {MENTOR, NEWCOMER})
    return ledger, str(opportunity.opportunity_id)


def trust_edge(*, source: PersonId = MENTOR, target: PersonId = NEWCOMER,
               at: WorldMoment | None = None):
    return record_relationship_evidence(
        None,
        source_person_id=source,
        target_person_id=target,
        dimension=RelationshipDimension.TRUST,
        delta=0.0,
        event_id=EventId("event:trust-evidence"),
        at=at or moment(2),
        direct_contact=False,
        initial_value=0.75,
    )


def mentor_profiles() -> tuple[SocialDisposition, SocialDisposition, MentorCapacity]:
    return (
        SocialDisposition(MENTOR, mentoring_willingness=0.95),
        SocialDisposition(NEWCOMER, mentoring_interest=0.90, mentoring_receptivity=0.95),
        MentorCapacity(MENTOR, concurrent_slots=1),
    )


class SocialSimulationTests(unittest.TestCase):
    def test_only_completed_meaningful_cogroup_attendance_creates_opportunities(self) -> None:
        ledger = record_shared_session(SocialLedger(), completed_session())
        self.assertEqual(len(ledger.opportunities), 1)
        opportunity = ledger.opportunities[0]
        self.assertEqual(set(opportunity.participants), {MENTOR, NEWCOMER})
        self.assertEqual(opportunity.shared_minutes, 25)
        self.assertEqual(opportunity.source_event_id, EventId("event:session-1"))
        self.assertEqual(record_shared_session(ledger, completed_session()), ledger)

        skipped = SharedSession(
            EventId("event:session-skipped"), moment(2), SessionOutcome.SKIPPED,
            completed_session().participants,
        )
        after_skip = record_shared_session(ledger, skipped)
        self.assertEqual(after_skip.opportunities, ledger.opportunities)
        self.assertEqual(len(after_skip.sessions), 2)

        conflicting = SharedSession(
            EventId("event:session-1"), moment(1), SessionOutcome.SKIPPED,
            completed_session().participants,
        )
        with self.assertRaisesRegex(ValueError, "conflicting content"):
            record_shared_session(ledger, conflicting)

    def test_opportunities_require_actual_overlapping_minutes(self) -> None:
        session = SharedSession(
            EventId("event:staggered-session"), moment(1), SessionOutcome.COMPLETED,
            (
                SessionParticipant(MENTOR, "group:staggered", 20, arrival_minute=0),
                SessionParticipant(NEWCOMER, "group:staggered", 20, arrival_minute=6),
                SessionParticipant(UNRELATED, "group:staggered", 20, arrival_minute=5),
            ),
        )
        ledger = record_shared_session(SocialLedger(), session)
        pairs = {frozenset(item.participants): item.shared_minutes for item in ledger.opportunities}
        self.assertNotIn(frozenset((MENTOR, NEWCOMER)), pairs)
        self.assertEqual(pairs[frozenset((MENTOR, UNRELATED))], 15)
        self.assertEqual(pairs[frozenset((NEWCOMER, UNRELATED))], 19)

    def test_shared_context_group_size_is_bounded(self) -> None:
        participants = tuple(
            SessionParticipant(PersonId(f"player:group-{index}"), "group:oversized", 20)
            for index in range(33)
        )
        with self.assertRaisesRegex(ValueError, "limited to 32 participants"):
            SharedSession(
                EventId("event:oversized-session"), moment(1),
                SessionOutcome.COMPLETED, participants,
            )

    def test_player_initiated_mentoring_offer_acceptance_retains_source_lineage(self) -> None:
        ledger, opportunity_id = opportunity_fixture()
        mentor, newcomer, capacity = mentor_profiles()
        edge = trust_edge()
        ledger, decision = propose_autonomous_offer(
            ledger,
            opportunity_id=opportunity_id,
            kind=OfferKind.MENTORSHIP,
            initiator=mentor,
            recipient=newcomer,
            at=moment(3),
            relationship=edge,
            mentor_capacity=capacity,
        )
        self.assertEqual(decision.choice.outcome, SocialChoiceOutcome.OFFERED)
        self.assertEqual(decision.choice.reason, "willing_trusted_mentor")
        self.assertGreaterEqual(decision.choice.score, decision.choice.threshold)
        self.assertEqual(decision.choice.source_event_id, EventId("event:session-1"))
        self.assertEqual(decision.offer.status, OfferStatus.OFFERED)
        self.assertEqual(decision.offer.initiator_id, MENTOR)
        self.assertEqual(decision.offer.recipient_id, NEWCOMER)

        restored = loads(dumps(ledger), SocialLedger)
        self.assertEqual(restored, ledger)
        ledger, accepted = respond_to_offer(
            ledger,
            offer_id=decision.offer.offer_id,
            recipient=newcomer,
            at=moment(4),
            mentor_capacity=capacity,
        )
        self.assertEqual(accepted.status, OfferStatus.ACCEPTED)
        self.assertEqual(accepted.response_reason, "mentoring_offer_accepted")
        self.assertIsNone(accepted.response_relationship_value)
        self.assertIsNone(accepted.response_relationship_dimension)
        self.assertEqual(accepted.response_score, newcomer.mentoring_receptivity)
        self.assertEqual(len(ledger.introductions), 1)
        introduction = ledger.introductions[0]
        self.assertEqual(introduction.offer_id, accepted.offer_id)
        self.assertEqual(introduction.opportunity_id, accepted.opportunity_id)
        self.assertEqual(introduction.source_event_id, EventId("event:session-1"))
        self.assertEqual(set(introduction.participants), {MENTOR, NEWCOMER})
        self.assertEqual(introduction.at, moment(4))
        # P13b records consent and introduction only. No mentorship or learning
        # receipt is created by accepting an offer.
        self.assertFalse(hasattr(ledger, "active_mentorships"))
        self.assertFalse(hasattr(accepted, "learning_receipts"))
        self.assertEqual(loads(dumps(ledger), SocialLedger), ledger)

    def test_accepted_mentoring_reservation_holds_until_boundary_then_releases(self) -> None:
        ledger, opportunity_id = opportunity_fixture()
        mentor, newcomer, capacity = mentor_profiles()
        edge = trust_edge()
        ledger, first = propose_autonomous_offer(
            ledger, opportunity_id=opportunity_id, kind=OfferKind.MENTORSHIP,
            initiator=mentor, recipient=newcomer, at=moment(3),
            relationship=edge, mentor_capacity=capacity,
        )
        ledger, accepted = respond_to_offer(
            ledger, offer_id=first.offer.offer_id, recipient=newcomer,
            at=moment(4), mentor_capacity=capacity,
        )
        boundary = accepted.reservation_until
        self.assertIsNotNone(boundary)
        self.assertEqual(boundary.on.day, START.day + timedelta(days=7))
        self.assertEqual(boundary.sequence, 0)

        before_boundary_session = completed_session(
            "event:session-before-reservation-end",
            WorldMoment(WorldDate(boundary.on.day - timedelta(days=1)), 1),
        )
        ledger = record_shared_session(ledger, before_boundary_session)
        before_boundary_opportunity = next(
            item for item in ledger.opportunities
            if item.source_event_id == before_boundary_session.event_id
            and set(item.participants) == {MENTOR, NEWCOMER}
        )
        ledger, still_reserved = propose_autonomous_offer(
            ledger, opportunity_id=before_boundary_opportunity.opportunity_id,
            kind=OfferKind.MENTORSHIP, initiator=mentor, recipient=newcomer,
            at=WorldMoment(before_boundary_session.at.on, 2),
            relationship=edge, mentor_capacity=capacity,
        )
        self.assertEqual(still_reserved.choice.outcome, SocialChoiceOutcome.CAPACITY_FULL)

        boundary_session = completed_session(
            "event:session-at-reservation-end", WorldMoment(boundary.on, 1)
        )
        ledger = record_shared_session(ledger, boundary_session)
        boundary_opportunity = next(
            item for item in ledger.opportunities
            if item.source_event_id == boundary_session.event_id
            and set(item.participants) == {MENTOR, NEWCOMER}
        )
        ledger, released = propose_autonomous_offer(
            ledger, opportunity_id=boundary_opportunity.opportunity_id,
            kind=OfferKind.MENTORSHIP, initiator=mentor, recipient=newcomer,
            at=WorldMoment(boundary.on, 2), relationship=edge, mentor_capacity=capacity,
        )
        self.assertEqual(released.choice.outcome, SocialChoiceOutcome.OFFERED)
        self.assertEqual(accepted.status, OfferStatus.ACCEPTED)
        self.assertEqual(len(ledger.introductions), 1)

    def test_unanswered_offer_expires_at_boundary_and_releases_capacity(self) -> None:
        ledger, opportunity_id = opportunity_fixture()
        mentor, newcomer, capacity = mentor_profiles()
        edge = trust_edge()
        ledger, decision = propose_autonomous_offer(
            ledger, opportunity_id=opportunity_id, kind=OfferKind.MENTORSHIP,
            initiator=mentor, recipient=newcomer, at=moment(3),
            relationship=edge, mentor_capacity=capacity,
        )
        deadline = decision.offer.expires_at
        before_deadline = WorldMoment(WorldDate(deadline.on.day - timedelta(days=1)), 999)
        with self.assertRaisesRegex(ValueError, "has not reached"):
            expire_offer(ledger, offer_id=decision.offer.offer_id, at=before_deadline)
        ledger, expired = respond_to_offer(
            ledger, offer_id=decision.offer.offer_id, recipient=newcomer,
            at=deadline, mentor_capacity=capacity,
        )
        self.assertEqual(expired.status, OfferStatus.EXPIRED)
        self.assertEqual(expired.responded_at, deadline)
        self.assertEqual(expired.response_reason, "offer_expired")
        self.assertIsNone(expired.recipient_disposition)
        self.assertEqual(ledger.introductions, ())
        replay, same_expiry = expire_offer(ledger, offer_id=expired.offer_id, at=deadline)
        self.assertIs(replay, ledger)
        self.assertEqual(same_expiry, expired)
        replay, same_response_expiry = respond_to_offer(
            ledger, offer_id=expired.offer_id, recipient=newcomer,
            at=deadline, mentor_capacity=capacity,
        )
        self.assertIs(replay, ledger)
        self.assertEqual(same_response_expiry, expired)

        later_session = completed_session("event:session-after-offer-expiry", WorldMoment(deadline.on, 1))
        ledger = record_shared_session(ledger, later_session)
        later_opportunity = next(
            item for item in ledger.opportunities
            if item.source_event_id == later_session.event_id
            and set(item.participants) == {MENTOR, NEWCOMER}
        )
        ledger, available = propose_autonomous_offer(
            ledger, opportunity_id=later_opportunity.opportunity_id,
            kind=OfferKind.MENTORSHIP, initiator=mentor, recipient=newcomer,
            at=WorldMoment(deadline.on, 2), relationship=edge, mentor_capacity=capacity,
        )
        self.assertEqual(available.choice.outcome, SocialChoiceOutcome.OFFERED)

    def test_offer_choice_and_response_are_idempotent_and_conflicts_rejected(self) -> None:
        ledger, opportunity_id = opportunity_fixture()
        mentor, newcomer, capacity = mentor_profiles()
        edge = trust_edge()
        proposal = dict(
            opportunity_id=opportunity_id,
            kind=OfferKind.MENTORSHIP,
            initiator=mentor,
            recipient=newcomer,
            at=moment(3),
            relationship=edge,
            mentor_capacity=capacity,
        )
        ledger, first = propose_autonomous_offer(ledger, **proposal)
        replay, repeated = propose_autonomous_offer(ledger, **proposal)
        self.assertIs(replay, ledger)
        self.assertEqual(repeated, first)
        with self.assertRaisesRegex(ValueError, "conflicting inputs"):
            propose_autonomous_offer(
                ledger,
                **{**proposal, "initiator": SocialDisposition(MENTOR, mentoring_willingness=0.85)},
            )

        response = dict(
            offer_id=first.offer.offer_id,
            recipient=newcomer,
            at=moment(4),
            mentor_capacity=capacity,
        )
        ledger, accepted = respond_to_offer(ledger, **response)
        replay, repeated = respond_to_offer(ledger, **response)
        self.assertIs(replay, ledger)
        self.assertEqual(repeated, accepted)
        with self.assertRaisesRegex(ValueError, "conflicting inputs"):
            respond_to_offer(
                ledger,
                **{**response, "recipient": SocialDisposition(
                    NEWCOMER, mentoring_interest=0.90, mentoring_receptivity=0.80,
                )},
            )
        with self.assertRaisesRegex(ValueError, "only the named offer recipient"):
            respond_to_offer(
                ledger, offer_id=first.offer.offer_id,
                recipient=mentor, at=moment(4), relationship=edge,
                mentor_capacity=capacity,
            )

    def test_decline_has_no_bond_effect_and_releases_capacity_for_later_offer(self) -> None:
        ledger, opportunity_id = opportunity_fixture()
        mentor, newcomer, capacity = mentor_profiles()
        edge = trust_edge()
        ledger, first = propose_autonomous_offer(
            ledger, opportunity_id=opportunity_id, kind=OfferKind.MENTORSHIP,
            initiator=mentor, recipient=newcomer, at=moment(3),
            relationship=edge, mentor_capacity=capacity,
        )
        hesitant = SocialDisposition(NEWCOMER, mentoring_receptivity=0.1)
        before = edge
        ledger, declined = respond_to_offer(
            ledger, offer_id=first.offer.offer_id, recipient=hesitant, at=moment(4),
            mentor_capacity=capacity,
        )
        self.assertEqual(declined.status, OfferStatus.DECLINED)
        self.assertEqual(declined.response_reason, "mentoring_receptivity_below_threshold")
        self.assertEqual(ledger.introductions, ())
        self.assertEqual(edge, before)

        second_session = completed_session("event:session-2", moment(5))
        ledger = record_shared_session(ledger, second_session)
        second_opportunity = next(
            item for item in ledger.opportunities
            if item.source_event_id == EventId("event:session-2")
            and set(item.participants) == {MENTOR, NEWCOMER}
        )
        ledger, second = propose_autonomous_offer(
            ledger, opportunity_id=second_opportunity.opportunity_id,
            kind=OfferKind.MENTORSHIP, initiator=mentor, recipient=newcomer,
            at=moment(6), relationship=edge, mentor_capacity=capacity,
        )
        self.assertEqual(second.choice.outcome, SocialChoiceOutcome.OFFERED)
        self.assertNotEqual(first.offer.offer_id, second.offer.offer_id)

    def test_full_capacity_blocks_offer_without_relationship_or_personal_state_effect(self) -> None:
        ledger, opportunity_id = opportunity_fixture()
        mentor, newcomer, _ = mentor_profiles()
        edge = trust_edge()
        full = MentorCapacity(MENTOR, concurrent_slots=1, external_commitments=1)
        ledger, decision = propose_autonomous_offer(
            ledger, opportunity_id=opportunity_id, kind=OfferKind.MENTORSHIP,
            initiator=mentor, recipient=newcomer, at=moment(3),
            relationship=edge, mentor_capacity=full,
        )
        self.assertEqual(decision.choice.outcome, SocialChoiceOutcome.CAPACITY_FULL)
        self.assertEqual(decision.choice.reason, "mentor_capacity_full")
        self.assertIsNone(decision.offer)
        self.assertEqual(ledger.offers, ())
        self.assertEqual(ledger.introductions, ())
        self.assertEqual(edge, trust_edge())
        replay, repeated = propose_autonomous_offer(
            ledger, opportunity_id=opportunity_id, kind=OfferKind.MENTORSHIP,
            initiator=mentor, recipient=newcomer, at=moment(3),
            relationship=edge, mentor_capacity=full,
        )
        self.assertIs(replay, ledger)
        self.assertEqual(repeated, decision)
        with self.assertRaisesRegex(ValueError, "conflicting inputs"):
            propose_autonomous_offer(
                ledger, opportunity_id=opportunity_id, kind=OfferKind.MENTORSHIP,
                initiator=mentor, recipient=newcomer, at=moment(3),
                relationship=edge, mentor_capacity=MentorCapacity(MENTOR, 1),
            )

    def test_capacity_is_rechecked_at_acceptance_and_rejected_offer_releases_slot(self) -> None:
        ledger, opportunity_id = opportunity_fixture()
        mentor, newcomer, capacity = mentor_profiles()
        edge = trust_edge()
        ledger, decision = propose_autonomous_offer(
            ledger, opportunity_id=opportunity_id, kind=OfferKind.MENTORSHIP,
            initiator=mentor, recipient=newcomer, at=moment(3),
            relationship=edge, mentor_capacity=capacity,
        )
        changed = MentorCapacity(MENTOR, concurrent_slots=1, external_commitments=1)
        ledger, unavailable = respond_to_offer(
            ledger, offer_id=decision.offer.offer_id, recipient=newcomer, at=moment(4),
            mentor_capacity=changed,
        )
        self.assertEqual(unavailable.status, OfferStatus.CAPACITY_UNAVAILABLE)
        self.assertEqual(unavailable.response_reason, "mentor_capacity_changed")
        self.assertEqual(ledger.introductions, ())
        self.assertEqual(edge, trust_edge())
        later_ledger = record_shared_session(
            ledger, completed_session("event:session-after-capacity", moment(5))
        )
        later_opportunity = next(
            item for item in later_ledger.opportunities
            if item.source_event_id == EventId("event:session-after-capacity")
            and set(item.participants) == {MENTOR, NEWCOMER}
        )
        later_ledger, available_again = propose_autonomous_offer(
            later_ledger, opportunity_id=later_opportunity.opportunity_id,
            kind=OfferKind.MENTORSHIP, initiator=mentor, recipient=newcomer,
            at=moment(6), relationship=edge, mentor_capacity=capacity,
        )
        self.assertEqual(available_again.choice.outcome, SocialChoiceOutcome.OFFERED)

    def test_missing_or_reverse_trust_does_not_turn_into_friendship_or_mentoring_authority(self) -> None:
        ledger, opportunity_id = opportunity_fixture()
        mentor, newcomer, capacity = mentor_profiles()
        ledger, missing = propose_autonomous_offer(
            ledger, opportunity_id=opportunity_id, kind=OfferKind.MENTORSHIP,
            initiator=mentor, recipient=newcomer, at=moment(3),
            relationship=None, mentor_capacity=capacity,
        )
        self.assertEqual(missing.choice.outcome, SocialChoiceOutcome.NO_OFFER)
        self.assertEqual(missing.choice.reason, "trust_not_established")

        edge = trust_edge()
        ledger = record_shared_session(
            ledger, completed_session("event:session-low-willingness", moment(4))
        )
        second_opportunity = next(
            item for item in ledger.opportunities
            if item.source_event_id == EventId("event:session-low-willingness")
            and set(item.participants) == {MENTOR, NEWCOMER}
        )
        ledger, hesitant = propose_autonomous_offer(
            ledger, opportunity_id=second_opportunity.opportunity_id,
            kind=OfferKind.MENTORSHIP,
            initiator=SocialDisposition(MENTOR, mentoring_willingness=0.20),
            recipient=newcomer, at=moment(5), relationship=edge,
            mentor_capacity=capacity,
        )
        self.assertEqual(hesitant.choice.outcome, SocialChoiceOutcome.NO_OFFER)
        self.assertEqual(hesitant.choice.reason, "mentoring_interest_below_threshold")
        reverse = trust_edge(source=NEWCOMER, target=MENTOR)
        with self.assertRaisesRegex(ValueError, "initiator-to-recipient"):
            propose_autonomous_offer(
                ledger, opportunity_id=opportunity_id, kind=OfferKind.MENTORSHIP,
                initiator=mentor, recipient=newcomer, at=moment(6),
                relationship=reverse, mentor_capacity=capacity,
            )
        fresh_ledger, fresh_opportunity_id = opportunity_fixture()
        future_edge = trust_edge(at=moment(9))
        with self.assertRaisesRegex(ValueError, "evidence from the future"):
            propose_autonomous_offer(
                fresh_ledger, opportunity_id=fresh_opportunity_id,
                kind=OfferKind.MENTORSHIP, initiator=mentor, recipient=newcomer,
                at=moment(3), relationship=future_edge, mentor_capacity=capacity,
            )

    def test_friendship_is_asymmetric_and_affinity_is_not_a_penalty_on_decline(self) -> None:
        ledger, opportunity_id = opportunity_fixture()
        friendship_edge = record_relationship_evidence(
            None, source_person_id=MENTOR, target_person_id=NEWCOMER,
            dimension=RelationshipDimension.AFFINITY, delta=0.0,
            event_id=EventId("event:affinity-evidence"), at=moment(2),
            direct_contact=False, initial_value=0.80,
        )
        initiator = SocialDisposition(MENTOR, friendship_initiative=0.95)
        recipient = SocialDisposition(NEWCOMER, friendship_receptivity=0.10)
        ledger, decision = propose_autonomous_offer(
            ledger, opportunity_id=opportunity_id, kind=OfferKind.FRIENDSHIP,
            initiator=initiator, recipient=recipient, at=moment(3),
            relationship=friendship_edge,
        )
        self.assertEqual(decision.choice.outcome, SocialChoiceOutcome.OFFERED)
        ledger, declined = respond_to_offer(
            ledger, offer_id=decision.offer.offer_id, recipient=recipient, at=moment(4),
            relationship=friendship_edge,
        )
        self.assertEqual(declined.status, OfferStatus.DECLINED)
        self.assertEqual(ledger.introductions, ())
        self.assertEqual(friendship_edge.dimensions[0].value, 0.80)

    def test_friendship_offer_can_be_accepted_without_mentor_capacity(self) -> None:
        ledger, opportunity_id = opportunity_fixture()
        edge = record_relationship_evidence(
            None, source_person_id=MENTOR, target_person_id=NEWCOMER,
            dimension=RelationshipDimension.AFFINITY, delta=0.0,
            event_id=EventId("event:friendship-affinity"), at=moment(2),
            direct_contact=True, initial_value=0.80,
        )
        initiator = SocialDisposition(MENTOR, friendship_initiative=0.95)
        recipient = SocialDisposition(NEWCOMER, friendship_receptivity=0.95)
        ledger, decision = propose_autonomous_offer(
            ledger, opportunity_id=opportunity_id, kind=OfferKind.FRIENDSHIP,
            initiator=initiator, recipient=recipient, at=moment(3),
            relationship=edge,
        )
        ledger, accepted = respond_to_offer(
            ledger, offer_id=decision.offer.offer_id, recipient=recipient,
            at=moment(4), relationship=edge,
        )
        self.assertEqual(accepted.status, OfferStatus.ACCEPTED)
        self.assertIsNone(accepted.response_capacity)
        self.assertEqual(len(ledger.introductions), 1)
        self.assertEqual(ledger.introductions[0].offer_id, accepted.offer_id)

    def test_opportunity_is_mandatory_and_session_order_is_chronological(self) -> None:
        with self.assertRaisesRegex(ValueError, "world chronology"):
            ledger = record_shared_session(SocialLedger(), completed_session())
            record_shared_session(ledger, completed_session("event:older", moment(0)))
        with self.assertRaisesRegex(ValueError, "requires a recorded shared-context opportunity"):
            propose_autonomous_offer(
                SocialLedger(), opportunity_id="opportunity:unknown", kind=OfferKind.FRIENDSHIP,
                initiator=SocialDisposition(MENTOR), recipient=SocialDisposition(NEWCOMER),
                at=moment(3),
            )

    def test_same_moment_mentor_proposals_are_serialized_to_prevent_overbooking(self) -> None:
        ledger, first_opportunity_id = opportunity_fixture()
        mentor, newcomer, capacity = mentor_profiles()
        edge = trust_edge()
        ledger = record_shared_session(
            ledger, completed_session("event:simultaneous-session", moment(2))
        )
        second_opportunity_id = next(
            item.opportunity_id for item in ledger.opportunities
            if item.source_event_id == EventId("event:simultaneous-session")
            and set(item.participants) == {MENTOR, NEWCOMER}
        )
        ledger, first = propose_autonomous_offer(
            ledger, opportunity_id=first_opportunity_id,
            kind=OfferKind.MENTORSHIP, initiator=mentor, recipient=newcomer,
            at=moment(3), relationship=edge, mentor_capacity=capacity,
        )
        with self.assertRaisesRegex(ValueError, "distinct world moments"):
            propose_autonomous_offer(
                ledger, opportunity_id=second_opportunity_id,
                kind=OfferKind.MENTORSHIP, initiator=mentor, recipient=newcomer,
                at=moment(3), relationship=edge, mentor_capacity=capacity,
            )
        self.assertEqual(len(ledger.choices), 1)
        self.assertEqual(len(ledger.offers), 1)
        self.assertEqual(first.offer.status, OfferStatus.OFFERED)

    def test_social_ledger_rejects_tampered_persisted_acceptance(self) -> None:
        ledger, opportunity_id = opportunity_fixture()
        mentor, newcomer, capacity = mentor_profiles()
        edge = trust_edge()
        ledger, decision = propose_autonomous_offer(
            ledger, opportunity_id=opportunity_id, kind=OfferKind.MENTORSHIP,
            initiator=mentor, recipient=newcomer, at=moment(3),
            relationship=edge, mentor_capacity=capacity,
        )
        ledger, _ = respond_to_offer(
            ledger, offer_id=decision.offer.offer_id, recipient=newcomer, at=moment(4),
            mentor_capacity=capacity,
        )
        payload = json.loads(dumps(ledger))
        payload["payload"]["introductions"] = []
        with self.assertRaisesRegex(SerializationError, "domain contract"):
            loads(json.dumps(payload), SocialLedger)
        payload = json.loads(dumps(ledger))
        payload["payload"]["offers"][0]["response_score"] = 0.01
        with self.assertRaisesRegex(SerializationError, "domain contract"):
            loads(json.dumps(payload), SocialLedger)
        payload = json.loads(dumps(ledger))
        payload["payload"]["offers"][0]["response_event_id"] = "event:tampered-response"
        with self.assertRaisesRegex(SerializationError, "domain contract"):
            loads(json.dumps(payload), SocialLedger)

    def test_probe_is_fresh_process_deterministic_and_social_import_is_headless(self) -> None:
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        command = [sys.executable, "-m", "games.touchline.checks.social_probe"]
        first = subprocess.run(command, cwd=ROOT, env=env, check=True, capture_output=True, text=True)
        second = subprocess.run(command, cwd=ROOT, env=env, check=True, capture_output=True, text=True)
        self.assertEqual(first.stdout, second.stdout)
        probe = json.loads(first.stdout)
        self.assertEqual(probe["offer_status"], "accepted")
        self.assertEqual(probe["introduction_count"], 1)

        headless = r"""
import builtins, io, sys
def denied(*args, **kwargs):
    raise AssertionError('social-domain imports must not open files')
builtins.open = denied
io.open = denied
import games.touchline.esb.people.social
assert 'curses' not in sys.modules
assert 'termstation_ui' not in sys.modules
assert 'games.touchline.main' not in sys.modules
"""
        subprocess.run([sys.executable, "-c", headless], cwd=ROOT, env=env, check=True)


if __name__ == "__main__":
    unittest.main()
