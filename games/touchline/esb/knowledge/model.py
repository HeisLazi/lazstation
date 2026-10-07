"""Versionable records for permissioned, club-local football knowledge."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from enum import Enum

from games.touchline.esb.ids import ClubId, EventId, MatchId, validate_id
from games.touchline.esb.model import DataProvenance, ProvenanceKind
from games.touchline.esb.time import WorldDate


OBSERVATION_FIELDS = frozenset({"goal_event", "pass_completion", "tracked_position"})


class CoverageLevel(str, Enum):
    RESULTS = "results"
    EVENTS = "events"
    TRACKING = "tracking"

    @property
    def rank(self) -> int:
        return {CoverageLevel.RESULTS: 0, CoverageLevel.EVENTS: 1,
                CoverageLevel.TRACKING: 2}[self]


class StaffRole(str, Enum):
    OBSERVER = "observer"
    ANALYST = "analyst"


@dataclass(frozen=True)
class CoverageGrant:
    """One club's dated permission to collect named fields from one match."""

    grant_id: str
    club_id: ClubId
    match_id: MatchId
    match_date: WorldDate
    starts_on: WorldDate
    expires_on: WorldDate
    level: CoverageLevel
    permitted_fields: tuple[str, ...]
    permitted_event_kinds: tuple[str, ...]
    method: str
    minimum_work_units: int

    def __post_init__(self) -> None:
        validate_id(self.grant_id, kind="coverage grant ID")
        validate_id(self.club_id, kind="coverage club ID")
        validate_id(self.match_id, kind="coverage match ID")
        if (not isinstance(self.match_date, WorldDate) or not isinstance(self.starts_on, WorldDate)
                or not isinstance(self.expires_on, WorldDate)):
            raise TypeError("coverage grant requires an evidence date and explicit validity dates")
        if self.starts_on < self.match_date:
            raise ValueError("coverage access cannot start before the match evidence exists")
        if self.expires_on < self.starts_on:
            raise ValueError("coverage grant expiry must not precede its start")
        if not isinstance(self.level, CoverageLevel):
            raise TypeError("coverage level must be explicit")
        for label, values in (("fields", self.permitted_fields),
                              ("event kinds", self.permitted_event_kinds)):
            if not isinstance(values, tuple) or any(
                not isinstance(value, str) or not value.strip() for value in values
            ):
                raise TypeError(f"coverage {label} must be a tuple of non-empty strings")
            if len(values) != len(set(values)):
                raise ValueError(f"coverage {label} cannot contain duplicates")
        unknown_fields = set(self.permitted_fields) - OBSERVATION_FIELDS
        if unknown_fields:
            raise ValueError(f"coverage grant names unsupported fields: {', '.join(sorted(unknown_fields))}")
        if "pass_completion" in self.permitted_fields and self.level.rank < CoverageLevel.EVENTS.rank:
            raise ValueError("pass completion requires event-level coverage")
        if "pass_completion" in self.permitted_fields and not {
            "pass", "ball_contact", "possession_controlled", "possession_regained",
        }.issubset(self.permitted_event_kinds):
            raise ValueError("pass completion requires complete pass, contact, and possession event access")
        if "goal_event" in self.permitted_fields and "goal" not in self.permitted_event_kinds:
            raise ValueError("goal-event observations require goal event access")
        if "tracked_position" in self.permitted_fields and self.level is not CoverageLevel.TRACKING:
            raise ValueError("player positions require tracking-level coverage")
        if "tracked_position" in self.permitted_fields and not self.permitted_event_kinds:
            raise ValueError("player positions require permission for tracked event kinds")
        if not isinstance(self.method, str) or not self.method.strip():
            raise ValueError("coverage grant requires an observation method")
        if type(self.minimum_work_units) is not int or self.minimum_work_units <= 0:
            raise ValueError("coverage work requirement must be positive")

    def active_on(self, world_date: WorldDate) -> bool:
        if not isinstance(world_date, WorldDate):
            raise TypeError("coverage check requires an explicit world date")
        return self.starts_on <= world_date <= self.expires_on

    def permits_field(self, field: str, level: CoverageLevel) -> bool:
        return field in self.permitted_fields and level.rank <= self.level.rank

    def permits_event(self, event_kind: str) -> bool:
        return event_kind in self.permitted_event_kinds


