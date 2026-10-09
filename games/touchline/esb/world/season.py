"""Deterministic fixture calendars and multi-competition simulation (P16a).

Callers provide fictional or authored competition inputs and matchday sheets.
Every fixture runs through the same rules-driven P05 spatial match engine; this
module does not connect or migrate the legacy terminal career.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from enum import Enum

from games.touchline.esb.ids import MatchId, validate_id
from games.touchline.esb.match.engine import MatchPhase, MatchState, TeamSheet, create_match, run_to_completion
from games.touchline.esb.match.rules import MatchRules
from games.touchline.esb.serialization import dumps
from games.touchline.esb.time import WorldDate


class CompetitionKind(str, Enum):
    LEAGUE = "league"
    CUP = "cup"
    REPRESENTATIVE = "representative"


@dataclass(frozen=True)
class WorldCompetition:
    competition_id: str
    participant_ids: tuple[str, ...]
    rules: MatchRules
    kind: CompetitionKind = CompetitionKind.LEAGUE
    minimum_rest_hours: int = 48
    half_time_break_minutes: int = 15
    extra_time_interval_minutes: int = 5
    shootout_duration_minutes: int = 15

    def __post_init__(self) -> None:
        validate_id(self.competition_id, kind="world competition ID")
        if not isinstance(self.participant_ids, tuple) or len(self.participant_ids) < 2:
            raise ValueError("world competition requires at least two participants")
        for participant_id in self.participant_ids:
            validate_id(participant_id, kind="world competition participant ID")
        if len(self.participant_ids) != len(set(self.participant_ids)):
            raise ValueError("competition participants cannot repeat")
        if not isinstance(self.rules, MatchRules):
            raise TypeError("world competition requires its immutable rules snapshot")
        if not isinstance(self.kind, CompetitionKind):
            raise TypeError("world competition requires a known competition kind")
        if type(self.minimum_rest_hours) is not int or not 0 <= self.minimum_rest_hours <= 720:
            raise ValueError("minimum rest must be an integer in [0, 720] hours")
        for label, value in (
            ("half-time break", self.half_time_break_minutes),
            ("extra-time interval", self.extra_time_interval_minutes),
            ("shootout duration", self.shootout_duration_minutes),
        ):
            if type(value) is not int or not 0 <= value <= 120:
                raise ValueError(f"{label} duration must be an integer in [0, 120] minutes")

    def to_json(self) -> str:
        return dumps(self)

    @classmethod
    def from_json(cls, value: str) -> WorldCompetition:
        from games.touchline.esb.serialization import loads
        return loads(value, cls)


@dataclass(frozen=True)
class WorldFixture:
    fixture_id: str
    match_id: MatchId
    competition_id: str
    scheduled_on: WorldDate
    kickoff_minute: int
    home_participant_id: str
    away_participant_id: str
    home_sheet: TeamSheet
    away_sheet: TeamSheet

    def __post_init__(self) -> None:
        validate_id(self.fixture_id, kind="world fixture ID")
        validate_id(self.match_id, kind="world match ID")
        validate_id(self.competition_id, kind="world fixture competition ID")
        for label, participant_id in (
            ("home", self.home_participant_id),
            ("away", self.away_participant_id),
        ):
            validate_id(participant_id, kind=f"{label} participant ID")
        if self.home_participant_id == self.away_participant_id:
            raise ValueError("a fixture must have two different participants")
        if not isinstance(self.scheduled_on, WorldDate):
            raise TypeError("world fixture requires a calendar date")
        if type(self.kickoff_minute) is not int or not 0 <= self.kickoff_minute < 24 * 60:
            raise ValueError("kickoff minute must be an integer in [0, 1439]")
        if not isinstance(self.home_sheet, TeamSheet) or self.home_sheet.team_id != "home":
            raise ValueError("world fixture requires a valid home match sheet")
        if not isinstance(self.away_sheet, TeamSheet) or self.away_sheet.team_id != "away":
            raise ValueError("world fixture requires a valid away match sheet")

    def to_json(self) -> str:
        return dumps(self)

    @classmethod
    def from_json(cls, value: str) -> WorldFixture:
        from games.touchline.esb.serialization import loads
        return loads(value, cls)

    @property
    def kickoff_at(self) -> datetime:
        return datetime.combine(
            self.scheduled_on.day,
            time(self.kickoff_minute // 60, self.kickoff_minute % 60),
            tzinfo=timezone.utc,
        )

    @property
    def named_player_ids(self) -> tuple[str, ...]:
        """All matchday squad IDs, including explicitly unavailable players."""
        ids = []
        for sheet in (self.home_sheet, self.away_sheet):
            ids.extend(str(item.profile.player_id) for item in sheet.starters)
            ids.extend(str(item.player_id) for item in sheet.substitutes)
            ids.extend(str(item) for item in sheet.unavailable_player_ids)
        return tuple(ids)

    @property
    def scheduled_player_ids(self) -> tuple[str, ...]:
        """Players who may enter play; unavailable squad members cannot."""
        ids = []
        for sheet in (self.home_sheet, self.away_sheet):
            ids.extend(str(item.profile.player_id) for item in sheet.starters)
            ids.extend(str(item.player_id) for item in sheet.substitutes)
        return tuple(ids)


@dataclass(frozen=True)
class WorldSeasonSchedule:
    world_id: str
    season_id: str
    seed: int
    competitions: tuple[WorldCompetition, ...]
    fixtures: tuple[WorldFixture, ...]
    schema_version: int = 1

    def __post_init__(self) -> None:
        validate_id(self.world_id, kind="world ID")
        validate_id(self.season_id, kind="world season ID")
        if type(self.seed) is not int or not 0 <= self.seed < 2**63:
            raise ValueError("world seed must be a non-negative signed 64-bit integer")
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("unsupported world season schedule version")
        if (not isinstance(self.competitions, tuple) or not self.competitions
                or any(not isinstance(item, WorldCompetition) for item in self.competitions)):
            raise TypeError("world season requires immutable competition records")
        if (not isinstance(self.fixtures, tuple) or not self.fixtures
                or any(not isinstance(item, WorldFixture) for item in self.fixtures)):
            raise TypeError("world season requires immutable fixture records")
        competition_ids = [item.competition_id for item in self.competitions]
        fixture_ids = [item.fixture_id for item in self.fixtures]
        match_ids = [str(item.match_id) for item in self.fixtures]
        if len(competition_ids) != len(set(competition_ids)):
            raise ValueError("world season cannot repeat a competition ID")
        if len(fixture_ids) != len(set(fixture_ids)) or len(match_ids) != len(set(match_ids)):
            raise ValueError("world season cannot repeat fixture or match IDs")
        competitions = {item.competition_id: item for item in self.competitions}
        seen_competitions: set[str] = set()
        for fixture in self.fixtures:
            competition = competitions.get(fixture.competition_id)
            if competition is None:
                raise ValueError("world fixture references an unknown competition")
            if ({fixture.home_participant_id, fixture.away_participant_id}
                    - set(competition.participant_ids)):
                raise ValueError("fixture participants must belong to its competition")
            if len(fixture.named_player_ids) != len(set(fixture.named_player_ids)):
                raise ValueError("one player cannot be named twice in the same world fixture")
            seen_competitions.add(fixture.competition_id)
        if seen_competitions != set(competition_ids):
            raise ValueError("every declared competition must have at least one fixture")
        self._validate_player_calendar(competitions)

    @property
    def ordered_fixtures(self) -> tuple[WorldFixture, ...]:
        return tuple(sorted(
            self.fixtures,
            key=lambda item: (
                item.scheduled_on.day,
                item.kickoff_minute,
                item.competition_id,
                item.fixture_id,
            ),
        ))

    def competition(self, competition_id: str) -> WorldCompetition:
        validate_id(competition_id, kind="world competition ID")
        return next(item for item in self.competitions if item.competition_id == competition_id)

    def to_json(self) -> str:
        return dumps(self)

    @classmethod
    def from_json(cls, value: str) -> WorldSeasonSchedule:
        from games.touchline.esb.serialization import loads
        return loads(value, cls)

    def _validate_player_calendar(
        self, competitions: dict[str, WorldCompetition]
    ) -> None:
        appearances: dict[str, list[tuple[WorldFixture, datetime, datetime, int]]] = {}
        for fixture in self.fixtures:
            competition = competitions[fixture.competition_id]
            # A fixture's named substitutes might play, so reserve their full
            # rest window too. Period breaks, stoppage, extra time and a
            # possible shootout are competition inputs, not hidden estimates.
            ticks = 2 * (
                competition.rules.half_duration_ticks
                + competition.rules.stoppage_time_ticks
                + competition.rules.extra_time_duration_ticks
                + competition.rules.extra_time_stoppage_ticks
            )
            minutes = (ticks * competition.rules.tick_duration_ms + 59_999) // 60_000
            minutes += competition.half_time_break_minutes
            if competition.rules.extra_time_duration_ticks > 0:
                minutes += 2 * competition.extra_time_interval_minutes
            if competition.rules.shootout_kicks_per_team > 0:
                minutes += competition.shootout_duration_minutes
            finish = fixture.kickoff_at + timedelta(minutes=minutes)
            for player_id in fixture.scheduled_player_ids:
                appearances.setdefault(player_id, []).append(
                    (fixture, fixture.kickoff_at, finish, competition.minimum_rest_hours)
                )
        for player_id, schedule in appearances.items():
            schedule.sort(key=lambda item: (item[1], item[0].fixture_id))
            for previous, current in zip(schedule, schedule[1:]):
                previous_fixture, _previous_start, previous_finish, previous_rest = previous
                current_fixture, current_start, _current_finish, current_rest = current
                rest = timedelta(hours=max(previous_rest, current_rest))
                if previous_finish + rest > current_start:
                    gap_hours = (current_start - previous_finish).total_seconds() / 3600
                    raise ValueError(
                        "player calendar conflict for "
                        f"{player_id}: {previous_fixture.fixture_id} to "
                        f"{current_fixture.fixture_id} leaves {gap_hours:g}h; "
                        f"{max(previous_rest, current_rest)}h required"
                    )


def fixture_input_sha256(
    fixture: WorldFixture, competition: WorldCompetition
) -> str:
    """Fingerprint typed inputs consistently across an encode/decode round trip."""
    payload = immutable_snapshot_json(fixture) + "\n" + immutable_snapshot_json(competition)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def immutable_snapshot_json(record: object) -> str:
    """Return versioned canonical JSON with equivalent integral floats normalized.

    The strict codec accepts integer JSON values for typed float fields. Without
    normalization, coordinates such as ``101`` and ``101.0`` compare equal as
    domain values but produce different hashes after a record round trip. Keep
    negative zero as a float because it has a distinct exact-input encoding.
    """
    def normalize(value: object) -> object:
        if (type(value) is float and value.is_integer()
                and not (value == 0.0 and math.copysign(1.0, value) < 0.0)):
            return int(value)
        if isinstance(value, list):
            return [normalize(item) for item in value]
        if isinstance(value, dict):
            return {key: normalize(item) for key, item in value.items()}
        return value

    data = normalize(json.loads(dumps(record)))
    return json.dumps(
        data, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    )


def fixture_seed(schedule: WorldSeasonSchedule, fixture: WorldFixture) -> int:
    """Derive an order-independent engine seed for this exact world fixture."""
    return derive_fixture_seed(schedule.world_id, schedule.season_id, schedule.seed, fixture.fixture_id)


def derive_fixture_seed(world_id: str, season_id: str, root_seed: int, fixture_id: str) -> int:
    validate_id(world_id, kind="world ID")
    validate_id(season_id, kind="world season ID")
    validate_id(fixture_id, kind="world fixture ID")
    if type(root_seed) is not int or not 0 <= root_seed < 2**63:
        raise ValueError("world seed must be a non-negative signed 64-bit integer")
    payload = "\0".join((
        "esb-world-fixture-seed-v1",
        str(root_seed),
        world_id,
        season_id,
        fixture_id,
    )).encode("utf-8")
    return int.from_bytes(hashlib.blake2b(payload, digest_size=8).digest(), "big")


def simulate_fixture(
    schedule: WorldSeasonSchedule,
    fixture: WorldFixture,
    *,
    maximum_transitions: int = 500_000,
) -> MatchState:
    """Resolve one scheduled fixture using its competition's frozen rules."""
    if not isinstance(schedule, WorldSeasonSchedule) or not isinstance(fixture, WorldFixture):
        raise TypeError("fixture simulation requires a world schedule and fixture")
    if fixture not in schedule.fixtures:
        raise ValueError("fixture is not part of the supplied world season")
    competition = schedule.competition(fixture.competition_id)
    match = create_match(
        fixture.home_sheet,
        fixture.away_sheet,
        rules=competition.rules,
        seed=fixture_seed(schedule, fixture),
        match_id=fixture.match_id,
    )
    run_to_completion(match, maximum_transitions=maximum_transitions)
    if match.phase is not MatchPhase.FINISHED:
        raise RuntimeError(f"fixture {fixture.fixture_id} did not finish normally")
    _validate_event_chronology(match)
    return match


def _validate_event_chronology(match: MatchState) -> None:
    previous_tick = -1
    known_events: set[str] = set()
    for sequence, event in enumerate(match.events):
        if event.sequence != sequence or event.match_id != match.match_id:
            raise ValueError("match event history is not contiguous for its fixture")
        if event.match_tick is None or event.match_tick < previous_tick:
            raise ValueError("match event chronology moves backwards")
        for reference in (event.cause_event_id, event.parent_event_id):
            if reference is not None and str(reference) not in known_events:
                raise ValueError("match event lineage must reference an earlier event")
        previous_tick = event.match_tick
        known_events.add(str(event.event_id))


__all__ = [
    "CompetitionKind",
    "WorldCompetition",
    "WorldFixture",
    "WorldSeasonSchedule",
    "derive_fixture_seed",
    "fixture_input_sha256",
    "fixture_seed",
    "immutable_snapshot_json",
    "simulate_fixture",
]
