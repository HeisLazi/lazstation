"""Eligibility, representative selection and condition continuity for P16b.

The flow runner accepts authored competition schedules, registration records,
national eligibility and call-up decisions. It resolves matches with the P05
engine, applies the P09 condition and medical formulas, and checkpoints each
match together with the resulting world state in the P16a archive.
"""

from __future__ import annotations

import copy
import hashlib
import math
from dataclasses import dataclass, replace
from datetime import date, timedelta
from enum import Enum

from games.touchline.esb.ids import MatchId, PlayerId, derive_id, validate_id
from games.touchline.esb.match.engine import (
    MatchPhase,
    MatchInputSnapshot,
    MatchState,
    PlayerState,
    TeamSheet,
    create_match,
    run_to_completion,
    match_input_snapshot_sha256,
)
from games.touchline.esb.match.spatial import limits_from_profile
from games.touchline.esb.model import DataProvenance, ProvenanceKind
from games.touchline.esb.people import PlayerProfile, ReadinessSnapshot
from games.touchline.esb.people.medical import (
    InjuryEpisode,
    MedicalProfile,
    MIN_ACUTE_DAYS,
    MIN_REHABILITATION_DAYS,
    MIN_RETURN_TO_PLAY_DAYS,
    RehabStage,
    add_rehabilitation_contact,
    injury_probability,
    progress_medical_day,
)
from games.touchline.esb.randomness import RandomStreams
from games.touchline.esb.serialization import SerializationError, dumps, loads
from games.touchline.esb.time import WorldDate
from games.touchline.esb.world.archive import WorldArchiveStore, WorldMatchRecord
from games.touchline.esb.world.preparation import PreparationPolicy
from games.touchline.esb.world.registration import (
    RegistrationBook,
    check_existing_registration,
)
from games.touchline.esb.world.season import (
    CompetitionKind,
    WorldCompetition,
    WorldFixture,
    WorldSeasonSchedule,
    fixture_input_sha256,
    fixture_seed,
    immutable_snapshot_json,
)


class CallUpDecision(str, Enum):
    ACCEPTED = "accepted"
    DECLINED = "declined"


class AvailabilityStatus(str, Enum):
    MEDICALLY_UNAVAILABLE = "medically_unavailable"
    BELOW_SELECTION_READINESS = "below_selection_readiness"
    SELECTABLE = "selectable"


@dataclass(frozen=True)
class NationalEligibility:
    """Explicitly authored player/representative eligibility and its dates."""

    player_id: PlayerId
    participant_id: str
    eligible_from: WorldDate
    eligible_through: WorldDate | None
    source_id: str

    def __post_init__(self) -> None:
        validate_id(self.player_id, kind="nationally eligible player ID")
        validate_id(self.participant_id, kind="representative participant ID")
        validate_id(self.source_id, kind="national eligibility source ID")
        if not isinstance(self.eligible_from, WorldDate):
            raise TypeError("national eligibility requires a start date")
        if self.eligible_through is not None and not isinstance(self.eligible_through, WorldDate):
            raise TypeError("national eligibility end must be a WorldDate")
        if self.eligible_through is not None and self.eligible_through < self.eligible_from:
            raise ValueError("national eligibility ends before it begins")

    def valid_on(self, day: WorldDate) -> bool:
        if not isinstance(day, WorldDate):
            raise TypeError("eligibility lookup requires a WorldDate")
        return self.eligible_from <= day and (
            self.eligible_through is None or day <= self.eligible_through
        )


@dataclass(frozen=True)
class NationalCallUpOffer:
    """One dated, fixture-specific representative selection and response."""

    offer_id: str
    player_id: PlayerId
    participant_id: str
    competition_id: str
    fixture_id: str
    fixture_on: WorldDate
    offered_on: WorldDate
    response_by: WorldDate
    decision: CallUpDecision | None = None
    responded_on: WorldDate | None = None

    def __post_init__(self) -> None:
        for value, label in (
            (self.offer_id, "national call-up offer ID"),
            (self.participant_id, "call-up participant ID"),
            (self.competition_id, "call-up competition ID"),
            (self.fixture_id, "call-up fixture ID"),
        ):
            validate_id(value, kind=label)
        validate_id(self.player_id, kind="call-up player ID")
        for label, day in (("fixture", self.fixture_on), ("offer", self.offered_on),
                           ("response deadline", self.response_by)):
            if not isinstance(day, WorldDate):
                raise TypeError(f"call-up {label} date must be explicit")
        if self.offered_on > self.response_by or self.response_by >= self.fixture_on:
            raise ValueError("call-up response deadline must precede its fixture")
        if self.decision is None:
            if self.responded_on is not None:
                raise ValueError("pending call-up cannot have a response date")
        else:
            if not isinstance(self.decision, CallUpDecision):
                raise TypeError("call-up response must be accepted or declined")
            if not isinstance(self.responded_on, WorldDate):
                raise TypeError("call-up response requires its date")
            if not self.offered_on <= self.responded_on <= self.response_by:
                raise ValueError("call-up response falls outside its offer window")


@dataclass(frozen=True)
class NationalSelectionBook:
    eligibility: tuple[NationalEligibility, ...] = ()
    call_ups: tuple[NationalCallUpOffer, ...] = ()
    schema_version: int = 1

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("unsupported national selection schema version")
        if (not isinstance(self.eligibility, tuple)
                or any(not isinstance(item, NationalEligibility) for item in self.eligibility)):
            raise TypeError("national eligibility must be an immutable record tuple")
        if (not isinstance(self.call_ups, tuple)
                or any(not isinstance(item, NationalCallUpOffer) for item in self.call_ups)):
            raise TypeError("national call-ups must be an immutable record tuple")
        keys = [(item.player_id, item.participant_id) for item in self.eligibility]
        if len(keys) != len(set(keys)):
            raise ValueError("national eligibility cannot repeat a player/participant pair")
        offer_ids = [item.offer_id for item in self.call_ups]
        fixture_selections = [(item.player_id, item.fixture_id) for item in self.call_ups]
        if len(offer_ids) != len(set(offer_ids)) or len(fixture_selections) != len(set(fixture_selections)):
            raise ValueError("call-up offer IDs and player/fixture selections must be unique")
        eligible_pairs = set(keys)
        if any((item.player_id, item.participant_id) not in eligible_pairs for item in self.call_ups):
            raise ValueError("call-up offer requires authored national eligibility")

    def to_json(self) -> str:
        return dumps(self)

    @classmethod
    def from_json(cls, value: str) -> NationalSelectionBook:
        try:
            return loads(value, cls)
        except SerializationError as exc:
            raise ValueError(f"invalid national selection book: {exc}") from exc


def offer_national_call_up(
    book: NationalSelectionBook,
    schedule: WorldSeasonSchedule,
    *,
    player_id: PlayerId,
    fixture_id: str,
    offered_on: WorldDate,
    response_by: WorldDate,
) -> NationalSelectionBook:
    """Create a stable offer only for an eligible player in a representative fixture."""
    if not isinstance(book, NationalSelectionBook) or not isinstance(schedule, WorldSeasonSchedule):
        raise TypeError("call-up offer requires a selection book and world schedule")
    fixture = next((item for item in schedule.fixtures if item.fixture_id == fixture_id), None)
    if fixture is None:
        raise KeyError(f"unknown call-up fixture: {fixture_id}")
    competition = schedule.competition(fixture.competition_id)
    if competition.kind is not CompetitionKind.REPRESENTATIVE:
        raise ValueError("national call-ups only apply to representative competitions")
    if fixture.scheduled_on <= response_by:
        raise ValueError("call-up response deadline must precede the scheduled fixture")
    named_for_participant = (
        fixture.home_sheet.starters + fixture.away_sheet.starters
        if player_id in {
            item.profile.player_id
            for sheet in (fixture.home_sheet, fixture.away_sheet)
            for item in sheet.starters
        }
        else ()
    )
    selected_profiles = tuple(item.profile for item in named_for_participant)
    selected_profiles += fixture.home_sheet.substitutes + fixture.away_sheet.substitutes
    if not any(item.player_id == player_id for item in selected_profiles):
        raise ValueError("call-up player must be named as a starter or substitute in that fixture")
    participant_id = (
        fixture.home_participant_id
        if any(item.profile.player_id == player_id for item in fixture.home_sheet.starters)
        or any(item.player_id == player_id for item in fixture.home_sheet.substitutes)
        else fixture.away_participant_id
    )
    eligibility = next((item for item in book.eligibility
                        if item.player_id == player_id and item.participant_id == participant_id), None)
    if eligibility is None or not eligibility.valid_on(fixture.scheduled_on):
        raise ValueError("player lacks valid eligibility for the selected representative side")
    existing = next((item for item in book.call_ups
                     if item.player_id == player_id and item.fixture_id == fixture_id), None)
    offer_id = derive_id("call-up", "p16b-national-call-up-v1", player_id,
                         participant_id, fixture.competition_id, fixture.fixture_id)
    candidate = NationalCallUpOffer(
        offer_id, player_id, participant_id, fixture.competition_id, fixture.fixture_id,
        fixture.scheduled_on, offered_on, response_by,
    )
    if existing is not None:
        if replace(existing, decision=None, responded_on=None) != candidate:
            raise ValueError("national call-up was already offered with different terms")
        return book
    return replace(book, call_ups=book.call_ups + (candidate,))


