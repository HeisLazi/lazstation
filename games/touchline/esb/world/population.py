"""Dated player aging, retirement, intake and roster viability evidence (P16d-a).

This boundary consumes complete, authored player profiles. It does not invent
players, edit contracts or registrations, or schedule fixtures. Retirement
rates, individual propensity and intake ranks are explicit scenario inputs.
"""

from __future__ import annotations

import hashlib
import json
import math
from calendar import monthrange
from dataclasses import dataclass, fields, is_dataclass, replace
from datetime import date, datetime
from enum import Enum
from functools import lru_cache
import types
from typing import Union, get_args, get_origin, get_type_hints

from games.touchline.esb.ids import derive_id, validate_id
from games.touchline.esb.people import PlayerProfile, PrimaryRole, validate_profile
from games.touchline.esb.model import ProvenanceKind
from games.touchline.esb.randomness import RandomStream, RandomStreams
from games.touchline.esb.serialization import loads
from games.touchline.esb.time import WorldDate


def player_age(born_on: date, as_of: WorldDate) -> int:
    """Return completed years; a 29 February birthday falls on 28 February."""
    if isinstance(born_on, datetime) or not isinstance(born_on, date):
        raise TypeError("player birth date must be a calendar date")
    if not isinstance(as_of, WorldDate):
        raise TypeError("player age requires a WorldDate")
    if born_on > as_of.day:
        raise ValueError("player birth date cannot follow the age observation")
    anniversary_day = min(born_on.day, monthrange(as_of.day.year, born_on.month)[1])
    anniversary = date(as_of.day.year, born_on.month, anniversary_day)
    return as_of.day.year - born_on.year - (as_of.day < anniversary)


def _next_annual_boundary(current: WorldDate) -> WorldDate:
    year = current.day.year + 1
    day = min(current.day.day, monthrange(year, current.day.month)[1])
    return WorldDate(date(year, current.day.month, day))


class PopulationOrigin(str, Enum):
    INITIAL = "initial"
    ACADEMY = "academy"


class PopulationEventKind(str, Enum):
    RETIREMENT = "retirement"
    ACADEMY_INTAKE = "academy_intake"


class CandidateOutcome(str, Enum):
    ACCEPTED = "accepted"
    DEFERRED = "deferred"
    EXPIRED = "expired"


@dataclass(frozen=True)
class PopulationRandomCheckpoint:
    root_seed: int
    state: int
    draws: int
    stream_name: str = "population"
    algorithm: str = "splitmix64-v1"

    def __post_init__(self) -> None:
        if type(self.root_seed) is not int or not 0 <= self.root_seed < 2**63:
            raise ValueError("population random checkpoint seed is out of range")
        if type(self.state) is not int or not 0 <= self.state < 2**64:
            raise ValueError("population random checkpoint state is out of range")
        if type(self.draws) is not int or self.draws < 0:
            raise ValueError("population random draw count must be non-negative")
        if self.stream_name != "population" or self.algorithm != "splitmix64-v1":
            raise ValueError("unsupported population random stream identity")


@dataclass(frozen=True)
class RetirementHazard:
    age: int
    probability: float

    def __post_init__(self) -> None:
        if type(self.age) is not int or not 16 <= self.age <= 64:
            raise ValueError("retirement hazard age must be in [16, 64]")
        if (type(self.probability) not in (int, float)
                or not math.isfinite(self.probability)
                or not 0.0 <= self.probability <= 1.0):
            raise ValueError("retirement hazard probability must be in [0, 1]")


@dataclass(frozen=True)
class PopulationPolicy:
    """Explicit annual retirement curve and bounded club intake requirements."""

    retirement_hazards: tuple[RetirementHazard, ...]
    guaranteed_retirement_age: int
    minimum_intake_age: int
    maximum_intake_age: int
    minimum_squad_size: int
    minimum_role_counts: tuple[tuple[PrimaryRole, int], ...]
    maximum_intake_per_club: int
    maximum_pending_candidates_per_club: int = 32
    maximum_candidate_lifetime_days: int = 3650
    schema_version: int = 1

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("unsupported population policy version")
        if (not isinstance(self.retirement_hazards, tuple)
                or not self.retirement_hazards
                or any(not isinstance(item, RetirementHazard) for item in self.retirement_hazards)):
            raise TypeError("population policy requires an immutable retirement hazard curve")
        ages = tuple(item.age for item in self.retirement_hazards)
        if ages != tuple(sorted(set(ages))):
            raise ValueError("retirement hazard ages must be strictly increasing")
        if (type(self.guaranteed_retirement_age) is not int
                or not 40 <= self.guaranteed_retirement_age <= 70
                or ages[-1] >= self.guaranteed_retirement_age):
            raise ValueError("guaranteed retirement age must follow the hazard curve and be in [40, 70]")
        if (type(self.minimum_intake_age) is not int
                or type(self.maximum_intake_age) is not int
                or not 15 <= self.minimum_intake_age <= self.maximum_intake_age <= 30):
            raise ValueError("intake ages must be an ordered range within [15, 30]")
        if type(self.minimum_squad_size) is not int or self.minimum_squad_size < 0:
            raise ValueError("minimum squad size must be non-negative")
        if type(self.maximum_intake_per_club) is not int or self.maximum_intake_per_club < 0:
            raise ValueError("maximum intake per club must be non-negative")
        if (type(self.maximum_pending_candidates_per_club) is not int
                or self.maximum_pending_candidates_per_club < 0):
            raise ValueError("pending candidate cap must be non-negative")
        if (type(self.maximum_candidate_lifetime_days) is not int
                or not 1 <= self.maximum_candidate_lifetime_days <= 3650):
            raise ValueError("candidate lifetime must be in [1, 3650] days")
        if (not isinstance(self.minimum_role_counts, tuple)
                or any(not isinstance(item, tuple) or len(item) != 2
                       or not isinstance(item[0], PrimaryRole)
                       or type(item[1]) is not int or item[1] < 0
                       for item in self.minimum_role_counts)):
            raise TypeError("minimum role counts must be immutable role/count pairs")
        roles = tuple(item[0] for item in self.minimum_role_counts)
        if roles != tuple(sorted(set(roles), key=lambda role: role.value)):
            raise ValueError("minimum role counts must use unique alphabetically ordered roles")

    def base_retirement_hazard(self, age: int) -> float:
        if type(age) is not int or age < 0:
            raise ValueError("player age must be a non-negative integer")
        if age >= self.guaranteed_retirement_age:
            return 1.0
        applicable = [item for item in self.retirement_hazards if item.age <= age]
        return float(applicable[-1].probability) if applicable else 0.0


