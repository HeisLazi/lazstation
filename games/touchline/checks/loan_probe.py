"""Fresh-process deterministic loan lifecycle probe for P15c."""

from __future__ import annotations

import json
from datetime import date

from games.touchline.esb.economy.ledger import (
    CashAccount, EconomyLedger, EmploymentContract, add_account, employment_at,
    settle_obligation,
)
from games.touchline.esb.economy.loans import (
    LoanBook, LoanProposal, PurchaseOption, accrue_loan_wage_share, activate_loan,
    propose_loan, respond_to_loan, return_loan,
)
from games.touchline.esb.people.medical_clearance import assess_transfer_medical
from games.touchline.esb.serialization import dumps
from games.touchline.esb.time import WorldDate
from games.touchline.esb.world.registration import (
    ClubCompetitionSquad, PlayerTrainingRecord, RegistrationBook, RegistrationPolicy,
)


def day(month: int, value: int) -> WorldDate:
    return WorldDate(date(2027, month, value))


def run_probe() -> dict[str, object]:
    contract = EmploymentContract(
        "contract:probe-owner", "club:probe-owner", "player:probe-loanee",
        day(1, 1), day(1, 1), day(12, 31), "GBP", 10_000,
    )
    economy = EconomyLedger(contracts=(contract,))
    for account in (
        CashAccount("club:probe-owner", "GBP", 500_000),
        CashAccount("club:probe-borrower", "GBP", 500_000),
        CashAccount("player:probe-loanee", "GBP", 0),
    ):
        economy = add_account(economy, account)
    registrations = RegistrationBook(
        policies=(RegistrationPolicy(
            "competition:probe", "rules:probe-v1", day(1, 1), day(11, 30), 5, 1, 3,
        ),),
        player_training=(
            PlayerTrainingRecord("player:probe-loanee", ("club:probe-owner",)),
            PlayerTrainingRecord("player:probe-owner-homegrown", ("club:probe-owner",)),
            PlayerTrainingRecord("player:probe-borrower-homegrown", ("club:probe-borrower",)),
        ),
        squads=(
            ClubCompetitionSquad("competition:probe", "club:probe-owner", (
                "player:probe-loanee", "player:probe-owner-homegrown",
            )),
            ClubCompetitionSquad("competition:probe", "club:probe-borrower", (
                "player:probe-borrower-homegrown",
            )),
        ),
    )
    proposal = LoanProposal(
        "loan:probe", "player:probe-loanee", "club:probe-owner", "club:probe-borrower",
        contract.contract_id, day(1, 2), day(1, 7), day(1, 10), day(3, 10),
        "GBP", 25_000, 5_000, ("competition:probe",), day(2, 1),
        PurchaseOption(40_000, day(2, 1), day(3, 1), 12_000, 52),
    )
    book = propose_loan(LoanBook(), proposal, economy)
    book = respond_to_loan(book, proposal.loan_id, proposal.owner_club_id, True, day(1, 3))
    book = respond_to_loan(book, proposal.loan_id, proposal.player_id, True, day(1, 4))
    assessment = assess_transfer_medical(
        proposal.player_id, "staff:probe-doctor", (), day(1, 9),
    )
    book, economy, registrations = activate_loan(
        book, economy, registrations, proposal.loan_id, assessment, day(1, 10),
    )
    book, economy, wage_share = accrue_loan_wage_share(
        book, economy, proposal.loan_id, day(1, 15),
    )
    assert wage_share is not None
    economy, _ = settle_obligation(economy, wage_share.obligation_id, day(1, 15))
    book, registrations = return_loan(book, registrations, proposal.loan_id, day(3, 10))
    return {
        "loan_status": book.events[-1].kind.value,
        "event_ids": [event.event_id for event in book.events],
        "loan_book": json.loads(book.to_json()),
        "economy": json.loads(dumps(economy)),
        "registrations": json.loads(registrations.to_json()),
        "effective_employer_after_return": employment_at(
            economy, proposal.player_id, day(3, 10),
        ).club_id,
    }


def main() -> None:
    print(json.dumps(run_probe(), ensure_ascii=False, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
