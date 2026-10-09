"""Dated preparation, exposure, selection and tactical-learning state for P09."""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, replace
from datetime import timedelta
from enum import Enum

from games.touchline.esb.events import EventEnvelope
from games.touchline.esb.ids import CareerId, ClubId, MatchId, PlayerId, derive_id, validate_id
from games.touchline.esb.model import DataProvenance, ProvenanceKind
from games.touchline.esb.people import PlayerProfile, ReadinessSnapshot
from games.touchline.esb.people.learning import UnitFamiliarity, record_unit_experience
from games.touchline.esb.people.medical import (
    InjuryEpisode,
    MedicalProfile,
    MIN_ACUTE_DAYS,
    MIN_REHABILITATION_CONTACT_DATES,
    MIN_REHABILITATION_DAYS,
    MIN_RETURN_TO_PLAY_CONTACT_DATES,
    MIN_RETURN_TO_PLAY_DAYS,
    RehabStage,
    add_rehabilitation_contact,
    injury_probability,
    progress_medical_day,
)
from games.touchline.esb.randomness import RandomStreams
from games.touchline.esb.serialization import SerializationError, dumps, loads
from games.touchline.esb.time import WorldDate


class TrainingKind(str, Enum):
    RECOVERY = "recovery"
    CONDITIONING = "conditioning"
    UNIT_REHEARSAL = "unit_rehearsal"
    REHABILITATION = "rehabilitation"
    RETURN_TO_PLAY = "return_to_play"


class SelectionStatus(str, Enum):
    MEDICALLY_UNAVAILABLE = "medically_unavailable"
    CLEARED_NOT_READY = "cleared_not_ready"
    SELECTABLE = "selectable"


@dataclass(frozen=True)
class PreparationFixture:
    match_id: MatchId
    scheduled_on: WorldDate

    def __post_init__(self) -> None:
        validate_id(self.match_id, kind="preparation fixture match ID")
        if not isinstance(self.scheduled_on, WorldDate):
            raise TypeError("preparation fixture requires an explicit world date")


@dataclass(frozen=True)
class PreparationPolicy:
    """Named provisional workload and selection coefficients for a career."""

    daily_training_minutes: int = 120
    day_before_fixture_minutes: int = 60
    day_after_fixture_minutes: int = 90
    minimum_selection_readiness: float = 0.72
    daily_fatigue_recovery: float = 0.04
    daily_readiness_recovery: float = 0.012
    injured_daily_readiness_recovery: float = 0.003
    recovery_fatigue_relief_per_hour: float = 0.08
    recovery_readiness_gain_per_hour: float = 0.06
    conditioning_fatigue_per_hour: float = 0.12
    conditioning_readiness_cost_per_hour: float = 0.025
    rehearsal_fatigue_per_hour: float = 0.035
    rehearsal_readiness_cost_per_hour: float = 0.008
    rehabilitation_fatigue_per_hour: float = 0.025
    return_to_play_fatigue_per_hour: float = 0.045
    return_to_play_readiness_gain_per_hour: float = 0.02
    match_fatigue_per_90: float = 0.12
    match_exertion_fatigue_per_90: float = 0.18
    match_readiness_loss_per_90: float = 0.08
    match_exertion_readiness_loss_per_90: float = 0.08
    injury_readiness_loss: float = 0.20

    def __post_init__(self) -> None:
        for label, value in (
            ("daily training minutes", self.daily_training_minutes),
            ("day-before fixture minutes", self.day_before_fixture_minutes),
            ("day-after fixture minutes", self.day_after_fixture_minutes),
        ):
            if type(value) is not int or value < 0 or value > 360:
                raise ValueError(f"{label} must be an integer in [0, 360]")
        for label, value in (
            ("minimum selection readiness", self.minimum_selection_readiness),
            ("daily fatigue recovery", self.daily_fatigue_recovery),
            ("daily readiness recovery", self.daily_readiness_recovery),
            ("injured daily readiness recovery", self.injured_daily_readiness_recovery),
            ("recovery fatigue relief", self.recovery_fatigue_relief_per_hour),
            ("recovery readiness gain", self.recovery_readiness_gain_per_hour),
            ("conditioning fatigue", self.conditioning_fatigue_per_hour),
            ("conditioning readiness cost", self.conditioning_readiness_cost_per_hour),
            ("rehearsal fatigue", self.rehearsal_fatigue_per_hour),
            ("rehearsal readiness cost", self.rehearsal_readiness_cost_per_hour),
            ("rehabilitation fatigue", self.rehabilitation_fatigue_per_hour),
            ("return-to-play fatigue", self.return_to_play_fatigue_per_hour),
            ("return-to-play readiness gain", self.return_to_play_readiness_gain_per_hour),
            ("match fatigue", self.match_fatigue_per_90),
            ("match exertion fatigue", self.match_exertion_fatigue_per_90),
            ("match readiness loss", self.match_readiness_loss_per_90),
            ("match exertion readiness loss", self.match_exertion_readiness_loss_per_90),
            ("injury readiness loss", self.injury_readiness_loss),
        ):
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError(f"{label} must be a finite non-negative value")
        if self.minimum_selection_readiness > 1.0:
            raise ValueError("minimum selection readiness cannot exceed 1")
        for label, value in (
            ("daily fatigue recovery", self.daily_fatigue_recovery),
            ("daily readiness recovery", self.daily_readiness_recovery),
            ("injured daily readiness recovery", self.injured_daily_readiness_recovery),
            ("injury readiness loss", self.injury_readiness_loss),
        ):
            if value > 1.0:
                raise ValueError(f"{label} cannot exceed 1")


@dataclass(frozen=True)
class PlayerPreparation:
    player_id: PlayerId
    match_readiness: float
    accumulated_fatigue: float

    def __post_init__(self) -> None:
        validate_id(self.player_id, kind="preparation player ID")
        for label, value in (
            ("match readiness", self.match_readiness),
            ("accumulated fatigue", self.accumulated_fatigue),
        ):
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{label} must be finite and normalized to [0, 1]")


