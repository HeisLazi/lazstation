"""Atomic annual player lifecycle integration across population, contracts and registration (P16d-b)."""

from __future__ import annotations

from dataclasses import dataclass

from games.touchline.esb.economy.ledger import (
    ContractTermination,
    ContractTerminationReason,
    EconomyLedger,
    EmploymentContract,
    ObligationKind,
    PaymentObligation,
    add_employment_contract,
    employment_at,
    terminate_employment,
)
from games.touchline.esb.economy.loans import (
    LoanBook,
    LoanEventKind,
    LoanStatus,
    loan_status,
)
from games.touchline.esb.ids import derive_id, validate_id
from games.touchline.esb.serialization import SerializationError, dumps, loads
from games.touchline.esb.time import WorldDate
from games.touchline.esb.world.population import (
    IntakeCandidate,
    PopulationBoundaryReceipt,
    PopulationPolicy,
    WorldPopulationState,
    _BoundaryRequest,
    _hash_record as _canonical_record_hash,
    advance_population,
)
from games.touchline.esb.world.registration import (
    ClubCompetitionSquad,
    RegistrationBook,
    RegistrationCheck,
    _release_retired_player,
    _loan_registration_states,
    register_new_player,
)


@dataclass(frozen=True)
class AcademyArrivalTerms:
    """Explicit employment and registration facts for one accepted candidate."""

    candidate_id: str
    contract: EmploymentContract
    trained_at_club_ids: tuple[str, ...]
    competition_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        validate_id(self.candidate_id, kind="academy continuity candidate ID")
        if not isinstance(self.contract, EmploymentContract):
            raise TypeError("academy arrival requires explicit employment terms")
        if not isinstance(self.trained_at_club_ids, tuple):
            raise TypeError("academy arrival training history must be immutable")
        if not isinstance(self.competition_ids, tuple) or not self.competition_ids:
            raise ValueError("academy arrival requires at least one competition registration")
        for club_id in self.trained_at_club_ids:
            validate_id(club_id, kind="academy training club ID")
        for competition_id in self.competition_ids:
            validate_id(competition_id, kind="academy registration competition ID")
        if self.trained_at_club_ids != tuple(sorted(set(self.trained_at_club_ids))):
            raise ValueError("academy training history must be unique and ID-ordered")
        if self.competition_ids != tuple(sorted(set(self.competition_ids))):
            raise ValueError("academy competitions must be unique and ID-ordered")


@dataclass(frozen=True)
class ContinuityBoundaryRequest:
    boundary_on: WorldDate
    policy: PopulationPolicy
    new_candidates: tuple[IntakeCandidate, ...] = ()
    academy_arrivals: tuple[AcademyArrivalTerms, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.boundary_on, WorldDate):
            raise TypeError("continuity boundary requires an explicit WorldDate")
        if not isinstance(self.policy, PopulationPolicy):
            raise TypeError("continuity boundary requires an explicit population policy")
        if (not isinstance(self.new_candidates, tuple)
                or any(not isinstance(item, IntakeCandidate) for item in self.new_candidates)):
            raise TypeError("continuity candidates must be an immutable tuple")
        if (not isinstance(self.academy_arrivals, tuple)
                or any(not isinstance(item, AcademyArrivalTerms) for item in self.academy_arrivals)):
            raise TypeError("academy arrival terms must be an immutable tuple")
        if tuple(item.candidate_id for item in self.new_candidates) != tuple(sorted(
                item.candidate_id for item in self.new_candidates)):
            raise ValueError("continuity candidates must be ID-ordered")
        if tuple(item.candidate_id for item in self.academy_arrivals) != tuple(sorted(
                item.candidate_id for item in self.academy_arrivals)):
            raise ValueError("academy arrival terms must be ID-ordered")
        if len({item.candidate_id for item in self.academy_arrivals}) != len(self.academy_arrivals):
            raise ValueError("academy arrival terms cannot repeat a candidate")


@dataclass(frozen=True)
class _ContinuitySnapshot:
    population: WorldPopulationState
    economy: EconomyLedger
    registration: RegistrationBook
    loans: LoanBook


@dataclass(frozen=True)
class _ContinuityReceiptContent:
    boundary_id: str
    sequence: int
    request: ContinuityBoundaryRequest
    request_sha256: str
    source_state_sha256: str
    result_state_sha256: str
    population_boundary_id: str
    retired_player_ids: tuple[str, ...]
    terminated_contract_ids: tuple[str, ...]
    academy_contract_ids: tuple[str, ...]
    registration_checks: tuple[RegistrationCheck, ...]


@dataclass(frozen=True)
class ContinuityBoundaryReceipt:
    boundary_id: str
    sequence: int
    request: ContinuityBoundaryRequest
    request_sha256: str
    source_state_sha256: str
    result_state_sha256: str
    population_boundary_id: str
    retired_player_ids: tuple[str, ...]
    terminated_contract_ids: tuple[str, ...]
    academy_contract_ids: tuple[str, ...]
    registration_checks: tuple[RegistrationCheck, ...]
    receipt_sha256: str

    @property
    def boundary_on(self) -> WorldDate:
        return self.request.boundary_on

    def __post_init__(self) -> None:
        validate_id(self.boundary_id, kind="continuity boundary ID")
        validate_id(self.population_boundary_id, kind="population boundary ID")
        if type(self.sequence) is not int or self.sequence < 0:
            raise ValueError("continuity boundary sequence must be a non-negative integer")
        if not isinstance(self.request, ContinuityBoundaryRequest):
            raise TypeError("continuity receipt requires its complete request")
        for label, value in (
            ("request", self.request_sha256),
            ("source continuity state", self.source_state_sha256),
            ("result continuity state", self.result_state_sha256),
            ("continuity receipt", self.receipt_sha256),
        ):
            _validate_sha256(value, f"{label} fingerprint")
        for label, values in (
            ("retired players", self.retired_player_ids),
            ("terminated contracts", self.terminated_contract_ids),
            ("academy contracts", self.academy_contract_ids),
        ):
            if not isinstance(values, tuple):
                raise TypeError(f"continuity {label} must be an immutable tuple")
            for value in values:
                validate_id(value, kind=f"continuity {label} ID")
            if values != tuple(sorted(set(values))):
                raise ValueError(f"continuity {label} must be unique and ID-ordered")
        if (not isinstance(self.registration_checks, tuple)
                or any(not isinstance(item, RegistrationCheck) for item in self.registration_checks)):
            raise TypeError("continuity registration evidence must be immutable checks")
        check_ids = tuple(item.check_id for item in self.registration_checks)
        if check_ids != tuple(sorted(set(check_ids))):
            raise ValueError("continuity registration checks must be unique and ID-ordered")
        content = _ContinuityReceiptContent(
            self.boundary_id,
            self.sequence,
            self.request,
            self.request_sha256,
            self.source_state_sha256,
            self.result_state_sha256,
            self.population_boundary_id,
            self.retired_player_ids,
            self.terminated_contract_ids,
            self.academy_contract_ids,
            self.registration_checks,
        )
        if self.request_sha256 != _sha256(self.request):
            raise ValueError("continuity request fingerprint does not match its request")
        if self.receipt_sha256 != _sha256(content):
            raise ValueError("continuity receipt does not match its sealed evidence")


