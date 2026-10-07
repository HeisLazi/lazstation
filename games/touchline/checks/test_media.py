"""Mechanism tests for P14 source-limited media and exact transcripts."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

from games.touchline.checks.governance_probe import START as GOVERNANCE_START
from games.touchline.esb.club.governance import (
    Appointment,
    AuthorityAction,
    AuthorityGrant,
    AuthorityPolicy,
    BudgetBook,
    ClubGovernance,
    ClubRole,
    DecisionOutcome,
    StaffFunction,
    StaffProfile,
    StaffTask,
    StaffTaskAssignment,
    add_staff_appointment,
    add_staff_member,
    assign_staff_task,
    create_staff_task,
)
from games.touchline.esb.events import EventEnvelope
from games.touchline.esb.ids import ClubId, EventId, MatchId
from games.touchline.esb.media.publication import (
    AwarenessReceipt,
    AwarenessRoute,
    EditorialFrame,
    EventWorldMoment,
    MatchMediaSource,
    MatchPlayerClub,
    MediaLedger,
    MediaStoryId,
    MediaStoryId,
    Outlet,
    OutletTier,
    PublicFactKind,
    PublicReasonCode,
    Repost,
    StatementClassification,
    TranscriptAnnotation,
    publish_story,
    record_person_awareness,
    record_repost,
    record_transcript,
)
from games.touchline.esb.people.relationships import (
    AwarenessBasis,
    PersonalDimension,
    PersonalHistory,
    PersonalState,
    PersonalStateValue,
    PersonId,
    WorldMoment,
)
from games.touchline.esb.serialization import dumps, loads
from games.touchline.esb.time import WorldDate

REPO_ROOT = Path(__file__).resolve().parents[3]
MATCH_ID = MatchId("match:p14-test")
HOME_CLUB = ClubId("club:p12-probe")
AWAY_CLUB = ClubId("club:p14-away")
SCORER = "player:p14-scorer"
ASSIST = "player:p14-assist"
AWAY_PLAYER = "player:p14-away-defender"
START = WorldDate(date(2026, 10, 5))


def moment(sequence: int, days: int = 0) -> WorldMoment:
    return WorldMoment(WorldDate(START.day + timedelta(days=days)), sequence)


def encoded(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def match_event(
    event_id: str,
    sequence: int,
    tick: int,
    kind: str = "goal",
    payload: dict[str, object] | None = None,
    outcome: dict[str, object] | None = None,
) -> EventEnvelope:
    return EventEnvelope(
        EventId(event_id), "match", str(MATCH_ID), sequence, kind,
        MATCH_ID, tick, payload_json=encoded(payload or {}),
        outcome_json=encoded(outcome or {"home_score": 1, "away_score": 0}),
    )


def goal_source(
    *,
    payload: dict[str, object] | None = None,
    event_kind: str = "goal",
    event_id: str = "event:p14-goal",
) -> MatchMediaSource:
    event = match_event(
        event_id,
        1,
        120,
        event_kind,
        payload or {
            "actor_id": SCORER,
            "assist_player_id": ASSIST,
            "team_id": "home",
            "scoring_team_id": "home",
            "private_tracking_value": "private-match-note",
        },
        {"home_score": 1, "away_score": 0, "private_model_field": "hidden-outcome"},
    )
    players = tuple(sorted((
        MatchPlayerClub(SCORER, "home", HOME_CLUB),
        MatchPlayerClub(ASSIST, "home", HOME_CLUB),
        MatchPlayerClub(AWAY_PLAYER, "away", AWAY_CLUB),
    ), key=lambda item: item.person_id))
    return MatchMediaSource(
        MATCH_ID,
        HOME_CLUB,
        AWAY_CLUB,
        players,
        (event,),
        (EventWorldMoment(event.event_id, moment(1)),),
        EventId("event:p14-calendar-fixture"),
    )


def outlet(
    outlet_id: str,
    tier: OutletTier,
    clubs: tuple[ClubId, ...] = (HOME_CLUB,),
    audience: int = 100_000,
) -> Outlet:
    return Outlet(
        outlet_id,
        f"Synthetic {tier.value} outlet",
        tier,
        tuple(sorted(clubs, key=str)),
        audience,
    )


def fresh_history(person_id: str = SCORER) -> PersonalHistory:
    person = PersonId(person_id)
    return PersonalHistory(
        person,
        PersonalState(
            person,
            tuple(PersonalStateValue(dimension, 0.5)
                  for dimension in sorted(PersonalDimension, key=lambda item: item.value)),
        ),
    )


def story_for(
    source: MatchMediaSource,
    media: MediaLedger,
    outlet_id: str = "outlet:p14-local",
    frame: EditorialFrame = EditorialFrame.STRAIGHT,
    published: WorldMoment | None = None,
):
    return publish_story(
        media,
        source,
        source_event_id=source.events[0].event_id,
        outlet_id=outlet_id,
        published_at=published or moment(10),
        frame=frame,
    )


def awareness_receipt(
    story_id: str,
    *,
    person_id: str = SCORER,
    source_event_id: EventId = EventId("event:p14-goal"),
    receipt_id: str = "event:p14-read",
    route: AwarenessRoute = AwarenessRoute.STORY_READ,
    at: WorldMoment | None = None,
) -> AwarenessReceipt:
    story = str(story_id)
    when = at or moment(11)
    kind = {
        AwarenessRoute.STORY_READ: "media_story_read",
        AwarenessRoute.PRESS_BRIEFING: "media_press_briefing",
        AwarenessRoute.REPORTED_RUMOUR: "media_story_rumoured",
    }[route]
    event = EventEnvelope(
        EventId(receipt_id), "media_story", story, 1, kind,
        world_date=when.on,
        cause_event_id=source_event_id,
        parent_event_id=EventId(story),
        payload_json=encoded({"actor_id": person_id, "story_id": story}),
    )
    return AwarenessReceipt(event, person_id, MediaStoryId(story), when, route)


def governance_with_media_staff(*, capacity: int = 2, expires_after_day: int = 2) -> ClubGovernance:
    manager_id = "appointment:p14-manager"
    manager = Appointment(
        manager_id,
        HOME_CLUB,
        "person:p14-manager",
        ClubRole.MANAGER,
        GOVERNANCE_START,
        None,
        (
            AuthorityGrant(AuthorityAction.APPOINT_STAFF),
            AuthorityGrant(AuthorityAction.REGISTER_STAFF),
            AuthorityGrant(AuthorityAction.CREATE_TASK),
            AuthorityGrant(AuthorityAction.ASSIGN_TASK),
        ),
    )
    base = ClubGovernance(
        HOME_CLUB,
        AuthorityPolicy(HOME_CLUB),
        BudgetBook(HOME_CLUB, "NAD", 50_000),
        appointments=(manager,),
    )
    appointment_id = "appointment:p14-media-officer"
    staff_id = "person:p14-media-officer"
    staff_appointment = Appointment(
        appointment_id,
        HOME_CLUB,
        staff_id,
        ClubRole.STAFF,
        GOVERNANCE_START,
        WorldDate(GOVERNANCE_START.day + timedelta(days=expires_after_day)),
        (),
        manager_id,
    )
    profile = StaffProfile(
        staff_id, HOME_CLUB, appointment_id, (StaffFunction.MEDIA,), capacity,
    )
    task = StaffTask(
        "task:p14-media-briefing", HOME_CLUB, StaffFunction.MEDIA,
        WorldDate(GOVERNANCE_START.day + timedelta(days=1)), 1,
        "Prepare the post-match response",
    )
    assignment = StaffTaskAssignment(
        "assignment:p14-media-briefing", task.task_id, staff_id,
        manager_id,
        WorldDate(GOVERNANCE_START.day + timedelta(days=1)), 1,
    )
    appointed = add_staff_appointment(base, manager_id, staff_appointment, GOVERNANCE_START)
    if not appointed.accepted:
        raise AssertionError(appointed.rejection)
    registered = add_staff_member(appointed.state, manager_id, profile, GOVERNANCE_START)
    if not registered.accepted:
        raise AssertionError(registered.rejection)
    task_created = create_staff_task(registered.state, manager_id, task, GOVERNANCE_START)
    if not task_created.accepted:
        raise AssertionError(task_created.rejection)
    assigned = assign_staff_task(task_created.state, manager_id, assignment, GOVERNANCE_START)
    if not assigned.accepted:
        raise AssertionError(assigned.rejection)
    return assigned.state


class MediaSourceTests(unittest.TestCase):
    def test_goal_projection_keeps_chronology_lineage_and_hides_unrelated_fields(self) -> None:
        source = goal_source()
        media = MediaLedger((outlet("outlet:p14-local", OutletTier.LOCAL),))
        updated, story = story_for(source, media)

        self.assertEqual(story.source_event_id, source.events[0].event_id)
        self.assertEqual(story.source_sequence, 1)
        self.assertEqual(story.source_tick, 120)
        self.assertEqual(story.occurred_at, moment(1))
        self.assertEqual(story.calendar_evidence_id, EventId("event:p14-calendar-fixture"))
        self.assertIs(story.fact.kind, PublicFactKind.GOAL)
        self.assertEqual(story.fact.subject_ids, (SCORER, ASSIST))
        self.assertEqual((story.fact.home_score, story.fact.away_score), (1, 0))
        record = dumps(updated)
        self.assertNotIn("private-match-note", record)
        self.assertNotIn("hidden-outcome", record)
        self.assertNotIn("private_tracking_value", record)
        self.assertNotIn("private_model_field", record)
        replayed, same_story = story_for(source, updated)
        self.assertEqual(replayed, updated)
        self.assertEqual(same_story, story)
        with self.assertRaisesRegex(ValueError, "does not match its source event and outlet"):
            replace(story, story_id=MediaStoryId("media-story:wrong"))

    def test_unknown_kinds_and_mismatched_player_lineage_are_rejected(self) -> None:
        unknown = goal_source(event_kind="private_medical_update")
        media = MediaLedger((outlet("outlet:p14-local", OutletTier.LOCAL),))
        with self.assertRaisesRegex(ValueError, "unsupported public match event kind"):
            story_for(unknown, media)

        wrong_player = goal_source(payload={
            "actor_id": "player:not-on-roster",
            "scoring_team_id": "home",
        })
        with self.assertRaisesRegex(ValueError, "outside the match roster"):
            story_for(wrong_player, media)

    def test_goal_scorer_assist_and_own_goal_side_must_reconcile(self) -> None:
        media = MediaLedger((outlet("outlet:p14-local", OutletTier.LOCAL),))
        contradictory = goal_source(payload={
            "actor_id": SCORER,
            "assist_player_id": ASSIST,
            "scoring_team_id": "away",
        })
        with self.assertRaisesRegex(ValueError, "conflicts with the scoring team"):
            story_for(contradictory, media)

        mixed_subjects = goal_source(payload={
            "actor_id": SCORER,
            "own_goal_player_id": AWAY_PLAYER,
            "scoring_team_id": "home",
        })
        with self.assertRaisesRegex(ValueError, "both a scorer and an own-goal player"):
            story_for(mixed_subjects, media)

        own_goal = goal_source(payload={
            "actor_id": None,
            "own_goal_player_id": AWAY_PLAYER,
            "scoring_team_id": "home",
            "last_touch_team_id": "away",
        })
        updated, story = story_for(own_goal, media)
        self.assertEqual(story.fact.subject_ids, (AWAY_PLAYER,))
        self.assertEqual(story.fact.club_ids, tuple(sorted((HOME_CLUB, AWAY_CLUB), key=str)))
        self.assertEqual(len(updated.stories), 1)

    def test_match_world_moments_follow_event_tick_and_sequence_order(self) -> None:
        source = goal_source()
        goal = source.events[0]
        finished = match_event(
            "event:p14-match-finished", 2, 240, "match_finished", {"reason": "full_time"},
        )
        with self.assertRaisesRegex(ValueError, "increase with match chronology"):
            MatchMediaSource(
                source.match_id,
                source.home_club_id,
                source.away_club_id,
                source.players,
                (goal, finished),
                (EventWorldMoment(goal.event_id, moment(2)),
                 EventWorldMoment(finished.event_id, moment(1))),
                source.calendar_evidence_id,
            )

    def test_supported_non_goal_facts_have_kind_specific_validated_projection(self) -> None:
        fixtures = (
            ("player_sent_off", {"actor_id": AWAY_PLAYER, "team_id": "away", "reason": "direct_red_card"},
             PublicFactKind.PLAYER_SENT_OFF),
            ("substitution", {"actor_id": ASSIST, "incoming_player_id": ASSIST,
                               "outgoing_player_id": SCORER, "team_id": "home"},
             PublicFactKind.SUBSTITUTION),
            ("match_finished", {"reason": "full_time"}, PublicFactKind.MATCH_FINISHED),
            ("match_abandoned", {"reason": "weather"}, PublicFactKind.MATCH_ABANDONED),
        )
        for kind, payload, public_kind in fixtures:
            with self.subTest(kind=kind):
                source = goal_source(payload=payload, event_kind=kind, event_id=f"event:p14-{kind}")
                if kind == "player_sent_off":
                    source_outlet = outlet("outlet:p14-away-local", OutletTier.LOCAL, (AWAY_CLUB,))
                elif kind == "substitution":
                    source_outlet = outlet("outlet:p14-home-local", OutletTier.LOCAL)
                else:
                    source_outlet = outlet(
                        "outlet:p14-regional", OutletTier.REGIONAL, (HOME_CLUB, AWAY_CLUB),
                    )
                media = MediaLedger((source_outlet,))
                updated, story = story_for(source, media, str(source_outlet.outlet_id))
                self.assertIs(story.fact.kind, public_kind)
                self.assertIn(story.fact.club_ids[0], (HOME_CLUB, AWAY_CLUB))
                self.assertEqual(len(updated.stories), 1)

    def test_unclassified_private_reason_strings_are_not_projected(self) -> None:
        source = goal_source(payload={
            "actor_id": AWAY_PLAYER,
            "team_id": "away",
            "reason": "private-player-disciplinary-detail",
        }, event_kind="player_sent_off")
        media = MediaLedger((outlet("outlet:p14-away-local", OutletTier.LOCAL, (AWAY_CLUB,)),))
        with self.assertRaisesRegex(ValueError, "not an allowed public code"):
            story_for(source, media, "outlet:p14-away-local")

        allowed = goal_source(payload={
            "actor_id": AWAY_PLAYER,
            "team_id": "away",
            "reason": "second_yellow",
        }, event_kind="player_sent_off")
        published, story = story_for(allowed, media, "outlet:p14-away-local")
        self.assertIs(story.fact.reason_code, PublicReasonCode.SECOND_YELLOW)
        self.assertEqual(len(published.stories), 1)

    def test_tier_scales_modeled_reach_and_story_identity_rejects_changed_replay(self) -> None:
        source = goal_source()
        local = outlet("outlet:p14-local", OutletTier.LOCAL)
        elite = outlet("outlet:p14-elite", OutletTier.ELITE, (HOME_CLUB, AWAY_CLUB))
        media = MediaLedger(tuple(sorted((local, elite), key=lambda item: str(item.outlet_id))))
        after_local, local_story = story_for(source, media)
        after_elite, elite_story = story_for(source, after_local, "outlet:p14-elite")
        self.assertEqual(local_story.modeled_reach, 20_000)
        self.assertEqual(elite_story.modeled_reach, 85_000)
        self.assertLess(local_story.modeled_reach, elite_story.modeled_reach)
        self.assertEqual(local_story.formula_version, "p14-modeled-reach-v1")

        _, provocative = story_for(
            source,
            MediaLedger((local,)),
            frame=EditorialFrame.PROVOCATIVE,
        )
        self.assertEqual(provocative.modeled_reach, 25_000)
        with self.assertRaisesRegex(ValueError, "conflicting content"):
            story_for(source, after_local, published=moment(12))


class MediaEffectTests(unittest.TestCase):
    def test_reposts_are_idempotent_and_do_not_create_personal_effects(self) -> None:
        source = goal_source()
        media = MediaLedger(
            (outlet("outlet:p14-local", OutletTier.LOCAL),),
            personal_histories=(fresh_history(),),
        )
        media, story = story_for(source, media)
        repost = Repost(
            "media-repost:p14-one", story.story_id, "account:p14-fan", moment(12), 7_500,
        )
        once = record_repost(media, repost)
        self.assertIs(record_repost(once, repost), once)
        self.assertEqual(once.personal_histories, media.personal_histories)
        self.assertEqual(once.awareness, ())
        with self.assertRaisesRegex(ValueError, "conflicting content"):
            record_repost(once, replace(repost, additional_impressions=8_000))

    def test_only_explicit_awareness_creates_one_pending_p13_experience(self) -> None:
        source = goal_source()
        media = MediaLedger(
            (outlet("outlet:p14-local", OutletTier.LOCAL),),
            personal_histories=(fresh_history(),),
        )
        media, story = story_for(source, media)
        initial = media.personal_histories[0]
        self.assertEqual(initial.experiences, ())  # aggregate reach alone is not awareness
        receipt = awareness_receipt(str(story.story_id))
        once = record_person_awareness(media, receipt)
        history = once.personal_histories[0]
        self.assertEqual(len(once.awareness), 1)
        self.assertEqual(len(history.experiences), 1)
        experience = history.experiences[0]
        self.assertEqual(experience.cause_event_id, story.source_event_id)
        self.assertIs(experience.awareness, AwarenessBasis.REPORTED)
        self.assertIsNone(experience.appraisal)
        self.assertEqual(history.state, initial.state)
        self.assertEqual(record_person_awareness(once, receipt), once)

        elite = outlet("outlet:p14-elite", OutletTier.ELITE, (HOME_CLUB, AWAY_CLUB))
        expanded = replace(once, outlets=tuple(sorted(
            once.outlets + (elite,), key=lambda item: str(item.outlet_id),
        )))
        both, other_story = story_for(source, expanded, "outlet:p14-elite")
        repeated = awareness_receipt(
            str(other_story.story_id), receipt_id="event:p14-read-elite",
        )
        after_repeated = record_person_awareness(both, repeated)
        self.assertEqual(after_repeated, both)
        self.assertEqual(len(after_repeated.personal_histories[0].experiences), 1)

    def test_awareness_requires_subject_story_and_match_cause_lineage(self) -> None:
        source = goal_source()
        media = MediaLedger(
            (outlet("outlet:p14-local", OutletTier.LOCAL),),
            personal_histories=(fresh_history(),),
        )
        media, story = story_for(source, media)
        with self.assertRaisesRegex(ValueError, "subject named"):
            record_person_awareness(
                media,
                awareness_receipt(str(story.story_id), person_id=AWAY_PLAYER,
                                  receipt_id="event:p14-away-read"),
            )
        with self.assertRaisesRegex(ValueError, "as its cause"):
            record_person_awareness(
                media,
                awareness_receipt(str(story.story_id), source_event_id=EventId("event:other"),
                                  receipt_id="event:p14-wrong-cause"),
            )


class TranscriptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = goal_source()
        self.media = MediaLedger((outlet("outlet:p14-local", OutletTier.LOCAL),))
        self.media, self.story = story_for(self.source, self.media)
        self.governance = governance_with_media_staff()

    def test_direct_manager_keeps_exact_negation_and_conditional_spans(self) -> None:
        words = "I will not promise a sale. If we are promoted, I will review my contract."
        denial = "I will not promise a sale."
        conditional = "If we are promoted, I will review my contract."
        annotations = (
            TranscriptAnnotation(0, len(denial), denial, StatementClassification.DENIAL,
                                 "appointment:p14-manager"),
            TranscriptAnnotation(len(denial) + 1, len(words), conditional,
                                 StatementClassification.CONDITIONAL,
                                 "appointment:p14-manager"),
        )
        updated, transcript = record_transcript(
            self.media,
            self.governance,
            transcript_id=EventId("event:p14-transcript-manager"),
            story_id=self.story.story_id,
            author_appointment_id="appointment:p14-manager",
            at=moment(20, 1),
            exact_words=words,
            annotations=annotations,
        )
        self.assertEqual(transcript.exact_words, words)
        self.assertEqual([item.quoted_text for item in transcript.annotations], [denial, conditional])
        self.assertEqual([item.classification for item in transcript.annotations], [
            StatementClassification.DENIAL, StatementClassification.CONDITIONAL,
        ])
        self.assertIs(record_transcript(
            updated,
            self.governance,
            transcript_id=transcript.transcript_id,
            story_id=self.story.story_id,
            author_appointment_id="appointment:p14-manager",
            at=moment(20, 1),
            exact_words=words,
            annotations=annotations,
        )[0], updated)

    def test_delegated_response_cites_active_p12_media_assignment(self) -> None:
        governance = governance_with_media_staff()
        updated, transcript = record_transcript(
            self.media,
            governance,
            transcript_id=EventId("event:p14-transcript-staff"),
            story_id=self.story.story_id,
            author_appointment_id="appointment:p14-media-officer",
            at=moment(20, 1),
            exact_words="The manager asked us to confirm the timeline.",
            task_assignment_id="assignment:p14-media-briefing",
        )
        self.assertEqual(transcript.staff_id, "person:p14-media-officer")
        self.assertEqual(transcript.task_assignment_id, "assignment:p14-media-briefing")
        self.assertEqual(transcript.assigned_by_appointment_id, "appointment:p14-manager")
        self.assertEqual(governance.assignments[0].assignment_id, transcript.task_assignment_id)
        self.assertEqual(len(updated.transcripts), 1)
        with self.assertRaisesRegex(ValueError, "cannot authorize multiple transcripts"):
            record_transcript(
                updated,
                governance,
                transcript_id=EventId("event:p14-transcript-staff-2"),
                story_id=self.story.story_id,
                author_appointment_id="appointment:p14-media-officer",
                at=moment(21, 1),
                exact_words="Another response.",
                task_assignment_id="assignment:p14-media-briefing",
            )

    def test_delegation_requires_p12_authority_evidence_and_capacity(self) -> None:
        governance = governance_with_media_staff(capacity=1)
        assignment_id = "assignment:p14-media-briefing"
        missing_decision = replace(
            governance,
            decisions=tuple(item for item in governance.decisions
                            if not (item.action is AuthorityAction.ASSIGN_TASK
                                    and item.subject_id == assignment_id)),
        )
        with self.assertRaisesRegex(ValueError, "P12-authorized ASSIGN_TASK decision"):
            record_transcript(
                self.media,
                missing_decision,
                transcript_id=EventId("event:p14-transcript-unapproved"),
                story_id=self.story.story_id,
                author_appointment_id="appointment:p14-media-officer",
                at=moment(20, 1),
                exact_words="A structurally valid but unauthorized assignment is insufficient.",
                task_assignment_id=assignment_id,
            )

        manager_id = "appointment:p14-manager"
        second_task = StaffTask(
            "task:p14-capacity-overflow", HOME_CLUB, StaffFunction.MEDIA,
            WorldDate(GOVERNANCE_START.day + timedelta(days=1)), 1,
            "Prepare a second same-day media response",
        )
        created = create_staff_task(governance, manager_id, second_task, GOVERNANCE_START)
        self.assertTrue(created.accepted)
        overbooked = StaffTaskAssignment(
            "assignment:p14-capacity-overflow", second_task.task_id,
            "person:p14-media-officer", manager_id,
            WorldDate(GOVERNANCE_START.day + timedelta(days=1)), 1,
        )
        rejected = assign_staff_task(created.state, manager_id, overbooked, GOVERNANCE_START)
        self.assertFalse(rejected.accepted)
        self.assertIn("shared daily staff capacity", rejected.rejection)
        self.assertEqual(rejected.state.assignments, governance.assignments)
        with self.assertRaisesRegex(ValueError, "existing P12 task assignment"):
            record_transcript(
                self.media,
                rejected.state,
                transcript_id=EventId("event:p14-transcript-over-capacity"),
                story_id=self.story.story_id,
                author_appointment_id="appointment:p14-media-officer",
                at=moment(20, 1),
                exact_words="Rejected work cannot authorize a response.",
                task_assignment_id=overbooked.assignment_id,
            )

    def test_unknown_expired_or_unauthorized_staff_routes_are_rejected(self) -> None:
        expired = governance_with_media_staff(expires_after_day=1)
        with self.assertRaisesRegex(ValueError, "active same-club appointment"):
            record_transcript(
                self.media,
                expired,
                transcript_id=EventId("event:p14-transcript-expired"),
                story_id=self.story.story_id,
                author_appointment_id="appointment:p14-media-officer",
                at=moment(20, 2),
                exact_words="This response is after the appointment expired.",
                task_assignment_id="assignment:p14-media-briefing",
            )
        with self.assertRaisesRegex(ValueError, "existing P12 task assignment"):
            record_transcript(
                self.media,
                self.governance,
                transcript_id=EventId("event:p14-transcript-missing-task"),
                story_id=self.story.story_id,
                author_appointment_id="appointment:p14-manager",
                at=moment(20, 1),
                exact_words="No such assignment.",
                task_assignment_id="assignment:p14-missing",
            )
        head_coach = Appointment(
            "appointment:p14-coach", HOME_CLUB, "person:p14-coach", ClubRole.HEAD_COACH,
            GOVERNANCE_START, None, (),
        )
        coach_governance = replace(
            self.governance,
            appointments=self.governance.appointments + (head_coach,),
        )
        with self.assertRaisesRegex(ValueError, "active manager appointment"):
            record_transcript(
                self.media,
                coach_governance,
                transcript_id=EventId("event:p14-transcript-coach"),
                story_id=self.story.story_id,
                author_appointment_id=head_coach.appointment_id,
                at=moment(20, 1),
                exact_words="The active head coach is not the recorded manager.",
            )

    def test_transcript_annotations_require_exact_non_overlapping_source_spans(self) -> None:
        bad = TranscriptAnnotation(
            0, 4, "else", StatementClassification.COMMITMENT,
            "appointment:p14-manager",
        )
        with self.assertRaisesRegex(ValueError, "not an exact span"):
            record_transcript(
                self.media,
                self.governance,
                transcript_id=EventId("event:p14-transcript-false-quote"),
                story_id=self.story.story_id,
                author_appointment_id="appointment:p14-manager",
                at=moment(20, 1),
                exact_words="I may review it.",
                annotations=(bad,),
            )


class MediaPersistenceAndImportTests(unittest.TestCase):
    def test_versioned_media_ledger_round_trip(self) -> None:
        source = goal_source()
        media = MediaLedger(
            (outlet("outlet:p14-local", OutletTier.LOCAL),),
            personal_histories=(fresh_history(),),
        )
        media, story = story_for(source, media)
        media = record_person_awareness(media, awareness_receipt(str(story.story_id)))
        media = record_repost(media, Repost(
            "media-repost:p14-roundtrip", story.story_id, "account:p14-news", moment(12), 2_000,
        ))
        restored = loads(dumps(media), MediaLedger)
        self.assertEqual(restored, media)
        self.assertEqual(dumps(restored), dumps(media))

    def test_probe_is_byte_stable_and_module_import_does_not_open_files(self) -> None:
        with tempfile.TemporaryDirectory(prefix="touchline-p14-pycache-") as pycache:
            env = dict(os.environ)
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            env["PYTHONPYCACHEPREFIX"] = pycache
            first = subprocess.check_output(
                [sys.executable, "-m", "games.touchline.checks.media_probe"],
                cwd=REPO_ROOT,
                env=env,
                text=True,
            ).strip()
            second = subprocess.check_output(
                [sys.executable, "-m", "games.touchline.checks.media_probe"],
                cwd=REPO_ROOT,
                env=env,
                text=True,
            ).strip()
            self.assertEqual(first, second)
            self.assertIn("p14-modeled-reach-v1", first)
            script = """\
import builtins
import io
import pathlib
import sys
def blocked(*args, **kwargs):
    raise AssertionError('file access during import')
builtins.open = blocked
io.open = blocked
pathlib.Path.open = blocked
pathlib.Path.read_text = blocked
pathlib.Path.read_bytes = blocked
import games.touchline.esb.media.publication
assert 'curses' not in sys.modules
assert 'termstation_ui' not in sys.modules
"""
            subprocess.run(
                [sys.executable, "-c", script],
                cwd=REPO_ROOT,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )


if __name__ == "__main__":
    unittest.main()