@dataclass(frozen=True)
class TrainingSession:
    work_id: str
    scheduled_on: WorldDate
    participants: tuple[PlayerId, ...]
    kind: TrainingKind
    duration_minutes: int
    exertion: float = 0.5
    unit_id: str | None = None
    meaningful_repetitions: int = 0

    def __post_init__(self) -> None:
        validate_id(self.work_id, kind="preparation work ID")
        if not isinstance(self.scheduled_on, WorldDate):
            raise TypeError("training session requires an explicit world date")
        if not isinstance(self.participants, tuple) or not self.participants:
            raise ValueError("training session requires immutable participant IDs")
        for player_id in self.participants:
            validate_id(player_id, kind="training participant ID")
        if len(self.participants) != len(set(self.participants)):
            raise ValueError("a player cannot appear twice in one training session")
        if not isinstance(self.kind, TrainingKind):
            raise TypeError("training session requires a registered work kind")
        if type(self.duration_minutes) is not int or not 1 <= self.duration_minutes <= 360:
            raise ValueError("training duration must be an integer in [1, 360] minutes")
        if type(self.exertion) not in (int, float) or not math.isfinite(self.exertion) or not 0 <= self.exertion <= 1:
            raise ValueError("training exertion must be normalized to [0, 1]")
        if self.unit_id is not None:
            validate_id(self.unit_id, kind="training unit ID")
        if type(self.meaningful_repetitions) is not int or not 0 <= self.meaningful_repetitions <= 100:
            raise ValueError("meaningful repetitions must be an integer in [0, 100]")
        if self.kind is TrainingKind.UNIT_REHEARSAL:
            if self.unit_id is None or self.meaningful_repetitions == 0:
                raise ValueError("unit rehearsal requires a unit and meaningful repetitions")
        elif self.unit_id is not None or self.meaningful_repetitions != 0:
            raise ValueError("only a unit rehearsal can record tactical repetitions")


@dataclass(frozen=True)
class TrainingResult:
    work_id: str
    completed_on: WorldDate
    completed_player_ids: tuple[PlayerId, ...]
    skipped_player_reasons: tuple[tuple[PlayerId, str], ...] = ()

    def __post_init__(self) -> None:
        validate_id(self.work_id, kind="completed work ID")
        if not isinstance(self.completed_on, WorldDate):
            raise TypeError("training result requires a completion date")
        if not isinstance(self.completed_player_ids, tuple) or not isinstance(self.skipped_player_reasons, tuple):
            raise TypeError("training result lists must be immutable tuples")
        for player_id in self.completed_player_ids:
            validate_id(player_id, kind="completed training player ID")
        for entry in self.skipped_player_reasons:
            if not isinstance(entry, tuple) or len(entry) != 2:
                raise TypeError("skipped training reasons must be player/reason pairs")
            validate_id(entry[0], kind="skipped training player ID")
            if not isinstance(entry[1], str) or not entry[1].strip():
                raise ValueError("skipped work requires a reason")
        ids = list(self.completed_player_ids) + [item[0] for item in self.skipped_player_reasons]
        if len(ids) != len(set(ids)):
            raise ValueError("training result cannot complete and skip the same player")


@dataclass(frozen=True)
class ExposureInput:
    player_id: PlayerId
    minutes_played: float
    exertion: float

    def __post_init__(self) -> None:
        validate_id(self.player_id, kind="match exposure player ID")
        if type(self.minutes_played) not in (int, float) or not math.isfinite(self.minutes_played) or not 0 <= self.minutes_played <= 150:
            raise ValueError("played minutes must be finite and in [0, 150]")
        if type(self.exertion) not in (int, float) or not math.isfinite(self.exertion) or not 0 <= self.exertion <= 1:
            raise ValueError("match exertion must be normalized to [0, 1]")
        if self.minutes_played == 0 and self.exertion != 0:
            raise ValueError("unused players must record zero match exertion")


@dataclass(frozen=True)
class ExposureResolution:
    match_id: MatchId
    player_id: PlayerId
    occurred_on: WorldDate
    minutes_played: float
    exertion: float
    injury_probability: float
    injury_roll: float | None
    injury_id: str | None

    def __post_init__(self) -> None:
        validate_id(self.match_id, kind="resolved match ID")
        validate_id(self.player_id, kind="resolved exposure player ID")
        if not isinstance(self.occurred_on, WorldDate):
            raise TypeError("exposure result requires its world date")
        if type(self.minutes_played) not in (int, float) or not math.isfinite(self.minutes_played) or not 0 <= self.minutes_played <= 150:
            raise ValueError("resolved played minutes must be finite and in [0, 150]")
        for label, value in (("exertion", self.exertion), ("injury probability", self.injury_probability)):
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"resolved {label} must be normalized to [0, 1]")
        if self.injury_probability == 0 and self.injury_roll is not None:
            raise ValueError("zero-risk exposure cannot consume an injury draw")
        if self.injury_probability > 0 and self.minutes_played > 0:
            if self.injury_roll is None or not 0 <= self.injury_roll < 1:
                raise ValueError("positive-risk exposure requires its actual random draw")
        if self.injury_id is not None:
            validate_id(self.injury_id, kind="resolved injury ID")
            if self.injury_roll is None or self.injury_roll >= self.injury_probability:
                raise ValueError("injury result must follow its recorded successful risk draw")


