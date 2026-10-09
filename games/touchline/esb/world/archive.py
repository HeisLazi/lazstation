"""Transactional match, event and player-stat archive (P16a).

The SQLite store is opened only by an explicit ``WorldArchiveStore`` call.
Each match, its ordered event stream, full replay state and all matchday player
lines commit together. Retention can discard replay detail while preserving
competition and player summaries.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum
from pathlib import Path
from typing import Any

from games.touchline.esb.events import EventEnvelope
from games.touchline.esb.ids import EventId, MatchId, PlayerId, derive_id, validate_id
from games.touchline.esb.match.engine import MatchPhase, MatchState
from games.touchline.esb.serialization import SerializationError, dumps, loads
from games.touchline.esb.time import WorldDate
from games.touchline.esb.world.season import (
    CompetitionKind,
    WorldCompetition,
    WorldFixture,
    WorldSeasonSchedule,
    derive_fixture_seed,
    fixture_input_sha256,
    fixture_seed,
    immutable_snapshot_json,
    simulate_fixture,
)


ARCHIVE_SCHEMA_VERSION = 3
ENGINE_ID = "ekse-slaan-ball-spatial"
ENGINE_VERSION = "1"


class ArchiveDetailUnavailable(ValueError):
    """Raised when a retention policy has removed a match's full replay data."""


class MatchdayRole(str, Enum):
    STARTER = "starter"
    SUBSTITUTE = "substitute"
    UNAVAILABLE = "unavailable"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _validate_sha256(value: str, label: str) -> None:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")


