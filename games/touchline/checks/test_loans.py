from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path

from games.touchline.esb.economy.ledger import (
    CashAccount, ContractTransfer, EconomyLedger, EmploymentContract, ObligationKind,
    add_account, employment_at, run_payroll, settle_obligation, transfer_employment,
)
from games.touchline.esb.economy.loans import (
    LoanBook, LoanEventKind, LoanProposal, LoanStatus, PurchaseOption,
    accrue_loan_wage_share, activate_loan, expire_loan_proposals,
    exercise_purchase_option, loan_status, propose_loan, recall_loan,
    respond_to_loan, return_loan, _event,
    scheduled_loan_obligation_ids,
)
from games.touchline.esb.ids import derive_id
from games.touchline.esb.people.medical import InjuryEpisode, RehabStage
from games.touchline.esb.people.medical_clearance import (
    MedicalOutcome, TransferMedicalAssessment, assess_transfer_medical,
)
from games.touchline.esb.serialization import SerializationError, dumps, loads
from games.touchline.esb.time import WorldDate
from games.touchline.esb.world.registration import (
    ClubCompetitionSquad, PlayerTrainingRecord, RegistrationBook,
    RegistrationPolicy,
)

ROOT = Path(__file__).resolve().parents[3]


def day(month: int, value: int) -> WorldDate:
    return WorldDate(date(2026, month, value))


def contract() -> EmploymentContract:
    return EmploymentContract(
        "contract:owner-player", "club:owner", "player:loaned",
        day(1, 1), day(1, 1), WorldDate(date(2027, 1, 1)), "GBP", 10_000,
    )


def ledger() -> EconomyLedger:
    state = EconomyLedger(contracts=(contract(),))
    for account in (
        CashAccount("club:owner", "GBP", 500_000),
        CashAccount("club:borrower", "GBP", 500_000),
        CashAccount("player:loaned", "GBP", 0),
    ):
        state = add_account(state, account)
    return state


def registrations(*, closes_on: WorldDate | None = None) -> RegistrationBook:
    return RegistrationBook(
        policies=(RegistrationPolicy(
            "competition:league", "rules:league-v1", day(1, 1),
            closes_on or WorldDate(date(2026, 12, 31)), 5, 1, 3,
        ),),
        player_training=(
            PlayerTrainingRecord("player:loaned", ("club:owner",)),
            PlayerTrainingRecord("player:owner-homegrown", ("club:owner",)),
            PlayerTrainingRecord("player:borrower-homegrown", ("club:borrower",)),
        ),
        squads=(
            ClubCompetitionSquad("competition:league", "club:owner",
                                 ("player:loaned", "player:owner-homegrown")),
            ClubCompetitionSquad("competition:league", "club:borrower",
                                 ("player:borrower-homegrown",)),
        ),
    )


def proposal(*, loan_id: str = "loan:one", purchase: bool = True,
             recall_from: WorldDate | None = day(2, 1)) -> LoanProposal:
    option = PurchaseOption(40_000, day(2, 1), day(3, 1), 12_000, 52) if purchase else None
    return LoanProposal(
        loan_id, "player:loaned", "club:owner", "club:borrower",
        "contract:owner-player", day(1, 2), day(1, 7), day(1, 10), day(3, 10),
        "GBP", 25_000, 5_000, ("competition:league",), recall_from, option,
    )


def agreed_loan(*, terms: LoanProposal | None = None) -> LoanBook:
    terms = terms or proposal()
    book = propose_loan(LoanBook(), terms, ledger())
    book = respond_to_loan(book, terms.loan_id, terms.owner_club_id, True, day(1, 3))
    return respond_to_loan(book, terms.loan_id, terms.player_id, True, day(1, 4))


def clearance(on: WorldDate | None = None, *, episodes: tuple[InjuryEpisode, ...] = ()) -> TransferMedicalAssessment:
    return assess_transfer_medical("player:loaned", "staff:doctor", episodes, on or day(1, 9))