@dataclass(frozen=True)
class SelectionAssessment:
    player_id: PlayerId
    status: SelectionStatus
    match_readiness: float
    accumulated_fatigue: float
    active_injury_id: str | None = None
    rehab_stage: RehabStage | None = None

    def __post_init__(self) -> None:
        validate_id(self.player_id, kind="selection player ID")
        if not isinstance(self.status, SelectionStatus):
            raise TypeError("selection assessment requires a registered status")
        for label, value in (("match readiness", self.match_readiness), ("fatigue", self.accumulated_fatigue)):
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"selection {label} must be normalized to [0, 1]")
        if self.active_injury_id is not None:
            validate_id(self.active_injury_id, kind="active injury ID")
        if self.status is SelectionStatus.MEDICALLY_UNAVAILABLE:
            if self.active_injury_id is None or self.rehab_stage is None or self.rehab_stage is RehabStage.CLEARED:
                raise ValueError("medical unavailability requires an active injury stage")
        elif self.active_injury_id is not None or self.rehab_stage is not None:
            raise ValueError("medically cleared assessments cannot name an active injury")


@dataclass(frozen=True)
class PreparationState:
    career_id: CareerId
    club_id: ClubId
    world_date: WorldDate
    profiles: tuple[PlayerProfile, ...]
    player_states: tuple[PlayerPreparation, ...]
    medical_profiles: tuple[MedicalProfile, ...]
    fixtures: tuple[PreparationFixture, ...]
    sessions: tuple[TrainingSession, ...]
    training_results: tuple[TrainingResult, ...]
    injury_history: tuple[InjuryEpisode, ...]
    exposure_results: tuple[ExposureResolution, ...]
    completed_fixture_ids: tuple[MatchId, ...]
    unit_familiarities: tuple[UnitFamiliarity, ...]
    random_streams: RandomStreams
    policy: PreparationPolicy = PreparationPolicy()
    schema_version: int = 1

    def __post_init__(self) -> None:
        validate_id(self.career_id, kind="preparation career ID")
        validate_id(self.club_id, kind="preparation club ID")
        if not isinstance(self.world_date, WorldDate):
            raise TypeError("preparation state requires a world date")
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("unsupported preparation state schema version")
        if not isinstance(self.policy, PreparationPolicy):
            raise TypeError("preparation state requires a versioned workload policy")
        tuple_fields = (
            self.profiles, self.player_states, self.medical_profiles, self.fixtures,
            self.sessions, self.training_results, self.injury_history,
            self.exposure_results, self.completed_fixture_ids, self.unit_familiarities,
        )
        if any(not isinstance(value, tuple) for value in tuple_fields):
            raise TypeError("preparation histories and records must be immutable tuples")
        if any(not isinstance(profile, PlayerProfile) for profile in self.profiles):
            raise TypeError("preparation profiles must be PlayerProfile records")
        if any(not isinstance(item, PlayerPreparation) for item in self.player_states):
            raise TypeError("preparation condition list contains an invalid record")
        if any(not isinstance(item, MedicalProfile) for item in self.medical_profiles):
            raise TypeError("medical profile list contains an invalid record")
        if any(not isinstance(item, PreparationFixture) for item in self.fixtures):
            raise TypeError("fixture list contains an invalid record")
        if any(not isinstance(item, TrainingSession) for item in self.sessions):
            raise TypeError("preparation schedule contains an invalid session")
        if any(not isinstance(item, TrainingResult) for item in self.training_results):
            raise TypeError("training results contain an invalid record")
        if any(not isinstance(item, InjuryEpisode) for item in self.injury_history):
            raise TypeError("medical history contains an invalid injury episode")
        if any(not isinstance(item, ExposureResolution) for item in self.exposure_results):
            raise TypeError("exposure ledger contains an invalid result")
        if any(not isinstance(item, UnitFamiliarity) for item in self.unit_familiarities):
            raise TypeError("unit familiarity list contains an invalid record")
        profile_ids = [profile.player_id for profile in self.profiles]
        state_ids = [item.player_id for item in self.player_states]
        medical_ids = [item.player_id for item in self.medical_profiles]
        if not profile_ids or len(profile_ids) != len(set(profile_ids)):
            raise ValueError("preparation profiles must be non-empty and unique")
        if set(state_ids) != set(profile_ids) or len(state_ids) != len(profile_ids):
            raise ValueError("preparation condition records must match the profile roster")
        if set(medical_ids) != set(profile_ids) or len(medical_ids) != len(profile_ids):
            raise ValueError("medical profiles must match the preparation roster")
        if any(profile.club_id != self.club_id for profile in self.profiles):
            raise ValueError("preparation profiles must belong to the preparation club")
        fixture_ids = [item.match_id for item in self.fixtures]
        fixture_days = [item.scheduled_on for item in self.fixtures]
        if len(fixture_ids) != len(set(fixture_ids)) or len(fixture_days) != len(set(fixture_days)):
            raise ValueError("preparation fixtures cannot repeat a match or calendar day")
        if any(item.scheduled_on < self.world_date for item in self.fixtures if item.match_id not in self.completed_fixture_ids):
            raise ValueError("unresolved preparation fixtures cannot precede the current world date")
        if any(item.match_id in self.completed_fixture_ids and item.scheduled_on > self.world_date for item in self.fixtures):
            raise ValueError("completed preparation fixtures cannot follow the current world date")
        session_ids = [item.work_id for item in self.sessions]
        if len(session_ids) != len(set(session_ids)):
            raise ValueError("preparation schedule cannot repeat a work ID")
        if any(set(item.participants) - set(profile_ids) for item in self.sessions):
            raise ValueError("training session references a player outside the roster")
        result_ids = [item.work_id for item in self.training_results]
        if len(result_ids) != len(set(result_ids)):
            raise ValueError("training work cannot be completed more than once")
        session_map = {item.work_id: item for item in self.sessions}
        result_map = {item.work_id: item for item in self.training_results}
        if set(result_ids) - set(session_ids):
            raise ValueError("training result must refer to scheduled work")
        due_work_ids = {
            item.work_id for item in self.sessions
            if item.scheduled_on <= self.world_date
        }
        if set(result_ids) != due_work_ids:
            raise ValueError("all past or current scheduled work must have one recorded result")
        for result in self.training_results:
            session = session_map[result.work_id]
            if result.completed_on != session.scheduled_on:
                raise ValueError("training result date must match its scheduled work date")
            result_players = set(result.completed_player_ids) | {
                player_id for player_id, _reason in result.skipped_player_reasons
            }
            if result_players != set(session.participants):
                raise ValueError("training result must explain every scheduled participant")
        work_minutes: dict[tuple[PlayerId, WorldDate], int] = {}
        for session in self.sessions:
            for player_id in session.participants:
                key = (player_id, session.scheduled_on)
                work_minutes[key] = work_minutes.get(key, 0) + session.duration_minutes
        for (player_id, scheduled_on), minutes in work_minutes.items():
            if minutes > available_training_minutes(self, player_id, scheduled_on):
                raise ValueError("scheduled work exceeds fixture-aware player preparation time")
        injury_ids = [item.injury_id for item in self.injury_history]
        if len(injury_ids) != len(set(injury_ids)):
            raise ValueError("medical history cannot repeat an injury episode")
        active_players = [item.player_id for item in self.injury_history if item.stage is not RehabStage.CLEARED]
        if len(active_players) != len(set(active_players)):
            raise ValueError("a player cannot have overlapping active injury episodes")
        exposure_keys = [(item.match_id, item.player_id) for item in self.exposure_results]
        if len(exposure_keys) != len(set(exposure_keys)):
            raise ValueError("exposure ledger cannot repeat a player/match pair")
        known_fixtures = set(fixture_ids)
        if set(self.completed_fixture_ids) - known_fixtures:
            raise ValueError("completed preparation fixtures must exist in the schedule")
        if len(self.completed_fixture_ids) != len(set(self.completed_fixture_ids)):
            raise ValueError("completed fixture IDs cannot repeat")
        fixture_map = {item.match_id: item for item in self.fixtures}
        exposure_by_match: dict[MatchId, list[ExposureResolution]] = {}
        for exposure in self.exposure_results:
            if exposure.match_id not in fixture_map:
                raise ValueError("exposure ledger references an unscheduled fixture")
            if exposure.occurred_on != fixture_map[exposure.match_id].scheduled_on:
                raise ValueError("exposure date must match the scheduled fixture date")
            exposure_by_match.setdefault(exposure.match_id, []).append(exposure)
        if set(exposure_by_match) != set(self.completed_fixture_ids):
            raise ValueError("completed fixtures and exposure settlements must match")
        if any(
            {item.player_id for item in exposure_by_match[match_id]} != set(profile_ids)
            for match_id in self.completed_fixture_ids
        ):
            raise ValueError("a completed fixture requires one exposure record per career player")
        exposure_sources = {
            derive_id("exposure", "p09-match", item.match_id, item.player_id): item
            for item in self.exposure_results
        }
        for injury in self.injury_history:
            if injury.occurred_on > self.world_date:
                raise ValueError("medical history cannot contain a future injury")
            source = exposure_sources.get(injury.source_exposure_id)
            if source is None or source.player_id != injury.player_id or source.injury_id != injury.injury_id:
                raise ValueError("injury history must match its actual injury-producing exposure")
            if source.occurred_on != injury.occurred_on:
                raise ValueError("injury date must match its source exposure")
        familiarity_keys = [(item.player_id, item.unit_id) for item in self.unit_familiarities]
        if len(familiarity_keys) != len(set(familiarity_keys)):
            raise ValueError("unit familiarity cannot repeat a player/unit pair")
        if set(item.player_id for item in self.unit_familiarities) - set(profile_ids):
            raise ValueError("unit familiarity references a player outside the roster")
        if not isinstance(self.random_streams, RandomStreams):
            raise TypeError("preparation state requires persisted random streams")
        if "medical" not in self.random_streams.streams:
            raise ValueError("preparation state requires its named medical random stream")
        if any(item.occurred_on > self.world_date for item in self.exposure_results):
            raise ValueError("exposure history cannot contain a future match")

    def to_json(self) -> str:
        return dumps(self)

    @classmethod
    def from_json(cls, value: str) -> PreparationState:
        try:
            return loads(value, cls)
        except SerializationError as exc:
            raise ValueError(f"invalid P09 preparation state: {exc}") from exc


