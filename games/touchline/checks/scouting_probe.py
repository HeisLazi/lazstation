"""Fresh-process scenario for multi-match recruitment and opposition reports."""

from __future__ import annotations

import json
from datetime import date

from games.touchline.esb.events import EventEnvelope
from games.touchline.esb.ids import ClubId, EventId, MatchId
from games.touchline.esb.knowledge.coverage import observation_task_id, record_match_observations
from games.touchline.esb.knowledge.metrics import CORE_METRICS
from games.touchline.esb.knowledge.model import (
    CoverageGrant,
    CoverageLevel,
    ObservationLedger,
    StaffCapacity,
    StaffRole,
    StaffSchedule,
    StaffWorkAssignment,
    assign_staff_work,
    record_observations,
)
from games.touchline.esb.knowledge.scouting import (
    RoleProfile,
    ScoutingQuery,
    opposition_brief,
    role_search,
)
from games.touchline.esb.serialization import dumps
from games.touchline.esb.time import WorldDate


CLUB_ID = ClubId("club:scouting-observer")
PLAYER_A = "player:reliable-distributor"
PLAYER_B = "player:variable-distributor"
UNKNOWN = "player:unobserved"
ROLE = RoleProfile(
    "role:build-up-distributor", "Build-up distributor", "pass_completion_rate",
    0.55, minimum_attempts=12, minimum_matches=2,
)


def _event(match_id: MatchId, sequence: int, tick: int, kind: str, actor: str,
           *, receiver: str | None = None, cause: str | None = None,
           parent: str | None = None) -> EventEnvelope:
    payload = {"actor_id": actor}
    if receiver is not None:
        payload["receiver_id"] = receiver
    return EventEnvelope(
        event_id=EventId(f"event:scouting:{match_id.split(':')[-1]}:{sequence:04d}"),
        aggregate_type="match",
        aggregate_id=str(match_id),
        sequence=sequence,
        kind=kind,
        match_id=match_id,
        match_tick=tick,
        cause_event_id=EventId(cause) if cause else None,
        parent_event_id=EventId(parent) if parent else None,
        payload_json=json.dumps(payload, sort_keys=True),
        outcome_json="{}",
    )


def _match(match_suffix: str, match_day: date, success_plan: dict[str, tuple[bool, ...]]):
    match_id = MatchId(f"match:scouting-{match_suffix}")
    world_date = WorldDate(match_day)
    grant = CoverageGrant(
        grant_id=f"coverage:scouting-{match_suffix}",
        club_id=CLUB_ID,
        match_id=match_id,
        match_date=world_date,
        starts_on=world_date,
        expires_on=WorldDate(date(match_day.year + 1, match_day.month, match_day.day)),
        level=CoverageLevel.EVENTS,
        permitted_fields=("pass_completion",),
        permitted_event_kinds=(
            "pass", "ball_contact", "possession_controlled", "possession_regained",
        ),
        method="authorized recorded match observation",
        minimum_work_units=2,
    )
    capacity = StaffCapacity(
        f"staff:scouting-{match_suffix}", CLUB_ID, (StaffRole.OBSERVER,), 8,
    )
    assignment = StaffWorkAssignment(
        f"assignment:scouting-{match_suffix}", observation_task_id(grant), capacity.staff_id,
        CLUB_ID, StaffRole.OBSERVER, world_date, 2,
    )
    schedule = assign_staff_work(StaffSchedule(), capacity, assignment)
    events: list[EventEnvelope] = []
    sequence = 0
    pass_index = 0
    event_prefix = f"event:scouting:scouting-{match_suffix}:"
    for player_id, successes in success_plan.items():
        for success in successes:
            pass_id = f"{event_prefix}{sequence:04d}"
            contact_id = f"{event_prefix}{sequence + 1:04d}"
            events.append(_event(match_id, sequence, pass_index * 3, "pass", player_id,
                                 receiver="player:target"))
            events.append(_event(match_id, sequence + 1, pass_index * 3 + 1,
                                 "ball_contact", "player:target" if success else "player:defender",
                                 cause=pass_id, parent=pass_id))
            resolution_kind = "possession_controlled" if success else "possession_regained"
            resolution_actor = "player:target" if success else "player:defender"
            events.append(_event(match_id, sequence + 2, pass_index * 3 + 1,
                                 resolution_kind, resolution_actor,
                                 cause=contact_id, parent=pass_id))
            sequence += 3
            pass_index += 1
    captured = record_match_observations(
        tuple(events), grant, assignment, capacity, schedule, world_date,
    )
    return tuple(events), captured, grant


def build_scenario():
    events_a, observations_a, grant_a = _match(
        "early", date(2026, 2, 14),
        {PLAYER_A: (True, True, True, True, True, True, True, False),
         PLAYER_B: (True, True, True, True, True, False, False, False)},
    )
    events_b, observations_b, grant_b = _match(
        "late", date(2026, 2, 21),
        {PLAYER_A: (True, True, True, True, True, True, True, False),
         PLAYER_B: (True, True, True, True, False, False, False, False)},
    )
    ledger = record_observations(ObservationLedger(), observations_a + observations_b)
    grants = (grant_a, grant_b)
    query = ScoutingQuery(
        CLUB_ID, WorldDate(date(2026, 2, 21)), (PLAYER_A, PLAYER_B, UNKNOWN), 90,
    )
    search = role_search(query, ROLE, ledger, grants, CORE_METRICS)
    brief = opposition_brief(
        ScoutingQuery(CLUB_ID, query.as_of, (PLAYER_A, PLAYER_B), 90),
        ledger, grants, minimum_attempts=12, minimum_matches=2,
    )
    return search, brief, ledger, grants, events_a + events_b


def main() -> int:
    search, brief, _, _, _ = build_scenario()
    payload = {
        "role_search": json.loads(dumps(search)),
        "opposition_brief": json.loads(dumps(brief)),
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