def respond_to_national_call_up(
    book: NationalSelectionBook,
    offer_id: str,
    decision: CallUpDecision,
    responded_on: WorldDate,
) -> NationalSelectionBook:
    if not isinstance(book, NationalSelectionBook) or not isinstance(decision, CallUpDecision):
        raise TypeError("call-up response requires a selection book and registered decision")
    if not isinstance(responded_on, WorldDate):
        raise TypeError("call-up response requires its world date")
    offer = next((item for item in book.call_ups if item.offer_id == offer_id), None)
    if offer is None:
        raise KeyError(f"unknown national call-up offer: {offer_id}")
    if offer.decision is not None:
        if (offer.decision, offer.responded_on) == (decision, responded_on):
            return book
        raise ValueError("national call-up response conflicts with its recorded decision")
    if not offer.offered_on <= responded_on <= offer.response_by:
        raise ValueError("national call-up response is outside its dated response window")
    updated = replace(offer, decision=decision, responded_on=responded_on)
    return replace(book, call_ups=tuple(updated if item.offer_id == offer_id else item
                                         for item in book.call_ups))


@dataclass(frozen=True)
class WorldPlayerCondition:
    player_id: PlayerId
    match_readiness: float
    accumulated_fatigue: float
    medical_profile: MedicalProfile

    def __post_init__(self) -> None:
        validate_id(self.player_id, kind="world condition player ID")
        for label, value in (("readiness", self.match_readiness), ("fatigue", self.accumulated_fatigue)):
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"world player {label} must be normalized to [0, 1]")
        if not isinstance(self.medical_profile, MedicalProfile):
            raise TypeError("world condition requires a medical risk profile")
        if self.medical_profile.player_id != self.player_id:
            raise ValueError("world medical profile belongs to another player")


@dataclass(frozen=True)
class WorldExposureResolution:
    fixture_id: str
    match_id: MatchId
    player_id: PlayerId
    occurred_on: WorldDate
    minutes_played: float
    exertion: float
    injury_probability: float
    injury_roll: float | None
    exposure_id: str
    injury_id: str | None
    match_state_sha256: str

    def __post_init__(self) -> None:
        validate_id(self.fixture_id, kind="world exposure fixture ID")
        validate_id(self.match_id, kind="world exposure match ID")
        validate_id(self.player_id, kind="world exposure player ID")
        if not isinstance(self.occurred_on, WorldDate):
            raise TypeError("world exposure requires a date")
        if (type(self.minutes_played) not in (int, float)
                or not math.isfinite(self.minutes_played)
                or not 0 <= self.minutes_played <= 150):
            raise ValueError("world exposure minutes must be finite and in [0, 150]")
        if (type(self.exertion) not in (int, float)
                or not math.isfinite(self.exertion) or not 0 <= self.exertion <= 1):
            raise ValueError("world exposure exertion must be finite and in [0, 1]")
        if (type(self.injury_probability) not in (int, float)
                or not math.isfinite(self.injury_probability)
                or not 0 <= self.injury_probability <= 0.25):
            raise ValueError("world exposure injury probability must be finite and in [0, 0.25]")
        if self.minutes_played == 0 and self.exertion != 0:
            raise ValueError("unused player exposure must have zero exertion")
        if self.minutes_played == 0 and self.injury_probability != 0:
            raise ValueError("unused player exposure cannot carry injury risk")
        if self.injury_probability == 0 and self.injury_roll is not None:
            raise ValueError("zero-risk exposure cannot consume a medical random draw")
        if self.injury_probability > 0 and self.minutes_played > 0:
            if self.injury_roll is None or not 0 <= self.injury_roll < 1:
                raise ValueError("played positive-risk exposure requires its actual draw")
            if self.injury_roll < self.injury_probability and self.injury_id is None:
                raise ValueError("successful injury draw requires its deterministic injury record")
        validate_id(self.exposure_id, kind="world exposure ID")
        expected_exposure_id = derive_id(
            "world-exposure", "p16b-match-exposure-v1",
            self.fixture_id, self.match_id, self.player_id,
        )
        if self.exposure_id != expected_exposure_id:
            raise ValueError("world exposure ID must retain its scheduled fixture/player identity")
        if self.injury_id is not None:
            validate_id(self.injury_id, kind="world injury ID")
            if self.injury_roll is None or self.injury_roll >= self.injury_probability:
                raise ValueError("world injury must follow its successful recorded draw")
            expected_injury_id = derive_id(
                "world-injury", "p16b-match-injury-v1", self.exposure_id,
            )
            if self.injury_id != expected_injury_id:
                raise ValueError("world injury ID must retain its source exposure")
        _validate_sha256(self.match_state_sha256, "world exposure match-state hash")


@dataclass(frozen=True)
class WorldFixtureSettlement:
    fixture_id: str
    match_id: MatchId
    competition_id: str
    scheduled_on: WorldDate
    input_sha256: str
    match_state_sha256: str
    pre_match_conditions_sha256: str
    exposure_sha256: str

    def __post_init__(self) -> None:
        for value, label in ((self.fixture_id, "settled fixture ID"),
                             (self.match_id, "settled match ID"),
                             (self.competition_id, "settled competition ID")):
            validate_id(value, kind=label)
        if not isinstance(self.scheduled_on, WorldDate):
            raise TypeError("world fixture settlement requires its scheduled date")
        for value, label in ((self.input_sha256, "fixture input hash"),
                             (self.match_state_sha256, "match-state hash"),
                             (self.pre_match_conditions_sha256, "pre-match condition hash"),
                             (self.exposure_sha256, "exposure projection hash")):
            _validate_sha256(value, label)


@dataclass(frozen=True)
class WorldFlowInputs:
    """Season-constant inputs stored once beside small rolling checkpoints."""

    world_id: str
    season_id: str
    schedule_sha256: str
    starting_on: WorldDate
    seed: int
    profiles: tuple[PlayerProfile, ...]
    medical_profiles: tuple[MedicalProfile, ...]
    initial_injuries: tuple[InjuryEpisode, ...]
    registration: RegistrationBook
    national_selection: NationalSelectionBook
    policy: PreparationPolicy
    match_exertion: float
    schema_version: int = 1

    def __post_init__(self) -> None:
        validate_id(self.world_id, kind="flow input world ID")
        validate_id(self.season_id, kind="flow input season ID")
        _validate_sha256(self.schedule_sha256, "flow input schedule hash")
        if not isinstance(self.starting_on, WorldDate):
            raise TypeError("world flow inputs require a start date")
        if type(self.seed) is not int or not 0 <= self.seed < 2**63:
            raise ValueError("world flow input seed must be a non-negative signed 64-bit integer")
        if not isinstance(self.profiles, tuple) or not self.profiles or any(
                not isinstance(item, PlayerProfile) for item in self.profiles):
            raise TypeError("world flow inputs require immutable player profiles")
        if any(item.readiness.sampled_on > self.starting_on
               or (item.readiness.provenance.evidence_date is not None
                   and item.readiness.provenance.evidence_date > item.readiness.sampled_on)
               for item in self.profiles):
            raise ValueError("world flow readiness and evidence dates cannot follow the immutable start")
        if (not isinstance(self.medical_profiles, tuple)
                or any(not isinstance(item, MedicalProfile) for item in self.medical_profiles)
                or {item.player_id for item in self.medical_profiles}
                != {item.player_id for item in self.profiles}
                or len({item.player_id for item in self.medical_profiles}) != len(self.medical_profiles)):
            raise ValueError("world flow medical inputs must match the player profile catalog")
        profile_ids = {item.player_id for item in self.profiles}
        if len(profile_ids) != len(self.profiles):
            raise ValueError("world flow profile catalog cannot repeat a player")
        if (not isinstance(self.initial_injuries, tuple)
                or any(not isinstance(item, InjuryEpisode) for item in self.initial_injuries)):
            raise TypeError("initial world injury state must be an immutable episode tuple")
        if (len({item.injury_id for item in self.initial_injuries}) != len(self.initial_injuries)
                or any(item.player_id not in profile_ids
                       or not _injury_episode_is_known_by(item, self.starting_on)
                       for item in self.initial_injuries)):
            raise ValueError("initial world injuries must be unique, rostered and fully dated by the start")
        if not isinstance(self.registration, RegistrationBook):
            raise TypeError("world flow inputs require competition registrations")
        if not isinstance(self.national_selection, NationalSelectionBook):
            raise TypeError("world flow inputs require national eligibility/call-up records")
        if not isinstance(self.policy, PreparationPolicy):
            raise TypeError("world flow inputs require a P09 preparation policy")
        if type(self.match_exertion) not in (float, int) or not math.isfinite(self.match_exertion) or not 0 <= self.match_exertion <= 1:
            raise ValueError("world flow input exertion must be normalized")
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("unsupported world flow input version")

    @property
    def inputs_sha256(self) -> str:
        return hashlib.sha256(immutable_snapshot_json(self).encode("utf-8")).hexdigest()

    def restore_checkpoint(self, checkpoint: WorldFlowCheckpoint) -> WorldCompetitionState:
        if not isinstance(checkpoint, WorldFlowCheckpoint):
            raise TypeError("world flow restore requires a validated checkpoint")
        if (checkpoint.world_id, checkpoint.season_id, checkpoint.initial_state_sha256) != (
                self.world_id, self.season_id, self.inputs_sha256):
            raise ValueError("world checkpoint belongs to different immutable flow inputs")
        return WorldCompetitionState(
            world_id=self.world_id,
            season_id=self.season_id,
            schedule_sha256=self.schedule_sha256,
            initial_state_sha256=self.inputs_sha256,
            starting_on=self.starting_on,
            world_date=checkpoint.world_date,
            seed=self.seed,
            profiles=self.profiles,
            initial_injuries=self.initial_injuries,
            registration=self.registration,
            national_selection=self.national_selection,
            conditions=checkpoint.conditions,
            injury_history=checkpoint.injury_history,
            random_streams=checkpoint.random_streams,
            policy=self.policy,
            match_exertion=float(self.match_exertion),
            revision=checkpoint.revision,
            last_fixture_id=checkpoint.last_fixture_id,
            last_match_id=checkpoint.last_match_id,
            last_fixture_on=checkpoint.last_fixture_on,
            last_input_sha256=checkpoint.last_input_sha256,
            last_match_state_sha256=checkpoint.last_match_state_sha256,
            last_pre_match_conditions_sha256=checkpoint.last_pre_match_conditions_sha256,
            last_exposure_sha256=checkpoint.last_exposure_sha256,
        )