def create_preparation_state(
    *,
    career_id: CareerId,
    club_id: ClubId,
    world_date: WorldDate,
    profiles: tuple[PlayerProfile, ...],
    seed: int,
    fixtures: tuple[PreparationFixture, ...] = (),
    medical_profiles: tuple[MedicalProfile, ...] | None = None,
    policy: PreparationPolicy = PreparationPolicy(),
) -> PreparationState:
    """Create an opt-in P09 career aggregate from explicit spatial profiles."""

    if not isinstance(profiles, tuple) or not profiles:
        raise ValueError("P09 preparation requires an explicit non-empty profile tuple")
    if not isinstance(world_date, WorldDate):
        raise TypeError("P09 preparation requires an explicit world date")
    profile_ids = [profile.player_id for profile in profiles]
    if len(profile_ids) != len(set(profile_ids)):
        raise ValueError("P09 preparation profiles cannot repeat players")
    if any(profile.club_id != club_id for profile in profiles):
        raise ValueError("P09 preparation accepts profiles for one club only")
    if any(profile.readiness.sampled_on > world_date for profile in profiles):
        raise ValueError("profile readiness cannot be sampled after preparation begins")
    canonical_profiles = tuple(loads(dumps(profile), PlayerProfile) for profile in profiles)
    if medical_profiles is None:
        medical_profiles = tuple(MedicalProfile(profile.player_id) for profile in canonical_profiles)
    if not isinstance(medical_profiles, tuple) or {item.player_id for item in medical_profiles} != set(profile_ids):
        raise ValueError("explicit medical profiles must match the complete spatial roster")
    if not isinstance(fixtures, tuple) or any(item.scheduled_on <= world_date for item in fixtures):
        raise ValueError("preparation fixtures must be an immutable tuple of future dates")
    if not isinstance(policy, PreparationPolicy):
        raise TypeError("P09 preparation requires an explicit policy")
    streams = RandomStreams.seeded(seed)
    streams.stream("medical")
    return PreparationState(
        career_id=career_id,
        club_id=club_id,
        world_date=world_date,
        profiles=tuple(sorted(canonical_profiles, key=lambda item: str(item.player_id))),
        player_states=tuple(sorted((
            PlayerPreparation(
                profile.player_id,
                profile.readiness.match_readiness,
                profile.readiness.accumulated_fatigue,
            ) for profile in canonical_profiles
        ), key=lambda item: str(item.player_id))),
        medical_profiles=tuple(sorted(medical_profiles, key=lambda item: str(item.player_id))),
        fixtures=tuple(sorted(fixtures, key=lambda item: (item.scheduled_on, str(item.match_id)))),
        sessions=(),
        training_results=(),
        injury_history=(),
        exposure_results=(),
        completed_fixture_ids=(),
        unit_familiarities=(),
        random_streams=streams,
        policy=policy,
    )