@dataclass(frozen=True)
class StaffCapacity:
    staff_id: str
    club_id: ClubId
    roles: tuple[StaffRole, ...]
    daily_work_units: int

    def __post_init__(self) -> None:
        validate_id(self.staff_id, kind="staff ID")
        validate_id(self.club_id, kind="staff club ID")
        if not isinstance(self.roles, tuple) or not self.roles or any(
            not isinstance(role, StaffRole) for role in self.roles
        ):
            raise TypeError("staff capacity requires one or more explicit roles")
        if len(self.roles) != len(set(self.roles)):
            raise ValueError("staff roles cannot be repeated")
        if type(self.daily_work_units) is not int or self.daily_work_units <= 0:
            raise ValueError("staff daily work capacity must be positive")


@dataclass(frozen=True)
class StaffWorkAssignment:
    assignment_id: str
    task_id: str
    staff_id: str
    club_id: ClubId
    role: StaffRole
    scheduled_on: WorldDate
    work_units: int

    def __post_init__(self) -> None:
        validate_id(self.assignment_id, kind="staff assignment ID")
        validate_id(self.task_id, kind="staff task ID")
        validate_id(self.staff_id, kind="assigned staff ID")
        validate_id(self.club_id, kind="assignment club ID")
        if not isinstance(self.role, StaffRole):
            raise TypeError("staff assignment requires an explicit role")
        if not isinstance(self.scheduled_on, WorldDate):
            raise TypeError("staff assignment requires a scheduled world date")
        if type(self.work_units) is not int or self.work_units <= 0:
            raise ValueError("assigned work units must be positive")


@dataclass(frozen=True)
class StaffSchedule:
    assignments: tuple[StaffWorkAssignment, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.assignments, tuple) or any(
            not isinstance(item, StaffWorkAssignment) for item in self.assignments
        ):
            raise TypeError("staff schedule requires immutable assignment records")
        ids = [item.assignment_id for item in self.assignments]
        tasks = [item.task_id for item in self.assignments]
        if len(ids) != len(set(ids)) or len(tasks) != len(set(tasks)):
            raise ValueError("staff schedule cannot repeat assignment or task IDs")


def assign_staff_work(
    schedule: StaffSchedule,
    capacity: StaffCapacity,
    assignment: StaffWorkAssignment,
) -> StaffSchedule:
    """Schedule work once after checking role, club, and daily capacity."""

    if not isinstance(schedule, StaffSchedule) or not isinstance(capacity, StaffCapacity):
        raise TypeError("staff work scheduling requires a schedule and capacity record")
    if not isinstance(assignment, StaffWorkAssignment):
        raise TypeError("staff work scheduling requires an assignment record")
    if assignment.staff_id != capacity.staff_id or assignment.club_id != capacity.club_id:
        raise ValueError("assignment staff and club must match the capacity record")
    if assignment.role not in capacity.roles:
        raise ValueError("staff member is not qualified for the assigned role")
    booked_items = [item for item in schedule.assignments
                    if item.staff_id == capacity.staff_id
                    and item.scheduled_on == assignment.scheduled_on]
    if any(item.club_id != capacity.club_id or item.role not in capacity.roles
           for item in booked_items):
        raise ValueError("existing staff schedule conflicts with the capacity record")
    booked = sum(item.work_units for item in booked_items)
    if booked > capacity.daily_work_units:
        raise ValueError("existing staff schedule already exceeds daily capacity")
    same_id = next((item for item in schedule.assignments
                    if item.assignment_id == assignment.assignment_id), None)
    if same_id is not None:
        if same_id != assignment:
            raise ValueError("staff assignment ID was reused with different work")
        return schedule
    if any(item.task_id == assignment.task_id for item in schedule.assignments):
        raise ValueError("staff task is already assigned and cannot create duplicate work")
    if booked + assignment.work_units > capacity.daily_work_units:
        raise ValueError("staff daily capacity would be exceeded")
    return StaffSchedule(schedule.assignments + (assignment,))