@dataclass(frozen=True)
class WorldFlowCheckpoint:
    """Bounded mutable checkpoint; fixture analytics live in normalized rows."""

    world_id: str
    season_id: str
    initial_state_sha256: str
    world_date: WorldDate
    conditions: tuple[WorldPlayerCondition, ...]
    injury_history: tuple[InjuryEpisode, ...]
    random_streams: RandomStreams
    revision: int
    last_fixture_id: str | None = None
    last_match_id: MatchId | None = None
    last_fixture_on: WorldDate | None = None
    last_input_sha256: str | None = None
    last_match_state_sha256: str | None = None
    last_pre_match_conditions_sha256: str | None = None
    last_exposure_sha256: str | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        validate_id(self.world_id, kind="checkpoint world ID")
        validate_id(self.season_id, kind="checkpoint season ID")
        _validate_sha256(self.initial_state_sha256, "checkpoint initial input hash")
        if not isinstance(self.world_date, WorldDate):
            raise TypeError("world checkpoint requires a date")
        if not isinstance(self.conditions, tuple) or any(not isinstance(item, WorldPlayerCondition) for item in self.conditions):
            raise TypeError("world checkpoint conditions must be immutable records")
        condition_ids = [item.player_id for item in self.conditions]
        if len(condition_ids) != len(set(condition_ids)):
            raise ValueError("world checkpoint cannot repeat a player's condition")
        if not isinstance(self.injury_history, tuple) or any(not isinstance(item, InjuryEpisode) for item in self.injury_history):
            raise TypeError("world checkpoint injuries must be immutable records")
        if (len({item.injury_id for item in self.injury_history}) != len(self.injury_history)
                or any(not _injury_episode_is_known_by(item, self.world_date)
                       for item in self.injury_history)):
            raise ValueError("world checkpoint injury history must be unique and no later than its date")
        if not isinstance(self.random_streams, RandomStreams) or "medical" not in self.random_streams.streams:
            raise ValueError("world checkpoint requires an isolated medical random stream")
        if type(self.revision) is not int or self.revision < 0:
            raise ValueError("world checkpoint revision must be non-negative")
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("unsupported world flow checkpoint version")
        tail = (self.last_fixture_id, self.last_match_id, self.last_fixture_on,
                self.last_input_sha256, self.last_match_state_sha256,
                self.last_pre_match_conditions_sha256, self.last_exposure_sha256)
        if self.revision == 0:
            if any(value is not None for value in tail):
                raise ValueError("initial world checkpoint cannot name a settled fixture")
        else:
            for value, label in ((self.last_fixture_id, "last fixture ID"),
                                 (self.last_match_id, "last match ID")):
                if value is None:
                    raise ValueError(f"world checkpoint requires its {label}")
                validate_id(value, kind=label)
            if not isinstance(self.last_fixture_on, WorldDate) or self.last_fixture_on > self.world_date:
                raise ValueError("world checkpoint date cannot precede the last fixture")
            for value, label in ((self.last_input_sha256, "last fixture input hash"),
                                 (self.last_match_state_sha256, "last match-state hash"),
                                 (self.last_pre_match_conditions_sha256, "last pre-match condition hash"),
                                 (self.last_exposure_sha256, "last exposure hash")):
                _validate_sha256(value, label)

    @classmethod
    def from_json(cls, value: str) -> WorldFlowCheckpoint:
        try:
            return loads(value, cls)
        except SerializationError as exc:
            raise ValueError(f"invalid world flow checkpoint: {exc}") from exc


