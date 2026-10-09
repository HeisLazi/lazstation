"""Permission checks and deterministic event-to-observation conversion."""

from __future__ import annotations

import json
import math
from typing import Any

from games.touchline.esb.events import EventEnvelope
from games.touchline.esb.ids import EventId, derive_id, validate_id
from games.touchline.esb.model import DataProvenance, ProvenanceKind
from games.touchline.esb.time import WorldDate

from .model import (
    CoverageGrant,
    CoverageLevel,
    Observation,
    StaffCapacity,
    StaffRole,
    StaffSchedule,
    StaffWorkAssignment,
)


def observation_task_id(grant: CoverageGrant) -> str:
    if not isinstance(grant, CoverageGrant):
        raise TypeError("observation task ID requires a coverage grant")
    return derive_id("command", "p10-observation-task-v1", grant.grant_id)


def _validate_assignment(
    grant: CoverageGrant,
    assignment: StaffWorkAssignment,
    capacity: StaffCapacity,
    schedule: StaffSchedule,
    recorded_on: WorldDate,
) -> None:
    if not isinstance(assignment, StaffWorkAssignment):
        raise TypeError("match observation requires an assigned staff task")
    if not isinstance(capacity, StaffCapacity) or not isinstance(schedule, StaffSchedule):
        raise TypeError("match observation requires staff capacity and schedule")
    if assignment not in schedule.assignments:
        raise ValueError("observation work must be present in the staff schedule")
    if assignment.task_id != observation_task_id(grant):
        raise ValueError("staff assignment does not refer to this coverage grant")
    if assignment.role is not StaffRole.OBSERVER:
        raise ValueError("match event capture requires an observer assignment")
    if assignment.staff_id != capacity.staff_id or assignment.club_id != capacity.club_id:
        raise ValueError("observation assignment and staff capacity do not agree")
    if assignment.club_id != grant.club_id:
        raise ValueError("observer and coverage grant must belong to the same club")
    if StaffRole.OBSERVER not in capacity.roles:
        raise ValueError("staff member is not qualified to observe matches")
    if assignment.scheduled_on != recorded_on:
        raise ValueError("observation work must be scheduled for its recording date")
    if assignment.work_units < grant.minimum_work_units:
        raise ValueError("observation assignment does not cover the grant's work requirement")
    booked_items = [item for item in schedule.assignments
                    if item.staff_id == capacity.staff_id and item.scheduled_on == recorded_on]
    if any(item.club_id != capacity.club_id or item.role not in capacity.roles
           for item in booked_items):
        raise ValueError("existing staff schedule conflicts with observation capacity")
    booked = sum(item.work_units for item in booked_items)
    if booked > capacity.daily_work_units:
        raise ValueError("scheduled staff work exceeds daily capacity")


def _json_value(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False,
                      sort_keys=True, separators=(",", ":"))


def _make_observation(
    grant: CoverageGrant,
    assignment: StaffWorkAssignment,
    recorded_on: WorldDate,
    *,
    subject_id: str,
    field: str,
    value: Any,
    source_events: tuple[EventEnvelope, ...],
    source_tick: int,
    source_sequence: int,
) -> Observation:
    source_ids = tuple(event.event_id for event in source_events)
    observation_id = derive_id(
        "observation", "touchline-observation-v1", grant.club_id, grant.match_id,
        field, subject_id, recorded_on.isoformat, grant.grant_id,
        *[str(event_id) for event_id in source_ids],
    )
    provenance = DataProvenance(
        ProvenanceKind.OBSERVED,
        f"coverage:{grant.grant_id};method:{grant.method};staff:{assignment.staff_id}",
        grant.match_date,
    )
    return Observation(
        observation_id=observation_id,
        club_id=grant.club_id,
        match_id=grant.match_id,
        subject_id=subject_id,
        field=field,
        value_json=_json_value(value),
        evidence_date=grant.match_date,
        recorded_on=recorded_on,
        source_tick=source_tick,
        source_sequence=source_sequence,
        method=grant.method,
        coverage_level=grant.level,
        coverage_grant_id=grant.grant_id,
        staff_id=assignment.staff_id,
        source_event_ids=source_ids,
        provenance=provenance,
    )


def _event_actor(event: EventEnvelope) -> str | None:
    value = event.payload.get("actor_id")
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("event actor ID must be a string")
    return validate_id(value, kind="observed player ID")


def _position_samples(
    event: EventEnvelope,
) -> tuple[tuple[str, float, float], ...]:
    positions = event.outcome.get("tracked_positions")
    if positions is None:
        return ()
    if not isinstance(positions, dict):
        raise ValueError("tracked_positions outcome must be a player-to-position object")
    samples: list[tuple[str, float, float]] = []
    for player_id, point in sorted(positions.items()):
        validate_id(player_id, kind="tracked player ID")
        if not isinstance(point, dict) or set(point) != {"x_m", "y_m"}:
            raise ValueError("tracked position requires x_m and y_m")
        x_m, y_m = point["x_m"], point["y_m"]
        if (type(x_m) not in (int, float) or type(y_m) not in (int, float)
                or not math.isfinite(x_m) or not math.isfinite(y_m)):
            raise ValueError("tracked coordinates must be finite metres")
        samples.append((player_id, float(x_m), float(y_m)))
    return tuple(samples)