@dataclass(frozen=True)
class _ContinuityUpdateContent:
    update_id: str
    sequence: int
    occurred_on: WorldDate
    changed_components: tuple[str, ...]
    economy_event_ids: tuple[str, ...]
    loan_event_ids: tuple[str, ...]
    registration_player_ids: tuple[str, ...]
    source_state_sha256: str
    result_state_sha256: str


@dataclass(frozen=True)
class ContinuityStateUpdate:
    """Sealed dated payroll, loan or loan-registration mutation between boundaries."""

    update_id: str
    sequence: int
    occurred_on: WorldDate
    changed_components: tuple[str, ...]
    economy_event_ids: tuple[str, ...]
    loan_event_ids: tuple[str, ...]
    registration_player_ids: tuple[str, ...]
    source_state_sha256: str
    result_state_sha256: str
    receipt_sha256: str

    def __post_init__(self) -> None:
        validate_id(self.update_id, kind="continuity update ID")
        if type(self.sequence) is not int or self.sequence < 0:
            raise ValueError("continuity update sequence must be a non-negative integer")
        if not isinstance(self.occurred_on, WorldDate):
            raise TypeError("continuity update requires an explicit WorldDate")
        if (not isinstance(self.changed_components, tuple)
                or not self.changed_components
                or self.changed_components != tuple(sorted(set(self.changed_components)))
                or not set(self.changed_components) <= {"economy", "loans", "registration"}):
            raise ValueError("continuity update components must be unique and ID-ordered")
        for label, values in (("economy events", self.economy_event_ids),
                              ("loan events", self.loan_event_ids)):
            if not isinstance(values, tuple):
                raise TypeError(f"continuity {label} must be immutable")
            for value in values:
                validate_id(value, kind=f"continuity {label} ID")
            if values != tuple(sorted(set(values))):
                raise ValueError(f"continuity {label} must be unique and ID-ordered")
        if not isinstance(self.registration_player_ids, tuple):
            raise TypeError("continuity registration player evidence must be immutable")
        for player_id in self.registration_player_ids:
            validate_id(player_id, kind="continuity registration player ID")
        if self.registration_player_ids != tuple(sorted(set(self.registration_player_ids))):
            raise ValueError("continuity registration player evidence must be unique and ID-ordered")
        if "economy" in self.changed_components and not self.economy_event_ids:
            raise ValueError("economy continuity update requires dated ledger evidence")
        if "economy" not in self.changed_components and self.economy_event_ids:
            raise ValueError("economy event evidence requires an economy component change")
        if "loans" in self.changed_components and not self.loan_event_ids:
            raise ValueError("loan continuity update requires dated loan-event evidence")
        if "loans" not in self.changed_components and self.loan_event_ids:
            raise ValueError("loan event evidence requires a loan component change")
        if "registration" in self.changed_components and "loans" not in self.changed_components:
            raise ValueError("between-boundary registration changes require a loan transition")
        if ("registration" in self.changed_components
                and not self.registration_player_ids):
            raise ValueError("registration continuity update requires affected player evidence")
        if ("registration" not in self.changed_components
                and self.registration_player_ids):
            raise ValueError("registration player evidence requires a registration change")
        for label, value in (("source continuity state", self.source_state_sha256),
                             ("result continuity state", self.result_state_sha256),
                             ("continuity update receipt", self.receipt_sha256)):
            _validate_sha256(value, f"{label} fingerprint")
        content = _ContinuityUpdateContent(
            self.update_id,
            self.sequence,
            self.occurred_on,
            self.changed_components,
            self.economy_event_ids,
            self.loan_event_ids,
            self.registration_player_ids,
            self.source_state_sha256,
            self.result_state_sha256,
        )
        if self.receipt_sha256 != _sha256(content):
            raise ValueError("continuity update does not match its sealed evidence")