@dataclass(frozen=True)
class PlayerPopulationRecord:
    profile: PlayerProfile
    joined_on: WorldDate
    retirement_propensity: float = 1.0
    origin: PopulationOrigin = PopulationOrigin.INITIAL
    intake_candidate_id: str | None = None
    retired_on: WorldDate | None = None
    retirement_event_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.profile, PlayerProfile):
            raise TypeError("population records require a full PlayerProfile")
        _validate_match_ready_profile(self.profile)
        if self.profile.provenance.kind is not ProvenanceKind.AUTHORED:
            raise ValueError("initial population requires an authored player profile")
        if not isinstance(self.joined_on, WorldDate):
            raise TypeError("population membership requires a join date")
        born_on = self.profile.identity.birth_date
        if born_on is None or self.profile.identity.birth_date_provenance is None:
            raise ValueError("population players require a sourced birth date")
        if born_on > self.joined_on.day:
            raise ValueError("player cannot join before birth")
        if (self.profile.readiness.sampled_on > self.joined_on
                or (self.profile.readiness.provenance.evidence_date is not None
                    and self.profile.readiness.provenance.evidence_date
                    > self.profile.readiness.sampled_on)):
            raise ValueError("player profile readiness cannot use future evidence")
        if (type(self.retirement_propensity) not in (int, float)
                or not math.isfinite(self.retirement_propensity)
                or not 0.0 <= self.retirement_propensity <= 2.0):
            raise ValueError("retirement propensity must be explicit and in [0, 2]")
        if not isinstance(self.origin, PopulationOrigin):
            raise TypeError("population origin must be explicit")
        if self.origin is PopulationOrigin.INITIAL:
            if self.intake_candidate_id is not None:
                raise ValueError("initial population cannot cite an academy candidate")
        else:
            validate_id(self.intake_candidate_id, kind="population intake candidate ID")
        if (self.retired_on is None) != (self.retirement_event_id is None):
            raise ValueError("retirement date and event lineage must be present together")
        if self.retired_on is not None:
            if not isinstance(self.retired_on, WorldDate) or self.retired_on < self.joined_on:
                raise ValueError("retirement must follow player membership")
            validate_id(self.retirement_event_id, kind="population retirement event ID")

    @property
    def player_id(self) -> str:
        return str(self.profile.player_id)

    @property
    def club_id(self) -> str:
        return str(self.profile.club_id)

    @property
    def active(self) -> bool:
        return self.retired_on is None


@dataclass(frozen=True)
class IntakeCandidate:
    candidate_id: str
    profile: PlayerProfile
    available_on: WorldDate
    expires_on: WorldDate
    selection_rank: int
    retirement_propensity: float = 1.0

    def __post_init__(self) -> None:
        validate_id(self.candidate_id, kind="academy candidate ID")
        if not isinstance(self.profile, PlayerProfile):
            raise TypeError("academy intake requires a complete player profile")
        _validate_match_ready_profile(self.profile)
        if not isinstance(self.available_on, WorldDate) or not isinstance(self.expires_on, WorldDate):
            raise TypeError("academy availability requires explicit dates")
        if self.expires_on < self.available_on:
            raise ValueError("academy candidate expires before availability")
        if type(self.selection_rank) is not int or self.selection_rank <= 0:
            raise ValueError("academy candidate requires a positive explicit selection rank")
        if (type(self.retirement_propensity) not in (int, float)
                or not math.isfinite(self.retirement_propensity)
                or not 0.0 <= self.retirement_propensity <= 2.0):
            raise ValueError("candidate retirement propensity must be explicit and in [0, 2]")
        born_on = self.profile.identity.birth_date
        if born_on is None or self.profile.identity.birth_date_provenance is None:
            raise ValueError("academy candidates require a sourced birth date")
        if born_on > self.available_on.day:
            raise ValueError("academy candidate cannot be available before birth")
        if self.profile.provenance.kind is not ProvenanceKind.AUTHORED:
            raise ValueError("academy intake requires an authored candidate profile")
        if (self.profile.readiness.sampled_on > self.available_on
                or (self.profile.readiness.provenance.evidence_date is not None
                    and self.profile.readiness.provenance.evidence_date
                    > self.profile.readiness.sampled_on)):
            raise ValueError("candidate profile readiness cannot use future evidence")

    @property
    def player_id(self) -> str:
        return str(self.profile.player_id)

    @property
    def club_id(self) -> str:
        return str(self.profile.club_id)


@dataclass(frozen=True)
class RetirementDecision:
    player_id: str
    age: int
    base_hazard: float
    retirement_propensity: float
    probability: float
    draw: float
    retired: bool

    def __post_init__(self) -> None:
        validate_id(self.player_id, kind="retirement decision player ID")
        if type(self.age) is not int or self.age < 0:
            raise ValueError("retirement decision age must be non-negative")
        for label, value in (("base hazard", self.base_hazard),
                             ("retirement propensity", self.retirement_propensity),
                             ("probability", self.probability), ("draw", self.draw)):
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError(f"retirement {label} must be finite")
        if not 0.0 <= self.base_hazard <= 1.0:
            raise ValueError("retirement base hazard must be in [0, 1]")
        if not 0.0 <= self.retirement_propensity <= 2.0:
            raise ValueError("retirement propensity must be in [0, 2]")
        if not 0.0 <= self.probability <= 1.0 or not 0.0 <= self.draw < 1.0:
            raise ValueError("retirement probability and draw are out of range")
        if type(self.retired) is not bool or self.retired != (self.draw < self.probability):
            raise ValueError("retirement result must match its recorded probability and draw")


@dataclass(frozen=True)
class IntakeDecision:
    candidate_id: str
    player_id: str
    club_id: str
    born_on: date
    candidate_sha256: str
    selection_rank: int
    age: int
    outcome: CandidateOutcome
    reason: str

    def __post_init__(self) -> None:
        validate_id(self.candidate_id, kind="intake decision candidate ID")
        validate_id(self.player_id, kind="intake decision player ID")
        validate_id(self.club_id, kind="intake decision club ID")
        if isinstance(self.born_on, datetime) or not isinstance(self.born_on, date):
            raise TypeError("intake decision requires the candidate's calendar birth date")
        _validate_sha256(self.candidate_sha256, "intake candidate fingerprint")
        if type(self.selection_rank) is not int or self.selection_rank <= 0:
            raise ValueError("intake decision rank must be positive")
        if type(self.age) is not int or self.age < 0:
            raise ValueError("intake decision age must be non-negative")
        if not isinstance(self.outcome, CandidateOutcome):
            raise TypeError("intake decision requires a known outcome")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("intake decision requires a reason")


