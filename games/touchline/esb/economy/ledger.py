"""Dated contracts, obligations, payroll and double-entry cash settlement.

All amounts are positive integer minor units on obligations and transactions.
Balances are projections from an opening balance and signed ledger entries.
This package deliberately has no calendar runner: a caller invokes payroll on
an explicit payroll date, and retries for that date are recorded once.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import Enum

from games.touchline.esb.ids import derive_id, validate_id
from games.touchline.esb.time import WorldDate

_CURRENCY_RE = re.compile(r"[A-Z]{3}\Z")


def _currency(value: str) -> str:
    if not isinstance(value, str) or not _CURRENCY_RE.fullmatch(value):
        raise ValueError("currency must be a three-letter uppercase code")
    return value


def _minor(value: int, label: str, *, allow_zero: bool = True) -> None:
    if type(value) is not int or value < (0 if allow_zero else 1):
        qualifier = "non-negative" if allow_zero else "positive"
        raise ValueError(f"{label} must be a {qualifier} integer number of minor units")


class ObligationKind(str, Enum):
    PLAYER_WAGE = "player_wage"
    TRANSFER_INSTALLMENT = "transfer_installment"
    LOAN_FEE = "loan_fee"
    LOAN_WAGE_CONTRIBUTION = "loan_wage_contribution"
    PURCHASE_FEE = "purchase_fee"
    OPERATING_COST = "operating_cost"
    OTHER = "other"


class ContractStatus(str, Enum):
    NOT_STARTED = "not_started"
    ACTIVE = "active"
    EXPIRED = "expired"


@dataclass(frozen=True)
class CashAccount:
    """An entity's opening cash for one currency; no overdraft is implicit."""

    owner_id: str
    currency: str
    opening_balance_minor: int

    def __post_init__(self) -> None:
        validate_id(self.owner_id, kind="cash account owner ID")
        _currency(self.currency)
        _minor(self.opening_balance_minor, "opening balance")


@dataclass(frozen=True)
class EmploymentContract:
    """Player employment with an exclusive expiry date and period wage.

    Payroll pays one full period wage when the contract is active on the
    explicit payroll date. Partial-period proration is not modeled here.
    """

    contract_id: str
    club_id: str
    player_id: str
    agreed_on: WorldDate
    starts_on: WorldDate
    expires_on: WorldDate
    currency: str
    wage_per_payroll_minor: int

    def __post_init__(self) -> None:
        validate_id(self.contract_id, kind="employment contract ID")
        validate_id(self.club_id, kind="employment club ID")
        validate_id(self.player_id, kind="employment player ID")
        for label, value in (
            ("agreement date", self.agreed_on),
            ("contract start", self.starts_on),
            ("contract expiry", self.expires_on),
        ):
            if not isinstance(value, WorldDate):
                raise TypeError(f"employment {label} must be a WorldDate")
        if self.agreed_on > self.starts_on:
            raise ValueError("contract cannot be agreed after it starts")
        if self.expires_on <= self.starts_on:
            raise ValueError("contract expiry is exclusive and must follow its start")
        _currency(self.currency)
        _minor(self.wage_per_payroll_minor, "period wage", allow_zero=False)

    def active_on(self, day: WorldDate) -> bool:
        if not isinstance(day, WorldDate):
            raise TypeError("contract status requires a WorldDate")
        return self.starts_on <= day < self.expires_on


@dataclass(frozen=True)
class ContractTransfer:
    """A dated novation that moves an active employment to a new club."""

    transfer_id: str
    from_contract_id: str
    to_contract_id: str
    completed_on: WorldDate

    def __post_init__(self) -> None:
        validate_id(self.transfer_id, kind="employment transfer ID")
        validate_id(self.from_contract_id, kind="previous employment contract ID")
        validate_id(self.to_contract_id, kind="new employment contract ID")
        if self.from_contract_id == self.to_contract_id:
            raise ValueError("employment transfer must replace a distinct contract")
        if not isinstance(self.completed_on, WorldDate):
            raise TypeError("employment transfer requires its completion date")
        expected_id = derive_id(
            "employment-transfer", "p15c-contract-novation-v1",
            self.from_contract_id, self.to_contract_id, self.completed_on.isoformat,
        )
        if self.transfer_id != expected_id:
            raise ValueError("employment transfer ID does not match its dated contracts")


class ContractTerminationReason(str, Enum):
    RETIREMENT = "retirement"


