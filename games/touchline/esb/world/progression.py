"""Auditable season-end movement and qualification over archived results (P16c).

This module resolves competition entrants from finished, immutable season
evidence. It does not generate fixtures, alter club employment, or infer a
winner when the configured sporting ranking rules leave a tie unresolved.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import timedelta
from enum import Enum

from games.touchline.esb.ids import derive_id, validate_id
from games.touchline.esb.serialization import SerializationError, dumps, loads
from games.touchline.esb.time import WorldDate
from games.touchline.esb.world.archive import WorldArchiveStore
from games.touchline.esb.world.season import (
    CompetitionKind,
    WorldCompetition,
    WorldFixture,
    WorldSeasonSchedule,
    fixture_input_sha256,
    fixture_seed,
    immutable_snapshot_json,
)


PROGRESSION_SCHEMA_VERSION = 1


class QualificationPurpose(str, Enum):
    DOMESTIC_CUP = "domestic_cup"
    CONTINENTAL = "continental"
    NATIONAL_TOURNAMENT = "national_tournament"


class ProgressionKind(str, Enum):
    RETAINED = "retained"
    PROMOTED = "promoted"
    RELEGATED = "relegated"
    QUALIFIED = "qualified"


class ResultCompletionBasis(str, Enum):
    MATCH_STATE = "match_state"
    MAXIMUM_SCHEDULED_DURATION = "maximum_scheduled_duration"


class IncompleteCompetitionResults(ValueError):
    """Raised when a required source competition has unplayed fixtures."""


class UnresolvedTableTie(ValueError):
    """Raised when the authored sporting tie-breakers do not determine order."""


class RegistrationDeadlineMissed(ValueError):
    """Raised when source results cannot be known before destination entry closes."""


@dataclass(frozen=True)
class ProgressionDestination:
    """Next-edition competition entry window and first playable date."""

    competition_id: str
    kind: CompetitionKind
    registration_opens_on: WorldDate
    registration_closes_on: WorldDate
    starts_on: WorldDate
    minimum_entrants: int = 2
    maximum_entrants: int = 64

    def __post_init__(self) -> None:
        validate_id(self.competition_id, kind="progression destination ID")
        if not isinstance(self.kind, CompetitionKind):
            raise TypeError("progression destination requires a competition kind")
        if any(not isinstance(value, WorldDate) for value in (
                self.registration_opens_on, self.registration_closes_on, self.starts_on)):
            raise TypeError("progression destination requires registration and start dates")
        if self.registration_closes_on < self.registration_opens_on:
            raise ValueError("destination registration closes before it opens")
        if not self.registration_closes_on < self.starts_on:
            raise ValueError("destination registration must close before its start date")
        if (type(self.minimum_entrants) is not int or type(self.maximum_entrants) is not int
                or self.minimum_entrants < 2 or self.maximum_entrants < self.minimum_entrants):
            raise ValueError("destination entrant limits must satisfy 2 <= minimum <= maximum")


@dataclass(frozen=True)
class PromotionPyramid:
    """Adjacent source and next-edition leagues, ordered from highest to lowest."""

    pyramid_id: str
    source_competition_ids: tuple[str, ...]
    destination_competition_ids: tuple[str, ...]
    places_each_way: tuple[int, ...]

    def __post_init__(self) -> None:
        validate_id(self.pyramid_id, kind="promotion pyramid ID")
        for label, values in (
            ("source leagues", self.source_competition_ids),
            ("destination leagues", self.destination_competition_ids),
            ("movement places", self.places_each_way),
        ):
            if not isinstance(values, tuple):
                raise TypeError(f"pyramid {label} must be an immutable tuple")
        if (len(self.source_competition_ids) < 2
                or len(self.destination_competition_ids) != len(self.source_competition_ids)
                or len(self.places_each_way) != len(self.source_competition_ids) - 1):
            raise ValueError("pyramid needs matching league editions and one movement count per boundary")
        for competition_id in self.source_competition_ids + self.destination_competition_ids:
            validate_id(competition_id, kind="pyramid competition ID")
        if (len(set(self.source_competition_ids)) != len(self.source_competition_ids)
                or len(set(self.destination_competition_ids)) != len(self.destination_competition_ids)):
            raise ValueError("a pyramid cannot repeat a source or destination league")
        if set(self.source_competition_ids) & set(self.destination_competition_ids):
            raise ValueError("source and destination league editions must have different IDs")
        if any(type(value) is not int or value <= 0 for value in self.places_each_way):
            raise ValueError("each pyramid boundary must move a positive number of clubs")


@dataclass(frozen=True)
class QualificationRoute:
    """Place-based route from one finished table to a next-edition event."""

    route_id: str
    source_competition_id: str
    destination_competition_id: str
    purpose: QualificationPurpose
    places: tuple[int, ...]

    def __post_init__(self) -> None:
        validate_id(self.route_id, kind="qualification route ID")
        validate_id(self.source_competition_id, kind="qualification source ID")
        validate_id(self.destination_competition_id, kind="qualification destination ID")
        if self.source_competition_id == self.destination_competition_id:
            raise ValueError("qualification route source and destination must differ")
        if not isinstance(self.purpose, QualificationPurpose):
            raise TypeError("qualification route requires an explicit purpose")
        if not isinstance(self.places, tuple) or not self.places:
            raise TypeError("qualification places must be a non-empty immutable tuple")
        if (any(type(value) is not int or value <= 0 for value in self.places)
                or len(set(self.places)) != len(self.places)):
            raise ValueError("qualification places must be unique positive table positions")


@dataclass(frozen=True)
class LeagueTableScoring:
    """Explicit points and supported sporting tie-break order for this transition."""

    win_points: int = 3
    draw_points: int = 1
    loss_points: int = 0
    tie_breakers: tuple[str, ...] = ("goal_difference", "goals_for")

    def __post_init__(self) -> None:
        if any(type(value) is not int or value < 0 for value in (
                self.win_points, self.draw_points, self.loss_points)):
            raise ValueError("table points must be non-negative integers")
        if not self.win_points > self.draw_points > self.loss_points:
            raise ValueError("table scoring must order wins above draws above losses")
        if self.tie_breakers != ("goal_difference", "goals_for"):
            raise ValueError("P16c currently supports goal difference then goals scored as tie-breakers")


@dataclass(frozen=True)
class SeasonProgressionPlan:
    world_id: str
    source_season_id: str
    destination_season_id: str
    destinations: tuple[ProgressionDestination, ...]
    pyramids: tuple[PromotionPyramid, ...] = ()
    qualification_routes: tuple[QualificationRoute, ...] = ()
    scoring: LeagueTableScoring = LeagueTableScoring()
    schema_version: int = PROGRESSION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        validate_id(self.world_id, kind="progression world ID")
        validate_id(self.source_season_id, kind="progression source season ID")
        validate_id(self.destination_season_id, kind="progression destination season ID")
        if self.source_season_id == self.destination_season_id:
            raise ValueError("season progression must advance to a different season ID")
        if type(self.schema_version) is not int or self.schema_version != PROGRESSION_SCHEMA_VERSION:
            raise ValueError("unsupported season progression plan version")
        if (not isinstance(self.destinations, tuple) or not self.destinations
                or any(not isinstance(item, ProgressionDestination) for item in self.destinations)):
            raise TypeError("progression plan requires immutable competition destinations")
        if (not isinstance(self.pyramids, tuple)
                or any(not isinstance(item, PromotionPyramid) for item in self.pyramids)):
            raise TypeError("progression pyramids must be immutable records")
        if (not isinstance(self.qualification_routes, tuple)
                or any(not isinstance(item, QualificationRoute) for item in self.qualification_routes)):
            raise TypeError("qualification routes must be immutable records")
        if not isinstance(self.scoring, LeagueTableScoring):
            raise TypeError("progression plan requires explicit table scoring")
        destination_ids = {item.competition_id for item in self.destinations}
        if len(destination_ids) != len(self.destinations):
            raise ValueError("progression destinations must be unique")
        pyramid_ids = [item.pyramid_id for item in self.pyramids]
        route_ids = [item.route_id for item in self.qualification_routes]
        if len(pyramid_ids) != len(set(pyramid_ids)) or len(route_ids) != len(set(route_ids)):
            raise ValueError("pyramids and qualification routes must have unique IDs")
        source_leagues = [value for item in self.pyramids for value in item.source_competition_ids]
        target_leagues = [value for item in self.pyramids for value in item.destination_competition_ids]
        if len(source_leagues) != len(set(source_leagues)) or len(target_leagues) != len(set(target_leagues)):
            raise ValueError("a league edition cannot appear in multiple configured pyramids")
        if set(source_leagues) & destination_ids:
            raise ValueError("a current competition cannot also be a destination edition")
        referenced_destinations = set(target_leagues)
        for item in self.pyramids:
            if any(value not in destination_ids for value in item.destination_competition_ids):
                raise ValueError("pyramid destination has no registration calendar")
            if any(next(dest for dest in self.destinations if dest.competition_id == value).kind
                   is not CompetitionKind.LEAGUE for value in item.destination_competition_ids):
                raise ValueError("pyramid destinations must be league competitions")
        for route in self.qualification_routes:
            if route.destination_competition_id not in destination_ids:
                raise ValueError("qualification route destination has no registration calendar")
            if route.destination_competition_id in set(target_leagues):
                raise ValueError("qualification routes cannot bypass configured league movement")
            destination = next(item for item in self.destinations
                               if item.competition_id == route.destination_competition_id)
            expected_kind = (CompetitionKind.REPRESENTATIVE
                             if route.purpose is QualificationPurpose.NATIONAL_TOURNAMENT
                             else CompetitionKind.CUP)
            if destination.kind is not expected_kind:
                raise ValueError("qualification purpose does not match destination competition kind")
            referenced_destinations.add(route.destination_competition_id)
        if referenced_destinations != destination_ids:
            raise ValueError("every progression destination must have a configured source route")

    def to_json(self) -> str:
        return dumps(self)

    @classmethod
    def from_json(cls, value: str) -> SeasonProgressionPlan:
        try:
            return loads(value, cls)
        except (SerializationError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid season progression plan: {exc}") from exc


@dataclass(frozen=True)
class ProgressionStanding:
    participant_id: str
    position: int
    played: int
    won: int
    drawn: int
    lost: int
    goals_for: int
    goals_against: int
    points: int

    def __post_init__(self) -> None:
        validate_id(self.participant_id, kind="progression participant ID")
        if any(type(value) is not int or value < 0 for value in (
                self.position, self.played, self.won, self.drawn, self.lost,
                self.goals_for, self.goals_against, self.points)):
            raise ValueError("progression table values must be non-negative integers")
        if self.position < 1 or self.won + self.drawn + self.lost != self.played:
            raise ValueError("progression standing has an invalid position or match record")

    @property
    def goal_difference(self) -> int:
        return self.goals_for - self.goals_against


@dataclass(frozen=True)
class FixtureResultEvidence:
    fixture_id: str
    match_id: str
    scheduled_on: WorldDate
    result_completed_on: WorldDate
    completion_basis: ResultCompletionBasis
    input_sha256: str
    state_sha256: str
    home_participant_id: str
    away_participant_id: str
    home_goals: int
    away_goals: int

    def __post_init__(self) -> None:
        for label, value in (
            ("progression fixture ID", self.fixture_id),
            ("progression match ID", self.match_id),
            ("progression home participant", self.home_participant_id),
            ("progression away participant", self.away_participant_id),
        ):
            validate_id(value, kind=label)
        if not isinstance(self.scheduled_on, WorldDate):
            raise TypeError("fixture result evidence requires a world date")
        if not isinstance(self.result_completed_on, WorldDate):
            raise TypeError("fixture result evidence requires its completion date")
        if self.result_completed_on < self.scheduled_on:
            raise ValueError("archived match cannot complete before its scheduled date")
        if not isinstance(self.completion_basis, ResultCompletionBasis):
            raise TypeError("fixture result evidence requires its completion evidence basis")
        _validate_sha256(self.input_sha256, "fixture input hash")
        _validate_sha256(self.state_sha256, "fixture state hash")
        if self.home_participant_id == self.away_participant_id:
            raise ValueError("fixture result evidence requires two participants")
        if any(type(value) is not int or value < 0 for value in (self.home_goals, self.away_goals)):
            raise ValueError("fixture results must be non-negative integer goals")


@dataclass(frozen=True)
class CompetitionProgressionEvidence:
    """Table, match results, and completion chronology for one source edition."""

    competition_id: str
    kind: CompetitionKind
    scoring: LeagueTableScoring
    participant_ids: tuple[str, ...]
    final_match_on: WorldDate
    fixtures: tuple[FixtureResultEvidence, ...]
    standings: tuple[ProgressionStanding, ...]

    def __post_init__(self) -> None:
        validate_id(self.competition_id, kind="progression evidence competition ID")
        if not isinstance(self.kind, CompetitionKind):
            raise TypeError("progression evidence requires its source competition kind")
        if not isinstance(self.scoring, LeagueTableScoring):
            raise TypeError("progression evidence requires its table scoring snapshot")
        if not isinstance(self.participant_ids, tuple) or len(self.participant_ids) < 2:
            raise TypeError("progression evidence requires its immutable participant set")
        for participant_id in self.participant_ids:
            validate_id(participant_id, kind="progression source participant ID")
        if len(set(self.participant_ids)) != len(self.participant_ids):
            raise ValueError("progression evidence participant IDs cannot repeat")
        if not isinstance(self.final_match_on, WorldDate):
            raise TypeError("progression evidence requires a final match date")
        if (not isinstance(self.fixtures, tuple) or not self.fixtures
                or any(not isinstance(item, FixtureResultEvidence) for item in self.fixtures)):
            raise TypeError("progression evidence requires archived fixture results")
        if (not isinstance(self.standings, tuple) or len(self.standings) < 2
                or any(not isinstance(item, ProgressionStanding) for item in self.standings)):
            raise TypeError("progression evidence requires a complete standings table")
        if len({item.fixture_id for item in self.fixtures}) != len(self.fixtures):
            raise ValueError("progression evidence cannot repeat a fixture")
        if len({item.match_id for item in self.fixtures}) != len(self.fixtures):
            raise ValueError("progression evidence cannot repeat a match")
        if len({item.participant_id for item in self.standings}) != len(self.standings):
            raise ValueError("progression standings cannot repeat a participant")
        if tuple(item.position for item in self.standings) != tuple(range(1, len(self.standings) + 1)):
            raise ValueError("progression standings must have contiguous positions")
        if self.final_match_on != max(item.result_completed_on for item in self.fixtures):
            raise ValueError("progression final date does not match archived result completion dates")
        _validate_table_projection(
            self.competition_id, self.participant_ids, self.fixtures, self.standings, self.scoring,
        )

    @property
    def evidence_sha256(self) -> str:
        return hashlib.sha256(immutable_snapshot_json(self).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ProgressionDecision:
    decision_id: str
    kind: ProgressionKind
    participant_id: str
    source_competition_id: str
    source_position: int
    destination_competition_id: str
    source_evidence_sha256: str
    qualification_route_id: str | None = None
    qualification_purpose: QualificationPurpose | None = None

    def __post_init__(self) -> None:
        validate_id(self.decision_id, kind="progression decision ID")
        if not isinstance(self.kind, ProgressionKind):
            raise TypeError("progression decision requires a registered kind")
        for label, value in (
            ("progression participant ID", self.participant_id),
            ("progression source competition ID", self.source_competition_id),
            ("progression destination competition ID", self.destination_competition_id),
        ):
            validate_id(value, kind=label)
        if type(self.source_position) is not int or self.source_position < 1:
            raise ValueError("progression source position must be positive")
        _validate_sha256(self.source_evidence_sha256, "progression source evidence hash")
        if self.kind is ProgressionKind.QUALIFIED:
            if self.qualification_route_id is None or not isinstance(
                    self.qualification_purpose, QualificationPurpose):
                raise ValueError("qualification decision must retain its route and purpose")
            validate_id(self.qualification_route_id, kind="progression qualification route ID")
        elif self.qualification_route_id is not None or self.qualification_purpose is not None:
            raise ValueError("league movement decisions cannot contain a qualification route")


@dataclass(frozen=True)
class CompetitionEntrants:
    competition_id: str
    kind: CompetitionKind
    participant_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        validate_id(self.competition_id, kind="progression entrants competition ID")
        if not isinstance(self.kind, CompetitionKind):
            raise TypeError("progression entrants require a competition kind")
        if not isinstance(self.participant_ids, tuple) or len(self.participant_ids) < 2:
            raise ValueError("a next-edition competition requires at least two immutable participants")
        for participant_id in self.participant_ids:
            validate_id(participant_id, kind="progression entrant ID")
        if len(self.participant_ids) != len(set(self.participant_ids)):
            raise ValueError("next-edition participants cannot repeat")


@dataclass(frozen=True)
class SeasonProgressionResult:
    progression_id: str
    world_id: str
    source_season_id: str
    destination_season_id: str
    source_schedule_sha256: str
    plan_sha256: str
    progression_plan: SeasonProgressionPlan
    source_evidence: tuple[CompetitionProgressionEvidence, ...]
    decisions: tuple[ProgressionDecision, ...]
    entrants: tuple[CompetitionEntrants, ...]
    schema_version: int = PROGRESSION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for label, value in (
            ("progression ID", self.progression_id),
            ("progression world ID", self.world_id),
            ("source season ID", self.source_season_id),
            ("destination season ID", self.destination_season_id),
        ):
            validate_id(value, kind=label)
        if self.source_season_id == self.destination_season_id:
            raise ValueError("progression result must advance to a different season")
        _validate_sha256(self.source_schedule_sha256, "source schedule hash")
        _validate_sha256(self.plan_sha256, "progression plan hash")
        if not isinstance(self.progression_plan, SeasonProgressionPlan):
            raise TypeError("progression result requires its immutable source plan")
        if self.plan_sha256 != _plan_sha256(self.progression_plan):
            raise ValueError("progression result plan hash does not match its retained plan")
        if (self.world_id != self.progression_plan.world_id
                or self.source_season_id != self.progression_plan.source_season_id
                or self.destination_season_id != self.progression_plan.destination_season_id):
            raise ValueError("progression result identity does not match its retained plan")
        if type(self.schema_version) is not int or self.schema_version != PROGRESSION_SCHEMA_VERSION:
            raise ValueError("unsupported season progression result version")
        if (not isinstance(self.source_evidence, tuple)
                or any(not isinstance(item, CompetitionProgressionEvidence) for item in self.source_evidence)):
            raise TypeError("progression result source evidence must be immutable records")
        if (not isinstance(self.decisions, tuple) or not self.decisions
                or any(not isinstance(item, ProgressionDecision) for item in self.decisions)):
            raise TypeError("progression result requires immutable decisions")
        if (not isinstance(self.entrants, tuple) or not self.entrants
                or any(not isinstance(item, CompetitionEntrants) for item in self.entrants)):
            raise TypeError("progression result requires immutable destination entrants")
        if len({item.competition_id for item in self.source_evidence}) != len(self.source_evidence):
            raise ValueError("progression result cannot repeat source evidence")
        entrant_ids = [item.competition_id for item in self.entrants]
        if len(entrant_ids) != len(set(entrant_ids)):
            raise ValueError("progression result cannot repeat a destination")
        if len({item.decision_id for item in self.decisions}) != len(self.decisions):
            raise ValueError("progression result cannot repeat a decision")
        destination_participants = tuple(
            (item.destination_competition_id, item.participant_id)
            for item in self.decisions
        )
        if len(destination_participants) != len(set(destination_participants)):
            raise ValueError("progression result cannot repeat a participant in one destination")
        evidence_by_id = {item.competition_id: item for item in self.source_evidence}
        entrants_by_id = {item.competition_id: item for item in self.entrants}
        for decision in self.decisions:
            evidence = evidence_by_id.get(decision.source_competition_id)
            destination = entrants_by_id.get(decision.destination_competition_id)
            if evidence is None or evidence.evidence_sha256 != decision.source_evidence_sha256:
                raise ValueError("progression decision is missing its source result evidence")
            if destination is None or decision.participant_id not in destination.participant_ids:
                raise ValueError("progression decision does not appear in its destination entrants")
        for destination_id, destination in entrants_by_id.items():
            decision_participants = {
                item.participant_id for item in self.decisions
                if item.destination_competition_id == destination_id
            }
            if decision_participants != set(destination.participant_ids):
                raise ValueError("destination entrant list does not reconcile to progression decisions")
        if (tuple(item.competition_id for item in self.source_evidence)
                != tuple(sorted(item.competition_id for item in self.source_evidence))):
            raise ValueError("progression source evidence is not in canonical competition order")
        if (tuple(item.competition_id for item in self.entrants)
                != tuple(sorted(item.competition_id for item in self.entrants))):
            raise ValueError("progression destination entrants are not in canonical order")
        expected_decisions, expected_entrants = _progression_outputs(
            self.progression_plan, evidence_by_id,
        )
        if self.decisions != expected_decisions:
            raise ValueError("progression decisions do not derive from their retained plan and table positions")
        if self.entrants != expected_entrants:
            raise ValueError("progression entrants do not derive from their retained plan and source tables")
        expected_id = _progression_id(
            self.world_id, self.source_season_id, self.destination_season_id,
            self.source_schedule_sha256, self.plan_sha256,
        )
        if self.progression_id != expected_id:
            raise ValueError("progression result ID does not match its immutable inputs")

    @property
    def result_sha256(self) -> str:
        return hashlib.sha256(immutable_snapshot_json(self).encode("utf-8")).hexdigest()

    def to_json(self) -> str:
        return dumps(_ProgressionResultEnvelope(self, self.result_sha256))

    @classmethod
    def from_json(cls, value: str) -> SeasonProgressionResult:
        try:
            envelope = loads(value, _ProgressionResultEnvelope)
            if envelope.result.result_sha256 != envelope.result_sha256:
                raise ValueError("progression result checksum does not match its payload")
            return envelope.result
        except (SerializationError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid season progression result: {exc}") from exc


@dataclass(frozen=True)
class _ProgressionResultEnvelope:
    result: SeasonProgressionResult
    result_sha256: str


def resolve_season_progression(
    schedule: WorldSeasonSchedule,
    archive: WorldArchiveStore,
    plan: SeasonProgressionPlan,
) -> SeasonProgressionResult:
    """Resolve entrants from complete archive evidence for the source season."""
    if not isinstance(schedule, WorldSeasonSchedule):
        raise TypeError("season progression requires an immutable source schedule")
    if not isinstance(archive, WorldArchiveStore):
        raise TypeError("season progression requires an open world archive")
    if not isinstance(plan, SeasonProgressionPlan):
        raise TypeError("season progression requires an immutable transition plan")
    if (schedule.world_id != plan.world_id or schedule.season_id != plan.source_season_id):
        raise ValueError("progression plan does not match the source season")
    metrics = archive.metrics()
    if (metrics.world_id != schedule.world_id or metrics.season_id != schedule.season_id):
        raise ValueError("archive does not contain the requested source season")
    if metrics.archived_matches == 0:
        raise IncompleteCompetitionResults("source archive has no completed fixture evidence")
    # For an initialized archive this verifies the exact immutable competition
    # and fixture snapshots without changing them. An empty archive was rejected
    # above so progression inspection never creates schedule rows as a side effect.
    archive.initialize(schedule)

    source_ids = {
        value for pyramid in plan.pyramids for value in pyramid.source_competition_ids
    } | {route.source_competition_id for route in plan.qualification_routes}
    unknown = source_ids - {item.competition_id for item in schedule.competitions}
    if unknown:
        raise ValueError(f"progression plan references unknown source competitions: {sorted(unknown)}")
    evidence = {
        competition_id: _read_competition_evidence(schedule, archive, competition_id, plan.scoring)
        for competition_id in sorted(source_ids)
    }

    decisions, entrants = _progression_outputs(plan, evidence)
    source_schedule_sha256 = hashlib.sha256(
        immutable_snapshot_json(schedule).encode("utf-8")
    ).hexdigest()
    plan_sha256 = _plan_sha256(plan)
    return SeasonProgressionResult(
        _progression_id(schedule.world_id, schedule.season_id, plan.destination_season_id,
                        source_schedule_sha256, plan_sha256),
        schedule.world_id,
        schedule.season_id,
        plan.destination_season_id,
        source_schedule_sha256,
        plan_sha256,
        plan,
        tuple(evidence[key] for key in sorted(evidence)),
        decisions,
        entrants,
    )


def validate_next_season_schedule(
    result: SeasonProgressionResult,
    plan: SeasonProgressionPlan,
    schedule: WorldSeasonSchedule,
) -> None:
    """Require exact progressed entrant sets and a post-registration calendar."""
    if not isinstance(result, SeasonProgressionResult) or not isinstance(plan, SeasonProgressionPlan):
        raise TypeError("next-season validation requires a progression result and plan")
    if not isinstance(schedule, WorldSeasonSchedule):
        raise TypeError("next-season validation requires an immutable target schedule")
    if (result.plan_sha256 != _plan_sha256(plan)
            or result.world_id != plan.world_id
            or result.source_season_id != plan.source_season_id
            or result.destination_season_id != plan.destination_season_id
            or schedule.world_id != plan.world_id
            or schedule.season_id != plan.destination_season_id):
        raise ValueError("next-season schedule does not match the progression result")
    expected = {item.competition_id: item for item in result.entrants}
    actual = {item.competition_id: item for item in schedule.competitions}
    destinations = {item.competition_id: item for item in plan.destinations}
    if set(actual) != set(expected) or set(expected) != set(destinations):
        raise ValueError("next-season competition editions do not match progression destinations")
    fixtures_by_competition: dict[str, list] = {key: [] for key in expected}
    for fixture in schedule.fixtures:
        fixtures_by_competition[fixture.competition_id].append(fixture)
    for competition_id, entrants in expected.items():
        competition = actual[competition_id]
        destination = destinations[competition_id]
        if (competition.kind is not entrants.kind
                or set(competition.participant_ids) != set(entrants.participant_ids)):
            raise ValueError(f"next-season entrants do not reconcile for {competition_id}")
        fixtures = fixtures_by_competition[competition_id]
        if not fixtures:
            raise ValueError(f"next-season competition {competition_id} has no fixtures")
        if any(fixture.scheduled_on < destination.starts_on for fixture in fixtures):
            raise ValueError(f"next-season fixture precedes the configured start for {competition_id}")
        if any(fixture.scheduled_on <= destination.registration_closes_on for fixture in fixtures):
            raise ValueError(f"next-season fixture starts before registration closes for {competition_id}")


def _progression_outputs(
    plan: SeasonProgressionPlan,
    evidence: dict[str, CompetitionProgressionEvidence],
) -> tuple[tuple[ProgressionDecision, ...], tuple[CompetitionEntrants, ...]]:
    """Derive and validate decisions and entrants from a retained plan and tables."""
    required_sources = {
        value for pyramid in plan.pyramids for value in pyramid.source_competition_ids
    } | {route.source_competition_id for route in plan.qualification_routes}
    if set(evidence) != required_sources:
        raise ValueError("progression source evidence does not match the retained plan")
    if any(item.scoring != plan.scoring for item in evidence.values()):
        raise ValueError("progression source evidence uses different table scoring")

    entrant_rows: dict[str, dict[str, ProgressionDecision]] = {}
    for pyramid in plan.pyramids:
        _resolve_pyramid(pyramid, evidence, entrant_rows, plan)
    for route in plan.qualification_routes:
        _resolve_route(route, evidence, entrant_rows, plan)

    destinations = {item.competition_id: item for item in plan.destinations}
    entrants = []
    for competition_id in sorted(entrant_rows):
        destination = destinations[competition_id]
        participant_ids = tuple(sorted(entrant_rows[competition_id]))
        if not destination.minimum_entrants <= len(participant_ids) <= destination.maximum_entrants:
            raise ValueError(
                f"destination {competition_id} has {len(participant_ids)} entrants outside its configured limits"
            )
        relevant_evidence = {
            item.source_competition_id for item in entrant_rows[competition_id].values()
        }
        last_source_day = max(evidence[value].final_match_on for value in relevant_evidence)
        if not last_source_day < destination.registration_closes_on:
            raise RegistrationDeadlineMissed(
                f"source results for {competition_id} finish on {last_source_day.isoformat}, "
                f"not before registration closes on {destination.registration_closes_on.isoformat}"
            )
        entrants.append(CompetitionEntrants(
            competition_id, destination.kind, participant_ids,
        ))

    decisions = tuple(sorted(
        (decision for destination in entrant_rows.values() for decision in destination.values()),
        key=lambda item: (item.destination_competition_id, item.participant_id),
    ))
    return decisions, tuple(entrants)


def _resolve_pyramid(
    pyramid: PromotionPyramid,
    evidence: dict[str, CompetitionProgressionEvidence],
    entrant_rows: dict[str, dict[str, ProgressionDecision]],
    plan: SeasonProgressionPlan,
) -> None:
    destination_records = {item.competition_id: item for item in plan.destinations}
    current_participants: set[str] = set()
    assignments: list[dict[str, tuple[str, ProgressionStanding, ProgressionKind]]] = []
    for source_id, target_id in zip(
            pyramid.source_competition_ids, pyramid.destination_competition_ids):
        source = evidence[source_id]
        if source.kind is not CompetitionKind.LEAGUE:
            raise ValueError("promotion pyramids can only use domestic league tables")
        target = destination_records[target_id]
        if target.kind is not CompetitionKind.LEAGUE:
            raise ValueError("promotion pyramid target must be a league edition")
        assignments.append({
            item.participant_id: (source_id, item, ProgressionKind.RETAINED)
            for item in source.standings
        })
        overlap = current_participants & {item.participant_id for item in source.standings}
        if overlap:
            raise ValueError("one club cannot occupy two levels of a promotion pyramid")
        current_participants.update(item.participant_id for item in source.standings)

    for boundary, places in enumerate(pyramid.places_each_way):
        upper = evidence[pyramid.source_competition_ids[boundary]].standings
        lower = evidence[pyramid.source_competition_ids[boundary + 1]].standings
        if places >= len(upper) or places >= len(lower):
            raise ValueError("promotion/relegation places must leave at least one club in each division")
        if boundary > 0 and pyramid.places_each_way[boundary - 1] + places > len(upper):
            raise ValueError("promotion and relegation places overlap within a pyramid division")
        promoted = lower[:places]
        relegated = upper[-places:]
        self_assignments = assignments[boundary]
        lower_assignments = assignments[boundary + 1]
        for row in relegated:
            del self_assignments[row.participant_id]
            lower_assignments[row.participant_id] = (
                pyramid.source_competition_ids[boundary], row, ProgressionKind.RELEGATED,
            )
        for row in promoted:
            del lower_assignments[row.participant_id]
            self_assignments[row.participant_id] = (
                pyramid.source_competition_ids[boundary + 1], row, ProgressionKind.PROMOTED,
            )

    for destination_id, assignments_at_level in zip(
            pyramid.destination_competition_ids, assignments):
        for participant_id, (source_id, standing, kind) in assignments_at_level.items():
            _add_decision(
                entrant_rows, plan, evidence[source_id], participant_id, standing.position,
                destination_id, kind,
            )


def _resolve_route(
    route: QualificationRoute,
    evidence: dict[str, CompetitionProgressionEvidence],
    entrant_rows: dict[str, dict[str, ProgressionDecision]],
    plan: SeasonProgressionPlan,
) -> None:
    source = evidence[route.source_competition_id]
    if route.purpose is QualificationPurpose.NATIONAL_TOURNAMENT:
        if source.kind is not CompetitionKind.REPRESENTATIVE:
            raise ValueError("national tournament qualification must come from representative standings")
    elif source.kind is not CompetitionKind.LEAGUE:
        raise ValueError("club cup/continental qualification must come from a league table")
    by_position = {item.position: item for item in source.standings}
    for position in route.places:
        standing = by_position.get(position)
        if standing is None:
            raise ValueError(f"qualification route {route.route_id} selects missing position {position}")
        _add_decision(
            entrant_rows, plan, source, standing.participant_id, standing.position,
            route.destination_competition_id, ProgressionKind.QUALIFIED,
            qualification_route_id=route.route_id,
            qualification_purpose=route.purpose,
        )


def _add_decision(
    entrant_rows: dict[str, dict[str, ProgressionDecision]],
    plan: SeasonProgressionPlan,
    evidence: CompetitionProgressionEvidence,
    participant_id: str,
    source_position: int,
    destination_competition_id: str,
    kind: ProgressionKind,
    *,
    qualification_route_id: str | None = None,
    qualification_purpose: QualificationPurpose | None = None,
) -> None:
    destination_rows = entrant_rows.setdefault(destination_competition_id, {})
    if participant_id in destination_rows:
        raise ValueError(
            f"participant {participant_id} has multiple qualification paths into {destination_competition_id}"
        )
    decision_id = derive_id(
        "progression-decision", "p16c-competition-progression-v1",
        plan.world_id, plan.source_season_id, plan.destination_season_id,
        destination_competition_id, participant_id, kind.value,
        evidence.competition_id, source_position, evidence.evidence_sha256,
        qualification_route_id, qualification_purpose.value if qualification_purpose else None,
    )
    destination_rows[participant_id] = ProgressionDecision(
        decision_id, kind, participant_id, evidence.competition_id,
        source_position, destination_competition_id, evidence.evidence_sha256,
        qualification_route_id, qualification_purpose,
    )


def _read_competition_evidence(
    schedule: WorldSeasonSchedule,
    archive: WorldArchiveStore,
    competition_id: str,
    scoring: LeagueTableScoring,
) -> CompetitionProgressionEvidence:
    competition = schedule.competition(competition_id)
    if competition.kind not in (CompetitionKind.LEAGUE, CompetitionKind.REPRESENTATIVE):
        raise ValueError("season progression standings require a league or representative qualifier")
    fixtures = tuple(item for item in schedule.ordered_fixtures
                     if item.competition_id == competition_id)
    totals = {
        participant_id: [0, 0, 0, 0, 0, 0, 0]
        for participant_id in competition.participant_ids
    }
    fixture_evidence = []
    for fixture in fixtures:
        input_sha256 = fixture_input_sha256(fixture, competition)
        recorded = archive.recorded_fixture(
            fixture.fixture_id,
            expected_input_sha256=input_sha256,
            expected_match_id=str(fixture.match_id),
            expected_simulation_seed=fixture_seed(schedule, fixture),
        )
        if recorded is None:
            raise IncompleteCompetitionResults(
                f"competition {competition_id} is incomplete at fixture {fixture.fixture_id}"
            )
        summary = archive.match_summary(recorded[1])
        expected_summary = (
            str(fixture.match_id), fixture.fixture_id, competition_id,
            fixture.scheduled_on.isoformat,
            fixture.home_participant_id, fixture.away_participant_id,
        )
        actual_summary = (
            summary.get("match_id"), summary.get("fixture_id"), summary.get("competition_id"),
            summary.get("scheduled_on"), summary.get("home_participant_id"),
            summary.get("away_participant_id"),
        )
        if (actual_summary != expected_summary or recorded[0] != input_sha256):
            raise ValueError("archived result does not match its immutable scheduled fixture")
        home_goals, away_goals = summary.get("home_goals"), summary.get("away_goals")
        if any(type(value) is not int or value < 0 for value in (home_goals, away_goals)):
            raise ValueError("archived result contains invalid goals")
        result_completed_on, completion_basis = _result_completion_date(
            archive, recorded[1], fixture, competition, summary,
        )
        fixture_evidence.append(FixtureResultEvidence(
            fixture.fixture_id, str(fixture.match_id), fixture.scheduled_on,
            result_completed_on, completion_basis,
            input_sha256, summary["state_sha256"], fixture.home_participant_id,
            fixture.away_participant_id, home_goals, away_goals,
        ))
        home = totals[fixture.home_participant_id]
        away = totals[fixture.away_participant_id]
        home[0] += 1
        away[0] += 1
        home[4] += home_goals
        home[5] += away_goals
        away[4] += away_goals
        away[5] += home_goals
        if home_goals > away_goals:
            home[1] += 1
            away[3] += 1
            home[6] += scoring.win_points
            away[6] += scoring.loss_points
        elif home_goals < away_goals:
            away[1] += 1
            home[3] += 1
            away[6] += scoring.win_points
            home[6] += scoring.loss_points
        else:
            home[2] += 1
            away[2] += 1
            home[6] += scoring.draw_points
            away[6] += scoring.draw_points
    if len(fixtures) == 0:
        raise IncompleteCompetitionResults(f"competition {competition_id} has no scheduled fixtures")
    unsorted = [ProgressionStanding(
        participant_id, 1, values[0], values[1], values[2], values[3],
        values[4], values[5], values[6],
    ) for participant_id, values in totals.items()]
    ordered = sorted(
        unsorted,
        key=lambda item: (-item.points, -item.goal_difference, -item.goals_for),
    )
    for previous, current in zip(ordered, ordered[1:]):
        if (previous.points, previous.goal_difference, previous.goals_for) == (
                current.points, current.goal_difference, current.goals_for):
            raise UnresolvedTableTie(
                f"competition {competition_id} has an unresolved sporting tie between "
                f"{previous.participant_id} and {current.participant_id}; define a further tie-break or playoff"
            )
    standings = tuple(
        ProgressionStanding(
            item.participant_id, position, item.played, item.won, item.drawn, item.lost,
            item.goals_for, item.goals_against, item.points,
        ) for position, item in enumerate(ordered, start=1)
    )
    ordered_fixture_evidence = tuple(fixture_evidence)
    return CompetitionProgressionEvidence(
        competition_id,
        competition.kind,
        scoring,
        competition.participant_ids,
        max(item.result_completed_on for item in ordered_fixture_evidence),
        ordered_fixture_evidence,
        standings,
    )


def _result_completion_date(
    archive: WorldArchiveStore,
    match_id: str,
    fixture: WorldFixture,
    competition: WorldCompetition,
    summary: dict[str, object],
) -> tuple[WorldDate, ResultCompletionBasis]:
    """Use the archived match clock, or a conservative schedule-duration bound."""
    if summary.get("details_available") is True:
        match = archive.match_state(match_id)
        elapsed_ms = match.play.clock.elapsed_milliseconds
        if type(elapsed_ms) is not int or elapsed_ms < 0:
            raise ValueError("archived match has an invalid final match clock")
        ended_periods = tuple(
            event.payload.get("period") for event in match.events
            if event.kind == "period_ended"
        )
        interval_minutes = 0
        if "first_half" in ended_periods:
            interval_minutes += competition.half_time_break_minutes
        if "second_half" in ended_periods and "extra_time_first" in ended_periods:
            interval_minutes += competition.extra_time_interval_minutes
        if "extra_time_first" in ended_periods:
            interval_minutes += competition.extra_time_interval_minutes
        if any(event.kind == "shootout_started" for event in match.events):
            interval_minutes += competition.shootout_duration_minutes
        completed_at = fixture.kickoff_at + timedelta(
            milliseconds=elapsed_ms, minutes=interval_minutes,
        )
        return WorldDate(completed_at.date()), ResultCompletionBasis.MATCH_STATE

    rules = competition.rules
    maximum_ticks = 2 * (
        rules.half_duration_ticks
        + rules.stoppage_time_ticks
        + rules.extra_time_duration_ticks
        + rules.extra_time_stoppage_ticks
    )
    maximum_minutes = competition.half_time_break_minutes
    if rules.extra_time_duration_ticks > 0:
        maximum_minutes += 2 * competition.extra_time_interval_minutes
    if rules.shootout_kicks_per_team > 0:
        maximum_minutes += competition.shootout_duration_minutes
    latest_finish = fixture.kickoff_at + timedelta(
        milliseconds=maximum_ticks * rules.tick_duration_ms,
        minutes=maximum_minutes,
    )
    return WorldDate(latest_finish.date()), ResultCompletionBasis.MAXIMUM_SCHEDULED_DURATION


def _validate_table_projection(
    competition_id: str,
    participant_ids: tuple[str, ...],
    fixtures: tuple[FixtureResultEvidence, ...],
    standings: tuple[ProgressionStanding, ...],
    scoring: LeagueTableScoring,
) -> None:
    """Rebuild every table line from its retained fixture outcomes."""
    if set(participant_ids) != {item.participant_id for item in standings}:
        raise ValueError("progression standings do not cover the source participant set")
    totals = {participant_id: [0, 0, 0, 0, 0, 0, 0] for participant_id in participant_ids}
    for fixture in fixtures:
        if (fixture.home_participant_id not in totals
                or fixture.away_participant_id not in totals):
            raise ValueError("progression fixture references a non-participant")
        home = totals[fixture.home_participant_id]
        away = totals[fixture.away_participant_id]
        home[0] += 1
        away[0] += 1
        home[4] += fixture.home_goals
        home[5] += fixture.away_goals
        away[4] += fixture.away_goals
        away[5] += fixture.home_goals
        if fixture.home_goals > fixture.away_goals:
            home[1] += 1
            away[3] += 1
            home[6] += scoring.win_points
            away[6] += scoring.loss_points
        elif fixture.home_goals < fixture.away_goals:
            away[1] += 1
            home[3] += 1
            away[6] += scoring.win_points
            home[6] += scoring.loss_points
        else:
            home[2] += 1
            away[2] += 1
            home[6] += scoring.draw_points
            away[6] += scoring.draw_points
    ranked = sorted(
        (
            ProgressionStanding(
                participant_id, 1, values[0], values[1], values[2], values[3],
                values[4], values[5], values[6],
            )
            for participant_id, values in totals.items()
        ),
        key=lambda item: (-item.points, -item.goal_difference, -item.goals_for),
    )
    for previous, current in zip(ranked, ranked[1:]):
        if (previous.points, previous.goal_difference, previous.goals_for) == (
                current.points, current.goal_difference, current.goals_for):
            raise UnresolvedTableTie(
                f"competition {competition_id} has an unresolved sporting tie between "
                f"{previous.participant_id} and {current.participant_id}; define a further tie-break or playoff"
            )
    expected = tuple(
        ProgressionStanding(
            item.participant_id, position, item.played, item.won, item.drawn, item.lost,
            item.goals_for, item.goals_against, item.points,
        ) for position, item in enumerate(ranked, start=1)
    )
    if expected != standings:
        raise ValueError("progression standings do not reconcile to fixture outcomes")


def _plan_sha256(plan: SeasonProgressionPlan) -> str:
    return hashlib.sha256(immutable_snapshot_json(plan).encode("utf-8")).hexdigest()


def _progression_id(
    world_id: str,
    source_season_id: str,
    destination_season_id: str,
    source_schedule_sha256: str,
    plan_sha256: str,
) -> str:
    return derive_id(
        "season-progression", "p16c-competition-progression-v1",
        world_id, source_season_id, destination_season_id,
        source_schedule_sha256, plan_sha256,
    )


def _validate_sha256(value: str, label: str) -> None:
    if (not isinstance(value, str) or len(value) != 64
            or any(char not in "0123456789abcdef" for char in value)):
        raise ValueError(f"{label} must be a lowercase SHA-256 fingerprint")


__all__ = [
    "CompetitionEntrants", "CompetitionProgressionEvidence", "FixtureResultEvidence",
    "IncompleteCompetitionResults", "LeagueTableScoring", "ProgressionDecision",
    "ProgressionDestination", "ProgressionKind", "ProgressionStanding",
    "PromotionPyramid", "QualificationPurpose", "QualificationRoute",
    "ResultCompletionBasis",
    "RegistrationDeadlineMissed", "SeasonProgressionPlan", "SeasonProgressionResult",
    "UnresolvedTableTie", "resolve_season_progression", "validate_next_season_schedule",
]
