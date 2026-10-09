"""Mechanism tests for P13c activated mentoring and evidenced learning."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

from games.touchline.esb.content.proof_roster import PROOF_SQUADS
from games.touchline.esb.ids import EventId
from games.touchline.esb.people.mentorship import (
    BASE_FOCUS_LEARNING_PER_REPETITION,
    DemonstratedBehavior,
    FocusAgreement,
    MentorTimeBudget,
    MentorshipAction,
    MentorshipFocus,
    MentorshipLedger,
    MentorshipStatus,
    MAX_MENTOR_TRUST_EVIDENCE_AGE_DAYS,
    activate_mentorship,
    end_mentorship,
    pause_mentorship,
    record_mentorship_contact,
    record_mentorship_review,
    resume_mentorship,
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
    OfferStatus,
    SessionOutcome,
    SessionParticipant,
    SharedSession,
    SocialDisposition,
    SocialLedger,
    propose_autonomous_offer,
    record_shared_session,
    respond_to_offer,
)
from games.touchline.esb.serialization import SerializationError, dumps, loads
from games.touchline.esb.time import WorldDate

ROOT = Path(__file__).resolve().parents[3]
START = WorldDate(date(2026, 10, 6))
FOCUS = MentorshipFocus.PASSING


def moment(sequence: int, days: int = 0, *, start: WorldDate = START) -> WorldMoment:
    return WorldMoment(WorldDate(start.day + timedelta(days=days)), sequence)


def prepared_scenario(
    *, suffix: str = "primary", mentee_index: int = 1,
    trust_age_days: int = 0, slots: int = 1, receptivity: float = 0.95,
) -> dict[str, object]:
    mentor_profile = PROOF_SQUADS[0].players[0]
    mentee_profile = PROOF_SQUADS[0].players[mentee_index]
    mentor = PersonId(str(mentor_profile.player_id))
    mentee = PersonId(str(mentee_profile.player_id))
    session = SharedSession(
        EventId(f"event:{suffix}-session"), moment(1), SessionOutcome.COMPLETED,
        (
            SessionParticipant(mentor, f"group:{suffix}-pair", 30),
            SessionParticipant(mentee, f"group:{suffix}-pair", 30),
        ),
    )
    social = record_shared_session(SocialLedger(), session)
    opportunity = social.opportunities[0]
    trust_date = WorldDate(START.day - timedelta(days=trust_age_days))
    forward = record_relationship_evidence(
        None, source_person_id=mentor, target_person_id=mentee,
        dimension=RelationshipDimension.TRUST, delta=0.0,
        event_id=EventId(f"event:{suffix}-trust-forward"),
        at=WorldMoment(trust_date, 1), direct_contact=True, initial_value=0.75,
    )
    reverse = record_relationship_evidence(
        None, source_person_id=mentee, target_person_id=mentor,
        dimension=RelationshipDimension.TRUST, delta=0.0,
        event_id=EventId(f"event:{suffix}-trust-reverse"),
        at=WorldMoment(trust_date, 2), direct_contact=True, initial_value=0.65,
    )
    relationships = tuple(sorted(
        (forward, reverse),
        key=lambda edge: (str(edge.source_person_id), str(edge.target_person_id)),
    ))
    capacity = MentorCapacity(mentor, concurrent_slots=slots)
    mentor_disposition = SocialDisposition(mentor, mentoring_willingness=0.95)
    mentee_disposition = SocialDisposition(
        mentee, mentoring_interest=0.90, mentoring_receptivity=receptivity,
    )
    social, decision = propose_autonomous_offer(
        social,
        opportunity_id=opportunity.opportunity_id,
        kind=OfferKind.MENTORSHIP,
        initiator=mentor_disposition,
        recipient=mentee_disposition,
        at=moment(3),
        relationship=forward,
        mentor_capacity=capacity,
    )
    if decision.offer is None:
        raise AssertionError(f"test fixture could not create its offer: {decision.choice.reason}")
    social, offer = respond_to_offer(
        social, offer_id=decision.offer.offer_id,
        recipient=mentee_disposition, at=moment(4), mentor_capacity=capacity,
    )
    agreement = FocusAgreement(
        FOCUS, mentor, mentee,
        EventId(f"event:{suffix}-mentor-focus"),
        EventId(f"event:{suffix}-mentee-interest"),
        0.82, 0.88, moment(5),
    )
    return {
        "social": social,
        "offer": offer,
        "mentor": mentor,
        "mentee": mentee,
        "mentee_profile": mentee_profile,
        "capacity": capacity,
        "relationships": relationships,
        "forward": forward,
        "reverse": reverse,
        "agreement": agreement,
    }


def active_scenario(**kwargs):
    value = prepared_scenario(**kwargs)
    value["ledger"], value["mentorship"] = activate_mentorship(
        value["social"], MentorshipLedger(),
        offer_id=str(value["offer"].offer_id),
        at=moment(6), actor_id=value["mentor"],
        focus_agreements=(value["agreement"],),
        mentor_capacity=value["capacity"],
        relationships=value["relationships"],
    )
    return value


def record_contact(value, *, sequence: int = 8, source: str = "demonstration-1",
                   duration: int = 20, repetitions: int = 12):
    ledger = record_mentorship_contact(
        value["ledger"],
        mentorship_id=value["mentorship"].mentorship_id,
        contact_id=EventId(f"event:{source}-contact"),
        at=moment(sequence), focus=FOCUS, duration_minutes=duration,
        examples=(
            DemonstratedBehavior(
                EventId(f"event:{source}"), moment(sequence - 1), FOCUS,
                (value["mentor"], value["mentee"]), repetitions,
            ),
        ),
        mentor_clarity=0.80, mentee_usefulness=0.60,
        mentor_trust_feedback=0.75, mentee_trust_feedback=0.25,
        mentee_profile=value["mentee_profile"],
        time_budget=MentorTimeBudget(value["mentor"], START, 60, 10),
    )
    value["ledger"] = ledger
    return ledger


class MentorshipSimulationTests(unittest.TestCase):
    def test_accepted_offer_activates_once_with_current_directed_trust_and_named_focus(self) -> None:
        value = active_scenario()
        ledger = value["ledger"]
        mentorship = value["mentorship"]
        self.assertEqual(mentorship.status, MentorshipStatus.ACTIVE)
        self.assertEqual(mentorship.accepted_at, value["offer"].responded_at)
        self.assertEqual(mentorship.source_event_id, value["offer"].source_event_id)
        self.assertEqual(mentorship.activation_trust_evidence_ids,
                         (EventId("event:primary-trust-forward"),))
        self.assertEqual(mentorship.focus_agreements[0].mentor_id, value["mentor"])
        self.assertEqual(mentorship.focus_agreements[0].mentee_id, value["mentee"])
        self.assertEqual(ledger.mentorships, (mentorship,))

        replay, same = activate_mentorship(
            value["social"], ledger,
            offer_id=str(value["offer"].offer_id), at=moment(6),
            actor_id=value["mentor"], focus_agreements=(value["agreement"],),
            mentor_capacity=value["capacity"], relationships=value["relationships"],
        )
        self.assertIs(replay, ledger)
        self.assertEqual(same, mentorship)
        self.assertEqual(loads(dumps(ledger), MentorshipLedger), ledger)

    def test_activation_rejects_consent_boundaries_missing_or_stale_trust(self) -> None:
        value = prepared_scenario()
        for at in (value["offer"].responded_at, moment(3), value["offer"].reservation_until):
            with self.subTest(at=at), self.assertRaisesRegex(ValueError, "consent window"):
                activate_mentorship(
                    value["social"], MentorshipLedger(),
                    offer_id=str(value["offer"].offer_id), at=at,
                    actor_id=value["mentor"], focus_agreements=(value["agreement"],),
                    mentor_capacity=value["capacity"], relationships=value["relationships"],
                )

        for edges in ((), (value["reverse"],)):
            with self.subTest(edge_count=len(edges)), self.assertRaisesRegex(ValueError, "directed trust"):
                activate_mentorship(
                    value["social"], MentorshipLedger(),
                    offer_id=str(value["offer"].offer_id), at=moment(6),
                    actor_id=value["mentor"], focus_agreements=(value["agreement"],),
                    mentor_capacity=value["capacity"], relationships=edges,
                )

        stale = prepared_scenario(suffix="stale", trust_age_days=MAX_MENTOR_TRUST_EVIDENCE_AGE_DAYS + 1)
        with self.assertRaisesRegex(ValueError, "current directed trust"):
            activate_mentorship(
                stale["social"], MentorshipLedger(),
                offer_id=str(stale["offer"].offer_id), at=moment(6),
                actor_id=stale["mentor"], focus_agreements=(stale["agreement"],),
                mentor_capacity=stale["capacity"], relationships=stale["relationships"],
            )
        same_moment = prepared_scenario(suffix="same-moment")
        same_time_edge = record_relationship_evidence(
            None, source_person_id=same_moment["mentor"], target_person_id=same_moment["mentee"],
            dimension=RelationshipDimension.TRUST, delta=0.0,
            event_id=EventId("event:same-moment-trust"), at=moment(6),
            direct_contact=True, initial_value=0.75,
        )
        with self.assertRaisesRegex(ValueError, "current directed trust"):
            activate_mentorship(
                same_moment["social"], MentorshipLedger(),
                offer_id=str(same_moment["offer"].offer_id), at=moment(6),
                actor_id=same_moment["mentor"], focus_agreements=(same_moment["agreement"],),
                mentor_capacity=same_moment["capacity"], relationships=(same_time_edge,),
            )

    def test_activation_rejects_future_or_below_threshold_trust_and_incompatible_focus(self) -> None:
        value = prepared_scenario()
        forward = value["forward"]
        low = record_relationship_evidence(
            None, source_person_id=value["mentor"], target_person_id=value["mentee"],
            dimension=RelationshipDimension.TRUST, delta=0.0,
            event_id=EventId("event:primary-trust-forward"), at=moment(2),
            direct_contact=True, initial_value=0.58,
        )
        low = record_relationship_evidence(
            low, source_person_id=value["mentor"], target_person_id=value["mentee"],
            dimension=RelationshipDimension.TRUST, delta=-0.05,
            event_id=EventId("event:primary-trust-falls"), at=moment(5), direct_contact=True,
        )
        for edge in (low,):
            with self.subTest(edge=edge), self.assertRaisesRegex(ValueError, "directed trust"):
                activate_mentorship(
                    value["social"], MentorshipLedger(),
                    offer_id=str(value["offer"].offer_id), at=moment(6),
                    actor_id=value["mentor"], focus_agreements=(value["agreement"],),
                    mentor_capacity=value["capacity"], relationships=tuple(sorted(
                        (edge, value["reverse"]),
                        key=lambda item: (str(item.source_person_id), str(item.target_person_id)),
                    )),
                )
        future = record_relationship_evidence(
            forward, source_person_id=value["mentor"], target_person_id=value["mentee"],
            dimension=RelationshipDimension.TRUST, delta=0.0,
            event_id=EventId("event:primary-future-trust"), at=moment(7),
            direct_contact=True,
        )
        with self.assertRaisesRegex(ValueError, "future evidence"):
            activate_mentorship(
                value["social"], MentorshipLedger(),
                offer_id=str(value["offer"].offer_id), at=moment(6),
                actor_id=value["mentor"], focus_agreements=(value["agreement"],),
                mentor_capacity=value["capacity"], relationships=tuple(sorted(
                    (future, value["reverse"]),
                    key=lambda item: (str(item.source_person_id), str(item.target_person_id)),
                )),
            )

        wrong_pair = replace(value["agreement"], mentee_id=PersonId("player:unrelated-person"))
        with self.assertRaisesRegex(ValueError, "accepted offer participants"):
            activate_mentorship(
                value["social"], MentorshipLedger(),
                offer_id=str(value["offer"].offer_id), at=moment(6),
                actor_id=value["mentor"], focus_agreements=(wrong_pair,),
                mentor_capacity=value["capacity"], relationships=value["relationships"],
            )
        with self.assertRaisesRegex(ValueError, "sufficient mentor competence"):
            replace(value["agreement"], mentor_competence=0.54)

    def test_declined_offer_and_full_capacity_cannot_activate(self) -> None:
        value = prepared_scenario(suffix="declined", receptivity=0.0)
        social, declined = value["social"], value["offer"]
        self.assertEqual(declined.status, OfferStatus.DECLINED)
        with self.assertRaisesRegex(ValueError, "accepted mentoring offer"):
            activate_mentorship(
                social, MentorshipLedger(), offer_id=str(declined.offer_id), at=moment(6),
                actor_id=value["mentor"], focus_agreements=(value["agreement"],),
                mentor_capacity=value["capacity"], relationships=value["relationships"],
            )

        active = active_scenario()
        other = prepared_scenario(suffix="other", mentee_index=2, slots=1)
        social = active["social"]
        second_session = replace(
            other["social"].sessions[0], at=moment(7),
        )
        # Rebuild the second opportunity inside the same social history.
        social = record_shared_session(social, second_session)
        opportunity = next(
            item for item in social.opportunities
            if item.source_event_id == second_session.event_id
        )
        mentor_disposition = SocialDisposition(active["mentor"], mentoring_willingness=0.95)
        other_disposition = SocialDisposition(other["mentee"], mentoring_interest=0.90,
                                              mentoring_receptivity=0.95)
        social, decision = propose_autonomous_offer(
            social, opportunity_id=opportunity.opportunity_id, kind=OfferKind.MENTORSHIP,
            initiator=mentor_disposition, recipient=other_disposition, at=moment(8),
            relationship=other["forward"], mentor_capacity=MentorCapacity(active["mentor"], 2),
        )
        self.assertIsNotNone(decision.offer)
        social, second_offer = respond_to_offer(
            social, offer_id=decision.offer.offer_id, recipient=other_disposition,
            at=moment(9), mentor_capacity=MentorCapacity(active["mentor"], 2),
        )
        agreement = replace(
            other["agreement"], assessed_at=moment(10),
        )
        with self.assertRaisesRegex(ValueError, "concurrent capacity"):
            activate_mentorship(
                social, active["ledger"], offer_id=str(second_offer.offer_id), at=moment(11),
                actor_id=active["mentor"], focus_agreements=(agreement,),
                mentor_capacity=MentorCapacity(active["mentor"], 1),
                relationships=other["relationships"],
            )
        paused_ledger, paused = pause_mentorship(
            active["ledger"], mentorship_id=active["mentorship"].mentorship_id,
            at=moment(12), actor_id=active["mentee"],
        )
        with self.assertRaisesRegex(ValueError, "concurrent capacity"):
            activate_mentorship(
                social, paused_ledger, offer_id=str(second_offer.offer_id), at=moment(11),
                actor_id=active["mentor"], focus_agreements=(agreement,),
                mentor_capacity=MentorCapacity(active["mentor"], 1),
                relationships=other["relationships"],
            )
        next_day_agreement = replace(agreement, assessed_at=moment(1, days=1))
        paused_ledger, second_mentorship = activate_mentorship(
            social, paused_ledger, offer_id=str(second_offer.offer_id),
            at=moment(2, days=1), actor_id=active["mentor"],
            focus_agreements=(next_day_agreement,),
            mentor_capacity=MentorCapacity(active["mentor"], 1),
            relationships=other["relationships"],
        )
        self.assertEqual(paused.status, MentorshipStatus.PAUSED)
        self.assertEqual(second_mentorship.status, MentorshipStatus.ACTIVE)
        with self.assertRaisesRegex(ValueError, "concurrent capacity"):
            resume_mentorship(
                social, paused_ledger, mentorship_id=paused.mentorship_id,
                at=moment(3, days=1), actor_id=active["mentor"],
                mentor_willing=True, mentee_willing=True,
                mentor_available=True, mentee_available=True,
                mentor_capacity=MentorCapacity(active["mentor"], 1),
            )

    def test_later_accepted_and_activated_mentorship_reserves_capacity_as_of_time(self) -> None:
        active = active_scenario(suffix="historical-reservation-a")
        capacity_three = MentorCapacity(active["mentor"], 3)

        def add_offer(social, other, *, session_at: int, proposed_at: int, answered_at: int):
            session = replace(other["social"].sessions[0], at=moment(session_at))
            social = record_shared_session(social, session)
            opportunity = next(
                item for item in social.opportunities
                if item.source_event_id == session.event_id
            )
            recipient = SocialDisposition(
                other["mentee"], mentoring_interest=0.90, mentoring_receptivity=0.95,
            )
            social, decision = propose_autonomous_offer(
                social, opportunity_id=opportunity.opportunity_id,
                kind=OfferKind.MENTORSHIP,
                initiator=SocialDisposition(active["mentor"], mentoring_willingness=0.95),
                recipient=recipient, at=moment(proposed_at),
                relationship=other["forward"], mentor_capacity=capacity_three,
            )
            if decision.offer is None:
                raise AssertionError("historical reservation fixture did not produce an offer")
            social, offer = respond_to_offer(
                social, offer_id=decision.offer.offer_id, recipient=recipient,
                at=moment(answered_at), mentor_capacity=capacity_three,
            )
            return social, offer

        future = prepared_scenario(suffix="historical-reservation-b", mentee_index=2)
        candidate = prepared_scenario(suffix="historical-reservation-c", mentee_index=3)
        social, future_offer = add_offer(
            active["social"], future, session_at=7, proposed_at=8, answered_at=9,
        )
        social, candidate_offer = add_offer(
            social, candidate, session_at=11, proposed_at=12, answered_at=13,
        )
        future_agreement = replace(future["agreement"], assessed_at=moment(10))
        ledger, future_mentorship = activate_mentorship(
            social, active["ledger"], offer_id=str(future_offer.offer_id), at=moment(20),
            actor_id=active["mentor"], focus_agreements=(future_agreement,),
            mentor_capacity=capacity_three, relationships=future["relationships"],
        )
        self.assertEqual(future_mentorship.started_at, moment(20))

        with self.assertRaisesRegex(ValueError, "concurrent capacity"):
            activate_mentorship(
                social, ledger, offer_id=str(candidate_offer.offer_id), at=moment(15),
                actor_id=active["mentor"],
                focus_agreements=(replace(candidate["agreement"], assessed_at=moment(14)),),
                mentor_capacity=MentorCapacity(active["mentor"], 2),
                relationships=candidate["relationships"],
            )

    def test_pause_resume_end_are_audited_and_resume_rechecks_consent_and_capacity(self) -> None:
        value = active_scenario()
        ledger, mentorship = pause_mentorship(
            value["ledger"], mentorship_id=value["mentorship"].mentorship_id,
            at=moment(7), actor_id=value["mentee"],
        )
        self.assertEqual(mentorship.status, MentorshipStatus.PAUSED)
        self.assertIs(pause_mentorship(
            ledger, mentorship_id=mentorship.mentorship_id, at=moment(7),
            actor_id=value["mentee"],
        )[0], ledger)
        with self.assertRaisesRegex(ValueError, "active mentorship"):
            record_contact(value | {"ledger": ledger, "mentorship": mentorship}, sequence=8)

        args = dict(
            social=value["social"], ledger=ledger, mentorship_id=mentorship.mentorship_id,
            at=moment(8), actor_id=value["mentor"],
            mentor_willing=True, mentee_willing=True,
            mentor_available=True, mentee_available=True,
            mentor_capacity=MentorCapacity(value["mentor"], 1, external_commitments=1),
        )
        with self.assertRaisesRegex(ValueError, "concurrent capacity"):
            resume_mentorship(**args)
        with self.assertRaisesRegex(ValueError, "willing and available"):
            resume_mentorship(**(args | {"mentor_capacity": value["capacity"], "mentee_willing": False}))
        ledger, mentorship = resume_mentorship(**(args | {"mentor_capacity": value["capacity"]}))
        self.assertEqual(mentorship.status, MentorshipStatus.ACTIVE)
        replay, same = resume_mentorship(**(
            args | {
                "ledger": ledger,
                "mentor_willing": False,
                "mentor_capacity": MentorCapacity(value["mentor"], 1, external_commitments=1),
            }
        ))
        self.assertIs(replay, ledger)
        self.assertEqual(same, mentorship)
        ledger, mentorship = pause_mentorship(
            ledger, mentorship_id=mentorship.mentorship_id, at=moment(9), actor_id=value["mentor"],
        )
        ledger, mentorship = resume_mentorship(
            value["social"], ledger, mentorship_id=mentorship.mentorship_id, at=moment(10),
            actor_id=value["mentee"], mentor_willing=True, mentee_willing=True,
            mentor_available=True, mentee_available=True, mentor_capacity=value["capacity"],
        )
        ledger, mentorship = end_mentorship(
            ledger, mentorship_id=mentorship.mentorship_id, at=moment(11),
            actor_id=value["mentor"], reason="both-finished",
        )
        self.assertEqual(mentorship.status, MentorshipStatus.ENDED)
        self.assertEqual([item.action for item in mentorship.transitions], [
            MentorshipAction.ACTIVATE, MentorshipAction.PAUSE, MentorshipAction.RESUME,
            MentorshipAction.PAUSE, MentorshipAction.RESUME, MentorshipAction.END,
        ])
        with self.assertRaisesRegex(ValueError, "willing and available"):
            resume_mentorship(
                value["social"], ledger, mentorship_id=mentorship.mentorship_id, at=moment(12),
                actor_id=value["mentor"], mentor_willing=True, mentee_willing=True,
                mentor_available=False, mentee_available=True, mentor_capacity=value["capacity"],
            )

    def test_contact_requires_focus_demonstration_and_finite_mentor_time(self) -> None:
        value = active_scenario()
        with self.assertRaisesRegex(ValueError, "remaining mentor time"):
            record_mentorship_contact(
                value["ledger"], mentorship_id=value["mentorship"].mentorship_id,
                contact_id=EventId("event:overbudget-contact"), at=moment(8), focus=FOCUS,
                duration_minutes=31,
                examples=(DemonstratedBehavior(
                    EventId("event:overbudget-demonstration"), moment(7), FOCUS,
                    (value["mentor"], value["mentee"]), 10,
                ),), mentor_clarity=0.8, mentee_usefulness=0.6,
                mentor_trust_feedback=0.5, mentee_trust_feedback=0.5,
                mentee_profile=value["mentee_profile"],
                time_budget=MentorTimeBudget(value["mentor"], START, 40, 10),
            )
        with self.assertRaisesRegex(TypeError, "demonstrated examples"):
            record_mentorship_contact(
                value["ledger"], mentorship_id=value["mentorship"].mentorship_id,
                contact_id=EventId("event:no-demonstration-contact"), at=moment(8), focus=FOCUS,
                duration_minutes=20, examples=(),
                mentor_clarity=0.8, mentee_usefulness=0.6,
                mentor_trust_feedback=0.5, mentee_trust_feedback=0.5,
                mentee_profile=value["mentee_profile"],
                time_budget=MentorTimeBudget(value["mentor"], START, 60, 10),
            )

    def test_contact_creates_once_only_focus_learning_and_directional_trust_feedback(self) -> None:
        value = active_scenario()
        profile_before = value["mentee_profile"]
        ledger = record_contact(value)
        contact = ledger.contacts[0]
        learning = ledger.focus_learning[0]
        receipt = learning.receipts[0]
        expected = min(
            0.05,
            round(contact.meaningful_repetitions * BASE_FOCUS_LEARNING_PER_REPETITION
                  * (0.5 + contact.learner_adaptability) * 0.60, 8),
        )
        self.assertAlmostEqual(receipt.gain, expected)
        self.assertEqual(receipt.example_event_ids, (EventId("event:demonstration-1"),))
        self.assertEqual(learning.value, receipt.gain)
        self.assertEqual(value["mentee_profile"], profile_before)
        self.assertIsNot(learning, value["mentee_profile"].capabilities)

        edges = {(edge.source_person_id, edge.target_person_id): edge for edge in ledger.relationships}
        forward = edges[(value["mentor"], value["mentee"])]
        reverse = edges[(value["mentee"], value["mentor"])]
        self.assertAlmostEqual(float(forward.dimensions[0].value), 0.755)
        self.assertAlmostEqual(float(reverse.dimensions[0].value), 0.645)
        self.assertTrue(forward.evidence[-1].direct_contact)
        self.assertTrue(reverse.evidence[-1].direct_contact)

        replay = record_mentorship_contact(
            ledger, mentorship_id=value["mentorship"].mentorship_id,
            contact_id=contact.contact_id, at=contact.at, focus=contact.focus,
            duration_minutes=contact.duration_minutes, examples=contact.examples,
            mentor_clarity=contact.mentor_clarity, mentee_usefulness=contact.mentee_usefulness,
            mentor_trust_feedback=contact.mentor_trust_feedback,
            mentee_trust_feedback=contact.mentee_trust_feedback,
            mentee_profile=value["mentee_profile"], time_budget=contact.time_budget,
        )
        self.assertIs(replay, ledger)
        with self.assertRaisesRegex(ValueError, "conflicting content"):
            record_mentorship_contact(
                ledger, mentorship_id=value["mentorship"].mentorship_id,
                contact_id=contact.contact_id, at=contact.at, focus=contact.focus,
                duration_minutes=contact.duration_minutes + 1, examples=contact.examples,
                mentor_clarity=contact.mentor_clarity, mentee_usefulness=contact.mentee_usefulness,
                mentor_trust_feedback=contact.mentor_trust_feedback,
                mentee_trust_feedback=contact.mentee_trust_feedback,
                mentee_profile=value["mentee_profile"], time_budget=contact.time_budget,
            )

    def test_reused_demonstration_id_is_rejected_and_absent_reverse_edge_stays_absent(self) -> None:
        value = active_scenario()
        ledger = record_contact(value)
        with self.assertRaisesRegex(ValueError, "reused"):
            record_mentorship_contact(
                ledger, mentorship_id=value["mentorship"].mentorship_id,
                contact_id=EventId("event:demonstration-2-contact"), at=moment(10), focus=FOCUS,
                duration_minutes=20,
                examples=ledger.contacts[0].examples,
                mentor_clarity=0.8, mentee_usefulness=0.6,
                mentor_trust_feedback=1.0, mentee_trust_feedback=1.0,
                mentee_profile=value["mentee_profile"],
                time_budget=ledger.contacts[0].time_budget,
            )

        one_way = prepared_scenario(suffix="oneway")
        one_way["ledger"], one_way["mentorship"] = activate_mentorship(
            one_way["social"], MentorshipLedger(), offer_id=str(one_way["offer"].offer_id),
            at=moment(6), actor_id=one_way["mentor"], focus_agreements=(one_way["agreement"],),
            mentor_capacity=one_way["capacity"], relationships=(one_way["forward"],),
        )
        record_contact(one_way)
        self.assertEqual(len(one_way["ledger"].relationships), 1)
        self.assertEqual(one_way["ledger"].relationships[0].source_person_id, one_way["mentor"])

    def test_reviews_are_read_only_as_of_snapshots_and_replay_after_later_contacts(self) -> None:
        value = active_scenario()
        ledger = value["ledger"]
        ledger, no_contact = record_mentorship_review(
            ledger, mentorship_id=value["mentorship"].mentorship_id, at=moment(7),
        )
        self.assertTrue(no_contact.no_contact)
        self.assertEqual(no_contact.contact_ids, ())
        self.assertEqual(no_contact.focus_progress[0].contact_count, 0)
        self.assertIsNone(no_contact.focus_progress[0].mean_mutual_utility)
        before_view = dumps(ledger)
        repeated_ledger, repeated = record_mentorship_review(
            ledger, mentorship_id=value["mentorship"].mentorship_id, at=moment(7),
        )
        self.assertIs(repeated_ledger, ledger)
        self.assertEqual(repeated, no_contact)
        self.assertEqual(dumps(ledger), before_view)

        value["ledger"] = ledger
        ledger = record_contact(value, sequence=8)
        ledger, after_first = record_mentorship_review(
            ledger, mentorship_id=value["mentorship"].mentorship_id, at=moment(9),
        )
        self.assertEqual(after_first.contact_ids, (ledger.contacts[0].contact_id,))
        self.assertEqual(after_first.focus_progress[0].contact_count, 1)
        value["ledger"] = ledger
        ledger = record_contact(value, sequence=11, source="demonstration-2", repetitions=8)
        replayed, same_old_review = record_mentorship_review(
            ledger, mentorship_id=value["mentorship"].mentorship_id, at=moment(9),
        )
        self.assertIs(replayed, ledger)
        self.assertEqual(same_old_review, after_first)
        self.assertEqual(len(ledger.reviews), 2)
        self.assertEqual(ledger.reviews[1].contact_ids, (ledger.contacts[0].contact_id,))
        forward = next(edge for edge in ledger.relationships
                       if edge.source_person_id == value["mentor"]
                       and edge.target_person_id == value["mentee"])
        latest_as_of = [item.event_id for item in forward.evidence if item.at <= moment(9)][-1]
        self.assertEqual(ledger.reviews[1].trust_snapshots[0].evidence_event_ids[-1], latest_as_of)

    def test_daily_time_budget_is_mentor_wide_across_programs(self) -> None:
        value = active_scenario()
        ledger = record_contact(value, duration=30)
        second = active_scenario(suffix="second", mentee_index=2, slots=2)
        social = record_shared_session(
            value["social"], replace(second["social"].sessions[0], at=moment(9))
        )
        opportunity = next(item for item in social.opportunities
                           if item.source_event_id == EventId("event:second-session"))
        disposition = SocialDisposition(second["mentee"], mentoring_interest=0.9,
                                        mentoring_receptivity=0.95)
        social, decision = propose_autonomous_offer(
            social, opportunity_id=opportunity.opportunity_id, kind=OfferKind.MENTORSHIP,
            initiator=SocialDisposition(value["mentor"], mentoring_willingness=0.95),
            recipient=disposition, at=moment(10), relationship=second["forward"],
            mentor_capacity=MentorCapacity(value["mentor"], 2),
        )
        social, offer = respond_to_offer(
            social, offer_id=decision.offer.offer_id, recipient=disposition, at=moment(11),
            mentor_capacity=MentorCapacity(value["mentor"], 2),
        )
        second_ledger, second_mentorship = activate_mentorship(
            social, ledger, offer_id=str(offer.offer_id), at=moment(13),
            actor_id=value["mentor"],
            focus_agreements=(replace(second["agreement"], assessed_at=moment(12)),),
            mentor_capacity=MentorCapacity(value["mentor"], 2),
            relationships=second["relationships"],
        )
        with self.assertRaisesRegex(ValueError, "same time-budget snapshot"):
            record_mentorship_contact(
                second_ledger, mentorship_id=second_mentorship.mentorship_id,
                contact_id=EventId("event:second-program-contact"), at=moment(15), focus=FOCUS,
                duration_minutes=25,
                examples=(DemonstratedBehavior(
                    EventId("event:second-program-demonstration"), moment(14), FOCUS,
                    (value["mentor"], second["mentee"]), 10,
                ),),
                mentor_clarity=0.8, mentee_usefulness=0.8,
                mentor_trust_feedback=0.5, mentee_trust_feedback=0.5,
                mentee_profile=second["mentee_profile"],
                time_budget=MentorTimeBudget(value["mentor"], START, 60, 5),
            )

    def test_versioned_codec_rejects_tampered_learning_formula(self) -> None:
        value = active_scenario()
        activation_payload = json.loads(dumps(value["ledger"]))
        activation_payload["payload"]["mentorships"][0]["activation_trust_evidence_ids"] = [
            "event:forged-activation-trust"
        ]
        with self.assertRaises(SerializationError):
            loads(json.dumps(activation_payload), MentorshipLedger)
        ledger = record_contact(value)
        encoded = dumps(ledger)
        self.assertEqual(loads(encoded, MentorshipLedger), ledger)
        payload = json.loads(encoded)
        payload["payload"]["focus_learning"][0]["receipts"][0]["formula_version"] = "unknown"
        with self.assertRaises(SerializationError):
            loads(json.dumps(payload), MentorshipLedger)
        payload = json.loads(encoded)
        payload["schema_version"] = 99
        with self.assertRaises(SerializationError):
            loads(json.dumps(payload), MentorshipLedger)

    def test_domain_import_is_headless_and_probe_replays_byte_for_byte(self) -> None:
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        script = r'''
import builtins, importlib, io, pathlib, sys
def blocked(*args, **kwargs): raise AssertionError("domain import performed file I/O")
builtins.open = blocked
io.open = blocked
pathlib.Path.open = blocked
importlib.import_module("games.touchline.esb.people.mentorship")
assert "curses" not in sys.modules
assert "termstation_ui" not in sys.modules
assert not any(name.startswith("termstation.") for name in sys.modules)
'''
        subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=env,
                       capture_output=True, text=True, check=True)
        command = [sys.executable, "-m", "games.touchline.checks.mentorship_probe"]
        first = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, check=True)
        second = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, check=True)
        self.assertEqual(first.stdout, second.stdout)
        self.assertIn('"contact_count":1', first.stdout)


if __name__ == "__main__":
    unittest.main()