@dataclass(frozen=True)
class ContractTermination:
    """Dated end of an employment contract before its agreed expiry."""

    termination_id: str
    contract_id: str
    terminated_on: WorldDate
    reason: ContractTerminationReason = ContractTerminationReason.RETIREMENT

    def __post_init__(self) -> None:
        validate_id(self.termination_id, kind="employment termination ID")
        validate_id(self.contract_id, kind="terminated employment contract ID")
        if not isinstance(self.terminated_on, WorldDate):
            raise TypeError("employment termination requires its effective date")
        if not isinstance(self.reason, ContractTerminationReason):
            raise TypeError("employment termination requires a registered reason")
        expected_id = derive_id(
            "contract-termination", "p16d-employment-termination-v1",
            self.contract_id, self.terminated_on.isoformat, self.reason.value,
        )
        if self.termination_id != expected_id:
            raise ValueError("employment termination ID does not match its contract and date")


@dataclass(frozen=True)
class PaymentObligation:
    """A dated payable between two entities, before cash changes hands."""

    obligation_id: str
    debtor_id: str
    creditor_id: str
    currency: str
    amount_minor: int
    due_on: WorldDate
    kind: ObligationKind
    source_contract_id: str | None = None

    def __post_init__(self) -> None:
        validate_id(self.obligation_id, kind="payment obligation ID")
        validate_id(self.debtor_id, kind="obligation debtor ID")
        validate_id(self.creditor_id, kind="obligation creditor ID")
        if self.debtor_id == self.creditor_id:
            raise ValueError("an obligation must transfer value between distinct entities")
        _currency(self.currency)
        _minor(self.amount_minor, "obligation amount", allow_zero=False)
        if not isinstance(self.due_on, WorldDate):
            raise TypeError("payment obligation requires a WorldDate")
        if not isinstance(self.kind, ObligationKind):
            raise TypeError("payment obligation kind must be registered")
        if self.source_contract_id is not None:
            validate_id(self.source_contract_id, kind="obligation source contract ID")
        if self.kind is ObligationKind.PLAYER_WAGE and self.source_contract_id is None:
            raise ValueError("player wage obligation requires its employment contract")
        if self.kind is not ObligationKind.PLAYER_WAGE and self.source_contract_id is not None:
            raise ValueError("only a player wage can cite an employment contract in P15a")


@dataclass(frozen=True)
class LedgerEntry:
    """One settled payment; its two parties receive equal/opposite postings."""

    entry_id: str
    obligation_id: str
    debtor_id: str
    creditor_id: str
    currency: str
    amount_minor: int
    settled_on: WorldDate

    def __post_init__(self) -> None:
        validate_id(self.entry_id, kind="ledger entry ID")
        validate_id(self.obligation_id, kind="ledger obligation ID")
        validate_id(self.debtor_id, kind="ledger debtor ID")
        validate_id(self.creditor_id, kind="ledger creditor ID")
        if self.debtor_id == self.creditor_id:
            raise ValueError("ledger payment requires distinct entities")
        _currency(self.currency)
        _minor(self.amount_minor, "ledger amount", allow_zero=False)
        if not isinstance(self.settled_on, WorldDate):
            raise TypeError("ledger settlement requires a WorldDate")


@dataclass(frozen=True)
class PayrollRun:
    """An exactly-once snapshot of active player contracts on a payroll date."""

    payroll_date: WorldDate
    active_contract_fingerprint: str
    obligation_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.payroll_date, WorldDate):
            raise TypeError("payroll run requires a WorldDate")
        if (not isinstance(self.active_contract_fingerprint, str)
                or not re.fullmatch(r"[0-9a-f]{64}", self.active_contract_fingerprint)):
            raise ValueError("payroll run requires a SHA-256 contract snapshot")
        if not isinstance(self.obligation_ids, tuple):
            raise TypeError("payroll obligation IDs must be an immutable tuple")
        for value in self.obligation_ids:
            validate_id(value, kind="payroll obligation ID")
        if len(self.obligation_ids) != len(set(self.obligation_ids)):
            raise ValueError("payroll run cannot repeat an obligation")