def _profile_map(state: PreparationState) -> dict[PlayerId, PlayerProfile]:
    return {item.player_id: item for item in state.profiles}


def _player_state_map(state: PreparationState) -> dict[PlayerId, PlayerPreparation]:
    return {item.player_id: item for item in state.player_states}


def _medical_profile_map(state: PreparationState) -> dict[PlayerId, MedicalProfile]:
    return {item.player_id: item for item in state.medical_profiles}


def _active_injury(state: PreparationState, player_id: PlayerId) -> InjuryEpisode | None:
    return next((item for item in reversed(state.injury_history)
                 if item.player_id == player_id and item.stage is not RehabStage.CLEARED), None)


def available_training_minutes(
    state: PreparationState, player_id: PlayerId, day: WorldDate
) -> int:
    """Return the calendar time cap after fixture-day and adjacent-day limits."""

    if not isinstance(state, PreparationState) or not isinstance(day, WorldDate):
        raise TypeError("training capacity requires preparation state and a world date")
    if player_id not in _profile_map(state):
        raise KeyError(f"unknown preparation player: {player_id}")
    fixture_dates = [item.scheduled_on.day for item in state.fixtures]
    if day.day in fixture_dates:
        return 0
    caps = [state.policy.daily_training_minutes]
    if any((fixture_day - day.day).days == 1 for fixture_day in fixture_dates):
        caps.append(state.policy.day_before_fixture_minutes)
    if any((day.day - fixture_day).days == 1 for fixture_day in fixture_dates):
        caps.append(state.policy.day_after_fixture_minutes)
    return min(caps)


def _projected_rehab_stage(
    state: PreparationState, episode: InjuryEpisode, day: WorldDate
) -> RehabStage:
    age_days = (day.day - episode.occurred_on.day).days
    if age_days < MIN_ACUTE_DAYS:
        return RehabStage.ACUTE
    if age_days < MIN_REHABILITATION_DAYS:
        return RehabStage.REHABILITATION
    planned_rehab_days = {
        item.scheduled_on for item in state.sessions
        if item.kind is TrainingKind.REHABILITATION
        and episode.player_id in item.participants
        and episode.occurred_on < item.scheduled_on < day
    }
    if len(set(episode.rehabilitation_dates) | planned_rehab_days) < MIN_REHABILITATION_CONTACT_DATES:
        return RehabStage.REHABILITATION
    if age_days < MIN_RETURN_TO_PLAY_DAYS:
        return RehabStage.RETURN_TO_PLAY
    planned_return_days = {
        item.scheduled_on for item in state.sessions
        if item.kind is TrainingKind.RETURN_TO_PLAY
        and episode.player_id in item.participants
        and episode.occurred_on < item.scheduled_on < day
    }
    if len(set(episode.return_to_play_dates) | planned_return_days) < MIN_RETURN_TO_PLAY_CONTACT_DATES:
        return RehabStage.RETURN_TO_PLAY
    return RehabStage.CLEARED


def schedule_training_session(
    state: PreparationState, session: TrainingSession
) -> PreparationState:
    """Schedule one dated session only when every participant has the time."""

    if not isinstance(state, PreparationState) or not isinstance(session, TrainingSession):
        raise TypeError("training schedule requires a preparation state and session")
    session = replace(
        session,
        participants=tuple(sorted(session.participants, key=str)),
    )
    existing = next((item for item in state.sessions if item.work_id == session.work_id), None)
    if existing is not None:
        if existing != session:
            raise ValueError("preparation work ID was reused with different inputs")
        return state
    if session.scheduled_on <= state.world_date:
        raise ValueError("training sessions must be scheduled after the current world date")
    profiles = _profile_map(state)
    if set(session.participants) - set(profiles):
        raise ValueError("training session references a player outside the career roster")
    if any(fixture.scheduled_on == session.scheduled_on for fixture in state.fixtures):
        raise ValueError("fixture days have no preparation training time")
    for player_id in session.participants:
        used = sum(
            item.duration_minutes for item in state.sessions
            if item.scheduled_on == session.scheduled_on and player_id in item.participants
        )
        available = available_training_minutes(state, player_id, session.scheduled_on)
        if used + session.duration_minutes > available:
            raise ValueError(
                f"{player_id} has {available - used} preparation minutes left on "
                f"{session.scheduled_on.isoformat}, not {session.duration_minutes}"
            )
    for player_id in session.participants:
        episode = _active_injury(state, player_id)
        if session.kind in (TrainingKind.REHABILITATION, TrainingKind.RETURN_TO_PLAY):
            if episode is None:
                raise ValueError("rehabilitation work requires an active injury episode")
            expected = (
                RehabStage.REHABILITATION
                if session.kind is TrainingKind.REHABILITATION
                else RehabStage.RETURN_TO_PLAY
            )
            if _projected_rehab_stage(state, episode, session.scheduled_on) is not expected:
                raise ValueError(f"{session.kind.value} work does not fit the projected rehab stage")
        elif episode is not None and session.kind in (TrainingKind.CONDITIONING, TrainingKind.UNIT_REHEARSAL):
            raise ValueError("an unavailable player cannot be scheduled for conditioning or unit rehearsal")
    sessions = tuple(sorted(
        state.sessions + (session,),
        key=lambda item: (item.scheduled_on, item.work_id),
    ))
    return replace(state, sessions=sessions)