@dataclass(frozen=True)
class WorldCompetitionState:
    world_id: str
    season_id: str
    schedule_sha256: str
    initial_state_sha256: str
    starting_on: WorldDate
    world_date: WorldDate
    seed: int
    profiles: tuple[PlayerProfile, ...]
    initial_injuries: tuple[InjuryEpisode, ...]
    registration: RegistrationBook
    national_selection: NationalSelectionBook
    conditions: tuple[WorldPlayerCondition, ...]
    injury_history: tuple[InjuryEpisode, ...]
    random_streams: RandomStreams
    policy: PreparationPolicy = PreparationPolicy()
    match_exertion: float = 0.5
    revision: int = 0
    last_fixture_id: str | None = None
    last_match_id: MatchId | None = None
    last_fixture_on: WorldDate | None = None
    last_input_sha256: str | None = None
    last_match_state_sha256: str | None = None
    last_pre_match_conditions_sha256: str | None = None
    last_exposure_sha256: str | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        validate_id(self.world_id, kind="flow world ID")
        validate_id(self.season_id, kind="flow season ID")
        _validate_sha256(self.schedule_sha256, "flow schedule hash")
        _validate_sha256(self.initial_state_sha256, "initial flow-state hash")
        if not isinstance(self.starting_on, WorldDate) or not isinstance(self.world_date, WorldDate):
            raise TypeError("world flow state requires explicit calendar dates")
        if self.world_date < self.starting_on:
            raise ValueError("world flow date cannot precede its explicit start date")
        if type(self.seed) is not int or not 0 <= self.seed < 2**63:
            raise ValueError("world flow seed must be a non-negative signed 64-bit integer")
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("unsupported world competition-flow state version")
        if type(self.revision) is not int or self.revision < 0:
            raise ValueError("world flow revision must be a non-negative integer")
        if type(self.match_exertion) not in (float, int) or not math.isfinite(self.match_exertion) or not 0 <= self.match_exertion <= 1:
            raise ValueError("world match exertion must be explicitly normalized")
        if not isinstance(self.policy, PreparationPolicy):
            raise TypeError("world flow requires a versioned P09 preparation policy")
        if not isinstance(self.registration, RegistrationBook):
            raise TypeError("world flow requires an explicit registration book")
        if not isinstance(self.national_selection, NationalSelectionBook):
            raise TypeError("world flow requires an explicit national selection book")
        if not isinstance(self.random_streams, RandomStreams) or "medical" not in self.random_streams.streams:
            raise ValueError("world flow requires a persisted isolated medical random stream")
        records = (self.profiles, self.conditions, self.injury_history)
        if any(not isinstance(items, tuple) for items in records):
            raise TypeError("world flow profiles and histories must be immutable tuples")
        if not self.profiles or any(not isinstance(item, PlayerProfile) for item in self.profiles):
            raise TypeError("world flow requires an explicit player profile catalog")
        if any(item.readiness.sampled_on > self.starting_on
               or (item.readiness.provenance.evidence_date is not None
                   and item.readiness.provenance.evidence_date > item.readiness.sampled_on)
               for item in self.profiles):
            raise ValueError("world readiness and evidence dates cannot follow the immutable start")
        profile_ids = [item.player_id for item in self.profiles]
        condition_ids = [item.player_id for item in self.conditions]
        if len(profile_ids) != len(set(profile_ids)) or set(condition_ids) != set(profile_ids) or len(condition_ids) != len(profile_ids):
            raise ValueError("world conditions must match the unique player profile catalog")
        if any(not isinstance(item, WorldPlayerCondition) for item in self.conditions):
            raise TypeError("world condition catalog contains an invalid player record")
        if any(item.medical_profile.player_id != item.player_id for item in self.conditions):
            raise ValueError("world medical profile catalog is inconsistent")
        if any(not isinstance(item, InjuryEpisode) for item in self.injury_history):
            raise TypeError("world injury history contains an invalid episode")
        if (not isinstance(self.initial_injuries, tuple)
                or any(not isinstance(item, InjuryEpisode) for item in self.initial_injuries)):
            raise TypeError("initial world injuries must be immutable episode records")
        if (len({item.injury_id for item in self.initial_injuries}) != len(self.initial_injuries)
                or any(not _injury_episode_is_known_by(item, self.starting_on)
                       for item in self.initial_injuries)):
            raise ValueError("initial world injury history must be unique and no later than the start date")
        if any(item.player_id not in set(profile_ids)
               or not _injury_episode_is_known_by(item, self.world_date)
               for item in self.injury_history):
            raise ValueError("world injury history references an unknown or future player event")
        if len({item.injury_id for item in self.injury_history}) != len(self.injury_history):
            raise ValueError("world injury history cannot repeat an episode")
        injury_by_id = {item.injury_id: item for item in self.injury_history}
        if any(
            injury.injury_id not in injury_by_id
            or (injury_by_id[injury.injury_id].player_id,
                injury_by_id[injury.injury_id].source_exposure_id,
                injury_by_id[injury.injury_id].occurred_on)
               != (injury.player_id, injury.source_exposure_id, injury.occurred_on)
            for injury in self.initial_injuries
        ):
            raise ValueError("world injury history must preserve every initial injury's source identity")
        if self.inputs_sha256 != self.initial_state_sha256:
            raise ValueError("world flow immutable inputs do not match their initial fingerprint")
        if self.revision == 0:
            medical_by_id = {item.player_id: item.medical_profile for item in self.conditions}
            starting_conditions, starting_injuries = _initial_flow_condition_values(
                self.profiles, medical_by_id, self.initial_injuries,
                self.starting_on, self.policy,
            )
            expected_conditions, expected_injuries = _recover_condition_values(
                starting_conditions, starting_injuries, self.starting_on,
                self.world_date, self.policy,
            )
            if self.conditions != expected_conditions:
                raise ValueError("unsettled world conditions must match sampled readiness and dated P09 recovery")
            if self.injury_history != expected_injuries:
                raise ValueError("unsettled world injury history must match dated recovery from immutable inputs")
            expected_streams = RandomStreams.seeded(self.seed)
            expected_streams.stream("medical")
            if self.random_streams != expected_streams:
                raise ValueError("initial world random streams must start from the immutable seed")
            if any(value is not None for value in (
                    self.last_fixture_id, self.last_match_id, self.last_fixture_on,
                    self.last_input_sha256, self.last_match_state_sha256,
                    self.last_pre_match_conditions_sha256, self.last_exposure_sha256)):
                raise ValueError("initial world flow state cannot name a settled fixture")
        else:
            if self.last_fixture_id is None or self.last_match_id is None or not isinstance(self.last_fixture_on, WorldDate):
                raise ValueError("world flow state requires its last settled fixture")
            validate_id(self.last_fixture_id, kind="last fixture ID")
            validate_id(self.last_match_id, kind="last match ID")
            if self.last_fixture_on > self.world_date:
                raise ValueError("world condition date cannot precede the last match")
            for value, label in ((self.last_input_sha256, "last fixture input hash"),
                                 (self.last_match_state_sha256, "last match-state hash"),
                                 (self.last_pre_match_conditions_sha256, "last condition hash"),
                                 (self.last_exposure_sha256, "last exposure hash")):
                _validate_sha256(value, label)

    @property
    def state_sha256(self) -> str:
        return hashlib.sha256(self.checkpoint_json().encode("utf-8")).hexdigest()

    @property
    def inputs_sha256(self) -> str:
        return self.flow_inputs().inputs_sha256

    def flow_inputs(self) -> WorldFlowInputs:
        return WorldFlowInputs(
            self.world_id, self.season_id, self.schedule_sha256, self.starting_on,
            self.seed, self.profiles,
            tuple(item.medical_profile for item in self.conditions),
            self.initial_injuries,
            self.registration, self.national_selection,
            self.policy, float(self.match_exertion),
        )

    def checkpoint(self) -> WorldFlowCheckpoint:
        return WorldFlowCheckpoint(
            self.world_id, self.season_id, self.initial_state_sha256,
            self.world_date, self.conditions, self.injury_history,
            self.random_streams, self.revision, self.last_fixture_id,
            self.last_match_id, self.last_fixture_on, self.last_input_sha256,
            self.last_match_state_sha256, self.last_pre_match_conditions_sha256,
            self.last_exposure_sha256,
        )

    def checkpoint_json(self) -> str:
        return dumps(self.checkpoint())

    def with_checkpoint(self, checkpoint: WorldFlowCheckpoint) -> WorldCompetitionState:
        if not isinstance(checkpoint, WorldFlowCheckpoint):
            raise TypeError("world flow restore requires a validated checkpoint")
        if (checkpoint.world_id, checkpoint.season_id, checkpoint.initial_state_sha256) != (
                self.world_id, self.season_id, self.initial_state_sha256):
            raise ValueError("world flow checkpoint belongs to different immutable inputs")
        return replace(
            self,
            world_date=checkpoint.world_date,
            conditions=checkpoint.conditions,
            injury_history=checkpoint.injury_history,
            random_streams=checkpoint.random_streams,
            revision=checkpoint.revision,
            last_fixture_id=checkpoint.last_fixture_id,
            last_match_id=checkpoint.last_match_id,
            last_fixture_on=checkpoint.last_fixture_on,
            last_input_sha256=checkpoint.last_input_sha256,
            last_match_state_sha256=checkpoint.last_match_state_sha256,
            last_pre_match_conditions_sha256=checkpoint.last_pre_match_conditions_sha256,
            last_exposure_sha256=checkpoint.last_exposure_sha256,
        )

    def to_json(self) -> str:
        return dumps(self)

    @classmethod
    def from_json(cls, value: str) -> WorldCompetitionState:
        try:
            return loads(value, cls)
        except SerializationError as exc:
            raise ValueError(f"invalid world competition-flow state: {exc}") from exc


@dataclass(frozen=True)
class PlayerEligibilityDecision:
    fixture_id: str
    participant_id: str
    player_id: PlayerId
    eligible: bool
    availability: AvailabilityStatus
    reasons: tuple[str, ...]
    registration_check_id: str | None = None
    call_up_offer_id: str | None = None

    def __post_init__(self) -> None:
        validate_id(self.fixture_id, kind="eligibility fixture ID")
        validate_id(self.participant_id, kind="eligibility participant ID")
        validate_id(self.player_id, kind="eligibility player ID")
        if type(self.eligible) is not bool or not isinstance(self.availability, AvailabilityStatus):
            raise TypeError("player eligibility result has invalid status fields")
        if not isinstance(self.reasons, tuple) or any(not isinstance(item, str) or not item for item in self.reasons):
            raise ValueError("eligibility reasons must be immutable non-empty codes")
        if self.eligible != (not self.reasons):
            raise ValueError("eligible player decisions cannot contain blocking reasons")
        if self.registration_check_id is not None:
            validate_id(self.registration_check_id, kind="registration check ID")
        if self.call_up_offer_id is not None:
            validate_id(self.call_up_offer_id, kind="call-up offer ID")


class WorldFixtureIneligible(ValueError):
    def __init__(self, decisions: tuple[PlayerEligibilityDecision, ...]):
        self.decisions = decisions
        rendered = "; ".join(
            f"{item.player_id} for {item.participant_id}: {','.join(item.reasons)}"
            for item in decisions if not item.eligible
        )
        super().__init__(f"world fixture has ineligible selections: {rendered}")


@dataclass(frozen=True)
class WorldSimulationProgress:
    scheduled: int
    archived: int
    simulated_this_run: int
    resumed_this_run: int
    pending: int
    world_state_revision: int

    def __post_init__(self) -> None:
        for label, value in (("scheduled", self.scheduled), ("archived", self.archived),
                             ("simulated", self.simulated_this_run), ("resumed", self.resumed_this_run),
                             ("pending", self.pending), ("world-state revision", self.world_state_revision)):
            if type(value) is not int or value < 0:
                raise ValueError(f"simulation {label} must be a non-negative integer")
        if self.archived + self.pending != self.scheduled:
            raise ValueError("simulation progress must reconcile archived and pending fixtures")