@dataclass(frozen=True)
class EconomyLedger:
    """Immutable economy snapshot with validated references and balances."""

    accounts: tuple[CashAccount, ...] = ()
    contracts: tuple[EmploymentContract, ...] = ()
    obligations: tuple[PaymentObligation, ...] = ()
    entries: tuple[LedgerEntry, ...] = ()
    payroll_runs: tuple[PayrollRun, ...] = ()
    contract_transfers: tuple[ContractTransfer, ...] = ()
    contract_terminations: tuple[ContractTermination, ...] = ()

    def __post_init__(self) -> None:
        groups = (
            ("accounts", self.accounts, CashAccount),
            ("contracts", self.contracts, EmploymentContract),
            ("obligations", self.obligations, PaymentObligation),
            ("entries", self.entries, LedgerEntry),
            ("payroll runs", self.payroll_runs, PayrollRun),
            ("contract transfers", self.contract_transfers, ContractTransfer),
            ("contract terminations", self.contract_terminations, ContractTermination),
        )
        for label, values, expected in groups:
            if not isinstance(values, tuple) or any(not isinstance(item, expected) for item in values):
                raise TypeError(f"economy {label} must be immutable {expected.__name__} records")

        account_keys = [(item.owner_id, item.currency) for item in self.accounts]
        if len(account_keys) != len(set(account_keys)):
            raise ValueError("cash account owner/currency pairs must be unique")
        contracts_by_id = {item.contract_id: item for item in self.contracts}
        if len(contracts_by_id) != len(self.contracts):
            raise ValueError("employment contract IDs must be unique")
        by_player: dict[str, list[EmploymentContract]] = {}
        for item in self.contracts:
            by_player.setdefault(item.player_id, []).append(item)
        transfers_by_old = {item.from_contract_id: item for item in self.contract_transfers}
        transfers_by_new = {item.to_contract_id: item for item in self.contract_transfers}
        transfer_dates_in_order = [item.completed_on for item in self.contract_transfers]
        if transfer_dates_in_order != sorted(transfer_dates_in_order):
            raise ValueError("employment transfers must retain calendar order")
        if len(transfers_by_old) != len(self.contract_transfers) or len(transfers_by_new) != len(self.contract_transfers):
            raise ValueError("an employment contract can transfer only once in either direction")
        if len({item.transfer_id for item in self.contract_transfers}) != len(self.contract_transfers):
            raise ValueError("employment transfer IDs must be unique")
        for origin in transfers_by_old:
            visited: set[str] = set()
            current = origin
            while current in transfers_by_old:
                if current in visited:
                    raise ValueError("employment transfer lineage cannot contain cycles")
                visited.add(current)
                current = transfers_by_old[current].to_contract_id
        transfer_dates: dict[str, WorldDate] = {}
        for transfer in self.contract_transfers:
            previous = contracts_by_id.get(transfer.from_contract_id)
            current = contracts_by_id.get(transfer.to_contract_id)
            if previous is None or current is None:
                raise ValueError("employment transfer references an absent contract")
            if (previous.player_id != current.player_id or previous.club_id == current.club_id
                    or previous.currency != current.currency or current.starts_on != transfer.completed_on
                    or current.agreed_on > transfer.completed_on or not previous.active_on(transfer.completed_on)):
                raise ValueError("employment transfer does not reconcile with both contract terms")
            transfer_dates[previous.contract_id] = transfer.completed_on
        terminations_by_contract = {
            item.contract_id: item for item in self.contract_terminations
        }
        if len(terminations_by_contract) != len(self.contract_terminations):
            raise ValueError("an employment contract can terminate only once")
        if tuple(sorted(
                self.contract_terminations,
                key=lambda item: (item.terminated_on, item.contract_id),
        )) != self.contract_terminations:
            raise ValueError("employment terminations must retain calendar order")
        for termination in self.contract_terminations:
            contract = contracts_by_id.get(termination.contract_id)
            if contract is None:
                raise ValueError("employment termination references an absent contract")
            if not contract.active_on(termination.terminated_on):
                raise ValueError("employment termination date must fall inside its contract")
            if termination.contract_id in transfers_by_old:
                raise ValueError("a transferred employment cannot also be terminated")
            incoming_transfer = transfers_by_new.get(termination.contract_id)
            if (incoming_transfer is not None
                    and termination.terminated_on <= incoming_transfer.completed_on):
                raise ValueError("employment termination cannot precede its incoming transfer")
            if any(
                item.player_id == contract.player_id
                and item.contract_id != contract.contract_id
                and item.starts_on >= termination.terminated_on
                for item in self.contracts
            ):
                raise ValueError("a retired player cannot start another employment contract")
        for history in by_player.values():
            dated = sorted(history, key=lambda item: (item.starts_on, item.expires_on, item.contract_id))
            for left, right in zip(dated, dated[1:]):
                if right.starts_on < left.expires_on:
                    transfer = transfers_by_old.get(left.contract_id)
                    if transfer is None or transfer.to_contract_id != right.contract_id or transfer.completed_on != right.starts_on:
                        raise ValueError("overlapping employment contracts require a matching dated transfer")

        obligations_by_id = {item.obligation_id: item for item in self.obligations}
        if len(obligations_by_id) != len(self.obligations):
            raise ValueError("payment obligation IDs must be unique")
        for obligation in self.obligations:
            if obligation.source_contract_id is None:
                continue
            contract = contracts_by_id.get(obligation.source_contract_id)
            if contract is None:
                raise ValueError("wage obligation references an absent employment contract")
            if (
                obligation.debtor_id != contract.club_id
                or obligation.creditor_id != contract.player_id
                or obligation.currency != contract.currency
                or obligation.amount_minor != contract.wage_per_payroll_minor
                or not contract.active_on(obligation.due_on)
                or (contract.contract_id in transfer_dates
                    and transfer_dates[contract.contract_id] <= obligation.due_on)
                or (contract.contract_id in terminations_by_contract
                    and terminations_by_contract[contract.contract_id].terminated_on <= obligation.due_on)
            ):
                raise ValueError("wage obligation does not match its active employment terms")

        entries_by_obligation = {item.obligation_id: item for item in self.entries}
        if len(entries_by_obligation) != len(self.entries):
            raise ValueError("a payment obligation can be settled only once")
        if len({item.entry_id for item in self.entries}) != len(self.entries):
            raise ValueError("ledger entry IDs must be unique")
        accounts_by_key = {(item.owner_id, item.currency): item for item in self.accounts}
        balances = {key: account.opening_balance_minor for key, account in accounts_by_key.items()}
        last_settled_on: WorldDate | None = None
        for entry in self.entries:
            if last_settled_on is not None and entry.settled_on < last_settled_on:
                raise ValueError("ledger entries must retain calendar settlement order")
            obligation = obligations_by_id.get(entry.obligation_id)
            if obligation is None:
                raise ValueError("ledger entry references an absent obligation")
            if (
                entry.entry_id != _entry_id(obligation.obligation_id)
                or entry.debtor_id != obligation.debtor_id
                or entry.creditor_id != obligation.creditor_id
                or entry.currency != obligation.currency
                or entry.amount_minor != obligation.amount_minor
                or entry.settled_on < obligation.due_on
            ):
                raise ValueError("ledger entry does not reconcile with its obligation")
            debtor_key = (entry.debtor_id, entry.currency)
            creditor_key = (entry.creditor_id, entry.currency)
            if debtor_key not in accounts_by_key or creditor_key not in accounts_by_key:
                raise ValueError("settled payment requires both currency accounts")
            balances[debtor_key] -= entry.amount_minor
            balances[creditor_key] += entry.amount_minor
            if balances[debtor_key] < 0:
                raise ValueError("ledger entries cannot overdraw a cash account")
            last_settled_on = entry.settled_on

        run_dates = [item.payroll_date for item in self.payroll_runs]
        if len(run_dates) != len(set(run_dates)):
            raise ValueError("payroll can run only once on a calendar date")
        if run_dates != sorted(run_dates):
            raise ValueError("payroll runs must retain calendar order")
        all_run_obligations: list[str] = []
        for run in self.payroll_runs:
            active = tuple(
                contract for contract in _effective_contracts(
                    self.contracts, self.contract_transfers, run.payroll_date,
                    self.contract_terminations,
                )
            )
            expected_ids = tuple(
                _payroll_obligation_id(contract.contract_id, run.payroll_date)
                for contract in active
            )
            expected_fingerprint = _contract_fingerprint(active)
            if run.obligation_ids != expected_ids or run.active_contract_fingerprint != expected_fingerprint:
                raise ValueError("payroll run does not match its active contract snapshot")
            for contract, obligation_id in zip(active, run.obligation_ids):
                expected_obligation = PaymentObligation(
                    obligation_id=obligation_id,
                    debtor_id=contract.club_id,
                    creditor_id=contract.player_id,
                    currency=contract.currency,
                    amount_minor=contract.wage_per_payroll_minor,
                    due_on=run.payroll_date,
                    kind=ObligationKind.PLAYER_WAGE,
                    source_contract_id=contract.contract_id,
                )
                if obligations_by_id.get(obligation_id) != expected_obligation:
                    raise ValueError("payroll run wage obligation does not match its contract snapshot")
            all_run_obligations.extend(run.obligation_ids)
        if len(all_run_obligations) != len(set(all_run_obligations)):
            raise ValueError("payroll runs cannot create duplicate wage obligations")
        if any(value not in obligations_by_id for value in all_run_obligations):
            raise ValueError("payroll run references an absent wage obligation")
        run_obligations = set(all_run_obligations)
        if any(item.kind is ObligationKind.PLAYER_WAGE and item.obligation_id not in run_obligations
               for item in self.obligations):
            raise ValueError("player wage obligation must belong to an explicit payroll run")

    def cash_balance_minor(self, owner_id: str, currency: str) -> int:
        """Return an account balance from the opening cash plus its postings."""

        validate_id(owner_id, kind="cash account owner ID")
        _currency(currency)
        account = next((item for item in self.accounts
                        if item.owner_id == owner_id and item.currency == currency), None)
        if account is None:
            raise KeyError(f"no {currency} cash account for {owner_id}")
        balance = account.opening_balance_minor
        for entry in self.entries:
            if entry.currency != currency:
                continue
            if entry.debtor_id == owner_id:
                balance -= entry.amount_minor
            if entry.creditor_id == owner_id:
                balance += entry.amount_minor
        return balance


