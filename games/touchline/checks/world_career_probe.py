"""Fresh-process P16d-c proof for dated staff moves and archive growth."""

from __future__ import annotations

from dataclasses import asdict, replace
from datetime import date, timedelta
import json
import tempfile

from games.touchline.esb.club.governance import (
    Appointment,
    AuthorityAction,
    AuthorityGrant,
    AuthorityPolicy,
    BudgetBook,
    ClubGovernance,
    ClubRole,
    StaffFunction,
    StaffProfile,
    add_staff_appointment,
    add_staff_member,
)
from games.touchline.esb.content.proof_world import proof_world_schedule
from games.touchline.esb.ids import MatchId
from games.touchline.esb.time import WorldDate
from games.touchline.esb.world.archive_series import WorldArchiveSeries
from games.touchline.esb.world.season import WorldSeasonSchedule
from games.touchline.esb.world.staff_continuity import (
    StaffContinuityState,
    advance_staff_continuity,
    create_staff_continuity,
)


WORLD_ID = "world:p16d-career-proof"
CLUBS = ("club:coast", "club:ridge")
MANAGERS = ("person:manager-one", "person:manager-two")
OWNER_GRANTS = tuple(AuthorityGrant(item) for item in (
    AuthorityAction.APPOINT_STAFF,
    AuthorityAction.REGISTER_STAFF,
    AuthorityAction.GRANT_MANDATE,
))
def _owner_id(club_id: str) -> str:
    return f"appointment:owner-{club_id.rsplit(':', 1)[-1]}"


OWNER_IDS = {club: _owner_id(club) for club in CLUBS}
INITIAL_ON = WorldDate(date(2026, 10, 1))


def _governance(club_id: str) -> ClubGovernance:
    owner = Appointment(
        _owner_id(club_id), club_id, f"person:owner-{club_id.rsplit(':', 1)[-1]}",
        ClubRole.OWNER, WorldDate(date(2020, 1, 1)), None, OWNER_GRANTS,
    )
    return ClubGovernance(
        club_id,
        AuthorityPolicy(club_id),
        BudgetBook(club_id, "NAD", 1_000_000),
        appointments=(owner,),
    )


def _appoint_manager(
    state: ClubGovernance,
    manager_id: str,
    on: WorldDate,
    expires_on: WorldDate,
) -> ClubGovernance:
    appointment_id = f"appointment:{state.club_id.rsplit(':', 1)[-1]}-{manager_id.rsplit(':', 1)[-1]}-{on.isoformat}"
    appointment = Appointment(
        appointment_id, state.club_id, manager_id, ClubRole.MANAGER, on, expires_on, (),
    )
    result = add_staff_appointment(state, OWNER_IDS[str(state.club_id)], appointment, on)
    if not result.accepted:
        raise AssertionError(f"manager appointment was denied: {result.rejection}")
    if not any(item.staff_id == manager_id for item in result.state.staff):
        profile = StaffProfile(
            manager_id, state.club_id, appointment_id,
            (StaffFunction.COACHING,), 8,
        )
        registered = add_staff_member(result.state, OWNER_IDS[str(state.club_id)], profile, on)
        if not registered.accepted:
            raise AssertionError(f"manager registration was denied: {registered.rejection}")
        return registered.state
    return result.state


def initial_staff_state() -> StaffContinuityState:
    expiry = WorldDate(date(2027, 9, 30))
    coast = _appoint_manager(_governance(CLUBS[0]), MANAGERS[0], INITIAL_ON, expiry)
    ridge = _appoint_manager(_governance(CLUBS[1]), MANAGERS[1], INITIAL_ON, expiry)
    return create_staff_continuity(WORLD_ID, INITIAL_ON, (coast, ridge))


def _move_managers(
    state: StaffContinuityState, boundary: WorldDate, season_index: int,
) -> StaffContinuityState:
    year_end = WorldDate(date(boundary.day.year + 1, boundary.day.month, boundary.day.day) - timedelta(days=1))
    club_states = {str(item.club_id): item for item in state.clubs}
    # The two managers swap clubs each season. A contract expires on the day
    # before the next season boundary because governance expiry is inclusive.
    for club_index, club_id in enumerate(CLUBS):
        manager_id = MANAGERS[(club_index + season_index) % len(MANAGERS)]
        club_states[club_id] = _appoint_manager(
            club_states[club_id], manager_id, boundary, year_end,
        )
    return advance_staff_continuity(
        state, boundary, tuple(club_states[key] for key in sorted(club_states)),
    )