@dataclass(frozen=True)
class PopulationEvent:
    event_id: str
    world_id: str
    kind: PopulationEventKind
    player_id: str
    occurred_on: WorldDate
    age: int
    source_id: str
    source_sha256: str
    probability: float | None = None
    draw: float | None = None

    def __post_init__(self) -> None:
        for value, label in ((self.event_id, "population event ID"),
                             (self.world_id, "population world ID"),
                             (self.player_id, "population event player ID"),
                             (self.source_id, "population event source ID")):
            validate_id(value, kind=label)
        if not isinstance(self.kind, PopulationEventKind):
            raise TypeError("population event requires a known lifecycle kind")
        if not isinstance(self.occurred_on, WorldDate):
            raise TypeError("population event requires an explicit date")
        if type(self.age) is not int or self.age < 0:
            raise ValueError("population event age must be non-negative")
        _validate_sha256(self.source_sha256, "population event source fingerprint")
        if self.kind is PopulationEventKind.RETIREMENT:
            if (type(self.probability) not in (int, float)
                    or type(self.draw) not in (int, float)
                    or not 0.0 <= self.probability <= 1.0
                    or not 0.0 <= self.draw < 1.0
                    or self.draw >= self.probability):
                raise ValueError("retirement event requires a successful recorded probability draw")
        elif self.probability is not None or self.draw is not None:
            raise ValueError("academy intake event cannot contain a retirement draw")


@dataclass(frozen=True)
class ClubRosterCoverage:
    club_id: str
    active_player_count: int
    minimum_squad_size: int
    squad_shortfall: int
    role_counts: tuple[tuple[PrimaryRole, int], ...]
    role_shortfalls: tuple[tuple[PrimaryRole, int], ...]

    def __post_init__(self) -> None:
        validate_id(self.club_id, kind="roster coverage club ID")
        for label, value in (("active count", self.active_player_count),
                             ("minimum size", self.minimum_squad_size),
                             ("squad shortfall", self.squad_shortfall)):
            if type(value) is not int or value < 0:
                raise ValueError(f"roster {label} must be non-negative")
        if self.squad_shortfall != max(0, self.minimum_squad_size - self.active_player_count):
            raise ValueError("roster squad shortfall does not reconcile")
        for label, rows in (("role counts", self.role_counts),
                            ("role shortfalls", self.role_shortfalls)):
            if not isinstance(rows, tuple) or any(
                    not isinstance(item, tuple) or len(item) != 2
                    or not isinstance(item[0], PrimaryRole)
                    or type(item[1]) is not int or item[1] < 0 for item in rows):
                raise TypeError(f"{label} must be immutable role/count pairs")
            roles = tuple(item[0] for item in rows)
            if roles != tuple(sorted(set(roles), key=lambda role: role.value)):
                raise ValueError(f"{label} must have unique alphabetically ordered roles")


@dataclass(frozen=True)
class _PopulationBoundaryContent:
    boundary_id: str
    boundary_on: WorldDate
    policy: PopulationPolicy
    request_sha256: str
    source_population_sha256: str
    result_population_sha256: str
    retirement_decisions: tuple[RetirementDecision, ...]
    intake_decisions: tuple[IntakeDecision, ...]
    coverage: tuple[ClubRosterCoverage, ...]


@dataclass(frozen=True)
class PopulationBoundaryReceipt:
    boundary_id: str
    boundary_on: WorldDate
    policy: PopulationPolicy
    request_sha256: str
    source_population_sha256: str
    result_population_sha256: str
    retirement_decisions: tuple[RetirementDecision, ...]
    intake_decisions: tuple[IntakeDecision, ...]
    coverage: tuple[ClubRosterCoverage, ...]
    receipt_sha256: str

    def __post_init__(self) -> None:
        validate_id(self.boundary_id, kind="population boundary ID")
        if not isinstance(self.boundary_on, WorldDate):
            raise TypeError("population boundary requires an explicit date")
        if not isinstance(self.policy, PopulationPolicy):
            raise TypeError("population boundary must retain its applied policy")
        for label, value in (("request", self.request_sha256),
                             ("source population", self.source_population_sha256),
                             ("result population", self.result_population_sha256)):
            _validate_sha256(value, f"{label} fingerprint")
        _validate_sha256(self.receipt_sha256, "population receipt fingerprint")
        groups = (("retirement decisions", self.retirement_decisions, RetirementDecision),
                  ("intake decisions", self.intake_decisions, IntakeDecision),
                  ("roster coverage", self.coverage, ClubRosterCoverage))
        for label, values, expected in groups:
            if not isinstance(values, tuple) or any(not isinstance(item, expected) for item in values):
                raise TypeError(f"population {label} must be immutable {expected.__name__} records")
        retirement_ids = [item.player_id for item in self.retirement_decisions]
        if retirement_ids != sorted(set(retirement_ids)):
            raise ValueError("retirement decisions must be uniquely ordered by player ID")
        candidate_ids = [item.candidate_id for item in self.intake_decisions]
        if candidate_ids != sorted(set(candidate_ids)):
            raise ValueError("intake decisions must be uniquely ordered by candidate ID")
        club_ids = [item.club_id for item in self.coverage]
        if club_ids != sorted(set(club_ids)):
            raise ValueError("roster coverage must be uniquely ordered by club ID")
        if self.receipt_sha256 != _hash_record(_boundary_content(self)):
            raise ValueError("population boundary receipt does not match its sealed evidence")


def _boundary_content(receipt: PopulationBoundaryReceipt) -> _PopulationBoundaryContent:
    return _PopulationBoundaryContent(
        receipt.boundary_id,
        receipt.boundary_on,
        receipt.policy,
        receipt.request_sha256,
        receipt.source_population_sha256,
        receipt.result_population_sha256,
        receipt.retirement_decisions,
        receipt.intake_decisions,
        receipt.coverage,
    )


@dataclass(frozen=True)
class _PopulationProjection:
    world_id: str
    started_on: WorldDate
    as_of: WorldDate
    seed: int
    players: tuple[PlayerPopulationRecord, ...]
    pending_candidates: tuple[IntakeCandidate, ...]
    events: tuple[PopulationEvent, ...]
    population_random: PopulationRandomCheckpoint
    revision: int


@dataclass(frozen=True)
class _BoundaryRequest:
    boundary_on: WorldDate
    policy: PopulationPolicy
    candidates: tuple[IntakeCandidate, ...]