@dataclass(frozen=True)
class Observation:
    observation_id: str
    club_id: ClubId
    match_id: MatchId
    subject_id: str
    field: str
    value_json: str
    evidence_date: WorldDate
    recorded_on: WorldDate
    source_tick: int
    source_sequence: int
    method: str
    coverage_level: CoverageLevel
    coverage_grant_id: str
    staff_id: str
    source_event_ids: tuple[EventId, ...]
    provenance: DataProvenance

    def __post_init__(self) -> None:
        validate_id(self.observation_id, kind="observation ID")
        validate_id(self.club_id, kind="observation club ID")
        validate_id(self.match_id, kind="observation match ID")
        validate_id(self.subject_id, kind="observation subject ID")
        validate_id(self.coverage_grant_id, kind="observation grant ID")
        validate_id(self.staff_id, kind="observation staff ID")
        if not isinstance(self.field, str) or not self.field.strip():
            raise ValueError("observation field must be non-empty")
        if self.field not in OBSERVATION_FIELDS:
            raise ValueError("observation field is not implemented or observable in P10")
        if not isinstance(self.value_json, str):
            raise TypeError("observation value must be finite JSON text")
        try:
            parsed = json.loads(self.value_json,
                                parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)))
            json.dumps(parsed, allow_nan=False)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("observation value must be finite JSON") from exc
        if parsed is None:
            raise ValueError("an observation cannot encode an unknown value")
        if not isinstance(self.evidence_date, WorldDate) or not isinstance(self.recorded_on, WorldDate):
            raise TypeError("observation requires evidence and recording dates")
        if self.recorded_on < self.evidence_date:
            raise ValueError("observation cannot be recorded before its source evidence exists")
        if type(self.source_tick) is not int or self.source_tick < 0:
            raise ValueError("observation source tick must be non-negative")
        if type(self.source_sequence) is not int or self.source_sequence < 0:
            raise ValueError("observation source sequence must be non-negative")
        if not isinstance(self.method, str) or not self.method.strip():
            raise ValueError("observation requires its method")
        if not isinstance(self.coverage_level, CoverageLevel):
            raise TypeError("observation coverage level must be explicit")
        if not isinstance(self.source_event_ids, tuple) or not self.source_event_ids:
            raise TypeError("observation requires immutable source event IDs")
        if len(self.source_event_ids) != len(set(self.source_event_ids)):
            raise ValueError("observation source event IDs cannot repeat")
        for event_id in self.source_event_ids:
            validate_id(event_id, kind="observation source event ID")
        if not isinstance(self.provenance, DataProvenance):
            raise TypeError("observation requires explicit provenance")
        if self.provenance.kind is not ProvenanceKind.OBSERVED:
            raise ValueError("match observation provenance must be observed")
        if self.provenance.evidence_date != self.evidence_date:
            raise ValueError("observation provenance date must match its source evidence date")


@dataclass(frozen=True)
class ObservationLedger:
    observations: tuple[Observation, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.observations, tuple) or any(
            not isinstance(item, Observation) for item in self.observations
        ):
            raise TypeError("observation ledger requires immutable observation records")
        ids = [item.observation_id for item in self.observations]
        if len(ids) != len(set(ids)):
            raise ValueError("observation ledger cannot repeat an observation ID")
        source_keys = [
            (item.club_id, item.match_id, item.subject_id, item.field, item.source_event_ids)
            for item in self.observations
        ]
        if len(source_keys) != len(set(source_keys)):
            raise ValueError("observation ledger cannot count one source chain twice")


