"""Deterministic synthetic multi-season probe for P16d-b player continuity."""

from __future__ import annotations

from datetime import date
import json

from games.touchline.checks.world_population_probe import (
    CLUB_ID,
    START,
    authored_profile,
    candidate_for,
    initial_population,
    population_policy,
)
from games.touchline.esb.economy.ledger import EconomyLedger, EmploymentContract, run_payroll
from games.touchline.esb.economy.loans import LoanBook
from games.touchline.esb.ids import derive_id
from games.touchline.esb.people import PrimaryRole
from games.touchline.esb.time import WorldDate
from games.touchline.esb.world.continuity import (
    AcademyArrivalTerms,
    AnnualContinuityState,
    advance_annual_continuity,
    record_continuity_update,
)
from games.touchline.esb.world.population import advance_population
from games.touchline.esb.world.registration import (
    ClubCompetitionSquad,
    PlayerTrainingRecord,
    RegistrationBook,
    RegistrationPolicy,
)


COMPETITION_ID = "competition:p16d-continuity-league"


def initial_continuity_state(*, seed: int = 92821) -> AnnualContinuityState:
    population = initial_population(seed=seed)
    contracts = tuple(
        EmploymentContract(
            derive_id("employment-contract", "p16d-continuity-initial-v1", player.player_id),
            player.club_id,
            player.player_id,
            START,
            START,
            WorldDate(date(2045, 10, 1)),
            "GBP",
            8_000,
        )
        for player in population.players
    )
    training = tuple(
        PlayerTrainingRecord(player.player_id, (player.club_id,))
        for player in population.players
    )
    book = RegistrationBook(
        policies=(RegistrationPolicy(
            COMPETITION_ID,
            "rules:p16d-continuity-v1",
            WorldDate(date(2026, 1, 1)),
            WorldDate(date(2045, 12, 31)),
            maximum_squad_size=12,
        ),),
        player_training=training,
        squads=(ClubCompetitionSquad(
            COMPETITION_ID,
            CLUB_ID,
            tuple(sorted(item.player_id for item in population.players)),
        ),),
    )
    return AnnualContinuityState(
        population.world_id, population, EconomyLedger(contracts=contracts), book, LoanBook(),
    )


def arrival_terms(candidate, boundary: WorldDate) -> AcademyArrivalTerms:
    return AcademyArrivalTerms(
        candidate_id=candidate.candidate_id,
        contract=EmploymentContract(
            derive_id(
                "employment-contract", "p16d-continuity-intake-v1",
                candidate.candidate_id, boundary.isoformat,
            ),
            candidate.club_id,
            candidate.player_id,
            boundary,
            boundary,
            WorldDate(date(boundary.day.year + 8, boundary.day.month, boundary.day.day)),
            "GBP",
            12_000,
        ),
        trained_at_club_ids=(),
        competition_ids=(COMPETITION_ID,),
    )


def run_probe() -> dict[str, object]:
    state = initial_continuity_state()
    policy = population_policy(minimum_squad_size=2)
    annual: list[dict[str, int]] = []
    for season_index in range(1, 6):
        boundary = WorldDate(date(
            START.day.year + season_index, START.day.month, START.day.day,
        ))
        candidates = tuple(sorted((
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
        ), key=lambda item: item.candidate_id))
        projected = advance_population(
            state.population, boundary, policy=policy, new_candidates=candidates,
        )
        accepted_ids = {
            item.candidate_id for item in projected.transitions[-1].intake_decisions
            if item.outcome.value == "accepted"
        }
        all_candidates = {
            item.candidate_id: item
            for item in state.population.pending_candidates + candidates
        }
        arrivals = tuple(
            arrival_terms(all_candidates[candidate_id], boundary)
            for candidate_id in sorted(accepted_ids)
        )
        state = advance_annual_continuity(
            state,
            boundary,
            policy=policy,
            new_candidates=candidates,
            academy_arrivals=arrivals,
        )
        receipt = state.transitions[-1]
        club = next(
            item for item in state.population.transitions[-1].coverage
            if item.club_id == CLUB_ID
        )
        registered = next(
            item for item in state.registration.squads
            if item.competition_id == COMPETITION_ID and item.club_id == CLUB_ID
        )
        active_ids = tuple(sorted(item.player_id for item in state.population.players if item.active))
        if registered.registered_player_ids != active_ids:
            raise AssertionError("active world players and competition registration diverged")
        annual.append({
            "year": boundary.day.year,
            "active_players": len(active_ids),
            "squad_shortfall": club.squad_shortfall,
            "retirements": len(receipt.retired_player_ids),
            "intakes": len(receipt.academy_contract_ids),
            "contracts": len(state.economy.contracts),
            "registration_checks": len(receipt.registration_checks),
        })
        payroll_on = WorldDate(date(boundary.day.year, 11, 1))
        state = record_continuity_update(
            state,
            payroll_on,
            economy=run_payroll(state.economy, payroll_on),
        )
    return {
        "world_id": state.world_id,
        "seed": state.population.seed,
        "seasons": len(annual),
        "annual": annual,
        "total_retirements": sum(item["retirements"] for item in annual),
        "total_intakes": sum(item["intakes"] for item in annual),
        "continuity_receipts": len(state.transitions),
        "between_boundary_payroll_receipts": len(state.state_updates),
        "population_events": len(state.population.events),
        "final_state_sha256": state.state_updates[-1].result_state_sha256,
        "evidence_boundary": (
            "fictional authored player archetypes; five annual population, contract and "
            "registration transitions and five dated between-boundary payroll updates; "
            "no fixtures, match archive, staff or manager simulation"
        ),
    }


if __name__ == "__main__":
    print(json.dumps(run_probe(), sort_keys=True, separators=(",", ":")))
