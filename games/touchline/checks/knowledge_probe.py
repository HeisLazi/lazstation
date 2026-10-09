"""Fresh-process deterministic P10 observation/report scenario."""

from __future__ import annotations

import json
from datetime import date

from games.touchline.esb.events import EventEnvelope
from games.touchline.esb.ids import ClubId, EventId, MatchId
from games.touchline.esb.knowledge import (
    CORE_METRICS,
    CoverageGrant,
    CoverageLevel,
    FieldRequest,
    ObservationLedger,
    ReportQuery,
    StaffCapacity,
    StaffRole,
    StaffSchedule,
    StaffWorkAssignment,
    assign_staff_work,
    build_report,
    observation_task_id,
    record_match_observations,
    record_observations,
)
from games.touchline.esb.serialization import dumps
from games.touchline.esb.time import WorldDate


OBSERVED_ON = WorldDate(date(2026, 2, 14))
CLUB_ID = ClubId("club:observer")
MATCH_ID = MatchId("match:knowledge-probe")


def event(
    sequence: int,
    tick: int,
    kind: str,
    actor: str,
    *,
    payload: dict[str, object] | None = None,
    outcome: dict[str, object] | None = None,
    cause: str | None = None,
    parent: str | None = None,
) -> EventEnvelope:
    event_id = EventId(f"event:knowledge-probe:{sequence:04d}")
    return EventEnvelope(
        event_id=event_id,
        aggregate_type="match",
        aggregate_id=str(MATCH_ID),
        sequence=sequence,
        kind=kind,
        match_id=MATCH_ID,
        match_tick=tick,
        cause_event_id=EventId(cause) if cause else None,
        parent_event_id=EventId(parent) if parent else None,
        payload_json=json.dumps({"actor_id": actor, **(payload or {})}, sort_keys=True),
        outcome_json=json.dumps(outcome or {}, sort_keys=True),
    )


def scenario_events() -> tuple[EventEnvelope, ...]:
    p1 = "event:knowledge-probe:0000"
    c1 = "event:knowledge-probe:0001"
    p2 = "event:knowledge-probe:0003"
    c2 = "event:knowledge-probe:0004"
    return (
        event(0, 0, "pass", "player:passer-a", payload={"receiver_id": "player:receiver-a"}),
        event(1, 1, "ball_contact", "player:receiver-a", cause=p1, parent=p1),
        event(2, 1, "possession_controlled", "player:receiver-a", cause=c1, parent=p1),
        event(3, 2, "pass", "player:passer-b", payload={"receiver_id": "player:receiver-b"}),
        event(4, 3, "ball_contact", "player:defender", cause=p2, parent=p2),
        event(5, 3, "possession_regained", "player:defender", cause=c2, parent=p2),
        event(6, 4, "tracking_sample", "player:passer-a", outcome={
            "tracked_positions": {
                "player:passer-a": {"x_m": 40.0, "y_m": 22.0},
                "player:receiver-a": {"x_m": 48.0, "y_m": 24.0},
            },
        }),
        event(7, 5, "goal", "player:scorer", payload={"scoring_team_id": "home"},
              outcome={"home_score": 1, "away_score": 0}),
    )


def rich_grant() -> CoverageGrant:
    return CoverageGrant(
        grant_id="coverage:knowledge-probe-rich",
        club_id=CLUB_ID,
        match_id=MATCH_ID,
        match_date=OBSERVED_ON,
        starts_on=OBSERVED_ON,
        expires_on=WorldDate(date(2027, 2, 14)),
        level=CoverageLevel.TRACKING,
        permitted_fields=("goal_event", "pass_completion", "tracked_position"),
        permitted_event_kinds=(
            "pass", "ball_contact", "possession_controlled", "possession_regained",
            "tracking_sample", "goal",
        ),
        method="tracked match observation",
        minimum_work_units=4,
    )


def build_scenario():
    grant = rich_grant()
    capacity = StaffCapacity("staff:observer", CLUB_ID,
                             (StaffRole.OBSERVER, StaffRole.ANALYST), daily_work_units=8)
    assignment = StaffWorkAssignment(
        "assignment:knowledge-probe", observation_task_id(grant), capacity.staff_id,
        CLUB_ID, StaffRole.OBSERVER, OBSERVED_ON, 4,
    )
    schedule = assign_staff_work(StaffSchedule(), capacity, assignment)
    captured = record_match_observations(
        scenario_events(), grant, assignment, capacity, schedule, OBSERVED_ON,
    )
    ledger = record_observations(ObservationLedger(), captured)
    query = ReportQuery(
        club_id=CLUB_ID,
        match_id=MATCH_ID,
        as_of=OBSERVED_ON,
        metric_ids=("pass_completion_rate", "tracked_position_samples", "observed_goal_events"),
        fields=(
            FieldRequest("pass_completion", CoverageLevel.EVENTS),
            FieldRequest("tracked_position", CoverageLevel.TRACKING, 14),
            FieldRequest("goal_event", CoverageLevel.RESULTS),
        ),
    )
    report, cache = build_report(query, ledger, (grant,), CORE_METRICS)
    return report, cache, ledger, grant


def main() -> int:
    report, _, _, _ = build_scenario()
    print(dumps(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