def record_observations(
    ledger: ObservationLedger,
    observations: tuple[Observation, ...],
) -> ObservationLedger:
    """Append observations idempotently; one source chain is one evidence item."""

    if not isinstance(ledger, ObservationLedger) or not isinstance(observations, tuple):
        raise TypeError("recording observations requires a ledger and immutable tuple")
    by_id = {item.observation_id: item for item in ledger.observations}
    source_keys = {
        (item.club_id, item.match_id, item.subject_id, item.field, item.source_event_ids): item
        for item in ledger.observations
    }
    updated = list(ledger.observations)
    for item in observations:
        if not isinstance(item, Observation):
            raise TypeError("observation batch contains an invalid record")
        existing = by_id.get(item.observation_id)
        if existing is not None:
            if existing != item:
                raise ValueError("observation ID was reused with conflicting evidence")
            continue
        source_key = (item.club_id, item.match_id, item.subject_id, item.field, item.source_event_ids)
        duplicate = source_keys.get(source_key)
        if duplicate is not None:
            if duplicate.value_json != item.value_json:
                raise ValueError("one source event chain produced conflicting observations")
            continue
        by_id[item.observation_id] = item
        source_keys[source_key] = item
        updated.append(item)
    return ObservationLedger(tuple(updated))


@dataclass(frozen=True)
class FieldRequest:
    field: str
    minimum_coverage: CoverageLevel
    max_evidence_age_days: int = 90

    def __post_init__(self) -> None:
        if not isinstance(self.field, str) or not self.field.strip():
            raise ValueError("report field request must be non-empty")
        if not isinstance(self.minimum_coverage, CoverageLevel):
            raise TypeError("report field request requires a coverage level")
        if type(self.max_evidence_age_days) is not int or self.max_evidence_age_days < 0:
            raise ValueError("field evidence age must be a non-negative number of days")


@dataclass(frozen=True)
class ReportQuery:
    club_id: ClubId
    match_id: MatchId
    as_of: WorldDate
    metric_ids: tuple[str, ...]
    fields: tuple[FieldRequest, ...] = ()
    subject_id: str | None = None
    method_version: str = "match-report-v1"

    def __post_init__(self) -> None:
        validate_id(self.club_id, kind="report club ID")
        validate_id(self.match_id, kind="report match ID")
        if not isinstance(self.as_of, WorldDate):
            raise TypeError("report query requires an as-of world date")
        if not isinstance(self.metric_ids, tuple) or any(
            not isinstance(value, str) or not value.strip() for value in self.metric_ids
        ):
            raise TypeError("report metrics must be an immutable tuple of IDs")
        if len(self.metric_ids) != len(set(self.metric_ids)):
            raise ValueError("report query cannot request duplicate metrics")
        if not isinstance(self.fields, tuple) or any(not isinstance(value, FieldRequest) for value in self.fields):
            raise TypeError("report fields must be immutable field requests")
        field_ids = [value.field for value in self.fields]
        if len(field_ids) != len(set(field_ids)):
            raise ValueError("report query cannot request duplicate fields")
        if self.subject_id is not None:
            validate_id(self.subject_id, kind="report subject ID")
        if not isinstance(self.method_version, str) or not self.method_version.strip():
            raise ValueError("report query requires a method version")


@dataclass(frozen=True)
class ReportFieldFinding:
    field: str
    sample_count: int
    source_observation_ids: tuple[str, ...] = ()
    source_event_ids: tuple[EventId, ...] = ()
    unavailable_reason: str | None = None
    warning_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.field, str) or not self.field.strip():
            raise ValueError("report field finding must be named")
        if type(self.sample_count) is not int or self.sample_count < 0:
            raise ValueError("report field sample count must be non-negative")
        if not isinstance(self.source_observation_ids, tuple) or not isinstance(self.source_event_ids, tuple):
            raise TypeError("report field evidence references must be immutable tuples")
        if not isinstance(self.warning_codes, tuple):
            raise TypeError("report field warning codes must be immutable")
        if (self.sample_count == 0) != (self.unavailable_reason is not None):
            raise ValueError("unavailable report fields need a reason and available fields cannot claim one")
        for value in self.source_observation_ids:
            validate_id(value, kind="report observation ID")
        for value in self.source_event_ids:
            validate_id(value, kind="report source event ID")