class LoanLifecycleTests(unittest.TestCase):
    def test_offer_deadline_must_leave_an_activation_date_before_exclusive_end(self) -> None:
        with self.assertRaisesRegex(ValueError, "deadline must precede"):
            replace(proposal(), expires_on=day(3, 10))

    def test_activation_and_purchase_require_one_registration_check_per_competition(self) -> None:
        terms = replace(
            proposal(), loan_fee_minor=0,
            competition_ids=("competition:league", "competition:cup"),
        )
        agreed = agreed_loan(terms=terms)
        assessment = clearance(day(1, 10))
        incomplete_activation = _event(
            terms, terms.borrower_club_id, day(1, 10), LoanEventKind.ACTIVATED,
            assessment_id=assessment.assessment_id,
            registration_checks=("registration:league-check",),
        )
        with self.assertRaisesRegex(ValueError, "activation requires medical and registration"):
            LoanBook(agreed.proposals, agreed.events + (incomplete_activation,))

        complete_activation = _event(
            terms, terms.borrower_club_id, day(1, 10), LoanEventKind.ACTIVATED,
            assessment_id=assessment.assessment_id,
            registration_checks=("registration:league-check", "registration:cup-check"),
        )
        active = LoanBook(agreed.proposals, agreed.events + (complete_activation,))
        purchase_date = day(2, 1)
        contract_id = derive_id(
            "employment-contract", "p15c-loan-purchase-v1", terms.loan_id,
            purchase_date.isoformat,
        )
        fee_id = derive_id("obligation", "p15c-loan-purchase-fee-v1", terms.loan_id)
        incomplete_purchase = _event(
            terms, terms.borrower_club_id, purchase_date, LoanEventKind.PURCHASED,
            obligation_id=fee_id, assessment_id=clearance(purchase_date).assessment_id,
            registration_checks=("registration:league-check",),
            replacement_contract_id=contract_id,
        )
        with self.assertRaisesRegex(ValueError, "completed purchase must retain"):
            LoanBook(active.proposals, active.events + (incomplete_purchase,))

    def test_consent_gates_activation_and_fee_and_wage_share_settle_through_shared_ledger(self) -> None:
        terms = proposal(purchase=False, recall_from=None)
        book = agreed_loan(terms=terms)
        self.assertEqual(loan_status(book, terms.loan_id), LoanStatus.AGREED)
        before_ledger = ledger()
        active, economy, registered = activate_loan(
            book, before_ledger, registrations(), terms.loan_id, clearance(), day(1, 10),
        )
        self.assertEqual(loan_status(active, terms.loan_id), LoanStatus.ACTIVE)
        self.assertEqual(len(economy.contracts), 1)
        fee = next(item for item in economy.obligations if item.kind is ObligationKind.LOAN_FEE)
        self.assertEqual((fee.amount_minor, fee.debtor_id, fee.creditor_id),
                         (25_000, "club:borrower", "club:owner"))
        owner_squad = next(item for item in registered.squads if item.club_id == "club:owner")
        borrower_squad = next(item for item in registered.squads if item.club_id == "club:borrower")
        self.assertIn("player:loaned", owner_squad.loan_reserve_player_ids)
        self.assertIn("player:loaned", borrower_squad.registered_player_ids)

        same_book, same_ledger, same_regs = activate_loan(
            active, economy, registered, terms.loan_id, clearance(), day(1, 10),
        )
        self.assertEqual((same_book, same_ledger, same_regs), (active, economy, registered))

        accrued, with_share, share = accrue_loan_wage_share(active, economy, terms.loan_id, day(1, 15))
        self.assertIsNotNone(share)
        assert share is not None
        self.assertEqual(share.amount_minor, 5_000)
        self.assertEqual(share.kind, ObligationKind.LOAN_WAGE_CONTRIBUTION)
        replayed, replayed_ledger, replayed_share = accrue_loan_wage_share(
            accrued, with_share, terms.loan_id, day(1, 15),
        )
        self.assertEqual((replayed, replayed_ledger, replayed_share), (accrued, with_share, share))
        with self.assertRaisesRegex(ValueError, "registration or fee evidence"):
            activate_loan(active, replace(economy, obligations=()), registered,
                          terms.loan_id, clearance(), day(1, 10))
        paid, _ = settle_obligation(with_share, share.obligation_id, day(1, 15))
        self.assertEqual(paid.cash_balance_minor("club:borrower", "GBP"), 495_000)
        self.assertEqual(paid.cash_balance_minor("club:owner", "GBP"), 505_000)

    def test_injury_or_expired_medical_clearance_blocks_without_partial_mutation(self) -> None:
        book = agreed_loan()
        state = ledger()
        regs = registrations()
        injury = InjuryEpisode("injury:strain", "player:loaned", "event:match-exposure", day(1, 8))
        not_fit = clearance(day(1, 9), episodes=(injury,))
        self.assertEqual(not_fit.outcome, MedicalOutcome.NOT_CLEARED)
        with self.assertRaisesRegex(ValueError, "no current clear medical assessment"):
            activate_loan(book, state, regs, "loan:one", not_fit, day(1, 10))
        self.assertEqual(loan_status(book, "loan:one"), LoanStatus.AGREED)
        with self.assertRaisesRegex(ValueError, "no current clear medical assessment"):
            activate_loan(book, state, regs, "loan:one", clearance(day(1, 1)), day(1, 20))
        self.assertEqual(state.obligations, ())
        self.assertEqual(regs.squads[0].loan_reserve_player_ids, ())
        with self.assertRaisesRegex(ValueError, "ID does not match"):
            replace(clearance(), expires_on=day(2, 1))

    def test_registration_failure_leaves_agreement_unactivated(self) -> None:
        book = agreed_loan()
        full = registrations()
        policy = full.policies[0]
        from dataclasses import replace
        from games.touchline.esb.world.registration import PlayerTrainingRecord
        extra_id = "player:borrower-extra"
        full = RegistrationBook(
            (replace(policy, maximum_squad_size=2, maximum_non_homegrown_players=2),),
            full.player_training + (PlayerTrainingRecord(extra_id, ("club:borrower",)),),
            tuple(replace(squad, registered_player_ids=squad.registered_player_ids + (extra_id,))
                  if squad.club_id == "club:borrower" else squad for squad in full.squads),
        )
        with self.assertRaisesRegex(ValueError, "registration failed"):
            activate_loan(book, ledger(), full, "loan:one", clearance(), day(1, 10))
        self.assertEqual(loan_status(book, "loan:one"), LoanStatus.AGREED)
        self.assertEqual(len(ledger().obligations), 0)

    def test_closed_registration_window_blocks_loan_without_partial_mutation(self) -> None:
        book = agreed_loan()
        state = ledger()
        regs = registrations(closes_on=day(1, 9))
        with self.assertRaisesRegex(ValueError, "registration failed.*window_closed"):
            activate_loan(book, state, regs, "loan:one", clearance(), day(1, 10))
        self.assertEqual(loan_status(book, "loan:one"), LoanStatus.AGREED)
        self.assertEqual(state.obligations, ())
        self.assertEqual(regs.squads, registrations(closes_on=day(1, 9)).squads)

    def test_rejection_and_offer_expiry_are_terminal(self) -> None:
        terms = proposal(purchase=False, recall_from=None)
        book = propose_loan(LoanBook(), terms, ledger())
        book = respond_to_loan(book, terms.loan_id, terms.owner_club_id, False, day(1, 3))
        self.assertEqual(loan_status(book, terms.loan_id), LoanStatus.REJECTED)
        with self.assertRaisesRegex(ValueError, "no longer awaiting consent"):
            respond_to_loan(book, terms.loan_id, terms.player_id, True, day(1, 4))

        expired_terms = replace_proposal_dates(terms, loan_id="loan:expired", expires_on=day(1, 4))
        expired = propose_loan(LoanBook(), expired_terms, ledger())
        expired = respond_to_loan(expired, expired_terms.loan_id,
                                  expired_terms.owner_club_id, True, day(1, 3))
        expired = expire_loan_proposals(expired, day(1, 5))
        self.assertEqual(loan_status(expired, expired_terms.loan_id), LoanStatus.OFFER_EXPIRED)
        with self.assertRaisesRegex(ValueError, "no longer awaiting consent"):
            respond_to_loan(expired, expired_terms.loan_id,
                            expired_terms.player_id, True, day(1, 5))

    def test_recall_restores_registration_once_and_stops_later_wage_share(self) -> None:
        book, state, regs = activate_fixture()
        with self.assertRaisesRegex(ValueError, "active registration state"):
            recall_loan(book, registrations(), "loan:one", "club:owner", day(2, 1))
        accrued, state, prior_share = accrue_loan_wage_share(
            book, state, "loan:one", day(1, 15),
        )
        self.assertIsNotNone(prior_share)
        with self.assertRaisesRegex(ValueError, "unavailable"):
            recall_loan(accrued, regs, "loan:one", "club:owner", day(1, 31))
        recalled, returned_regs = recall_loan(accrued, regs, "loan:one", "club:owner", day(2, 1))
        self.assertEqual(
            activate_loan(recalled, state, returned_regs, "loan:one", clearance(), day(1, 10)),
            (recalled, state, returned_regs),
        )
        self.assertEqual(loan_status(recalled, "loan:one"), LoanStatus.RECALLED)
        self.assertEqual(
            recall_loan(recalled, returned_regs, "loan:one", "club:owner", day(2, 1)),
            (recalled, returned_regs),
        )
        with self.assertRaisesRegex(ValueError, "conflicts with its completed registration move"):
            recall_loan(recalled, regs, "loan:one", "club:owner", day(2, 1))
        owner = next(item for item in returned_regs.squads if item.club_id == "club:owner")
        borrower = next(item for item in returned_regs.squads if item.club_id == "club:borrower")
        self.assertIn("player:loaned", owner.registered_player_ids)
        self.assertNotIn("player:loaned", owner.loan_reserve_player_ids)
        self.assertNotIn("player:loaned", borrower.registered_player_ids)
        with self.assertRaisesRegex(ValueError, "only accrues while"):
            accrue_loan_wage_share(recalled, state, "loan:one", day(2, 15))
        with self.assertRaisesRegex(ValueError, "only an active loan"):
            recall_loan(recalled, returned_regs, "loan:one", "club:owner", day(2, 2))
        replay = accrue_loan_wage_share(recalled, state, "loan:one", day(1, 15))
        self.assertEqual(replay, (recalled, state, prior_share))

    def test_natural_return_releases_reserved_registration_at_exclusive_end(self) -> None:
        book, _, regs = activate_fixture(purchase=False, recall_from=None)
        with self.assertRaisesRegex(ValueError, "before its agreed end"):
            return_loan(book, regs, "loan:one", day(3, 9))
        with self.assertRaisesRegex(ValueError, "active registration state"):
            return_loan(book, registrations(), "loan:one", day(3, 10))
        returned, state = return_loan(book, regs, "loan:one", day(3, 10))
        self.assertEqual(loan_status(returned, "loan:one"), LoanStatus.EXPIRED)
        owner = next(item for item in state.squads if item.club_id == "club:owner")
        self.assertIn("player:loaned", owner.registered_player_ids)

    def test_purchase_transfers_employment_and_registration_and_respects_past_payroll(self) -> None:
        book, state, regs = activate_fixture()
        loan_registrations = regs
        state = run_payroll(state, day(1, 15))
        purchased, state, regs, new_contract = exercise_purchase_option(
            book, state, regs, "loan:one", clearance(day(1, 31)), day(2, 1),
        )
        self.assertEqual(loan_status(purchased, "loan:one"), LoanStatus.PURCHASED)
        transfer = state.contract_transfers[0]
        self.assertEqual(transfer.from_contract_id, "contract:owner-player")
        self.assertEqual(transfer.to_contract_id, new_contract.contract_id)
        self.assertEqual(new_contract.club_id, "club:borrower")
        self.assertEqual(employment_at(state, "player:loaned", day(1, 15)).club_id, "club:owner")
        self.assertEqual(employment_at(state, "player:loaned", day(2, 1)), new_contract)
        self.assertEqual(loads(dumps(state), EconomyLedger), state)
        self.assertEqual(new_contract.wage_per_payroll_minor, 12_000)
        self.assertEqual(len(state.payroll_runs), 1)
        self.assertEqual(len(state.payroll_runs[0].obligation_ids), 1)
        state = run_payroll(state, day(2, 1))
        wage = next(item for item in state.obligations if item.kind is ObligationKind.PLAYER_WAGE
                    and item.due_on == day(2, 1))
        self.assertEqual(wage.debtor_id, "club:borrower")
        purchase_fee = next(item for item in state.obligations if item.kind is ObligationKind.PURCHASE_FEE)
        self.assertEqual(purchase_fee.amount_minor, 40_000)
        self.assertEqual(
            scheduled_loan_obligation_ids(purchased, "loan:one"),
            (next(item.obligation_id for item in state.obligations
                  if item.kind is ObligationKind.LOAN_FEE), purchase_fee.obligation_id),
        )
        owner = next(item for item in regs.squads if item.club_id == "club:owner")
        borrower = next(item for item in regs.squads if item.club_id == "club:borrower")
        self.assertNotIn("player:loaned", owner.loan_reserve_player_ids)
        self.assertIn("player:loaned", borrower.registered_player_ids)
        self.assertEqual(sum(item.source_contract_id == "contract:owner-player"
                             for item in state.obligations), 1)

        replay = exercise_purchase_option(
            purchased, state, regs, "loan:one", clearance(day(1, 31)), day(2, 1),
        )
        self.assertEqual(replay, (purchased, state, regs, new_contract))
        self.assertEqual(
            activate_loan(purchased, state, regs, "loan:one", clearance(), day(1, 10)),
            (purchased, state, regs),
        )
        with self.assertRaisesRegex(ValueError, "conflicts with its completed transaction"):
            exercise_purchase_option(
                purchased, state, loan_registrations, "loan:one",
                clearance(day(1, 31)), day(2, 1),
            )

    def test_purchase_keeps_registration_after_window_closes(self) -> None:
        terms = proposal()
        book = agreed_loan(terms=terms)
        book, state, regs = activate_loan(
            book, ledger(), registrations(closes_on=day(1, 20)),
            terms.loan_id, clearance(), day(1, 10),
        )
        purchased, _, _, _ = exercise_purchase_option(
            book, state, regs, terms.loan_id, clearance(day(1, 31)), day(2, 1),
        )
        self.assertEqual(loan_status(purchased, terms.loan_id), LoanStatus.PURCHASED)

    def test_purchase_is_blocked_by_future_owner_payroll_snapshot(self) -> None:
        book, state, regs = activate_fixture()
        future_payroll = run_payroll(state, day(2, 2))
        with self.assertRaisesRegex(ValueError, "future payroll snapshot"):
            exercise_purchase_option(book, future_payroll, regs, "loan:one",
                                     clearance(day(2, 1)), day(2, 1))

    def test_loan_and_purchase_contracts_survive_strict_round_trip(self) -> None:
        book, _, _ = activate_fixture()
        encoded = book.to_json()
        restored = LoanBook.from_json(encoded)
        self.assertEqual(restored, book)
        self.assertEqual(restored.to_json(), encoded)
        activation = next(item for item in book.events if item.kind is LoanEventKind.ACTIVATED)
        with self.assertRaisesRegex(ValueError, "ID does not match"):
            replace(activation, medical_assessment_id="medical:altered")
        data = json.loads(encoded)
        data["payload"]["events"] = [
            item for item in data["payload"]["events"] if item["kind"] != "activated"
        ]
        with self.assertRaises((SerializationError, ValueError)):
            loads(json.dumps(data), LoanBook)

    def test_terminal_loan_cannot_be_resurrected_by_a_later_activation_event(self) -> None:
        active, _, regs = activate_fixture()
        recalled, _ = recall_loan(active, regs, "loan:one", "club:owner", day(2, 1))
        terms = next(item for item in recalled.proposals if item.loan_id == "loan:one")
        original_activation = next(
            item for item in recalled.events if item.kind is LoanEventKind.ACTIVATED
        )
        resurrection = _event(
            terms, terms.borrower_club_id, day(2, 2), LoanEventKind.ACTIVATED,
            assessment_id=clearance(day(2, 2)).assessment_id,
            registration_checks=original_activation.registration_check_ids,
        )
        with self.assertRaisesRegex(ValueError, "activation requires both consents"):
            LoanBook(recalled.proposals, recalled.events + (resurrection,))

    def test_persisted_wage_share_event_requires_its_deterministic_obligation_id(self) -> None:
        active, _, _ = activate_fixture()
        terms = next(item for item in active.proposals if item.loan_id == "loan:one")
        forged_reference = _event(
            terms, terms.borrower_club_id, day(1, 15),
            LoanEventKind.WAGE_SHARE_SCHEDULED, obligation_id="obligation:unrelated",
        )
        with self.assertRaisesRegex(ValueError, "deterministic obligation ID"):
            LoanBook(active.proposals, active.events + (forged_reference,))

    def test_fresh_process_loan_lifecycle_is_deterministic(self) -> None:
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        command = [sys.executable, "-m", "games.touchline.checks.loan_probe"]
        first = subprocess.run(command, cwd=ROOT, env=env,
                               capture_output=True, text=True, check=True)
        second = subprocess.run(command, cwd=ROOT, env=env,
                                capture_output=True, text=True, check=True)
        self.assertEqual(first.stdout, second.stdout)
        result = json.loads(first.stdout)
        self.assertEqual(result["loan_status"], "expired")
        self.assertEqual(result["effective_employer_after_return"], "club:probe-owner")
        self.assertEqual(len(result["event_ids"]), 7)