@dataclass(frozen=True)
class AnnualContinuityState:
    world_id: str
    population: WorldPopulationState
    economy: EconomyLedger
    registration: RegistrationBook
    loans: LoanBook
    transitions: tuple[ContinuityBoundaryReceipt, ...] = ()
    state_updates: tuple[ContinuityStateUpdate, ...] = ()
    schema_version: int = 2

    def __post_init__(self) -> None:
        validate_id(self.world_id, kind="continuity world ID")
        if not isinstance(self.population, WorldPopulationState):
            raise TypeError("continuity state requires a WorldPopulationState")
        if not isinstance(self.economy, EconomyLedger):
            raise TypeError("continuity state requires an EconomyLedger")
        if not isinstance(self.registration, RegistrationBook):
            raise TypeError("continuity state requires a RegistrationBook")
        if not isinstance(self.loans, LoanBook):
            raise TypeError("continuity state requires a LoanBook")
        if self.population.world_id != self.world_id:
            raise ValueError("continuity and population world IDs must match")
        if type(self.schema_version) is not int or self.schema_version != 2:
            raise ValueError("unsupported annual continuity schema version")
        if (not isinstance(self.transitions, tuple)
                or any(not isinstance(item, ContinuityBoundaryReceipt) for item in self.transitions)):
            raise TypeError("continuity transitions must be immutable receipts")
        if (not isinstance(self.state_updates, tuple)
                or any(not isinstance(item, ContinuityStateUpdate) for item in self.state_updates)):
            raise TypeError("continuity state updates must be immutable receipts")
        dates = tuple(item.boundary_on for item in self.transitions)
        if dates != tuple(sorted(set(dates))):
            raise ValueError("continuity receipts must be unique and chronologically ordered")
        if len(self.population.transitions) != len(self.transitions):
            raise ValueError("continuity and population boundary histories must stay aligned")
        population_players = {item.player_id: item for item in self.population.players}
        training_records = {item.player_id: item for item in self.registration.player_training}
        if set(training_records) != set(population_players):
            raise ValueError("continuity population and registration player histories must align")
        for contract in self.economy.contracts:
            player = population_players.get(contract.player_id)
            if player is None:
                raise ValueError("continuity employment references a player outside its population")
            if contract.club_id != player.club_id:
                raise ValueError("continuity employment club must match its population player")
        for termination in self.economy.contract_terminations:
            contract = next(item for item in self.economy.contracts
                            if item.contract_id == termination.contract_id)
            player = population_players[contract.player_id]
            if player.retired_on != termination.terminated_on:
                raise ValueError("continuity retirement termination must match population retirement")
        for squad in self.registration.squads:
            for player_id in squad.registered_player_ids + squad.loan_reserve_player_ids:
                if not population_players[player_id].active:
                    raise ValueError("retired population players cannot hold current registration slots")
        for proposal in self.loans.proposals:
            player = population_players.get(proposal.player_id)
            if player is None or player.club_id != proposal.owner_club_id:
                raise ValueError("continuity loan owner must match its population player")
        for index, receipt in enumerate(self.transitions):
            population_receipt = self.population.transitions[index]
            if (receipt.population_boundary_id != population_receipt.boundary_id
                    or receipt.boundary_on != population_receipt.boundary_on):
                raise ValueError("continuity receipt does not match its population boundary")
            expected_boundary_id = derive_id(
                "continuity-boundary", "p16d-continuity-boundary-v1",
                self.world_id, receipt.boundary_on.isoformat,
            )
            if receipt.boundary_id != expected_boundary_id:
                raise ValueError("continuity boundary ID does not match its world and date")
            expected_population_request = _canonical_record_hash(_BoundaryRequest(
                receipt.request.boundary_on,
                receipt.request.policy,
                receipt.request.new_candidates,
            ))
            if (receipt.request.policy != population_receipt.policy
                    or population_receipt.request_sha256 != expected_population_request):
                raise ValueError("continuity request does not match the applied population policy and candidates")
            retired_ids = tuple(sorted(
                item.player_id for item in population_receipt.retirement_decisions
                if item.retired
            ))
            if receipt.retired_player_ids != retired_ids:
                raise ValueError("continuity retirement receipt does not match its population decisions")
            transferred_before = {
                item.from_contract_id for item in self.economy.contract_transfers
                if item.completed_on <= receipt.boundary_on
            }
            expected_terminations = tuple(sorted(
                contract.contract_id
                for player_id in retired_ids
                for contract in self.economy.contracts
                if contract.player_id == player_id
                and contract.active_on(receipt.boundary_on)
                and contract.contract_id not in transferred_before
            ))
            if receipt.terminated_contract_ids != expected_terminations:
                raise ValueError("continuity retirement receipt does not list the effective contracts")
            terminations = {item.termination_id: item for item in self.economy.contract_terminations}
            for contract_id in receipt.terminated_contract_ids:
                expected_id = _termination_id(contract_id, receipt.boundary_on)
                termination = terminations.get(expected_id)
                if (termination is None
                        or termination.contract_id != contract_id
                        or termination.terminated_on != receipt.boundary_on
                        or termination.reason is not ContractTerminationReason.RETIREMENT):
                    raise ValueError("continuity retirement receipt lost its dated termination")
            contracts = {item.contract_id: item for item in self.economy.contracts}
            accepted = {
                item.candidate_id: item for item in population_receipt.intake_decisions
                if item.outcome.value == "accepted"
            }
            arrivals = {item.candidate_id: item for item in receipt.request.academy_arrivals}
            if set(accepted) != set(arrivals):
                raise ValueError("continuity intake terms do not match accepted candidates")
            expected_contract_ids = tuple(sorted(
                arrivals[key].contract.contract_id for key in arrivals
            ))
            if receipt.academy_contract_ids != expected_contract_ids:
                raise ValueError("continuity intake contracts do not match their explicit terms")
            players = {item.player_id: item for item in self.population.players}
            training = {item.player_id: item for item in self.registration.player_training}
            for candidate_id, terms in arrivals.items():
                accepted_player_id = accepted[candidate_id].player_id
                player = players.get(accepted_player_id)
                if player is None:
                    raise ValueError("continuity intake receipt lost its accepted player")
                decision = accepted[candidate_id]
                if (player.intake_candidate_id != candidate_id
                        or player.club_id != decision.club_id
                        or player.profile.identity.birth_date != decision.born_on
                        or player.joined_on != receipt.boundary_on):
                    raise ValueError("continuity intake decision does not match the retained player")
                if contracts.get(terms.contract.contract_id) != terms.contract:
                    raise ValueError("continuity intake contract terms do not match the retained contract")
                if (terms.contract.player_id != player.player_id
                        or terms.contract.club_id != player.club_id
                        or terms.contract.starts_on != receipt.boundary_on
                        or terms.contract.agreed_on > receipt.boundary_on):
                    raise ValueError("continuity intake contract does not match its accepted player")
                retained_training = training.get(player.player_id)
                if (retained_training is None
                        or retained_training.trained_at_club_ids != terms.trained_at_club_ids):
                    raise ValueError("continuity intake training terms do not match the retained training record")
            expected_checks = tuple(sorted(
                (accepted[key].player_id, competition_id)
                for key, terms in arrivals.items()
                for competition_id in terms.competition_ids
            ))
            actual_checks = tuple(sorted(
                (item.player_id, item.competition_id) for item in receipt.registration_checks
            ))
            if actual_checks != expected_checks:
                raise ValueError("continuity registration evidence does not match academy terms")
            checks_by_pair = {
                (item.player_id, item.competition_id): item
                for item in receipt.registration_checks
            }
            for candidate_id, terms in arrivals.items():
                player_id = accepted[candidate_id].player_id
                player = players[player_id]
                for competition_id in terms.competition_ids:
                    check = checks_by_pair[(player_id, competition_id)]
                    policy = next((item for item in self.registration.policies
                                   if item.competition_id == competition_id), None)
                    if (policy is None or check.club_id != player.club_id
                            or check.assessed_on != receipt.boundary_on
                            or check.ruleset_id != policy.ruleset_id
                            or check.check_id != derive_id(
                                "registration-check", "p15c-registration-check-v1",
                                competition_id, player.club_id, player_id,
                                receipt.boundary_on.isoformat, policy.ruleset_id,
                            )
                            or not check.eligible or check.reasons):
                        raise ValueError("continuity registration evidence does not match its club and policy")
        history: list[tuple[int, WorldDate, str, str]] = []
        history.extend((item.sequence, item.boundary_on, item.source_state_sha256,
                        item.result_state_sha256) for item in self.transitions)
        history.extend((item.sequence, item.occurred_on, item.source_state_sha256,
                        item.result_state_sha256) for item in self.state_updates)
        history.sort(key=lambda item: item[0])
        if tuple(item[0] for item in history) != tuple(range(len(history))):
            raise ValueError("continuity event sequence must be contiguous")
        if tuple(item[1] for item in history) != tuple(sorted(item[1] for item in history)):
            raise ValueError("continuity events must retain calendar chronology")
        for prior, following in zip(history, history[1:]):
            if prior[3] != following[2]:
                raise ValueError("continuity event history does not form a state chain")
        if self.transitions:
            latest = self.transitions[-1]
            if latest.boundary_on != self.population.as_of:
                raise ValueError("latest continuity boundary must match the population date")
        elif self.population.transitions:
            raise ValueError("population boundaries must enter through annual continuity")
        if history and history[-1][3] != _state_fingerprint(
                self.population, self.economy, self.registration, self.loans):
            raise ValueError("continuity state does not match its latest event receipt")
        _loan_obligation_expectations(self.economy, self.loans)
        self._validate_update_evidence()
        self._validate_loan_registration_state()

    def _validate_update_evidence(self) -> None:
        loan_events = {item.event_id: item for item in self.loans.events}
        proposals = {item.loan_id: item for item in self.loans.proposals}
        cited_loan_event_ids: set[str] = set()
        cited_economy_event_dates: dict[str, WorldDate] = {}
        movement_kinds = {
            LoanEventKind.ACTIVATED,
            LoanEventKind.RECALLED,
            LoanEventKind.RETURNED,
            LoanEventKind.EXPIRED,
            LoanEventKind.PURCHASED,
        }
        for update in self.state_updates:
            if update.occurred_on < self.population.started_on:
                raise ValueError("continuity update cannot predate the population start")
            expected_update_id = derive_id(
                "continuity-update", "p16d-continuity-update-v1",
                self.world_id, update.sequence, update.occurred_on.isoformat,
                update.source_state_sha256, update.result_state_sha256,
            )
            if update.update_id != expected_update_id:
                raise ValueError("continuity update ID does not match its state transition")
            if not set(update.loan_event_ids) <= loan_events.keys():
                raise ValueError("continuity update references absent loan evidence")
            if cited_loan_event_ids.intersection(update.loan_event_ids):
                raise ValueError("continuity loan events cannot be cited by multiple updates")
            cited_loan_event_ids.update(update.loan_event_ids)
            dated_loan_events = {
                event_id for event_id in update.loan_event_ids
                if loan_events[event_id].at == update.occurred_on
            }
            if dated_loan_events != set(update.loan_event_ids):
                raise ValueError("continuity update references loan evidence from another date")
            economy_ids = _economy_evidence_on(
                self.economy, self.loans, update.occurred_on,
            )
            if not set(update.economy_event_ids) <= economy_ids:
                raise ValueError("continuity update references absent or undated economy evidence")
            if cited_economy_event_dates.keys() & set(update.economy_event_ids):
                raise ValueError("continuity economy events cannot be cited by multiple updates")
            cited_economy_event_dates.update(
                (event_id, update.occurred_on) for event_id in update.economy_event_ids
            )
            if "registration" in update.changed_components:
                movement_events = [
                    loan_events[event_id] for event_id in update.loan_event_ids
                    if loan_events[event_id].kind in movement_kinds
                ]
                if not movement_events:
                    raise ValueError("continuity registration update lacks a loan movement event")
                event_players = {
                    proposals[event.loan_id].player_id for event in movement_events
                    if event.loan_id in proposals
                }
                if set(update.registration_player_ids) != event_players:
                    raise ValueError("continuity registration update does not match its loan players")
                movement_loans = [item.loan_id for item in movement_events]
                if len(movement_loans) != len(set(movement_loans)):
                    raise ValueError("continuity update cannot combine multiple movements for one loan")
            elif any(loan_events[event_id].kind in movement_kinds
                     for event_id in update.loan_event_ids):
                raise ValueError("loan movement receipt must include its registration component")

        boundary_dates = tuple(item.boundary_on for item in self.transitions)
        required_loan_receipts: set[str] = set()
        previous_boundary = self.population.started_on
        for boundary in boundary_dates:
            required_loan_receipts.update(
                event.event_id for event in self.loans.events
                if previous_boundary <= event.at <= boundary
            )
            previous_boundary = boundary
        latest_boundary = max(boundary_dates, default=self.population.as_of)
        required_loan_receipts.update(
            event.event_id for event in self.loans.events
            if event.at >= latest_boundary
        )
        if not required_loan_receipts <= cited_loan_event_ids:
            raise ValueError("between-boundary loan events require continuity update receipts")

        required_economy_evidence: dict[str, WorldDate] = {}

        def require_economy_evidence(event_id: str, occurred_on: WorldDate) -> None:
            existing_date = required_economy_evidence.get(event_id)
            if existing_date is not None and existing_date != occurred_on:
                raise ValueError("economy evidence ID is reused across different dates")
            required_economy_evidence[event_id] = occurred_on

        for run in self.economy.payroll_runs:
            if run.payroll_date < self.population.started_on:
                continue
            require_economy_evidence(
                _payroll_event_id(run.payroll_date, run.active_contract_fingerprint),
                run.payroll_date,
            )
            for obligation_id in run.obligation_ids:
                require_economy_evidence(obligation_id, run.payroll_date)
        for entry in self.economy.entries:
            if entry.settled_on >= self.population.started_on:
                require_economy_evidence(entry.entry_id, entry.settled_on)
        for event in self.loans.events:
            if (event.at >= self.population.started_on
                    and event.kind in (
                        LoanEventKind.LOAN_FEE_SCHEDULED,
                        LoanEventKind.WAGE_SHARE_SCHEDULED,
                    )
                    and event.obligation_id is not None):
                require_economy_evidence(event.obligation_id, event.at)
        if any(cited_economy_event_dates.get(event_id) != occurred_on
               for event_id, occurred_on in required_economy_evidence.items()):
            raise ValueError("dated economy evidence requires continuity update receipts")

    def _validate_loan_registration_state(self) -> None:
        latest_for_player: dict[str, tuple[int, object]] = {}
        event_position = {
            item.event_id: position for position, item in enumerate(self.loans.events)
        }
        for proposal in self.loans.proposals:
            position = max(
                (event_position[item.event_id] for item in self.loans.events
                 if item.loan_id == proposal.loan_id),
                default=-1,
            )
            prior = latest_for_player.get(proposal.player_id)
            if prior is None or position > prior[0]:
                latest_for_player[proposal.player_id] = (position, proposal)
        for _position, proposal in latest_for_player.values():
            status = loan_status(self.loans, proposal.loan_id)
            if status is LoanStatus.PURCHASED:
                raise ValueError("loan purchase requires population transfer integration outside P16d-b")
            expected = "loaned" if status is LoanStatus.ACTIVE else "source"
            states = _loan_registration_states(
                self.registration,
                proposal.player_id,
                proposal.owner_club_id,
                proposal.borrower_club_id,
                proposal.competition_ids,
            )
            if any(item != expected for item in states):
                raise ValueError("continuity loan status does not match current player registrations")

    def to_json(self) -> str:
        return dumps(self)

    @classmethod
    def from_json(cls, value: str) -> AnnualContinuityState:
        try:
            return loads(value, cls)
        except SerializationError as exc:
            raise ValueError(f"invalid annual continuity state: {exc}") from exc