def _set_condition(
    conditions: dict[PlayerId, PlayerPreparation],
    player_id: PlayerId,
    *,
    readiness_delta: float = 0.0,
    fatigue_delta: float = 0.0,
) -> None:
    current = conditions[player_id]
    conditions[player_id] = replace(
        current,
        match_readiness=min(1.0, max(0.0, current.match_readiness + readiness_delta)),
        accumulated_fatigue=min(1.0, max(0.0, current.accumulated_fatigue + fatigue_delta)),
    )


def advance_preparation_day(state: PreparationState, day: WorldDate) -> PreparationState:
    """Advance exactly one date, applying due work and medical stage changes once."""

    if not isinstance(state, PreparationState) or not isinstance(day, WorldDate):
        raise TypeError("calendar advance requires preparation state and world date")
    if day.day != state.world_date.day + timedelta(days=1):
        raise ValueError("preparation calendar advances one day at a time")
    unresolved_current = [item for item in state.fixtures
                         if item.scheduled_on == state.world_date
                         and item.match_id not in state.completed_fixture_ids]
    if unresolved_current:
        raise ValueError("settle the current fixture exposure before advancing the calendar")

    episodes = progress_medical_day(state.injury_history, day)
    active_by_player = {
        item.player_id: item for item in episodes if item.stage is not RehabStage.CLEARED
    }
    conditions = _player_state_map(state)
    for player_id in sorted(conditions, key=str):
        injured = player_id in active_by_player
        _set_condition(
            conditions,
            player_id,
            readiness_delta=(
                state.policy.injured_daily_readiness_recovery
                if injured else state.policy.daily_readiness_recovery
            ),
            fatigue_delta=-state.policy.daily_fatigue_recovery,
        )

    familiarity = {(item.player_id, item.unit_id): item for item in state.unit_familiarities}
    results: list[TrainingResult] = []
    sessions = sorted(
        (item for item in state.sessions if item.scheduled_on == day),
        key=lambda item: item.work_id,
    )
    profile_map = _profile_map(state)
    for session in sessions:
        completed: list[PlayerId] = []
        skipped: list[tuple[PlayerId, str]] = []
        hours = session.duration_minutes / 60.0
        for player_id in sorted(session.participants, key=str):
            episode = active_by_player.get(player_id)
            if session.kind in (TrainingKind.CONDITIONING, TrainingKind.UNIT_REHEARSAL) and episode is not None:
                skipped.append((player_id, "medically_unavailable"))
                continue
            if session.kind is TrainingKind.REHABILITATION:
                if episode is None or episode.stage is not RehabStage.REHABILITATION:
                    skipped.append((player_id, "rehabilitation_stage_not_active"))
                    continue
                position = episodes.index(episode)
                episodes = episodes[:position] + (
                    add_rehabilitation_contact(episode, day, return_to_play=False),
                ) + episodes[position + 1:]
                updated = episodes[position]
                active_by_player[player_id] = updated
                _set_condition(conditions, player_id,
                               fatigue_delta=state.policy.rehabilitation_fatigue_per_hour * hours)
            elif session.kind is TrainingKind.RETURN_TO_PLAY:
                if episode is None or episode.stage is not RehabStage.RETURN_TO_PLAY:
                    skipped.append((player_id, "return_to_play_stage_not_active"))
                    continue
                position = episodes.index(episode)
                episodes = episodes[:position] + (
                    add_rehabilitation_contact(episode, day, return_to_play=True),
                ) + episodes[position + 1:]
                updated = episodes[position]
                active_by_player[player_id] = updated
                _set_condition(
                    conditions,
                    player_id,
                    readiness_delta=state.policy.return_to_play_readiness_gain_per_hour * hours,
                    fatigue_delta=state.policy.return_to_play_fatigue_per_hour * hours,
                )
            elif session.kind is TrainingKind.RECOVERY:
                _set_condition(
                    conditions,
                    player_id,
                    readiness_delta=(0.0 if episode else state.policy.recovery_readiness_gain_per_hour * hours),
                    fatigue_delta=-state.policy.recovery_fatigue_relief_per_hour * hours,
                )
            elif session.kind is TrainingKind.CONDITIONING:
                _set_condition(
                    conditions,
                    player_id,
                    readiness_delta=-state.policy.conditioning_readiness_cost_per_hour * hours * session.exertion,
                    fatigue_delta=state.policy.conditioning_fatigue_per_hour * hours * session.exertion,
                )
            elif session.kind is TrainingKind.UNIT_REHEARSAL:
                _set_condition(
                    conditions,
                    player_id,
                    readiness_delta=-state.policy.rehearsal_readiness_cost_per_hour * hours * session.exertion,
                    fatigue_delta=state.policy.rehearsal_fatigue_per_hour * hours * session.exertion,
                )
                key = (player_id, session.unit_id)
                familiarity[key] = record_unit_experience(
                    familiarity.get(key),
                    profile_map[player_id],
                    unit_id=session.unit_id,
                    source_id=session.work_id,
                    meaningful_repetitions=session.meaningful_repetitions,
                )
            completed.append(player_id)
        results.append(TrainingResult(
            session.work_id,
            day,
            tuple(completed),
            tuple(skipped),
        ))

    return replace(
        state,
        world_date=day,
        player_states=tuple(sorted(conditions.values(), key=lambda item: str(item.player_id))),
        injury_history=episodes,
        training_results=state.training_results + tuple(results),
        unit_familiarities=tuple(sorted(
            familiarity.values(), key=lambda item: (str(item.player_id), item.unit_id)
        )),
    )