def create_world_competition_state(
    schedule: WorldSeasonSchedule,
    *,
    profiles: tuple[PlayerProfile, ...],
    registration: RegistrationBook,
    national_selection: NationalSelectionBook,
    starting_on: WorldDate,
    seed: int | None = None,
    medical_profiles: tuple[MedicalProfile, ...] | None = None,
    initial_injuries: tuple[InjuryEpisode, ...] = (),
    policy: PreparationPolicy = PreparationPolicy(),
    match_exertion: float = 0.5,
) -> WorldCompetitionState:
    if not isinstance(schedule, WorldSeasonSchedule) or not isinstance(starting_on, WorldDate):
        raise TypeError("world flow initialization requires a schedule and start date")
    if (type(match_exertion) not in (int, float) or not math.isfinite(match_exertion)
            or not 0 <= match_exertion <= 1):
        raise ValueError("world flow exertion must be finite and normalized")
    if not isinstance(profiles, tuple) or not profiles or any(not isinstance(item, PlayerProfile) for item in profiles):
        raise TypeError("world flow initialization requires an explicit profile tuple")
    if not isinstance(initial_injuries, tuple) or any(not isinstance(item, InjuryEpisode) for item in initial_injuries):
        raise TypeError("initial world injuries must be an immutable InjuryEpisode tuple")
    if (len({item.injury_id for item in initial_injuries}) != len(initial_injuries)
            or any(item.player_id not in {profile.player_id for profile in profiles}
                   or not _injury_episode_is_known_by(item, starting_on)
                   for item in initial_injuries)):
        raise ValueError("initial world injuries must match the roster and be fully dated by the start")
    if any(item.readiness.sampled_on > starting_on for item in profiles):
        raise ValueError("initial player condition cannot use future readiness evidence")
    if any(item.readiness.provenance.evidence_date is not None
           and item.readiness.provenance.evidence_date > item.readiness.sampled_on
           for item in profiles):
        raise ValueError("readiness evidence date cannot follow its condition sample")
    first_fixture_day = min(item.scheduled_on for item in schedule.fixtures)
    if starting_on > first_fixture_day:
        raise ValueError("world flow must begin on or before the first scheduled fixture")
    if any(item.scheduled_on < starting_on for item in schedule.fixtures):
        raise ValueError("world schedule cannot contain fixtures before the flow start date")
    _validate_profile_catalog_matches_schedule(profiles, schedule)
    if medical_profiles is None:
        medical_profiles = tuple(MedicalProfile(item.player_id) for item in profiles)
    if (not isinstance(medical_profiles, tuple)
            or any(not isinstance(item, MedicalProfile) for item in medical_profiles)
            or {item.player_id for item in medical_profiles}
               != {item.player_id for item in profiles}
            or len({item.player_id for item in medical_profiles}) != len(medical_profiles)):
        raise ValueError("medical profile inputs must match the complete world player catalog")
    medical_map = {item.player_id: item for item in medical_profiles}
    profile_tuple = tuple(sorted(profiles, key=lambda item: str(item.player_id)))
    condition_tuple, starting_injuries = _initial_flow_condition_values(
        profile_tuple, medical_map, initial_injuries, starting_on, policy,
    )
    root_seed = schedule.seed if seed is None else seed
    if type(root_seed) is not int or not 0 <= root_seed < 2**63:
        raise ValueError("world flow seed must be a non-negative signed 64-bit integer")
    streams = RandomStreams.seeded(root_seed)
    streams.stream("medical")
    schedule_hash = hashlib.sha256(immutable_snapshot_json(schedule).encode("utf-8")).hexdigest()
    flow_inputs = WorldFlowInputs(
        schedule.world_id, schedule.season_id, schedule_hash, starting_on,
        root_seed, profile_tuple,
        tuple(sorted(medical_profiles, key=lambda item: str(item.player_id))),
        initial_injuries,
        registration, national_selection,
        policy, float(match_exertion),
    )
    initial_hash = flow_inputs.inputs_sha256
    return WorldCompetitionState(
        schedule.world_id, schedule.season_id, schedule_hash, initial_hash,
        starting_on, starting_on, root_seed, profile_tuple, initial_injuries,
        registration, national_selection, condition_tuple, starting_injuries,
        streams, policy,
        float(match_exertion), 0,
    )


def assess_fixture_selections(
    state: WorldCompetitionState,
    schedule: WorldSeasonSchedule,
    fixture: WorldFixture,
) -> tuple[PlayerEligibilityDecision, ...]:
    _assert_state_matches_schedule(state, schedule)
    if fixture not in schedule.fixtures:
        raise ValueError("eligibility check requires a fixture from the supplied world schedule")
    return _assess_fixture_selections(
        state, schedule.competition(fixture.competition_id), fixture,
    )


def _assess_fixture_selections(
    state: WorldCompetitionState,
    competition: WorldCompetition,
    fixture: WorldFixture,
) -> tuple[PlayerEligibilityDecision, ...]:
    if competition.competition_id != fixture.competition_id:
        raise ValueError("fixture eligibility requires its immutable competition definition")
    if state.world_date != fixture.scheduled_on:
        raise ValueError("player eligibility must be checked on the fixture's current world date")
    conditions = {item.player_id: item for item in state.conditions}
    injuries = _active_injuries(state)
    decisions: list[PlayerEligibilityDecision] = []
    for sheet, participant_id in ((fixture.home_sheet, fixture.home_participant_id),
                                  (fixture.away_sheet, fixture.away_participant_id)):
        named = tuple(item.profile for item in sheet.starters) + sheet.substitutes
        for profile in named:
            condition = conditions[profile.player_id]
            reasons: list[str] = []
            registration_id = None
            call_up_id = None
            if competition.kind is CompetitionKind.REPRESENTATIVE:
                eligible = any(item.player_id == profile.player_id
                               and item.participant_id == participant_id
                               and item.valid_on(fixture.scheduled_on)
                               for item in state.national_selection.eligibility)
                if not eligible:
                    reasons.append("representative_eligibility_missing")
                call_up = next((item for item in state.national_selection.call_ups
                                if item.player_id == profile.player_id
                                and item.participant_id == participant_id
                                and item.competition_id == fixture.competition_id
                                and item.fixture_id == fixture.fixture_id), None)
                if call_up is None:
                    reasons.append("call_up_missing")
                elif call_up.fixture_on != fixture.scheduled_on:
                    reasons.append("call_up_fixture_date_mismatch")
                elif call_up.decision is not CallUpDecision.ACCEPTED:
                    reasons.append("call_up_not_accepted")
                elif call_up.responded_on is None or call_up.responded_on > call_up.response_by:
                    reasons.append("call_up_response_late")
                else:
                    call_up_id = call_up.offer_id
            else:
                try:
                    check = check_existing_registration(
                        state.registration, fixture.competition_id, participant_id,
                        str(profile.player_id), fixture.scheduled_on,
                    )
                    registration_id = check.check_id
                    if not check.eligible:
                        reasons.extend(check.reasons)
                except KeyError:
                    reasons.append("competition_registration_missing")
            active = injuries.get(profile.player_id)
            if active is not None:
                availability = AvailabilityStatus.MEDICALLY_UNAVAILABLE
                reasons.append("active_injury")
            elif condition.match_readiness < state.policy.minimum_selection_readiness:
                availability = AvailabilityStatus.BELOW_SELECTION_READINESS
                reasons.append("below_selection_readiness")
            else:
                availability = AvailabilityStatus.SELECTABLE
            decisions.append(PlayerEligibilityDecision(
                fixture.fixture_id, participant_id, profile.player_id,
                not reasons, availability, tuple(dict.fromkeys(reasons)),
                registration_id, call_up_id,
            ))
    return tuple(decisions)


def _require_fixture_eligible(
    state: WorldCompetitionState,
    competition: WorldCompetition,
    fixture: WorldFixture,
) -> None:
    denied = tuple(item for item in _assess_fixture_selections(state, competition, fixture)
                   if not item.eligible)
    if denied:
        raise WorldFixtureIneligible(denied)