def _validate_sha256(value: str, label: str) -> None:
    if not isinstance(value, str) or len(value) != 64 or any(
            char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")


def _sha256(record: object) -> str:
    return _canonical_record_hash(record)


def _termination_id(contract_id: str, on: WorldDate) -> str:
    from games.touchline.esb.economy.ledger import ContractTerminationReason

    return derive_id(
        "contract-termination", "p16d-employment-termination-v1",
        contract_id, on.isoformat, ContractTerminationReason.RETIREMENT.value,
    )


def _state_fingerprint(
    population: WorldPopulationState,
    economy: EconomyLedger,
    registration: RegistrationBook,
    loans: LoanBook,
) -> str:
    return _sha256(_ContinuitySnapshot(population, economy, registration, loans))


def _payroll_event_id(on: WorldDate, active_contract_fingerprint: str) -> str:
    return derive_id(
        "continuity-economy-event", "p16d-continuity-payroll-v1",
        on.isoformat, active_contract_fingerprint,
    )


def _economy_evidence_on(
    ledger: EconomyLedger,
    loans: LoanBook,
    on: WorldDate,
) -> set[str]:
    evidence: set[str] = set()
    evidence.update(
        _payroll_event_id(item.payroll_date, item.active_contract_fingerprint)
        for item in ledger.payroll_runs if item.payroll_date == on
    )
    evidence.update(item.entry_id for item in ledger.entries if item.settled_on == on)
    evidence.update(item.obligation_id for item in ledger.obligations if item.due_on == on)
    loan_event_ids = {
        item.obligation_id for item in loans.events
        if item.at == on and item.obligation_id is not None
    }
    evidence.update(
        item.obligation_id for item in ledger.obligations
        if item.obligation_id in loan_event_ids
    )
    return evidence


def _loan_obligation_expectations(
    ledger: EconomyLedger,
    loans: LoanBook,
) -> dict[str, PaymentObligation]:
    """Validate that each loan cost event has exactly the payable its terms imply."""
    proposals = {item.loan_id: item for item in loans.proposals}
    contracts = {item.contract_id: item for item in ledger.contracts}
    obligations = {item.obligation_id: item for item in ledger.obligations}
    expected: dict[str, PaymentObligation] = {}
    loan_cost_kinds = {
        ObligationKind.LOAN_FEE,
        ObligationKind.LOAN_WAGE_CONTRIBUTION,
    }
    loan_related_kinds = loan_cost_kinds | {ObligationKind.PURCHASE_FEE}

    for event in loans.events:
        proposal = proposals[event.loan_id]
        if event.kind is LoanEventKind.PURCHASED:
            raise ValueError("loan purchase continuity is outside P16d-b")
        if event.kind not in (
                LoanEventKind.ACTIVATED,
                LoanEventKind.LOAN_FEE_SCHEDULED,
                LoanEventKind.WAGE_SHARE_SCHEDULED,
        ) and event.obligation_id is not None:
            raise ValueError("loan lifecycle event has an unsupported obligation reference")
        if event.kind is LoanEventKind.ACTIVATED:
            expected_fee_id = (
                derive_id("obligation", "p15c-loan-fee-v1", proposal.loan_id)
                if proposal.loan_fee_minor else None
            )
            if event.obligation_id != expected_fee_id:
                raise ValueError("loan activation obligation does not match its agreed fee")
            continue
        if event.kind is LoanEventKind.LOAN_FEE_SCHEDULED:
            expected_id = derive_id(
                "obligation", "p15c-loan-fee-v1", proposal.loan_id,
            )
            if proposal.loan_fee_minor <= 0 or event.obligation_id != expected_id:
                raise ValueError("loan fee obligation ID does not match its proposal")
            obligation = PaymentObligation(
                expected_id,
                proposal.borrower_club_id,
                proposal.owner_club_id,
                proposal.currency,
                proposal.loan_fee_minor,
                event.at,
                ObligationKind.LOAN_FEE,
            )
        elif event.kind is LoanEventKind.WAGE_SHARE_SCHEDULED:
            expected_id = derive_id(
                "obligation", "p15c-loan-wage-share-v1",
                proposal.loan_id, event.at.isoformat,
            )
            if event.obligation_id != expected_id:
                raise ValueError("loan wage obligation ID does not match its proposal and date")
            contract = contracts.get(proposal.employment_contract_id)
            if (contract is None or contract.player_id != proposal.player_id
                    or contract.club_id != proposal.owner_club_id
                    or contract.currency != proposal.currency
                    or not contract.active_on(event.at)
                    or employment_at(ledger, proposal.player_id, event.at) != contract):
                raise ValueError("loan wage obligation lacks its active owner employment contract")
            amount = contract.wage_per_payroll_minor * proposal.borrower_wage_share_bps // 10_000
            if amount <= 0:
                raise ValueError("loan wage obligation has no positive payable under its agreed share")
            obligation = PaymentObligation(
                expected_id,
                proposal.borrower_club_id,
                proposal.owner_club_id,
                proposal.currency,
                amount,
                event.at,
                ObligationKind.LOAN_WAGE_CONTRIBUTION,
            )
        else:
            continue

        if event.obligation_id is None:
            raise ValueError("loan cost event is missing its obligation reference")
        if event.obligation_id in expected:
            raise ValueError("loan cost events cannot share one obligation")
        actual = obligations.get(event.obligation_id)
        if actual != obligation:
            label = "loan fee" if event.kind is LoanEventKind.LOAN_FEE_SCHEDULED else "loan wage"
            raise ValueError(f"{label} obligation does not match its event and proposal")
        expected[event.obligation_id] = obligation

    for obligation in ledger.obligations:
        if obligation.kind in loan_related_kinds and obligation.obligation_id not in expected:
            raise ValueError("economy ledger contains an orphan or unsupported loan obligation")
    return expected


def _new_economy_evidence(
    before: EconomyLedger,
    after: EconomyLedger,
    on: WorldDate,
    linked_loan_obligation_ids: frozenset[str] = frozenset(),
) -> tuple[str, ...]:
    evidence: set[str] = set()
    old_runs = {item for item in before.payroll_runs}
    evidence.update(
        _payroll_event_id(item.payroll_date, item.active_contract_fingerprint)
        for item in after.payroll_runs
        if item not in old_runs and item.payroll_date == on
    )
    old_entries = {item.entry_id for item in before.entries}
    evidence.update(
        item.entry_id for item in after.entries
        if item.entry_id not in old_entries and item.settled_on == on
    )
    old_obligations = {item.obligation_id for item in before.obligations}
    evidence.update(
        item.obligation_id for item in after.obligations
        if item.obligation_id not in old_obligations
        and (item.due_on == on or item.obligation_id in linked_loan_obligation_ids)
    )
    return tuple(sorted(evidence))


def _validate_economy_update(
    before: EconomyLedger,
    after: EconomyLedger,
    on: WorldDate,
    *,
    linked_loan_obligations: dict[str, PaymentObligation],
) -> None:
    if (before.accounts != after.accounts
            or before.contracts != after.contracts
            or before.contract_transfers != after.contract_transfers
            or before.contract_terminations != after.contract_terminations):
        raise ValueError("between-boundary account and employment mutations are outside P16d-b")
    for label, old, new in (
        ("payroll runs", before.payroll_runs, after.payroll_runs),
        ("ledger entries", before.entries, after.entries),
        ("payment obligations", before.obligations, after.obligations),
    ):
        if len(new) < len(old) or new[:len(old)] != old:
            raise ValueError(f"between-boundary {label} must retain their existing history")
    added_runs = after.payroll_runs[len(before.payroll_runs):]
    if any(item.payroll_date != on for item in added_runs):
        raise ValueError("between-boundary payroll evidence must use the update date")
    added_entries = after.entries[len(before.entries):]
    if any(item.settled_on != on for item in added_entries):
        raise ValueError("between-boundary settlement evidence must use the update date")
    added_obligations = after.obligations[len(before.obligations):]
    payroll_obligation_ids = {
        obligation_id for run in added_runs for obligation_id in run.obligation_ids
    }
    for item in added_obligations:
        expected_loan_obligation = linked_loan_obligations.get(item.obligation_id)
        if expected_loan_obligation is not None:
            if item != expected_loan_obligation:
                raise ValueError("new loan obligation does not match its loan event and proposal")
            continue
        if item.obligation_id not in payroll_obligation_ids or item.due_on != on:
            raise ValueError("between-boundary obligations must come from payroll or a dated loan event")
    available_obligations = {item.obligation_id for item in after.obligations}
    if payroll_obligation_ids - available_obligations:
        raise ValueError("between-boundary payroll receipt lost a wage obligation")


def _changed_registration_players(
    before: RegistrationBook,
    after: RegistrationBook,
) -> tuple[str, ...]:
    if before.policies != after.policies or before.player_training != after.player_training:
        raise ValueError("between-boundary loan registration cannot change policies or training history")
    old_squads = {(item.competition_id, item.club_id): item for item in before.squads}
    new_squads = {(item.competition_id, item.club_id): item for item in after.squads}
    changed: set[str] = set()
    for key in set(old_squads) | set(new_squads):
        old = old_squads.get(key, ClubCompetitionSquad(*key))
        new = new_squads.get(key, ClubCompetitionSquad(*key))
        changed.update(set(old.registered_player_ids) ^ set(new.registered_player_ids))
        changed.update(set(old.loan_reserve_player_ids) ^ set(new.loan_reserve_player_ids))
    return tuple(sorted(changed))


def record_continuity_update(
    state: AnnualContinuityState,
    occurred_on: WorldDate,
    *,
    economy: EconomyLedger | None = None,
    registration: RegistrationBook | None = None,
    loans: LoanBook | None = None,
) -> AnnualContinuityState:
    """Record a dated component operation without severing annual-boundary lineage.

    Economy changes need an append-only dated contract, payroll, obligation,
    transfer, termination or cash-settlement event. Loan changes need a dated
    loan event. Registration changes are accepted only with a linked loan
    transition because P16d-b does not define another between-boundary cause.
    """
    if not isinstance(state, AnnualContinuityState) or not isinstance(occurred_on, WorldDate):
        raise TypeError("continuity update requires a state and explicit date")
    next_economy = state.economy if economy is None else economy
    next_registration = state.registration if registration is None else registration
    next_loans = state.loans if loans is None else loans
    if not isinstance(next_economy, EconomyLedger):
        raise TypeError("continuity economy update requires an EconomyLedger")
    if not isinstance(next_registration, RegistrationBook):
        raise TypeError("continuity registration update requires a RegistrationBook")
    if not isinstance(next_loans, LoanBook):
        raise TypeError("continuity loan update requires a LoanBook")
    changed = tuple(sorted(
        name for name, old, new in (
            ("economy", state.economy, next_economy),
            ("loans", state.loans, next_loans),
            ("registration", state.registration, next_registration),
        ) if old != new
    ))
    if not changed:
        return state
    last_date = state.population.as_of
    if state.transitions or state.state_updates:
        last_date = max(
            [item.boundary_on for item in state.transitions]
            + [item.occurred_on for item in state.state_updates]
        )
    if occurred_on < last_date:
        raise ValueError("continuity updates must retain calendar chronology")
    loan_event_ids: tuple[str, ...] = ()
    registration_player_ids: tuple[str, ...] = ()
    if "loans" in changed:
        if (len(next_loans.proposals) < len(state.loans.proposals)
                or next_loans.proposals[:len(state.loans.proposals)] != state.loans.proposals):
            raise ValueError("between-boundary loan proposals must retain their existing history")
        if (len(next_loans.events) < len(state.loans.events)
                or next_loans.events[:len(state.loans.events)] != state.loans.events):
            raise ValueError("between-boundary loan events must retain their existing history")
        added_proposals = next_loans.proposals[len(state.loans.proposals):]
        added_events = next_loans.events[len(state.loans.events):]
        if any(item.submitted_on != occurred_on for item in added_proposals):
            raise ValueError("new loan proposals must use the continuity update date")
        if any(item.at != occurred_on for item in added_events):
            raise ValueError("all new loan events must use the continuity update date")
        loan_event_ids = tuple(sorted(item.event_id for item in added_events))
        if not loan_event_ids:
            raise ValueError("loan update has no new loan event on its recorded date")
    expected_loan_obligations = _loan_obligation_expectations(next_economy, next_loans)
    linked_loan_obligation_ids = frozenset(
        item.obligation_id for item in next_loans.events
        if item.event_id in loan_event_ids and item.obligation_id is not None
    )
    linked_loan_obligations = {
        obligation_id: expected_loan_obligations[obligation_id]
        for obligation_id in linked_loan_obligation_ids
        if obligation_id in expected_loan_obligations
    }
    economy_event_ids = ()
    if "economy" in changed:
        _validate_economy_update(
            state.economy,
            next_economy,
            occurred_on,
            linked_loan_obligations=linked_loan_obligations,
        )
        economy_event_ids = _new_economy_evidence(
            state.economy,
            next_economy,
            occurred_on,
            linked_loan_obligation_ids,
        )
        if not economy_event_ids:
            raise ValueError("economy update has no new dated ledger evidence")
    movement_kinds = {
        LoanEventKind.ACTIVATED,
        LoanEventKind.RECALLED,
        LoanEventKind.RETURNED,
        LoanEventKind.EXPIRED,
        LoanEventKind.PURCHASED,
    }
    movement_events = tuple(
        item for item in next_loans.events
        if item.event_id in loan_event_ids and item.kind in movement_kinds
    )
    if len({item.loan_id for item in movement_events}) != len(movement_events):
        raise ValueError("one continuity update may contain only one player movement per loan")
    required_registration_mode = {
        LoanEventKind.ACTIVATED: "loaned",
        LoanEventKind.RECALLED: "source",
        LoanEventKind.RETURNED: "source",
        LoanEventKind.EXPIRED: "source",
        LoanEventKind.PURCHASED: "purchased",
    }
    if movement_events and "registration" not in changed:
        raise ValueError("loan movement must update player registration in the same continuity event")
    if "registration" in changed:
        if not movement_events:
            raise ValueError("between-boundary registration changes require a loan movement event")
        registration_player_ids = _changed_registration_players(
            state.registration, next_registration,
        )
        proposals = {item.loan_id: item for item in next_loans.proposals}
        event_to_loan = {item.event_id: item.loan_id for item in next_loans.events}
        linked_players = {
            proposals[event_to_loan[event_id]].player_id
            for event_id in loan_event_ids
            if event_id in event_to_loan and event_to_loan[event_id] in proposals
        }
        if not registration_player_ids or set(registration_player_ids) != linked_players:
            raise ValueError("registration changes do not match the dated loan player transition")
    for event in movement_events:
        proposal = next(item for item in next_loans.proposals if item.loan_id == event.loan_id)
        states = _loan_registration_states(
            next_registration,
            proposal.player_id,
            proposal.owner_club_id,
            proposal.borrower_club_id,
            proposal.competition_ids,
        )
        expected_mode = required_registration_mode[event.kind]
        if any(item != expected_mode for item in states):
            raise ValueError("loan movement registration does not match its transition")
    source_sha = _state_fingerprint(
        state.population, state.economy, state.registration, state.loans,
    )
    result_sha = _state_fingerprint(
        state.population, next_economy, next_registration, next_loans,
    )
    sequence = len(state.transitions) + len(state.state_updates)
    update_id = derive_id(
        "continuity-update", "p16d-continuity-update-v1", state.world_id,
        sequence, occurred_on.isoformat, source_sha, result_sha,
    )
    content = _ContinuityUpdateContent(
        update_id,
        sequence,
        occurred_on,
        changed,
        economy_event_ids,
        loan_event_ids,
        registration_player_ids,
        source_sha,
        result_sha,
    )
    receipt = ContinuityStateUpdate(
        content.update_id,
        content.sequence,
        content.occurred_on,
        content.changed_components,
        content.economy_event_ids,
        content.loan_event_ids,
        content.registration_player_ids,
        content.source_state_sha256,
        content.result_state_sha256,
        _sha256(content),
    )
    return AnnualContinuityState(
        state.world_id,
        state.population,
        next_economy,
        next_registration,
        next_loans,
        state.transitions,
        state.state_updates + (receipt,),
    )


def _make_request(
    boundary_on: WorldDate,
    policy: PopulationPolicy,
    new_candidates: tuple[IntakeCandidate, ...],
    academy_arrivals: tuple[AcademyArrivalTerms, ...],
) -> ContinuityBoundaryRequest:
    if any(not isinstance(item, IntakeCandidate) for item in new_candidates):
        raise TypeError("continuity candidates must be IntakeCandidate records")
    if any(not isinstance(item, AcademyArrivalTerms) for item in academy_arrivals):
        raise TypeError("academy arrival terms must be AcademyArrivalTerms records")
    return ContinuityBoundaryRequest(
        boundary_on,
        policy,
        tuple(sorted(new_candidates, key=lambda item: item.candidate_id)),
        tuple(sorted(academy_arrivals, key=lambda item: item.candidate_id)),
    )


def advance_annual_continuity(
    state: AnnualContinuityState,
    boundary_on: WorldDate,
    *,
    policy: PopulationPolicy,
    new_candidates: tuple[IntakeCandidate, ...] = (),
    academy_arrivals: tuple[AcademyArrivalTerms, ...] = (),
) -> AnnualContinuityState:
    """Apply one player-population boundary and its employment/registration changes atomically."""
    if not isinstance(state, AnnualContinuityState):
        raise TypeError("annual continuity requires an AnnualContinuityState")
    if not isinstance(boundary_on, WorldDate) or not isinstance(policy, PopulationPolicy):
        raise TypeError("annual continuity requires an explicit date and population policy")
    if not isinstance(new_candidates, tuple) or not isinstance(academy_arrivals, tuple):
        raise TypeError("annual continuity inputs must be immutable tuples")
    request = _make_request(boundary_on, policy, new_candidates, academy_arrivals)
    request_sha = _sha256(request)

    if boundary_on == state.population.as_of and state.transitions:
        prior = state.transitions[-1]
        if prior.boundary_on == boundary_on and prior.request_sha256 == request_sha:
            return state
        raise ValueError("same-date continuity retry conflicts with its recorded request")

    source_sha = _state_fingerprint(
        state.population, state.economy, state.registration, state.loans,
    )
    next_population = advance_population(
        state.population,
        boundary_on,
        policy=request.policy,
        new_candidates=request.new_candidates,
    )
    population_receipt: PopulationBoundaryReceipt = next_population.transitions[-1]
    decisions = population_receipt.intake_decisions
    accepted_candidate_ids = tuple(sorted(
        item.candidate_id for item in decisions if item.outcome.value == "accepted"
    ))
    supplied_candidate_ids = tuple(item.candidate_id for item in request.academy_arrivals)
    if supplied_candidate_ids != accepted_candidate_ids:
        raise ValueError("academy employment and registration terms must exactly cover accepted candidates")

    economy = state.economy
    registration = state.registration
    retired_ids = tuple(sorted(
        item.player_id for item in population_receipt.retirement_decisions if item.retired
    ))
    initial_players = {item.player_id: item for item in state.population.players}
    terminations: list[ContractTermination] = []
    live_loan_statuses = {
        LoanStatus.OFFERED, LoanStatus.OWNER_ACCEPTED, LoanStatus.PLAYER_ACCEPTED,
        LoanStatus.AGREED, LoanStatus.ACTIVE,
    }
    for player_id in retired_ids:
        if any(item.player_id == player_id
               and loan_status(state.loans, item.loan_id) in live_loan_statuses
               for item in state.loans.proposals):
            raise ValueError("retirement cannot strand a live loan or unresolved proposal")
        player = initial_players[player_id]
        contract = employment_at(economy, player_id, boundary_on)
        if contract is not None:
            if contract.club_id != player.club_id:
                raise ValueError("retiring player's effective employer does not match population club")
            economy, termination = terminate_employment(
                economy, contract.contract_id, boundary_on, loan_book=state.loans,
            )
            terminations.append(termination)
        registration = _release_retired_player(registration, player_id)

    next_players = {item.player_id: item for item in next_population.players}
    academy_contract_ids: list[str] = []
    registration_checks: list[RegistrationCheck] = []
    for terms in request.academy_arrivals:
        decision = next(item for item in decisions if item.candidate_id == terms.candidate_id)
        player = next_players[decision.player_id]
        contract = terms.contract
        if (contract.player_id != player.player_id
                or contract.club_id != player.club_id
                or contract.starts_on != boundary_on
                or contract.agreed_on > boundary_on):
            raise ValueError("academy employment must match the accepted player, club and intake date")
        if any(item.player_id == player.player_id for item in economy.contracts):
            raise ValueError("academy player already has employment history")
        economy = add_employment_contract(economy, contract)
        registration, checks = register_new_player(
            registration,
            player.player_id,
            player.club_id,
            terms.trained_at_club_ids,
            terms.competition_ids,
            boundary_on,
        )
        academy_contract_ids.append(contract.contract_id)
        registration_checks.extend(checks)

    boundary_id = derive_id(
        "continuity-boundary", "p16d-continuity-boundary-v1",
        state.world_id, boundary_on.isoformat,
    )
    result_sha = _state_fingerprint(
        next_population, economy, registration, state.loans,
    )
    ordered_terminations = tuple(sorted(item.contract_id for item in terminations))
    ordered_contracts = tuple(sorted(academy_contract_ids))
    ordered_checks = tuple(sorted(registration_checks, key=lambda item: item.check_id))
    content = _ContinuityReceiptContent(
        boundary_id,
        len(state.transitions) + len(state.state_updates),
        request,
        request_sha,
        source_sha,
        result_sha,
        population_receipt.boundary_id,
        retired_ids,
        ordered_terminations,
        ordered_contracts,
        ordered_checks,
    )
    receipt = ContinuityBoundaryReceipt(
        content.boundary_id,
        content.sequence,
        content.request,
        content.request_sha256,
        content.source_state_sha256,
        content.result_state_sha256,
        content.population_boundary_id,
        content.retired_player_ids,
        content.terminated_contract_ids,
        content.academy_contract_ids,
        content.registration_checks,
        _sha256(content),
    )
    return AnnualContinuityState(
        state.world_id,
        next_population,
        economy,
        registration,
        state.loans,
        state.transitions + (receipt,),
        state.state_updates,
    )


__all__ = [
    "AcademyArrivalTerms", "AnnualContinuityState", "ContinuityBoundaryReceipt",
    "ContinuityBoundaryRequest", "ContinuityStateUpdate", "advance_annual_continuity",
    "record_continuity_update",
]