def selection_assessment(state: PreparationState, player_id: PlayerId) -> SelectionAssessment:
    """Read current medical eligibility and readiness without side effects."""

    if not isinstance(state, PreparationState):
        raise TypeError("selection assessment requires preparation state")
    conditions = _player_state_map(state)
    if player_id not in conditions:
        raise KeyError(f"unknown preparation player: {player_id}")
    condition = conditions[player_id]
    episode = _active_injury(state, player_id)
    if episode is not None:
        return SelectionAssessment(
            player_id,
            SelectionStatus.MEDICALLY_UNAVAILABLE,
            condition.match_readiness,
            condition.accumulated_fatigue,
            episode.injury_id,
            episode.stage,
        )
    status = (
        SelectionStatus.SELECTABLE
        if condition.match_readiness >= state.policy.minimum_selection_readiness
        else SelectionStatus.CLEARED_NOT_READY
    )
    return SelectionAssessment(
        player_id,
        status,
        condition.match_readiness,
        condition.accumulated_fatigue,
    )


def selection_assessments(state: PreparationState) -> tuple[SelectionAssessment, ...]:
    return tuple(
        selection_assessment(state, player_id)
        for player_id in sorted(_profile_map(state), key=str)
    )


def selectable_profiles(
    state: PreparationState, player_ids: tuple[PlayerId, ...] | None = None
) -> tuple[PlayerProfile, ...]:
    """Build current-condition profiles only for medically eligible, ready players."""

    if not isinstance(state, PreparationState):
        raise TypeError("selection profile generation requires preparation state")
    selected_ids = (
        tuple(sorted(_profile_map(state), key=str))
        if player_ids is None else player_ids
    )
    if not isinstance(selected_ids, tuple):
        raise TypeError("selected player IDs must be an immutable tuple")
    if len(selected_ids) != len(set(selected_ids)):
        raise ValueError("selection cannot repeat a player")
    result: list[PlayerProfile] = []
    for player_id in selected_ids:
        assessment = selection_assessment(state, player_id)
        if assessment.status is not SelectionStatus.SELECTABLE:
            raise ValueError(
                f"{player_id} is not selectable: {assessment.status.value}"
            )
        result.append(prepared_profile(state, player_id))
    return tuple(result)


def prepared_profile(state: PreparationState, player_id: PlayerId) -> PlayerProfile:
    """Return a profile snapshot with current condition for actual spatial play."""

    profiles = _profile_map(state)
    conditions = _player_state_map(state)
    if player_id not in profiles:
        raise KeyError(f"unknown preparation player: {player_id}")
    condition = conditions[player_id]
    readiness = ReadinessSnapshot(
        player_id=player_id,
        sampled_on=state.world_date,
        match_readiness=condition.match_readiness,
        accumulated_fatigue=condition.accumulated_fatigue,
        provenance=DataProvenance(
            ProvenanceKind.INFERRED,
            "p09-preparation-model-v1",
            state.world_date,
        ),
    )
    return replace(profiles[player_id], readiness=readiness)


def injury_risk_for_exposure(
    state: PreparationState, match_id: MatchId, exposure: ExposureInput
) -> float:
    """Inspect one player's provisional risk without drawing or mutating state."""

    if not isinstance(state, PreparationState) or not isinstance(exposure, ExposureInput):
        raise TypeError("injury risk query requires preparation state and exposure")
    fixture = next((item for item in state.fixtures if item.match_id == match_id), None)
    if (
        fixture is None
        or fixture.scheduled_on != state.world_date
        or match_id in state.completed_fixture_ids
    ):
        raise ValueError("injury risk can only be queried for the current scheduled fixture")
    if exposure.player_id not in _profile_map(state):
        raise KeyError(f"unknown preparation player: {exposure.player_id}")
    condition = _player_state_map(state)[exposure.player_id]
    recurring = any(
        item.player_id == exposure.player_id and item.injury_kind == "soft_tissue_strain"
        for item in state.injury_history
    )
    return injury_probability(
        _medical_profile_map(state)[exposure.player_id],
        minutes_played=exposure.minutes_played,
        exertion=exposure.exertion,
        fatigue=condition.accumulated_fatigue,
        recurrence=recurring,
    )


