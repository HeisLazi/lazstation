"""Fresh-process determinism probe for P15a payroll and obligations."""

from __future__ import annotations

import json
from datetime import date

from games.touchline.esb.economy.ledger import (
    CashAccount,
    EconomyLedger,
    EmploymentContract,
    ObligationKind,
    PaymentObligation,
    add_account,
    add_obligation,
    run_payroll,
    settle_obligation,
)
from games.touchline.esb.serialization import dumps
from games.touchline.esb.time import WorldDate


def run_probe() -> dict[str, object]:
    payroll_day = WorldDate(date(2026, 10, 6))
    contract = EmploymentContract(
        "contract:probe-player", "club:probe", "player:probe",
        WorldDate(date(2026, 9, 1)), WorldDate(date(2026, 9, 1)),
        WorldDate(date(2027, 6, 1)), "GBP", 500,
    )
    ledger = EconomyLedger(contracts=(contract,))
    ledger = add_account(ledger, CashAccount("club:probe", "GBP", 8_000))
    ledger = add_account(ledger, CashAccount("player:probe", "GBP", 0))
    ledger = add_account(ledger, CashAccount("club:vendor", "GBP", 0))
    ledger = run_payroll(ledger, payroll_day)
    ledger = run_payroll(ledger, payroll_day)
    installment = PaymentObligation(
        "obligation:probe-installment", "club:probe", "club:vendor", "GBP",
        375, payroll_day, ObligationKind.TRANSFER_INSTALLMENT,
    )
    ledger = add_obligation(ledger, installment)
    for obligation in ledger.obligations:
        ledger, _ = settle_obligation(ledger, obligation.obligation_id, payroll_day)
    for obligation in ledger.obligations:
        ledger, _ = settle_obligation(ledger, obligation.obligation_id, payroll_day)
    return {
        "payroll_runs": len(ledger.payroll_runs),
        "ledger_entries": len(ledger.entries),
        "club_balance_minor": ledger.cash_balance_minor("club:probe", "GBP"),
        "player_balance_minor": ledger.cash_balance_minor("player:probe", "GBP"),
        "ledger": json.loads(dumps(ledger)),
    }


def main() -> None:
    print(json.dumps(run_probe(), ensure_ascii=False, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