def _entry_id(obligation_id: str) -> str:
    return derive_id("ledger-entry", "p15a-obligation-settlement-v1", obligation_id)


def _payroll_obligation_id(contract_id: str, payroll_date: WorldDate) -> str:
    return derive_id("obligation", "p15a-player-payroll-v1", contract_id, payroll_date.isoformat)


def _contract_fingerprint(contracts: tuple[EmploymentContract, ...]) -> str:
    payload = [
        [item.contract_id, item.club_id, item.player_id,
         item.agreed_on.isoformat, item.starts_on.isoformat, item.expires_on.isoformat,
         item.currency, item.wage_per_payroll_minor]
        for item in contracts
    ]
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _effective_contracts(
    contracts: tuple[EmploymentContract, ...],
    transfers: tuple[ContractTransfer, ...],
    on: WorldDate,
    terminations: tuple[ContractTermination, ...] = (),
) -> tuple[EmploymentContract, ...]:
    transferred = {item.from_contract_id for item in transfers if item.completed_on <= on}
    terminated = {
        item.contract_id for item in terminations if item.terminated_on <= on
    }
    return tuple(item for item in sorted(contracts, key=lambda row: row.contract_id)
                 if item.active_on(on) and item.contract_id not in transferred
                 and item.contract_id not in terminated)


