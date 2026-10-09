"""Small fictional promotion and qualification world used by P16c tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from itertools import combinations

from games.touchline.esb.content.proof_world import proof_sheet
from games.touchline.esb.ids import MatchId, new_player_id
from games.touchline.esb.match.engine import TeamSheet
from games.touchline.esb.match.possession import PlayerState
from games.touchline.esb.match.rules import STANDARD_RULES
from games.touchline.esb.time import WorldDate
from games.touchline.esb.world.progression import (
    LeagueTableScoring,
    ProgressionDestination,
    PromotionPyramid,
    QualificationPurpose,
    QualificationRoute,
    SeasonProgressionPlan,
    SeasonProgressionResult,
)
from games.touchline.esb.world.season import (
    CompetitionKind,
    WorldCompetition,
    WorldFixture,
    WorldSeasonSchedule,
)


WORLD_ID = "world:proof-progression"
SOURCE_SEASON_ID = "season:proof-progression-2026"
DESTINATION_SEASON_ID = "season:proof-progression-2027"
TOP_LEAGUE = "competition:proof-tier-one-2026"
LOWER_LEAGUE = "competition:proof-tier-two-2026"
NATIONAL_QUALIFIER = "competition:proof-nations-qualifier-2026"
NEXT_TOP_LEAGUE = "competition:proof-tier-one-2027"
NEXT_LOWER_LEAGUE = "competition:proof-tier-two-2027"
DOMESTIC_CUP = "competition:proof-domestic-cup-2027"
CONTINENTAL_CUP = "competition:proof-continental-cup-2027"
NATIONAL_FINALS = "competition:proof-national-finals-2027"

TOP_CLUBS = ("club:top-ash", "club:top-birch", "club:top-cinder")
LOWER_CLUBS = ("club:lower-dune", "club:lower-elm", "club:lower-flint")
NATIONS = ("nation:amber", "nation:birch", "nation:cedar", "nation:delta")
_SQUAD_INDEX = {
    participant_id: index % 2
    for index, participant_id in enumerate(TOP_CLUBS + LOWER_CLUBS + NATIONS)
}
_PARTICIPANT_STRENGTH = {
    participant_id: 0.62 + 0.04 * index
    for index, participant_id in enumerate(TOP_CLUBS + LOWER_CLUBS + NATIONS)
}


def proof_progression_schedule(*, seed: int = 161803, half_ticks: int = 6) -> WorldSeasonSchedule:
    """Return two small leagues and one four-nation round-robin qualifier."""
    rules = STANDARD_RULES.with_overrides(
        "rules:p16c-proof-progression-short-v1",
        half_duration_ticks=half_ticks,
        stoppage_time_ticks=1,
        extra_time_duration_ticks=0,
        extra_time_stoppage_ticks=0,
        shootout_kicks_per_team=0,
        fouls_enabled=False,
        cards_enabled=False,
        advantage_enabled=False,
    )
    competitions = (
        WorldCompetition(TOP_LEAGUE, TOP_CLUBS, rules, CompetitionKind.LEAGUE),
        WorldCompetition(LOWER_LEAGUE, LOWER_CLUBS, rules, CompetitionKind.LEAGUE),
        WorldCompetition(NATIONAL_QUALIFIER, NATIONS, rules, CompetitionKind.REPRESENTATIVE),
    )
    pairings = tuple(
        (competition, home, away)
        for competition, participants in (
            (competitions[0], TOP_CLUBS),
            (competitions[1], LOWER_CLUBS),
            (competitions[2], NATIONS),
        )
        for home, away in combinations(participants, 2)
    )
    first_day = date(2026, 10, 1)
    fixtures = tuple(
        WorldFixture(
            f"fixture:progression-source-{index:02d}",
            MatchId(f"match:progression-source-{index:02d}"),
            competition.competition_id,
            WorldDate(first_day + timedelta(days=index * 3)),
            15 * 60,
            home,
            away,
            _participant_sheet("home", home),
            _participant_sheet("away", away),
        )
        for index, (competition, home, away) in enumerate(pairings)
    )
    return WorldSeasonSchedule(
        WORLD_ID, SOURCE_SEASON_ID, seed, competitions, fixtures,
    )


def proof_progression_plan(
    *, registration_opens_on: date = date(2026, 10, 15),
    registration_closes_on: date = date(2026, 11, 10),
    starts_on: date = date(2026, 12, 1),
) -> SeasonProgressionPlan:
    """Build a versioned transition plan with domestic, continental and national routes."""
    opens = WorldDate(registration_opens_on)
    closes = WorldDate(registration_closes_on)
    starts = WorldDate(starts_on)
    destinations = tuple(ProgressionDestination(
        competition_id,
        kind,
        opens,
        closes,
        starts,
        minimum_entrants=2,
        maximum_entrants=8,
    ) for competition_id, kind in (
        (NEXT_TOP_LEAGUE, CompetitionKind.LEAGUE),
        (NEXT_LOWER_LEAGUE, CompetitionKind.LEAGUE),
        (DOMESTIC_CUP, CompetitionKind.CUP),
        (CONTINENTAL_CUP, CompetitionKind.CUP),
        (NATIONAL_FINALS, CompetitionKind.REPRESENTATIVE),
    ))
    return SeasonProgressionPlan(
        WORLD_ID,
        SOURCE_SEASON_ID,
        DESTINATION_SEASON_ID,
        destinations,
        pyramids=(PromotionPyramid(
            "pyramid:proof-national-levels",
            (TOP_LEAGUE, LOWER_LEAGUE),
            (NEXT_TOP_LEAGUE, NEXT_LOWER_LEAGUE),
            (1,),
        ),),
        qualification_routes=(
            QualificationRoute(
                "route:proof-domestic-cup",
                TOP_LEAGUE,
                DOMESTIC_CUP,
                QualificationPurpose.DOMESTIC_CUP,
                (1,),
            ),
            QualificationRoute(
                "route:proof-domestic-cup-lower",
                LOWER_LEAGUE,
                DOMESTIC_CUP,
                QualificationPurpose.DOMESTIC_CUP,
                (1,),
            ),
            QualificationRoute(
                "route:proof-continent",
                TOP_LEAGUE,
                CONTINENTAL_CUP,
                QualificationPurpose.CONTINENTAL,
                (1, 2),
            ),
            QualificationRoute(
                "route:proof-national-finals",
                NATIONAL_QUALIFIER,
                NATIONAL_FINALS,
                QualificationPurpose.NATIONAL_TOURNAMENT,
                (1, 2),
            ),
        ),
        scoring=LeagueTableScoring(),
    )


def proof_next_season_schedule(
    result: SeasonProgressionResult,
    plan: SeasonProgressionPlan,
    *,
    seed: int = 141421,
) -> WorldSeasonSchedule:
    """Make one fixture per target competition from exactly the resolved entrants."""
    rules = STANDARD_RULES.with_overrides(
        "rules:p16c-proof-next-season-short-v1",
        half_duration_ticks=2,
        stoppage_time_ticks=1,
        extra_time_duration_ticks=0,
        extra_time_stoppage_ticks=0,
        shootout_kicks_per_team=0,
        fouls_enabled=False,
        cards_enabled=False,
        advantage_enabled=False,
    )
    entries = {item.competition_id: item for item in result.entrants}
    competitions = tuple(WorldCompetition(
        item.competition_id,
        entries[item.competition_id].participant_ids,
        rules,
        item.kind,
    ) for item in plan.destinations)
    first_day = max(item.starts_on.day for item in plan.destinations)
    fixtures = []
    for index, competition in enumerate(competitions):
        participants = competition.participant_ids
        fixtures.append(WorldFixture(
            f"fixture:progression-next-{index:02d}",
            MatchId(f"match:progression-next-{index:02d}"),
            competition.competition_id,
            WorldDate(first_day + timedelta(days=index * 3)),
            15 * 60,
            participants[0],
            participants[1],
            _participant_sheet("home", participants[0]),
            _participant_sheet("away", participants[1]),
        ))
    return WorldSeasonSchedule(
        result.world_id,
        result.destination_season_id,
        seed,
        competitions,
        tuple(fixtures),
    )


def _participant_sheet(team_id: str, participant_id: str) -> TeamSheet:
    """Give each fictional club/nation its own roster identities across editions."""
    squad_index = _SQUAD_INDEX[participant_id]
    source = proof_sheet(team_id, squad_index)
    source_profiles = {
        item.player_id: _clone_profile(item, participant_id)
        for item in (
            tuple(state.profile for state in source.starters)
            + source.substitutes
        )
    }
    starters = tuple(
        PlayerState(
            source_profiles[state.profile.player_id],
            replace(state.motion, player_id=source_profiles[state.profile.player_id].player_id),
            team_id,
        )
        for state in source.starters
    )
    substitutes = tuple(source_profiles[item.player_id] for item in source.substitutes)
    unavailable = tuple(new_player_id(
        "p16c-proof-roster-v1", participant_id, str(item),
    ) for item in source.unavailable_player_ids)
    return TeamSheet(team_id, starters, substitutes, unavailable)


def _clone_profile(profile, participant_id: str):
    player_id = new_player_id("p16c-proof-roster-v1", participant_id, str(profile.player_id))
    strength_delta = _PARTICIPANT_STRENGTH[participant_id] - 0.80
    capabilities = replace(
        profile.capabilities,
        player_id=player_id,
        capabilities=tuple(replace(
            item,
            normalized_value=max(0.0, min(1.0, item.normalized_value + strength_delta)),
        ) for item in profile.capabilities.capabilities),
    )
    return replace(
        profile,
        player_id=player_id,
        identity=replace(profile.identity, player_id=player_id),
        capabilities=capabilities,
        preference=replace(profile.preference, player_id=player_id),
        readiness=replace(profile.readiness, player_id=player_id),
        tendencies=replace(profile.tendencies, player_id=player_id),
    )


__all__ = [
    "CONTINENTAL_CUP", "DOMESTIC_CUP", "DESTINATION_SEASON_ID", "LOWER_CLUBS",
    "LOWER_LEAGUE", "NATIONAL_FINALS", "NATIONAL_QUALIFIER", "NATIONS",
    "NEXT_LOWER_LEAGUE", "NEXT_TOP_LEAGUE", "SOURCE_SEASON_ID", "TOP_CLUBS",
    "TOP_LEAGUE", "WORLD_ID", "proof_next_season_schedule", "proof_progression_plan",
    "proof_progression_schedule",
]