def _initial_flow_condition_values(
    profiles: tuple[PlayerProfile, ...],
    medical_by_id: dict[PlayerId, MedicalProfile],
    initial_injuries: tuple[InjuryEpisode, ...],
    starting_on: WorldDate,
    policy: PreparationPolicy,
) -> tuple[tuple[WorldPlayerCondition, ...], tuple[InjuryEpisode, ...]]:
    """Bring each sampled readiness and dated initial injury to the flow start."""
    conditions = {
        profile.player_id: WorldPlayerCondition(
            profile.player_id, profile.readiness.match_readiness,
            profile.readiness.accumulated_fatigue, medical_by_id[profile.player_id],
        )
        for profile in profiles
    }
    sample_dates = {item.player_id: item.readiness.sampled_on for item in profiles}
    source_dates = [*sample_dates.values(), *(item.occurred_on for item in initial_injuries)]
    first_date = min(source_dates)
    # Imported episodes describe their current state plus dated rehab contacts.
    # Rebuild them from the exposure day so future stage/contact facts cannot
    # leak backward into the condition history.
    episodes = tuple(InjuryEpisode(
        item.injury_id, item.player_id, item.source_exposure_id,
        item.occurred_on, injury_kind=item.injury_kind,
    ) for item in initial_injuries)
    for offset in range((starting_on.day - first_date.day).days + 1):
        current_day = WorldDate(first_date.day + timedelta(days=offset))
        eligible_episodes = tuple(item for item in episodes if item.occurred_on < current_day)
        future_episodes = tuple(item for item in episodes if item.occurred_on >= current_day)
        progressed = progress_medical_day(eligible_episodes, current_day)
        progressed_by_id = {item.injury_id: item for item in progressed}
        episodes = tuple(progressed_by_id.get(item.injury_id, item) for item in eligible_episodes) + future_episodes
        for target in initial_injuries:
            if target.occurred_on > current_day:
                continue
            position = next((index for index, item in enumerate(episodes)
                             if item.injury_id == target.injury_id), None)
            if position is None:
                continue
            episode = episodes[position]
            if current_day in target.rehabilitation_dates:
                episode = add_rehabilitation_contact(episode, current_day, return_to_play=False)
            if current_day in target.return_to_play_dates:
                episode = add_rehabilitation_contact(episode, current_day, return_to_play=True)
            episodes = episodes[:position] + (episode,) + episodes[position + 1:]
        active_ids = {item.player_id for item in episodes
                      if item.occurred_on < current_day and item.stage is not RehabStage.CLEARED}
        new_injuries: dict[PlayerId, int] = {}
        for episode in episodes:
            if episode.occurred_on == current_day:
                new_injuries[episode.player_id] = new_injuries.get(episode.player_id, 0) + 1
        for player_id, condition in tuple(conditions.items()):
            if sample_dates[player_id] >= current_day:
                continue
            injury_loss = new_injuries.get(player_id, 0) * policy.injury_readiness_loss
            # An injury is recorded after that date's exposure. Match-day
            # readiness loss applies once; dated daily recovery starts on the
            # following date, matching P09's settlement order.
            if injury_loss:
                conditions[player_id] = replace(
                    condition,
                    match_readiness=max(0.0, condition.match_readiness - injury_loss),
                )
                continue
            conditions[player_id] = replace(
                condition,
                match_readiness=min(
                    1.0,
                    condition.match_readiness + (
                        policy.injured_daily_readiness_recovery
                        if player_id in active_ids else policy.daily_readiness_recovery
                    ),
                ),
                accumulated_fatigue=max(
                    0.0, condition.accumulated_fatigue - policy.daily_fatigue_recovery,
                ),
            )
    replayed_by_id = {item.injury_id: item for item in episodes}
    if any(replayed_by_id.get(item.injury_id) != item for item in initial_injuries):
        raise ValueError("initial world injury stages and contacts do not match their dated replay")
    return tuple(sorted(conditions.values(), key=lambda item: str(item.player_id))), episodes


def _recover_condition_values(
    source_conditions: tuple[WorldPlayerCondition, ...],
    source_injuries: tuple[InjuryEpisode, ...],
    source_day: WorldDate,
    target_day: WorldDate,
    policy: PreparationPolicy,
) -> tuple[tuple[WorldPlayerCondition, ...], tuple[InjuryEpisode, ...]]:
    """Apply only dated P09 recovery, with no match or RNG side effects."""
    if target_day < source_day:
        raise ValueError("world condition cannot move backward in time")
    conditions = {item.player_id: item for item in source_conditions}
    episodes = source_injuries
    for offset in range(1, (target_day.day - source_day.day).days + 1):
        current_day = WorldDate(source_day.day + timedelta(days=offset))
        episodes = progress_medical_day(episodes, current_day)
        active_ids = {item.player_id for item in episodes if item.stage is not RehabStage.CLEARED}
        for player_id, condition in tuple(conditions.items()):
            conditions[player_id] = replace(
                condition,
                match_readiness=min(
                    1.0,
                    condition.match_readiness + (
                        policy.injured_daily_readiness_recovery
                        if player_id in active_ids else policy.daily_readiness_recovery
                    ),
                ),
                accumulated_fatigue=max(
                    0.0, condition.accumulated_fatigue - policy.daily_fatigue_recovery,
                ),
            )
    return tuple(sorted(conditions.values(), key=lambda item: str(item.player_id))), episodes


def advance_world_condition_to(state: WorldCompetitionState, day: WorldDate) -> WorldCompetitionState:
    if not isinstance(state, WorldCompetitionState) or not isinstance(day, WorldDate):
        raise TypeError("world recovery requires a flow state and date")
    if day < state.world_date:
        raise ValueError("world condition cannot move backward in time")
    if day == state.world_date:
        return state
    conditions, episodes = _recover_condition_values(
        state.conditions, state.injury_history, state.world_date, day, state.policy,
    )
    return replace(
        state,
        world_date=day,
        conditions=conditions,
        injury_history=episodes,
    )


def simulate_world_season(
    schedule: WorldSeasonSchedule,
    initial_state: WorldCompetitionState,
    archive: WorldArchiveStore,
    *,
    maximum_fixtures: int | None = None,
) -> tuple[WorldSimulationProgress, WorldCompetitionState]:
    """Resolve fixtures in calendar order with atomic match/state checkpoints."""
    if not isinstance(archive, WorldArchiveStore):
        raise TypeError("world-flow simulation requires a WorldArchiveStore")
    if maximum_fixtures is not None and (type(maximum_fixtures) is not int or maximum_fixtures < 0):
        raise ValueError("maximum fixture count must be a non-negative integer or None")
    _assert_state_matches_schedule(initial_state, schedule)
    state, checkpoint_sha = archive.initialize_world_flow(schedule, initial_state)
    settled_ids = archive.world_flow_fixture_ids()
    expected_ids = tuple(item.fixture_id for item in schedule.ordered_fixtures[:state.revision])
    if settled_ids != expected_ids:
        raise ValueError("world archive flow rows do not form the checkpoint's schedule prefix")
    if state.revision:
        latest = schedule.ordered_fixtures[state.revision - 1]
        if (state.last_fixture_id, state.last_match_id, state.last_fixture_on) != (
                latest.fixture_id, latest.match_id, latest.scheduled_on):
            raise ValueError("world flow checkpoint does not match the archived schedule prefix")
    simulated = resumed = 0
    for fixture in schedule.ordered_fixtures:
        if fixture.fixture_id in settled_ids:
            resumed += 1
            continue
        if maximum_fixtures is not None and simulated >= maximum_fixtures:
            break
        state = advance_world_condition_to(state, fixture.scheduled_on)
        decisions = assess_fixture_selections(state, schedule, fixture)
        denied = tuple(item for item in decisions if not item.eligible)
        if denied:
            raise WorldFixtureIneligible(denied)
        effective = _conditioned_fixture(state, fixture)
        competition = schedule.competition(fixture.competition_id)
        match = create_match(
            effective.home_sheet, effective.away_sheet,
            rules=competition.rules,
            seed=fixture_seed(schedule, fixture),
            match_id=fixture.match_id,
        )
        run_to_completion(match)
        if match.phase is not MatchPhase.FINISHED:
            raise RuntimeError(f"fixture {fixture.fixture_id} did not finish normally")
        record = WorldMatchRecord.create(schedule, fixture, match)
        pre_match_conditions_sha = _condition_snapshot_sha256(state)
        updated, exposures, settlement = _settle_fixture(
            state, schedule, fixture, record, pre_match_conditions_sha,
        )
        checkpoint_sha = archive.append_with_world_flow(
            record, updated, exposures, settlement,
            expected_previous_state_sha256=checkpoint_sha,
        )
        state = updated
        settled_ids += (fixture.fixture_id,)
        simulated += 1
    pending = len(schedule.fixtures) - state.revision
    progress = WorldSimulationProgress(
        len(schedule.fixtures), state.revision, simulated,
        resumed, pending, state.revision,
    )
    return progress, state