def employment_at(ledger: EconomyLedger, player_id: str, on: WorldDate) -> EmploymentContract | None:
    """Return the player's effective employer after any recorded novations."""
    if not isinstance(ledger, EconomyLedger) or not isinstance(on, WorldDate):
        raise TypeError("employment lookup requires an EconomyLedger and WorldDate")
    validate_id(player_id, kind="employment player ID")
    matches = tuple(item for item in _effective_contracts(
        ledger.contracts, ledger.contract_transfers, on, ledger.contract_terminations,
    ) if item.player_id == player_id)
    if len(matches) > 1:
        raise ValueError("player has multiple effective employment contracts")
    return matches[0] if matches else None


def transfer_employment(
    ledger: EconomyLedger,
    from_contract_id: str,
    new_contract: EmploymentContract,
    *,
    loan_book: object,
) -> tuple[EconomyLedger, ContractTransfer]:
    """Novate a current contract only when no live loan owns that employment.

    The loan book is required so pending consent and active registrations cannot
    be stranded by an economy-only transfer. A player on loan must go through
    ``exercise_purchase_option`` to coordinate employment and registration.
    """
    from games.touchline.esb.economy.loans import LoanBook, LoanStatus, loan_status

    if not isinstance(loan_book, LoanBook):
        raise TypeError("employment transfer requires the current LoanBook")
    if not isinstance(ledger, EconomyLedger) or not isinstance(new_contract, EmploymentContract):
        raise TypeError("employment transfer requires an economy ledger and new contract")
    validate_id(from_contract_id, kind="previous employment contract ID")
    previous = next((item for item in ledger.contracts if item.contract_id == from_contract_id), None)
    if previous is None:
        raise KeyError(f"unknown employment contract: {from_contract_id}")
    live_statuses = {
        LoanStatus.OFFERED, LoanStatus.OWNER_ACCEPTED, LoanStatus.PLAYER_ACCEPTED,
        LoanStatus.AGREED, LoanStatus.ACTIVE,
    }
    if any(proposal.employment_contract_id == from_contract_id
           and proposal.player_id == previous.player_id
           and loan_status(loan_book, proposal.loan_id) in live_statuses
           for proposal in loan_book.proposals):
        raise ValueError("live loan employment must be changed through the loan lifecycle")
    return _novate_employment(ledger, from_contract_id, new_contract)