def season_schedule(seed: int, year: int) -> WorldSeasonSchedule:
    """Clone the fictional proof schedule with distinct IDs and dates."""
    base = replace(proof_world_schedule(seed=seed, half_ticks=8), world_id=WORLD_ID)
    offset = year - 2026
    fixtures = tuple(replace(
        fixture,
        fixture_id=f"fixture:career-{year}-{index:02d}",
        match_id=MatchId(f"match:career-{year}-{index:02d}"),
        scheduled_on=WorldDate(date(
            fixture.scheduled_on.day.year + offset,
            fixture.scheduled_on.day.month,
            fixture.scheduled_on.day.day,
        )),
    ) for index, fixture in enumerate(base.ordered_fixtures, start=1))
    return replace(
        base,
        season_id=f"season:proof-career-{year}",
        fixtures=fixtures,
    )


def run_probe(seed: int = 271828) -> str:
    staff = initial_staff_state()
    yearly = []
    with tempfile.TemporaryDirectory(prefix="touchline-p16d-c-") as directory:
        with WorldArchiveSeries(directory) as series:
            series.initialize(WORLD_ID, seed)
            for index, year in enumerate(range(2026, 2031)):
                if index:
                    staff = _move_managers(
                        staff, WorldDate(date(year, 10, 1)), index,
                    )
                schedule = season_schedule(seed, year)
                progress = series.simulate(schedule)
                metrics = series.metrics()
                with series.season_archive(schedule.season_id) as archive:
                    season_metrics = archive.metrics()
                if progress.pending or progress.archived != progress.scheduled:
                    raise AssertionError(f"season {year} did not archive every fixture")
                active_managers = [
                    {
                        "club_id": str(club.club_id),
                        "appointment_id": appointment.appointment_id,
                        "person_id": appointment.person_id,
                    }
                    for club in staff.clubs
                    for appointment in club.appointments
                    if appointment.role is ClubRole.MANAGER and appointment.active_on(staff.as_of)
                ]
                yearly.append({
                    "year": year,
                    "staff_receipt_sha256": staff.receipts[-1].receipt_sha256 if staff.receipts else None,
                    "active_managers": sorted(active_managers, key=lambda item: item["club_id"]),
                    "fixtures": progress.archived,
                    "season_events": season_metrics.total_recorded_events,
                    "season_player_rows": season_metrics.player_rows,
                    "season_unique_players": season_metrics.unique_players,
                    "season_database_bytes": season_metrics.database_bytes,
                    "season_summary_bytes": season_metrics.summary_bytes,
                    "cumulative_matches": metrics.archived_matches,
                    "cumulative_events": metrics.total_recorded_events,
                    "cumulative_player_rows": metrics.player_rows,
                    "cumulative_unique_players": metrics.unique_players,
                    "cumulative_database_bytes": metrics.database_bytes,
                    "cumulative_summary_bytes": metrics.summary_bytes,
                    "cumulative_catalog_bytes": metrics.catalog_database_bytes,
                    "cumulative_disk_bytes": metrics.on_disk_bytes,
                })
            player_id = season_schedule(seed, 2026).fixtures[0].home_sheet.starters[0].profile.player_id
            career = series.player_career_summary(player_id)
            final_metrics = series.metrics()
    if final_metrics.seasons != 5 or final_metrics.complete_seasons != 5:
        raise AssertionError("five complete seasons were not retained in the archive catalog")
    if career.matchday_selections != 20 or career.appearances != 20:
        raise AssertionError("proof player career history did not span the five seasons")
    if final_metrics.total_recorded_events <= 0 or final_metrics.on_disk_bytes <= 0:
        raise AssertionError("archive event and storage growth must be measurable")
    return json.dumps({
        "scenario": "synthetic-static-rosters-archive-growth",
        "seed": seed,
        "seasons": yearly,
        "career_player_id": str(player_id),
        "career_summary": asdict(career),
        "final_metrics": asdict(final_metrics),
        "limitations": [
            "Static fictional proof rosters; no aging, recruitment or transfer simulation.",
            "One existing single-season SQLite archive per season; no legacy archive migration.",
        ],
    }, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))


def main() -> None:
    print(run_probe())


if __name__ == "__main__":
    main()