@dataclass(frozen=True)
class WorldPopulationState:
    world_id: str
    started_on: WorldDate
    as_of: WorldDate
    seed: int
    players: tuple[PlayerPopulationRecord, ...]
    pending_candidates: tuple[IntakeCandidate, ...]
    events: tuple[PopulationEvent, ...]
    transitions: tuple[PopulationBoundaryReceipt, ...]
    population_random: PopulationRandomCheckpoint
    revision: int = 0
    schema_version: int = 1

    def __post_init__(self) -> None:
        validate_id(self.world_id, kind="population world ID")
        if not isinstance(self.started_on, WorldDate) or not isinstance(self.as_of, WorldDate):
            raise TypeError("population state requires an explicit as-of date")
        if self.started_on > self.as_of:
            raise ValueError("population start date cannot follow its as-of date")
        if type(self.seed) is not int or not 0 <= self.seed < 2**63:
            raise ValueError("population seed must be a non-negative signed 64-bit integer")
        if type(self.revision) is not int or self.revision < 0:
            raise ValueError("population revision must be non-negative")
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("unsupported population state version")
        if (not isinstance(self.population_random, PopulationRandomCheckpoint)
                or self.population_random.root_seed != self.seed):
            raise ValueError("population state requires its seeded named population stream")
        if not isinstance(self.players, tuple) or not self.players or any(
                not isinstance(item, PlayerPopulationRecord) for item in self.players):
            raise TypeError("population state requires immutable player records")
        if not isinstance(self.pending_candidates, tuple) or any(
                not isinstance(item, IntakeCandidate) for item in self.pending_candidates):
            raise TypeError("population candidate pool must be immutable")
        if not isinstance(self.events, tuple) or any(
                not isinstance(item, PopulationEvent) for item in self.events):
            raise TypeError("population event history must be immutable")
        if not isinstance(self.transitions, tuple) or any(
                not isinstance(item, PopulationBoundaryReceipt) for item in self.transitions):
            raise TypeError("population transition history must be immutable")
        player_ids = [item.player_id for item in self.players]
        if player_ids != sorted(set(player_ids)):
            raise ValueError("population players must be uniquely ordered by player ID")
        candidate_ids = [item.candidate_id for item in self.pending_candidates]
        if candidate_ids != sorted(set(candidate_ids)):
            raise ValueError("pending candidates must be uniquely ordered by candidate ID")
        player_ids_set = set(player_ids)
        pending_player_ids = [item.player_id for item in self.pending_candidates]
        if (len(pending_player_ids) != len(set(pending_player_ids))
                or player_ids_set.intersection(pending_player_ids)):
            raise ValueError("population candidates cannot reuse an existing player ID")
        ranks: set[tuple[str, int]] = set()
        for candidate in self.pending_candidates:
            key = (candidate.club_id, candidate.selection_rank)
            if key in ranks:
                raise ValueError("pending candidate ranks must be unique within a club")
            ranks.add(key)
            if candidate.expires_on < self.as_of:
                raise ValueError("expired candidates must be removed at the annual boundary")
        for player in self.players:
            if player.joined_on > self.as_of or player.profile.identity.birth_date > self.as_of.day:
                raise ValueError("population membership cannot use future dates")
            if player.retired_on is not None and player.retired_on > self.as_of:
                raise ValueError("retirement cannot follow the population state date")
        event_order = [(item.occurred_on.day, item.event_id) for item in self.events]
        event_ids = [item.event_id for item in self.events]
        if event_order != sorted(event_order) or len(event_ids) != len(set(event_ids)):
            raise ValueError("population events must be unique and chronologically ordered")
        transitions = {item.boundary_id: item for item in self.transitions}
        if len(transitions) != len(self.transitions):
            raise ValueError("population boundary IDs must be unique")
        by_player = {item.player_id: item for item in self.players}
        event_by_id = {item.event_id: item for item in self.events}
        for event in self.events:
            player = by_player.get(event.player_id)
            if player is None or event.world_id != self.world_id or event.occurred_on > self.as_of:
                raise ValueError("population event must refer to a known player in this world")
            if event.age != player_age(player.profile.identity.birth_date, event.occurred_on):
                raise ValueError("population event age does not reconcile to its birth date")
            transition = next((item for item in self.transitions
                               if item.boundary_on == event.occurred_on), None)
            if transition is None:
                raise ValueError("population lifecycle event must cite a recorded annual boundary")
            if event.kind is PopulationEventKind.RETIREMENT:
                expected_id = derive_id(
                    "population-event", "p16d-retirement-v1", self.world_id,
                    event.player_id, event.occurred_on.isoformat,
                )
                decision = next((item for item in transition.retirement_decisions
                                 if item.player_id == event.player_id), None)
                if (event.event_id != expected_id or event.source_id != transition.boundary_id
                        or event.source_sha256 != transition.source_population_sha256
                        or decision is None or not decision.retired
                        or decision.age != event.age
                        or event.probability != decision.probability or event.draw != decision.draw
                        or player.retired_on != event.occurred_on
                        or player.retirement_event_id != event.event_id):
                    raise ValueError("retirement event does not reconcile to its decision receipt")
            else:
                decision = next((item for item in transition.intake_decisions
                                 if item.candidate_id == event.source_id), None)
                expected_id = derive_id(
                    "population-event", "p16d-academy-intake-v1", self.world_id,
                    event.source_id, event.player_id, event.occurred_on.isoformat,
                )
                if (event.event_id != expected_id or decision is None
                        or decision.outcome is not CandidateOutcome.ACCEPTED
                        or decision.player_id != event.player_id
                        or decision.candidate_sha256 != event.source_sha256
                        or player.origin is not PopulationOrigin.ACADEMY
                        or player.intake_candidate_id != event.source_id
                        or player.joined_on != event.occurred_on):
                    raise ValueError("academy intake event does not reconcile to its candidate receipt")
        for transition in self.transitions:
            for decision in transition.retirement_decisions:
                player = by_player.get(decision.player_id)
                if player is None or decision.retired != (
                        player.retired_on == transition.boundary_on):
                    raise ValueError("retirement decision does not reconcile to player status")
                expected_base = transition.policy.base_retirement_hazard(decision.age)
                expected_probability = (
                    1.0 if decision.age >= transition.policy.guaranteed_retirement_age
                    else min(1.0, expected_base * decision.retirement_propensity)
                )
                if (decision.base_hazard != expected_base
                        or decision.probability != expected_probability):
                    raise ValueError("retirement decision does not reconcile to its applied policy")
            accepted_by_club: dict[str, int] = {}
            for decision in transition.intake_decisions:
                matching = [event for event in self.events
                            if event.kind is PopulationEventKind.ACADEMY_INTAKE
                            and event.source_id == decision.candidate_id
                            and event.occurred_on == transition.boundary_on]
                if decision.outcome is CandidateOutcome.ACCEPTED:
                    if (len(matching) != 1 or matching[0].player_id != decision.player_id
                            or matching[0].source_sha256 != decision.candidate_sha256):
                        raise ValueError("accepted intake decision does not have one matching event")
                    if not (transition.policy.minimum_intake_age <= decision.age
                            <= transition.policy.maximum_intake_age):
                        raise ValueError("accepted intake age falls outside its applied policy")
                    player = by_player[decision.player_id]
                    accepted_by_club[player.club_id] = accepted_by_club.get(player.club_id, 0) + 1
                elif matching:
                    raise ValueError("deferred or expired candidate cannot have an intake event")
            if any(count > transition.policy.maximum_intake_per_club
                   for count in accepted_by_club.values()):
                raise ValueError("population transition exceeds its per-club intake cap")
            for row in transition.coverage:
                if row.minimum_squad_size != transition.policy.minimum_squad_size:
                    raise ValueError("roster coverage does not use its recorded policy")
                expected_roles = tuple(role for role, _count in transition.policy.minimum_role_counts)
                if (tuple(role for role, _count in row.role_counts) != expected_roles
                        or tuple(role for role, _count in row.role_shortfalls) != expected_roles):
                    raise ValueError("roster role coverage does not use its recorded policy")
                counts = dict(row.role_counts)
                shortfalls = dict(row.role_shortfalls)
                if any(shortfalls[role] != max(0, required - counts[role])
                       for role, required in transition.policy.minimum_role_counts):
                    raise ValueError("roster role shortfalls do not reconcile to the recorded policy")
        for player in self.players:
            if player.retired_on is not None:
                event = event_by_id.get(player.retirement_event_id)
                if (event is None or event.kind is not PopulationEventKind.RETIREMENT
                        or event.player_id != player.player_id or event.occurred_on != player.retired_on):
                    raise ValueError("retired player does not reconcile to one retirement event")
            elif player.retirement_event_id is not None:
                raise ValueError("active player cannot cite a retirement event")
            if player.origin is PopulationOrigin.ACADEMY:
                intake_events = [event for event in self.events
                                 if event.kind is PopulationEventKind.ACADEMY_INTAKE
                                 and event.player_id == player.player_id]
                if len(intake_events) != 1:
                    raise ValueError("academy player must retain exactly one intake event")
        transition_dates = [item.boundary_on for item in self.transitions]
        if transition_dates != sorted(set(transition_dates)):
            raise ValueError("population boundaries must be unique and chronological")
        candidate_history: dict[str, IntakeDecision] = {}
        for transition in self.transitions:
            for decision in transition.intake_decisions:
                previous = candidate_history.get(decision.candidate_id)
                if previous is not None:
                    if previous.outcome is not CandidateOutcome.DEFERRED:
                        raise ValueError("terminal intake candidate IDs cannot reappear in later boundaries")
                    identity = ("player_id", "club_id", "born_on", "candidate_sha256", "selection_rank")
                    if any(getattr(previous, field) != getattr(decision, field) for field in identity):
                        raise ValueError("deferred intake candidate identity changed across boundaries")
                candidate_history[decision.candidate_id] = decision
        if self.revision != len(self.transitions):
            raise ValueError("population revision must equal its committed boundary count")
        expected_date = self.started_on
        for transition in self.transitions:
            expected_date = _next_annual_boundary(expected_date)
            if transition.boundary_on != expected_date:
                raise ValueError("population transitions must follow every annual boundary")
        if expected_date != self.as_of:
            raise ValueError("population as-of date must match its annual boundary history")
        for previous, following in zip(self.transitions, self.transitions[1:]):
            if previous.result_population_sha256 != following.source_population_sha256:
                raise ValueError("population transition fingerprints do not form a continuous chain")
        for transition in self.transitions:
            expected_id = derive_id(
                "population-boundary", "p16d-population-boundary-v1",
                self.world_id, transition.boundary_on.isoformat,
            )
            if transition.boundary_id != expected_id:
                raise ValueError("population boundary ID does not match its date")
        if not self.transitions:
            initial_stream = RandomStreams.seeded(self.seed).stream("population")
            if (self.population_random.state != initial_stream.state
                    or self.population_random.draws != initial_stream.draws):
                raise ValueError("unadvanced population must retain the initial random checkpoint")
        replay_stream = RandomStreams.seeded(self.seed).stream("population")
        for transition in self.transitions:
            boundary = transition.boundary_on
            expected_active = tuple(sorted(
                (player for player in self.players
                 if player.joined_on < boundary
                 and (player.retired_on is None or player.retired_on >= boundary)),
                key=lambda player: player.player_id,
            ))
            decisions = transition.retirement_decisions
            if tuple(item.player_id for item in decisions) != tuple(
                    player.player_id for player in expected_active):
                raise ValueError("retirement receipt must include each player active before the boundary")
            for player, decision in zip(expected_active, decisions):
                age = player_age(player.profile.identity.birth_date, boundary)
                expected_base = transition.policy.base_retirement_hazard(age)
                expected_probability = (
                    1.0 if age >= transition.policy.guaranteed_retirement_age
                    else min(1.0, expected_base * float(player.retirement_propensity))
                )
                expected_draw = replay_stream.random()
                if (decision.age != age
                        or decision.retirement_propensity != float(player.retirement_propensity)
                        or decision.base_hazard != expected_base
                        or decision.probability != expected_probability
                        or decision.draw != expected_draw
                        or decision.retired != (expected_draw < expected_probability)
                        or decision.retired != (player.retired_on == boundary)):
                    raise ValueError("retirement decision does not reconcile to its player and random history")
            expected_coverage_clubs = {
                player.club_id for player in self.players if player.joined_on <= boundary
            }
            expected_coverage_clubs.update(
                decision.club_id for decision in transition.intake_decisions
                if decision.outcome is not CandidateOutcome.EXPIRED
            )
            if tuple(row.club_id for row in transition.coverage) != tuple(sorted(expected_coverage_clubs)):
                raise ValueError("roster coverage does not include exactly the clubs active in its boundary")
            active_at_boundary = tuple(
                player for player in self.players
                if player.joined_on <= boundary
                and (player.retired_on is None or player.retired_on > boundary)
            )
            by_coverage = {row.club_id: row for row in transition.coverage}
            for club_id in sorted(expected_coverage_clubs):
                active = tuple(player for player in active_at_boundary if player.club_id == club_id)
                row = by_coverage[club_id]
                expected_roles = tuple(role for role, _count in transition.policy.minimum_role_counts)
                expected_counts = tuple(
                    (role, sum(player.profile.primary_role is role for player in active))
                    for role in expected_roles
                )
                expected_shortfalls = tuple(
                    (role, max(0, required - count))
                    for (role, required), (_same_role, count)
                    in zip(transition.policy.minimum_role_counts, expected_counts)
                )
                if (row.active_player_count != len(active)
                        or row.minimum_squad_size != transition.policy.minimum_squad_size
                        or row.squad_shortfall != max(
                            0, transition.policy.minimum_squad_size - len(active))
                        or row.role_counts != expected_counts
                        or row.role_shortfalls != expected_shortfalls):
                    raise ValueError("roster coverage does not reconcile to historical player membership")
            expected_decision_candidates = tuple(
                item.candidate_id for item in transition.intake_decisions
            )
            if expected_decision_candidates != tuple(sorted(set(expected_decision_candidates))):
                raise ValueError("intake decisions must be uniquely ordered by candidate ID")
            for decision in transition.intake_decisions:
                if decision.age != player_age(decision.born_on, boundary):
                    raise ValueError("intake decision age does not reconcile to its recorded birth date")
                if decision.outcome is CandidateOutcome.ACCEPTED:
                    player = by_player.get(decision.player_id)
                    if (player is None or player.club_id != decision.club_id
                            or player.profile.identity.birth_date != decision.born_on
                            or player.joined_on != boundary):
                        raise ValueError("accepted intake decision does not reconcile to the player record")
        if (self.population_random.state != replay_stream.state
                or self.population_random.draws != replay_stream.draws):
            raise ValueError("population random checkpoint does not reconcile to boundary decisions")
        if self.transitions:
            latest = self.transitions[-1]
            if latest.boundary_on != self.as_of:
                raise ValueError("latest population boundary must match the state date")
            if latest.result_population_sha256 != _population_sha256(self):
                raise ValueError("population state does not match its last transition receipt")

    def to_json(self) -> str:
        return _canonical_record_json(self)

    @classmethod
    def from_json(cls, value: str) -> WorldPopulationState:
        return loads(value, cls)