def add_employment_contract(
    ledger: EconomyLedger,
    contract: EmploymentContract,
) -> EconomyLedger:
    """Add one explicit player contract, returning an identical retry unchanged."""
    if not isinstance(ledger, EconomyLedger) or not isinstance(contract, EmploymentContract):
        raise TypeError("employment requires an economy ledger and dated contract")
    existing = next((item for item in ledger.contracts
                     if item.contract_id == contract.contract_id), None)
    if existing is not None:
        if existing == contract:
            return ledger
        raise ValueError("employment contract ID was reused with conflicting terms")
    return EconomyLedger(
        ledger.accounts, ledger.contracts + (contract,), ledger.obligations,
        ledger.entries, ledger.payroll_runs, ledger.contract_transfers,
        ledger.contract_terminations,
    )


def terminate_employment(
    ledger: EconomyLedger,
    contract_id: str,
    on: WorldDate,
    *,
    loan_book: object,
    reason: ContractTerminationReason = ContractTerminationReason.RETIREMENT,
) -> tuple[EconomyLedger, ContractTermination]:
    """End effective employment once, rejecting live loan and payroll conflicts."""
    from games.touchline.esb.economy.loans import LoanBook, LoanStatus, loan_status

    if not isinstance(ledger, EconomyLedger) or not isinstance(on, WorldDate):
        raise TypeError("employment termination requires a ledger and explicit date")
    if not isinstance(loan_book, LoanBook):
        raise TypeError("employment termination requires the current LoanBook")
    if not isinstance(reason, ContractTerminationReason):
        raise TypeError("employment termination requires a registered reason")
    validate_id(contract_id, kind="terminated employment contract ID")
    previous = next((item for item in ledger.contract_terminations
                     if item.contract_id == contract_id), None)
    termination_id = derive_id(
        "contract-termination", "p16d-employment-termination-v1",
        contract_id, on.isoformat, reason.value,
    )
    proposed = ContractTermination(termination_id, contract_id, on, reason)
    if previous is not None:
        if previous == proposed:
            return ledger, previous
        raise ValueError("employment contract already has a different termination")
    contract = next((item for item in ledger.contracts if item.contract_id == contract_id), None)
    if contract is None:
        raise KeyError(f"unknown employment contract: {contract_id}")
    if employment_at(ledger, contract.player_id, on) != contract:
        raise ValueError("only the player's effective employment can be terminated")
    live_statuses = {
        LoanStatus.OFFERED, LoanStatus.OWNER_ACCEPTED, LoanStatus.PLAYER_ACCEPTED,
        LoanStatus.AGREED, LoanStatus.ACTIVE,
    }
    if any(item.employment_contract_id == contract_id
           and item.player_id == contract.player_id
           and loan_status(loan_book, item.loan_id) in live_statuses
           for item in loan_book.proposals):
        raise ValueError("live loan employment must be resolved before termination")
    if any(run.payroll_date >= on and contract_id in {
        obligation.source_contract_id for obligation in ledger.obligations
        if obligation.obligation_id in run.obligation_ids
    } for run in ledger.payroll_runs):
        raise ValueError("employment termination crosses a recorded payroll snapshot")
    if any(item.source_contract_id == contract_id and item.due_on >= on
           for item in ledger.obligations):
        raise ValueError("employment termination crosses a recorded future wage obligation")
    if ledger.contract_terminations and on < ledger.contract_terminations[-1].terminated_on:
        raise ValueError("employment termination must follow the latest termination")
    updated = EconomyLedger(
        ledger.accounts, ledger.contracts, ledger.obligations, ledger.entries,
        ledger.payroll_runs, ledger.contract_transfers,
        tuple(sorted(
            ledger.contract_terminations + (proposed,),
            key=lambda item: (item.terminated_on, item.contract_id),
        )),
    )
    return updated, proposed