def _json(text: str, label: str) -> Any:
    try:
        return json.loads(text, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not valid finite JSON") from exc


def _canonical_json(value: Any) -> str:
    return json.dumps(value, allow_nan=False, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class ArchivedPlayerLine:
    player_id: PlayerId
    participant_id: str
    role: MatchdayRole
    minutes_played: float
    statistics: tuple[tuple[str, int], ...]

    def __post_init__(self) -> None:
        validate_id(self.player_id, kind="archived player ID")
        validate_id(self.participant_id, kind="archived participant ID")
        if not isinstance(self.role, MatchdayRole):
            raise TypeError("archived player line requires a registered matchday role")
        if (type(self.minutes_played) not in (float, int)
                or not math.isfinite(self.minutes_played)
                or not 0 <= self.minutes_played <= 150):
            raise ValueError("archived minutes must be finite and in [0, 150]")
        if not isinstance(self.statistics, tuple):
            raise TypeError("player statistics must use an immutable tuple")
        names = []
        for item in self.statistics:
            if (not isinstance(item, tuple) or len(item) != 2
                    or not isinstance(item[0], str) or not item[0].strip()
                    or type(item[1]) is not int or item[1] < 0):
                raise ValueError("player statistics require named non-negative integer totals")
            names.append(item[0])
        if names != sorted(names) or len(names) != len(set(names)):
            raise ValueError("player statistics must have unique alphabetically ordered names")
        if self.role is MatchdayRole.UNAVAILABLE and self.minutes_played != 0:
            raise ValueError("unavailable matchday players cannot receive match minutes")


@dataclass(frozen=True)
class GoalLineage:
    event_id: EventId
    sequence: int
    tick: int
    scorer_id: PlayerId | None
    assist_id: PlayerId | None
    assist_event_id: EventId | None
    cause_event_id: EventId | None
    parent_event_id: EventId | None
    own_goal_player_id: PlayerId | None = None

    def __post_init__(self) -> None:
        validate_id(self.event_id, kind="goal event ID")
        for player_id in (self.scorer_id, self.assist_id, self.own_goal_player_id):
            if player_id is not None:
                validate_id(player_id, kind="goal player ID")
        for event_id in (self.assist_event_id, self.cause_event_id, self.parent_event_id):
            if event_id is not None:
                validate_id(event_id, kind="goal lineage event ID")
        if type(self.sequence) is not int or self.sequence < 0:
            raise ValueError("goal sequence must be non-negative")
        if type(self.tick) is not int or self.tick < 0:
            raise ValueError("goal tick must be non-negative")


@dataclass(frozen=True)
class WorldMatchRecord:
    world_id: str
    season_id: str
    fixture_id: str
    match_id: MatchId
    competition_id: str
    competition_kind: CompetitionKind
    scheduled_on: WorldDate
    kickoff_minute: int
    home_participant_id: str
    away_participant_id: str
    home_goals: int
    away_goals: int
    ruleset_id: str
    ruleset_version: int
    event_count: int
    simulation_seed: int
    input_sha256: str
    state_sha256: str
    match_state_json: str
    fixture_json: str
    competition_json: str
    player_lines: tuple[ArchivedPlayerLine, ...]
    goal_lineage: tuple[GoalLineage, ...]
    engine_id: str = ENGINE_ID
    engine_version: str = ENGINE_VERSION
    schema_version: int = ARCHIVE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        validate_id(self.world_id, kind="archived world ID")
        validate_id(self.season_id, kind="archived season ID")
        validate_id(self.fixture_id, kind="archived fixture ID")
        validate_id(self.match_id, kind="archived match ID")
        validate_id(self.competition_id, kind="archived competition ID")
        validate_id(self.home_participant_id, kind="archived home participant ID")
        validate_id(self.away_participant_id, kind="archived away participant ID")
        validate_id(self.ruleset_id, kind="archived ruleset ID")
        if not isinstance(self.competition_kind, CompetitionKind):
            raise TypeError("archived match requires a known competition kind")
        if not isinstance(self.scheduled_on, WorldDate):
            raise TypeError("archived match requires its scheduled world date")
        if type(self.kickoff_minute) is not int or not 0 <= self.kickoff_minute < 1440:
            raise ValueError("archived kickoff minute must be in [0, 1439]")
        for label, value in (("home goals", self.home_goals), ("away goals", self.away_goals),
                             ("event count", self.event_count), ("ruleset version", self.ruleset_version),
                             ("simulation seed", self.simulation_seed)):
            if type(value) is not int or value < 0:
                raise ValueError(f"archived {label} must be a non-negative integer")
        if self.simulation_seed >= 2**64:
            raise ValueError("archived simulation seed must fit an unsigned 64-bit integer")
        if type(self.schema_version) is not int or self.schema_version != ARCHIVE_SCHEMA_VERSION:
            raise ValueError("unsupported world match archive record version")
        if self.engine_id != ENGINE_ID or self.engine_version != ENGINE_VERSION:
            raise ValueError("unsupported archived match engine identity")
        _validate_sha256(self.input_sha256, "world fixture input hash")
        _validate_sha256(self.state_sha256, "match state hash")
        if not isinstance(self.player_lines, tuple) or any(not isinstance(item, ArchivedPlayerLine) for item in self.player_lines):
            raise TypeError("archived player lines must be immutable validated records")
        if not isinstance(self.goal_lineage, tuple) or any(not isinstance(item, GoalLineage) for item in self.goal_lineage):
            raise TypeError("archived goal lineage must be immutable validated records")
        if _sha256(self.match_state_json) != self.state_sha256:
            raise ValueError("archived match state does not match its content hash")
        if _sha256(self.fixture_json + "\n" + self.competition_json) != self.input_sha256:
            raise ValueError("archived fixture inputs do not match their content hash")
        match = MatchState.from_json(self.match_state_json)
        fixture = WorldFixture.from_json(self.fixture_json)
        competition = WorldCompetition.from_json(self.competition_json)
        self._validate_projection(match, fixture, competition)

    def _validate_projection(
        self,
        match: MatchState,
        fixture: WorldFixture,
        competition: WorldCompetition,
    ) -> None:
        if (match.match_id != self.match_id or match.phase is not MatchPhase.FINISHED
                or match.home_score != self.home_goals or match.away_score != self.away_goals
                or match.rules.ruleset_id != self.ruleset_id
                or match.rules.schema_version != self.ruleset_version
                or match.play.random_streams.root_seed != self.simulation_seed
                or len(match.events) != self.event_count):
            raise ValueError("archived match metadata does not reconcile to its final state")
        if (fixture.fixture_id != self.fixture_id or fixture.match_id != self.match_id
                or fixture.competition_id != self.competition_id
                or fixture.scheduled_on != self.scheduled_on
                or fixture.kickoff_minute != self.kickoff_minute
                or fixture.home_participant_id != self.home_participant_id
                or fixture.away_participant_id != self.away_participant_id):
            raise ValueError("archived fixture fields do not reconcile to its source snapshot")
        if (competition.competition_id != self.competition_id
                or competition.rules != match.rules
                or competition.kind != self.competition_kind):
            raise ValueError("archived competition rules do not reconcile to the played match")
        if match.input_snapshot is None:
            raise ValueError("archived match is missing its immutable kickoff input snapshot")
        match.validate_playing_time_projection()
        if self.player_lines != _player_lines(match, fixture):
            raise ValueError("archived player analytics do not reconcile to match events and lineups")
        if self.goal_lineage != _goal_lineage(match):
            raise ValueError("archived goal lineage does not reconcile to the chronological event stream")
        _validate_chronology(match)

    @classmethod
    def create(
        cls,
        schedule: WorldSeasonSchedule,
        fixture: WorldFixture,
        match: MatchState,
    ) -> WorldMatchRecord:
        competition = schedule.competition(fixture.competition_id)
        fixture_json = immutable_snapshot_json(fixture)
        competition_json = immutable_snapshot_json(competition)
        return cls(
            world_id=schedule.world_id,
            season_id=schedule.season_id,
            fixture_id=fixture.fixture_id,
            match_id=fixture.match_id,
            competition_id=competition.competition_id,
            competition_kind=competition.kind,
            scheduled_on=fixture.scheduled_on,
            kickoff_minute=fixture.kickoff_minute,
            home_participant_id=fixture.home_participant_id,
            away_participant_id=fixture.away_participant_id,
            home_goals=match.home_score,
            away_goals=match.away_score,
            ruleset_id=match.rules.ruleset_id,
            ruleset_version=match.rules.schema_version,
            event_count=len(match.events),
            simulation_seed=fixture_seed(schedule, fixture),
            input_sha256=fixture_input_sha256(fixture, competition),
            state_sha256=_sha256(match.to_json()),
            match_state_json=match.to_json(),
            fixture_json=fixture_json,
            competition_json=competition_json,
            player_lines=_player_lines(match, fixture),
            goal_lineage=_goal_lineage(match),
        )

    def match_state(self) -> MatchState:
        return MatchState.from_json(self.match_state_json)

    @property
    def analytics_json(self) -> str:
        match = self.match_state()
        return _canonical_json({
            "world_id": self.world_id,
            "season_id": self.season_id,
            "fixture_id": self.fixture_id,
            "match_id": str(self.match_id),
            "competition_id": self.competition_id,
            "competition_kind": self.competition_kind.value,
            "scheduled_on": self.scheduled_on.isoformat,
            "kickoff_minute": self.kickoff_minute,
            "home_participant_id": self.home_participant_id,
            "away_participant_id": self.away_participant_id,
            "home_goals": self.home_goals,
            "away_goals": self.away_goals,
            "ruleset_id": self.ruleset_id,
            "ruleset_version": self.ruleset_version,
            "engine_id": self.engine_id,
            "engine_version": self.engine_version,
            "match_input_sha256": match.input_snapshot_sha256,
            "event_count": self.event_count,
            "simulation_seed": self.simulation_seed,
            "input_sha256": self.input_sha256,
            "state_sha256": self.state_sha256,
            "player_lines": [
                {
                    "player_id": str(item.player_id),
                    "participant_id": item.participant_id,
                    "role": item.role.value,
                    "minutes_played": float(item.minutes_played),
                    "statistics": dict(item.statistics),
                }
                for item in self.player_lines
            ],
            "goal_lineage": [
                {
                    "event_id": str(item.event_id),
                    "sequence": item.sequence,
                    "tick": item.tick,
                    "scorer_id": str(item.scorer_id) if item.scorer_id else None,
                    "assist_id": str(item.assist_id) if item.assist_id else None,
                    "assist_event_id": str(item.assist_event_id) if item.assist_event_id else None,
                    "cause_event_id": str(item.cause_event_id) if item.cause_event_id else None,
                    "parent_event_id": str(item.parent_event_id) if item.parent_event_id else None,
                    "own_goal_player_id": str(item.own_goal_player_id) if item.own_goal_player_id else None,
                }
                for item in self.goal_lineage
            ],
        })

    @property
    def analytics_sha256(self) -> str:
        return _sha256(self.analytics_json)


def _player_lines(match: MatchState, fixture: WorldFixture) -> tuple[ArchivedPlayerLine, ...]:
    stats = match.player_statistics
    minutes = match.minutes_played
    records: list[ArchivedPlayerLine] = []
    for sheet, participant_id in (
        (fixture.home_sheet, fixture.home_participant_id),
        (fixture.away_sheet, fixture.away_participant_id),
    ):
        inputs: list[tuple[PlayerId, MatchdayRole]] = []
        inputs.extend((item.profile.player_id, MatchdayRole.STARTER) for item in sheet.starters)
        inputs.extend((item.player_id, MatchdayRole.SUBSTITUTE) for item in sheet.substitutes)
        inputs.extend((item, MatchdayRole.UNAVAILABLE) for item in sheet.unavailable_player_ids)
        for player_id, role in inputs:
            player_stats = tuple(sorted(stats.get(player_id, {}).items()))
            records.append(ArchivedPlayerLine(
                player_id,
                participant_id,
                role,
                float(minutes.get(player_id, 0.0)),
                player_stats,
            ))
    return tuple(sorted(records, key=lambda item: (item.participant_id, str(item.player_id))))


def _goal_lineage(match: MatchState) -> tuple[GoalLineage, ...]:
    result = []
    for event in match.events:
        if event.kind != "goal":
            continue
        payload = event.payload
        result.append(GoalLineage(
            event.event_id,
            event.sequence,
            event.match_tick or 0,
            PlayerId(str(payload["actor_id"])) if payload.get("actor_id") else None,
            PlayerId(str(payload["assist_player_id"])) if payload.get("assist_player_id") else None,
            EventId(str(payload["assist_event_id"])) if payload.get("assist_event_id") else None,
            event.cause_event_id,
            event.parent_event_id,
            PlayerId(str(payload["own_goal_player_id"])) if payload.get("own_goal_player_id") else None,
        ))
    return tuple(result)


def _validate_chronology(match: MatchState) -> None:
    previous_tick = -1
    seen: set[str] = set()
    for expected_sequence, event in enumerate(match.events):
        if event.sequence != expected_sequence or event.match_id != match.match_id:
            raise ValueError("archived match events must have contiguous sequence numbers")
        if event.match_tick is None or event.match_tick < previous_tick:
            raise ValueError("archived match events must preserve actual tick chronology")
        for event_id in (event.cause_event_id, event.parent_event_id):
            if event_id is not None and str(event_id) not in seen:
                raise ValueError("event cause and parent references must point to earlier events")
        assist_event_id = event.payload.get("assist_event_id")
        if assist_event_id is not None and str(assist_event_id) not in seen:
            raise ValueError("goal assist lineage must point to an earlier match event")
        seen.add(str(event.event_id))
        previous_tick = event.match_tick


@dataclass(frozen=True)
class DetailRetentionPolicy:
    maximum_age_days: int | None = None
    maximum_detailed_matches: int | None = None

    def __post_init__(self) -> None:
        if (self.maximum_age_days is not None
                and (type(self.maximum_age_days) is not int or self.maximum_age_days < 0)):
            raise ValueError("detail retention age must be a non-negative number of days")
        if (self.maximum_detailed_matches is not None
                and (type(self.maximum_detailed_matches) is not int or self.maximum_detailed_matches < 0)):
            raise ValueError("detailed match limit must be a non-negative integer")


@dataclass(frozen=True)
class PlayerMatchSummary:
    match_id: MatchId
    fixture_id: str
    competition_id: str
    scheduled_on: WorldDate
    participant_id: str
    opponent_id: str
    home: bool
    goals_for: int
    goals_against: int
    minutes_played: float
    role: MatchdayRole
    statistics: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class PlayerCareerSummary:
    player_id: PlayerId
    matchday_selections: int
    appearances: int
    total_minutes: float
    statistics: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class CompetitionTableLine:
    participant_id: str
    played: int
    won: int
    drawn: int
    lost: int
    goals_for: int
    goals_against: int
    goal_difference: int
    points: int


@dataclass(frozen=True)
class ArchiveMetrics:
    world_id: str
    season_id: str
    archived_matches: int
    detailed_matches: int
    retained_events: int
    total_recorded_events: int
    player_rows: int
    unique_players: int
    database_bytes: int
    summary_bytes: int


class WorldArchiveStore:
    """Single-writer SQLite archive with one atomic transaction per fixture."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        self._connection: sqlite3.Connection | None = None

    def __enter__(self) -> WorldArchiveStore:
        if self._connection is not None:
            raise RuntimeError("archive store is already open")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA busy_timeout = 30000")
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    @property
    def connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("open the archive store with a context manager first")
        return self._connection

    def initialize(self, schedule: WorldSeasonSchedule) -> None:
        if not isinstance(schedule, WorldSeasonSchedule):
            raise TypeError("archive initialization requires a world season schedule")
        connection = self.connection
        tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        if tables:
            self._validate_identity(schedule)
            self._register_schedule(schedule, create=False)
            return
        connection.executescript("BEGIN IMMEDIATE;\n" + _SCHEMA)
        try:
            metadata = {
                "schema_version": str(ARCHIVE_SCHEMA_VERSION),
                "world_id": schedule.world_id,
                "season_id": schedule.season_id,
                "seed": str(schedule.seed),
            }
            connection.executemany(
                "INSERT INTO archive_meta(key, value) VALUES (?, ?)", metadata.items()
            )
            self._register_schedule(schedule, create=True)
            connection.execute("COMMIT")
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        self._validate_identity(schedule)

    def initialize_world_flow(
        self, schedule: WorldSeasonSchedule, initial_state: object
    ) -> tuple[object, str]:
        """Create/load P16b inputs and a bounded checkpoint for this season."""
        from games.touchline.esb.world.competition_flow import (
            WorldCompetitionState,
            WorldExposureResolution,
            WorldFixtureSettlement,
            WorldFlowCheckpoint,
            WorldFlowInputs,
            _assert_state_matches_schedule,
            flow_snapshot_sha256,
            replay_world_flow_fixture,
        )

        if not isinstance(initial_state, WorldCompetitionState):
            raise TypeError("world flow initialization requires a WorldCompetitionState")
        if not isinstance(schedule, WorldSeasonSchedule):
            raise TypeError("world flow initialization requires a WorldSeasonSchedule")
        _assert_state_matches_schedule(initial_state, schedule)
        flow_inputs = initial_state.flow_inputs()
        inputs_json = dumps(flow_inputs)
        inputs_sha = flow_inputs.inputs_sha256
        if inputs_sha != initial_state.initial_state_sha256:
            raise ValueError("world flow initialization inputs fail their initial fingerprint")
        if initial_state.revision != 0:
            raise ValueError("world flow initialization requires an unsettled revision-zero checkpoint")
        # RandomStreams is mutable even though its containing state is frozen.
        # Rebuild through the validating checkpoint constructor before persisting it.
        flow_inputs.restore_checkpoint(initial_state.checkpoint())
        schedule_sha = _sha256(immutable_snapshot_json(schedule))
        if (initial_state.world_id, initial_state.season_id, initial_state.schedule_sha256) != (
                schedule.world_id, schedule.season_id, schedule_sha):
            raise ValueError("world flow initialization does not match the archived schedule")
        self.initialize(schedule)
        connection = self.connection
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS world_flow_state ("
                "singleton INTEGER PRIMARY KEY CHECK(singleton = 1), "
                "schema_version INTEGER NOT NULL, world_id TEXT NOT NULL, season_id TEXT NOT NULL, "
                "schedule_sha256 TEXT NOT NULL, initial_state_sha256 TEXT NOT NULL, "
                "inputs_json TEXT NOT NULL, inputs_sha256 TEXT NOT NULL, "
                "checkpoint_json TEXT NOT NULL, checkpoint_sha256 TEXT NOT NULL, "
                "revision INTEGER NOT NULL, last_fixture_id TEXT, last_match_id TEXT, "
                "last_input_sha256 TEXT, last_match_state_sha256 TEXT)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS world_flow_fixtures ("
                "fixture_id TEXT PRIMARY KEY, match_id TEXT NOT NULL UNIQUE, "
                "competition_id TEXT NOT NULL, scheduled_on TEXT NOT NULL, kickoff_minute INTEGER NOT NULL, "
                "input_sha256 TEXT NOT NULL, match_state_sha256 TEXT NOT NULL, "
                "pre_match_conditions_sha256 TEXT NOT NULL, exposure_sha256 TEXT NOT NULL, "
                "exposure_count INTEGER NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS world_flow_exposures ("
                "fixture_id TEXT NOT NULL, player_id TEXT NOT NULL, match_id TEXT NOT NULL, "
                "resolution_json TEXT NOT NULL, resolution_sha256 TEXT NOT NULL, "
                "PRIMARY KEY(fixture_id, player_id), "
                "FOREIGN KEY(fixture_id) REFERENCES world_flow_fixtures(fixture_id) ON DELETE CASCADE)"
            )
            row = connection.execute("SELECT * FROM world_flow_state WHERE singleton = 1").fetchone()
            if row is None:
                existing_matches = connection.execute(
                    "SELECT COUNT(*) FROM archived_matches"
                ).fetchone()[0]
                if existing_matches:
                    raise ValueError("cannot attach P16b condition flow after P16a fixtures were simulated")
                checkpoint_json = initial_state.checkpoint_json()
                connection.execute(
                    "INSERT INTO world_flow_state(singleton, schema_version, world_id, season_id, "
                    "schedule_sha256, initial_state_sha256, inputs_json, inputs_sha256, checkpoint_json, "
                    "checkpoint_sha256, revision, last_fixture_id, last_match_id, last_input_sha256, "
                    "last_match_state_sha256) VALUES (1, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (initial_state.world_id, initial_state.season_id, schedule_sha,
                     initial_state.initial_state_sha256, inputs_json, inputs_sha,
                     checkpoint_json, initial_state.state_sha256, initial_state.revision,
                     initial_state.last_fixture_id,
                     str(initial_state.last_match_id) if initial_state.last_match_id else None,
                     initial_state.last_input_sha256, initial_state.last_match_state_sha256),
                )
                current = initial_state
                stored_inputs = flow_inputs
            else:
                if (row["schema_version"] != 1
                        or row["world_id"] != schedule.world_id
                        or row["season_id"] != schedule.season_id
                        or row["schedule_sha256"] != schedule_sha
                        or row["initial_state_sha256"] != initial_state.initial_state_sha256
                        or row["inputs_sha256"] != inputs_sha):
                    raise ValueError("world flow immutable inputs conflict with the stored season")
                try:
                    stored_inputs = loads(row["inputs_json"], WorldFlowInputs)
                except SerializationError as exc:
                    raise ValueError("stored world flow immutable inputs are invalid") from exc
                if (stored_inputs.inputs_sha256 != inputs_sha
                        or stored_inputs.inputs_sha256 != row["inputs_sha256"]):
                    raise ValueError("stored world flow immutable inputs fail their semantic fingerprint")
                checkpoint_json = row["checkpoint_json"]
                if _sha256(checkpoint_json) != row["checkpoint_sha256"]:
                    raise ValueError("world flow checkpoint integrity check failed")
                checkpoint = WorldFlowCheckpoint.from_json(checkpoint_json)
                if (checkpoint.revision != row["revision"]
                        or checkpoint.world_id != row["world_id"]
                        or checkpoint.season_id != row["season_id"]
                        or checkpoint.initial_state_sha256 != row["initial_state_sha256"]
                        or checkpoint.last_fixture_id != row["last_fixture_id"]
                        or (str(checkpoint.last_match_id) if checkpoint.last_match_id else None)
                           != row["last_match_id"]
                        or checkpoint.last_input_sha256 != row["last_input_sha256"]
                        or checkpoint.last_match_state_sha256 != row["last_match_state_sha256"]):
                    raise ValueError("world flow checkpoint columns do not reconcile")
                current = stored_inputs.restore_checkpoint(checkpoint)
            replay_state = initial_state
            fixture_rows = connection.execute(
                "SELECT * FROM world_flow_fixtures ORDER BY scheduled_on, kickoff_minute, competition_id, fixture_id"
            ).fetchall()
            ordered = schedule.ordered_fixtures
            if len(fixture_rows) != current.revision or len(fixture_rows) > len(ordered):
                raise ValueError("world flow fixture archive and checkpoint revision differ")
            archived_count = connection.execute("SELECT COUNT(*) FROM archived_matches").fetchone()[0]
            if archived_count != current.revision:
                raise ValueError("world flow and full match archive counts do not reconcile")
            expected_player_ids = tuple(sorted(
                (str(item.player_id) for item in initial_state.profiles),
            ))
            for stored, fixture in zip(fixture_rows, ordered):
                competition = schedule.competition(fixture.competition_id)
                expected_input = fixture_input_sha256(fixture, competition)
                archived = connection.execute(
                    "SELECT input_sha256, state_sha256 FROM archived_matches WHERE fixture_id = ? AND match_id = ?",
                    (fixture.fixture_id, str(fixture.match_id)),
                ).fetchone()
                if (stored["fixture_id"] != fixture.fixture_id
                        or stored["match_id"] != str(fixture.match_id)
                        or stored["competition_id"] != fixture.competition_id
                        or stored["scheduled_on"] != fixture.scheduled_on.isoformat
                        or stored["kickoff_minute"] != fixture.kickoff_minute
                        or stored["input_sha256"] != expected_input
                        or archived is None
                        or archived["input_sha256"] != expected_input
                        or archived["state_sha256"] != stored["match_state_sha256"]):
                    raise ValueError("world flow fixture rows do not reconcile to scheduled archive matches")
                exposures = connection.execute(
                    "SELECT player_id, match_id, resolution_json, resolution_sha256 FROM world_flow_exposures "
                    "WHERE fixture_id = ? ORDER BY player_id", (fixture.fixture_id,),
                ).fetchall()
                parsed = []
                for exposure in exposures:
                    if _sha256(exposure["resolution_json"]) != exposure["resolution_sha256"]:
                        raise ValueError("world exposure row failed its integrity check")
                    parsed_item = loads(exposure["resolution_json"], WorldExposureResolution)
                    if (str(parsed_item.player_id) != exposure["player_id"]
                            or exposure["match_id"] != str(fixture.match_id)
                            or parsed_item.fixture_id != fixture.fixture_id
                            or str(parsed_item.match_id) != str(fixture.match_id)
                            or parsed_item.occurred_on != fixture.scheduled_on
                            or parsed_item.match_state_sha256 != stored["match_state_sha256"]):
                        raise ValueError("world exposure row does not match its scheduled fixture and match")
                    parsed.append(parsed_item)
                if (tuple(str(item.player_id) for item in parsed) != expected_player_ids
                        or stored["exposure_count"] != len(parsed)
                        or flow_snapshot_sha256(tuple(parsed)) != stored["exposure_sha256"]):
                    raise ValueError("world flow exposure records do not reconcile to their fixture summary")
                analytics = self._validate_archived_match(fixture.match_id)
                player_minutes = {
                    PlayerId(item["player_id"]): float(item["minutes_played"])
                    for item in analytics["player_lines"]
                }
                stored_settlement = WorldFixtureSettlement(
                    fixture.fixture_id, fixture.match_id, fixture.competition_id,
                    fixture.scheduled_on, stored["input_sha256"], stored["match_state_sha256"],
                    stored["pre_match_conditions_sha256"], stored["exposure_sha256"],
                )
                replay_state = replay_world_flow_fixture(
                    replay_state, fixture, competition,
                    match_state_sha256=stored["match_state_sha256"],
                    match_input_sha256=analytics["match_input_sha256"],
                    player_minutes=player_minutes,
                    exposures=tuple(parsed), settlement=stored_settlement,
                )
            if current.revision:
                last = fixture_rows[-1]
                if (current.last_fixture_id, str(current.last_match_id), current.last_input_sha256,
                    current.last_match_state_sha256, current.last_pre_match_conditions_sha256,
                    current.last_exposure_sha256) != (
                        last["fixture_id"], last["match_id"], last["input_sha256"],
                        last["match_state_sha256"], last["pre_match_conditions_sha256"],
                        last["exposure_sha256"]):
                    raise ValueError("world flow latest checkpoint does not reconcile to its last fixture")
            if replay_state != current:
                raise ValueError("world flow checkpoint does not reconcile to replayed P09 match settlements")
            connection.execute("COMMIT")
            return current, current.state_sha256
        except BaseException:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise

    def world_flow_fixture_ids(self) -> tuple[str, ...]:
        table = self.connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'world_flow_fixtures'"
        ).fetchone()
        if table is None:
            return ()
        rows = self.connection.execute(
            "SELECT fixture_id FROM world_flow_fixtures "
            "ORDER BY scheduled_on, kickoff_minute, competition_id, fixture_id"
        ).fetchall()
        return tuple(row["fixture_id"] for row in rows)

    def world_player_exposure_history(self, player_id: PlayerId | str) -> tuple[object, ...]:
        from games.touchline.esb.world.competition_flow import WorldExposureResolution

        validate_id(player_id, kind="world player exposure history ID")
        table = self.connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'world_flow_exposures'"
        ).fetchone()
        if table is None:
            return ()
        rows = self.connection.execute(
            "SELECT e.fixture_id, e.player_id, e.match_id, e.resolution_json, e.resolution_sha256, "
            "f.match_id AS flow_match_id, f.competition_id AS flow_competition_id, "
            "f.scheduled_on AS flow_scheduled_on, "
            "f.input_sha256 AS flow_input_sha256, f.match_state_sha256 AS flow_match_state_sha256 "
            "FROM world_flow_exposures e "
            "JOIN world_flow_fixtures f USING(fixture_id) WHERE e.player_id = ? "
            "ORDER BY f.scheduled_on, f.kickoff_minute, f.competition_id, f.fixture_id",
            (str(player_id),),
        ).fetchall()
        result = []
        for row in rows:
            if _sha256(row["resolution_json"]) != row["resolution_sha256"]:
                raise ValueError("world player exposure history failed its integrity check")
            resolution = loads(row["resolution_json"], WorldExposureResolution)
            if (resolution.fixture_id != row["fixture_id"]
                    or str(resolution.player_id) != row["player_id"]
                    or str(resolution.match_id) != row["match_id"]):
                raise ValueError("world player exposure history does not reconcile to its row indexes")
            analytics = self._validate_archived_match(row["match_id"])
            if (analytics["fixture_id"] != row["fixture_id"]
                    or analytics["competition_id"] != row["flow_competition_id"]
                    or analytics["input_sha256"] != row["flow_input_sha256"]
                    or analytics["match_id"] != row["match_id"]
                    or row["flow_match_id"] != row["match_id"]
                    or analytics["scheduled_on"] != row["flow_scheduled_on"]
                    or resolution.occurred_on.isoformat != row["flow_scheduled_on"]
                    or analytics["state_sha256"] != row["flow_match_state_sha256"]
                    or resolution.match_state_sha256 != row["flow_match_state_sha256"]):
                raise ValueError("world player exposure lineage does not reconcile to the archived fixture")
            archived_line = self.connection.execute(
                "SELECT minutes FROM player_match_lines WHERE match_id = ? AND player_id = ?",
                (row["match_id"], row["player_id"]),
            ).fetchone()
            archived_minutes = 0.0 if archived_line is None else float(archived_line["minutes"])
            if float(resolution.minutes_played) != archived_minutes:
                raise ValueError("world player exposure minutes do not reconcile to the archived match line")
            result.append(resolution)
        return tuple(result)

    def _validate_identity(self, schedule: WorldSeasonSchedule) -> None:
        rows = self.connection.execute("SELECT key, value FROM archive_meta").fetchall()
        metadata = {row["key"]: row["value"] for row in rows}
        expected = {
            "schema_version": str(ARCHIVE_SCHEMA_VERSION),
            "world_id": schedule.world_id,
            "season_id": schedule.season_id,
            "seed": str(schedule.seed),
        }
        if metadata != expected:
            raise ValueError("archive belongs to a different world/season/seed or schema")

    def _register_schedule(self, schedule: WorldSeasonSchedule, *, create: bool) -> None:
        connection = self.connection
        expected_competitions = {
            item.competition_id: immutable_snapshot_json(item)
            for item in schedule.competitions
        }
        expected_fixtures = {
            item.fixture_id: (
                str(item.match_id), item.competition_id, item.scheduled_on.isoformat,
                item.kickoff_minute, fixture_input_sha256(item, schedule.competition(item.competition_id)),
                immutable_snapshot_json(item),
            )
            for item in schedule.fixtures
        }
        if create:
            connection.executemany(
                "INSERT INTO world_competitions(competition_id, definition_json) VALUES (?, ?)",
                expected_competitions.items(),
            )
            connection.executemany(
                "INSERT INTO world_fixtures(fixture_id, match_id, competition_id, scheduled_on, "
                "kickoff_minute, input_sha256, input_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [(fixture_id, *values) for fixture_id, values in expected_fixtures.items()],
            )
            return
        stored_competitions = {
            row["competition_id"]: row["definition_json"]
            for row in connection.execute("SELECT competition_id, definition_json FROM world_competitions")
        }
        stored_fixtures = {
            row["fixture_id"]: (
                row["match_id"], row["competition_id"], row["scheduled_on"],
                row["kickoff_minute"], row["input_sha256"], row["input_json"],
            )
            for row in connection.execute("SELECT * FROM world_fixtures")
        }
        if stored_competitions != expected_competitions or stored_fixtures != expected_fixtures:
            raise ValueError("world schedule differs from the immutable archived season inputs")

    def recorded_fixture(
        self,
        fixture_id: str,
        *,
        expected_input_sha256: str | None = None,
        expected_match_id: str | None = None,
        expected_simulation_seed: int | None = None,
    ) -> tuple[str, str] | None:
        validate_id(fixture_id, kind="archive fixture ID")
        row = self.connection.execute(
            "SELECT input_sha256, match_id, simulation_seed FROM archived_matches WHERE fixture_id = ?",
            (fixture_id,),
        ).fetchone()
        if row is None:
            return None
        if (expected_input_sha256 is not None and row["input_sha256"] != expected_input_sha256
                or expected_match_id is not None and row["match_id"] != expected_match_id
                or expected_simulation_seed is not None
                and int(row["simulation_seed"]) != expected_simulation_seed):
            raise ValueError("scheduled fixture conflicts with the archived version")
        self._validate_archived_match(row["match_id"])
        return row["input_sha256"], row["match_id"]

    def _validate_archived_match(
        self,
        match_id: MatchId | str,
        *,
        expected_record: WorldMatchRecord | None = None,
    ) -> dict[str, Any]:
        """Verify retained analytics and, while available, its replay source."""
        row = self.connection.execute(
            "SELECT * FROM archived_matches WHERE match_id = ?", (str(match_id),)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown archived match: {match_id}")
        raw = row["analytics_json"]
        if _sha256(raw) != row["analytics_sha256"]:
            raise ValueError(f"archived analytics integrity check failed for {match_id}")
        analytics = _json(raw, "archived analytics")
        if not isinstance(analytics, dict) or _canonical_json(analytics) != raw:
            raise ValueError(f"archived analytics integrity check failed for {match_id}")
        _validate_sha256(analytics.get("match_input_sha256"), "archived kickoff input hash")
        column_projection = {
            "match_id": row["match_id"],
            "fixture_id": row["fixture_id"],
            "competition_id": row["competition_id"],
            "competition_kind": row["competition_kind"],
            "scheduled_on": row["scheduled_on"],
            "kickoff_minute": row["kickoff_minute"],
            "home_participant_id": row["home_participant_id"],
            "away_participant_id": row["away_participant_id"],
            "home_goals": row["home_goals"],
            "away_goals": row["away_goals"],
            "ruleset_id": row["ruleset_id"],
            "ruleset_version": row["ruleset_version"],
            "engine_id": row["engine_id"],
            "engine_version": row["engine_version"],
            "event_count": row["event_count"],
            "simulation_seed": int(row["simulation_seed"]),
            "input_sha256": row["input_sha256"],
            "state_sha256": row["state_sha256"],
        }
        if any(analytics.get(key) != value for key, value in column_projection.items()):
            raise ValueError(f"archived analytics columns do not reconcile for {match_id}")

        player_rows = self.connection.execute(
            "SELECT player_id, participant_id, role, minutes, stats_json "
            "FROM player_match_lines WHERE match_id = ? ORDER BY participant_id, player_id",
            (str(match_id),),
        ).fetchall()
        actual_players = [{
            "player_id": item["player_id"],
            "participant_id": item["participant_id"],
            "role": item["role"],
            "minutes_played": float(item["minutes"]),
            "statistics": _json(item["stats_json"], "archived player statistics"),
        } for item in player_rows]
        if actual_players != analytics.get("player_lines"):
            raise ValueError(f"archived player projections do not reconcile for {match_id}")

        try:
            player_lines = tuple(ArchivedPlayerLine(
                PlayerId(item["player_id"]), item["participant_id"], MatchdayRole(item["role"]),
                item["minutes_played"], tuple(sorted(item["statistics"].items())),
            ) for item in analytics["player_lines"])
            goals = tuple(GoalLineage(
                EventId(item["event_id"]), item["sequence"], item["tick"],
                PlayerId(item["scorer_id"]) if item["scorer_id"] else None,
                PlayerId(item["assist_id"]) if item["assist_id"] else None,
                EventId(item["assist_event_id"]) if item["assist_event_id"] else None,
                EventId(item["cause_event_id"]) if item["cause_event_id"] else None,
                EventId(item["parent_event_id"]) if item["parent_event_id"] else None,
                PlayerId(item["own_goal_player_id"]) if item["own_goal_player_id"] else None,
            ) for item in analytics["goal_lineage"])
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"archived analytics projection schema is invalid for {match_id}") from exc

        goal_envelope = _json(row["goal_lineage_json"], "archived goal lineage")
        expected_goal_envelope = _json(dumps(_GoalLineageEnvelope(goals)), "expected archived goal lineage")
        if (not isinstance(goal_envelope, dict)
                or _canonical_json(goal_envelope) != _canonical_json(expected_goal_envelope)):
            raise ValueError(f"archived goal projections do not reconcile for {match_id}")

        if expected_record is not None and (
            expected_record.analytics_json != raw
            or expected_record.analytics_sha256 != row["analytics_sha256"]
        ):
            raise ValueError(f"archived analytics do not match the deterministic fixture for {match_id}")

        meta = {item["key"]: item["value"] for item in self.connection.execute(
            "SELECT key, value FROM archive_meta"
        )}
        fixture_row = self.connection.execute(
            "SELECT match_id, competition_id, input_sha256, input_json FROM world_fixtures "
            "WHERE fixture_id = ?", (row["fixture_id"],)
        ).fetchone()
        competition_row = self.connection.execute(
            "SELECT definition_json FROM world_competitions WHERE competition_id = ?",
            (row["competition_id"],),
        ).fetchone()
        if fixture_row is None or competition_row is None:
            raise ValueError(f"archived match source snapshots are missing for {match_id}")
        fixture = WorldFixture.from_json(fixture_row["input_json"])
        competition = WorldCompetition.from_json(competition_row["definition_json"])
        expected_seed = derive_fixture_seed(
            meta["world_id"], meta["season_id"], int(meta["seed"]), row["fixture_id"]
        )
        snapshot_sha256 = _sha256(
            fixture_row["input_json"] + "\n" + competition_row["definition_json"]
        )
        if (fixture_row["match_id"] != row["match_id"]
                or fixture_row["competition_id"] != row["competition_id"]
                or fixture_row["input_sha256"] != row["input_sha256"]
                or snapshot_sha256 != row["input_sha256"]
                or expected_seed != int(row["simulation_seed"])):
            raise ValueError(f"archived match does not reconcile to its immutable fixture inputs: {match_id}")
        if row["match_state_json"] is None:
            retained_events = self.connection.execute(
                "SELECT COUNT(*) FROM archived_events WHERE match_id = ?", (str(match_id),)
            ).fetchone()[0]
            if retained_events:
                raise ValueError(f"pruned archive details still contain event rows for {match_id}")
            return analytics

        state_json = row["match_state_json"]
        if _sha256(state_json) != row["state_sha256"]:
            raise ValueError(f"archived match state integrity check failed for {match_id}")
        state = MatchState.from_json(state_json)
        reconstructed = WorldMatchRecord(
            world_id=meta["world_id"], season_id=meta["season_id"],
            fixture_id=row["fixture_id"], match_id=MatchId(row["match_id"]),
            competition_id=row["competition_id"], competition_kind=CompetitionKind(row["competition_kind"]),
            scheduled_on=WorldDate(date.fromisoformat(row["scheduled_on"])),
            kickoff_minute=row["kickoff_minute"],
            home_participant_id=row["home_participant_id"],
            away_participant_id=row["away_participant_id"],
            home_goals=row["home_goals"], away_goals=row["away_goals"],
            ruleset_id=row["ruleset_id"], ruleset_version=row["ruleset_version"],
            event_count=row["event_count"], simulation_seed=int(row["simulation_seed"]),
            input_sha256=row["input_sha256"], state_sha256=row["state_sha256"],
            match_state_json=state_json, fixture_json=fixture_row["input_json"],
            competition_json=competition_row["definition_json"],
            player_lines=player_lines, goal_lineage=goals,
        )
        if reconstructed.analytics_json != raw:
            raise ValueError(f"archived projections do not reconcile to match state for {match_id}")
        self._validate_event_rows(row["match_id"], state)
        return analytics

    def append(
        self,
        record: WorldMatchRecord,
        *,
        world_flow_state: object | None = None,
        world_flow_exposures: tuple[object, ...] = (),
        world_flow_settlement: object | None = None,
        expected_previous_state_sha256: str | None = None,
    ) -> bool:
        """Atomically add a complete match; return False for an exact replay.

        In a flow-enabled archive, direct retry is supported for the latest
        committed fixture only because the archive keeps one rolling flow
        checkpoint. Use ``simulate_world_season`` to resume an older committed
        prefix; it validates and skips every archived fixture in schedule order.
        """
        if not isinstance(record, WorldMatchRecord):
            raise TypeError("archive append requires a validated full-match record")
        flow_update = None
        if world_flow_state is None:
            if (world_flow_exposures or world_flow_settlement is not None
                    or expected_previous_state_sha256 is not None):
                raise ValueError("world flow checkpoint data must be supplied together")
        else:
            from games.touchline.esb.world.competition_flow import (
                WorldCompetitionState,
                WorldExposureResolution,
                WorldFixtureSettlement,
                WorldFlowCheckpoint,
                WorldFlowInputs,
                flow_snapshot_sha256,
                validate_world_flow_append,
            )

            if (not isinstance(world_flow_state, WorldCompetitionState)
                    or not isinstance(world_flow_settlement, WorldFixtureSettlement)
                    or not isinstance(world_flow_exposures, tuple)
                    or any(not isinstance(item, WorldExposureResolution) for item in world_flow_exposures)):
                raise TypeError("atomic world append requires validated flow state, settlement and exposure records")
            if (not isinstance(expected_previous_state_sha256, str)
                    or len(expected_previous_state_sha256) != 64
                    or any(char not in "0123456789abcdef" for char in expected_previous_state_sha256)):
                raise ValueError("atomic world append requires the previous checkpoint hash")
            if (world_flow_state.revision < 1
                    or world_flow_state.last_fixture_id != record.fixture_id
                    or str(world_flow_state.last_match_id) != str(record.match_id)
                    or world_flow_state.last_input_sha256 != record.input_sha256
                    or world_flow_state.last_match_state_sha256 != record.state_sha256
                    or world_flow_settlement.fixture_id != record.fixture_id
                    or str(world_flow_settlement.match_id) != str(record.match_id)
                    or world_flow_settlement.input_sha256 != record.input_sha256
                    or world_flow_settlement.match_state_sha256 != record.state_sha256
                    or world_flow_settlement.competition_id != record.competition_id
                    or world_flow_settlement.scheduled_on != record.scheduled_on
                    or world_flow_state.last_pre_match_conditions_sha256
                       != world_flow_settlement.pre_match_conditions_sha256
                    or world_flow_state.last_exposure_sha256 != world_flow_settlement.exposure_sha256):
                raise ValueError("world flow checkpoint does not reconcile to the match being appended")
            exposure_ids = tuple(item.player_id for item in world_flow_exposures)
            expected_player_ids = tuple(sorted(
                (item.player_id for item in world_flow_state.profiles), key=str,
            ))
            if exposure_ids != expected_player_ids:
                raise ValueError("world fixture exposure must cover the complete ordered player catalog")
            if any(item.fixture_id != record.fixture_id or item.match_id != record.match_id
                   or item.match_state_sha256 != record.state_sha256
                   or item.occurred_on != record.scheduled_on
                   for item in world_flow_exposures):
                raise ValueError("world exposure records do not belong to the match being appended")
            if flow_snapshot_sha256(world_flow_exposures) != world_flow_settlement.exposure_sha256:
                raise ValueError("world exposure records do not match their settlement checksum")
            flow_update = {
                "state": world_flow_state,
                "state_json": world_flow_state.checkpoint_json(),
                "state_sha256": world_flow_state.state_sha256,
                "exposures": world_flow_exposures,
                "settlement": world_flow_settlement,
                "expected_previous_sha256": expected_previous_state_sha256,
            }
        connection = self.connection
        meta = {row["key"]: row["value"] for row in connection.execute(
            "SELECT key, value FROM archive_meta"
        )}
        if (meta.get("world_id"), meta.get("season_id")) != (record.world_id, record.season_id):
            raise ValueError("match belongs to another archived world or season")
        expected_seed = derive_fixture_seed(
            meta["world_id"], meta["season_id"], int(meta["seed"]), record.fixture_id,
        )
        if record.simulation_seed != expected_seed:
            raise ValueError("match simulation seed does not match the initialized world fixture")
        fixture_input = _canonical_json(_json(record.fixture_json, "fixture snapshot"))
        competition_input = _canonical_json(_json(record.competition_json, "competition snapshot"))
        connection.execute("BEGIN IMMEDIATE")
        try:
            flow_row = None
            previous_flow_state = None
            if flow_update is not None:
                flow_row = connection.execute(
                    "SELECT * FROM world_flow_state WHERE singleton = 1"
                ).fetchone()
                if (flow_row is None
                        or flow_update["state"].initial_state_sha256 != flow_row["initial_state_sha256"]
                        or flow_update["state"].schedule_sha256 != flow_row["schedule_sha256"]):
                    raise ValueError("world flow checkpoint changed before its match transaction")
                try:
                    flow_inputs = loads(flow_row["inputs_json"], WorldFlowInputs)
                except SerializationError as exc:
                    raise ValueError("stored world flow immutable inputs are invalid") from exc
                if (flow_inputs.inputs_sha256 != flow_row["inputs_sha256"]
                        or flow_inputs.inputs_sha256 != flow_row["initial_state_sha256"]):
                    raise ValueError("stored world flow immutable inputs fail their semantic fingerprint")
                self._validate_stored_flow_schedule(flow_inputs)
                prior_checkpoint_json = flow_row["checkpoint_json"]
                if _sha256(prior_checkpoint_json) != flow_row["checkpoint_sha256"]:
                    raise ValueError("world flow checkpoint integrity check failed")
                prior_checkpoint = WorldFlowCheckpoint.from_json(prior_checkpoint_json)
                if (prior_checkpoint.revision != flow_row["revision"]
                        or prior_checkpoint.world_id != flow_row["world_id"]
                        or prior_checkpoint.season_id != flow_row["season_id"]
                        or prior_checkpoint.last_fixture_id != flow_row["last_fixture_id"]
                        or (str(prior_checkpoint.last_match_id) if prior_checkpoint.last_match_id else None)
                           != flow_row["last_match_id"]
                        or prior_checkpoint.last_input_sha256 != flow_row["last_input_sha256"]
                        or prior_checkpoint.last_match_state_sha256 != flow_row["last_match_state_sha256"]):
                    raise ValueError("world flow checkpoint columns do not reconcile")
                previous_flow_state = flow_inputs.restore_checkpoint(prior_checkpoint)
            by_fixture = connection.execute(
                "SELECT match_id, input_sha256, state_sha256 FROM archived_matches WHERE fixture_id = ?",
                (record.fixture_id,),
            ).fetchone()
            by_match = connection.execute(
                "SELECT fixture_id, input_sha256, state_sha256 FROM archived_matches WHERE match_id = ?",
                (str(record.match_id),),
            ).fetchone()
            if by_fixture is not None or by_match is not None:
                if (by_fixture is not None and by_match is not None
                        and by_fixture["match_id"] == str(record.match_id)
                        and by_match["fixture_id"] == record.fixture_id
                        and by_fixture["input_sha256"] == record.input_sha256
                        and by_fixture["state_sha256"] == record.state_sha256):
                    self._validate_archived_match(record.match_id, expected_record=record)
                    if flow_update is not None:
                        stored_flow = connection.execute(
                            "SELECT match_state_sha256, exposure_sha256 FROM world_flow_fixtures "
                            "WHERE fixture_id = ?", (record.fixture_id,),
                        ).fetchone()
                        if (flow_row["checkpoint_sha256"] != flow_update["state_sha256"]
                                or stored_flow is None
                                or stored_flow["match_state_sha256"] != record.state_sha256
                                or stored_flow["exposure_sha256"] != flow_update["settlement"].exposure_sha256):
                            raise ValueError("replayed world match does not match its committed flow checkpoint")
                    connection.execute("COMMIT")
                    return False
                raise ValueError("archive fixture or match ID already exists with different evidence")
            if flow_update is None:
                flow_table = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'world_flow_state'"
                ).fetchone()
                flow_state = connection.execute(
                    "SELECT 1 FROM world_flow_state WHERE singleton = 1"
                ).fetchone() if flow_table is not None else None
                if flow_state is not None:
                    raise ValueError(
                        "world-flow seasons require match, exposure and checkpoint data in one append"
                    )
            if flow_update is not None:
                next_fixture = connection.execute(
                    "SELECT fixture_id, match_id, competition_id, scheduled_on, kickoff_minute, input_sha256 "
                    "FROM world_fixtures ORDER BY scheduled_on, kickoff_minute, competition_id, fixture_id "
                    "LIMIT 1 OFFSET ?",
                    (flow_row["revision"],),
                ).fetchone()
                if (next_fixture is None
                        or next_fixture["fixture_id"] != record.fixture_id
                        or next_fixture["match_id"] != str(record.match_id)
                        or next_fixture["competition_id"] != record.competition_id
                        or next_fixture["scheduled_on"] != record.scheduled_on.isoformat
                        or next_fixture["kickoff_minute"] != record.kickoff_minute
                        or next_fixture["input_sha256"] != record.input_sha256):
                    raise ValueError("world-flow match must append the next chronological scheduled fixture")
            if flow_update is not None and (
                    flow_row["checkpoint_sha256"] != flow_update["expected_previous_sha256"]
                    or flow_update["state"].revision != flow_row["revision"] + 1):
                raise ValueError("world flow checkpoint changed before its match transaction")
            self._ensure_competition(record.competition_id, competition_input)
            fixture_row = connection.execute(
                "SELECT input_sha256, match_id, input_json FROM world_fixtures WHERE fixture_id = ?",
                (record.fixture_id,),
            ).fetchone()
            if (fixture_row is None
                    or fixture_row["input_sha256"] != record.input_sha256
                    or fixture_row["match_id"] != str(record.match_id)
                    or fixture_row["input_json"] != fixture_input):
                raise ValueError("fixture snapshot conflicts with the immutable world schedule")
            if flow_update is not None:
                competition_row = connection.execute(
                    "SELECT definition_json FROM world_competitions WHERE competition_id = ?",
                    (record.competition_id,),
                ).fetchone()
                if competition_row is None:
                    raise ValueError("world-flow competition snapshot is missing from the immutable schedule")
                fixture_snapshot = WorldFixture.from_json(fixture_row["input_json"])
                competition_snapshot = WorldCompetition.from_json(competition_row["definition_json"])
                validate_world_flow_append(
                    previous_flow_state, fixture_snapshot, competition_snapshot, record,
                    flow_update["state"], flow_update["exposures"], flow_update["settlement"],
                )
            goal_json = dumps(_GoalLineageEnvelope(record.goal_lineage))
            connection.execute(
                "INSERT INTO archived_matches(match_id, fixture_id, competition_id, competition_kind, "
                "scheduled_on, kickoff_minute, home_participant_id, away_participant_id, home_goals, "
                "away_goals, ruleset_id, ruleset_version, engine_id, engine_version, event_count, "
                "simulation_seed, input_sha256, state_sha256, match_state_json, goal_lineage_json, "
                "analytics_json, analytics_sha256) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (str(record.match_id), record.fixture_id, record.competition_id,
                 record.competition_kind.value, record.scheduled_on.isoformat,
                 record.kickoff_minute, record.home_participant_id, record.away_participant_id,
                 record.home_goals, record.away_goals, record.ruleset_id,
                 record.ruleset_version, record.engine_id, record.engine_version,
                 record.event_count, str(record.simulation_seed), record.input_sha256, record.state_sha256,
                 record.match_state_json, goal_json, record.analytics_json, record.analytics_sha256),
            )
            connection.executemany(
                "INSERT INTO player_match_lines(match_id, player_id, participant_id, role, minutes, stats_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [(str(record.match_id), str(item.player_id), item.participant_id,
                  item.role.value, item.minutes_played, _canonical_json(dict(item.statistics)))
                 for item in record.player_lines],
            )
            state = record.match_state()
            connection.executemany(
                "INSERT INTO archived_events(match_id, sequence, event_id, tick, kind, actor_id, "
                "cause_event_id, parent_event_id, payload_json, outcome_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(str(record.match_id), event.sequence, str(event.event_id), event.match_tick,
                  event.kind, event.payload.get("actor_id"),
                  str(event.cause_event_id) if event.cause_event_id else None,
                  str(event.parent_event_id) if event.parent_event_id else None,
                  event.payload_json, event.outcome_json)
                 for event in state.events],
            )
            if flow_update is not None:
                settlement = flow_update["settlement"]
                connection.execute(
                    "INSERT INTO world_flow_fixtures(fixture_id, match_id, competition_id, scheduled_on, "
                    "kickoff_minute, input_sha256, match_state_sha256, pre_match_conditions_sha256, "
                    "exposure_sha256, exposure_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (settlement.fixture_id, str(settlement.match_id), settlement.competition_id,
                     settlement.scheduled_on.isoformat, record.kickoff_minute,
                     settlement.input_sha256, settlement.match_state_sha256,
                     settlement.pre_match_conditions_sha256, settlement.exposure_sha256,
                     len(flow_update["exposures"])),
                )
                connection.executemany(
                    "INSERT INTO world_flow_exposures(fixture_id, player_id, match_id, resolution_json, "
                    "resolution_sha256) VALUES (?, ?, ?, ?, ?)",
                    [(item.fixture_id, str(item.player_id), str(item.match_id),
                      dumps(item), _sha256(dumps(item)))
                     for item in flow_update["exposures"]],
                )
                updated = connection.execute(
                    "UPDATE world_flow_state SET checkpoint_json = ?, checkpoint_sha256 = ?, revision = ?, "
                    "last_fixture_id = ?, last_match_id = ?, last_input_sha256 = ?, last_match_state_sha256 = ? "
                    "WHERE singleton = 1 AND checkpoint_sha256 = ?",
                    (flow_update["state_json"], flow_update["state_sha256"],
                     flow_update["state"].revision, flow_update["state"].last_fixture_id,
                     str(flow_update["state"].last_match_id), flow_update["state"].last_input_sha256,
                     flow_update["state"].last_match_state_sha256,
                     flow_update["expected_previous_sha256"]),
                )
                if updated.rowcount != 1:
                    raise ValueError("world flow checkpoint lost its atomic compare-and-swap")
            connection.execute("COMMIT")
            return True
        except BaseException:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise

    def append_with_world_flow(
        self,
        record: WorldMatchRecord,
        state: object,
        exposures: tuple[object, ...],
        settlement: object,
        *,
        expected_previous_state_sha256: str,
    ) -> str:
        """Atomically append match evidence, exposures and the rolling checkpoint."""
        from games.touchline.esb.world.competition_flow import WorldCompetitionState

        if not isinstance(state, WorldCompetitionState):
            raise TypeError("world-flow append requires a WorldCompetitionState")
        self.append(
            record,
            world_flow_state=state,
            world_flow_exposures=exposures,
            world_flow_settlement=settlement,
            expected_previous_state_sha256=expected_previous_state_sha256,
        )
        return state.state_sha256

    def _ensure_competition(self, competition_id: str, definition_json: str) -> None:
        existing = self.connection.execute(
            "SELECT definition_json FROM world_competitions WHERE competition_id = ?",
            (competition_id,),
        ).fetchone()
        if existing is not None:
            if existing["definition_json"] != definition_json:
                raise ValueError("competition definition changed within the archived season")
            return
        self.connection.execute(
            "INSERT INTO world_competitions(competition_id, definition_json) VALUES (?, ?)",
            (competition_id, definition_json),
        )

    def _validate_stored_flow_schedule(self, flow_inputs: object) -> None:
        """Rebuild the complete immutable schedule from DB rows before a flow append."""
        from games.touchline.esb.world.competition_flow import WorldFlowInputs

        if not isinstance(flow_inputs, WorldFlowInputs):
            raise TypeError("stored schedule validation requires immutable world flow inputs")
        connection = self.connection
        metadata = {row["key"]: row["value"] for row in connection.execute(
            "SELECT key, value FROM archive_meta"
        )}
        expected_metadata = {
            "schema_version": str(ARCHIVE_SCHEMA_VERSION),
            "world_id": flow_inputs.world_id,
            "season_id": flow_inputs.season_id,
        }
        try:
            schedule_seed = int(metadata.get("seed", ""))
        except ValueError as exc:
            raise ValueError("world-flow archive schedule seed is invalid") from exc
        if (set(metadata) != set(expected_metadata) | {"seed"}
                or any(metadata.get(key) != value for key, value in expected_metadata.items())
                or str(schedule_seed) != metadata.get("seed")):
            raise ValueError("world-flow archive identity does not match its immutable inputs")

        competitions = []
        for row in connection.execute(
                "SELECT competition_id, definition_json FROM world_competitions ORDER BY rowid"):
            competition = WorldCompetition.from_json(row["definition_json"])
            if (competition.competition_id != row["competition_id"]
                    or immutable_snapshot_json(competition) != row["definition_json"]):
                raise ValueError("world-flow competition rows differ from their immutable definitions")
            competitions.append(competition)
        competition_by_id = {item.competition_id: item for item in competitions}

        fixtures = []
        for row in connection.execute("SELECT * FROM world_fixtures ORDER BY rowid"):
            fixture = WorldFixture.from_json(row["input_json"])
            competition = competition_by_id.get(fixture.competition_id)
            if competition is None:
                raise ValueError("world-flow fixture references a missing competition")
            expected_input_sha256 = fixture_input_sha256(fixture, competition)
            if (fixture.fixture_id != row["fixture_id"]
                    or str(fixture.match_id) != row["match_id"]
                    or fixture.competition_id != row["competition_id"]
                    or fixture.scheduled_on.isoformat != row["scheduled_on"]
                    or fixture.kickoff_minute != row["kickoff_minute"]
                    or immutable_snapshot_json(fixture) != row["input_json"]
                    or expected_input_sha256 != row["input_sha256"]):
                raise ValueError("world-flow fixture rows differ from their immutable snapshots")
            fixtures.append(fixture)
        try:
            schedule = WorldSeasonSchedule(
                flow_inputs.world_id, flow_inputs.season_id, schedule_seed,
                tuple(competitions), tuple(fixtures),
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("stored world-flow schedule is invalid") from exc
        schedule_sha256 = _sha256(immutable_snapshot_json(schedule))
        if schedule_sha256 != flow_inputs.schedule_sha256:
            raise ValueError("stored world-flow schedule differs from its immutable fingerprint")

    def _validated_competition_definition(self, competition_id: str) -> WorldCompetition:
        row = self.connection.execute(
            "SELECT definition_json FROM world_competitions WHERE competition_id = ?",
            (competition_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown archived competition: {competition_id}")
        definition_json = row["definition_json"]
        competition = WorldCompetition.from_json(definition_json)
        if competition.competition_id != competition_id:
            raise ValueError("archived competition ID does not match its immutable definition")
        fixtures = self.connection.execute(
            "SELECT fixture_id, match_id, competition_id, scheduled_on, kickoff_minute, "
            "input_sha256, input_json FROM world_fixtures WHERE competition_id = ? ORDER BY fixture_id",
            (competition_id,),
        ).fetchall()
        if not fixtures:
            raise ValueError("archived competition has no immutable fixture snapshots")
        for fixture_row in fixtures:
            fixture = WorldFixture.from_json(fixture_row["input_json"])
            snapshot_sha256 = _sha256(fixture_row["input_json"] + "\n" + definition_json)
            if (fixture.fixture_id != fixture_row["fixture_id"]
                    or str(fixture.match_id) != fixture_row["match_id"]
                    or fixture.competition_id != competition_id
                    or fixture.scheduled_on.isoformat != fixture_row["scheduled_on"]
                    or fixture.kickoff_minute != fixture_row["kickoff_minute"]
                    or ({fixture.home_participant_id, fixture.away_participant_id}
                        - set(competition.participant_ids))
                    or snapshot_sha256 != fixture_row["input_sha256"]):
                raise ValueError("archived competition differs from its immutable fixture snapshots")
        return competition

    def simulate(
        self,
        schedule: WorldSeasonSchedule,
        *,
        maximum_fixtures: int | None = None,
    ) -> SimulationProgress:
        """Simulate in calendar order, committing each match before continuing."""
        if type(maximum_fixtures) is not int and maximum_fixtures is not None:
            raise TypeError("maximum fixture count must be an integer or None")
        if maximum_fixtures is not None and maximum_fixtures < 0:
            raise ValueError("maximum fixture count cannot be negative")
        self.initialize(schedule)
        simulated = skipped = 0
        for fixture in schedule.ordered_fixtures:
            competition = schedule.competition(fixture.competition_id)
            expected_input = fixture_input_sha256(fixture, competition)
            existing = self.recorded_fixture(
                fixture.fixture_id,
                expected_input_sha256=expected_input,
                expected_match_id=str(fixture.match_id),
                expected_simulation_seed=fixture_seed(schedule, fixture),
            )
            if existing is not None:
                skipped += 1
                continue
            if maximum_fixtures is not None and simulated >= maximum_fixtures:
                break
            match = simulate_fixture(schedule, fixture)
            record = WorldMatchRecord.create(schedule, fixture, match)
            self.append(record)
            simulated += 1
        archived = int(self.connection.execute("SELECT COUNT(*) FROM archived_matches").fetchone()[0])
        return SimulationProgress(
            scheduled=len(schedule.fixtures),
            archived=archived,
            simulated_this_run=simulated,
            resumed_this_run=skipped,
            pending=len(schedule.fixtures) - archived,
        )

    def match_summary(self, match_id: MatchId | str) -> dict[str, Any]:
        validate_id(match_id, kind="archived match ID")
        analytics = self._validate_archived_match(match_id)
        row = self.connection.execute(
            "SELECT * FROM archived_matches WHERE match_id = ?", (str(match_id),)
        ).fetchone()
        return {
            "match_id": row["match_id"],
            "fixture_id": row["fixture_id"],
            "competition_id": row["competition_id"],
            "competition_kind": row["competition_kind"],
            "scheduled_on": row["scheduled_on"],
            "kickoff_minute": row["kickoff_minute"],
            "home_participant_id": row["home_participant_id"],
            "away_participant_id": row["away_participant_id"],
            "home_goals": row["home_goals"],
            "away_goals": row["away_goals"],
            "ruleset_id": row["ruleset_id"],
            "ruleset_version": row["ruleset_version"],
            "engine_id": row["engine_id"],
            "engine_version": row["engine_version"],
            "event_count": row["event_count"],
            "simulation_seed": int(row["simulation_seed"]),
            "state_sha256": row["state_sha256"],
            "details_available": row["match_state_json"] is not None,
            "goal_lineage": analytics["goal_lineage"],
        }

    def player_match_history(
        self, player_id: PlayerId | str, *, competition_id: str | None = None
    ) -> tuple[PlayerMatchSummary, ...]:
        validate_id(player_id, kind="archived player ID")
        if competition_id is not None:
            validate_id(competition_id, kind="history competition ID")
        sql = (
            "SELECT l.*, m.fixture_id, m.competition_id, m.scheduled_on, m.kickoff_minute, "
            "m.home_participant_id, m.away_participant_id, m.home_goals, m.away_goals "
            "FROM player_match_lines l JOIN archived_matches m USING(match_id) "
            "WHERE l.player_id = ?"
        )
        args: list[Any] = [str(player_id)]
        if competition_id is not None:
            sql += " AND m.competition_id = ?"
            args.append(competition_id)
        sql += " ORDER BY m.scheduled_on, m.kickoff_minute, m.match_id"
        rows = self.connection.execute(sql, args).fetchall()
        for match_id in sorted({row["match_id"] for row in rows}):
            self._validate_archived_match(match_id)
        result = []
        for row in rows:
            home = row["participant_id"] == row["home_participant_id"]
            opponent = row["away_participant_id"] if home else row["home_participant_id"]
            result.append(PlayerMatchSummary(
                MatchId(row["match_id"]), row["fixture_id"], row["competition_id"],
                WorldDate(date.fromisoformat(row["scheduled_on"])), row["participant_id"],
                opponent, home,
                row["home_goals"] if home else row["away_goals"],
                row["away_goals"] if home else row["home_goals"],
                row["minutes"], MatchdayRole(row["role"]),
                tuple(sorted(_json(row["stats_json"], "player match statistics").items())),
            ))
        return tuple(result)

    def player_career_summary(
        self, player_id: PlayerId | str, *, competition_id: str | None = None
    ) -> PlayerCareerSummary:
        history = self.player_match_history(player_id, competition_id=competition_id)
        totals: dict[str, int] = {}
        for item in history:
            for key, value in item.statistics:
                totals[key] = totals.get(key, 0) + value
        return PlayerCareerSummary(
            PlayerId(str(player_id)),
            len(history),
            sum(item.minutes_played > 0 for item in history),
            sum(item.minutes_played for item in history),
            tuple(sorted(totals.items())),
        )

    def competition_table(self, competition_id: str) -> tuple[CompetitionTableLine, ...]:
        validate_id(competition_id, kind="table competition ID")
        competition = self._validated_competition_definition(competition_id)
        if competition.kind is not CompetitionKind.LEAGUE:
            raise ValueError("a league table can only be requested for a league competition")
        rows = self.connection.execute(
            "SELECT match_id, home_participant_id, away_participant_id, home_goals, away_goals "
            "FROM archived_matches WHERE competition_id = ? ORDER BY scheduled_on, kickoff_minute, match_id",
            (competition_id,),
        ).fetchall()
        for row in rows:
            self._validate_archived_match(row["match_id"])
        totals = {participant_id: [0, 0, 0, 0, 0, 0, 0, 0]
                  for participant_id in competition.participant_ids}
        for row in rows:
            home = totals[row["home_participant_id"]]
            away = totals[row["away_participant_id"]]
            hg, ag = row["home_goals"], row["away_goals"]
            home[0] += 1
            away[0] += 1
            home[4] += hg
            home[5] += ag
            away[4] += ag
            away[5] += hg
            if hg > ag:
                home[1] += 1
                home[7] += 3
                away[3] += 1
            elif hg < ag:
                away[1] += 1
                away[7] += 3
                home[3] += 1
            else:
                home[2] += 1
                away[2] += 1
                home[7] += 1
                away[7] += 1
        return tuple(sorted((
            CompetitionTableLine(
                participant_id, values[0], values[1], values[2], values[3],
                values[4], values[5], values[4] - values[5], values[7],
            )
            for participant_id, values in totals.items()
        ), key=lambda row: (-row.points, -row.goal_difference, -row.goals_for, row.participant_id)))

    def match_state(self, match_id: MatchId | str) -> MatchState:
        validate_id(match_id, kind="archived match ID")
        row = self.connection.execute(
            "SELECT match_state_json, state_sha256 FROM archived_matches WHERE match_id = ?",
            (str(match_id),),
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown archived match: {match_id}")
        if row["match_state_json"] is None:
            raise ArchiveDetailUnavailable(f"detailed match data expired for {match_id}")
        if _sha256(row["match_state_json"]) != row["state_sha256"]:
            raise ValueError(f"archived match state integrity check failed for {match_id}")
        self._validate_archived_match(match_id)
        return MatchState.from_json(row["match_state_json"])

    def events(self, match_id: MatchId | str) -> tuple[EventEnvelope, ...]:
        validate_id(match_id, kind="archived match ID")
        match = self.match_state(match_id)
        return self._validate_event_rows(str(match_id), match)

    def _validate_event_rows(self, match_id: str, match: MatchState) -> tuple[EventEnvelope, ...]:
        rows = self.connection.execute(
            "SELECT sequence, event_id, tick, kind, actor_id, cause_event_id, parent_event_id, "
            "payload_json, outcome_json FROM archived_events WHERE match_id = ? ORDER BY sequence",
            (match_id,),
        ).fetchall()
        if len(rows) != len(match.events):
            raise ValueError("archived event rows do not reconcile to the full match record")
        if any(
            row["actor_id"] != (
                str(event.payload.get("actor_id"))
                if event.payload.get("actor_id") is not None else None
            )
            for row, event in zip(rows, match.events)
        ):
            raise ValueError("archived event actor index does not reconcile to the full match record")
        events = tuple(EventEnvelope(
            EventId(row["event_id"]), "match", str(match_id), row["sequence"], row["kind"],
            match_id=MatchId(str(match_id)), match_tick=row["tick"],
            cause_event_id=EventId(row["cause_event_id"]) if row["cause_event_id"] else None,
            parent_event_id=EventId(row["parent_event_id"]) if row["parent_event_id"] else None,
            payload_json=row["payload_json"], outcome_json=row["outcome_json"],
        ) for row in rows)
        if events != match.events:
            raise ValueError("archived event rows do not reconcile to the full match chronology")
        return events

    def apply_retention(
        self, policy: DetailRetentionPolicy, as_of: WorldDate
    ) -> tuple[str, ...]:
        if not isinstance(policy, DetailRetentionPolicy) or not isinstance(as_of, WorldDate):
            raise TypeError("retention requires an explicit policy and world date")
        if policy.maximum_age_days is None and policy.maximum_detailed_matches is None:
            return ()
        connection = self.connection
        connection.execute("BEGIN IMMEDIATE")
        try:
            candidates: set[str] = set()
            rows = connection.execute(
                "SELECT match_id, scheduled_on, kickoff_minute FROM archived_matches "
                "WHERE match_state_json IS NOT NULL "
                "ORDER BY scheduled_on DESC, kickoff_minute DESC, match_id DESC"
            ).fetchall()
            if policy.maximum_age_days is not None:
                cutoff = as_of.day - timedelta(days=policy.maximum_age_days)
                candidates.update(row["match_id"] for row in rows
                                  if date.fromisoformat(row["scheduled_on"]) < cutoff)
            eligible = [row for row in rows if row["match_id"] not in candidates]
            if policy.maximum_detailed_matches is not None:
                candidates.update(row["match_id"] for row in eligible[policy.maximum_detailed_matches:])
            ordered = tuple(sorted(candidates))
            for match_id in ordered:
                self._validate_archived_match(match_id)
            for match_id in ordered:
                connection.execute("UPDATE archived_matches SET match_state_json = NULL WHERE match_id = ?", (match_id,))
                connection.execute("DELETE FROM archived_events WHERE match_id = ?", (match_id,))
            if ordered:
                run_id = derive_id(
                    "retention", "world-archive-retention-v1", as_of.isoformat,
                    policy.maximum_age_days, policy.maximum_detailed_matches, *ordered,
                )
                connection.execute(
                    "INSERT OR IGNORE INTO retention_runs(run_id, applied_on, max_age_days, "
                    "max_detailed_matches, pruned_match_ids_json) VALUES (?, ?, ?, ?, ?)",
                    (run_id, as_of.isoformat, policy.maximum_age_days,
                     policy.maximum_detailed_matches, _canonical_json(ordered)),
                )
            connection.execute("COMMIT")
        except BaseException:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        return ordered

    def metrics(self) -> ArchiveMetrics:
        metadata = {row["key"]: row["value"] for row in self.connection.execute(
            "SELECT key, value FROM archive_meta"
        )}
        counts = self.connection.execute(
            "SELECT COUNT(*) AS matches, "
            "SUM(CASE WHEN match_state_json IS NOT NULL THEN 1 ELSE 0 END) AS detailed, "
            "SUM(event_count) AS total_events FROM archived_matches"
        ).fetchone()
        player_rows = self.connection.execute("SELECT COUNT(*) FROM player_match_lines").fetchone()[0]
        players = self.connection.execute("SELECT COUNT(DISTINCT player_id) FROM player_match_lines").fetchone()[0]
        events = self.connection.execute("SELECT COUNT(*) FROM archived_events").fetchone()[0]
        summary_matches = self.connection.execute(
            "SELECT COALESCE(SUM(LENGTH(goal_lineage_json) + LENGTH(input_sha256) + LENGTH(state_sha256) "
            "+ LENGTH(analytics_json) + LENGTH(analytics_sha256)), 0) "
            "FROM archived_matches"
        ).fetchone()[0]
        summary_players = self.connection.execute(
            "SELECT COALESCE(SUM(LENGTH(player_id) + LENGTH(participant_id) + LENGTH(stats_json)), 0) "
            "FROM player_match_lines"
        ).fetchone()[0]
        database_bytes = self.connection.execute("PRAGMA page_count").fetchone()[0] * self.connection.execute(
            "PRAGMA page_size"
        ).fetchone()[0]
        return ArchiveMetrics(
            metadata["world_id"], metadata["season_id"], counts["matches"], counts["detailed"] or 0,
            events, counts["total_events"] or 0, player_rows, players, database_bytes,
            summary_matches + summary_players,
        )


@dataclass(frozen=True)
class SimulationProgress:
    scheduled: int
    archived: int
    simulated_this_run: int
    resumed_this_run: int
    pending: int

    def __post_init__(self) -> None:
        values = (self.scheduled, self.archived, self.simulated_this_run,
                  self.resumed_this_run, self.pending)
        if any(type(value) is not int or value < 0 for value in values):
            raise ValueError("simulation progress counts must be non-negative integers")
        if self.archived + self.pending != self.scheduled:
            raise ValueError("simulation progress must reconcile archived and pending fixtures")


@dataclass(frozen=True)
class _GoalLineageEnvelope:
    goals: tuple[GoalLineage, ...]


_SCHEMA = """
CREATE TABLE archive_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE world_competitions(
    competition_id TEXT PRIMARY KEY,
    definition_json TEXT NOT NULL
);
CREATE TABLE world_fixtures(
    fixture_id TEXT PRIMARY KEY,
    match_id TEXT NOT NULL UNIQUE,
    competition_id TEXT NOT NULL REFERENCES world_competitions(competition_id),
    scheduled_on TEXT NOT NULL,
    kickoff_minute INTEGER NOT NULL CHECK(kickoff_minute BETWEEN 0 AND 1439),
    input_sha256 TEXT NOT NULL,
    input_json TEXT NOT NULL
);
CREATE TABLE archived_matches(
    match_id TEXT PRIMARY KEY,
    fixture_id TEXT NOT NULL UNIQUE REFERENCES world_fixtures(fixture_id),
    competition_id TEXT NOT NULL REFERENCES world_competitions(competition_id),
    competition_kind TEXT NOT NULL,
    scheduled_on TEXT NOT NULL,
    kickoff_minute INTEGER NOT NULL,
    home_participant_id TEXT NOT NULL,
    away_participant_id TEXT NOT NULL,
    home_goals INTEGER NOT NULL CHECK(home_goals >= 0),
    away_goals INTEGER NOT NULL CHECK(away_goals >= 0),
    ruleset_id TEXT NOT NULL,
    ruleset_version INTEGER NOT NULL,
    engine_id TEXT NOT NULL,
    engine_version TEXT NOT NULL,
    event_count INTEGER NOT NULL CHECK(event_count >= 0),
    simulation_seed TEXT NOT NULL,
    input_sha256 TEXT NOT NULL,
    state_sha256 TEXT NOT NULL,
    match_state_json TEXT,
    goal_lineage_json TEXT NOT NULL,
    analytics_json TEXT NOT NULL,
    analytics_sha256 TEXT NOT NULL
);
CREATE TABLE player_match_lines(
    match_id TEXT NOT NULL REFERENCES archived_matches(match_id) ON DELETE CASCADE,
    player_id TEXT NOT NULL,
    participant_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('starter', 'substitute', 'unavailable')),
    minutes REAL NOT NULL CHECK(minutes >= 0 AND minutes <= 150),
    stats_json TEXT NOT NULL,
    PRIMARY KEY(match_id, player_id)
);
CREATE INDEX player_lines_by_player ON player_match_lines(player_id, match_id);
CREATE INDEX matches_by_competition_date ON archived_matches(competition_id, scheduled_on, kickoff_minute);
CREATE TABLE archived_events(
    match_id TEXT NOT NULL REFERENCES archived_matches(match_id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL CHECK(sequence >= 0),
    event_id TEXT NOT NULL UNIQUE,
    tick INTEGER NOT NULL CHECK(tick >= 0),
    kind TEXT NOT NULL,
    actor_id TEXT,
    cause_event_id TEXT,
    parent_event_id TEXT,
    payload_json TEXT NOT NULL,
    outcome_json TEXT NOT NULL,
    PRIMARY KEY(match_id, sequence)
);
CREATE INDEX events_by_actor ON archived_events(actor_id, match_id, sequence);
CREATE TABLE retention_runs(
    run_id TEXT PRIMARY KEY,
    applied_on TEXT NOT NULL,
    max_age_days INTEGER,
    max_detailed_matches INTEGER,
    pruned_match_ids_json TEXT NOT NULL
);
"""


__all__ = [
    "ARCHIVE_SCHEMA_VERSION", "ArchiveDetailUnavailable", "ArchiveMetrics",
    "CompetitionKind", "CompetitionTableLine", "DetailRetentionPolicy",
    "GoalLineage", "MatchdayRole", "PlayerCareerSummary", "PlayerMatchSummary",
    "ArchivedPlayerLine", "SimulationProgress", "WorldArchiveStore", "WorldMatchRecord",
]