def settle_fixture_exposure(
    state: PreparationState,
    match_id: MatchId,
    exposures: tuple[ExposureInput, ...],
) -> PreparationState:
    """Record one complete fixture's minutes, condition, risk and injury history.

    All roster members must be present; unused players submit zero minutes.
    Players are resolved in stable ID order. Only positive, non-zero-risk match
    exposures consume one value from the isolated ``medical`` random stream.
    """

    if not isinstance(state, PreparationState) or not isinstance(exposures, tuple):
        raise TypeError("fixture exposure settlement requires immutable inputs")
    validate_id(match_id, kind="fixture exposure match ID")
    fixture = next((item for item in state.fixtures if item.match_id == match_id), None)
    if fixture is None or fixture.scheduled_on != state.world_date:
        raise ValueError("fixture exposure must match the current scheduled world date")
    if any(not isinstance(item, ExposureInput) for item in exposures):
        raise TypeError("fixture exposure list contains an invalid player record")
    roster = set(_profile_map(state))
    by_player = {item.player_id: item for item in exposures}
    if len(by_player) != len(exposures) or set(by_player) != roster:
        raise ValueError("fixture exposure must include each career player exactly once")

    existing = [item for item in state.exposure_results if item.match_id == match_id]
    if existing:
        expected = {
            item.player_id: (item.minutes_played, item.exertion)
            for item in existing
        }
        supplied = {
            item.player_id: (item.minutes_played, item.exertion)
            for item in exposures
        }
        if expected != supplied:
            raise ValueError("fixture exposure was already settled with different minutes")
        return state
    if match_id in state.completed_fixture_ids:
        raise ValueError("completed fixture is missing its exposure ledger")

    # Validate all players before consuming any random draws.
    for player_id, exposure in by_player.items():
        if exposure.minutes_played and _active_injury(state, player_id) is not None:
            raise ValueError(f"medically unavailable player {player_id} cannot record match minutes")

    working_streams = copy.deepcopy(state.random_streams)
    condition_map = _player_state_map(state)
    med_map = _medical_profile_map(state)
    previous_injuries = tuple(state.injury_history)
    resolutions: list[ExposureResolution] = []
    new_episodes: list[InjuryEpisode] = []
    for player_id in sorted(roster, key=str):
        exposure = by_player[player_id]
        condition = condition_map[player_id]
        recurrence = any(
            item.player_id == player_id and item.injury_kind == "soft_tissue_strain"
            for item in previous_injuries
        )
        probability = injury_probability(
            med_map[player_id],
            minutes_played=exposure.minutes_played,
            exertion=exposure.exertion,
            fatigue=condition.accumulated_fatigue,
            recurrence=recurrence,
        )
        roll = working_streams.stream("medical").random() if probability > 0 else None
        exposure_id = derive_id("exposure", "p09-match", match_id, player_id)
        injury_id = None
        if roll is not None and roll < probability:
            injury_id = derive_id("injury", "p09-soft-tissue", exposure_id)
            new_episodes.append(InjuryEpisode(
                injury_id=injury_id,
                player_id=player_id,
                source_exposure_id=exposure_id,
                occurred_on=state.world_date,
            ))
        resolutions.append(ExposureResolution(
            match_id=match_id,
            player_id=player_id,
            occurred_on=state.world_date,
            minutes_played=exposure.minutes_played,
            exertion=exposure.exertion,
            injury_probability=probability,
            injury_roll=roll,
            injury_id=injury_id,
        ))
        if exposure.minutes_played:
            fraction = exposure.minutes_played / 90.0
            fatigue_delta = fraction * (
                state.policy.match_fatigue_per_90
                + state.policy.match_exertion_fatigue_per_90 * exposure.exertion
            )
            readiness_delta = -fraction * (
                state.policy.match_readiness_loss_per_90
                + state.policy.match_exertion_readiness_loss_per_90 * exposure.exertion
            )
            if injury_id is not None:
                readiness_delta -= state.policy.injury_readiness_loss
            condition_map[player_id] = replace(
                condition,
                accumulated_fatigue=min(1.0, condition.accumulated_fatigue + fatigue_delta),
                match_readiness=max(0.0, condition.match_readiness + readiness_delta),
            )

    return replace(
        state,
        player_states=tuple(sorted(condition_map.values(), key=lambda item: str(item.player_id))),
        injury_history=state.injury_history + tuple(new_episodes),
        exposure_results=state.exposure_results + tuple(resolutions),
        completed_fixture_ids=state.completed_fixture_ids + (match_id,),
        random_streams=working_streams,
    )


def record_unit_match_experience(
    state: PreparationState,
    *,
    source_event: EventEnvelope,
    unit_id: str,
    player_ids: tuple[PlayerId, ...],
    meaningful_repetitions: int,
) -> PreparationState:
    """Record familiarity from a real, completed match event and its participants."""

    if not isinstance(state, PreparationState) or not isinstance(source_event, EventEnvelope):
        raise TypeError("match learning requires preparation state and a recorded match event")
    validate_id(unit_id, kind="match learning unit ID")
    if not isinstance(player_ids, tuple) or len(player_ids) < 2:
        raise ValueError("coordinated match learning requires at least two participants")
    if len(player_ids) != len(set(player_ids)):
        raise ValueError("match learning participants cannot repeat")
    if type(meaningful_repetitions) is not int or not 1 <= meaningful_repetitions <= 100:
        raise ValueError("match learning requires 1 to 100 meaningful repetitions")
    if source_event.match_id is None or source_event.match_id not in state.completed_fixture_ids:
        raise ValueError("match learning must cite an event from a completed scheduled fixture")
    if set(player_ids) - set(_profile_map(state)):
        raise ValueError("match learning references a player outside the career roster")
    played = {
        item.player_id for item in state.exposure_results
        if item.match_id == source_event.match_id and item.minutes_played > 0
    }
    if set(player_ids) - played:
        raise ValueError("every unit-learning participant must have actual match exposure")
    source_id = str(source_event.event_id)
    familiarity = {(item.player_id, item.unit_id): item for item in state.unit_familiarities}
    profiles = _profile_map(state)
    for player_id in sorted(player_ids, key=str):
        key = (player_id, unit_id)
        familiarity[key] = record_unit_experience(
            familiarity.get(key),
            profiles[player_id],
            unit_id=unit_id,
            source_id=source_id,
            meaningful_repetitions=meaningful_repetitions,
        )
    return replace(
        state,
        unit_familiarities=tuple(sorted(
            familiarity.values(), key=lambda item: (str(item.player_id), item.unit_id)
        )),
    )


__all__ = [
    "ExposureInput",
    "ExposureResolution",
    "PlayerPreparation",
    "PreparationFixture",
    "PreparationPolicy",
    "PreparationState",
    "SelectionAssessment",
    "SelectionStatus",
    "TrainingKind",
    "TrainingResult",
    "TrainingSession",
    "advance_preparation_day",
    "available_training_minutes",
    "create_preparation_state",
    "injury_risk_for_exposure",
    "prepared_profile",
    "record_unit_match_experience",
    "schedule_training_session",
    "selection_assessment",
    "selection_assessments",
    "selectable_profiles",
    "settle_fixture_exposure",
]