def _conditioned_fixture(state: WorldCompetitionState, fixture: WorldFixture) -> WorldFixture:
    conditions = {item.player_id: item for item in state.conditions}
    profiles = {item.player_id: item for item in state.profiles}

    def current_profile(profile: PlayerProfile) -> PlayerProfile:
        baseline = profiles[profile.player_id]
        if _without_readiness(baseline) != _without_readiness(profile):
            raise ValueError("fixture changed immutable player profile data")
        condition = conditions[profile.player_id]
        readiness = ReadinessSnapshot(
            profile.player_id, state.world_date, condition.match_readiness,
            condition.accumulated_fatigue,
            DataProvenance(
                ProvenanceKind.INFERRED, "p16b-world-condition-flow-v1", state.world_date,
            ),
        )
        return replace(baseline, readiness=readiness)

    def current_sheet(sheet: TeamSheet) -> TeamSheet:
        starters: list[PlayerState] = []
        for player in sheet.starters:
            profile = current_profile(player.profile)
            limits = limits_from_profile(profile)
            speed = math.hypot(player.motion.velocity_x_mps, player.motion.velocity_y_mps)
            if speed > limits.maximum_speed_mps:
                factor = limits.maximum_speed_mps / speed
                vx, vy = player.motion.velocity_x_mps * factor, player.motion.velocity_y_mps * factor
            else:
                vx, vy = player.motion.velocity_x_mps, player.motion.velocity_y_mps
            motion = replace(player.motion, limits=limits, velocity_x_mps=vx, velocity_y_mps=vy)
            starters.append(replace(player, profile=profile, motion=motion))
        substitutes = tuple(current_profile(profile) for profile in sheet.substitutes)
        return replace(sheet, starters=tuple(starters), substitutes=substitutes)

    return replace(fixture, home_sheet=current_sheet(fixture.home_sheet),
                   away_sheet=current_sheet(fixture.away_sheet))


def _settle_fixture(
    state: WorldCompetitionState,
    schedule: WorldSeasonSchedule,
    fixture: WorldFixture,
    record: WorldMatchRecord,
    pre_match_conditions_sha256: str,
) -> tuple[WorldCompetitionState, tuple[WorldExposureResolution, ...], WorldFixtureSettlement]:
    competition = schedule.competition(fixture.competition_id)
    if (record.fixture_id != fixture.fixture_id or record.match_id != fixture.match_id
            or record.input_sha256 != fixture_input_sha256(fixture, competition)
            or record.simulation_seed != fixture_seed(schedule, fixture)
            or record.ruleset_id != competition.rules.ruleset_id
            or record.scheduled_on != fixture.scheduled_on):
        raise ValueError("world exposure record conflicts with its scheduled match inputs")
    return _settle_fixture_projection(
        state, fixture, competition, match_id=record.match_id,
        input_sha256=record.input_sha256, match_state_sha256=record.state_sha256,
        scheduled_on=record.scheduled_on,
        player_minutes={item.player_id: float(item.minutes_played) for item in record.player_lines},
        pre_match_conditions_sha256=pre_match_conditions_sha256,
    )


def _settle_fixture_projection(
    state: WorldCompetitionState,
    fixture: WorldFixture,
    competition: WorldCompetition,
    *,
    match_id: MatchId,
    input_sha256: str,
    match_state_sha256: str,
    scheduled_on: WorldDate,
    player_minutes: dict[PlayerId, float],
    pre_match_conditions_sha256: str,
) -> tuple[WorldCompetitionState, tuple[WorldExposureResolution, ...], WorldFixtureSettlement]:
    """Recompute the P09 settlement from validated match-minute projections."""
    if (fixture.competition_id != competition.competition_id
            or match_id != fixture.match_id
            or scheduled_on != fixture.scheduled_on
            or input_sha256 != fixture_input_sha256(fixture, competition)):
        raise ValueError("world exposure record conflicts with its scheduled match inputs")
    profile_ids = {item.player_id for item in state.profiles}
    if (not isinstance(player_minutes, dict)
            or any(player_id not in profile_ids for player_id in player_minutes)
            or any(type(minutes) not in (float, int) or not math.isfinite(minutes)
                   or not 0 <= minutes <= 150 for minutes in player_minutes.values())):
        raise ValueError("world match minutes must be valid and belong to the immutable player catalog")
    if state.last_fixture_on is not None and state.last_fixture_on > fixture.scheduled_on:
        raise ValueError("world fixture settlement cannot move backward in calendar order")
    if fixture.scheduled_on != state.world_date:
        raise ValueError("world condition must advance to the fixture date before settlement")
    streams = copy.deepcopy(state.random_streams)
    episodes = list(state.injury_history)
    resolutions: list[WorldExposureResolution] = []
    updated_conditions: list[WorldPlayerCondition] = []
    for condition in sorted(state.conditions, key=lambda item: str(item.player_id)):
        minutes = float(player_minutes.get(condition.player_id, 0.0))
        exertion = state.match_exertion if minutes > 0 else 0.0
        recurring = any(item.player_id == condition.player_id
                        and item.injury_kind == "soft_tissue_strain" for item in episodes)
        risk = injury_probability(
            condition.medical_profile,
            minutes_played=minutes,
            exertion=exertion,
            fatigue=condition.accumulated_fatigue,
            recurrence=recurring,
        )
        roll = streams.stream("medical").random() if risk > 0 and minutes > 0 else None
        exposure_id = derive_id(
            "world-exposure", "p16b-match-exposure-v1", fixture.fixture_id,
            fixture.match_id, condition.player_id,
        )
        injury_id = derive_id("world-injury", "p16b-match-injury-v1", exposure_id) \
            if roll is not None and roll < risk else None
        resolutions.append(WorldExposureResolution(
            fixture.fixture_id, fixture.match_id, condition.player_id,
            fixture.scheduled_on, minutes, exertion, risk, roll, exposure_id, injury_id,
            match_state_sha256,
        ))
        readiness = condition.match_readiness
        fatigue = condition.accumulated_fatigue
        if minutes > 0:
            fraction = minutes / 90.0
            fatigue = min(1.0, fatigue + fraction * (
                state.policy.match_fatigue_per_90
                + state.policy.match_exertion_fatigue_per_90 * exertion
            ))
            readiness = max(0.0, readiness - fraction * (
                state.policy.match_readiness_loss_per_90
                + state.policy.match_exertion_readiness_loss_per_90 * exertion
            ))
        if injury_id is not None:
            readiness = max(0.0, readiness - state.policy.injury_readiness_loss)
            episodes.append(InjuryEpisode(
                injury_id, condition.player_id, exposure_id, fixture.scheduled_on,
            ))
        updated_conditions.append(replace(
            condition, match_readiness=readiness, accumulated_fatigue=fatigue,
        ))
    exposure_tuple = tuple(resolutions)
    settlement = WorldFixtureSettlement(
        fixture.fixture_id, fixture.match_id, fixture.competition_id,
        fixture.scheduled_on, input_sha256, match_state_sha256,
        pre_match_conditions_sha256, _hash_snapshot(exposure_tuple),
    )
    updated = replace(
        state,
        conditions=tuple(updated_conditions),
        injury_history=tuple(episodes),
        random_streams=streams,
        revision=state.revision + 1,
        last_fixture_id=fixture.fixture_id,
        last_match_id=fixture.match_id,
        last_fixture_on=fixture.scheduled_on,
        last_input_sha256=input_sha256,
        last_match_state_sha256=match_state_sha256,
        last_pre_match_conditions_sha256=pre_match_conditions_sha256,
        last_exposure_sha256=settlement.exposure_sha256,
    )
    return updated, exposure_tuple, settlement


def validate_world_flow_append(
    previous_state: WorldCompetitionState,
    fixture: WorldFixture,
    competition: WorldCompetition,
    record: WorldMatchRecord,
    updated_state: WorldCompetitionState,
    exposures: tuple[WorldExposureResolution, ...],
    settlement: WorldFixtureSettlement,
) -> None:
    """Rebuild an append from the prior checkpoint and match player minutes."""
    if not isinstance(previous_state, WorldCompetitionState):
        raise TypeError("world flow append validation requires its prior checkpoint")
    if not isinstance(record, WorldMatchRecord):
        raise TypeError("world flow append validation requires an archived match record")
    if (not isinstance(updated_state, WorldCompetitionState)
            or not isinstance(exposures, tuple)
            or any(not isinstance(item, WorldExposureResolution) for item in exposures)
            or not isinstance(settlement, WorldFixtureSettlement)):
        raise TypeError("world flow append validation requires typed settlement projections")
    pre_match = advance_world_condition_to(previous_state, fixture.scheduled_on)
    _require_fixture_eligible(pre_match, competition, fixture)
    effective_fixture = _conditioned_fixture(pre_match, fixture)
    expected_match_inputs = MatchInputSnapshot(
        effective_fixture.home_sheet, effective_fixture.away_sheet,
    )
    if record.match_state().input_snapshot != expected_match_inputs:
        raise ValueError("world match did not use the prior checkpoint's conditioned fixture profiles")
    expected = _settle_fixture_projection(
        pre_match, fixture, competition, match_id=record.match_id,
        input_sha256=record.input_sha256, match_state_sha256=record.state_sha256,
        scheduled_on=record.scheduled_on,
        player_minutes={item.player_id: float(item.minutes_played) for item in record.player_lines},
        pre_match_conditions_sha256=_condition_snapshot_sha256(pre_match),
    )
    if expected != (updated_state, exposures, settlement):
        raise ValueError(
            "world flow append does not reconcile to the prior checkpoint, match lines and P09 outcomes"
        )


