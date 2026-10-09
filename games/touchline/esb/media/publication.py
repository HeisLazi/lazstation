"""Source-limited public stories, modeled reach, and transcript records.

Match events are generic envelopes, so this module accepts only a small,
validated public-fact allowlist. A caller supplies the event collection and
calendar context; the module does not authenticate either against a career
archive. Aggregate reach is an estimate. A named person receives a P13
experience only after a separate, sourced awareness receipt.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, replace
from enum import Enum
from typing import NewType

from games.touchline.esb.club.governance import (
    AuthorityAction,
    ClubGovernance,
    ClubRole,
    DecisionOutcome,
    StaffFunction,
)
from games.touchline.esb.events import EventEnvelope
from games.touchline.esb.ids import ClubId, EventId, MatchId, derive_id, validate_id
from games.touchline.esb.people.relationships import (
    AwarenessBasis,
    ExperienceId,
    PersonalHistory,
    WorldMoment,
    new_personal_experience,
    record_personal_experience,
)
from games.touchline.esb.serialization import dumps
from games.touchline.esb.time import WorldDate

OutletId = NewType("OutletId", str)
MediaStoryId = NewType("MediaStoryId", str)
MediaRepostId = NewType("MediaRepostId", str)

MAX_MODELED_AUDIENCE = 1_000_000
MAX_HEADLINE_ATTENTION_MULTIPLIER = 1.25
MEDIA_REACH_FORMULA_VERSION = "p14-modeled-reach-v1"
MAX_TRANSCRIPT_CHARACTERS = 8_000


class OutletTier(str, Enum):
    LOCAL = "local"
    REGIONAL = "regional"
    ELITE = "elite"


class EditorialFrame(str, Enum):
    STRAIGHT = "straight"
    PROVOCATIVE = "provocative"


class PublicFactKind(str, Enum):
    GOAL = "goal"
    PLAYER_SENT_OFF = "player_sent_off"
    SUBSTITUTION = "substitution"
    MATCH_FINISHED = "match_finished"
    MATCH_ABANDONED = "match_abandoned"


class PublicReasonCode(str, Enum):
    DIRECT_RED_CARD = "direct_red_card"
    SECOND_YELLOW = "second_yellow"
    FULL_TIME = "full_time"
    FULL_TIME_DRAW = "full_time_draw"
    REGULATION_DRAW = "regulation_draw"
    PENALTIES_HOME = "penalties_home"
    PENALTIES_AWAY = "penalties_away"
    STARTING_PLAYERS_BELOW_COMPETITION_MINIMUM = "starting_players_below_competition_minimum"
    TEAM_BELOW_COMPETITION_MINIMUM = "team_below_competition_minimum"
    REQUIRED_GOALKEEPER_UNAVAILABLE_AFTER_DISMISSAL = "required_goalkeeper_unavailable_after_dismissal"
    NO_ELIGIBLE_SHOOTOUT_TAKER = "no_eligible_shootout_taker"
    WEATHER = "weather"
    SAFETY = "safety"
    PITCH_CONDITION = "pitch_condition"
    POWER_FAILURE = "power_failure"
    SERIOUS_INCIDENT = "serious_incident"


class AwarenessRoute(str, Enum):
    STORY_READ = "story_read"
    PRESS_BRIEFING = "press_briefing"
    REPORTED_RUMOUR = "reported_rumour"


class StatementClassification(str, Enum):
    COMMITMENT = "commitment"
    DENIAL = "denial"
    CONDITIONAL = "conditional"
    POSITION = "position"
    OTHER = "other"


TIER_REACH_FRACTIONS = (
    (OutletTier.LOCAL, 0.20),
    (OutletTier.REGIONAL, 0.50),
    (OutletTier.ELITE, 0.85),
)


@dataclass(frozen=True)
class Outlet:
    outlet_id: OutletId
    name: str
    tier: OutletTier
    covered_club_ids: tuple[ClubId, ...]
    estimated_audience: int

    def __post_init__(self) -> None:
        validate_id(self.outlet_id, kind="media outlet ID")
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("fictional media outlet requires a name")
        if not isinstance(self.tier, OutletTier):
            raise TypeError("media outlet requires an explicit coverage tier")
        if not isinstance(self.covered_club_ids, tuple) or not self.covered_club_ids:
            raise TypeError("media outlet requires an immutable covered-club list")
        for club_id in self.covered_club_ids:
            validate_id(club_id, kind="media outlet covered club ID")
        if len(self.covered_club_ids) != len(set(self.covered_club_ids)):
            raise ValueError("media outlet cannot repeat a covered club")
        if tuple(sorted(self.covered_club_ids, key=str)) != self.covered_club_ids:
            raise ValueError("media outlet club coverage must use canonical order")
        if self.tier is OutletTier.LOCAL and len(self.covered_club_ids) != 1:
            raise ValueError("a local outlet must name exactly one local club")
        if type(self.estimated_audience) is not int or not 1 <= self.estimated_audience <= MAX_MODELED_AUDIENCE:
            raise ValueError(f"estimated audience must be in 1..{MAX_MODELED_AUDIENCE}")


@dataclass(frozen=True)
class MatchPlayerClub:
    person_id: str
    team_id: str
    club_id: ClubId

    def __post_init__(self) -> None:
        validate_id(self.person_id, kind="media match player ID")
        if self.team_id not in ("home", "away"):
            raise ValueError("media match roster team must be home or away")
        validate_id(self.club_id, kind="media match player club ID")


@dataclass(frozen=True)
class EventWorldMoment:
    event_id: EventId
    at: WorldMoment

    def __post_init__(self) -> None:
        validate_id(self.event_id, kind="media source event ID")
        if not isinstance(self.at, WorldMoment):
            raise TypeError("media source chronology requires a world moment")


@dataclass(frozen=True)
class MatchMediaSource:
    """Caller-supplied match evidence plus separately sourced world chronology."""

    match_id: MatchId
    home_club_id: ClubId
    away_club_id: ClubId
    players: tuple[MatchPlayerClub, ...]
    events: tuple[EventEnvelope, ...]
    event_moments: tuple[EventWorldMoment, ...]
    calendar_evidence_id: EventId

    def __post_init__(self) -> None:
        for value, label in (
            (self.match_id, "media source match ID"),
            (self.home_club_id, "media source home club ID"),
            (self.away_club_id, "media source away club ID"),
            (self.calendar_evidence_id, "media calendar evidence ID"),
        ):
            validate_id(value, kind=label)
        if self.home_club_id == self.away_club_id:
            raise ValueError("media match source requires two different clubs")
        if not isinstance(self.players, tuple) or any(
            not isinstance(item, MatchPlayerClub) for item in self.players
        ):
            raise TypeError("media match roster must be an immutable tuple")
        player_ids = [item.person_id for item in self.players]
        if not player_ids or len(player_ids) != len(set(player_ids)):
            raise ValueError("media match roster must contain unique players")
        if tuple(sorted(self.players, key=lambda item: item.person_id)) != self.players:
            raise ValueError("media match roster must use canonical player order")
        for item in self.players:
            expected_club = self.home_club_id if item.team_id == "home" else self.away_club_id
            if item.club_id != expected_club:
                raise ValueError("media roster team and club mapping do not agree")
        if not isinstance(self.events, tuple) or not self.events or any(
            not isinstance(item, EventEnvelope) for item in self.events
        ):
            raise TypeError("media match source requires immutable match event envelopes")
        event_ids = [item.event_id for item in self.events]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("media match source cannot repeat event IDs")
        if tuple(sorted(self.events, key=lambda item: (item.match_tick, item.sequence))) != self.events:
            raise ValueError("media match events must retain tick/sequence chronology")
        sequences = [item.sequence for item in self.events]
        if len(sequences) != len(set(sequences)):
            raise ValueError("media match events cannot repeat a sequence")
        for event in self.events:
            if (
                event.aggregate_type != "match"
                or event.aggregate_id != str(self.match_id)
                or event.match_id != self.match_id
                or event.match_tick is None
            ):
                raise ValueError("media source event must belong to the named match aggregate")
        if not isinstance(self.event_moments, tuple) or any(
            not isinstance(item, EventWorldMoment) for item in self.event_moments
        ):
            raise TypeError("media source world moments must be immutable records")
        moment_ids = [item.event_id for item in self.event_moments]
        if set(moment_ids) != set(event_ids) or len(moment_ids) != len(event_ids):
            raise ValueError("each match event needs exactly one separately supplied world moment")
        moment_map = {item.event_id: item.at for item in self.event_moments}
        ordered_moments = tuple(moment_map[item.event_id] for item in self.events)
        expected_moments = tuple(
            EventWorldMoment(event.event_id, moment_map[event.event_id]) for event in self.events
        )
        if self.event_moments != expected_moments:
            raise ValueError("media event moments must follow match event chronology")
        if any(left >= right for left, right in zip(ordered_moments, ordered_moments[1:])):
            raise ValueError("media source world moments must increase with match chronology")
        source_date = ordered_moments[0].on
        if any(item.on != source_date for item in ordered_moments):
            raise ValueError("one match media source must use one caller-supplied world date")
        for event, at in zip(self.events, ordered_moments):
            if event.world_date is not None and event.world_date != at.on:
                raise ValueError("event and separately supplied media world dates disagree")

    def event(self, event_id: EventId) -> EventEnvelope | None:
        return next((item for item in self.events if item.event_id == event_id), None)

    def moment(self, event_id: EventId) -> WorldMoment | None:
        return next((item.at for item in self.event_moments if item.event_id == event_id), None)

    def player_map(self) -> dict[str, MatchPlayerClub]:
        return {item.person_id: item for item in self.players}


@dataclass(frozen=True)
class PublicFact:
    kind: PublicFactKind
    club_ids: tuple[ClubId, ...]
    subject_ids: tuple[str, ...]
    home_score: int | None = None
    away_score: int | None = None
    reason_code: PublicReasonCode | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, PublicFactKind):
            raise TypeError("public media fact requires a supported kind")
        if not isinstance(self.club_ids, tuple) or not self.club_ids:
            raise TypeError("public media fact requires immutable club references")
        for club_id in self.club_ids:
            validate_id(club_id, kind="public media fact club ID")
        if len(self.club_ids) != len(set(self.club_ids)):
            raise ValueError("public media fact cannot repeat a club")
        if tuple(sorted(self.club_ids, key=str)) != self.club_ids:
            raise ValueError("public media fact clubs must use canonical order")
        if not isinstance(self.subject_ids, tuple):
            raise TypeError("public media fact subjects must be immutable")
        for person_id in self.subject_ids:
            validate_id(person_id, kind="public media fact subject ID")
        if len(self.subject_ids) != len(set(self.subject_ids)):
            raise ValueError("public media fact cannot repeat a person")
        has_score = self.home_score is not None or self.away_score is not None
        if has_score:
            if any(type(value) is not int or value < 0 for value in (self.home_score, self.away_score)):
                raise ValueError("public media score must contain two non-negative integers")
        if self.reason_code is not None and not isinstance(self.reason_code, PublicReasonCode):
            raise TypeError("public media fact reason must use a controlled public code")
        if self.kind is PublicFactKind.GOAL:
            if not self.subject_ids or not has_score:
                raise ValueError("goal coverage requires a named player and score snapshot")
        elif self.kind is PublicFactKind.PLAYER_SENT_OFF:
            if len(self.subject_ids) != 1:
                raise ValueError("sending-off coverage requires its named player")
        elif self.kind is PublicFactKind.SUBSTITUTION:
            if len(self.subject_ids) != 2:
                raise ValueError("substitution coverage requires the outgoing and incoming players")
        elif self.kind in (PublicFactKind.MATCH_FINISHED, PublicFactKind.MATCH_ABANDONED):
            if len(self.club_ids) != 2 or not has_score or self.subject_ids:
                raise ValueError("match outcome coverage requires both clubs and the score, not named players")


@dataclass(frozen=True)
class Story:
    story_id: MediaStoryId
    source_event_id: EventId
    source_fingerprint: str
    match_id: MatchId
    source_sequence: int
    source_tick: int
    occurred_at: WorldMoment
    calendar_evidence_id: EventId
    outlet_id: OutletId
    published_at: WorldMoment
    frame: EditorialFrame
    fact: PublicFact
    modeled_reach: int
    reach_fraction: float
    formula_version: str = MEDIA_REACH_FORMULA_VERSION

    def __post_init__(self) -> None:
        for value, label in (
            (self.story_id, "media story ID"),
            (self.source_event_id, "media source event ID"),
            (self.match_id, "media story match ID"),
            (self.calendar_evidence_id, "media story calendar evidence ID"),
            (self.outlet_id, "media story outlet ID"),
        ):
            validate_id(value, kind=label)
        expected_story_id = derive_id(
            "media-story", "p14-media-story-v1", str(self.source_event_id), str(self.outlet_id)
        )
        if str(self.story_id) != expected_story_id:
            raise ValueError("media story ID does not match its source event and outlet")
        if not isinstance(self.source_fingerprint, str) or len(self.source_fingerprint) != 64:
            raise ValueError("media source fingerprint must be a SHA-256 hex digest")
        try:
            int(self.source_fingerprint, 16)
        except ValueError as exc:
            raise ValueError("media source fingerprint must be hexadecimal") from exc
        if type(self.source_sequence) is not int or self.source_sequence < 0:
            raise ValueError("media source sequence must be a non-negative integer")
        if type(self.source_tick) is not int or self.source_tick < 0:
            raise ValueError("media source tick must be a non-negative integer")
        if not isinstance(self.occurred_at, WorldMoment) or not isinstance(self.published_at, WorldMoment):
            raise TypeError("media story requires source and publication moments")
        if self.published_at <= self.occurred_at:
            raise ValueError("media story publication must follow its source event")
        if not isinstance(self.frame, EditorialFrame) or not isinstance(self.fact, PublicFact):
            raise TypeError("media story requires an explicit frame and projected public fact")
        if type(self.modeled_reach) is not int or not 0 <= self.modeled_reach <= MAX_MODELED_AUDIENCE:
            raise ValueError("modeled story reach is outside its documented bounds")
        if type(self.reach_fraction) not in (int, float) or not math.isfinite(self.reach_fraction) \
                or not 0.0 <= self.reach_fraction <= 1.0:
            raise ValueError("modeled story reach fraction must be normalized")
        if self.formula_version != MEDIA_REACH_FORMULA_VERSION:
            raise ValueError("unknown media reach formula version")


@dataclass(frozen=True)
class Repost:
    repost_id: MediaRepostId
    story_id: MediaStoryId
    actor_id: str
    at: WorldMoment
    additional_impressions: int

    def __post_init__(self) -> None:
        validate_id(self.repost_id, kind="media repost ID")
        validate_id(self.story_id, kind="media repost story ID")
        validate_id(self.actor_id, kind="media repost actor ID")
        if not isinstance(self.at, WorldMoment):
            raise TypeError("media repost requires a world moment")
        if type(self.additional_impressions) is not int or self.additional_impressions < 0:
            raise ValueError("repost impression estimate must be a non-negative integer")


@dataclass(frozen=True)
class PersonAwareness:
    person_id: str
    source_event_id: EventId
    story_id: MediaStoryId
    receipt_event_id: EventId
    receipt_fingerprint: str
    at: WorldMoment
    basis: AwarenessBasis

    def __post_init__(self) -> None:
        validate_id(self.person_id, kind="media-aware person ID")
        validate_id(self.source_event_id, kind="media awareness cause event ID")
        validate_id(self.story_id, kind="media awareness story ID")
        validate_id(self.receipt_event_id, kind="media awareness receipt event ID")
        if not isinstance(self.receipt_fingerprint, str) or len(self.receipt_fingerprint) != 64:
            raise ValueError("media awareness fingerprint must be a SHA-256 hex digest")
        try:
            int(self.receipt_fingerprint, 16)
        except ValueError as exc:
            raise ValueError("media awareness fingerprint must be hexadecimal") from exc
        if not isinstance(self.at, WorldMoment) or not isinstance(self.basis, AwarenessBasis):
            raise TypeError("media awareness requires a moment and P13 awareness basis")


@dataclass(frozen=True)
class AwarenessReceipt:
    """Caller-attested read/briefing/report event for a named story subject."""

    event: EventEnvelope
    person_id: str
    story_id: MediaStoryId
    at: WorldMoment
    route: AwarenessRoute

    def __post_init__(self) -> None:
        if not isinstance(self.event, EventEnvelope):
            raise TypeError("media awareness requires a source event envelope")
        validate_id(self.person_id, kind="media awareness person ID")
        validate_id(self.story_id, kind="media awareness story ID")
        if not isinstance(self.at, WorldMoment) or not isinstance(self.route, AwarenessRoute):
            raise TypeError("media awareness requires a route and world moment")
        expected_kind = {
            AwarenessRoute.STORY_READ: "media_story_read",
            AwarenessRoute.PRESS_BRIEFING: "media_press_briefing",
            AwarenessRoute.REPORTED_RUMOUR: "media_story_rumoured",
        }[self.route]
        payload = self.event.payload
        if (
            self.event.kind != expected_kind
            or self.event.aggregate_type != "media_story"
            or self.event.aggregate_id != str(self.story_id)
            or payload.get("actor_id") != self.person_id
            or payload.get("story_id") != str(self.story_id)
            or self.event.parent_event_id != EventId(str(self.story_id))
            or self.event.cause_event_id is None
            or self.event.world_date != self.at.on
            or self.event.match_id is not None
        ):
            raise ValueError("awareness event does not attest its named person's story access")


@dataclass(frozen=True)
class TranscriptAnnotation:
    start_offset: int
    end_offset: int
    quoted_text: str
    classification: StatementClassification
    classified_by_appointment_id: str

    def __post_init__(self) -> None:
        if type(self.start_offset) is not int or type(self.end_offset) is not int \
                or self.start_offset < 0 or self.end_offset <= self.start_offset:
            raise ValueError("transcript annotation requires a non-empty exact character span")
        if not isinstance(self.quoted_text, str) or not self.quoted_text:
            raise ValueError("transcript annotation must retain its exact quoted text")
        if not isinstance(self.classification, StatementClassification):
            raise TypeError("transcript annotation requires an explicit source classification")
        validate_id(self.classified_by_appointment_id, kind="transcript classification appointment ID")


@dataclass(frozen=True)
class Transcript:
    transcript_id: EventId
    story_id: MediaStoryId
    source_event_id: EventId
    club_id: ClubId
    at: WorldMoment
    author_appointment_id: str
    staff_id: str | None
    task_assignment_id: str | None
    assigned_by_appointment_id: str | None
    exact_words: str
    annotations: tuple[TranscriptAnnotation, ...]

    def __post_init__(self) -> None:
        for value, label in (
            (self.transcript_id, "media transcript ID"),
            (self.story_id, "media transcript story ID"),
            (self.source_event_id, "media transcript source event ID"),
            (self.club_id, "media transcript club ID"),
            (self.author_appointment_id, "media transcript author appointment ID"),
        ):
            validate_id(value, kind=label)
        if not isinstance(self.at, WorldMoment):
            raise TypeError("media transcript requires a world moment")
        if not isinstance(self.exact_words, str) or not self.exact_words.strip() \
                or len(self.exact_words) > MAX_TRANSCRIPT_CHARACTERS or "\x00" in self.exact_words:
            raise ValueError("media transcript must retain non-empty exact wording within its length bound")
        if (self.staff_id is None) != (self.task_assignment_id is None) \
                or (self.staff_id is None) != (self.assigned_by_appointment_id is None):
            raise ValueError("delegated media transcripts must cite staff, assignment and assigning appointment")
        if self.staff_id is not None:
            validate_id(self.staff_id, kind="media transcript staff ID")
            validate_id(self.task_assignment_id, kind="media transcript assignment ID")
            validate_id(self.assigned_by_appointment_id, kind="media assigning appointment ID")
        if not isinstance(self.annotations, tuple) or any(
            not isinstance(item, TranscriptAnnotation) for item in self.annotations
        ):
            raise TypeError("transcript annotations must be an immutable tuple")
        ranges: list[tuple[int, int]] = []
        for annotation in self.annotations:
            if annotation.end_offset > len(self.exact_words) \
                    or self.exact_words[annotation.start_offset:annotation.end_offset] != annotation.quoted_text:
                raise ValueError("transcript annotation is not an exact span of the stored words")
            if annotation.classified_by_appointment_id != self.author_appointment_id:
                raise ValueError("transcript classifications must name the recorded spokesperson")
            ranges.append((annotation.start_offset, annotation.end_offset))
        if ranges != sorted(ranges) or any(left[1] > right[0] for left, right in zip(ranges, ranges[1:])):
            raise ValueError("transcript annotation spans must be ordered and non-overlapping")


@dataclass(frozen=True)
class MediaLedger:
    outlets: tuple[Outlet, ...]
    stories: tuple[Story, ...] = ()
    reposts: tuple[Repost, ...] = ()
    awareness: tuple[PersonAwareness, ...] = ()
    transcripts: tuple[Transcript, ...] = ()
    personal_histories: tuple[PersonalHistory, ...] = ()

    def __post_init__(self) -> None:
        groups = (
            ("outlets", self.outlets, Outlet, "outlet_id"),
            ("stories", self.stories, Story, "story_id"),
            ("reposts", self.reposts, Repost, "repost_id"),
            ("awareness", self.awareness, PersonAwareness, "receipt_event_id"),
            ("transcripts", self.transcripts, Transcript, "transcript_id"),
            ("personal histories", self.personal_histories, PersonalHistory, "person_id"),
        )
        for label, records, record_type, key in groups:
            if not isinstance(records, tuple) or any(not isinstance(item, record_type) for item in records):
                raise TypeError(f"media {label} must be an immutable {record_type.__name__} tuple")
            ids = [getattr(item, key) for item in records]
            if len(ids) != len(set(ids)):
                raise ValueError(f"media {label} cannot repeat {key} values")
        outlet_ids = [item.outlet_id for item in self.outlets]
        story_ids = [item.story_id for item in self.stories]
        if outlet_ids != sorted(outlet_ids, key=str):
            raise ValueError("media outlets must use canonical ID order")
        if self.stories != tuple(sorted(self.stories, key=lambda item: (item.published_at, str(item.story_id)))):
            raise ValueError("media stories must retain publication chronology")
        if self.reposts != tuple(sorted(self.reposts, key=lambda item: (item.at, str(item.repost_id)))):
            raise ValueError("media reposts must retain chronology")
        if self.awareness != tuple(sorted(self.awareness, key=lambda item: (item.at, str(item.receipt_event_id)))):
            raise ValueError("person awareness records must retain chronology")
        if self.transcripts != tuple(sorted(self.transcripts, key=lambda item: (item.at, str(item.transcript_id)))):
            raise ValueError("media transcripts must retain chronology")
        if [item.person_id for item in self.personal_histories] != sorted(
            item.person_id for item in self.personal_histories
        ):
            raise ValueError("media personal histories must use canonical person order")
        outlets = {str(item.outlet_id): item for item in self.outlets}
        stories = {str(item.story_id): item for item in self.stories}
        if len(outlets) != len(self.outlets) or len(stories) != len(self.stories):
            raise ValueError("media ledger cannot repeat outlet or story IDs")
        fingerprints: dict[EventId, str] = {}
        for story in self.stories:
            outlet = outlets.get(str(story.outlet_id))
            if outlet is None:
                raise ValueError("media story references an unknown outlet")
            if not set(story.fact.club_ids).intersection(outlet.covered_club_ids):
                raise ValueError("media story is outside the outlet's covered-club scope")
            reach, fraction = _modeled_reach(outlet, story.frame)
            if story.modeled_reach != reach or not math.isclose(
                float(story.reach_fraction), fraction, rel_tol=0.0, abs_tol=1e-8
            ):
                raise ValueError("media story modeled reach does not match its outlet and frame")
            prior = fingerprints.get(story.source_event_id)
            if prior is not None and prior != story.source_fingerprint:
                raise ValueError("one source event cannot have conflicting fingerprints across outlets")
            fingerprints[story.source_event_id] = story.source_fingerprint
        for repost in self.reposts:
            story = stories.get(str(repost.story_id))
            if story is None or repost.at <= story.published_at:
                raise ValueError("media repost must reference an earlier published story")
        seen_awareness = set()
        histories = {str(item.person_id): item for item in self.personal_histories}
        for awareness in self.awareness:
            story = stories.get(str(awareness.story_id))
            history = histories.get(awareness.person_id)
            if story is None or history is None or story.source_event_id != awareness.source_event_id \
                    or awareness.person_id not in story.fact.subject_ids or awareness.at < story.published_at:
                raise ValueError("person awareness must match a published story, named subject and history")
            key = (awareness.person_id, awareness.source_event_id)
            if key in seen_awareness:
                raise ValueError("one person can receive only one awareness record per source event")
            seen_awareness.add(key)
            if not any(item.cause_event_id == awareness.source_event_id for item in history.experiences):
                raise ValueError("person awareness must create its corresponding P13 experience")
        assignment_ids: set[str] = set()
        for transcript in self.transcripts:
            story = stories.get(str(transcript.story_id))
            if story is None or story.source_event_id != transcript.source_event_id \
                    or transcript.at <= story.published_at or transcript.club_id not in story.fact.club_ids:
                raise ValueError("media transcript must respond to a published story affecting its club")
            if transcript.task_assignment_id is not None:
                if transcript.task_assignment_id in assignment_ids:
                    raise ValueError("one scheduled media assignment cannot be reused for several transcripts")
                assignment_ids.add(transcript.task_assignment_id)


def _modeled_reach(outlet: Outlet, frame: EditorialFrame) -> tuple[int, float]:
    frame_factor = MAX_HEADLINE_ATTENTION_MULTIPLIER if frame is EditorialFrame.PROVOCATIVE else 1.0
    tier_fraction = next(value for tier, value in TIER_REACH_FRACTIONS if tier is outlet.tier)
    fraction = min(1.0, tier_fraction * frame_factor)
    estimate = min(MAX_MODELED_AUDIENCE, int(round(outlet.estimated_audience * fraction)))
    return estimate, round(fraction, 6)


def _score(outcome: dict[str, object]) -> tuple[int, int]:
    home, away = outcome.get("home_score"), outcome.get("away_score")
    if type(home) is not int or type(away) is not int or home < 0 or away < 0:
        raise ValueError("public match result requires non-negative integer home and away scores")
    return home, away


def _event_person(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a named match player")
    validate_id(value, kind=label)
    return value


def _optional_people(payload: dict[str, object], names: tuple[str, ...]) -> tuple[str, ...]:
    values = []
    for name in names:
        raw = payload.get(name)
        if raw is None:
            continue
        values.append(_event_person(raw, f"public event {name}"))
    return tuple(dict.fromkeys(values))


def _project_public_fact(source: MatchMediaSource, event: EventEnvelope) -> PublicFact:
    payload, outcome = event.payload, event.outcome
    players = source.player_map()
    team_clubs = {"home": source.home_club_id, "away": source.away_club_id}
    kind = event.kind
    if kind == "goal":
        actor_value = payload.get("actor_id")
        own_goal_value = payload.get("own_goal_player_id")
        if actor_value is not None and own_goal_value is not None:
            raise ValueError("goal cannot identify both a scorer and an own-goal player")
        if actor_value is None and own_goal_value is None:
            raise ValueError("goal source needs one rostered scorer or own-goal player")
        performer_id = _event_person(
            own_goal_value if own_goal_value is not None else actor_value,
            "public goal performer ID",
        )
        performer = players.get(performer_id)
        if performer is None:
            raise ValueError("goal source performer is outside the match roster")
        performer_team = performer.team_id
        expected_scoring_team = (
            ("away" if performer_team == "home" else "home")
            if own_goal_value is not None else performer_team
        )
        scoring_team = payload.get("scoring_team_id")
        if scoring_team is None:
            scoring_team = expected_scoring_team
        if scoring_team not in team_clubs:
            raise ValueError("goal scoring team must be home or away")
        if scoring_team != expected_scoring_team:
            raise ValueError("goal scorer/own-goal player conflicts with the scoring team")
        for field in ("team_id", "last_touch_team_id"):
            team_value = payload.get(field)
            if team_value is not None and team_value != performer_team:
                raise ValueError(f"goal {field} conflicts with its named player")
        subjects = [performer_id]
        assist_value = payload.get("assist_player_id")
        if assist_value is not None:
            if own_goal_value is not None:
                raise ValueError("own-goal source cannot also name an attacking assist")
            assist_id = _event_person(assist_value, "public goal assist player ID")
            assist = players.get(assist_id)
            if assist is None or assist.team_id != scoring_team:
                raise ValueError("goal assist player must be on the scoring team")
            if assist_id == performer_id:
                raise ValueError("goal scorer cannot be their own assist")
            subjects.append(assist_id)
        club_refs = {players[item].club_id for item in subjects}
        club_refs.add(team_clubs[scoring_team])
        return PublicFact(PublicFactKind.GOAL, tuple(sorted(club_refs, key=str)),
                          tuple(subjects), *_score(outcome))
    if kind == "player_sent_off":
        subjects = _optional_people(payload, ("actor_id",))
        if len(subjects) != 1 or subjects[0] not in players:
            raise ValueError("sending-off source must name a rostered player")
        team = payload.get("team_id")
        if team not in team_clubs or players[subjects[0]].team_id != team:
            raise ValueError("sending-off team must match its named player")
        reason = _public_reason(payload.get("reason"), {
            PublicReasonCode.DIRECT_RED_CARD,
            PublicReasonCode.SECOND_YELLOW,
        }, "sending-off")
        return PublicFact(PublicFactKind.PLAYER_SENT_OFF, (team_clubs[team],), subjects,
                          reason_code=reason)
    if kind == "substitution":
        subjects = _optional_people(payload, ("outgoing_player_id", "incoming_player_id"))
        team = payload.get("team_id")
        if len(subjects) != 2 or any(person not in players for person in subjects):
            raise ValueError("substitution source must name both rostered players")
        if team not in team_clubs or any(players[person].team_id != team for person in subjects):
            raise ValueError("substitution team must match both named players")
        if payload.get("actor_id") != payload.get("incoming_player_id"):
            raise ValueError("substitution actor must be its incoming player")
        return PublicFact(PublicFactKind.SUBSTITUTION, (team_clubs[team],), subjects)
    if kind == "match_finished":
        reason = _public_reason(payload.get("reason"), {
            PublicReasonCode.FULL_TIME,
            PublicReasonCode.FULL_TIME_DRAW,
            PublicReasonCode.REGULATION_DRAW,
            PublicReasonCode.PENALTIES_HOME,
            PublicReasonCode.PENALTIES_AWAY,
        }, "finished-match")
        home, away = _score(outcome)
        return PublicFact(PublicFactKind.MATCH_FINISHED,
                          tuple(sorted((source.home_club_id, source.away_club_id), key=str)),
                          (), home, away, reason)
    if kind == "match_abandoned":
        reason = _public_reason(payload.get("reason"), {
            PublicReasonCode.STARTING_PLAYERS_BELOW_COMPETITION_MINIMUM,
            PublicReasonCode.TEAM_BELOW_COMPETITION_MINIMUM,
            PublicReasonCode.REQUIRED_GOALKEEPER_UNAVAILABLE_AFTER_DISMISSAL,
            PublicReasonCode.NO_ELIGIBLE_SHOOTOUT_TAKER,
            PublicReasonCode.WEATHER,
            PublicReasonCode.SAFETY,
            PublicReasonCode.PITCH_CONDITION,
            PublicReasonCode.POWER_FAILURE,
            PublicReasonCode.SERIOUS_INCIDENT,
        }, "abandoned-match")
        home, away = _score(outcome)
        return PublicFact(PublicFactKind.MATCH_ABANDONED,
                          tuple(sorted((source.home_club_id, source.away_club_id), key=str)),
                          (), home, away, reason)
    raise ValueError(f"unsupported public match event kind: {kind}")


def _public_reason(
    value: object,
    allowed: set[PublicReasonCode],
    label: str,
) -> PublicReasonCode:
    if not isinstance(value, str):
        raise ValueError(f"{label} source requires a controlled public reason code")
    try:
        reason = PublicReasonCode(value)
    except ValueError as exc:
        raise ValueError(f"{label} source reason is not an allowed public code") from exc
    if reason not in allowed:
        raise ValueError(f"{label} source reason is not allowed for this event kind")
    return reason


def _event_fingerprint(event: EventEnvelope) -> str:
    return hashlib.sha256(dumps(event).encode("utf-8")).hexdigest()


def publish_story(
    ledger: MediaLedger,
    source: MatchMediaSource,
    *,
    source_event_id: EventId,
    outlet_id: OutletId,
    published_at: WorldMoment,
    frame: EditorialFrame = EditorialFrame.STRAIGHT,
) -> tuple[MediaLedger, Story]:
    """Publish one projected fact; arbitrary event payload fields stay private."""

    if not isinstance(ledger, MediaLedger) or not isinstance(source, MatchMediaSource):
        raise TypeError("story publication requires media and match source records")
    validate_id(source_event_id, kind="story source event ID")
    validate_id(outlet_id, kind="story outlet ID")
    if not isinstance(published_at, WorldMoment) or not isinstance(frame, EditorialFrame):
        raise TypeError("story publication requires a date and explicit editorial frame")
    event = source.event(source_event_id)
    if event is None:
        raise ValueError("story source event is absent from the supplied match event collection")
    moment = source.moment(source_event_id)
    if moment is None:
        raise ValueError("story source event has no separately supplied world moment")
    fact = _project_public_fact(source, event)
    outlet = next((item for item in ledger.outlets if item.outlet_id == outlet_id), None)
    if outlet is None:
        raise ValueError("story outlet is not registered in the media ledger")
    if not set(fact.club_ids).intersection(outlet.covered_club_ids):
        raise ValueError("story facts fall outside the outlet's covered clubs")
    if published_at <= moment:
        raise ValueError("a story must be published after its source event")
    reach, fraction = _modeled_reach(outlet, frame)
    story_id = MediaStoryId(derive_id(
        "media-story", "p14-media-story-v1", str(source_event_id), str(outlet_id)
    ))
    story = Story(
        story_id, source_event_id, _event_fingerprint(event), source.match_id,
        event.sequence, event.match_tick, moment, source.calendar_evidence_id,
        outlet_id, published_at, frame, fact, reach, fraction,
    )
    existing = next((item for item in ledger.stories if item.story_id == story_id), None)
    if existing is not None:
        if existing == story:
            return ledger, existing
        raise ValueError("story source/outlet identity was replayed with conflicting content")
    updated = replace(ledger, stories=tuple(sorted(
        ledger.stories + (story,), key=lambda item: (item.published_at, str(item.story_id))
    )))
    return updated, story


def record_repost(ledger: MediaLedger, repost: Repost) -> MediaLedger:
    """Retain repost lineage without treating impressions as a second event effect."""

    if not isinstance(ledger, MediaLedger) or not isinstance(repost, Repost):
        raise TypeError("media repost requires a ledger and repost record")
    story = next((item for item in ledger.stories if item.story_id == repost.story_id), None)
    if story is None or repost.at <= story.published_at:
        raise ValueError("repost must cite a published story and occur after publication")
    existing = next((item for item in ledger.reposts if item.repost_id == repost.repost_id), None)
    if existing is not None:
        if existing == repost:
            return ledger
        raise ValueError("media repost ID was reused with conflicting content")
    updated = replace(ledger, reposts=tuple(sorted(
        ledger.reposts + (repost,), key=lambda item: (item.at, str(item.repost_id))
    )))
    return updated


def record_person_awareness(
    ledger: MediaLedger,
    receipt: AwarenessReceipt,
) -> MediaLedger:
    """Turn one explicit access receipt into one pending P13 experience."""

    if not isinstance(ledger, MediaLedger) or not isinstance(receipt, AwarenessReceipt):
        raise TypeError("media awareness requires a ledger and source receipt")
    story = next((item for item in ledger.stories if item.story_id == receipt.story_id), None)
    if story is None or receipt.at < story.published_at:
        raise ValueError("awareness receipt must follow the cited story publication")
    if receipt.person_id not in story.fact.subject_ids:
        raise ValueError("person awareness requires a subject named by the public fact")
    if receipt.event.cause_event_id != story.source_event_id:
        raise ValueError("awareness event must cite the published match event as its cause")
    existing_event = next((item for item in ledger.awareness
                           if item.receipt_event_id == receipt.event.event_id), None)
    basis = AwarenessBasis.RUMOURED if receipt.route is AwarenessRoute.REPORTED_RUMOUR \
        else AwarenessBasis.REPORTED
    awareness = PersonAwareness(
        receipt.person_id, story.source_event_id, story.story_id,
        receipt.event.event_id, _event_fingerprint(receipt.event), receipt.at, basis,
    )
    if existing_event is not None:
        if existing_event == awareness:
            return ledger
        raise ValueError("awareness event ID was reused with conflicting content")
    if any(
        item.person_id == awareness.person_id and item.source_event_id == awareness.source_event_id
        for item in ledger.awareness
    ):
        # Another outlet or read receipt for this cause cannot create another
        # person-level awareness or state effect.
        return ledger
    history_index = next((i for i, item in enumerate(ledger.personal_histories)
                          if item.person_id == receipt.person_id), None)
    if history_index is None:
        raise ValueError("media awareness requires an existing P13 personal history")
    history = ledger.personal_histories[history_index]
    if not any(item.cause_event_id == story.source_event_id for item in history.experiences):
        experience = new_personal_experience(
            receipt.person_id, story.source_event_id, story.occurred_at, basis, receipt.at,
        )
        history = record_personal_experience(history, experience)
    histories = ledger.personal_histories[:history_index] + (history,) + ledger.personal_histories[history_index + 1:]
    updated = replace(
        ledger,
        awareness=tuple(sorted(ledger.awareness + (awareness,),
                               key=lambda item: (item.at, str(item.receipt_event_id)))),
        personal_histories=histories,
    )
    return updated


def _authorize_response(
    governance: ClubGovernance,
    story: Story,
    author_appointment_id: str,
    at: WorldMoment,
    task_assignment_id: str | None,
) -> tuple[str | None, str | None]:
    if not isinstance(governance, ClubGovernance) or not isinstance(at, WorldMoment):
        raise TypeError("media response requires dated club governance")
    validate_id(author_appointment_id, kind="media response author appointment ID")
    if governance.club_id not in story.fact.club_ids:
        raise ValueError("response club is not involved in the cited story")
    appointment = next((item for item in governance.appointments
                        if item.appointment_id == author_appointment_id), None)
    if appointment is None or appointment.club_id != governance.club_id or not appointment.active_on(at.on):
        raise ValueError("media response author must be an active same-club appointment")
    if task_assignment_id is None:
        if appointment.role is not ClubRole.MANAGER:
            raise ValueError("direct media response requires an active manager appointment")
        return None, None
    validate_id(task_assignment_id, kind="media response staff assignment ID")
    assignment = next((item for item in governance.assignments
                       if item.assignment_id == task_assignment_id), None)
    if assignment is None:
        raise ValueError("delegated response requires an existing P12 task assignment")
    assignment_decision = next((item for item in governance.decisions
                                if item.action is AuthorityAction.ASSIGN_TASK
                                and item.subject_id == assignment.assignment_id
                                and item.actor_appointment_id == assignment.assigned_by_appointment_id
                                and item.outcome is DecisionOutcome.EXECUTED), None)
    if assignment_decision is None:
        raise ValueError("delegated response requires a P12-authorized ASSIGN_TASK decision")
    task = next((item for item in governance.tasks if item.task_id == assignment.task_id), None)
    staff = next((item for item in governance.staff if item.staff_id == assignment.staff_id), None)
    staff_appointment = next((item for item in governance.appointments
                              if staff is not None and item.appointment_id == staff.appointment_id), None)
    assigning_appointment = next((item for item in governance.appointments
                                  if item.appointment_id == assignment.assigned_by_appointment_id), None)
    if (
        task is None or staff is None or staff_appointment is None or assigning_appointment is None
        or governance.club_id != staff.club_id or task.club_id != governance.club_id
        or task.function is not StaffFunction.MEDIA
        or StaffFunction.MEDIA not in staff.functions
        or assignment.work_units != task.work_units
        or assignment.scheduled_on != at.on
        or assignment.scheduled_on > task.due_on
        or assignment_decision.decided_on > assignment.scheduled_on
        or author_appointment_id != staff.appointment_id
        or not staff_appointment.active_on(at.on)
        or not assigning_appointment.active_on(at.on)
    ):
        raise ValueError("delegated response needs active same-club MEDIA staff and a valid dated assignment")
    return staff.staff_id, assigning_appointment.appointment_id


def record_transcript(
    ledger: MediaLedger,
    governance: ClubGovernance,
    *,
    transcript_id: EventId,
    story_id: MediaStoryId,
    author_appointment_id: str,
    at: WorldMoment,
    exact_words: str,
    annotations: tuple[TranscriptAnnotation, ...] = (),
    task_assignment_id: str | None = None,
) -> tuple[MediaLedger, Transcript]:
    """Keep exact response wording and only explicitly source-classified spans."""

    if not isinstance(ledger, MediaLedger) or not isinstance(governance, ClubGovernance):
        raise TypeError("media transcript requires a ledger and club governance record")
    validate_id(transcript_id, kind="media transcript event ID")
    validate_id(story_id, kind="media transcript story ID")
    if not isinstance(at, WorldMoment):
        raise TypeError("media transcript requires a world moment")
    story = next((item for item in ledger.stories if item.story_id == story_id), None)
    if story is None or at <= story.published_at:
        raise ValueError("media transcript must respond after a recorded story")
    staff_id, assigning_id = _authorize_response(
        governance, story, author_appointment_id, at, task_assignment_id,
    )
    transcript = Transcript(
        transcript_id, story_id, story.source_event_id, governance.club_id, at,
        author_appointment_id, staff_id, task_assignment_id, assigning_id,
        exact_words, annotations,
    )
    existing = next((item for item in ledger.transcripts
                     if item.transcript_id == transcript_id), None)
    if existing is not None:
        if existing == transcript:
            return ledger, existing
        raise ValueError("media transcript ID was reused with conflicting wording or attribution")
    if task_assignment_id is not None and any(
        item.task_assignment_id == task_assignment_id for item in ledger.transcripts
    ):
        raise ValueError("one P12 media assignment cannot authorize multiple transcripts")
    updated = replace(ledger, transcripts=tuple(sorted(
        ledger.transcripts + (transcript,), key=lambda item: (item.at, str(item.transcript_id))
    )))
    return updated, transcript


__all__ = [
    "AwarenessReceipt",
    "AwarenessRoute",
    "EditorialFrame",
    "EventWorldMoment",
    "MAX_MODELED_AUDIENCE",
    "MEDIA_REACH_FORMULA_VERSION",
    "MatchMediaSource",
    "MatchPlayerClub",
    "MediaLedger",
    "MediaRepostId",
    "MediaStoryId",
    "Outlet",
    "OutletId",
    "OutletTier",
    "PersonAwareness",
    "PublicFact",
    "PublicFactKind",
    "PublicReasonCode",
    "Repost",
    "StatementClassification",
    "Story",
    "Transcript",
    "TranscriptAnnotation",
    "publish_story",
    "record_person_awareness",
    "record_repost",
    "record_transcript",
]