def _validate_sha256(value: str, label: str) -> None:
    if (not isinstance(value, str) or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")


def _validate_match_ready_profile(profile: PlayerProfile) -> None:
    issues = validate_profile(profile)
    if issues:
        summary = "; ".join(f"{item.code}: {item.message}" for item in issues)
        raise ValueError(f"population requires a match-ready player profile: {summary}")


def _hash_record(record: object) -> str:
    return hashlib.sha256(_canonical_record_json(record).encode("utf-8")).hexdigest()


@lru_cache(maxsize=None)
def _record_type_hints(record_type: type) -> dict[str, object]:
    return get_type_hints(record_type)


def _canonical_data(value, expected=None):
    if value is None:
        return None
    if expected is not None and hasattr(expected, "__supertype__"):
        expected = expected.__supertype__
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        raise TypeError("datetime values are not valid population evidence")
    if isinstance(value, date):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        hints = _record_type_hints(type(value))
        return {
            item.name: _canonical_data(getattr(value, item.name), hints.get(item.name))
            for item in fields(value)
        }
    origin = get_origin(expected)
    args = get_args(expected)
    if origin in (Union, types.UnionType):
        expected = next((item for item in args if item is not type(None)), None)
        origin = get_origin(expected)
        args = get_args(expected)
    if origin is tuple or isinstance(value, tuple):
        if len(args) == 2 and args[1] is Ellipsis:
            return [_canonical_data(item, args[0]) for item in value]
        if args:
            return [_canonical_data(item, kind) for item, kind in zip(value, args)]
        return [_canonical_data(item) for item in value]
    if origin is dict or isinstance(value, dict):
        value_type = args[1] if len(args) == 2 else None
        if any(not isinstance(key, str) for key in value):
            raise TypeError("population record dictionary keys must be strings")
        return {key: _canonical_data(value[key], value_type) for key in sorted(value)}
    if expected is float and type(value) in (int, float):
        return float(value)
    if type(value) in (str, bool, int, float):
        if type(value) is float and not math.isfinite(value):
            raise ValueError("population record floats must be finite")
        return value
    raise TypeError(f"unsupported population record value: {type(value).__name__}")


def _canonical_record_json(record: object) -> str:
    if not is_dataclass(record) or isinstance(record, type):
        raise TypeError("population record fingerprint requires a dataclass")
    envelope = {
        "format": "esb.core-record",
        "schema_version": 1,
        "record_type": f"{type(record).__module__}.{type(record).__qualname__}",
        "payload": _canonical_data(record, type(record)),
    }
    return json.dumps(envelope, ensure_ascii=False, allow_nan=False, sort_keys=True,
                      separators=(",", ":"))


def _population_projection(state: WorldPopulationState) -> _PopulationProjection:
    return _PopulationProjection(
        state.world_id, state.started_on, state.as_of, state.seed, state.players,
        state.pending_candidates, state.events, state.population_random, state.revision,
    )


def _population_hash_values(
    world_id: str,
    started_on: WorldDate,
    as_of: WorldDate,
    seed: int,
    players: tuple[PlayerPopulationRecord, ...],
    candidates: tuple[IntakeCandidate, ...],
    events: tuple[PopulationEvent, ...],
    population_random: PopulationRandomCheckpoint,
    revision: int,
) -> str:
    return _hash_record(_PopulationProjection(
        world_id, started_on, as_of, seed, players, candidates, events,
        population_random, revision,
    ))


def _population_sha256(state: WorldPopulationState) -> str:
    return _hash_record(_population_projection(state))


def create_population_state(
    world_id: str,
    *,
    as_of: WorldDate,
    seed: int,
    players: tuple[PlayerPopulationRecord, ...],
    candidates: tuple[IntakeCandidate, ...] = (),
) -> WorldPopulationState:
    """Create a dated population; all player facts are supplied by the caller."""
    if not isinstance(as_of, WorldDate):
        raise TypeError("population initialization requires a WorldDate")
    if not isinstance(players, tuple) or any(not isinstance(item, PlayerPopulationRecord) for item in players):
        raise TypeError("population initialization requires immutable player records")
    if not isinstance(candidates, tuple) or any(not isinstance(item, IntakeCandidate) for item in candidates):
        raise TypeError("population initialization candidates must be immutable")
    stream = RandomStreams.seeded(seed).stream("population")
    return WorldPopulationState(
        world_id=world_id,
        started_on=as_of,
        as_of=as_of,
        seed=seed,
        players=tuple(sorted(players, key=lambda item: item.player_id)),
        pending_candidates=tuple(sorted(candidates, key=lambda item: item.candidate_id)),
        events=(),
        transitions=(),
        population_random=PopulationRandomCheckpoint(seed, stream.state, stream.draws),
    )


def _candidate_fingerprint(candidate: IntakeCandidate) -> str:
    return _hash_record(candidate)


def _intake_decision(
    candidate: IntakeCandidate,
    age: int,
    outcome: CandidateOutcome,
    reason: str,
) -> IntakeDecision:
    return IntakeDecision(
        candidate_id=candidate.candidate_id,
        player_id=candidate.player_id,
        club_id=candidate.club_id,
        born_on=candidate.profile.identity.birth_date,
        candidate_sha256=_candidate_fingerprint(candidate),
        selection_rank=candidate.selection_rank,
        age=age,
        outcome=outcome,
        reason=reason,
    )


def _validate_new_candidates(
    state: WorldPopulationState,
    candidates: tuple[IntakeCandidate, ...],
    boundary_on: WorldDate,
) -> tuple[IntakeCandidate, ...]:
    existing_by_id = {item.candidate_id: item for item in state.pending_candidates}
    consumed_ids = {item.source_id for item in state.events
                    if item.kind is PopulationEventKind.ACADEMY_INTAKE}
    recorded_ids = {
        decision.candidate_id
        for transition in state.transitions
        for decision in transition.intake_decisions
    }
    known_players = {item.player_id for item in state.players}
    known_players.update(item.player_id for item in state.pending_candidates)
    accepted_new: dict[str, IntakeCandidate] = {}
    submitted_ids: set[str] = set()
    for candidate in candidates:
        if candidate.candidate_id in submitted_ids:
            raise ValueError("candidate ID is repeated in the intake request")
        submitted_ids.add(candidate.candidate_id)
        if candidate.expires_on < boundary_on:
            raise ValueError("new intake candidate is already expired at this boundary")
        if candidate.available_on < state.as_of:
            raise ValueError("new intake candidate availability cannot be backdated")
        if candidate.candidate_id in consumed_ids:
            raise ValueError("intake candidate was already consumed")
        existing = existing_by_id.get(candidate.candidate_id)
        if existing is not None:
            if existing != candidate:
                raise ValueError("candidate ID was reused with different authored evidence")
            continue
        if candidate.candidate_id in recorded_ids:
            raise ValueError("intake candidate ID was already recorded in population history")
        if candidate.player_id in known_players:
            raise ValueError("candidate player ID already exists in population history")
        if candidate.player_id in {item.player_id for item in accepted_new.values()}:
            raise ValueError("candidate player ID cannot have multiple intake records")
        accepted_new[candidate.candidate_id] = candidate
    merged = tuple(sorted(
        (*state.pending_candidates, *accepted_new.values()),
        key=lambda item: item.candidate_id,
    ))
    ranks: set[tuple[str, int]] = set()
    for candidate in merged:
        key = (candidate.club_id, candidate.selection_rank)
        if key in ranks:
            raise ValueError("candidate selection ranks must be unique within a club")
        ranks.add(key)
    return merged


def _coverage(
    players: tuple[PlayerPopulationRecord, ...],
    candidates: tuple[IntakeCandidate, ...],
    policy: PopulationPolicy,
) -> tuple[ClubRosterCoverage, ...]:
    clubs = {item.club_id for item in players}
    clubs.update(item.club_id for item in candidates)
    result = []
    for club_id in sorted(clubs):
        active = tuple(item for item in players if item.active and item.club_id == club_id)
        counts = {role: sum(item.profile.primary_role is role for item in active)
                  for role, _minimum in policy.minimum_role_counts}
        role_counts = tuple((role, counts[role]) for role, _minimum in policy.minimum_role_counts)
        role_shortfalls = tuple(
            (role, max(0, required - counts[role]))
            for role, required in policy.minimum_role_counts
        )
        result.append(ClubRosterCoverage(
            club_id, len(active), policy.minimum_squad_size,
            max(0, policy.minimum_squad_size - len(active)),
            role_counts, role_shortfalls,
        ))
    return tuple(result)


def advance_population(
    state: WorldPopulationState,
    boundary_on: WorldDate,
    *,
    policy: PopulationPolicy,
    new_candidates: tuple[IntakeCandidate, ...] = (),
) -> WorldPopulationState:
    """Advance one annual boundary; exact retries do not consume extra draws."""
    if not isinstance(state, WorldPopulationState) or not isinstance(policy, PopulationPolicy):
        raise TypeError("population advancement requires state and explicit policy")
    if not isinstance(boundary_on, WorldDate):
        raise TypeError("population advancement requires an explicit WorldDate")
    if (not isinstance(new_candidates, tuple)
            or any(not isinstance(item, IntakeCandidate) for item in new_candidates)):
        raise TypeError("new candidates must be supplied as an immutable IntakeCandidate tuple")
    canonical_new = tuple(sorted(new_candidates, key=lambda item: item.candidate_id))
    request_hash = _hash_record(_BoundaryRequest(boundary_on, policy, canonical_new))
    if boundary_on == state.as_of and state.transitions:
        prior = state.transitions[-1]
        if prior.boundary_on == boundary_on and prior.request_sha256 == request_hash:
            if prior.result_population_sha256 != _population_sha256(state):
                raise ValueError("population state changed after its committed boundary")
            return state
        raise ValueError("same-date population retry conflicts with its recorded request")
    expected = _next_annual_boundary(state.as_of)
    if boundary_on != expected:
        raise ValueError(f"population boundary must be the next annual anniversary ({expected.isoformat})")

    merged_candidates = _validate_new_candidates(state, canonical_new, boundary_on)
    pending_by_club: dict[str, int] = {}
    for candidate in merged_candidates:
        if ((candidate.expires_on.day - candidate.available_on.day).days
                > policy.maximum_candidate_lifetime_days):
            raise ValueError("candidate expiry exceeds the policy lifetime")
        age = player_age(candidate.profile.identity.birth_date, boundary_on)
        if candidate.expires_on >= boundary_on and age <= policy.maximum_intake_age:
            pending_by_club[candidate.club_id] = pending_by_club.get(candidate.club_id, 0) + 1
    if any(count > policy.maximum_pending_candidates_per_club
           for count in pending_by_club.values()):
        raise ValueError("pending candidate pool exceeds its per-club policy cap")
    source_sha = _population_sha256(state)
    population_stream = RandomStream(
        "population", state.population_random.state, state.population_random.draws,
    )
    retirement_decisions: list[RetirementDecision] = []
    events = list(state.events)
    next_players: list[PlayerPopulationRecord] = []
    boundary_id = derive_id(
        "population-boundary", "p16d-population-boundary-v1",
        state.world_id, boundary_on.isoformat,
    )

    for player in state.players:
        if not player.active:
            next_players.append(player)
            continue
        age = player_age(player.profile.identity.birth_date, boundary_on)
        base_hazard = policy.base_retirement_hazard(age)
        probability = (1.0 if age >= policy.guaranteed_retirement_age
                       else min(1.0, base_hazard * float(player.retirement_propensity)))
        draw = population_stream.random()
        retired = draw < probability
        retirement_decisions.append(RetirementDecision(
            player.player_id, age, base_hazard,
            float(player.retirement_propensity), probability, draw, retired,
        ))
        if retired:
            event_id = derive_id(
                "population-event", "p16d-retirement-v1",
                state.world_id, player.player_id, boundary_on.isoformat,
            )
            events.append(PopulationEvent(
                event_id, state.world_id, PopulationEventKind.RETIREMENT,
                player.player_id, boundary_on, age, boundary_id, source_sha,
                probability, draw,
            ))
            next_players.append(replace(
                player, retired_on=boundary_on, retirement_event_id=event_id,
            ))
        else:
            next_players.append(player)

    intake_decisions: dict[str, IntakeDecision] = {}
    eligible_by_club: dict[str, list[IntakeCandidate]] = {}
    retained_candidates: dict[str, IntakeCandidate] = {}
    for candidate in merged_candidates:
        age = player_age(candidate.profile.identity.birth_date, boundary_on)
        if candidate.expires_on < boundary_on:
            intake_decisions[candidate.candidate_id] = _intake_decision(
                candidate, age, CandidateOutcome.EXPIRED, "candidate_expired",
            )
            continue
        if age > policy.maximum_intake_age:
            intake_decisions[candidate.candidate_id] = _intake_decision(
                candidate, age, CandidateOutcome.EXPIRED, "over_intake_age_limit",
            )
            continue
        retained_candidates[candidate.candidate_id] = candidate
        if candidate.available_on > boundary_on:
            reason = "not_yet_available"
        elif age < policy.minimum_intake_age:
            reason = "below_intake_age_minimum"
        else:
            eligible_by_club.setdefault(candidate.club_id, []).append(candidate)
            continue
        intake_decisions[candidate.candidate_id] = _intake_decision(
            candidate, age, CandidateOutcome.DEFERRED, reason,
        )

    intake_count: dict[str, int] = {}
    selected_reason: dict[str, str] = {}
    selected: dict[str, IntakeCandidate] = {}
    active_counts: dict[str, int] = {}
    role_counts: dict[tuple[str, PrimaryRole], int] = {}
    for player in next_players:
        if player.active:
            active_counts[player.club_id] = active_counts.get(player.club_id, 0) + 1
            key = (player.club_id, player.profile.primary_role)
            role_counts[key] = role_counts.get(key, 0) + 1

    for club_id in sorted(eligible_by_club):
        ranked = sorted(eligible_by_club[club_id], key=lambda item: item.selection_rank)
        chosen_for_club: set[str] = set()
        for role, required in policy.minimum_role_counts:
            deficit = max(0, required - role_counts.get((club_id, role), 0))
            for candidate in ranked:
                if deficit <= 0 or intake_count.get(club_id, 0) >= policy.maximum_intake_per_club:
                    break
                if candidate.profile.primary_role is role:
                    chosen_for_club.add(candidate.candidate_id)
                    selected[candidate.candidate_id] = candidate
                    selected_reason[candidate.candidate_id] = "fills_role_minimum"
                    intake_count[club_id] = intake_count.get(club_id, 0) + 1
                    role_counts[(club_id, role)] = role_counts.get((club_id, role), 0) + 1
                    active_counts[club_id] = active_counts.get(club_id, 0) + 1
                    deficit -= 1
        total_deficit = max(0, policy.minimum_squad_size - active_counts.get(club_id, 0))
        for candidate in ranked:
            if total_deficit <= 0 or intake_count.get(club_id, 0) >= policy.maximum_intake_per_club:
                break
            if candidate.candidate_id in chosen_for_club:
                continue
            chosen_for_club.add(candidate.candidate_id)
            selected[candidate.candidate_id] = candidate
            selected_reason[candidate.candidate_id] = "fills_squad_minimum"
            intake_count[club_id] = intake_count.get(club_id, 0) + 1
            active_counts[club_id] = active_counts.get(club_id, 0) + 1
            role_key = (club_id, candidate.profile.primary_role)
            role_counts[role_key] = role_counts.get(role_key, 0) + 1
            total_deficit -= 1

    for candidate_id, candidate in sorted(selected.items()):
        age = player_age(candidate.profile.identity.birth_date, boundary_on)
        event_id = derive_id(
            "population-event", "p16d-academy-intake-v1",
            state.world_id, candidate.candidate_id, candidate.player_id,
            boundary_on.isoformat,
        )
        events.append(PopulationEvent(
            event_id, state.world_id, PopulationEventKind.ACADEMY_INTAKE,
            candidate.player_id, boundary_on, age, candidate.candidate_id,
            _candidate_fingerprint(candidate),
        ))
        next_players.append(PlayerPopulationRecord(
            candidate.profile, boundary_on, candidate.retirement_propensity,
            PopulationOrigin.ACADEMY, candidate.candidate_id,
        ))
        intake_decisions[candidate_id] = _intake_decision(
            candidate, age, CandidateOutcome.ACCEPTED, selected_reason[candidate_id],
        )

    final_candidates = tuple(sorted(
        (candidate for candidate_id, candidate in retained_candidates.items()
         if candidate_id not in selected),
        key=lambda item: item.candidate_id,
    ))
    for candidate in final_candidates:
        if candidate.candidate_id not in intake_decisions:
            age = player_age(candidate.profile.identity.birth_date, boundary_on)
            reason = ("annual_intake_cap" if intake_count.get(candidate.club_id, 0)
                      >= policy.maximum_intake_per_club else "no_roster_need")
            intake_decisions[candidate.candidate_id] = _intake_decision(
                candidate, age, CandidateOutcome.DEFERRED, reason,
            )

    final_players = tuple(sorted(next_players, key=lambda item: item.player_id))
    final_events = tuple(sorted(events, key=lambda item: (item.occurred_on.day, item.event_id)))
    retirement_rows = tuple(sorted(retirement_decisions, key=lambda item: item.player_id))
    intake_rows = tuple(sorted(intake_decisions.values(), key=lambda item: item.candidate_id))
    coverage = _coverage(final_players, final_candidates, policy)
    random_checkpoint = PopulationRandomCheckpoint(
        state.seed, population_stream.state, population_stream.draws,
    )
    result_sha = _population_hash_values(
        state.world_id, state.started_on, boundary_on, state.seed, final_players,
        final_candidates, final_events, random_checkpoint, state.revision + 1,
    )
    receipt_content = _PopulationBoundaryContent(
        boundary_id, boundary_on, policy, request_hash, source_sha, result_sha,
        retirement_rows, intake_rows, coverage,
    )
    receipt = PopulationBoundaryReceipt(
        boundary_id, boundary_on, policy, request_hash, source_sha,
        result_sha, retirement_rows, intake_rows, coverage, _hash_record(receipt_content),
    )
    return WorldPopulationState(
        world_id=state.world_id,
        started_on=state.started_on,
        as_of=boundary_on,
        seed=state.seed,
        players=final_players,
        pending_candidates=final_candidates,
        events=final_events,
        transitions=state.transitions + (receipt,),
        population_random=random_checkpoint,
        revision=state.revision + 1,
    )


__all__ = [
    "CandidateOutcome", "ClubRosterCoverage", "IntakeCandidate", "IntakeDecision",
    "PlayerPopulationRecord", "PopulationBoundaryReceipt", "PopulationEvent",
    "PopulationEventKind", "PopulationOrigin", "PopulationPolicy",
    "PopulationRandomCheckpoint", "RetirementDecision", "RetirementHazard",
    "WorldPopulationState",
    "advance_population", "create_population_state", "player_age",
]