def _novate_employment(
    ledger: EconomyLedger,
    from_contract_id: str,
    new_contract: EmploymentContract,
) -> tuple[EconomyLedger, ContractTransfer]:
    """Internal novation primitive used by the coordinated loan-purchase path."""
    if not isinstance(ledger, EconomyLedger) or not isinstance(new_contract, EmploymentContract):
        raise TypeError("employment transfer requires an economy ledger and new contract")
    validate_id(from_contract_id, kind="previous employment contract ID")
    previous = next((item for item in ledger.contracts if item.contract_id == from_contract_id), None)
    if previous is None:
        raise KeyError(f"unknown employment contract: {from_contract_id}")
    effective_on = new_contract.starts_on
    if (new_contract.player_id != previous.player_id or new_contract.club_id == previous.club_id
            or new_contract.currency != previous.currency or new_contract.agreed_on != effective_on
            or not previous.active_on(effective_on)):
        raise ValueError("new employment terms do not match the existing player's transfer")
    prior_transfer = next((item for item in ledger.contract_transfers
                           if item.from_contract_id == from_contract_id), None)
    if prior_transfer is not None:
        existing_contract = next((item for item in ledger.contracts
                                  if item.contract_id == new_contract.contract_id), None)
        if (prior_transfer.to_contract_id == new_contract.contract_id
                and prior_transfer.completed_on == effective_on
                and existing_contract == new_contract):
            return ledger, prior_transfer
        raise ValueError("employment contract already transferred under different terms")
    if employment_at(ledger, previous.player_id, effective_on) != previous:
        raise ValueError("only the player's effective employment can be transferred")
    if any(item.from_contract_id == from_contract_id for item in ledger.contract_transfers):
        raise ValueError("employment contract already participates in a transfer")
    if any(item.from_contract_id == new_contract.contract_id or item.to_contract_id == new_contract.contract_id
           for item in ledger.contract_transfers):
        raise ValueError("replacement employment contract already participates in a transfer")
    if (ledger.contract_transfers
            and effective_on < ledger.contract_transfers[-1].completed_on):
        raise ValueError("employment transfers must retain calendar order")
    if any(run.payroll_date >= effective_on and from_contract_id in {
        obligation.source_contract_id for obligation in ledger.obligations
        if obligation.obligation_id in run.obligation_ids
    } for run in ledger.payroll_runs):
        raise ValueError("employment transfer crosses a recorded future payroll snapshot")
    if any(item.source_contract_id == from_contract_id and item.due_on >= effective_on
           for item in ledger.obligations):
        raise ValueError("employment transfer crosses a recorded future wage obligation")
    transfer = ContractTransfer(
        derive_id("employment-transfer", "p15c-contract-novation-v1",
                  previous.contract_id, new_contract.contract_id, effective_on.isoformat),
        previous.contract_id, new_contract.contract_id, effective_on,
    )
    if any(item.contract_id == new_contract.contract_id for item in ledger.contracts):
        raise ValueError("replacement employment contract ID already exists")
    updated = EconomyLedger(
        ledger.accounts, ledger.contracts + (new_contract,), ledger.obligations,
        ledger.entries, ledger.payroll_runs, ledger.contract_transfers + (transfer,),
        ledger.contract_terminations,
    )
    return updated, transfer


def add_account(ledger: EconomyLedger, account: CashAccount) -> EconomyLedger:
    if not isinstance(ledger, EconomyLedger) or not isinstance(account, CashAccount):
        raise TypeError("adding cash requires an economy ledger and account")
    existing = next((item for item in ledger.accounts
                     if (item.owner_id, item.currency) == (account.owner_id, account.currency)), None)
    if existing is not None:
        if existing == account:
            return ledger
        raise ValueError("cash account owner/currency pair already has different opening terms")
    return EconomyLedger(
        ledger.accounts + (account,), ledger.contracts, ledger.obligations,
        ledger.entries, ledger.payroll_runs, ledger.contract_transfers,
        ledger.contract_terminations,
    )


def add_obligation(ledger: EconomyLedger, obligation: PaymentObligation) -> EconomyLedger:
    """Schedule an obligation once; settlement is a separate dated command."""

    if not isinstance(ledger, EconomyLedger) or not isinstance(obligation, PaymentObligation):
        raise TypeError("scheduling a payable requires an economy ledger and obligation")
    existing = next((item for item in ledger.obligations
                     if item.obligation_id == obligation.obligation_id), None)
    if existing is not None:
        if existing == obligation:
            return ledger
        raise ValueError("obligation ID was reused with conflicting terms")
    if obligation.kind is ObligationKind.PLAYER_WAGE:
        raise ValueError("player wage obligations are created only by an explicit payroll run")
    contract_ids = {item.contract_id for item in ledger.contracts}
    if obligation.source_contract_id is not None and obligation.source_contract_id not in contract_ids:
        raise ValueError("wage obligation references an absent employment contract")
    return EconomyLedger(
        ledger.accounts, ledger.contracts, ledger.obligations + (obligation,),
        ledger.entries, ledger.payroll_runs, ledger.contract_transfers,
        ledger.contract_terminations,
    )


def contract_status(contract: EmploymentContract, on: WorldDate) -> ContractStatus:
    """Return the contract's dated-term status, without resolving novations.

    Use :func:`employment_at` to identify the effective employer in a ledger.
    """
    if not isinstance(contract, EmploymentContract) or not isinstance(on, WorldDate):
        raise TypeError("contract status requires an employment contract and WorldDate")
    if on < contract.starts_on:
        return ContractStatus.NOT_STARTED
    if on >= contract.expires_on:
        return ContractStatus.EXPIRED
    return ContractStatus.ACTIVE


