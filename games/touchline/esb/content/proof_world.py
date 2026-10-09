"""Small fictional multi-competition season used to exercise P16 world APIs."""

from __future__ import annotations

from datetime import date, timedelta

from games.touchline.esb.content.proof_roster import PROOF_SQUADS
from games.touchline.esb.ids import MatchId
from games.touchline.esb.match.engine import TeamSheet
from games.touchline.esb.match.possession import PlayerState
from games.touchline.esb.match.rules import STANDARD_RULES
from games.touchline.esb.match.spatial import PlayerMotion, limits_from_profile
from games.touchline.esb.model import Position2D
from games.touchline.esb.time import WorldDate
from games.touchline.esb.world.preparation import PreparationPolicy
from games.touchline.esb.world.registration import (
    ClubCompetitionSquad,
    PlayerTrainingRecord,
    RegistrationBook,
    RegistrationPolicy,
)
from games.touchline.esb.world.season import (
    CompetitionKind,
    WorldCompetition,
    WorldFixture,
    WorldSeasonSchedule,
)


_LINEUP = (0, 2, 3, 5, 6, 10, 13)
_POSITIONS = {
    "home": ((4, 34), (15, 20), (15, 48), (28, 9), (28, 59), (52.5, 34), (40, 34)),
    "away": ((101, 34), (90, 20), (90, 48), (78, 9), (78, 59), (62, 34), (70, 34)),
}


def proof_sheet(team_id: str, squad_index: int) -> TeamSheet:
    squad = PROOF_SQUADS[squad_index]
    starters = []
    for offset, roster_index in enumerate(_LINEUP):
        profile = squad.players[roster_index]
        motion = PlayerMotion(
            profile.player_id,
            team_id,
            Position2D(*_POSITIONS[team_id][offset]),
            0.0,
            0.0,
            0.0,
            limits_from_profile(profile),
        )
        starters.append(PlayerState(profile, motion, team_id))
    substitutes = tuple(
        profile for index, profile in enumerate(squad.players) if index not in _LINEUP
    )[:3]
    return TeamSheet(team_id, tuple(starters), substitutes, (squad.players[15].player_id,))


def proof_world_schedule(
    *, seed: int = 271828, half_ticks: int = 18
) -> WorldSeasonSchedule:
    """Return two clubs, league/cup/representative fixtures and shared players."""
    rules = STANDARD_RULES.with_overrides(
        "rules:p16-proof-world-short-v1",
        half_duration_ticks=half_ticks,
        stoppage_time_ticks=2,
        extra_time_duration_ticks=0,
        extra_time_stoppage_ticks=0,
        shootout_kicks_per_team=0,
        fouls_enabled=False,
        cards_enabled=False,
        advantage_enabled=False,
    )
    cup_rules = rules.with_overrides(
        "rules:p16-proof-world-cup-v1",
        offside_enabled=False,
        shootout_kicks_per_team=3,
    )
    competitions = (
        WorldCompetition(
            "competition:proof-league",
            ("club:coast", "club:ridge"),
            rules,
            CompetitionKind.LEAGUE,
        ),
        WorldCompetition(
            "competition:proof-cup",
            ("club:coast", "club:ridge"),
            cup_rules,
            CompetitionKind.CUP,
        ),
        WorldCompetition(
            "competition:proof-representative",
            ("nation:north", "nation:south"),
            rules,
            CompetitionKind.REPRESENTATIVE,
        ),
    )
    # The proof roster's readiness snapshots are dated 2026-09-24.
    # Schedule fixtures after those authored condition observations.
    start = date(2026, 10, 1)
    fixtures = (
        WorldFixture(
            "fixture:proof-league-01", MatchId("match:proof-league-01"),
            "competition:proof-league", WorldDate(start), 15 * 60,
            "club:coast", "club:ridge", proof_sheet("home", 0), proof_sheet("away", 1),
        ),
        WorldFixture(
            "fixture:proof-representative-01", MatchId("match:proof-representative-01"),
            "competition:proof-representative", WorldDate(start + timedelta(days=4)), 18 * 60,
            "nation:north", "nation:south", proof_sheet("home", 0), proof_sheet("away", 1),
        ),
        WorldFixture(
            "fixture:proof-cup-01", MatchId("match:proof-cup-01"),
            "competition:proof-cup", WorldDate(start + timedelta(days=8)), 15 * 60,
            "club:ridge", "club:coast", proof_sheet("home", 1), proof_sheet("away", 0),
        ),
        WorldFixture(
            "fixture:proof-league-02", MatchId("match:proof-league-02"),
            "competition:proof-league", WorldDate(start + timedelta(days=12)), 15 * 60,
            "club:ridge", "club:coast", proof_sheet("home", 1), proof_sheet("away", 0),
        ),
    )
    return WorldSeasonSchedule(
        "world:proof-world-v1",
        "season:proof-world-2026",
        seed,
        competitions,
        fixtures,
    )