@dataclass(frozen=True)
class MetricFinding:
    metric_id: str
    value: float | None
    unit: str
    numerator_label: str
    denominator_label: str
    context: str
    numerator: int | None
    denominator: int | None
    sample_size: int
    lower_bound: float | None
    upper_bound: float | None
    uncertainty: str | None
    source_observation_ids: tuple[str, ...]
    source_event_ids: tuple[EventId, ...]
    unavailable_reason: str | None = None
    warning_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.metric_id, str) or not self.metric_id.strip():
            raise ValueError("metric finding requires a metric ID")
        if not isinstance(self.unit, str) or not self.unit.strip():
            raise ValueError("metric finding requires an explicit unit")
        if not isinstance(self.numerator_label, str) or not self.numerator_label.strip():
            raise ValueError("metric finding requires its numerator definition")
        if not isinstance(self.denominator_label, str) or not self.denominator_label.strip():
            raise ValueError("metric finding requires its denominator definition")
        if not isinstance(self.context, str) or not self.context.strip():
            raise ValueError("metric finding requires cohort and context")
        if type(self.sample_size) is not int or self.sample_size < 0:
            raise ValueError("metric sample size must be non-negative")
        if not isinstance(self.source_observation_ids, tuple) or not isinstance(self.source_event_ids, tuple):
            raise TypeError("metric evidence references must be immutable tuples")
        if not isinstance(self.warning_codes, tuple):
            raise TypeError("metric warning codes must be immutable")
        unavailable = self.unavailable_reason is not None
        if unavailable:
            if any(value is not None for value in (self.value, self.numerator, self.denominator,
                                                   self.lower_bound, self.upper_bound, self.uncertainty)):
                raise ValueError("unavailable metrics cannot encode numeric zero or an interval")
        else:
            if self.value is None or not math.isfinite(self.value):
                raise ValueError("available metrics require a finite value")
            if self.numerator is None or self.denominator is None:
                raise ValueError("registered metrics require explicit numerator and denominator")
            if self.denominator <= 0 or self.numerator < 0:
                raise ValueError("metric denominator must be positive and numerator non-negative")
            if (self.lower_bound is None) != (self.upper_bound is None):
                raise ValueError("metric uncertainty interval requires both bounds")
            if self.lower_bound is not None and not (
                math.isfinite(self.lower_bound) and math.isfinite(self.upper_bound)
                and 0.0 <= self.lower_bound <= self.upper_bound <= 1.0
            ):
                raise ValueError("metric confidence bounds must be ordered fractions")
        for value in self.source_observation_ids:
            validate_id(value, kind="metric observation ID")
        for value in self.source_event_ids:
            validate_id(value, kind="metric source event ID")


@dataclass(frozen=True)
class Report:
    report_id: str
    cache_key: str
    query: ReportQuery
    generated_on: WorldDate
    method_version: str
    metric_findings: tuple[MetricFinding, ...]
    field_findings: tuple[ReportFieldFinding, ...]

    def __post_init__(self) -> None:
        validate_id(self.report_id, kind="report ID")
        validate_id(self.cache_key, kind="report cache key")
        if not isinstance(self.query, ReportQuery) or self.generated_on != self.query.as_of:
            raise ValueError("report date must match its query date")
        if not isinstance(self.method_version, str) or not self.method_version.strip():
            raise ValueError("report requires a method version")
        if not isinstance(self.metric_findings, tuple) or not isinstance(self.field_findings, tuple):
            raise TypeError("report findings must be immutable tuples")
        if tuple(item.metric_id for item in self.metric_findings) != self.query.metric_ids:
            raise ValueError("report metric findings must match the requested order")
        if tuple(item.field for item in self.field_findings) != tuple(item.field for item in self.query.fields):
            raise ValueError("report field findings must match the requested order")


@dataclass(frozen=True)
class ReportCache:
    reports: tuple[Report, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.reports, tuple) or any(not isinstance(item, Report) for item in self.reports):
            raise TypeError("report cache must contain immutable report records")
        keys = [item.cache_key for item in self.reports]
        if len(keys) != len(set(keys)):
            raise ValueError("report cache cannot repeat a cache key")

    def get(self, cache_key: str) -> Report | None:
        return next((item for item in self.reports if item.cache_key == cache_key), None)

    def add(self, report: Report) -> ReportCache:
        existing = self.get(report.cache_key)
        if existing is not None:
            if existing != report:
                raise ValueError("report cache key was reused for different content")
            return self
        return ReportCache(self.reports + (report,))
