"""Consented loans, registration moves and purchase settlement (P15c).

This package separates employment ownership from temporary competition
registration. Loan costs use the shared P15a payable/settlement ledger. Every
decision is an explicit dated event; this module does not run a calendar or
mutate a live career save.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import timedelta
from enum import Enum

from games.touchline.esb.economy.ledger import (
    EconomyLedger, EmploymentContract, ObligationKind, PaymentObligation, employment_at,
    _novate_employment,
)
from games.touchline.esb.ids import derive_id, validate_id
from games.touchline.esb.people.medical_clearance import (
    MedicalOutcome, TransferMedicalAssessment,
)
from games.touchline.esb.serialization import SerializationError, dumps, loads
from games.touchline.esb.time import WorldDate
from games.touchline.esb.world.registration import (
    RegistrationBook, check_existing_registration, check_registration, purchase_loan_player,
    register_loan_player, return_loan_player,
)

_BPS = 10_000


class LoanStatus(str, Enum):
    OFFERED = "offered"
    OWNER_ACCEPTED = "owner_accepted"
    PLAYER_ACCEPTED = "player_accepted"
    AGREED = "agreed_in_principle"
    REJECTED = "rejected"
    OFFER_EXPIRED = "offer_expired"
    ACTIVE = "active"
    RECALLED = "recalled"
    RETURNED = "returned"
    PURCHASED = "purchased"
    EXPIRED = "expired"


class LoanEventKind(str, Enum):
    PROPOSED = "proposed"
    OWNER_ACCEPTED = "owner_accepted"
    OWNER_REJECTED = "owner_rejected"
    PLAYER_ACCEPTED = "player_accepted"
    PLAYER_REJECTED = "player_rejected"
    OFFER_EXPIRED = "offer_expired"
    ACTIVATED = "activated"
    LOAN_FEE_SCHEDULED = "loan_fee_scheduled"
    WAGE_SHARE_SCHEDULED = "wage_share_scheduled"
    RECALLED = "recalled"
    RETURNED = "returned"
    EXPIRED = "expired"
    PURCHASED = "purchased"


def _loan_event_id(
    loan_id: str,
    kind: LoanEventKind,
    actor_id: str,
    on: WorldDate,
    obligation_id: str | None,
    assessment_id: str | None,
    registration_check_ids: tuple[str, ...],
    replacement_contract_id: str | None,
) -> str:
    return derive_id(
        "loan-event", "p15c-loan-lifecycle-v2", loan_id, kind.value,
        actor_id, on.isoformat, obligation_id or "", assessment_id or "",
        str(len(registration_check_ids)), *registration_check_ids,
        replacement_contract_id or "",
    )


@dataclass(frozen=True)
class PurchaseOption:
    fee_minor: int
    opens_on: WorldDate
    expires_on: WorldDate
    wage_per_payroll_minor: int
    contract_weeks: int

    def __post_init__(self) -> None:
        if type(self.fee_minor) is not int or self.fee_minor <= 0:
            raise ValueError("purchase option fee must be a positive minor-unit amount")
        if not isinstance(self.opens_on, WorldDate) or not isinstance(self.expires_on, WorldDate):
            raise TypeError("purchase option requires explicit dates")
        if self.expires_on < self.opens_on:
            raise ValueError("purchase option expires before it opens")
        if type(self.wage_per_payroll_minor) is not int or self.wage_per_payroll_minor <= 0:
            raise ValueError("purchase contract wage must be positive minor units")
        if type(self.contract_weeks) is not int or self.contract_weeks <= 0:
            raise ValueError("purchase contract length must be positive weeks")


@dataclass(frozen=True)
class LoanProposal:
    loan_id: str
    player_id: str
    owner_club_id: str
    borrower_club_id: str
    employment_contract_id: str
    submitted_on: WorldDate
    expires_on: WorldDate
    starts_on: WorldDate
    ends_on: WorldDate
    currency: str
    loan_fee_minor: int
    borrower_wage_share_bps: int
    competition_ids: tuple[str, ...]
    recall_from: WorldDate | None = None
    purchase_option: PurchaseOption | None = None

    def __post_init__(self) -> None:
        for value, label in ((self.loan_id, "loan ID"), (self.player_id, "loan player ID"),
                             (self.owner_club_id, "loan owner club ID"),
                             (self.borrower_club_id, "loan borrower club ID"),
                             (self.employment_contract_id, "loan employment contract ID")):
            validate_id(value, kind=label)
        if self.owner_club_id == self.borrower_club_id:
            raise ValueError("loan owner and borrower must be different clubs")
        for label, value in (("submission", self.submitted_on), ("offer expiry", self.expires_on),
                             ("loan start", self.starts_on), ("loan end", self.ends_on)):
            if not isinstance(value, WorldDate):
                raise TypeError(f"loan {label} requires a WorldDate")
        if self.expires_on < self.submitted_on:
            raise ValueError("loan offer expires before it was submitted")
        if self.starts_on < self.submitted_on or self.ends_on <= self.starts_on:
            raise ValueError("loan term must start after agreement and have positive duration")
        if self.expires_on >= self.ends_on:
            raise ValueError("loan consent deadline must precede the exclusive loan end")
        if not isinstance(self.currency, str) or len(self.currency) != 3 or not self.currency.isascii() or not self.currency.isalpha() or self.currency.upper() != self.currency:
            raise ValueError("loan currency must be a three-letter uppercase code")
        if type(self.loan_fee_minor) is not int or self.loan_fee_minor < 0:
            raise ValueError("loan fee must be non-negative integer minor units")
        if type(self.borrower_wage_share_bps) is not int or not 0 <= self.borrower_wage_share_bps <= _BPS:
            raise ValueError("borrower wage share must be basis points in [0, 10000]")
        if not isinstance(self.competition_ids, tuple) or not self.competition_ids:
            raise ValueError("a loan must name at least one competition")
        for competition_id in self.competition_ids:
            validate_id(competition_id, kind="loan competition ID")
        if len(self.competition_ids) != len(set(self.competition_ids)):
            raise ValueError("loan competition list cannot repeat a competition")
        if self.recall_from is not None:
            if not isinstance(self.recall_from, WorldDate):
                raise TypeError("loan recall date must be a WorldDate")
            if not self.starts_on <= self.recall_from < self.ends_on:
                raise ValueError("recall eligibility must fall inside the loan term")
        if self.purchase_option is not None:
            if not isinstance(self.purchase_option, PurchaseOption):
                raise TypeError("loan purchase terms must use PurchaseOption")
            if not self.starts_on <= self.purchase_option.opens_on <= self.purchase_option.expires_on < self.ends_on:
                raise ValueError("purchase option dates must fall inside the loan term")


@dataclass(frozen=True)
class LoanEvent:
    event_id: str
    loan_id: str
    actor_id: str
    at: WorldDate
    kind: LoanEventKind
    obligation_id: str | None = None
    medical_assessment_id: str | None = None
    registration_check_ids: tuple[str, ...] = ()
    replacement_contract_id: str | None = None

    def __post_init__(self) -> None:
        for value, label in ((self.event_id, "loan event ID"), (self.loan_id, "loan event loan ID"),
                             (self.actor_id, "loan event actor ID")):
            validate_id(value, kind=label)
        if not isinstance(self.at, WorldDate) or not isinstance(self.kind, LoanEventKind):
            raise TypeError("loan event requires an explicit date and registered kind")
        for value, label in ((self.obligation_id, "loan obligation ID"),
                             (self.medical_assessment_id, "medical assessment ID"),
                             (self.replacement_contract_id, "replacement contract ID")):
            if value is not None:
                validate_id(value, kind=label)
        if not isinstance(self.registration_check_ids, tuple):
            raise TypeError("loan registration references must be an immutable tuple")
        for value in self.registration_check_ids:
            validate_id(value, kind="registration check ID")
        if len(self.registration_check_ids) != len(set(self.registration_check_ids)):
            raise ValueError("loan event cannot repeat a registration check")
        expected_event_id = _loan_event_id(
            self.loan_id, self.kind, self.actor_id, self.at, self.obligation_id,
            self.medical_assessment_id, self.registration_check_ids,
            self.replacement_contract_id,
        )
        if self.event_id != expected_event_id:
            raise ValueError("loan event ID does not match its immutable event lineage")


def _event(proposal: LoanProposal, actor_id: str, on: WorldDate, kind: LoanEventKind,
           *, obligation_id: str | None = None,
           assessment_id: str | None = None,
           registration_checks: tuple[str, ...] = (),
           replacement_contract_id: str | None = None) -> LoanEvent:
    event_id = _loan_event_id(
        proposal.loan_id, kind, actor_id, on, obligation_id, assessment_id,
        registration_checks, replacement_contract_id,
    )
    return LoanEvent(event_id, proposal.loan_id, actor_id, on, kind, obligation_id,
                     assessment_id, registration_checks, replacement_contract_id)


@dataclass(frozen=True)
class LoanBook:
    proposals: tuple[LoanProposal, ...] = ()
    events: tuple[LoanEvent, ...] = ()
    schema_version: int = 1

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("unsupported loan-book schema version")
        if not isinstance(self.proposals, tuple) or any(not isinstance(item, LoanProposal) for item in self.proposals):
            raise TypeError("loan proposals must be immutable LoanProposal records")
        if not isinstance(self.events, tuple) or any(not isinstance(item, LoanEvent) for item in self.events):
            raise TypeError("loan events must be immutable LoanEvent records")
        proposals = {item.loan_id: item for item in self.proposals}
        if len(proposals) != len(self.proposals):
            raise ValueError("loan IDs must be unique")
        if len({item.event_id for item in self.events}) != len(self.events):
            raise ValueError("loan event IDs must be unique")
        if tuple(sorted(self.events, key=lambda item: item.at)) != self.events:
            raise ValueError("loan events must retain calendar order")
        if any(item.loan_id not in proposals for item in self.events):
            raise ValueError("loan event references an absent proposal")
        if len({(item.loan_id, item.kind, item.actor_id) for item in self.events
                if item.kind in (LoanEventKind.OWNER_ACCEPTED, LoanEventKind.OWNER_REJECTED,
                                 LoanEventKind.PLAYER_ACCEPTED, LoanEventKind.PLAYER_REJECTED)}) != sum(
            item.kind in (LoanEventKind.OWNER_ACCEPTED, LoanEventKind.OWNER_REJECTED,
                          LoanEventKind.PLAYER_ACCEPTED, LoanEventKind.PLAYER_REJECTED)
            for item in self.events
        ):
            raise ValueError("each loan party can decide only once")
        for proposal in self.proposals:
            matching = tuple(item for item in self.events if item.loan_id == proposal.loan_id)
            if not matching or matching[0].kind is not LoanEventKind.PROPOSED:
                raise ValueError("each loan proposal requires its opening event")
            _validate_loan_events(proposal, matching)
        active_player_ids: set[str] = set()
        unresolved_player_ids: set[str] = set()
        for proposal in self.proposals:
            status = loan_status(self, proposal.loan_id)
            if status in (LoanStatus.OFFERED, LoanStatus.OWNER_ACCEPTED,
                          LoanStatus.PLAYER_ACCEPTED, LoanStatus.AGREED, LoanStatus.ACTIVE):
                if proposal.player_id in unresolved_player_ids:
                    raise ValueError("a player cannot have multiple live loan proposals")
                unresolved_player_ids.add(proposal.player_id)
            if status is LoanStatus.ACTIVE:
                if proposal.player_id in active_player_ids:
                    raise ValueError("a player cannot have two active loans")
                active_player_ids.add(proposal.player_id)

    def to_json(self) -> str:
        return dumps(self)

    @classmethod
    def from_json(cls, value: str) -> LoanBook:
        try:
            return loads(value, cls)
        except SerializationError as exc:
            raise ValueError(f"invalid loan book: {exc}") from exc


def _validate_loan_events(proposal: LoanProposal, events: tuple[LoanEvent, ...]) -> None:
    if events[0].kind is not LoanEventKind.PROPOSED or events[0].actor_id != proposal.borrower_club_id or events[0].at != proposal.submitted_on:
        raise ValueError("loan proposal event does not match its submitted terms")
    owner_accepted = player_accepted = False
    decided = False
    active = False
    finished = False
    scheduled: set[tuple[LoanEventKind, str | None]] = set()
    scheduled_dates: set[tuple[LoanEventKind, WorldDate]] = set()
    scheduled_obligation_ids: set[str] = set()
    activation_event: LoanEvent | None = None
    loan_fee_event: LoanEvent | None = None
    for event in events[1:]:
        if event.at < proposal.submitted_on:
            raise ValueError("loan decision precedes its proposal")
        if decided and event.kind not in (LoanEventKind.WAGE_SHARE_SCHEDULED,):
            raise ValueError("loan cannot transition after a terminal decision")
        if event.kind is LoanEventKind.OWNER_ACCEPTED:
            if event.actor_id != proposal.owner_club_id or owner_accepted or active or event.at > proposal.expires_on:
                raise ValueError("owner loan acceptance is duplicate, late or misattributed")
            owner_accepted = True
        elif event.kind is LoanEventKind.OWNER_REJECTED:
            if event.actor_id != proposal.owner_club_id or owner_accepted or active or event.at > proposal.expires_on:
                raise ValueError("owner loan rejection is duplicate, late or misattributed")
            decided = True
        elif event.kind is LoanEventKind.PLAYER_ACCEPTED:
            if event.actor_id != proposal.player_id or player_accepted or active or event.at > proposal.expires_on:
                raise ValueError("player loan acceptance is duplicate, late or misattributed")
            player_accepted = True
        elif event.kind is LoanEventKind.PLAYER_REJECTED:
            if event.actor_id != proposal.player_id or player_accepted or active or event.at > proposal.expires_on:
                raise ValueError("player loan rejection is duplicate, late or misattributed")
            decided = True
        elif event.kind is LoanEventKind.OFFER_EXPIRED:
            if (decided or active or (owner_accepted and player_accepted)
                    or event.actor_id != proposal.borrower_club_id or event.at <= proposal.expires_on):
                raise ValueError("only an undecided loan may expire after its response deadline")
            decided = True
        elif event.kind is LoanEventKind.ACTIVATED:
            if (not (owner_accepted and player_accepted) or active or decided or finished
                    or event.actor_id != proposal.borrower_club_id
                    or event.at < proposal.starts_on or event.at >= proposal.ends_on):
                raise ValueError("loan activation requires both consents inside the loan term")
            if (event.medical_assessment_id is None
                    or len(event.registration_check_ids) != len(proposal.competition_ids)):
                raise ValueError("loan activation requires medical and registration evidence")
            active = True
            activation_event = event
        elif event.kind in (LoanEventKind.LOAN_FEE_SCHEDULED, LoanEventKind.WAGE_SHARE_SCHEDULED):
            if (not active or event.obligation_id is None
                    or event.actor_id != proposal.borrower_club_id):
                raise ValueError("loan cost obligations require an active loan and obligation reference")
            key = (event.kind, event.obligation_id)
            date_key = (event.kind, event.at)
            if key in scheduled or date_key in scheduled_dates:
                raise ValueError("loan cost obligation cannot be scheduled twice")
            if event.obligation_id in scheduled_obligation_ids:
                raise ValueError("loan obligation cannot be reused across cost events")
            scheduled.add(key)
            scheduled_dates.add(date_key)
            scheduled_obligation_ids.add(event.obligation_id)
            if event.kind is LoanEventKind.LOAN_FEE_SCHEDULED:
                if (proposal.loan_fee_minor <= 0 or activation_event is None
                        or event.obligation_id != activation_event.obligation_id
                        or event.at != activation_event.at or loan_fee_event is not None):
                    raise ValueError("loan fee event does not reconcile with activation terms")
                loan_fee_event = event
            else:
                expected_wage_share_id = derive_id(
                    "obligation", "p15c-loan-wage-share-v1", proposal.loan_id,
                    event.at.isoformat,
                )
                if (activation_event is None or event.at < activation_event.at
                        or not proposal.starts_on <= event.at < proposal.ends_on):
                    raise ValueError("loan wage share date is outside its active term")
                if event.obligation_id != expected_wage_share_id:
                    raise ValueError("loan wage share does not match its deterministic obligation ID")
        elif event.kind in (LoanEventKind.RECALLED, LoanEventKind.RETURNED,
                            LoanEventKind.EXPIRED, LoanEventKind.PURCHASED):
            if not active or finished:
                raise ValueError("loan end requires one active agreement")
            if event.kind is LoanEventKind.RECALLED:
                if (event.actor_id != proposal.owner_club_id or proposal.recall_from is None
                        or event.at < proposal.recall_from or event.at >= proposal.ends_on):
                    raise ValueError("loan recall is not authorized by the agreed terms")
            elif event.kind is LoanEventKind.PURCHASED:
                if (event.actor_id != proposal.borrower_club_id or proposal.purchase_option is None
                        or event.at < proposal.purchase_option.opens_on or event.at > proposal.purchase_option.expires_on):
                    raise ValueError("loan purchase falls outside its agreed option")
                if event.replacement_contract_id is None or event.obligation_id is None:
                    raise ValueError("completed purchase must name a new contract and fee obligation")
                if (event.medical_assessment_id is None
                        or len(event.registration_check_ids) != len(proposal.competition_ids)):
                    raise ValueError("completed purchase must retain its medical and registration evidence")
                expected_contract_id = derive_id(
                    "employment-contract", "p15c-loan-purchase-v1",
                    proposal.loan_id, event.at.isoformat,
                )
                expected_fee_id = derive_id(
                    "obligation", "p15c-loan-purchase-fee-v1", proposal.loan_id,
                )
                if (event.replacement_contract_id != expected_contract_id
                        or event.obligation_id != expected_fee_id
                        or event.obligation_id in scheduled_obligation_ids):
                    raise ValueError("completed purchase references conflicting contract or fee lineage")
            elif event.kind is LoanEventKind.RETURNED:
                if event.actor_id != proposal.owner_club_id or event.at < proposal.ends_on:
                    raise ValueError("loan return must follow the agreed term and be recorded by its owner")
            elif event.kind is LoanEventKind.EXPIRED:
                if event.actor_id != proposal.owner_club_id or event.at < proposal.ends_on:
                    raise ValueError("loan cannot expire before its agreed end date")
            if event.kind in (LoanEventKind.RECALLED, LoanEventKind.RETURNED, LoanEventKind.EXPIRED, LoanEventKind.PURCHASED):
                active = False
                finished = True
        else:
            raise ValueError("invalid loan lifecycle event")
    if any(item.kind is LoanEventKind.ACTIVATED for item in events) and not (
        owner_accepted and player_accepted
    ):
        raise ValueError("active loan lost one of its party consents")
    if activation_event is not None:
        expected_fee_id = (derive_id("obligation", "p15c-loan-fee-v1", proposal.loan_id)
                           if proposal.loan_fee_minor else None)
        if (activation_event.obligation_id != expected_fee_id
                or (proposal.loan_fee_minor > 0) != (loan_fee_event is not None)):
            raise ValueError("loan activation fee schedule does not match the agreed fee")


def loan_status(book: LoanBook, loan_id: str) -> LoanStatus:
    if not isinstance(book, LoanBook):
        raise TypeError("loan status requires a LoanBook")
    validate_id(loan_id, kind="loan ID")
    proposal = next((item for item in book.proposals if item.loan_id == loan_id), None)
    if proposal is None:
        raise KeyError(f"unknown loan: {loan_id}")
    events = tuple(item for item in book.events if item.loan_id == loan_id)
    if any(item.kind is LoanEventKind.PURCHASED for item in events):
        return LoanStatus.PURCHASED
    if any(item.kind is LoanEventKind.RECALLED for item in events):
        return LoanStatus.RECALLED
    if any(item.kind is LoanEventKind.EXPIRED for item in events):
        return LoanStatus.EXPIRED
    if any(item.kind is LoanEventKind.RETURNED for item in events):
        return LoanStatus.RETURNED
    if any(item.kind is LoanEventKind.OFFER_EXPIRED for item in events):
        return LoanStatus.OFFER_EXPIRED
    if any(item.kind is LoanEventKind.OWNER_REJECTED or item.kind is LoanEventKind.PLAYER_REJECTED for item in events):
        return LoanStatus.REJECTED
    if any(item.kind is LoanEventKind.ACTIVATED for item in events):
        return LoanStatus.ACTIVE
    owner = any(item.kind is LoanEventKind.OWNER_ACCEPTED for item in events)
    player = any(item.kind is LoanEventKind.PLAYER_ACCEPTED for item in events)
    if owner and player:
        return LoanStatus.AGREED
    if owner:
        return LoanStatus.OWNER_ACCEPTED
    if player:
        return LoanStatus.PLAYER_ACCEPTED
    return LoanStatus.OFFERED


def _append(book: LoanBook, event: LoanEvent) -> LoanBook:
    if book.events and event.at < book.events[-1].at:
        raise ValueError("loan decisions must retain calendar chronology")
    existing = next((item for item in book.events if item.event_id == event.event_id), None)
    if existing is not None:
        if existing != event:
            raise ValueError("loan event ID was reused with conflicting data")
        return book
    return LoanBook(book.proposals, book.events + (event,))


def propose_loan(book: LoanBook, proposal: LoanProposal, ledger: EconomyLedger) -> LoanBook:
    if not isinstance(book, LoanBook) or not isinstance(proposal, LoanProposal) or not isinstance(ledger, EconomyLedger):
        raise TypeError("loan proposal requires a loan book, proposal and economy ledger")
    existing = next((item for item in book.proposals if item.loan_id == proposal.loan_id), None)
    if existing is not None:
        if existing == proposal:
            return book
        raise ValueError("loan ID was reused with different terms")
    contract = next((item for item in ledger.contracts if item.contract_id == proposal.employment_contract_id), None)
    if contract is None or contract.player_id != proposal.player_id or contract.club_id != proposal.owner_club_id:
        raise ValueError("loan proposal must cite the player's active owner employment contract")
    if contract.currency != proposal.currency or contract.expires_on < proposal.ends_on:
        raise ValueError("loan terms exceed the employment contract's currency or expiry")
    if (not contract.active_on(proposal.starts_on)
            or employment_at(ledger, proposal.player_id, proposal.starts_on) != contract):
        raise ValueError("employment contract is not active at loan start")
    if any(item.player_id == proposal.player_id and loan_status(book, item.loan_id) in
           (LoanStatus.OFFERED, LoanStatus.OWNER_ACCEPTED, LoanStatus.PLAYER_ACCEPTED,
            LoanStatus.AGREED, LoanStatus.ACTIVE) for item in book.proposals):
        raise ValueError("player already has an unresolved or active loan proposal")
    event = _event(proposal, proposal.borrower_club_id, proposal.submitted_on, LoanEventKind.PROPOSED)
    if book.events and proposal.submitted_on < book.events[-1].at:
        raise ValueError("loan proposals must retain calendar chronology")
    return LoanBook(book.proposals + (proposal,), book.events + (event,))


def respond_to_loan(book: LoanBook, loan_id: str, actor_id: str, accepted: bool,
                    on: WorldDate) -> LoanBook:
    if not isinstance(book, LoanBook) or not isinstance(on, WorldDate) or type(accepted) is not bool:
        raise TypeError("loan response requires a book, decision and explicit date")
    validate_id(loan_id, kind="loan ID")
    validate_id(actor_id, kind="loan decision actor ID")
    proposal = next((item for item in book.proposals if item.loan_id == loan_id), None)
    if proposal is None:
        raise KeyError(f"unknown loan: {loan_id}")
    if actor_id == proposal.owner_club_id:
        kind = LoanEventKind.OWNER_ACCEPTED if accepted else LoanEventKind.OWNER_REJECTED
    elif actor_id == proposal.player_id:
        kind = LoanEventKind.PLAYER_ACCEPTED if accepted else LoanEventKind.PLAYER_REJECTED
    else:
        raise ValueError("loan consent must come from the owner club or the player")
    prior = next((item for item in book.events if item.loan_id == loan_id
                  and item.actor_id == actor_id
                  and item.kind in (LoanEventKind.OWNER_ACCEPTED, LoanEventKind.OWNER_REJECTED,
                                    LoanEventKind.PLAYER_ACCEPTED, LoanEventKind.PLAYER_REJECTED)), None)
    if prior is not None:
        if prior.kind is kind and prior.at == on:
            return book
        raise ValueError("loan party already made a different decision")
    if loan_status(book, loan_id) in (LoanStatus.REJECTED, LoanStatus.OFFER_EXPIRED,
                                      LoanStatus.ACTIVE, LoanStatus.RECALLED,
                                      LoanStatus.RETURNED, LoanStatus.PURCHASED, LoanStatus.EXPIRED):
        raise ValueError("loan is no longer awaiting consent")
    if not proposal.submitted_on <= on <= proposal.expires_on:
        raise ValueError("loan decision is outside the offer dates")
    return _append(book, _event(proposal, actor_id, on, kind))


def expire_loan_proposals(book: LoanBook, on: WorldDate) -> LoanBook:
    if not isinstance(book, LoanBook) or not isinstance(on, WorldDate):
        raise TypeError("loan expiry requires a LoanBook and WorldDate")
    updated = book
    for proposal in book.proposals:
        if (loan_status(updated, proposal.loan_id) in
                (LoanStatus.OFFERED, LoanStatus.OWNER_ACCEPTED, LoanStatus.PLAYER_ACCEPTED)
                and on > proposal.expires_on):
            updated = _append(updated, _event(
                proposal, proposal.borrower_club_id, on, LoanEventKind.OFFER_EXPIRED,
            ))
    return updated


def _require_medical(assessment: TransferMedicalAssessment, player_id: str, on: WorldDate) -> None:
    if not isinstance(assessment, TransferMedicalAssessment) or assessment.player_id != player_id:
        raise ValueError("transaction needs a matching player medical assessment")
    if not assessment.valid_on(on) or assessment.outcome is not MedicalOutcome.CLEARED:
        raise ValueError("player has no current clear medical assessment")


def activate_loan(book: LoanBook, ledger: EconomyLedger, registrations: RegistrationBook,
                  loan_id: str, assessment: TransferMedicalAssessment,
                  on: WorldDate) -> tuple[LoanBook, EconomyLedger, RegistrationBook]:
    if not isinstance(book, LoanBook) or not isinstance(ledger, EconomyLedger) or not isinstance(registrations, RegistrationBook):
        raise TypeError("loan activation requires its three domain books")
    if not isinstance(on, WorldDate):
        raise TypeError("loan activation requires a WorldDate")
    if not isinstance(assessment, TransferMedicalAssessment):
        raise TypeError("loan activation requires a medical assessment")
    validate_id(loan_id, kind="loan ID")
    proposal = next((item for item in book.proposals if item.loan_id == loan_id), None)
    if proposal is None:
        raise KeyError(f"unknown loan: {loan_id}")
    status = loan_status(book, loan_id)
    prior = next((item for item in book.events if item.loan_id == loan_id
                  and item.kind is LoanEventKind.ACTIVATED), None)
    if prior is not None:
        expected_fee_id = (derive_id("obligation", "p15c-loan-fee-v1", proposal.loan_id)
                           if proposal.loan_fee_minor else None)
        fee = next((item for item in ledger.obligations
                    if item.obligation_id == expected_fee_id), None)
        fee_event = next((item for item in book.events if item.loan_id == loan_id
                          and item.kind is LoanEventKind.LOAN_FEE_SCHEDULED), None)
        same_decision = (
            prior.at == on and prior.medical_assessment_id == assessment.assessment_id
            and prior.obligation_id == expected_fee_id
                and prior.registration_check_ids == tuple(check_registration(
                    registrations, comp, proposal.borrower_club_id, proposal.player_id, on,
                    moving_from_club_id=proposal.owner_club_id).check_id
                    for comp in proposal.competition_ids)
        )
        if same_decision:
            fee_is_valid = not proposal.loan_fee_minor or (
                fee is not None and fee.debtor_id == proposal.borrower_club_id
                and fee.creditor_id == proposal.owner_club_id
                and fee.currency == proposal.currency
                and fee.amount_minor == proposal.loan_fee_minor and fee.due_on == on
                and fee.kind is ObligationKind.LOAN_FEE
                and fee_event is not None and fee_event.obligation_id == expected_fee_id
            )
            registration_state_matches = (
                (status is LoanStatus.ACTIVE and _registration_is_active(registrations, proposal))
                or (status in (LoanStatus.RECALLED, LoanStatus.RETURNED, LoanStatus.EXPIRED)
                    and _registration_is_returned(registrations, proposal))
                or (status is LoanStatus.PURCHASED
                    and _registration_is_purchased(registrations, proposal))
            )
            if registration_state_matches and fee_is_valid:
                return book, ledger, registrations
            raise ValueError("loan activation replay is missing its registration or fee evidence")
        raise ValueError("loan was already activated with different evidence")
    if status is not LoanStatus.AGREED:
        raise ValueError("loan requires owner and player consent before activation")
    if not proposal.starts_on <= on < proposal.ends_on:
        raise ValueError("loan activation must occur inside its agreed term")
    _require_medical(assessment, proposal.player_id, on)
    contract = next((item for item in ledger.contracts if item.contract_id == proposal.employment_contract_id), None)
    if (contract is None or not contract.active_on(on)
            or employment_at(ledger, proposal.player_id, on) != contract
            or contract.expires_on < proposal.ends_on):
        raise ValueError("owner employment contract must cover the active loan term")
    checks = tuple(check_registration(
        registrations, competition_id, proposal.borrower_club_id, proposal.player_id, on,
        moving_from_club_id=proposal.owner_club_id,
    ) for competition_id in proposal.competition_ids)
    if any(not item.eligible for item in checks):
        detail = ", ".join(f"{item.competition_id}:{reason}" for item in checks for reason in item.reasons)
        raise ValueError("loan registration failed: " + detail)
    updated_registrations = register_loan_player(
        registrations, proposal.player_id, proposal.owner_club_id,
        proposal.borrower_club_id, proposal.competition_ids, on,
    )
    fee_id: str | None = None
    updated_ledger = ledger
    events: tuple[LoanEvent, ...] = ()
    if proposal.loan_fee_minor:
        fee_id = derive_id("obligation", "p15c-loan-fee-v1", proposal.loan_id)
        updated_ledger = _add_loan_obligation(updated_ledger, PaymentObligation(
            fee_id, proposal.borrower_club_id, proposal.owner_club_id,
            proposal.currency, proposal.loan_fee_minor, on,
            ObligationKind.LOAN_FEE,
        ))
    activation = _event(proposal, proposal.borrower_club_id, on, LoanEventKind.ACTIVATED,
                        obligation_id=fee_id, assessment_id=assessment.assessment_id,
                        registration_checks=tuple(item.check_id for item in checks))
    events += (activation,)
    if fee_id is not None:
        events += (_event(proposal, proposal.borrower_club_id, on,
                          LoanEventKind.LOAN_FEE_SCHEDULED, obligation_id=fee_id),)
    updated_book = LoanBook(book.proposals, book.events + events)
    return updated_book, updated_ledger, updated_registrations


def _add_loan_obligation(ledger: EconomyLedger, obligation: PaymentObligation) -> EconomyLedger:
    from games.touchline.esb.economy.ledger import add_obligation
    return add_obligation(ledger, obligation)


def accrue_loan_wage_share(book: LoanBook, ledger: EconomyLedger, loan_id: str,
                           payroll_date: WorldDate) -> tuple[LoanBook, EconomyLedger, PaymentObligation | None]:
    if not isinstance(book, LoanBook) or not isinstance(ledger, EconomyLedger) or not isinstance(payroll_date, WorldDate):
        raise TypeError("loan wage contribution requires books and a payroll date")
    validate_id(loan_id, kind="loan ID")
    proposal = next((item for item in book.proposals if item.loan_id == loan_id), None)
    if proposal is None:
        raise KeyError(f"unknown loan: {loan_id}")
    if not proposal.starts_on <= payroll_date < proposal.ends_on:
        raise ValueError("loan wage share only accrues while the loan is active")
    contract = next((item for item in ledger.contracts if item.contract_id == proposal.employment_contract_id), None)
    if (contract is None or not contract.active_on(payroll_date)
            or employment_at(ledger, proposal.player_id, payroll_date) != contract):
        raise ValueError("owner employment contract is not active on the loan payroll date")
    amount = contract.wage_per_payroll_minor * proposal.borrower_wage_share_bps // _BPS
    existing_event = next((item for item in book.events if item.loan_id == loan_id
                           and item.kind is LoanEventKind.WAGE_SHARE_SCHEDULED
                           and item.at == payroll_date), None)
    if existing_event is not None:
        obligation = next((item for item in ledger.obligations
                           if item.obligation_id == existing_event.obligation_id), None)
        if amount == 0 or obligation is None:
            raise ValueError("recorded loan wage event is missing a payable amount")
        if (obligation.debtor_id != proposal.borrower_club_id
                or obligation.creditor_id != proposal.owner_club_id
                or obligation.currency != proposal.currency
                or obligation.amount_minor != amount or obligation.due_on != payroll_date
                or obligation.kind is not ObligationKind.LOAN_WAGE_CONTRIBUTION):
            raise ValueError("recorded loan wage event conflicts with its ledger obligation")
        return book, ledger, obligation
    if loan_status(book, loan_id) is not LoanStatus.ACTIVE:
        raise ValueError("loan wage share only accrues while the loan is active")
    if book.events and payroll_date < book.events[-1].at:
        raise ValueError("loan wage shares must retain calendar chronology")
    if amount == 0:
        return book, ledger, None
    obligation_id = derive_id("obligation", "p15c-loan-wage-share-v1", proposal.loan_id,
                              payroll_date.isoformat)
    obligation = PaymentObligation(
        obligation_id, proposal.borrower_club_id, proposal.owner_club_id,
        proposal.currency, amount, payroll_date,
        ObligationKind.LOAN_WAGE_CONTRIBUTION,
    )
    updated_ledger = _add_loan_obligation(ledger, obligation)
    updated_book = _append(book, _event(
        proposal, proposal.borrower_club_id, payroll_date,
        LoanEventKind.WAGE_SHARE_SCHEDULED, obligation_id=obligation_id,
    ))
    return updated_book, updated_ledger, obligation


def _move_registration_back(book: RegistrationBook, proposal: LoanProposal) -> RegistrationBook:
    return return_loan_player(book, proposal.player_id, proposal.owner_club_id,
                              proposal.borrower_club_id, proposal.competition_ids)


def _registration_is_returned(registrations: RegistrationBook, proposal: LoanProposal) -> bool:
    for competition_id in proposal.competition_ids:
        owner = next((item for item in registrations.squads
                      if item.competition_id == competition_id
                      and item.club_id == proposal.owner_club_id), None)
        borrower = next((item for item in registrations.squads
                         if item.competition_id == competition_id
                         and item.club_id == proposal.borrower_club_id), None)
        if (owner is None or borrower is None
                or proposal.player_id not in owner.registered_player_ids
                or proposal.player_id in owner.loan_reserve_player_ids
                or proposal.player_id in borrower.registered_player_ids):
            return False
    return True


def _registration_is_purchased(registrations: RegistrationBook, proposal: LoanProposal) -> bool:
    for competition_id in proposal.competition_ids:
        owner = next((item for item in registrations.squads
                      if item.competition_id == competition_id
                      and item.club_id == proposal.owner_club_id), None)
        borrower = next((item for item in registrations.squads
                         if item.competition_id == competition_id
                         and item.club_id == proposal.borrower_club_id), None)
        if (owner is None or borrower is None
                or proposal.player_id in owner.registered_player_ids
                or proposal.player_id in owner.loan_reserve_player_ids
                or proposal.player_id not in borrower.registered_player_ids):
            return False
    return True


def _registration_is_active(registrations: RegistrationBook, proposal: LoanProposal) -> bool:
    for competition_id in proposal.competition_ids:
        owner = next((item for item in registrations.squads
                      if item.competition_id == competition_id
                      and item.club_id == proposal.owner_club_id), None)
        borrower = next((item for item in registrations.squads
                         if item.competition_id == competition_id
                         and item.club_id == proposal.borrower_club_id), None)
        if (owner is None or borrower is None
                or proposal.player_id not in owner.loan_reserve_player_ids
                or proposal.player_id in owner.registered_player_ids
                or proposal.player_id not in borrower.registered_player_ids):
            return False
    return True


def recall_loan(book: LoanBook, registrations: RegistrationBook, loan_id: str,
                actor_id: str, on: WorldDate) -> tuple[LoanBook, RegistrationBook]:
    if (not isinstance(book, LoanBook) or not isinstance(registrations, RegistrationBook)
            or not isinstance(on, WorldDate)):
        raise TypeError("loan recall requires a LoanBook, RegistrationBook and WorldDate")
    validate_id(loan_id, kind="loan ID")
    validate_id(actor_id, kind="loan recall actor ID")
    proposal = next((item for item in book.proposals if item.loan_id == loan_id), None)
    if proposal is None:
        raise KeyError(f"unknown loan: {loan_id}")
    if actor_id != proposal.owner_club_id:
        raise ValueError("only the owning club can recall its player")
    if proposal.recall_from is None or on < proposal.recall_from or on >= proposal.ends_on:
        raise ValueError("recall is unavailable on the requested date")
    prior = next((item for item in book.events if item.loan_id == loan_id
                  and item.kind is LoanEventKind.RECALLED), None)
    if prior is not None:
        if prior.actor_id == actor_id and prior.at == on:
            if _registration_is_returned(registrations, proposal):
                return book, registrations
            raise ValueError("loan recall retry conflicts with its completed registration move")
        if loan_status(book, loan_id) is not LoanStatus.ACTIVE:
            raise ValueError("only an active loan can be recalled")
        raise ValueError("loan recall retry conflicts with its completed registration move")
    if loan_status(book, loan_id) is not LoanStatus.ACTIVE:
        raise ValueError("only an active loan can be recalled")
    if not _registration_is_active(registrations, proposal):
        raise ValueError("loan recall requires the borrower's active registration state")
    updated_registrations = _move_registration_back(registrations, proposal)
    return _append(book, _event(proposal, actor_id, on, LoanEventKind.RECALLED)), updated_registrations


def return_loan(book: LoanBook, registrations: RegistrationBook, loan_id: str,
                on: WorldDate) -> tuple[LoanBook, RegistrationBook]:
    if (not isinstance(book, LoanBook) or not isinstance(registrations, RegistrationBook)
            or not isinstance(on, WorldDate)):
        raise TypeError("loan return requires a LoanBook, RegistrationBook and WorldDate")
    validate_id(loan_id, kind="loan ID")
    proposal = next((item for item in book.proposals if item.loan_id == loan_id), None)
    if proposal is None:
        raise KeyError(f"unknown loan: {loan_id}")
    prior = next((item for item in book.events if item.loan_id == loan_id
                  and item.kind in (LoanEventKind.RETURNED, LoanEventKind.EXPIRED)), None)
    if prior is not None:
        if prior.actor_id == proposal.owner_club_id and prior.at == on:
            if _registration_is_returned(registrations, proposal):
                return book, registrations
            raise ValueError("loan return retry conflicts with its completed registration move")
        if loan_status(book, loan_id) is not LoanStatus.ACTIVE:
            raise ValueError("only an active loan can be returned")
        raise ValueError("loan return retry conflicts with its completed registration move")
    if loan_status(book, loan_id) is not LoanStatus.ACTIVE:
        raise ValueError("only an active loan can be returned")
    if on < proposal.ends_on:
        raise ValueError("loan cannot be returned before its agreed end date")
    if not _registration_is_active(registrations, proposal):
        raise ValueError("loan return requires the borrower's active registration state")
    updated_registrations = _move_registration_back(registrations, proposal)
    kind = LoanEventKind.EXPIRED if on == proposal.ends_on else LoanEventKind.RETURNED
    return _append(book, _event(proposal, proposal.owner_club_id, on, kind)), updated_registrations


def exercise_purchase_option(book: LoanBook, ledger: EconomyLedger,
                             registrations: RegistrationBook, loan_id: str,
                             assessment: TransferMedicalAssessment, on: WorldDate
                             ) -> tuple[LoanBook, EconomyLedger, RegistrationBook, EmploymentContract]:
    if (not isinstance(book, LoanBook) or not isinstance(ledger, EconomyLedger)
            or not isinstance(registrations, RegistrationBook)):
        raise TypeError("purchase exercise requires loan, economy and registration books")
    if not isinstance(on, WorldDate):
        raise TypeError("purchase exercise requires a WorldDate")
    if not isinstance(assessment, TransferMedicalAssessment):
        raise TypeError("purchase exercise requires a medical assessment")
    validate_id(loan_id, kind="loan ID")
    proposal = next((item for item in book.proposals if item.loan_id == loan_id), None)
    if proposal is None:
        raise KeyError(f"unknown loan: {loan_id}")
    option = proposal.purchase_option
    if option is None or not option.opens_on <= on <= option.expires_on:
        raise ValueError("no purchase option is exercisable on this date")
    expected_contract_id = derive_id(
        "employment-contract", "p15c-loan-purchase-v1", proposal.loan_id, on.isoformat,
    )
    expected_contract = EmploymentContract(
        expected_contract_id, proposal.borrower_club_id, proposal.player_id, on, on,
        WorldDate(on.day + timedelta(weeks=option.contract_weeks)),
        proposal.currency, option.wage_per_payroll_minor,
    )
    fee_id = derive_id("obligation", "p15c-loan-purchase-fee-v1", proposal.loan_id)
    prior_purchase = next((item for item in book.events
                           if item.loan_id == loan_id and item.kind is LoanEventKind.PURCHASED), None)
    if prior_purchase is not None:
        _require_medical(assessment, proposal.player_id, on)
        checks = tuple(check_existing_registration(
            registrations, competition_id, proposal.borrower_club_id,
            proposal.player_id, on,
        ) for competition_id in proposal.competition_ids)
        existing_contract = next((item for item in ledger.contracts
                                  if item.contract_id == expected_contract_id), None)
        purchase_fee = next((item for item in ledger.obligations
                             if item.obligation_id == fee_id), None)
        owner_reservations = tuple(
            next((item for item in registrations.squads
                  if item.competition_id == competition_id
                  and item.club_id == proposal.owner_club_id), None)
            for competition_id in proposal.competition_ids
        )
        exact_replay = (
            prior_purchase.actor_id == proposal.borrower_club_id
            and prior_purchase.at == on
            and prior_purchase.medical_assessment_id == assessment.assessment_id
            and prior_purchase.registration_check_ids == tuple(item.check_id for item in checks)
            and all(item.eligible for item in checks)
            and prior_purchase.replacement_contract_id == expected_contract_id
            and prior_purchase.obligation_id == fee_id
            and existing_contract == expected_contract
            and purchase_fee is not None
            and purchase_fee.debtor_id == proposal.borrower_club_id
            and purchase_fee.creditor_id == proposal.owner_club_id
            and purchase_fee.currency == proposal.currency
            and purchase_fee.amount_minor == option.fee_minor
            and purchase_fee.due_on == on
            and purchase_fee.kind is ObligationKind.PURCHASE_FEE
            and any(item.from_contract_id == proposal.employment_contract_id
                    and item.to_contract_id == expected_contract_id
                    and item.completed_on == on for item in ledger.contract_transfers)
            and all(item is not None and proposal.player_id not in item.loan_reserve_player_ids
                    for item in owner_reservations)
        )
        if exact_replay:
            return book, ledger, registrations, existing_contract
        raise ValueError("loan purchase retry conflicts with its completed transaction")
    if loan_status(book, loan_id) is not LoanStatus.ACTIVE:
        raise ValueError("purchase option requires an active loan")
    _require_medical(assessment, proposal.player_id, on)
    original = next((item for item in ledger.contracts
                     if item.contract_id == proposal.employment_contract_id), None)
    if (original is None or original.club_id != proposal.owner_club_id
            or not original.active_on(on)
            or employment_at(ledger, proposal.player_id, on) != original):
        raise ValueError("purchase must replace the owner's active employment contract")
    if original.currency != proposal.currency:
        raise ValueError("purchase and employment currencies differ")
    checks = tuple(check_existing_registration(registrations, comp, proposal.borrower_club_id,
                                               proposal.player_id, on)
                   for comp in proposal.competition_ids)
    if any(not item.eligible for item in checks):
        raise ValueError("borrower registration no longer permits the purchase")
    roster_state = tuple(
        next((item for item in registrations.squads
              if item.competition_id == comp and item.club_id == proposal.borrower_club_id), None)
        for comp in proposal.competition_ids
    )
    if any(item is None or proposal.player_id not in item.registered_player_ids for item in roster_state):
        raise ValueError("purchased player must still be registered at the borrower")
    new_contract = expected_contract
    updated_ledger, _ = _novate_employment(ledger, original.contract_id, new_contract)
    from games.touchline.esb.economy.ledger import add_obligation
    updated_ledger = add_obligation(updated_ledger, PaymentObligation(
        fee_id, proposal.borrower_club_id, proposal.owner_club_id,
        proposal.currency, option.fee_minor, on, ObligationKind.PURCHASE_FEE,
    ))
    updated_registrations = purchase_loan_player(
        registrations, proposal.player_id, proposal.owner_club_id,
        proposal.borrower_club_id, proposal.competition_ids,
    )
    purchased = _event(proposal, proposal.borrower_club_id, on, LoanEventKind.PURCHASED,
                       obligation_id=fee_id, assessment_id=assessment.assessment_id,
                       registration_checks=tuple(item.check_id for item in checks),
                       replacement_contract_id=new_contract.contract_id)
    updated_book = _append(book, purchased)
    return updated_book, updated_ledger, updated_registrations, new_contract


def scheduled_loan_obligation_ids(book: LoanBook, loan_id: str) -> tuple[str, ...]:
    """Return the immutable fee, payroll contribution and purchase obligation IDs."""
    if not isinstance(book, LoanBook):
        raise TypeError("loan obligations require a LoanBook")
    validate_id(loan_id, kind="loan ID")
    loan_status(book, loan_id)
    return tuple(item.obligation_id for item in book.events
                 if item.loan_id == loan_id and item.obligation_id is not None
                 and item.kind in (LoanEventKind.LOAN_FEE_SCHEDULED,
                                   LoanEventKind.WAGE_SHARE_SCHEDULED,
                                   LoanEventKind.PURCHASED))


__all__ = [
    "LoanBook", "LoanEvent", "LoanEventKind", "LoanProposal", "LoanStatus",
    "PurchaseOption", "activate_loan", "accrue_loan_wage_share",
    "exercise_purchase_option", "loan_status", "scheduled_loan_obligation_ids",
    "expire_loan_proposals", "propose_loan", "recall_loan", "respond_to_loan", "return_loan",
]
