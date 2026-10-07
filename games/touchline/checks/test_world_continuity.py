"""Mechanism tests for P16d-b annual employment and registration continuity."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

from games.touchline.checks.world_continuity_probe import (
    COMPETITION_ID,
    START,
    arrival_terms,
    initial_continuity_state,
    run_probe,
)
from games.touchline.checks.world_population_probe import (
    candidate_for,
    population_policy,
)
from games.touchline.esb.economy.ledger import (
    ContractTermination,
    EconomyLedger,
    EmploymentContract,
    ObligationKind,
    add_employment_contract,
    employment_at,
    run_payroll,
    terminate_employment,
    transfer_employment,
)
from games.touchline.esb.economy.loans import (
    LoanBook,
    LoanProposal,
    accrue_loan_wage_share,
    activate_loan,
    propose_loan,
    respond_to_loan,
)
from games.touchline.esb.ids import derive_id
from games.touchline.esb.people import PrimaryRole
from games.touchline.esb.people.medical_clearance import assess_transfer_medical
from games.touchline.esb.serialization import dumps, loads
from games.touchline.esb.time import WorldDate
from games.touchline.esb.world.continuity import (
    AnnualContinuityState,
    ContinuityBoundaryReceipt,
    ContinuityStateUpdate,
    _ContinuityReceiptContent,
    _ContinuityUpdateContent,
    _sha256,
    _state_fingerprint,
    advance_annual_continuity,
    record_continuity_update,
)
from games.touchline.esb.world.population import advance_population
from games.touchline.esb.world.registration import (
    ClubCompetitionSquad,
    RegistrationPolicy,
)


ROOT = Path(__file__).resolve().parents[3]
NEXT = WorldDate(date(2027, 10, 1))


def _retiring_player(state: AnnualContinuityState):
    return next(
        item for item in state.population.players
        if item.profile.identity.birth_date == date(1986, 1, 1)
    )


def _next_keeper(state: AnnualContinuityState):
    return candidate_for(
        PrimaryRole.GOALKEEPER,
        boundary=NEXT,
        season_index=1,
        selection_rank=1,
    )


def _accepted_request(state: AnnualContinuityState):
    candidate = _next_keeper(state)
    policy = population_policy(minimum_squad_size=2)
    projected = advance_population(
        state.population,
        NEXT,
        policy=policy,
        new_candidates=(candidate,),
    )
    accepted = tuple(
        item.candidate_id for item in projected.transitions[-1].intake_decisions
        if item.outcome.value == "accepted"
    )
    if accepted != (candidate.candidate_id,):
        raise AssertionError(f"test candidate was not selected: {accepted}")
    return policy, candidate, (arrival_terms(candidate, NEXT),)


def _reseal_state_result_json(
    state: AnnualContinuityState,
    economy: EconomyLedger,
) -> str:
    """Create a self-consistent serialized receipt around deliberately forged state."""
    update = state.state_updates[-1]
    result_sha = _state_fingerprint(
        state.population, economy, state.registration, state.loans,
    )
    update_id = derive_id(
        "continuity-update", "p16d-continuity-update-v1",
        state.world_id, update.sequence, update.occurred_on.isoformat,
        update.source_state_sha256, result_sha,
    )
    content = _ContinuityUpdateContent(
        update_id,
        update.sequence,
        update.occurred_on,
        update.changed_components,
        update.economy_event_ids,
        update.loan_event_ids,
        update.registration_player_ids,
        update.source_state_sha256,
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
    return _dump_unvalidated_state(
        state,
        economy=economy,
        state_updates=state.state_updates[:-1] + (receipt,),
    )


def _dump_unvalidated_state(
    state: AnnualContinuityState,
    *,
    economy: EconomyLedger | None = None,
    state_updates: tuple[ContinuityStateUpdate, ...] | None = None,
) -> str:
    forged = object.__new__(AnnualContinuityState)
    for name, value in (
        ("world_id", state.world_id),
        ("population", state.population),
        ("economy", state.economy if economy is None else economy),
        ("registration", state.registration),
        ("loans", state.loans),
        ("transitions", state.transitions),
        ("state_updates", state.state_updates if state_updates is None else state_updates),
    ):
        object.__setattr__(forged, name, value)
    return dumps(forged)


def _reseal_economy_update(
    update: ContinuityStateUpdate,
    economy_event_ids: tuple[str, ...],
) -> ContinuityStateUpdate:
    content = _ContinuityUpdateContent(
        update.update_id,
        update.sequence,
        update.occurred_on,
        update.changed_components,
        economy_event_ids,
        update.loan_event_ids,
        update.registration_player_ids,
        update.source_state_sha256,
        update.result_state_sha256,
    )
    return ContinuityStateUpdate(
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


def _reseal_loan_update(
    update: ContinuityStateUpdate,
    loan_event_ids: tuple[str, ...],
) -> ContinuityStateUpdate:
    content = _ContinuityUpdateContent(
        update.update_id,
        update.sequence,
        update.occurred_on,
        update.changed_components,
        update.economy_event_ids,
        loan_event_ids,
        update.registration_player_ids,
        update.source_state_sha256,
        update.result_state_sha256,
    )
    return ContinuityStateUpdate(
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


class AnnualContinuityTests(unittest.TestCase):
    def test_resume_rejects_update_before_population_start(self):
        state = initial_continuity_state()
        before_start = WorldDate(date(2026, 9, 30))
        economy = run_payroll(state.economy, before_start)
        source_sha = _state_fingerprint(
            state.population, state.economy, state.registration, state.loans,
        )
        result_sha = _state_fingerprint(
            state.population, economy, state.registration, state.loans,
        )
        payroll_event_id = derive_id(
            "continuity-economy-event", "p16d-continuity-payroll-v1",
            before_start.isoformat,
            economy.payroll_runs[-1].active_contract_fingerprint,
        )
        update_id = derive_id(
            "continuity-update", "p16d-continuity-update-v1",
            state.world_id, 0, before_start.isoformat, source_sha, result_sha,
        )
        content = _ContinuityUpdateContent(
            update_id,
            0,
            before_start,
            ("economy",),
            (payroll_event_id,),
            (),
            (),
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
        with self.assertRaisesRegex(ValueError, "invalid annual continuity state"):
            AnnualContinuityState.from_json(_dump_unvalidated_state(
                state,
                economy=economy,
                state_updates=(receipt,),
            ))

    def test_receipts_cover_loan_and_payroll_evidence_on_population_start_date(self):
        start_state = initial_continuity_state()
        player = start_state.population.players[0]
        contract = next(
            item for item in start_state.economy.contracts
            if item.player_id == player.player_id
        )
        start_date = start_state.population.started_on
        loan = LoanProposal(
            derive_id("loan", "p16d-continuity-start-date-v1", player.player_id),
            player.player_id,
            player.club_id,
            "club:p16d-continuity-start-date-borrower",
            contract.contract_id,
            start_date,
            start_date,
            start_date,
            WorldDate(date(2027, 9, 30)),
            "GBP",
            0,
            0,
            (COMPETITION_ID,),
        )
        loan_book = propose_loan(start_state.loans, loan, start_state.economy)
        loan_book = respond_to_loan(
            loan_book, loan.loan_id, loan.owner_club_id, True, start_date,
        )
        loan_book = respond_to_loan(
            loan_book, loan.loan_id, loan.player_id, True, start_date,
        )
        loan_state = record_continuity_update(start_state, start_date, loans=loan_book)
        loan_update = loan_state.state_updates[-1]
        incomplete_loan_update = _reseal_loan_update(
            loan_update, loan_update.loan_event_ids[:-1],
        )
        with self.assertRaisesRegex(ValueError, "invalid annual continuity state"):
            AnnualContinuityState.from_json(_dump_unvalidated_state(
                loan_state,
                state_updates=loan_state.state_updates[:-1] + (incomplete_loan_update,),
            ))

        payroll_state = initial_continuity_state()
        payroll_ledger = run_payroll(payroll_state.economy, start_date)
        payroll_state = record_continuity_update(
            payroll_state,
            start_date,
            economy=payroll_ledger,
        )
        payroll_update = payroll_state.state_updates[-1]
        omitted_obligation_id = payroll_state.economy.payroll_runs[-1].obligation_ids[0]
        incomplete_payroll_update = _reseal_economy_update(
            payroll_update,
            tuple(
                item for item in payroll_update.economy_event_ids
                if item != omitted_obligation_id
            ),
        )
        with self.assertRaisesRegex(ValueError, "invalid annual continuity state"):
            AnnualContinuityState.from_json(_dump_unvalidated_state(
                payroll_state,
                state_updates=payroll_state.state_updates[:-1] + (incomplete_payroll_update,),
            ))

    def test_retirement_ends_employment_and_registration_on_boundary(self):
        state = initial_continuity_state()
        retiring = _retiring_player(state)
        old_contract = next(
            item for item in state.economy.contracts
            if item.player_id == retiring.player_id
        )
        before_boundary = WorldDate(date(2027, 9, 1))
        state = record_continuity_update(
            state,
            before_boundary,
            economy=run_payroll(state.economy, before_boundary),
        )
        policy, candidate, arrivals = _accepted_request(state)

        result = advance_annual_continuity(
            state,
            NEXT,
            policy=policy,
            new_candidates=(candidate,),
            academy_arrivals=arrivals,
        )

        self.assertEqual(employment_at(state.economy, retiring.player_id, before_boundary), old_contract)
        self.assertIsNone(employment_at(result.economy, retiring.player_id, NEXT))
        terminations = result.economy.contract_terminations
        self.assertEqual(len(terminations), 1)
        self.assertEqual(terminations[0].contract_id, old_contract.contract_id)
        self.assertEqual(terminations[0].terminated_on, NEXT)
        self.assertIsInstance(terminations[0], ContractTermination)
        self.assertIs(employment_at(result.economy, candidate.player_id, NEXT), arrivals[0].contract)

        before_squad = next(
            item for item in state.registration.squads
            if item.competition_id == COMPETITION_ID
        )
        after_squad = next(
            item for item in result.registration.squads
            if item.competition_id == COMPETITION_ID
        )
        self.assertIn(retiring.player_id, before_squad.registered_player_ids)
        self.assertNotIn(retiring.player_id, after_squad.registered_player_ids)
        self.assertIn(candidate.player_id, after_squad.registered_player_ids)
        candidate_training = next(
            item for item in result.registration.player_training
            if item.player_id == candidate.player_id
        )
        self.assertEqual(candidate_training.trained_at_club_ids, ())
        self.assertFalse(candidate_training.is_homegrown_for(retiring.club_id))
        self.assertEqual(
            next(item for item in result.registration.player_training
                 if item.player_id == retiring.player_id),
            next(item for item in state.registration.player_training
                 if item.player_id == retiring.player_id),
        )
        self.assertEqual(len(result.transitions[-1].registration_checks), 1)

        next_payroll = run_payroll(result.economy, NEXT)
        wage_contract_ids = {
            item.source_contract_id for item in next_payroll.obligations
            if item.due_on == NEXT and item.source_contract_id is not None
        }
        self.assertNotIn(old_contract.contract_id, wage_contract_ids)
        self.assertIn(arrivals[0].contract.contract_id, wage_contract_ids)
        self.assertIn(old_contract.contract_id, {
            item.source_contract_id for item in state.economy.obligations
            if item.due_on == before_boundary
        })

    def test_missing_intake_terms_and_closed_second_window_reject_atomically(self):
        state = initial_continuity_state()
        policy, candidate, arrivals = _accepted_request(state)
        encoded_before = state.to_json()
        with self.assertRaisesRegex(ValueError, "exactly cover accepted candidates"):
            advance_annual_continuity(
                state,
                NEXT,
                policy=policy,
                new_candidates=(candidate,),
            )
        self.assertEqual(state.to_json(), encoded_before)

        cup_id = "competition:p16d-continuity-cup"
        closed = replace(
            state.registration.policies[0],
            competition_id=cup_id,
            ruleset_id="rules:p16d-continuity-cup-v1",
            closes_on=WorldDate(date(2027, 9, 30)),
        )
        registration = replace(
            state.registration,
            policies=state.registration.policies + (closed,),
            squads=state.registration.squads + (ClubCompetitionSquad(
                cup_id,
                state.registration.squads[0].club_id,
                state.registration.squads[0].registered_player_ids,
            ),),
        )
        state_with_cup = replace(state, registration=registration)
        two_competition_terms = replace(
            arrivals[0], competition_ids=tuple(sorted((COMPETITION_ID, cup_id))),
        )
        encoded_before = state_with_cup.to_json()
        with self.assertRaisesRegex(ValueError, "registration failed"):
            advance_annual_continuity(
                state_with_cup,
                NEXT,
                policy=policy,
                new_candidates=(candidate,),
                academy_arrivals=(two_competition_terms,),
            )
        self.assertEqual(state_with_cup.to_json(), encoded_before)
        self.assertEqual(state_with_cup.economy.contracts, state.economy.contracts)

    def test_live_loan_or_unresolved_offer_blocks_retirement_without_partial_change(self):
        state = initial_continuity_state()
        retiring = _retiring_player(state)
        contract = next(
            item for item in state.economy.contracts
            if item.player_id == retiring.player_id
        )
        submitted = WorldDate(date(2027, 9, 1))
        proposal = LoanProposal(
            derive_id("loan", "p16d-continuity-live-loan-v1", retiring.player_id),
            retiring.player_id,
            retiring.club_id,
            "club:p16d-continuity-borrower",
            contract.contract_id,
            submitted,
            WorldDate(date(2027, 10, 5)),
            NEXT,
            WorldDate(date(2028, 10, 1)),
            "GBP",
            0,
            0,
            (COMPETITION_ID,),
        )
        loan_book = propose_loan(LoanBook(), proposal, state.economy)
        state = record_continuity_update(state, submitted, loans=loan_book)
        policy, candidate, arrivals = _accepted_request(state)
        encoded_before = state.to_json()

        with self.assertRaisesRegex(ValueError, "live loan or unresolved proposal"):
            advance_annual_continuity(
                state,
                NEXT,
                policy=policy,
                new_candidates=(candidate,),
                academy_arrivals=arrivals,
            )

        self.assertEqual(state.to_json(), encoded_before)
        self.assertEqual(state.economy.contract_terminations, ())
        self.assertEqual(state.registration, initial_continuity_state().registration)

    def test_exact_retry_serialization_and_receipt_integrity(self):
        state = initial_continuity_state()
        policy, candidate, arrivals = _accepted_request(state)
        result = advance_annual_continuity(
            state,
            NEXT,
            policy=policy,
            new_candidates=(candidate,),
            academy_arrivals=arrivals,
        )
        replay = advance_annual_continuity(
            result,
            NEXT,
            policy=policy,
            new_candidates=(candidate,),
            academy_arrivals=arrivals,
        )
        self.assertIs(replay, result)
        self.assertEqual(AnnualContinuityState.from_json(result.to_json()), result)
        self.assertEqual(loads(dumps(result.economy), EconomyLedger), result.economy)
        with self.assertRaisesRegex(ValueError, "same-date.*conflicts"):
            advance_annual_continuity(
                result,
                NEXT,
                policy=replace(policy, maximum_intake_per_club=policy.maximum_intake_per_club + 1),
                new_candidates=(candidate,),
                academy_arrivals=arrivals,
            )
        with self.assertRaisesRegex(ValueError, "sealed evidence"):
            replace(result.transitions[-1], retired_player_ids=())

    def test_resealed_intake_receipts_must_match_retained_cross_domain_facts(self):
        state = initial_continuity_state()
        policy, candidate, arrivals = _accepted_request(state)
        result = advance_annual_continuity(
            state,
            NEXT,
            policy=policy,
            new_candidates=(candidate,),
            academy_arrivals=arrivals,
        )
        receipt = result.transitions[-1]

        def reseal(*, request=None, checks=None):
            changed_request = receipt.request if request is None else request
            changed_checks = receipt.registration_checks if checks is None else checks
            request_sha = _sha256(changed_request)
            content = _ContinuityReceiptContent(
                receipt.boundary_id,
                receipt.sequence,
                changed_request,
                request_sha,
                receipt.source_state_sha256,
                receipt.result_state_sha256,
                receipt.population_boundary_id,
                receipt.retired_player_ids,
                receipt.terminated_contract_ids,
                receipt.academy_contract_ids,
                changed_checks,
            )
            return ContinuityBoundaryReceipt(
                receipt.boundary_id,
                receipt.sequence,
                changed_request,
                request_sha,
                receipt.source_state_sha256,
                receipt.result_state_sha256,
                receipt.population_boundary_id,
                receipt.retired_player_ids,
                receipt.terminated_contract_ids,
                receipt.academy_contract_ids,
                changed_checks,
                _sha256(content),
            )

        forged_training = replace(
            arrivals[0], trained_at_club_ids=(state.population.players[0].club_id,),
        )
        forged_request = replace(receipt.request, academy_arrivals=(forged_training,))
        with self.assertRaisesRegex(ValueError, "training terms.*retained training"):
            replace(result, transitions=(reseal(request=forged_request),))

        forged_contract = replace(
            arrivals[0],
            contract=replace(
                arrivals[0].contract,
                wage_per_payroll_minor=arrivals[0].contract.wage_per_payroll_minor + 1,
            ),
        )
        forged_request = replace(receipt.request, academy_arrivals=(forged_contract,))
        with self.assertRaisesRegex(ValueError, "contract terms.*retained contract"):
            replace(result, transitions=(reseal(request=forged_request),))

        original_check = receipt.registration_checks[0]
        wrong_club = "club:continuity-forged-registration"
        forged_check = replace(
            original_check,
            club_id=wrong_club,
            check_id=derive_id(
                "registration-check", "p15c-registration-check-v1",
                original_check.competition_id,
                wrong_club,
                original_check.player_id,
                original_check.assessed_on.isoformat,
                original_check.ruleset_id,
            ),
        )
        with self.assertRaisesRegex(ValueError, "registration evidence.*club and policy"):
            replace(result, transitions=(reseal(checks=(forged_check,)),))

        forged_policy = replace(
            receipt.request.policy,
            maximum_intake_per_club=receipt.request.policy.maximum_intake_per_club + 1,
        )
        forged_request = replace(receipt.request, policy=forged_policy)
        with self.assertRaisesRegex(ValueError, "request does not match the applied population policy"):
            replace(result, transitions=(reseal(request=forged_request),))

    def test_between_boundary_employment_changes_cannot_diverge_from_population(self):
        state = initial_continuity_state()
        policy, candidate, arrivals = _accepted_request(state)
        state = advance_annual_continuity(
            state,
            NEXT,
            policy=policy,
            new_candidates=(candidate,),
            academy_arrivals=arrivals,
        )
        changed_on = WorldDate(date(2027, 11, 1))
        player = next(item for item in state.population.players if item.active)
        original = next(item for item in state.economy.contracts
                        if item.player_id == player.player_id)

        outside_contract = EmploymentContract(
            derive_id("employment-contract", "p16d-outside-player-test-v1"),
            player.club_id,
            "player:outside-continuity-world",
            changed_on,
            changed_on,
            WorldDate(date(2030, 1, 1)),
            "GBP",
            1_000,
        )
        with self.assertRaisesRegex(ValueError, "outside P16d-b"):
            record_continuity_update(
                state,
                changed_on,
                economy=add_employment_contract(state.economy, outside_contract),
            )

        with self.assertRaisesRegex(ValueError, "outside P16d-b"):
            terminated, _ = terminate_employment(
                state.economy, original.contract_id, changed_on, loan_book=state.loans,
            )
            record_continuity_update(state, changed_on, economy=terminated)
        with self.assertRaisesRegex(ValueError, "termination must match population"):
            replace(state, economy=terminated)

        buyer_contract = EmploymentContract(
            derive_id("employment-contract", "p16d-transfer-outside-world-v1"),
            "club:p16d-outside-buyer",
            player.player_id,
            changed_on,
            changed_on,
            WorldDate(date(2030, 1, 1)),
            "GBP",
            1_500,
        )
        transferred, _ = transfer_employment(
            state.economy,
            original.contract_id,
            buyer_contract,
            loan_book=state.loans,
        )
        with self.assertRaisesRegex(ValueError, "outside P16d-b"):
            record_continuity_update(state, changed_on, economy=transferred)

    def test_between_boundary_payroll_and_loan_updates_resume_into_next_boundary(self):
        state = initial_continuity_state()
        policy, candidate, arrivals = _accepted_request(state)
        state = advance_annual_continuity(
            state,
            NEXT,
            policy=policy,
            new_candidates=(candidate,),
            academy_arrivals=arrivals,
        )

        payroll_on = WorldDate(date(2027, 11, 1))
        paid_ledger = run_payroll(state.economy, payroll_on)
        with self.assertRaisesRegex(ValueError, "latest event receipt"):
            replace(state, economy=paid_ledger)
        state = record_continuity_update(state, payroll_on, economy=paid_ledger)
        payroll_update = state.state_updates[-1]
        omitted_payroll_obligation = state.economy.payroll_runs[-1].obligation_ids[0]
        incomplete_payroll_update = _reseal_economy_update(
            payroll_update,
            tuple(
                item for item in payroll_update.economy_event_ids
                if item != omitted_payroll_obligation
            ),
        )
        with self.assertRaisesRegex(ValueError, "invalid annual continuity state"):
            AnnualContinuityState.from_json(_dump_unvalidated_state(
                state,
                state_updates=state.state_updates[:-1] + (incomplete_payroll_update,),
            ))

        loan_on = WorldDate(date(2027, 11, 5))
        loan = LoanProposal(
            derive_id("loan", "p16d-continuity-midseason-v1", candidate.player_id),
            candidate.player_id,
            candidate.club_id,
            "club:p16d-continuity-borrower",
            arrivals[0].contract.contract_id,
            loan_on,
            WorldDate(date(2027, 11, 12)),
            WorldDate(date(2027, 11, 15)),
            WorldDate(date(2028, 9, 30)),
            "GBP",
            5_000,
            2_000,
            (COMPETITION_ID,),
        )
        updated_loans = propose_loan(state.loans, loan, state.economy)
        mixed_date_loans = respond_to_loan(
            updated_loans,
            loan.loan_id,
            candidate.club_id,
            True,
            WorldDate(date(2027, 11, 6)),
        )
        with self.assertRaisesRegex(ValueError, "all new loan events must use the continuity update date"):
            record_continuity_update(state, loan_on, loans=mixed_date_loans)
        state = record_continuity_update(state, loan_on, loans=updated_loans)
        owner_decision_on = WorldDate(date(2027, 11, 6))
        updated_loans = respond_to_loan(
            state.loans, loan.loan_id, candidate.club_id, True, owner_decision_on,
        )
        state = record_continuity_update(state, owner_decision_on, loans=updated_loans)
        player_decision_on = WorldDate(date(2027, 11, 7))
        updated_loans = respond_to_loan(
            state.loans, loan.loan_id, candidate.player_id, True, player_decision_on,
        )
        state = record_continuity_update(state, player_decision_on, loans=updated_loans)
        activation_on = WorldDate(date(2027, 11, 15))
        medical = assess_transfer_medical(
            candidate.player_id, "staff:p16d-continuity-doctor", (), activation_on,
        )
        activated_loans, loan_economy, loan_registration = activate_loan(
            state.loans,
            state.economy,
            state.registration,
            loan.loan_id,
            medical,
            activation_on,
        )
        with self.assertRaisesRegex(ValueError, "loan movement must update player registration"):
            record_continuity_update(
                state,
                activation_on,
                economy=loan_economy,
                loans=activated_loans,
            )
        loan_fee = next(
            item for item in loan_economy.obligations
            if item.kind is ObligationKind.LOAN_FEE
        )
        forged_fee = replace(
            loan_fee,
            debtor_id=loan.owner_club_id,
            creditor_id=loan.borrower_club_id,
            amount_minor=1,
        )
        forged_economy = replace(
            loan_economy,
            obligations=tuple(
                forged_fee if item.obligation_id == loan_fee.obligation_id else item
                for item in loan_economy.obligations
            ),
        )
        with self.assertRaisesRegex(ValueError, "loan fee obligation does not match"):
            record_continuity_update(
                state,
                activation_on,
                economy=forged_economy,
                registration=loan_registration,
                loans=activated_loans,
            )
        state = record_continuity_update(
            state,
            activation_on,
            economy=loan_economy,
            registration=loan_registration,
            loans=activated_loans,
        )
        self.assertEqual(len(state.state_updates), 5)
        self.assertEqual(state.state_updates[-1].changed_components,
                         ("economy", "loans", "registration"))
        resumed = AnnualContinuityState.from_json(state.to_json())
        self.assertEqual(resumed, state)
        with self.assertRaisesRegex(ValueError, "invalid annual continuity state"):
            AnnualContinuityState.from_json(
                _reseal_state_result_json(state, forged_economy),
            )

        wage_on = WorldDate(date(2027, 11, 30))
        loans_with_share, economy_with_share, wage_obligation = accrue_loan_wage_share(
            state.loans, state.economy, loan.loan_id, wage_on,
        )
        self.assertIsNotNone(wage_obligation)
        self.assertEqual(wage_obligation.amount_minor, 2_400)
        forged_wage = replace(wage_obligation, amount_minor=1)
        forged_wage_economy = replace(
            economy_with_share,
            obligations=tuple(
                forged_wage if item.obligation_id == wage_obligation.obligation_id else item
                for item in economy_with_share.obligations
            ),
        )
        with self.assertRaisesRegex(ValueError, "loan wage obligation does not match"):
            record_continuity_update(
                state,
                wage_on,
                economy=forged_wage_economy,
                loans=loans_with_share,
            )
        state = record_continuity_update(
            state,
            wage_on,
            economy=economy_with_share,
            loans=loans_with_share,
        )
        self.assertEqual(AnnualContinuityState.from_json(state.to_json()), state)

        following = WorldDate(date(2028, 10, 1))
        next_state = advance_annual_continuity(state, following, policy=policy)
        self.assertEqual(len(next_state.transitions), 2)
        self.assertEqual(len(next_state.state_updates), 6)
        self.assertEqual(
            next_state.transitions[-1].source_state_sha256,
            next_state.state_updates[-1].result_state_sha256,
        )
        self.assertEqual(
            AnnualContinuityState.from_json(next_state.to_json()), next_state,
        )
        fee_event_id = next(
            item.event_id for item in next_state.loans.events
            if item.kind.value == "loan_fee_scheduled"
        )
        activation_update_index = next(
            index for index, item in enumerate(next_state.state_updates)
            if fee_event_id in item.loan_event_ids
        )
        activation_update = next_state.state_updates[activation_update_index]
        incomplete_update = _reseal_loan_update(
            activation_update,
            tuple(item for item in activation_update.loan_event_ids if item != fee_event_id),
        )
        forged_updates = (
            next_state.state_updates[:activation_update_index]
            + (incomplete_update,)
            + next_state.state_updates[activation_update_index + 1:]
        )
        with self.assertRaisesRegex(ValueError, "between-boundary loan events require continuity update receipts"):
            replace(next_state, state_updates=forged_updates)

    def test_loan_receipts_cover_initial_and_exact_annual_boundary_dates(self):
        state = initial_continuity_state()
        policy, candidate, arrivals = _accepted_request(state)
        defender = next(
            item for item in state.population.players
            if item.profile.identity.birth_date == date(2000, 1, 1)
        )
        defender_contract = next(
            item for item in state.economy.contracts
            if item.player_id == defender.player_id
        )
        before_boundary = WorldDate(date(2027, 9, 1))
        first_loan = LoanProposal(
            derive_id("loan", "p16d-continuity-pre-boundary-v1", defender.player_id),
            defender.player_id,
            defender.club_id,
            "club:p16d-continuity-pre-boundary-borrower",
            defender_contract.contract_id,
            before_boundary,
            before_boundary,
            before_boundary,
            WorldDate(date(2028, 9, 30)),
            "GBP",
            0,
            0,
            (COMPETITION_ID,),
        )
        first_book = propose_loan(state.loans, first_loan, state.economy)
        first_book = respond_to_loan(
            first_book, first_loan.loan_id, first_loan.owner_club_id, True, before_boundary,
        )
        first_book = respond_to_loan(
            first_book, first_loan.loan_id, first_loan.player_id, True, before_boundary,
        )
        state = record_continuity_update(state, before_boundary, loans=first_book)
        first_update_index = len(state.state_updates) - 1

        state = advance_annual_continuity(
            state,
            NEXT,
            policy=policy,
            new_candidates=(candidate,),
            academy_arrivals=arrivals,
        )
        academy_contract = arrivals[0].contract
        boundary_loan = LoanProposal(
            derive_id("loan", "p16d-continuity-boundary-date-v1", candidate.player_id),
            candidate.player_id,
            candidate.club_id,
            "club:p16d-continuity-boundary-borrower",
            academy_contract.contract_id,
            NEXT,
            NEXT,
            NEXT,
            WorldDate(date(2028, 9, 30)),
            "GBP",
            0,
            0,
            (COMPETITION_ID,),
        )
        boundary_book = propose_loan(state.loans, boundary_loan, state.economy)
        boundary_book = respond_to_loan(
            boundary_book, boundary_loan.loan_id,
            boundary_loan.owner_club_id, True, NEXT,
        )
        boundary_book = respond_to_loan(
            boundary_book, boundary_loan.loan_id,
            boundary_loan.player_id, True, NEXT,
        )
        state = record_continuity_update(state, NEXT, loans=boundary_book)
        boundary_update_index = len(state.state_updates) - 1

        first_update = state.state_updates[first_update_index]
        incomplete_first = _reseal_loan_update(
            first_update, first_update.loan_event_ids[:-1],
        )
        first_forgery = (
            state.state_updates[:first_update_index]
            + (incomplete_first,)
            + state.state_updates[first_update_index + 1:]
        )
        with self.assertRaisesRegex(ValueError, "between-boundary loan events require continuity update receipts"):
            replace(state, state_updates=first_forgery)

        boundary_update = state.state_updates[boundary_update_index]
        incomplete_boundary = _reseal_loan_update(
            boundary_update, boundary_update.loan_event_ids[:-1],
        )
        boundary_forgery = (
            state.state_updates[:boundary_update_index]
            + (incomplete_boundary,)
            + state.state_updates[boundary_update_index + 1:]
        )
        with self.assertRaisesRegex(ValueError, "between-boundary loan events require continuity update receipts"):
            replace(state, state_updates=boundary_forgery)

    def test_contract_termination_rejects_payroll_crossing_and_is_idempotent(self):
        state = initial_continuity_state()
        retiring = _retiring_player(state)
        contract = next(item for item in state.economy.contracts
                        if item.player_id == retiring.player_id)
        same_date_payroll = run_payroll(state.economy, NEXT)
        with self.assertRaisesRegex(ValueError, "payroll snapshot"):
            terminate_employment(
                same_date_payroll,
                contract.contract_id,
                NEXT,
                loan_book=state.loans,
            )
        updated, termination = terminate_employment(
            state.economy,
            contract.contract_id,
            NEXT,
            loan_book=state.loans,
        )
        replay, prior = terminate_employment(
            updated,
            contract.contract_id,
            NEXT,
            loan_book=state.loans,
        )
        self.assertIs(replay, updated)
        self.assertEqual(prior, termination)
        later_start = WorldDate(date(2045, 10, 1))
        future_contract = EmploymentContract(
            derive_id("employment-contract", "p16d-retired-player-rehire-test-v1", retiring.player_id),
            retiring.club_id,
            retiring.player_id,
            later_start,
            later_start,
            WorldDate(date(2050, 10, 1)),
            "GBP",
            8_000,
        )
        with self.assertRaisesRegex(ValueError, "retired player"):
            add_employment_contract(updated, future_contract)

    def test_five_season_probe_is_deterministic_and_headless(self):
        direct = run_probe()
        self.assertEqual(direct["seasons"], 5)
        self.assertEqual(direct["continuity_receipts"], 5)
        self.assertGreater(direct["total_retirements"], 0)
        self.assertGreater(direct["total_intakes"], 0)
        self.assertTrue(all(item["squad_shortfall"] == 0 for item in direct["annual"]))
        self.assertIn("no fixtures", direct["evidence_boundary"])

        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        env["PYTHONPYCACHEPREFIX"] = "/tmp/touchline-p16d-b-probe-cache"
        command = [sys.executable, "-m", "games.touchline.checks.world_continuity_probe"]
        first = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, check=True)
        second = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, check=True)
        self.assertEqual(first.stdout, second.stdout)
        self.assertEqual(json.loads(first.stdout), direct)

        script = (
            "import builtins\n"
            "def blocked(*args, **kwargs):\n"
            "    raise AssertionError('continuity import attempted file access')\n"
            "builtins.open = blocked\n"
            "import games.touchline.esb.world.continuity\n"
        )
        subprocess.run(
            [sys.executable, "-c", script], cwd=ROOT, env=env,
            capture_output=True, text=True, check=True,
        )


if __name__ == "__main__":
    unittest.main()