def proof_world_flow_state(schedule: WorldSeasonSchedule | None = None):
    """Build a fully registered fictional world with accepted representative calls."""
    from games.touchline.esb.world.competition_flow import (
        CallUpDecision,
        NationalEligibility,
        NationalSelectionBook,
        create_world_competition_state,
        offer_national_call_up,
        respond_to_national_call_up,
    )

    schedule = schedule or proof_world_schedule()
    profiles = tuple(profile for squad in PROOF_SQUADS for profile in squad.players)
    start = schedule.ordered_fixtures[0].scheduled_on
    last_day = schedule.ordered_fixtures[-1].scheduled_on
    club_competitions = tuple(
        item for item in schedule.competitions
        if item.kind in (CompetitionKind.LEAGUE, CompetitionKind.CUP)
    )
    policies = tuple(RegistrationPolicy(
        item.competition_id,
        f"ruleset:proof-registration-{item.competition_id.rsplit(':', 1)[-1]}",
        WorldDate(start.day - timedelta(days=30)),
        WorldDate(last_day.day + timedelta(days=30)),
        maximum_squad_size=25,
    ) for item in club_competitions)
    proof_club_ids = ("club:coast", "club:ridge")
    training = tuple(PlayerTrainingRecord(
        str(profile.player_id), (proof_club_ids[index],),
    ) for index, squad in enumerate(PROOF_SQUADS) for profile in squad.players)
    squads = tuple(ClubCompetitionSquad(
        competition.competition_id,
        proof_club_ids[index],
        tuple(str(item.player_id) for item in squad.players),
    ) for competition in club_competitions
      for index, squad in enumerate(PROOF_SQUADS))
    registration = RegistrationBook(policies, training, squads)
    eligibility = tuple(NationalEligibility(
        profile.player_id,
        "nation:north" if index == 0 else "nation:south",
        WorldDate(start.day - timedelta(days=365)),
        WorldDate(last_day.day + timedelta(days=365)),
        "source:proof-world-representative-eligibility",
    ) for index, squad in enumerate(PROOF_SQUADS) for profile in squad.players)
    book = NationalSelectionBook(eligibility)
    representative_fixture = next(
        item for item in schedule.fixtures
        if schedule.competition(item.competition_id).kind is CompetitionKind.REPRESENTATIVE
    )
    offered_on = WorldDate(representative_fixture.scheduled_on.day - timedelta(days=7))
    response_by = WorldDate(representative_fixture.scheduled_on.day - timedelta(days=1))
    accepted_on = WorldDate(representative_fixture.scheduled_on.day - timedelta(days=2))
    for sheet in (representative_fixture.home_sheet, representative_fixture.away_sheet):
        named = tuple(item.profile.player_id for item in sheet.starters) + tuple(
            item.player_id for item in sheet.substitutes
        )
        for player_id in named:
            book = offer_national_call_up(
                book, schedule, player_id=player_id,
                fixture_id=representative_fixture.fixture_id,
                offered_on=offered_on, response_by=response_by,
            )
            book = respond_to_national_call_up(
                book, book.call_ups[-1].offer_id, CallUpDecision.ACCEPTED, accepted_on,
            )
    return create_world_competition_state(
        schedule,
        profiles=profiles,
        registration=registration,
        national_selection=book,
        starting_on=start,
        policy=PreparationPolicy(minimum_selection_readiness=0.68),
    )


__all__ = ["proof_sheet", "proof_world_flow_state", "proof_world_schedule"]
