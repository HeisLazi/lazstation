from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from datetime import date
from pathlib import Path

from games.touchline.esb.economy.ledger import (
    CashAccount,
    ContractStatus,
    EconomyLedger,
    EmploymentContract,
    ObligationKind,
    PaymentObligation,
    add_account,
    add_obligation,
    contract_status,
    run_payroll,
    settle_obligation,
)
from games.touchline.esb.serialization import SerializationError, dumps, loads
from games.touchline.esb.time import WorldDate

ROOT = Path(__file__).resolve().parents[3]


def day(value: int) -> WorldDate:
    return WorldDate(date(2026, 10, value))


def contract(
    contract_id: str = "contract:player-a",
    club_id: str = "club:human",
    player_id: str = "player:a",
    *,
    start: int = 1,
    expiry: int = 31,
    wage: int = 500,
    currency: str = "GBP",
) -> EmploymentContract:
    return EmploymentContract(
        contract_id, club_id, player_id, day(1), day(start), day(expiry),
        currency, wage,
    )


def payroll_state(*, cash: int = 10_000, player_cash: int = 0) -> EconomyLedger:
    state = EconomyLedger(contracts=(contract(),))
    state = add_account(state, CashAccount("club:human", "GBP", cash))
    state = add_account(state, CashAccount("player:a", "GBP", player_cash))
    return state


class ContractAndPayrollTests(unittest.TestCase):
    def test_expiry_is_exclusive_and_overlapping_employment_is_rejected(self) -> None:
        player_contract = contract(expiry=8)
        self.assertEqual(contract_status(player_contract, day(1)), ContractStatus.ACTIVE)
        self.assertEqual(contract_status(player_contract, day(7)), ContractStatus.ACTIVE)
        self.assertEqual(contract_status(player_contract, day(8)), ContractStatus.EXPIRED)
        self.assertEqual(
            contract_status(contract(start=9, expiry=12), day(8)),
            ContractStatus.NOT_STARTED,
        )

        with self.assertRaisesRegex(ValueError, "overlapping employment"):
            EconomyLedger(contracts=(
                contract(expiry=12),
                contract("contract:second", "club:other", start=11, expiry=20),
            ))
        sequential = EconomyLedger(contracts=(
            contract(expiry=12),
            contract("contract:second", "club:other", start=12, expiry=20),
        ))
        self.assertEqual(len(sequential.contracts), 2)

    def test_payroll_is_explicit_dated_and_same_date_retries_are_exactly_once(self) -> None:
        expired = contract("contract:expired", "club:human", "player:expired", expiry=6)
        state = EconomyLedger(contracts=(contract(), expired))
        for account in (
            CashAccount("club:human", "GBP", 10_000),
            CashAccount("player:a", "GBP", 0),
            CashAccount("player:expired", "GBP", 0),
        ):
            state = add_account(state, account)

        # Fixtures earlier in this same payroll period are not payroll inputs.
        fixture_dates = (day(2), day(5))
        self.assertEqual(len(fixture_dates), 2)
        self.assertEqual(state.obligations, ())
        first = run_payroll(state, day(6))
        self.assertEqual(len(first.payroll_runs), 1)
        self.assertEqual(len(first.obligations), 1)
        self.assertEqual(first.obligations[0].creditor_id, "player:a")
        self.assertEqual(first.obligations[0].amount_minor, 500)
        self.assertEqual(first.obligations[0].due_on, day(6))
        self.assertIs(run_payroll(first, day(6)), first)
        self.assertEqual(run_payroll(first, day(7)).payroll_runs[-1].payroll_date, day(7))

        settled, entry = settle_obligation(first, first.obligations[0].obligation_id, day(6))
        self.assertEqual(settled.cash_balance_minor("club:human", "GBP"), 9_500)
        self.assertEqual(settled.cash_balance_minor("player:a", "GBP"), 500)
        self.assertEqual(entry.amount_minor, 500)
        self.assertEqual(entry.debtor_id, "club:human")
        self.assertEqual(entry.creditor_id, "player:a")
        retried, replayed_entry = settle_obligation(
            settled, first.obligations[0].obligation_id, day(6)
        )
        self.assertIs(retried, settled)
        self.assertIs(replayed_entry, entry)
        self.assertEqual(len(retried.entries), 1)
        with self.assertRaisesRegex(ValueError, "retry date conflicts"):
            settle_obligation(settled, first.obligations[0].obligation_id, day(7))

    def test_serialized_payroll_cannot_point_at_a_non_wage_obligation(self) -> None:
        state = run_payroll(payroll_state(), day(6))
        wage = state.obligations[0]
        mislabeled = PaymentObligation(
            wage.obligation_id, wage.debtor_id, "club:vendor", wage.currency,
            wage.amount_minor, wage.due_on, ObligationKind.OTHER,
        )
        with self.assertRaisesRegex(ValueError, "does not match its contract snapshot"):
            EconomyLedger(
                state.accounts, state.contracts, (mislabeled,), (), state.payroll_runs,
            )

    def test_contract_wage_cannot_bypass_an_explicit_payroll_run(self) -> None:
        state = EconomyLedger(contracts=(contract(),))
        wage = PaymentObligation(
            "obligation:manual-wage", "club:human", "player:a", "GBP",
            500, day(6), ObligationKind.PLAYER_WAGE, "contract:player-a",
        )
        with self.assertRaisesRegex(ValueError, "only by an explicit payroll run"):
            add_obligation(state, wage)
        with self.assertRaisesRegex(ValueError, "belong to an explicit payroll run"):
            EconomyLedger(state.accounts, state.contracts, (wage,), (), ())

    def test_human_and_ai_clubs_use_identical_payroll_and_settlement_rules(self) -> None:
        outcomes = []
        for club_id, player_id in (("club:human", "player:human"), ("club:ai", "player:ai")):
            employment = contract(
                f"contract:{club_id}", club_id, player_id, wage=1_237,
            )
            state = EconomyLedger(contracts=(employment,))
            state = add_account(state, CashAccount(club_id, "GBP", 9_000))
            state = add_account(state, CashAccount(player_id, "GBP", 0))
            scheduled = run_payroll(state, day(6))
            paid, _ = settle_obligation(scheduled, scheduled.obligations[0].obligation_id, day(6))
            outcomes.append((paid.cash_balance_minor(club_id, "GBP"), paid.cash_balance_minor(player_id, "GBP")))
        self.assertEqual(outcomes, [(7_763, 1_237), (7_763, 1_237)])


