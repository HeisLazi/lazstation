"""Deterministic multi-season probe for the P16d-a population boundary."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
import json

from games.touchline.esb.content.proof_roster import PROOF_SQUADS
from games.touchline.esb.ids import PlayerId
from games.touchline.esb.people import PrimaryRole
from games.touchline.esb.time import WorldDate
from games.touchline.esb.world.population import (
    IntakeCandidate,
    PlayerPopulationRecord,
    PopulationPolicy,
    RetirementHazard,
    WorldPopulationState,
    advance_population,
    create_population_state,
)


START = WorldDate(date(2026, 10, 1))
CLUB_ID = str(PROOF_SQUADS[0].club_id)


def authored_profile(template, key: str, born_on: date, *, display_name: str | None = None):
    """Give a fictional proof archetype unique, dated authored scenario facts."""
    player_id = PlayerId(f"player:p16d-probe:{key}")
    identity = replace(
        template.identity,
        player_id=player_id,
        birth_date=born_on,
        birth_date_provenance="p16d.fictional-probe-birth-date-v1",
    )
    capabilities = replace(template.capabilities, player_id=player_id)
    preference = replace(template.preference, player_id=player_id)
    readiness = replace(template.readiness, player_id=player_id)
    tendencies = replace(template.tendencies, player_id=player_id)
    return replace(
        template,
        player_id=player_id,
        display_name=display_name or f"{template.display_name} {key}",
        identity=identity,
        capabilities=capabilities,
        preference=preference,
        readiness=readiness,
        tendencies=tendencies,
    )


def population_policy(*, minimum_squad_size: int = 2, maximum_intake: int = 2):
    return PopulationPolicy(
        retirement_hazards=(
            RetirementHazard(30, 0.05),
            RetirementHazard(35, 0.20),
            RetirementHazard(39, 0.50),
        ),
        guaranteed_retirement_age=40,
        minimum_intake_age=16,
        maximum_intake_age=23,
        minimum_squad_size=minimum_squad_size,
        minimum_role_counts=(
            (PrimaryRole.CENTER_BACK, 1),
            (PrimaryRole.GOALKEEPER, 1),
        ),
        maximum_intake_per_club=maximum_intake,
    )


def initial_population(*, seed: int = 92821) -> WorldPopulationState:
    goalkeeper = authored_profile(
        PROOF_SQUADS[0].players[0], "initial-gk", date(1986, 1, 1),
    )
    defender = authored_profile(
        PROOF_SQUADS[0].players[2], "initial-cb", date(2000, 1, 1),
    )
    return create_population_state(
        "world:p16d-probe",
        as_of=START,
        seed=seed,
        players=(
            PlayerPopulationRecord(goalkeeper, START, retirement_propensity=1.0),
            PlayerPopulationRecord(defender, START, retirement_propensity=1.0),
        ),
    )


def candidate_for(
    role: PrimaryRole,
    *,
    boundary: WorldDate,
    season_index: int,
    selection_rank: int,
) -> IntakeCandidate:
    template = (
        PROOF_SQUADS[0].players[0]
        if role is PrimaryRole.GOALKEEPER
        else PROOF_SQUADS[0].players[2]
        if role is PrimaryRole.CENTER_BACK
        else PROOF_SQUADS[0].players[10]
    )
    key = f"intake-{season_index}-{role.value}"
    profile = authored_profile(
        template,
        key,
        date(boundary.day.year - 18, 1, 1),
        display_name=f"Fictional intake {season_index} {role.value}",
    )
    return IntakeCandidate(
        candidate_id=f"candidate:p16d-probe:{season_index}:{role.value}",
        profile=profile,
        available_on=boundary,
        expires_on=WorldDate(boundary.day + timedelta(days=365 * 8)),
        selection_rank=selection_rank,
        retirement_propensity=1.0,
    )


def run_probe() -> dict[str, object]:
    state = initial_population()
    policy = population_policy()
    annual = []
    for season_index in range(1, 31):
        boundary = WorldDate(date(START.day.year + season_index, START.day.month, START.day.day))
        candidates = (
            candidate_for(
                PrimaryRole.GOALKEEPER,
                boundary=boundary,
                season_index=season_index,
                selection_rank=season_index * 2 - 1,
            ),
            candidate_for(
                PrimaryRole.CENTER_BACK,
                boundary=boundary,
                season_index=season_index,
                selection_rank=season_index * 2,
            ),
        )
        state = advance_population(
            state, boundary, policy=policy, new_candidates=candidates,
        )
        receipt = state.transitions[-1]
        club = next(item for item in receipt.coverage if item.club_id == CLUB_ID)
        annual.append({
            "year": boundary.day.year,
            "active": club.active_player_count,
            "squad_shortfall": club.squad_shortfall,
            "role_shortfalls": sum(value for _role, value in club.role_shortfalls),
            "retirements": sum(item.retired for item in receipt.retirement_decisions),
            "intakes": sum(item.outcome.value == "accepted" for item in receipt.intake_decisions),
            "pending_candidates": len(state.pending_candidates),
        })
    return {
        "world_id": state.world_id,
        "seed": state.seed,
        "seasons": len(annual),
        "annual": annual,
        "total_retirements": sum(row["retirements"] for row in annual),
        "total_intakes": sum(row["intakes"] for row in annual),
        "final_state_sha256": state.transitions[-1].result_population_sha256,
        "evidence_boundary": (
            "fictional authored archetypes; demographic lifecycle only; "
            "no fixtures, contracts, registration changes or generated players"
        ),
    }


if __name__ == "__main__":
    print(json.dumps(run_probe(), sort_keys=True, separators=(",", ":")))