def replace_proposal_dates(proposal: LoanProposal, *, loan_id: str,
                           expires_on: WorldDate) -> LoanProposal:
    from dataclasses import replace
    return replace(proposal, loan_id=loan_id, expires_on=expires_on, purchase_option=None)


def activate_fixture(*, purchase: bool = True,
                     recall_from: WorldDate | None = day(2, 1)
                     ) -> tuple[LoanBook, EconomyLedger, RegistrationBook]:
    terms = proposal(purchase=purchase, recall_from=recall_from)
    book = agreed_loan(terms=terms)
    return activate_loan(book, ledger(), registrations(), terms.loan_id,
                         clearance(), day(1, 10))


class EmploymentTransferTests(unittest.TestCase):
    def test_persisted_contract_transfer_cycles_are_rejected(self) -> None:
        contract_a = EmploymentContract(
            "contract:cycle-a", "club:cycle-a", "player:cycle",
            day(1, 1), day(1, 1), WorldDate(date(2027, 1, 1)), "GBP", 8_000,
        )
        contract_b = EmploymentContract(
            "contract:cycle-b", "club:cycle-b", "player:cycle",
            day(1, 1), day(1, 1), WorldDate(date(2027, 1, 1)), "GBP", 9_000,
        )
        transfer_ab = ContractTransfer(
            derive_id("employment-transfer", "p15c-contract-novation-v1",
                      contract_a.contract_id, contract_b.contract_id, day(1, 1).isoformat),
            contract_a.contract_id, contract_b.contract_id, day(1, 1),
        )
        transfer_ba = ContractTransfer(
            derive_id("employment-transfer", "p15c-contract-novation-v1",
                      contract_b.contract_id, contract_a.contract_id, day(1, 1).isoformat),
            contract_b.contract_id, contract_a.contract_id, day(1, 1),
        )
        valid = EconomyLedger(contracts=(contract_a, contract_b),
                              contract_transfers=(transfer_ab,))
        self.assertEqual(employment_at(valid, "player:cycle", day(1, 1)), contract_b)
        with self.assertRaisesRegex(ValueError, "cannot contain cycles"):
            EconomyLedger(contracts=(contract_a, contract_b),
                          contract_transfers=(transfer_ab, transfer_ba))
        payload = json.loads(dumps(valid))
        payload["payload"]["contract_transfers"].append(
            json.loads(dumps(transfer_ba))["payload"]
        )
        with self.assertRaisesRegex(SerializationError, "domain contract"):
            loads(json.dumps(payload), EconomyLedger)

    def test_transfer_preserves_old_payroll_and_rejects_overlapping_unlinked_contract(self) -> None:
        state = run_payroll(ledger(), day(1, 15))
        next_contract = EmploymentContract(
            "contract:buyer-player", "club:borrower", "player:loaned",
            day(2, 1), day(2, 1), WorldDate(date(2027, 2, 1)), "GBP", 12_000,
        )
        updated, transfer = transfer_employment(
            state, "contract:owner-player", next_contract, loan_book=LoanBook(),
        )
        self.assertEqual(updated.contract_transfers, (transfer,))
        with self.assertRaisesRegex(ValueError, "ID does not match"):
            replace(transfer, completed_on=day(2, 2))
        self.assertIs(run_payroll(updated, day(1, 15)), updated)
        after = run_payroll(updated, day(2, 1))
        self.assertEqual(after.obligations[-1].debtor_id, "club:borrower")
        self.assertEqual(len(after.payroll_runs[-1].obligation_ids), 1)
        with self.assertRaisesRegex(ValueError, "overlapping employment contracts require"):
            EconomyLedger(contracts=state.contracts + (next_contract,))

    def test_transfer_cannot_rewrite_a_future_payroll_or_wage_obligation(self) -> None:
        state = run_payroll(ledger(), day(2, 5))
        next_contract = EmploymentContract(
            "contract:future-transfer", "club:borrower", "player:loaned",
            day(2, 1), day(2, 1), WorldDate(date(2027, 2, 1)), "GBP", 12_000,
        )
        with self.assertRaisesRegex(ValueError, "future payroll snapshot"):
            transfer_employment(
                state, "contract:owner-player", next_contract, loan_book=LoanBook(),
            )

    def test_economy_transfer_rejects_live_loan_and_preserves_transfer_chronology(self) -> None:
        active, state, _ = activate_fixture()
        third_club = EmploymentContract(
            "contract:third-player", "club:third", "player:loaned",
            day(2, 1), day(2, 1), WorldDate(date(2027, 2, 1)), "GBP", 11_000,
        )
        with self.assertRaisesRegex(ValueError, "live loan employment"):
            transfer_employment(
                state, "contract:owner-player", third_club, loan_book=active,
            )

        other_owner = EmploymentContract(
            "contract:other-owner", "club:other-owner", "player:other",
            day(1, 1), day(1, 1), WorldDate(date(2027, 1, 1)), "GBP", 7_000,
        )
        initial = EconomyLedger(contracts=(contract(), other_owner))
        later_contract = EmploymentContract(
            "contract:later-buyer", "club:buyer", "player:loaned",
            day(2, 1), day(2, 1), WorldDate(date(2027, 2, 1)), "GBP", 12_000,
        )
        moved_later, later_transfer = transfer_employment(
            initial, "contract:owner-player", later_contract, loan_book=LoanBook(),
        )
        earlier_contract = EmploymentContract(
            "contract:earlier-buyer", "club:earlier", "player:other",
            day(1, 20), day(1, 20), WorldDate(date(2027, 1, 20)), "GBP", 8_000,
        )
        with self.assertRaisesRegex(ValueError, "transfers must retain calendar order"):
            transfer_employment(
                moved_later, "contract:other-owner", earlier_contract,
                loan_book=LoanBook(),
            )

        early, early_transfer = transfer_employment(
            initial, "contract:other-owner", earlier_contract, loan_book=LoanBook(),
        )
        chronological, _ = transfer_employment(
            early, "contract:owner-player", later_contract, loan_book=LoanBook(),
        )
        with self.assertRaisesRegex(ValueError, "transfers must retain calendar order"):
            EconomyLedger(
                chronological.accounts, chronological.contracts, chronological.obligations,
                chronological.entries, chronological.payroll_runs,
                (later_transfer, early_transfer),
            )


if __name__ == "__main__":
    unittest.main()
