"""Mechanism tests for P12 authority, delegation, budget and staff work."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

from games.touchline.checks.governance_probe import START, build_probe_record
from games.touchline.esb.club.governance import (
    Appointment,
    AuthorityAction,
    AuthorityGrant,
    AuthorityPolicy,
    AuthoritySource,
    BudgetBook,
    BudgetProposal,
    BudgetProposalStatus,
    ClubGovernance,
    ClubRole,
    Delegation,
    OwnerFunding,
    StaffFunction,
    StaffProfile,
    StaffTask,
    StaffTaskAssignment,
    add_staff_appointment,
    add_staff_member,
    assign_staff_task,
    check_authority,
    change_authority_policy,
    create_budget_proposal,
    create_staff_task,
    decide_budget_proposal,
    delegate_authority,
)
from games.touchline.esb.ids import ClubId, EventId
from games.touchline.esb.model import Money
from games.touchline.esb.serialization import dumps, loads
from games.touchline.esb.time import WorldDate

REPO_ROOT = Path(__file__).resolve().parents[3]
CLUB_ID = ClubId("club:p12-authority-test")


def day(offset: int) -> WorldDate:
    return WorldDate(START.day + timedelta(days=offset))


def grant(action: AuthorityAction, limit: int | None = None, *, delegate: bool = False) -> AuthorityGrant:
    return AuthorityGrant(action, limit, delegate)


def appointment(
    appointment_id: str,
    person_id: str,
    role: ClubRole,
    grants: tuple[AuthorityGrant, ...],
    *,
    starts_on: WorldDate = START,
    expires_on: WorldDate | None = None,
    reports_to: str | None = None,
) -> Appointment:
    return Appointment(
        appointment_id, CLUB_ID, person_id, role, starts_on, expires_on, grants, reports_to,
    )


def make_state() -> ClubGovernance:
    owner = appointment(
        "appointment:p12-owner", "person:p12-owner", ClubRole.OWNER,
        (grant(AuthorityAction.ALLOCATE_BUDGET), grant(AuthorityAction.PROPOSE_BUDGET, 100_000),
         grant(AuthorityAction.APPOINT_STAFF), grant(AuthorityAction.REGISTER_STAFF),
         grant(AuthorityAction.GRANT_MANDATE), grant(AuthorityAction.CHANGE_AUTHORITY_POLICY)),
    )
    board = appointment(
        "appointment:p12-board", "person:p12-board", ClubRole.BOARD,
        (grant(AuthorityAction.ALLOCATE_BUDGET), grant(AuthorityAction.PROPOSE_BUDGET, 100_000),
         grant(AuthorityAction.APPOINT_STAFF), grant(AuthorityAction.REGISTER_STAFF),
         grant(AuthorityAction.GRANT_MANDATE), grant(AuthorityAction.CHANGE_AUTHORITY_POLICY)),
    )
    manager = appointment(
        "appointment:p12-manager", "person:p12-manager", ClubRole.MANAGER,
        (grant(AuthorityAction.PROPOSE_BUDGET, 100_000),
         grant(AuthorityAction.ALLOCATE_BUDGET, 12_000, delegate=True),
         grant(AuthorityAction.APPOINT_STAFF), grant(AuthorityAction.REGISTER_STAFF),
         grant(AuthorityAction.CREATE_TASK), grant(AuthorityAction.ASSIGN_TASK, delegate=True),
         grant(AuthorityAction.DELEGATE_AUTHORITY), grant(AuthorityAction.GRANT_MANDATE)),
        expires_on=day(10),
    )
    coach = appointment(
        "appointment:p12-coach", "person:p12-coach", ClubRole.HEAD_COACH,
        (grant(AuthorityAction.PROPOSE_BUDGET, 100_000),
         grant(AuthorityAction.CREATE_TASK), grant(AuthorityAction.ASSIGN_TASK)),
        expires_on=day(15),
    )
    finance = appointment(
        "appointment:p12-finance", "person:p12-finance", ClubRole.FINANCE_LEAD,
        (grant(AuthorityAction.PROPOSE_BUDGET, 100_000),), expires_on=day(6),
    )
    assistant = appointment(
        "appointment:p12-assistant", "person:p12-assistant", ClubRole.STAFF, (),
        expires_on=day(8),
    )
    return ClubGovernance(
        CLUB_ID,
        AuthorityPolicy(
            CLUB_ID,
            board_reserved_actions=(
                AuthorityAction.APPOINT_STAFF, AuthorityAction.REGISTER_STAFF,
                AuthorityAction.GRANT_MANDATE, AuthorityAction.CHANGE_AUTHORITY_POLICY,
            ),
            board_approval_above_minor=5_000,
        ),
        BudgetBook(CLUB_ID, "NAD", 50_000),
        appointments=(owner, board, manager, coach, finance, assistant),
        owner_funding=OwnerFunding(owner.appointment_id, Money(1_000_000, "NAD"), 4_500),
    )


def make_proposal(
    state: ClubGovernance,
    proposal_id: str,
    *,
    amount: int = 3_000,
    proposer: str = "appointment:p12-coach",
) -> BudgetProposal:
    return BudgetProposal(
        proposal_id, state.club_id, "recruitment", amount, "NAD", proposer,
        START, "recruitment observation recommends role cover", (EventId("event:p12-scout-report"),),
    )


class AppointmentAuthorityTests(unittest.TestCase):
    def test_auth_01_same_budget_proposal_uses_appointment_mandates_and_denial_is_atomic(self):
        state = make_state()
        proposal = make_proposal(state, "proposal:p12-auth-01")
        proposed = create_budget_proposal(state, "appointment:p12-coach", proposal, START)
        self.assertTrue(proposed.accepted)
        rejected = decide_budget_proposal(
            proposed.state, "appointment:p12-coach", proposal.proposal_id, True, START,
        )
        self.assertFalse(rejected.accepted)
        self.assertIn("no active grant", rejected.rejection)
        self.assertEqual(rejected.state, proposed.state)
        self.assertEqual(rejected.state.budget, state.budget)

        approved = decide_budget_proposal(
            proposed.state, "appointment:p12-manager", proposal.proposal_id, True, START,
        )
        self.assertTrue(approved.accepted)
        self.assertEqual(approved.state.budget.allocations[0].amount_minor, 3_000)
        self.assertEqual(approved.state.budget.cash_on_hand_minor, 50_000)
        self.assertEqual(approved.state.proposals[0].status, BudgetProposalStatus.APPROVED)
        self.assertEqual(approved.decision.actor_role, ClubRole.MANAGER)
        self.assertEqual(approved.decision.authority_source, AuthoritySource.APPOINTMENT)
        self.assertEqual(approved.decision.proposal_id, proposal.proposal_id)
        replay = decide_budget_proposal(
            approved.state, "appointment:p12-manager", proposal.proposal_id, True, START,
        )
        self.assertTrue(replay.accepted)
        self.assertTrue(replay.replayed)
        self.assertEqual(replay.state.budget.allocations, approved.state.budget.allocations)
        self.assertEqual(len(replay.state.decisions), len(approved.state.decisions))

    def test_auth_02_board_threshold_and_cash_limit_are_distinct_checks(self):
        state = make_state()
        high = make_proposal(state, "proposal:p12-high", amount=8_000)
        proposed = create_budget_proposal(state, "appointment:p12-coach", high, START)
        manager = decide_budget_proposal(
            proposed.state, "appointment:p12-manager", high.proposal_id, True, START,
        )
        self.assertFalse(manager.accepted)
        self.assertIn("board approval threshold", manager.rejection)
        self.assertEqual(manager.state, proposed.state)
        board = decide_budget_proposal(
            proposed.state, "appointment:p12-board", high.proposal_id, True, START,
        )
        self.assertTrue(board.accepted)
        self.assertEqual(board.decision.actor_role, ClubRole.BOARD)
        self.assertEqual(board.state.budget.allocated_minor, 8_000)

        too_large = make_proposal(state, "proposal:p12-over-cash", amount=51_000,
                                  proposer="appointment:p12-owner")
        large_proposed = create_budget_proposal(state, "appointment:p12-owner", too_large, START)
        cash_rejection = decide_budget_proposal(
            large_proposed.state, "appointment:p12-owner", too_large.proposal_id, True, START,
        )
        self.assertFalse(cash_rejection.accepted)
        self.assertIn("exceed club cash", cash_rejection.rejection)
        self.assertEqual(cash_rejection.state, large_proposed.state)
        self.assertEqual(cash_rejection.state.budget.allocations, ())

        later_proposal = replace(
            make_proposal(state, "proposal:p12-later"), proposed_on=day(1),
        )
        later_state = create_budget_proposal(
            state, "appointment:p12-coach", later_proposal, day(1),
        )
        chronology = decide_budget_proposal(
            later_state.state, "appointment:p12-manager", later_proposal.proposal_id, True, START,
        )
        self.assertFalse(chronology.accepted)
        self.assertIn("before it was submitted", chronology.rejection)
        self.assertEqual(chronology.state, later_state.state)

    def test_appointment_checks_are_dated_club_scoped_and_explicit(self):
        state = make_state()
        self.assertFalse(check_authority(
            state, "appointment:p12-coach", AuthorityAction.APPOINT_STAFF, START,
        ).allowed)
        self.assertFalse(check_authority(
            state, "appointment:p12-manager", AuthorityAction.APPOINT_STAFF, START,
        ).allowed)
        self.assertFalse(check_authority(
            state, "appointment:p12-manager", AuthorityAction.ASSIGN_TASK, day(11),
        ).allowed)
        self.assertFalse(check_authority(
            state, "appointment:missing", AuthorityAction.ALLOCATE_BUDGET, START, 100,
        ).allowed)

        foreign = replace(
            appointment("appointment:p12-foreign", "person:p12-foreign", ClubRole.STAFF, ()),
            club_id=ClubId("club:other"),
        )
        rejected = add_staff_appointment(
            state, "appointment:p12-board", foreign, START,
        )
        self.assertFalse(rejected.accepted)
        self.assertEqual(rejected.state, state)
        self.assertEqual(len(rejected.state.appointments), len(state.appointments))

        new_board = appointment(
            "appointment:p12-new-board", "person:p12-new-board", ClubRole.BOARD,
            (grant(AuthorityAction.ALLOCATE_BUDGET),), starts_on=day(2),
        )
        board_cannot_backdate = add_staff_appointment(state, "appointment:p12-board", new_board, day(3))
        self.assertFalse(board_cannot_backdate.accepted)
        board_can_appoint = add_staff_appointment(state, "appointment:p12-board", new_board, START)
        self.assertTrue(board_can_appoint.accepted)
        self.assertEqual(board_can_appoint.decision.action, AuthorityAction.APPOINT_STAFF)
        self.assertEqual(board_can_appoint.state.appointments[-1], new_board)
        self.assertEqual(board_can_appoint.state.decisions[-2].action, AuthorityAction.APPOINT_STAFF)
        self.assertEqual(board_can_appoint.state.decisions[-1].action, AuthorityAction.GRANT_MANDATE)

    def test_policy_changes_are_themselves_authorized(self):
        state = make_state()
        updated_policy = replace(state.policy, board_approval_above_minor=9_000)
        manager = change_authority_policy(
            state, "appointment:p12-manager", updated_policy, START,
        )
        self.assertFalse(manager.accepted)
        self.assertEqual(manager.state, state)
        board = change_authority_policy(
            state, "appointment:p12-board", updated_policy, START,
        )
        self.assertTrue(board.accepted)
        self.assertEqual(board.state.policy.board_approval_above_minor, 9_000)
        self.assertEqual(board.decision.actor_role, ClubRole.BOARD)

    def test_staff_hiring_permission_does_not_implicitly_grant_powers(self):
        state = make_state()
        policy = replace(state.policy, board_reserved_actions=(
            AuthorityAction.GRANT_MANDATE,
            AuthorityAction.CHANGE_AUTHORITY_POLICY,
        ))
        state = replace(state, policy=policy)
        candidate = appointment(
            "appointment:p12-new-finance", "person:p12-new-finance", ClubRole.FINANCE_LEAD,
            (grant(AuthorityAction.ALLOCATE_BUDGET, 10_000),),
        )
        result = add_staff_appointment(state, "appointment:p12-manager", candidate, START)
        self.assertTrue(check_authority(
            state, "appointment:p12-manager", AuthorityAction.APPOINT_STAFF, START,
        ).allowed)
        self.assertFalse(result.accepted)
        self.assertIn("reserved to an owner or board", result.rejection)
        self.assertEqual(result.state, state)

    def test_owner_resources_and_willingness_do_not_become_club_cash(self):
        state = make_state()
        self.assertEqual(state.owner_funding.available_resources.amount_minor, 1_000_000)
        self.assertEqual(state.owner_funding.willingness_basis_points, 4_500)
        self.assertEqual(state.budget.cash_on_hand_minor, 50_000)
        self.assertEqual(state.budget.unallocated_cash_minor, 50_000)

    def test_authorized_decline_is_logged_without_allocating_cash(self):
        state = make_state()
        proposal = make_proposal(state, "proposal:p12-declined")
        proposed = create_budget_proposal(state, "appointment:p12-coach", proposal, START)
        declined = decide_budget_proposal(
            proposed.state, "appointment:p12-manager", proposal.proposal_id, False, START,
        )
        self.assertTrue(declined.accepted)
        self.assertEqual(declined.state.budget, state.budget)
        self.assertEqual(declined.state.proposals[0].status, BudgetProposalStatus.DECLINED)
        self.assertEqual(declined.decision.outcome.value, "declined")
        self.assertEqual(declined.decision.actor_appointment_id, "appointment:p12-manager")


class DelegationAndCapacityTests(unittest.TestCase):
    def test_delegation_is_capped_by_direct_mandate_threshold_and_dates(self):
        state = make_state()
        delegation = Delegation(
            "delegation:p12-budget", "appointment:p12-manager", "appointment:p12-finance",
            AuthorityAction.ALLOCATE_BUDGET, START, day(5), 3_000,
        )
        issued = delegate_authority(state, delegation, START)
        self.assertTrue(issued.accepted)
        under_cap = check_authority(
            issued.state, "appointment:p12-finance", AuthorityAction.ALLOCATE_BUDGET, day(1), 3_000,
        )
        self.assertTrue(under_cap.allowed)
        self.assertEqual(under_cap.source_kind, AuthoritySource.DELEGATION)
        over_cap = check_authority(
            issued.state, "appointment:p12-finance", AuthorityAction.ALLOCATE_BUDGET, day(1), 3_001,
        )
        self.assertFalse(over_cap.allowed)
        self.assertFalse(check_authority(
            issued.state, "appointment:p12-finance", AuthorityAction.ALLOCATE_BUDGET, day(6), 1_000,
        ).allowed)

        over_direct = replace(delegation, delegation_id="delegation:p12-too-wide", max_amount_minor=12_001)
        rejected = delegate_authority(state, over_direct, START)
        self.assertFalse(rejected.accepted)
        self.assertEqual(rejected.state, state)
        cross_threshold = replace(
            delegation, delegation_id="delegation:p12-over-board-threshold", max_amount_minor=5_001,
        )
        self.assertFalse(delegate_authority(state, cross_threshold, START).accepted)
        outlives_issuer = replace(
            delegation, delegation_id="delegation:p12-expired-issuer", expires_on=day(11),
        )
        self.assertFalse(delegate_authority(state, outlives_issuer, START).accepted)
        outlives_delegate = replace(
            delegation, delegation_id="delegation:p12-expired-recipient", expires_on=day(7),
        )
        self.assertFalse(delegate_authority(state, outlives_delegate, START).accepted)

    def test_delegation_cannot_confer_board_reserved_or_redelegation_power(self):
        state = make_state()
        manager = state.appointments[2]
        reserved_grants = tuple(
            replace(item, may_delegate=True)
            if item.action is AuthorityAction.REGISTER_STAFF else item
            for item in manager.grants
        )
        manager_with_reserved = replace(manager, grants=reserved_grants)
        state = replace(state, appointments=state.appointments[:2] + (manager_with_reserved,) + state.appointments[3:])
        reserved = Delegation(
            "delegation:p12-reserved", manager.appointment_id, "appointment:p12-assistant",
            AuthorityAction.REGISTER_STAFF, START, day(3),
        )
        self.assertFalse(delegate_authority(state, reserved, START).accepted)

        finance_to_assistant = Delegation(
            "delegation:p12-subdelegate", "appointment:p12-manager", "appointment:p12-finance",
            AuthorityAction.ALLOCATE_BUDGET, START, day(3), 3_000,
        )
        issued = delegate_authority(make_state(), finance_to_assistant, START)
        self.assertTrue(issued.accepted)
        attempted = Delegation(
            "delegation:p12-redelegated", "appointment:p12-finance", "appointment:p12-assistant",
            AuthorityAction.ALLOCATE_BUDGET, day(1), day(2), 1_000,
        )
        refused = delegate_authority(issued.state, attempted, day(1))
        self.assertFalse(refused.accepted)
        self.assertEqual(refused.state, issued.state)

    def test_combined_staff_functions_share_one_daily_capacity(self):
        state = make_state()
        assistant_appointment = next(
            item for item in state.appointments if item.appointment_id == "appointment:p12-assistant"
        )
        profile = StaffProfile(
            assistant_appointment.person_id, CLUB_ID, assistant_appointment.appointment_id,
            (StaffFunction.SCOUTING, StaffFunction.ANALYSIS), 8,
        )
        registered = add_staff_member(state, "appointment:p12-owner", profile, START)
        self.assertTrue(registered.accepted)
        day_one = day(1)
        tasks = (
            StaffTask("task:p12-scout", CLUB_ID, StaffFunction.SCOUTING, day(3), 5, "Review role evidence"),
            StaffTask("task:p12-analysis", CLUB_ID, StaffFunction.ANALYSIS, day(3), 3, "Prepare match report"),
            StaffTask("task:p12-overbook", CLUB_ID, StaffFunction.ANALYSIS, day(3), 1, "Check one more report"),
        )
        scheduled = registered.state
        for task in tasks:
            result = create_staff_task(scheduled, "appointment:p12-manager", task, START)
            self.assertTrue(result.accepted)
            scheduled = result.state
        first = StaffTaskAssignment(
            "assignment:p12-scout", tasks[0].task_id, profile.staff_id,
            "appointment:p12-manager", day_one, 5,
        )
        assigned = assign_staff_task(scheduled, "appointment:p12-manager", first, START)
        self.assertTrue(assigned.accepted)
        second = StaffTaskAssignment(
            "assignment:p12-analysis", tasks[1].task_id, profile.staff_id,
            "appointment:p12-manager", day_one, 3,
        )
        full = assign_staff_task(assigned.state, "appointment:p12-manager", second, START)
        self.assertTrue(full.accepted)
        self.assertEqual(sum(item.work_units for item in full.state.assignments), 8)
        overbooked = StaffTaskAssignment(
            "assignment:p12-overbook", tasks[2].task_id, profile.staff_id,
            "appointment:p12-manager", day_one, 1,
        )
        rejected = assign_staff_task(full.state, "appointment:p12-manager", overbooked, START)
        self.assertFalse(rejected.accepted)
        self.assertIn("shared daily staff capacity", rejected.rejection)
        self.assertEqual(rejected.state, full.state)
        self.assertEqual(len(rejected.state.assignments), 2)
        self.assertEqual(rejected.state.decisions[-1].action, AuthorityAction.ASSIGN_TASK)

    def test_task_assignment_retries_are_idempotent_and_logs_name_actor(self):
        state = make_state()
        profile = StaffProfile(
            "person:p12-assistant", CLUB_ID, "appointment:p12-assistant",
            (StaffFunction.SCOUTING,), 8,
        )
        state = add_staff_member(state, "appointment:p12-owner", profile, START).state
        task = StaffTask("task:p12-idempotent", CLUB_ID, StaffFunction.SCOUTING,
                         day(2), 4, "Inspect a prospect")
        state = create_staff_task(state, "appointment:p12-manager", task, START).state
        assignment = StaffTaskAssignment(
            "assignment:p12-idempotent", task.task_id, profile.staff_id,
            "appointment:p12-manager", day(1), 4,
        )
        first = assign_staff_task(state, "appointment:p12-manager", assignment, START)
        retry = assign_staff_task(first.state, "appointment:p12-manager", assignment, START)
        self.assertTrue(retry.replayed)
        self.assertEqual(retry.state, first.state)
        self.assertEqual(first.decision.actor_appointment_id, "appointment:p12-manager")
        self.assertEqual(first.decision.authority_source_id, "appointment:p12-manager")


class GovernanceSerializationTests(unittest.TestCase):
    def test_state_and_decision_records_round_trip(self):
        state = build_probe_record()
        restored = loads(dumps(state), ClubGovernance)
        self.assertEqual(restored, state)
        self.assertEqual(restored.decisions[-1].outcome.value, "approved")

    def test_fresh_process_output_is_stable_and_import_is_headless(self):
        with tempfile.TemporaryDirectory(prefix="touchline-p12-pycache-") as pycache:
            env = dict(os.environ)
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            env["PYTHONPYCACHEPREFIX"] = pycache
            first = subprocess.check_output(
                [sys.executable, "-m", "games.touchline.checks.governance_probe"],
                cwd=REPO_ROOT, env=env, text=True,
            ).strip()
            second = subprocess.check_output(
                [sys.executable, "-m", "games.touchline.checks.governance_probe"],
                cwd=REPO_ROOT, env=env, text=True,
            ).strip()
        self.assertEqual(first, second)
        self.assertEqual(loads(first, ClubGovernance), build_probe_record())

        code = r'''
import builtins, importlib, io, pathlib, sys
def blocked(*args, **kwargs): raise AssertionError("governance import performed file I/O")
builtins.open = blocked
io.open = blocked
pathlib.Path.open = blocked
importlib.import_module("games.touchline.esb.club.governance")
assert "curses" not in sys.modules
assert "termstation_ui" not in sys.modules
assert "games.touchline.main" not in sys.modules
'''
        with tempfile.TemporaryDirectory(prefix="touchline-p12-import-") as pycache:
            env = dict(os.environ)
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            env["PYTHONPYCACHEPREFIX"] = pycache
            subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT,
                           env=env, check=True, capture_output=True, text=True)


if __name__ == "__main__":
    unittest.main()