def replay_world_flow_fixture(
    previous_state: WorldCompetitionState,
    fixture: WorldFixture,
    competition: WorldCompetition,
    *,
    match_state_sha256: str,
    match_input_sha256: str,
    player_minutes: dict[PlayerId, float],
    exposures: tuple[WorldExposureResolution, ...],
    settlement: WorldFixtureSettlement,
) -> WorldCompetitionState:
    """Replay one archived fixture's P09 transition and verify its projections."""
    pre_match = advance_world_condition_to(previous_state, fixture.scheduled_on)
    _require_fixture_eligible(pre_match, competition, fixture)
    effective_fixture = _conditioned_fixture(pre_match, fixture)
    expected_match_inputs = MatchInputSnapshot(
        effective_fixture.home_sheet, effective_fixture.away_sheet,
    )
    if match_input_snapshot_sha256(expected_match_inputs) != match_input_sha256:
        raise ValueError("archived world match did not use its replayed conditioned fixture profiles")
    expected = _settle_fixture_projection(
        pre_match, fixture, competition, match_id=fixture.match_id,
        input_sha256=fixture_input_sha256(fixture, competition),
        match_state_sha256=match_state_sha256, scheduled_on=fixture.scheduled_on,
        player_minutes=player_minutes,
        pre_match_conditions_sha256=_condition_snapshot_sha256(pre_match),
    )
    if expected[1:] != (exposures, settlement):
        raise ValueError(
            "archived world exposure or settlement does not reconcile to match lines and P09 outcomes"
        )
    return expected[0]


def _active_injuries(state: WorldCompetitionState) -> dict[PlayerId, InjuryEpisode]:
    active: dict[PlayerId, InjuryEpisode] = {}
    for item in state.injury_history:
        if item.stage is not RehabStage.CLEARED:
            active[item.player_id] = item
    return active


def _condition_snapshot_sha256(state: WorldCompetitionState) -> str:
    return _hash_snapshot((state.world_date, state.conditions, state.injury_history,
                           state.registration, state.national_selection))


def _without_readiness(profile: PlayerProfile) -> PlayerProfile:
    return replace(profile, readiness=replace(profile.readiness,
                                               sampled_on=WorldDate(date(1, 1, 1)),
                                               match_readiness=0.5,
                                               accumulated_fatigue=0.5,
                                               provenance=DataProvenance(
                                                   ProvenanceKind.AUTHORED,
                                                   "p16b.profile-catalog-comparison",
                                               )))


def _validate_profile_catalog_matches_schedule(
    profiles: tuple[PlayerProfile, ...], schedule: WorldSeasonSchedule,
) -> None:
    ids = [item.player_id for item in profiles]
    if len(ids) != len(set(ids)):
        raise ValueError("world flow profile IDs cannot repeat")
    required_ids = {
        item for fixture in schedule.fixtures
        for sheet in (fixture.home_sheet, fixture.away_sheet)
        for item in (
            tuple(player.profile.player_id for player in sheet.starters)
            + tuple(player.player_id for player in sheet.substitutes)
            + tuple(sheet.unavailable_player_ids)
        )
    }
    if required_ids - set(ids):
        raise ValueError("world flow profile catalog omits a scheduled player")
    profile_map = {item.player_id: item for item in profiles}
    for fixture in schedule.fixtures:
        for sheet in (fixture.home_sheet, fixture.away_sheet):
            for match_profile in tuple(item.profile for item in sheet.starters) + sheet.substitutes:
                base = profile_map.get(match_profile.player_id)
                if base is None or _without_readiness(base) != _without_readiness(match_profile):
                    raise ValueError("scheduled player profile differs from the immutable world catalog")


def _assert_state_matches_schedule(state: WorldCompetitionState, schedule: WorldSeasonSchedule) -> None:
    if not isinstance(state, WorldCompetitionState) or not isinstance(schedule, WorldSeasonSchedule):
        raise TypeError("world simulation requires typed state and schedule records")
    digest = hashlib.sha256(immutable_snapshot_json(schedule).encode("utf-8")).hexdigest()
    if (state.world_id, state.season_id, state.schedule_sha256) != (
            schedule.world_id, schedule.season_id, digest):
        raise ValueError("world flow state belongs to different immutable season inputs")
    first_fixture_day = schedule.ordered_fixtures[0].scheduled_on
    if state.starting_on > first_fixture_day:
        raise ValueError("world flow start date cannot follow the first scheduled fixture")
    if any(item.scheduled_on < state.starting_on for item in schedule.fixtures):
        raise ValueError("world schedule cannot contain fixtures before the flow start date")
    _validate_profile_catalog_matches_schedule(state.profiles, schedule)
    ordered_ids = tuple(item.fixture_id for item in schedule.ordered_fixtures)
    if state.revision > len(ordered_ids):
        raise ValueError("world flow checkpoint exceeds its immutable fixture schedule")
    if state.revision:
        expected = schedule.ordered_fixtures[state.revision - 1]
        if (state.last_fixture_id, state.last_match_id, state.last_fixture_on) != (
                expected.fixture_id, expected.match_id, expected.scheduled_on):
            raise ValueError("world flow checkpoint must refer to its chronological schedule prefix")


def _validate_sha256(value: str, label: str) -> None:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")


def _injury_episode_is_known_by(episode: InjuryEpisode, day: WorldDate) -> bool:
    dates = (episode.occurred_on, episode.stage_started_on,
             *episode.rehabilitation_dates, *episode.return_to_play_dates)
    if not all(item is None or item <= day for item in dates):
        return False
    # Stage labels and contact dates are one historical claim. Derive the
    # earliest transition dates using P09's daily order (progress first, then
    # dated contacts), so old injury records validate in bounded time.
    occurred_on = episode.occurred_on
    occurred_ordinal = occurred_on.day.toordinal()
    day_ordinal = day.day.toordinal()
    rehabilitation_start_ordinal = occurred_ordinal + MIN_ACUTE_DAYS
    rehab_dates = episode.rehabilitation_dates
    return_dates = episode.return_to_play_dates
    if any(item.day.toordinal() < rehabilitation_start_ordinal for item in rehab_dates):
        return False

    return_to_play_start = None
    if len(rehab_dates) >= 3:
        return_to_play_start = max(
            occurred_ordinal + MIN_REHABILITATION_DAYS,
            rehab_dates[2].day.toordinal() + 1,
        )
        if any(item.day.toordinal() >= return_to_play_start for item in rehab_dates):
            return False

    if day_ordinal < rehabilitation_start_ordinal:
        expected_stage, expected_start = RehabStage.ACUTE, None
        if rehab_dates or return_dates:
            return False
    elif return_to_play_start is None or day_ordinal < return_to_play_start:
        expected_stage = RehabStage.REHABILITATION
        expected_start = WorldDate(date.fromordinal(rehabilitation_start_ordinal))
        if return_dates:
            return False
    else:
        if any(item.day.toordinal() < return_to_play_start for item in return_dates):
            return False
        clear_start = None
        if len(return_dates) >= 2:
            clear_start = max(
                occurred_ordinal + MIN_RETURN_TO_PLAY_DAYS,
                return_dates[1].day.toordinal() + 1,
            )
            if any(item.day.toordinal() >= clear_start for item in return_dates):
                return False
        if clear_start is not None and day_ordinal >= clear_start:
            expected_stage = RehabStage.CLEARED
            expected_start = WorldDate(date.fromordinal(clear_start))
        else:
            expected_stage = RehabStage.RETURN_TO_PLAY
            expected_start = WorldDate(date.fromordinal(return_to_play_start))

    return episode.stage is expected_stage and episode.stage_started_on == expected_start


def _hash_snapshot(value: object) -> str:
    return hashlib.sha256(immutable_snapshot_json(_SnapshotEnvelope(value)).encode("utf-8")).hexdigest()


def flow_snapshot_sha256(value: object) -> str:
    """Hash one versioned flow projection with the module's canonical envelope."""
    return _hash_snapshot(value)


@dataclass(frozen=True)
class _SnapshotEnvelope:
    payload: object


__all__ = [
    "AvailabilityStatus",
    "CallUpDecision",
    "NationalCallUpOffer",
    "NationalEligibility",
    "NationalSelectionBook",
    "PlayerEligibilityDecision",
    "WorldCompetitionState",
    "WorldExposureResolution",
    "WorldFlowCheckpoint",
    "WorldFlowInputs",
    "WorldFixtureIneligible",
    "WorldFixtureSettlement",
    "WorldPlayerCondition",
    "WorldSimulationProgress",
    "advance_world_condition_to",
    "assess_fixture_selections",
    "create_world_competition_state",
    "flow_snapshot_sha256",
    "offer_national_call_up",
    "replay_world_flow_fixture",
    "respond_to_national_call_up",
    "validate_world_flow_append",
    "simulate_world_season",
]