class ObligationLedgerTests(unittest.TestCase):
    def test_installment_is_scheduled_and_posted_once_with_balanced_minor_units(self) -> None:
        state = EconomyLedger()
        for account in (
            CashAccount("club:buyer", "GBP", 8_000),
            CashAccount("club:seller", "GBP", 100),
        ):
            state = add_account(state, account)
        installment = PaymentObligation(
            "obligation:installment-1", "club:buyer", "club:seller", "GBP",
            1_375, day(6), ObligationKind.TRANSFER_INSTALLMENT,
        )
        scheduled = add_obligation(state, installment)
        self.assertIs(add_obligation(scheduled, installment), scheduled)
        with self.assertRaisesRegex(ValueError, "conflicting terms"):
            add_obligation(scheduled, PaymentObligation(
                installment.obligation_id, installment.debtor_id,
                installment.creditor_id, installment.currency, 1_376,
                installment.due_on, installment.kind,
            ))
        with self.assertRaisesRegex(ValueError, "not due yet"):
            settle_obligation(scheduled, installment.obligation_id, day(5))

        paid, entry = settle_obligation(scheduled, installment.obligation_id, day(6))
        self.assertEqual(paid.cash_balance_minor("club:buyer", "GBP"), 6_625)
        self.assertEqual(paid.cash_balance_minor("club:seller", "GBP"), 1_475)
        self.assertEqual(sum((6_625, 1_475)), sum((8_000, 100)))
        self.assertEqual(len(paid.entries), 1)
        retried, prior = settle_obligation(paid, installment.obligation_id, day(6))
        self.assertIs(retried, paid)
        self.assertEqual(prior, entry)

    def test_insufficient_cash_leaves_obligation_and_ledger_unchanged(self) -> None:
        state = EconomyLedger()
        state = add_account(state, CashAccount("club:poor", "GBP", 499))
        state = add_account(state, CashAccount("player:a", "GBP", 0))
        obligation = PaymentObligation(
            "obligation:unpaid-wage", "club:poor", "player:a", "GBP",
            500, day(6), ObligationKind.OTHER,
        )
        state = add_obligation(state, obligation)
        with self.assertRaisesRegex(ValueError, "insufficient cash"):
            settle_obligation(state, obligation.obligation_id, day(6))
        self.assertEqual(state.entries, ())
        self.assertEqual(state.cash_balance_minor("club:poor", "GBP"), 499)
        self.assertEqual(len(state.obligations), 1)

    def test_settlement_history_cannot_be_backdated_after_later_cash_movements(self) -> None:
        state = EconomyLedger()
        for account in (
            CashAccount("club:buyer", "GBP", 100),
            CashAccount("club:seller", "GBP", 100),
            CashAccount("player:a", "GBP", 0),
        ):
            state = add_account(state, account)
        incoming = PaymentObligation(
            "obligation:incoming", "club:seller", "club:buyer", "GBP",
            100, day(6), ObligationKind.OTHER,
        )
        outgoing = PaymentObligation(
            "obligation:outgoing", "club:buyer", "player:a", "GBP",
            100, day(6), ObligationKind.OTHER,
        )
        state = add_obligation(add_obligation(state, incoming), outgoing)
        later = settle_obligation(state, outgoing.obligation_id, day(7))[0]
        with self.assertRaisesRegex(ValueError, "before the latest economy event date"):
            settle_obligation(later, incoming.obligation_id, day(6))
        corrected = settle_obligation(later, incoming.obligation_id, day(8))[0]
        self.assertEqual(corrected.cash_balance_minor("club:buyer", "GBP"), 100)
        self.assertEqual([entry.settled_on for entry in corrected.entries], [day(7), day(8)])

    def test_payroll_run_also_advances_economy_chronology(self) -> None:
        state = payroll_state()
        state = add_account(state, CashAccount("club:vendor", "GBP", 0))
        state = run_payroll(state, day(6))
        past_due = PaymentObligation(
            "obligation:past-due-cost", "club:human", "club:vendor", "GBP",
            100, day(5), ObligationKind.OPERATING_COST,
        )
        state = add_obligation(state, past_due)
        with self.assertRaisesRegex(ValueError, "latest economy event date"):
            settle_obligation(state, past_due.obligation_id, day(5))
        settled, _ = settle_obligation(state, past_due.obligation_id, day(6))
        self.assertEqual(settled.cash_balance_minor("club:human", "GBP"), 9_900)
        self.assertEqual(settled.cash_balance_minor("club:vendor", "GBP"), 100)

    def test_contract_wage_provenance_and_cash_accounts_are_required_at_settlement(self) -> None:
        state = EconomyLedger(contracts=(contract(),))
        state = add_account(state, CashAccount("club:human", "GBP", 10_000))
        state = run_payroll(state, day(6))
        with self.assertRaisesRegex(ValueError, "both debtor and creditor"):
            settle_obligation(state, state.obligations[0].obligation_id, day(6))

        with self.assertRaisesRegex(ValueError, "requires its employment contract"):
            PaymentObligation(
                "obligation:orphan-wage", "club:human", "player:a", "GBP",
                500, day(6), ObligationKind.PLAYER_WAGE,
            )
        with self.assertRaisesRegex(ValueError, "only a player wage"):
            PaymentObligation(
                "obligation:wrong-source", "club:human", "player:a", "GBP",
                500, day(6), ObligationKind.OTHER, "contract:player-a",
            )

    def test_records_round_trip_and_corrupt_ledger_references_fail(self) -> None:
        state = run_payroll(payroll_state(), day(6))
        paid, _ = settle_obligation(state, state.obligations[0].obligation_id, day(6))
        self.assertEqual(loads(dumps(paid), EconomyLedger), paid)
        with self.assertRaises(SerializationError):
            loads(dumps(paid).replace('"amount_minor":500', '"amount_minor":501'), EconomyLedger)

    def test_probe_is_fresh_process_deterministic_and_economy_import_is_headless(self) -> None:
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        command = [sys.executable, "-m", "games.touchline.checks.economy_probe"]
        first = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, check=True)
        second = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, check=True)
        self.assertEqual(first.stdout, second.stdout)
        summary = json.loads(first.stdout)
        self.assertEqual(summary["payroll_runs"], 1)
        self.assertEqual(summary["ledger_entries"], 2)
        self.assertEqual(summary["club_balance_minor"], 7_125)
        self.assertEqual(summary["player_balance_minor"], 500)

        code = """
import builtins
def blocked(*args, **kwargs):
    raise AssertionError('economy import attempted file access')
builtins.open = blocked
import games.touchline.esb.economy
import games.touchline.esb.economy.ledger
"""
        subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, check=True)


if __name__ == "__main__":
    unittest.main()