def record_match_observations(
    events: tuple[EventEnvelope, ...],
    grant: CoverageGrant,
    assignment: StaffWorkAssignment,
    capacity: StaffCapacity,
    schedule: StaffSchedule,
    recorded_on: WorldDate,
) -> tuple[Observation, ...]:
    """Capture only facts licensed by a club's grant and staffed assignment.

    The pass metric is deliberately derived from a pass → contact → possession
    lineage. Execution ratings, capability snapshots and unrecorded positions
    are never copied into observations.
    """

    if not isinstance(events, tuple) or any(not isinstance(event, EventEnvelope) for event in events):
        raise TypeError("match observation requires an immutable event tuple")
    if not isinstance(grant, CoverageGrant):
        raise TypeError("match observation requires a coverage grant")
    if not isinstance(recorded_on, WorldDate):
        raise TypeError("match observation requires a recording date")
    if not grant.active_on(recorded_on):
        raise ValueError("coverage grant is not active on the observation date")
    if recorded_on < grant.match_date:
        raise ValueError("observation cannot be recorded before the match took place")
    _validate_assignment(grant, assignment, capacity, schedule, recorded_on)

    sequences = [event.sequence for event in events]
    ticks = [event.match_tick for event in events]
    event_ids = [event.event_id for event in events]
    if (len(sequences) != len(set(sequences)) or sequences != sorted(sequences)
            or len(event_ids) != len(set(event_ids))):
        raise ValueError("observation source events must be in unique sequence order")
    if any(tick is None for tick in ticks) or ticks != sorted(ticks):
        raise ValueError("observation source events must have chronological match ticks")
    if any(event.match_id != grant.match_id for event in events):
        raise ValueError("coverage grant cannot observe events from another match")
    if any(event.aggregate_type != "match" or event.aggregate_id != str(grant.match_id)
           for event in events):
        raise ValueError("coverage grant requires events from the matching match aggregate")
    by_id = {event.event_id: event for event in events}

    observed: list[Observation] = []
    if grant.permits_field("goal_event", CoverageLevel.RESULTS):
        for goal_event in events:
            if goal_event.kind != "goal" or not grant.permits_event("goal"):
                continue
            scoring_team_id = goal_event.payload.get("scoring_team_id")
            if not isinstance(scoring_team_id, str):
                continue
            validate_id(scoring_team_id, kind="observed scoring team ID")
            observed.append(_make_observation(
                grant, assignment, recorded_on,
                subject_id=str(grant.match_id),
                field="goal_event",
                value={"scoring_team_id": scoring_team_id},
                source_events=(goal_event,),
                source_tick=goal_event.match_tick or 0,
                source_sequence=goal_event.sequence,
            ))

    if grant.permits_field("pass_completion", CoverageLevel.EVENTS):
        for pass_event in events:
            if pass_event.kind != "pass" or not grant.permits_event("pass"):
                continue
            actor_id = _event_actor(pass_event)
            receiver_id = pass_event.payload.get("receiver_id")
            if actor_id is None or not isinstance(receiver_id, str):
                continue
            receiver_id = validate_id(receiver_id, kind="observed pass receiver ID")
            resolutions = [event for event in events
                           if event.kind in ("possession_controlled", "possession_regained")
                           and event.parent_event_id == pass_event.event_id]
            if not resolutions:
                continue
            resolution = resolutions[0]
            contact = by_id.get(resolution.cause_event_id) if resolution.cause_event_id else None
            if (contact is None or contact.kind not in ("ball_contact", "rebound_contact")
                    or not grant.permits_event(contact.kind)
                    or not grant.permits_event(resolution.kind)
                    or contact.cause_event_id != pass_event.event_id
                    or contact.parent_event_id != pass_event.event_id
                    or contact.sequence <= pass_event.sequence
                    or resolution.sequence <= contact.sequence):
                continue
            controlled_id = _event_actor(resolution)
            if controlled_id is None:
                continue
            success = resolution.kind == "possession_controlled" and controlled_id == receiver_id
            observed.append(_make_observation(
                grant, assignment, recorded_on,
                subject_id=actor_id,
                field="pass_completion",
                value=success,
                source_events=(pass_event, contact, resolution),
                source_tick=resolution.match_tick or 0,
                source_sequence=resolution.sequence,
            ))

    if grant.permits_field("tracked_position", CoverageLevel.TRACKING):
        for event in events:
            if not grant.permits_event(event.kind):
                continue
            for player_id, x_m, y_m in _position_samples(event):
                observed.append(_make_observation(
                    grant, assignment, recorded_on,
                    subject_id=player_id,
                    field="tracked_position",
                    value={"x_m": x_m, "y_m": y_m},
                    source_events=(event,),
                    source_tick=event.match_tick or 0,
                    source_sequence=event.sequence,
                ))
    observed.sort(key=lambda item: (
        item.recorded_on.day, item.source_tick, item.source_sequence, item.observation_id,
    ))
    return tuple(observed)