def run_payroll(ledger: EconomyLedger, on: WorldDate) -> EconomyLedger:
    """Create one period wage payable for every player contract active that day.

    The explicit date is the caller's payroll calendar. This function never
    runs because a fixture occurred, and same-date replay must match the
    previously captured contract snapshot exactly.
    """

    if not isinstance(ledger, EconomyLedger) or not isinstance(on, WorldDate):
        raise TypeError("payroll requires an economy ledger and explicit WorldDate")
    active = _effective_contracts(
        ledger.contracts, ledger.contract_transfers, on, ledger.contract_terminations,
    )
    fingerprint = _contract_fingerprint(active)
    obligation_ids = tuple(_payroll_obligation_id(contract.contract_id, on) for contract in active)
    prior = next((item for item in ledger.payroll_runs if item.payroll_date == on), None)
    if prior is not None:
        if prior.active_contract_fingerprint != fingerprint or prior.obligation_ids != obligation_ids:
            raise ValueError("payroll date retry conflicts with its original contract snapshot")
        return ledger
    if ledger.payroll_runs and on < ledger.payroll_runs[-1].payroll_date:
        raise ValueError("payroll cannot be recorded before the latest payroll date")
    if ledger.entries and on < ledger.entries[-1].settled_on:
        raise ValueError("payroll cannot be recorded before the latest ledger date")

    obligations = ledger.obligations + tuple(
        PaymentObligation(
            obligation_id=_payroll_obligation_id(contract.contract_id, on),
            debtor_id=contract.club_id,
            creditor_id=contract.player_id,
            currency=contract.currency,
            amount_minor=contract.wage_per_payroll_minor,
            due_on=on,
            kind=ObligationKind.PLAYER_WAGE,
            source_contract_id=contract.contract_id,
        )
        for contract in active
    )
    run = PayrollRun(on, fingerprint, obligation_ids)
    return EconomyLedger(
        ledger.accounts, ledger.contracts, obligations, ledger.entries,
        ledger.payroll_runs + (run,), ledger.contract_transfers,
        ledger.contract_terminations,
    )


def settle_obligation(
    ledger: EconomyLedger,
    obligation_id: str,
    on: WorldDate,
) -> tuple[EconomyLedger, LedgerEntry]:
    """Settle one due payable, posting equal debit/credit cash movements.

    The obligation ID is the stable settlement key. An exact retry on the
    original booking date returns its original entry without changing state.
    Insufficient cash or an early attempt leaves the immutable input untouched.
    """

    if not isinstance(ledger, EconomyLedger) or not isinstance(on, WorldDate):
        raise TypeError("settlement requires an economy ledger and explicit WorldDate")
    validate_id(obligation_id, kind="settlement obligation ID")
    obligation = next((item for item in ledger.obligations
                       if item.obligation_id == obligation_id), None)
    if obligation is None:
        raise KeyError(f"unknown payment obligation: {obligation_id}")
    prior = next((item for item in ledger.entries if item.obligation_id == obligation_id), None)
    if prior is not None:
        if prior.settled_on != on:
            raise ValueError("settlement retry date conflicts with the original ledger entry")
        return ledger, prior
    if on < obligation.due_on:
        raise ValueError("payment obligation is not due yet")
    latest_dates = [item.settled_on for item in ledger.entries]
    latest_dates.extend(item.payroll_date for item in ledger.payroll_runs)
    latest_economy_date = max(latest_dates, default=None)
    if latest_economy_date is not None and on < latest_economy_date:
        raise ValueError("settlement cannot be booked before the latest economy event date")
    debtor = next((item for item in ledger.accounts
                   if item.owner_id == obligation.debtor_id and item.currency == obligation.currency), None)
    creditor = next((item for item in ledger.accounts
                     if item.owner_id == obligation.creditor_id and item.currency == obligation.currency), None)
    if debtor is None or creditor is None:
        raise ValueError("settlement requires both debtor and creditor cash accounts")
    if ledger.cash_balance_minor(debtor.owner_id, debtor.currency) < obligation.amount_minor:
        raise ValueError("insufficient cash to settle payment obligation")

    entry = LedgerEntry(
        entry_id=_entry_id(obligation_id),
        obligation_id=obligation_id,
        debtor_id=obligation.debtor_id,
        creditor_id=obligation.creditor_id,
        currency=obligation.currency,
        amount_minor=obligation.amount_minor,
        settled_on=on,
    )
    updated = EconomyLedger(
        ledger.accounts, ledger.contracts, ledger.obligations,
        ledger.entries + (entry,), ledger.payroll_runs, ledger.contract_transfers,
        ledger.contract_terminations,
    )
    return updated, entry
