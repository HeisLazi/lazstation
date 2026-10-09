"""Immutable appointment, authority, budget-proposal and staff-work rules.

Authority is data on dated appointments. Roles do not silently imply powers:
every action needs an explicit mandate grant, while a club policy can reserve
selected actions or route larger budget decisions to its board.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum

from games.touchline.esb.ids import ClubId, EventId, derive_id, validate_id
from games.touchline.esb.model import Money
from games.touchline.esb.time import WorldDate


class ClubRole(str, Enum):
    OWNER = "owner"
    BOARD = "board"
    EXECUTIVE = "executive"
    MANAGER = "manager"
    HEAD_COACH = "head_coach"
    SPORTING_DIRECTOR = "sporting_director"
    FINANCE_LEAD = "finance_lead"
    STAFF = "staff"


class StaffFunction(str, Enum):
    COACHING = "coaching"
    RECRUITMENT = "recruitment"
    SCOUTING = "scouting"
    ANALYSIS = "analysis"
    MEDICAL = "medical"
    FINANCE = "finance"
    MEDIA = "media"
    OPERATIONS = "operations"


class AuthorityAction(str, Enum):
    PROPOSE_BUDGET = "propose_budget"
    ALLOCATE_BUDGET = "allocate_budget"
    APPOINT_STAFF = "appoint_staff"
    REGISTER_STAFF = "register_staff"
    GRANT_MANDATE = "grant_mandate"
    CHANGE_AUTHORITY_POLICY = "change_authority_policy"
    CREATE_TASK = "create_task"
    ASSIGN_TASK = "assign_task"
    DELEGATE_AUTHORITY = "delegate_authority"


class AuthoritySource(str, Enum):
    APPOINTMENT = "appointment"
    DELEGATION = "delegation"


class BudgetProposalStatus(str, Enum):
    OPEN = "open"
    APPROVED = "approved"
    DECLINED = "declined"


class DecisionOutcome(str, Enum):
    APPROVED = "approved"
    DECLINED = "declined"
    EXECUTED = "executed"


_AMOUNT_ACTIONS = frozenset({AuthorityAction.PROPOSE_BUDGET, AuthorityAction.ALLOCATE_BUDGET})
_BOARD_ROLES = frozenset({ClubRole.OWNER, ClubRole.BOARD})


@dataclass(frozen=True)
class AuthorityGrant:
    """One explicit appointment power and its optional amount cap."""

    action: AuthorityAction
    max_amount_minor: int | None = None
    may_delegate: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.action, AuthorityAction):
            raise TypeError("authority grant requires an explicit action")
        if type(self.may_delegate) is not bool:
            raise TypeError("delegation permission must be boolean")
        if self.max_amount_minor is not None and (
            type(self.max_amount_minor) is not int or self.max_amount_minor < 0
        ):
            raise ValueError("authority amount limit must be a non-negative minor-unit integer")
        if self.action not in _AMOUNT_ACTIONS and self.max_amount_minor is not None:
            raise ValueError("non-financial authority cannot have a money limit")
        if self.action is AuthorityAction.DELEGATE_AUTHORITY and self.may_delegate:
            raise ValueError("delegation authority itself cannot be delegated")


@dataclass(frozen=True)
class Appointment:
    appointment_id: str
    club_id: ClubId
    person_id: str
    role: ClubRole
    starts_on: WorldDate
    expires_on: WorldDate | None
    grants: tuple[AuthorityGrant, ...]
    reports_to_appointment_id: str | None = None

    def __post_init__(self) -> None:
        validate_id(self.appointment_id, kind="appointment ID")
        validate_id(self.club_id, kind="appointment club ID")
        validate_id(self.person_id, kind="appointment person ID")
        if not isinstance(self.role, ClubRole):
            raise TypeError("appointment requires an explicit club role")
        if not isinstance(self.starts_on, WorldDate):
            raise TypeError("appointment requires an effective start date")
        if self.expires_on is not None and not isinstance(self.expires_on, WorldDate):
            raise TypeError("appointment expiry must be a world date")
        if self.expires_on is not None and self.expires_on < self.starts_on:
            raise ValueError("appointment expiry cannot precede its start")
        if not isinstance(self.grants, tuple) or any(not isinstance(item, AuthorityGrant) for item in self.grants):
            raise TypeError("appointment mandates must be immutable authority grants")
        actions = [item.action for item in self.grants]
        if len(actions) != len(set(actions)):
            raise ValueError("appointment cannot repeat an authority action")
        if self.reports_to_appointment_id is not None:
            validate_id(self.reports_to_appointment_id, kind="reporting appointment ID")

    def active_on(self, on: WorldDate) -> bool:
        if not isinstance(on, WorldDate):
            raise TypeError("appointment check requires a world date")
        return self.starts_on <= on and (self.expires_on is None or on <= self.expires_on)

    def grant_for(self, action: AuthorityAction) -> AuthorityGrant | None:
        return next((item for item in self.grants if item.action is action), None)


@dataclass(frozen=True)
class AuthorityPolicy:
    club_id: ClubId
    board_reserved_actions: tuple[AuthorityAction, ...] = ()
    board_approval_above_minor: int | None = None

    def __post_init__(self) -> None:
        validate_id(self.club_id, kind="authority-policy club ID")
        if not isinstance(self.board_reserved_actions, tuple) or any(
            not isinstance(item, AuthorityAction) for item in self.board_reserved_actions
        ):
            raise TypeError("reserved powers must be explicit authority actions")
        if len(self.board_reserved_actions) != len(set(self.board_reserved_actions)):
            raise ValueError("board-reserved powers cannot be repeated")
        if AuthorityAction.ALLOCATE_BUDGET in self.board_reserved_actions:
            raise ValueError("use the budget approval threshold for budget-reserved authority")
        if self.board_approval_above_minor is not None and (
            type(self.board_approval_above_minor) is not int or self.board_approval_above_minor < 0
        ):
            raise ValueError("board budget threshold must be non-negative minor units")


@dataclass(frozen=True)
class AuthorityEvaluation:
    allowed: bool
    action: AuthorityAction
    actor_appointment_id: str
    actor_role: ClubRole | None
    source_kind: AuthoritySource | None
    source_id: str | None
    reason: str

    def __post_init__(self) -> None:
        if type(self.allowed) is not bool or not isinstance(self.action, AuthorityAction):
            raise TypeError("authority evaluation requires a result and explicit action")
        validate_id(self.actor_appointment_id, kind="authority actor appointment ID")
        if self.actor_role is not None and not isinstance(self.actor_role, ClubRole):
            raise TypeError("authority actor role must be explicit when known")
        if self.source_kind is not None and not isinstance(self.source_kind, AuthoritySource):
            raise TypeError("authority source type must be explicit when known")
        if self.source_id is not None:
            validate_id(self.source_id, kind="authority source ID")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("authority evaluation requires an explanation")
        if self.allowed != (self.source_kind is not None and self.source_id is not None):
            raise ValueError("allowed authority needs exactly one auditable source")


@dataclass(frozen=True)
class BudgetAllocation:
    category: str
    amount_minor: int

    def __post_init__(self) -> None:
        if not isinstance(self.category, str) or not self.category.strip():
            raise ValueError("budget allocation requires a named category")
        if type(self.amount_minor) is not int or self.amount_minor <= 0:
            raise ValueError("budget allocation must be a positive minor-unit amount")


@dataclass(frozen=True)
class BudgetBook:
    club_id: ClubId
    currency_id: str
    cash_on_hand_minor: int
    allocations: tuple[BudgetAllocation, ...] = ()

    def __post_init__(self) -> None:
        validate_id(self.club_id, kind="budget club ID")
        Money(0, self.currency_id)
        if type(self.cash_on_hand_minor) is not int or self.cash_on_hand_minor < 0:
            raise ValueError("club cash must be non-negative integer minor units")
        if not isinstance(self.allocations, tuple) or any(
            not isinstance(item, BudgetAllocation) for item in self.allocations
        ):
            raise TypeError("budget allocations must be immutable records")
        categories = [item.category for item in self.allocations]
        if len(categories) != len(set(categories)):
            raise ValueError("budget categories cannot be repeated")
        if sum(item.amount_minor for item in self.allocations) > self.cash_on_hand_minor:
            raise ValueError("allocated budgets cannot exceed club cash on hand")

    @property
    def allocated_minor(self) -> int:
        return sum(item.amount_minor for item in self.allocations)

    @property
    def unallocated_cash_minor(self) -> int:
        return self.cash_on_hand_minor - self.allocated_minor


@dataclass(frozen=True)
class OwnerFunding:
    """Owner resources and willingness, kept separate from club cash."""

    owner_appointment_id: str
    available_resources: Money
    willingness_basis_points: int

    def __post_init__(self) -> None:
        validate_id(self.owner_appointment_id, kind="owner funding appointment ID")
        if not isinstance(self.available_resources, Money) or self.available_resources.amount_minor < 0:
            raise ValueError("owner resources must be non-negative money")
        if type(self.willingness_basis_points) is not int or not 0 <= self.willingness_basis_points <= 10_000:
            raise ValueError("owner funding willingness must be in [0, 10000] basis points")


@dataclass(frozen=True)
class Delegation:
    delegation_id: str
    delegator_appointment_id: str
    delegate_appointment_id: str
    action: AuthorityAction
    starts_on: WorldDate
    expires_on: WorldDate | None
    max_amount_minor: int | None = None

    def __post_init__(self) -> None:
        validate_id(self.delegation_id, kind="delegation ID")
        validate_id(self.delegator_appointment_id, kind="delegating appointment ID")
        validate_id(self.delegate_appointment_id, kind="delegated appointment ID")
        if self.delegator_appointment_id == self.delegate_appointment_id:
            raise ValueError("an appointment cannot delegate authority to itself")
        if not isinstance(self.action, AuthorityAction):
            raise TypeError("delegation requires an explicit action")
        if not isinstance(self.starts_on, WorldDate):
            raise TypeError("delegation requires an effective date")
        if self.expires_on is not None and not isinstance(self.expires_on, WorldDate):
            raise TypeError("delegation expiry must be a world date")
        if self.expires_on is not None and self.expires_on < self.starts_on:
            raise ValueError("delegation expiry cannot precede its start")
        if self.max_amount_minor is not None and (
            type(self.max_amount_minor) is not int or self.max_amount_minor < 0
        ):
            raise ValueError("delegated amount limit must be non-negative minor units")
        if self.action not in _AMOUNT_ACTIONS and self.max_amount_minor is not None:
            raise ValueError("non-financial delegation cannot have a money limit")

    def active_on(self, on: WorldDate) -> bool:
        if not isinstance(on, WorldDate):
            raise TypeError("delegation check requires a world date")
        return self.starts_on <= on and (self.expires_on is None or on <= self.expires_on)


@dataclass(frozen=True)
class StaffProfile:
    staff_id: str
    club_id: ClubId
    appointment_id: str
    functions: tuple[StaffFunction, ...]
    daily_capacity_units: int

    def __post_init__(self) -> None:
        validate_id(self.staff_id, kind="staff ID")
        validate_id(self.club_id, kind="staff club ID")
        validate_id(self.appointment_id, kind="staff appointment ID")
        if not isinstance(self.functions, tuple) or not self.functions or any(
            not isinstance(item, StaffFunction) for item in self.functions
        ):
            raise TypeError("staff profile requires one or more explicit functions")
        if len(self.functions) != len(set(self.functions)):
            raise ValueError("staff functions cannot be repeated")
        if type(self.daily_capacity_units) is not int or self.daily_capacity_units <= 0:
            raise ValueError("staff daily work capacity must be positive")


@dataclass(frozen=True)
class StaffTask:
    task_id: str
    club_id: ClubId
    function: StaffFunction
    due_on: WorldDate
    work_units: int
    description: str

    def __post_init__(self) -> None:
        validate_id(self.task_id, kind="staff task ID")
        validate_id(self.club_id, kind="staff task club ID")
        if not isinstance(self.function, StaffFunction):
            raise TypeError("staff task requires an explicit function")
        if not isinstance(self.due_on, WorldDate):
            raise TypeError("staff task requires a due date")
        if type(self.work_units) is not int or self.work_units <= 0:
            raise ValueError("staff task work must be positive")
        if not isinstance(self.description, str) or not self.description.strip():
            raise ValueError("staff task requires a description")


@dataclass(frozen=True)
class StaffTaskAssignment:
    assignment_id: str
    task_id: str
    staff_id: str
    assigned_by_appointment_id: str
    scheduled_on: WorldDate
    work_units: int

    def __post_init__(self) -> None:
        validate_id(self.assignment_id, kind="staff assignment ID")
        validate_id(self.task_id, kind="assigned task ID")
        validate_id(self.staff_id, kind="assigned staff ID")
        validate_id(self.assigned_by_appointment_id, kind="assigning appointment ID")
        if not isinstance(self.scheduled_on, WorldDate):
            raise TypeError("staff assignment requires a scheduled date")
        if type(self.work_units) is not int or self.work_units <= 0:
            raise ValueError("staff assignment work must be positive")


@dataclass(frozen=True)
class BudgetProposal:
    proposal_id: str
    club_id: ClubId
    category: str
    amount_minor: int
    currency_id: str
    proposed_by_appointment_id: str
    proposed_on: WorldDate
    rationale: str
    source_event_ids: tuple[EventId, ...] = ()
    status: BudgetProposalStatus = BudgetProposalStatus.OPEN

    def __post_init__(self) -> None:
        validate_id(self.proposal_id, kind="budget proposal ID")
        validate_id(self.club_id, kind="budget proposal club ID")
        validate_id(self.proposed_by_appointment_id, kind="proposal appointment ID")
        if not isinstance(self.category, str) or not self.category.strip():
            raise ValueError("budget proposal requires a named category")
        if type(self.amount_minor) is not int or self.amount_minor <= 0:
            raise ValueError("budget proposal amount must be positive minor units")
        Money(0, self.currency_id)
        if not isinstance(self.proposed_on, WorldDate):
            raise TypeError("budget proposal requires a world date")
        if not isinstance(self.rationale, str) or not self.rationale.strip():
            raise ValueError("budget proposal requires an explicit rationale")
        if not isinstance(self.source_event_ids, tuple):
            raise TypeError("budget proposal source references must be immutable")
        for event_id in self.source_event_ids:
            validate_id(event_id, kind="budget proposal source event ID")
        if not isinstance(self.status, BudgetProposalStatus):
            raise TypeError("budget proposal status must be explicit")


@dataclass(frozen=True)
class DecisionLogEntry:
    decision_id: str
    subject_id: str
    proposal_id: str | None
    action: AuthorityAction
    actor_appointment_id: str
    actor_role: ClubRole
    authority_source: AuthoritySource
    authority_source_id: str
    decided_on: WorldDate
    outcome: DecisionOutcome
    reason: str
    amount_minor: int | None = None

    def __post_init__(self) -> None:
        validate_id(self.decision_id, kind="decision ID")
        validate_id(self.subject_id, kind="decision subject ID")
        if self.proposal_id is not None:
            validate_id(self.proposal_id, kind="decision proposal ID")
        if not isinstance(self.action, AuthorityAction):
            raise TypeError("decision log requires an explicit authority action")
        validate_id(self.actor_appointment_id, kind="decision actor appointment ID")
        if not isinstance(self.actor_role, ClubRole):
            raise TypeError("decision log requires the actor's role at decision time")
        if not isinstance(self.authority_source, AuthoritySource):
            raise TypeError("decision log requires an explicit authority source")
        validate_id(self.authority_source_id, kind="decision authority source ID")
        if not isinstance(self.decided_on, WorldDate) or not isinstance(self.outcome, DecisionOutcome):
            raise TypeError("decision log requires a date and outcome")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("decision log requires a reason")
        if self.action in _AMOUNT_ACTIONS:
            if type(self.amount_minor) is not int or self.amount_minor <= 0:
                raise ValueError("financial decision requires a positive minor-unit amount")
        elif self.amount_minor is not None:
            raise ValueError("non-financial decision cannot have a money amount")
        if (self.proposal_id is None) == (self.action is AuthorityAction.ALLOCATE_BUDGET):
            raise ValueError("budget allocation decisions must reference exactly one proposal")


@dataclass(frozen=True)
class ClubGovernance:
    club_id: ClubId
    policy: AuthorityPolicy
    budget: BudgetBook
    appointments: tuple[Appointment, ...] = ()
    delegations: tuple[Delegation, ...] = ()
    staff: tuple[StaffProfile, ...] = ()
    tasks: tuple[StaffTask, ...] = ()
    assignments: tuple[StaffTaskAssignment, ...] = ()
    proposals: tuple[BudgetProposal, ...] = ()
    decisions: tuple[DecisionLogEntry, ...] = ()
    owner_funding: OwnerFunding | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        validate_id(self.club_id, kind="governance club ID")
        if not isinstance(self.policy, AuthorityPolicy) or self.policy.club_id != self.club_id:
            raise ValueError("governance policy must belong to its club")
        if not isinstance(self.budget, BudgetBook) or self.budget.club_id != self.club_id:
            raise ValueError("governance budget must belong to its club")
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("unsupported club-governance schema version")
        collections = (
            ("appointments", self.appointments, Appointment, "appointment_id"),
            ("delegations", self.delegations, Delegation, "delegation_id"),
            ("staff", self.staff, StaffProfile, "staff_id"),
            ("tasks", self.tasks, StaffTask, "task_id"),
            ("assignments", self.assignments, StaffTaskAssignment, "assignment_id"),
            ("proposals", self.proposals, BudgetProposal, "proposal_id"),
            ("decisions", self.decisions, DecisionLogEntry, "decision_id"),
        )
        for label, records, record_type, key in collections:
            if not isinstance(records, tuple) or any(not isinstance(item, record_type) for item in records):
                raise TypeError(f"governance {label} must be immutable {record_type.__name__} records")
            ids = [getattr(item, key) for item in records]
            if len(ids) != len(set(ids)):
                raise ValueError(f"governance {label} cannot repeat IDs")

        appointments = {item.appointment_id: item for item in self.appointments}
        for item in self.appointments:
            if item.club_id != self.club_id:
                raise ValueError("appointment belongs to another club")
            if item.reports_to_appointment_id is not None and item.reports_to_appointment_id not in appointments:
                raise ValueError("appointment reporting line references a missing appointment")
        for item in self.delegations:
            principal = appointments.get(item.delegator_appointment_id)
            delegate = appointments.get(item.delegate_appointment_id)
            if principal is None or delegate is None:
                raise ValueError("delegation references a missing appointment")
            principal_grant = principal.grant_for(item.action)
            if principal.club_id != delegate.club_id or principal.club_id != self.club_id:
                raise ValueError("delegation appointments must belong to this club")
            if principal_grant is None or not principal_grant.may_delegate:
                raise ValueError("delegation must remain within a direct delegable mandate")
            if (item.starts_on < principal.starts_on or item.starts_on < delegate.starts_on
                    or (principal.expires_on is not None
                        and (item.expires_on is None or item.expires_on > principal.expires_on))
                    or (delegate.expires_on is not None
                        and (item.expires_on is None or item.expires_on > delegate.expires_on))):
                raise ValueError("delegation cannot outlive either appointment")
            if (principal_grant.max_amount_minor is not None
                    and (item.max_amount_minor is None
                         or item.max_amount_minor > principal_grant.max_amount_minor)):
                raise ValueError("delegation cannot exceed its direct amount limit")
        staff = {item.staff_id: item for item in self.staff}
        for item in self.staff:
            appointment = appointments.get(item.appointment_id)
            if item.club_id != self.club_id or appointment is None or appointment.person_id != item.staff_id:
                raise ValueError("staff profile must reference its person's same-club appointment")
        tasks = {item.task_id: item for item in self.tasks}
        assigned_tasks = set()
        booked: dict[tuple[str, WorldDate], int] = {}
        for item in self.tasks:
            if item.club_id != self.club_id:
                raise ValueError("staff task belongs to another club")
        for item in self.assignments:
            task = tasks.get(item.task_id)
            profile = staff.get(item.staff_id)
            actor = appointments.get(item.assigned_by_appointment_id)
            target_appointment = appointments.get(profile.appointment_id) if profile is not None else None
            if task is None or profile is None or actor is None or target_appointment is None:
                raise ValueError("staff assignment references a missing task, staff member or appointment")
            if item.work_units != task.work_units or task.function not in profile.functions:
                raise ValueError("staff assignment does not match task work or staff function")
            if (item.scheduled_on > task.due_on or actor.club_id != self.club_id
                    or not target_appointment.active_on(item.scheduled_on)):
                raise ValueError("staff assignment is outside its club or task deadline")
            if item.task_id in assigned_tasks:
                raise ValueError("staff task cannot be assigned more than once")
            assigned_tasks.add(item.task_id)
            slot = (item.staff_id, item.scheduled_on)
            booked[slot] = booked.get(slot, 0) + item.work_units
            if booked[slot] > profile.daily_capacity_units:
                raise ValueError("staff assignment schedule exceeds daily capacity")
        proposals = {item.proposal_id: item for item in self.proposals}
        decisions_by_proposal: dict[str, list[DecisionLogEntry]] = {}
        approved_allocations: dict[str, int] = {}
        for item in self.proposals:
            if item.club_id != self.club_id or item.proposed_by_appointment_id not in appointments:
                raise ValueError("budget proposal references another club or missing appointment")
            if item.currency_id != self.budget.currency_id:
                raise ValueError("budget proposal currency differs from club budget currency")
        for item in self.decisions:
            actor = appointments.get(item.actor_appointment_id)
            if actor is None or item.actor_role is not actor.role or not actor.active_on(item.decided_on):
                raise ValueError("decision log references a missing appointment")
            if item.proposal_id is not None and item.proposal_id not in proposals:
                raise ValueError("decision log references a missing proposal")
            if item.authority_source is AuthoritySource.APPOINTMENT:
                if (item.authority_source_id not in appointments
                        or item.authority_source_id != item.actor_appointment_id):
                    raise ValueError("decision log references a missing source appointment")
                grant = actor.grant_for(item.action)
                if grant is None or not _grant_covers(grant, item.amount_minor):
                    raise ValueError("decision log exceeds the actor's recorded appointment mandate")
            else:
                delegation = next(
                    (entry for entry in self.delegations
                     if entry.delegation_id == item.authority_source_id), None,
                )
                if (delegation is None or delegation.delegate_appointment_id != item.actor_appointment_id
                        or delegation.action is not item.action or not delegation.active_on(item.decided_on)
                        or not appointments[delegation.delegator_appointment_id].active_on(item.decided_on)):
                    raise ValueError("decision log references a mismatched authority delegation")
                principal_grant = appointments[delegation.delegator_appointment_id].grant_for(item.action)
                if (principal_grant is None or not principal_grant.may_delegate
                        or (principal_grant.max_amount_minor is not None
                            and (delegation.max_amount_minor is None
                                 or delegation.max_amount_minor > principal_grant.max_amount_minor))
                        or (delegation.max_amount_minor is not None and item.amount_minor is not None
                            and item.amount_minor > delegation.max_amount_minor)):
                    raise ValueError("decision log exceeds the issuer's recorded delegation")
            if item.proposal_id is not None:
                decisions_by_proposal.setdefault(item.proposal_id, []).append(item)
                proposal = proposals[item.proposal_id]
                if (item.action is not AuthorityAction.ALLOCATE_BUDGET
                        or item.amount_minor != proposal.amount_minor):
                    raise ValueError("budget proposal decision action and amount must match the proposal")
                if item.outcome is DecisionOutcome.APPROVED:
                    approved_allocations[proposal.category] = (
                        approved_allocations.get(proposal.category, 0) + proposal.amount_minor
                    )
        for proposal in self.proposals:
            linked = decisions_by_proposal.get(proposal.proposal_id, [])
            expected = {
                BudgetProposalStatus.OPEN: None,
                BudgetProposalStatus.APPROVED: DecisionOutcome.APPROVED,
                BudgetProposalStatus.DECLINED: DecisionOutcome.DECLINED,
            }[proposal.status]
            if expected is None:
                if linked:
                    raise ValueError("open budget proposal cannot already have a decision")
            elif len(linked) != 1 or linked[0].outcome is not expected:
                raise ValueError("closed budget proposal must have exactly one matching decision")
        budget_by_category = {item.category: item.amount_minor for item in self.budget.allocations}
        if any(amount > budget_by_category.get(category, 0)
               for category, amount in approved_allocations.items()):
            raise ValueError("approved proposal history exceeds allocated budget records")
        if self.owner_funding is not None:
            if not isinstance(self.owner_funding, OwnerFunding):
                raise TypeError("owner funding must use an OwnerFunding record")
            owner = appointments.get(self.owner_funding.owner_appointment_id)
            if owner is None or owner.role is not ClubRole.OWNER:
                raise ValueError("owner funding must reference an owner appointment")
            if self.owner_funding.available_resources.currency_id != self.budget.currency_id:
                raise ValueError("owner funding currency must match club budget currency")


@dataclass(frozen=True)
class GovernanceCommandResult:
    state: ClubGovernance
    accepted: bool
    authorization: AuthorityEvaluation
    decision: DecisionLogEntry | None = None
    rejection: str | None = None
    replayed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.state, ClubGovernance) or type(self.accepted) is not bool:
            raise TypeError("governance command result requires a state and accepted flag")
        if not isinstance(self.authorization, AuthorityEvaluation):
            raise TypeError("governance command result requires its authority evaluation")
        if self.accepted == (self.rejection is not None):
            raise ValueError("accepted results have no rejection; rejected results require one")
        if self.decision is not None and not isinstance(self.decision, DecisionLogEntry):
            raise TypeError("governance result decision must use a DecisionLogEntry")


def _denied(
    action: AuthorityAction,
    actor_appointment_id: str,
    reason: str,
    role: ClubRole | None = None,
) -> AuthorityEvaluation:
    return AuthorityEvaluation(False, action, actor_appointment_id, role, None, None, reason)


def _find_appointment(state: ClubGovernance, appointment_id: str) -> Appointment | None:
    return next((item for item in state.appointments if item.appointment_id == appointment_id), None)


def _check_policy(
    state: ClubGovernance,
    appointment: Appointment,
    action: AuthorityAction,
    amount_minor: int | None,
    source_kind: AuthoritySource,
    source_id: str,
) -> AuthorityEvaluation:
    if action in state.policy.board_reserved_actions and appointment.role not in _BOARD_ROLES:
        return _denied(action, appointment.appointment_id,
                       "this action is reserved to an owner or board appointment", appointment.role)
    threshold = state.policy.board_approval_above_minor
    if (action is AuthorityAction.ALLOCATE_BUDGET and threshold is not None
            and amount_minor is not None and amount_minor > threshold
            and appointment.role not in _BOARD_ROLES):
        return _denied(action, appointment.appointment_id,
                       "amount exceeds the configured board approval threshold", appointment.role)
    return AuthorityEvaluation(
        True, action, appointment.appointment_id, appointment.role,
        source_kind, source_id, "explicit active appointment authority applies",
    )


def _grant_covers(grant: AuthorityGrant, amount_minor: int | None) -> bool:
    if grant.action in _AMOUNT_ACTIONS:
        return amount_minor is not None and (
            grant.max_amount_minor is None or amount_minor <= grant.max_amount_minor
        )
    return amount_minor is None


def check_authority(
    state: ClubGovernance,
    actor_appointment_id: str,
    action: AuthorityAction,
    on: WorldDate,
    amount_minor: int | None = None,
) -> AuthorityEvaluation:
    """Return an explainable decision from current direct or delegated mandate."""

    if not isinstance(state, ClubGovernance) or not isinstance(action, AuthorityAction):
        raise TypeError("authority checks require governance state and an explicit action")
    validate_id(actor_appointment_id, kind="authority actor appointment ID")
    if not isinstance(on, WorldDate):
        raise TypeError("authority checks require a world date")
    if action in _AMOUNT_ACTIONS:
        if type(amount_minor) is not int or amount_minor <= 0:
            raise ValueError("financial authority checks require a positive amount")
    elif amount_minor is not None:
        raise ValueError("non-financial authority checks do not accept a money amount")

    actor = _find_appointment(state, actor_appointment_id)
    if actor is None:
        return _denied(action, actor_appointment_id, "appointment is not on this club's authority register")
    if not actor.active_on(on):
        return _denied(action, actor_appointment_id, "appointment is not active on the requested date", actor.role)

    direct = actor.grant_for(action)
    if direct is not None and _grant_covers(direct, amount_minor):
        return _check_policy(
            state, actor, action, amount_minor, AuthoritySource.APPOINTMENT, actor.appointment_id,
        )

    for delegation in state.delegations:
        if delegation.delegate_appointment_id != actor_appointment_id or delegation.action is not action:
            continue
        if not delegation.active_on(on):
            continue
        principal = _find_appointment(state, delegation.delegator_appointment_id)
        if principal is None or not principal.active_on(on):
            continue
        principal_grant = principal.grant_for(action)
        if principal_grant is None or not principal_grant.may_delegate:
            continue
        if action in state.policy.board_reserved_actions:
            continue
        if action is AuthorityAction.ALLOCATE_BUDGET and state.policy.board_approval_above_minor is not None:
            if amount_minor is not None and amount_minor > state.policy.board_approval_above_minor:
                continue
        if principal_grant.max_amount_minor is not None and (
            delegation.max_amount_minor is None
            or delegation.max_amount_minor > principal_grant.max_amount_minor
        ):
            continue
        if delegation.max_amount_minor is not None and amount_minor is not None and (
            amount_minor > delegation.max_amount_minor
        ):
            continue
        if _grant_covers(principal_grant, amount_minor):
            return _check_policy(
                state, actor, action, amount_minor, AuthoritySource.DELEGATION, delegation.delegation_id,
            )

    if direct is not None:
        return _denied(action, actor_appointment_id,
                       "requested amount exceeds the appointment's explicit limit", actor.role)
    return _denied(action, actor_appointment_id,
                   "appointment has no active grant or delegation for this action", actor.role)


def _record_decision(
    state: ClubGovernance,
    authorization: AuthorityEvaluation,
    action: AuthorityAction,
    subject_id: str,
    on: WorldDate,
    outcome: DecisionOutcome,
    reason: str,
    *,
    proposal_id: str | None = None,
    amount_minor: int | None = None,
) -> DecisionLogEntry:
    if authorization.actor_role is None or authorization.source_kind is None or authorization.source_id is None:
        raise ValueError("only an authorized action can be written as a completed decision")
    decision_id = derive_id(
        "decision", str(state.club_id), action.value, subject_id,
        authorization.actor_appointment_id, outcome.value, on.isoformat,
    )
    return DecisionLogEntry(
        decision_id, subject_id, proposal_id, action,
        authorization.actor_appointment_id, authorization.actor_role,
        authorization.source_kind, authorization.source_id, on, outcome, reason,
        amount_minor,
    )


def _rejected(state: ClubGovernance, evaluation: AuthorityEvaluation) -> GovernanceCommandResult:
    return GovernanceCommandResult(
        state, False, evaluation, rejection=evaluation.reason,
    )


def add_staff_appointment(
    state: ClubGovernance,
    actor_appointment_id: str,
    appointment: Appointment,
    on: WorldDate,
) -> GovernanceCommandResult:
    if not isinstance(appointment, Appointment):
        raise TypeError("appointment command requires an Appointment record")
    evaluation = check_authority(state, actor_appointment_id, AuthorityAction.APPOINT_STAFF, on)
    if not evaluation.allowed:
        return _rejected(state, evaluation)
    mandate_evaluation = None
    if appointment.grants:
        mandate_evaluation = check_authority(
            state, actor_appointment_id, AuthorityAction.GRANT_MANDATE, on,
        )
        if not mandate_evaluation.allowed:
            return _rejected(state, mandate_evaluation)
    if appointment.club_id != state.club_id:
        return _rejected(state, _denied(
            AuthorityAction.APPOINT_STAFF, actor_appointment_id,
            "cannot appoint staff to another club",
        ))
    if appointment.starts_on < on:
        return _rejected(state, _denied(
            AuthorityAction.APPOINT_STAFF, actor_appointment_id,
            "new appointments cannot be backdated",
        ))
    actor = _find_appointment(state, actor_appointment_id)
    if actor is not None and not actor.active_on(on):
        return _rejected(state, _denied(
            AuthorityAction.APPOINT_STAFF, actor_appointment_id,
            "appointing authority is not active on the command date", actor.role,
        ))
    existing = next((item for item in state.appointments
                     if item.appointment_id == appointment.appointment_id), None)
    if existing is not None:
        if existing == appointment:
            return GovernanceCommandResult(state, True, evaluation, replayed=True)
        raise ValueError("appointment ID was reused for different terms")
    if appointment.reports_to_appointment_id is not None and _find_appointment(
        state, appointment.reports_to_appointment_id
    ) is None:
        return _rejected(state, _denied(
            AuthorityAction.APPOINT_STAFF, actor_appointment_id,
            "reporting line must reference an existing same-club appointment",
        ))
    if appointment.reports_to_appointment_id is not None:
        supervisor = _find_appointment(state, appointment.reports_to_appointment_id)
        if supervisor is None or not supervisor.active_on(appointment.starts_on):
            return _rejected(state, _denied(
                AuthorityAction.APPOINT_STAFF, actor_appointment_id,
                "reporting appointment must be active when the new appointment starts",
                actor.role if actor else None,
            ))
    for current in state.appointments:
        if current.person_id != appointment.person_id or current.role is not appointment.role:
            continue
        current_end = current.expires_on
        new_end = appointment.expires_on
        overlaps = current_end is None or appointment.starts_on <= current_end
        overlaps = overlaps and (new_end is None or new_end >= current.starts_on)
        if overlaps:
            return _rejected(state, _denied(
                AuthorityAction.APPOINT_STAFF, actor_appointment_id,
                "same person already has an overlapping appointment for this role",
                actor.role if actor else None,
            ))
    decision = _record_decision(
        state, evaluation, AuthorityAction.APPOINT_STAFF,
        appointment.appointment_id, on, DecisionOutcome.EXECUTED,
        f"appointed {appointment.person_id} as {appointment.role.value}",
    )
    decisions = (decision,)
    if mandate_evaluation is not None:
        mandate_decision = _record_decision(
            state, mandate_evaluation, AuthorityAction.GRANT_MANDATE,
            appointment.appointment_id, on, DecisionOutcome.EXECUTED,
            "issued the appointment's explicit authority mandate",
        )
        decisions += (mandate_decision,)
    updated = replace(
        state,
        appointments=state.appointments + (appointment,),
        decisions=state.decisions + decisions,
    )
    return GovernanceCommandResult(updated, True, evaluation, decision=decision)


def change_authority_policy(
    state: ClubGovernance,
    actor_appointment_id: str,
    policy: AuthorityPolicy,
    on: WorldDate,
) -> GovernanceCommandResult:
    if not isinstance(policy, AuthorityPolicy):
        raise TypeError("authority-policy command requires an AuthorityPolicy record")
    evaluation = check_authority(
        state, actor_appointment_id, AuthorityAction.CHANGE_AUTHORITY_POLICY, on,
    )
    if not evaluation.allowed:
        return _rejected(state, evaluation)
    if policy.club_id != state.club_id:
        return _rejected(state, _denied(
            AuthorityAction.CHANGE_AUTHORITY_POLICY, actor_appointment_id,
            "authority policy must belong to this club", evaluation.actor_role,
        ))
    if policy == state.policy:
        return GovernanceCommandResult(state, True, evaluation, replayed=True)
    decision = _record_decision(
        state, evaluation, AuthorityAction.CHANGE_AUTHORITY_POLICY,
        str(state.club_id), on, DecisionOutcome.EXECUTED,
        "updated reserved powers and budget approval threshold",
    )
    updated = replace(
        state, policy=policy, decisions=state.decisions + (decision,),
    )
    return GovernanceCommandResult(updated, True, evaluation, decision=decision)


def add_staff_member(
    state: ClubGovernance,
    actor_appointment_id: str,
    profile: StaffProfile,
    on: WorldDate,
) -> GovernanceCommandResult:
    if not isinstance(profile, StaffProfile):
        raise TypeError("staff registration command requires a StaffProfile")
    evaluation = check_authority(state, actor_appointment_id, AuthorityAction.REGISTER_STAFF, on)
    if not evaluation.allowed:
        return _rejected(state, evaluation)
    appointment = _find_appointment(state, profile.appointment_id)
    if profile.club_id != state.club_id or appointment is None or appointment.person_id != profile.staff_id:
        return _rejected(state, _denied(
            AuthorityAction.REGISTER_STAFF, actor_appointment_id,
            "staff profile must match a registered same-club appointment",
            evaluation.actor_role,
        ))
    if not appointment.active_on(on):
        return _rejected(state, _denied(
            AuthorityAction.REGISTER_STAFF, actor_appointment_id,
            "staff appointment is not active on the registration date", evaluation.actor_role,
        ))
    existing = next((item for item in state.staff if item.staff_id == profile.staff_id), None)
    if existing is not None:
        if existing == profile:
            return GovernanceCommandResult(state, True, evaluation, replayed=True)
        raise ValueError("staff profile ID was reused with different functions or capacity")
    decision = _record_decision(
        state, evaluation, AuthorityAction.REGISTER_STAFF,
        profile.staff_id, on, DecisionOutcome.EXECUTED,
        "registered staff functions and shared daily capacity",
    )
    updated = replace(
        state, staff=state.staff + (profile,), decisions=state.decisions + (decision,),
    )
    return GovernanceCommandResult(updated, True, evaluation, decision=decision)


def create_staff_task(
    state: ClubGovernance,
    actor_appointment_id: str,
    task: StaffTask,
    on: WorldDate,
) -> GovernanceCommandResult:
    if not isinstance(task, StaffTask):
        raise TypeError("task command requires a StaffTask record")
    if task.club_id != state.club_id or task.due_on < on:
        return _rejected(state, _denied(
            AuthorityAction.CREATE_TASK, actor_appointment_id,
            "task must belong to this club and have a current or future deadline",
        ))
    existing = next((item for item in state.tasks if item.task_id == task.task_id), None)
    evaluation = check_authority(state, actor_appointment_id, AuthorityAction.CREATE_TASK, on)
    if existing is not None:
        if existing == task:
            return GovernanceCommandResult(state, evaluation.allowed, evaluation,
                                           rejection=None if evaluation.allowed else evaluation.reason,
                                           replayed=evaluation.allowed)
        raise ValueError("task ID was reused for different work")
    if not evaluation.allowed:
        return _rejected(state, evaluation)
    decision = _record_decision(
        state, evaluation, AuthorityAction.CREATE_TASK,
        task.task_id, on, DecisionOutcome.EXECUTED,
        f"created {task.function.value} task due {task.due_on.isoformat}",
    )
    updated = replace(state, tasks=state.tasks + (task,), decisions=state.decisions + (decision,))
    return GovernanceCommandResult(updated, True, evaluation, decision=decision)


def assign_staff_task(
    state: ClubGovernance,
    actor_appointment_id: str,
    assignment: StaffTaskAssignment,
    on: WorldDate,
) -> GovernanceCommandResult:
    if not isinstance(assignment, StaffTaskAssignment):
        raise TypeError("assignment command requires a StaffTaskAssignment record")
    evaluation = check_authority(state, actor_appointment_id, AuthorityAction.ASSIGN_TASK, on)
    existing = next((item for item in state.assignments if item.assignment_id == assignment.assignment_id), None)
    if existing is not None:
        if existing != assignment:
            raise ValueError("assignment ID was reused for different work")
        return GovernanceCommandResult(state, evaluation.allowed, evaluation,
                                       rejection=None if evaluation.allowed else evaluation.reason,
                                       replayed=evaluation.allowed)
    if not evaluation.allowed:
        return _rejected(state, evaluation)
    if assignment.assigned_by_appointment_id != actor_appointment_id:
        return _rejected(state, _denied(
            AuthorityAction.ASSIGN_TASK, actor_appointment_id,
            "assignment actor does not match its attribution", evaluation.actor_role,
        ))
    task = next((item for item in state.tasks if item.task_id == assignment.task_id), None)
    profile = next((item for item in state.staff if item.staff_id == assignment.staff_id), None)
    target_appointment = _find_appointment(state, profile.appointment_id) if profile is not None else None
    if task is None or profile is None or target_appointment is None:
        return _rejected(state, _denied(
            AuthorityAction.ASSIGN_TASK, actor_appointment_id,
            "task and assigned staff member must exist on this club's register", evaluation.actor_role,
        ))
    if assignment.scheduled_on < on or assignment.scheduled_on > task.due_on:
        return _rejected(state, _denied(
            AuthorityAction.ASSIGN_TASK, actor_appointment_id,
            "scheduled work must fall between command date and task deadline", evaluation.actor_role,
        ))
    if not target_appointment.active_on(assignment.scheduled_on):
        return _rejected(state, _denied(
            AuthorityAction.ASSIGN_TASK, actor_appointment_id,
            "assigned staff appointment will not be active on the scheduled date", evaluation.actor_role,
        ))
    if task.function not in profile.functions or assignment.work_units != task.work_units:
        return _rejected(state, _denied(
            AuthorityAction.ASSIGN_TASK, actor_appointment_id,
            "staff function or assigned work does not meet the task definition", evaluation.actor_role,
        ))
    if any(item.task_id == task.task_id for item in state.assignments):
        return _rejected(state, _denied(
            AuthorityAction.ASSIGN_TASK, actor_appointment_id,
            "task already has an assignment", evaluation.actor_role,
        ))
    booked = sum(
        item.work_units for item in state.assignments
        if item.staff_id == profile.staff_id and item.scheduled_on == assignment.scheduled_on
    )
    if booked + assignment.work_units > profile.daily_capacity_units:
        return _rejected(state, _denied(
            AuthorityAction.ASSIGN_TASK, actor_appointment_id,
            "assignment would exceed shared daily staff capacity", evaluation.actor_role,
        ))
    decision = _record_decision(
        state, evaluation, AuthorityAction.ASSIGN_TASK,
        assignment.assignment_id, on, DecisionOutcome.EXECUTED,
        f"assigned {task.function.value} work to {profile.staff_id}",
    )
    updated = replace(
        state,
        assignments=state.assignments + (assignment,),
        decisions=state.decisions + (decision,),
    )
    return GovernanceCommandResult(updated, True, evaluation, decision=decision)


def create_budget_proposal(
    state: ClubGovernance,
    actor_appointment_id: str,
    proposal: BudgetProposal,
    on: WorldDate,
) -> GovernanceCommandResult:
    if not isinstance(proposal, BudgetProposal):
        raise TypeError("budget proposal command requires a BudgetProposal record")
    if not isinstance(on, WorldDate):
        raise TypeError("budget proposal command requires its decision date")
    evaluation = check_authority(
        state, actor_appointment_id, AuthorityAction.PROPOSE_BUDGET,
        on, proposal.amount_minor,
    )
    if not evaluation.allowed:
        return _rejected(state, evaluation)
    if proposal.proposed_on != on:
        return _rejected(state, _denied(
            AuthorityAction.PROPOSE_BUDGET, actor_appointment_id,
            "proposal date must match the command date", evaluation.actor_role,
        ))
    if proposal.proposed_by_appointment_id != actor_appointment_id:
        return _rejected(state, _denied(
            AuthorityAction.PROPOSE_BUDGET, actor_appointment_id,
            "proposal attribution must match the proposing appointment", evaluation.actor_role,
        ))
    if proposal.club_id != state.club_id or proposal.currency_id != state.budget.currency_id:
        return _rejected(state, _denied(
            AuthorityAction.PROPOSE_BUDGET, actor_appointment_id,
            "proposal club and currency must match this budget book", evaluation.actor_role,
        ))
    if proposal.status is not BudgetProposalStatus.OPEN:
        return _rejected(state, _denied(
            AuthorityAction.PROPOSE_BUDGET, actor_appointment_id,
            "new budget proposals must be open", evaluation.actor_role,
        ))
    existing = next((item for item in state.proposals if item.proposal_id == proposal.proposal_id), None)
    if existing is not None:
        if existing == proposal:
            return GovernanceCommandResult(state, True, evaluation, replayed=True)
        raise ValueError("proposal ID was reused with different terms")
    updated = replace(state, proposals=state.proposals + (proposal,))
    return GovernanceCommandResult(updated, True, evaluation)


def decide_budget_proposal(
    state: ClubGovernance,
    actor_appointment_id: str,
    proposal_id: str,
    approve: bool,
    on: WorldDate,
) -> GovernanceCommandResult:
    validate_id(proposal_id, kind="budget proposal ID")
    if type(approve) is not bool:
        raise TypeError("budget proposal decision must be approve or decline")
    proposal = next((item for item in state.proposals if item.proposal_id == proposal_id), None)
    if proposal is None:
        evaluation = _denied(
            AuthorityAction.ALLOCATE_BUDGET, actor_appointment_id,
            "budget proposal does not exist on this club's register",
        )
        return _rejected(state, evaluation)
    desired_outcome = DecisionOutcome.APPROVED if approve else DecisionOutcome.DECLINED
    previous = next((item for item in state.decisions if item.proposal_id == proposal_id), None)
    if previous is not None:
        if (previous.actor_appointment_id == actor_appointment_id
                and previous.outcome is desired_outcome and previous.decided_on == on):
            evaluation = AuthorityEvaluation(
                True, AuthorityAction.ALLOCATE_BUDGET, actor_appointment_id,
                previous.actor_role, previous.authority_source, previous.authority_source_id,
                "matching budget decision was already recorded",
            )
            return GovernanceCommandResult(state, True, evaluation, decision=previous, replayed=True)
        actor = _find_appointment(state, actor_appointment_id)
        return _rejected(state, _denied(
            AuthorityAction.ALLOCATE_BUDGET, actor_appointment_id,
            "budget proposal already has a recorded decision",
            actor.role if actor is not None else None,
        ))
    if proposal.status is not BudgetProposalStatus.OPEN:
        return _rejected(state, _denied(
            AuthorityAction.ALLOCATE_BUDGET, actor_appointment_id,
            "budget proposal is not open", _find_appointment(state, actor_appointment_id).role
            if _find_appointment(state, actor_appointment_id) else None,
        ))
    if on < proposal.proposed_on:
        actor = _find_appointment(state, actor_appointment_id)
        return _rejected(state, _denied(
            AuthorityAction.ALLOCATE_BUDGET, actor_appointment_id,
            "budget proposal cannot be decided before it was submitted",
            actor.role if actor is not None else None,
        ))
    evaluation = check_authority(
        state, actor_appointment_id, AuthorityAction.ALLOCATE_BUDGET, on, proposal.amount_minor,
    )
    if not evaluation.allowed:
        return _rejected(state, evaluation)
    next_budget = state.budget
    if approve:
        if proposal.amount_minor > state.budget.unallocated_cash_minor:
            return _rejected(state, _denied(
                AuthorityAction.ALLOCATE_BUDGET, actor_appointment_id,
                "budget allocation would exceed club cash on hand", evaluation.actor_role,
            ))
        allocations = list(state.budget.allocations)
        index = next((i for i, item in enumerate(allocations) if item.category == proposal.category), None)
        if index is None:
            allocations.append(BudgetAllocation(proposal.category, proposal.amount_minor))
        else:
            previous_allocation = allocations[index]
            allocations[index] = BudgetAllocation(
                previous_allocation.category, previous_allocation.amount_minor + proposal.amount_minor,
            )
        next_budget = replace(state.budget, allocations=tuple(allocations))
    reason = (
        f"approved {proposal.category} budget allocation from club cash"
        if approve else f"declined {proposal.category} budget proposal"
    )
    decision = _record_decision(
        state, evaluation, AuthorityAction.ALLOCATE_BUDGET,
        proposal.proposal_id, on, desired_outcome, reason,
        proposal_id=proposal.proposal_id, amount_minor=proposal.amount_minor,
    )
    status = BudgetProposalStatus.APPROVED if approve else BudgetProposalStatus.DECLINED
    proposals = tuple(
        replace(item, status=status) if item.proposal_id == proposal_id else item
        for item in state.proposals
    )
    updated = replace(
        state, budget=next_budget, proposals=proposals,
        decisions=state.decisions + (decision,),
    )
    return GovernanceCommandResult(updated, True, evaluation, decision=decision)


def delegate_authority(
    state: ClubGovernance,
    delegation: Delegation,
    on: WorldDate,
) -> GovernanceCommandResult:
    if not isinstance(delegation, Delegation):
        raise TypeError("delegation command requires a Delegation record")
    delegator = _find_appointment(state, delegation.delegator_appointment_id)
    delegate = _find_appointment(state, delegation.delegate_appointment_id)
    evaluation = check_authority(
        state, delegation.delegator_appointment_id,
        AuthorityAction.DELEGATE_AUTHORITY, on,
    )
    if not evaluation.allowed:
        return _rejected(state, evaluation)
    if evaluation.source_kind is not AuthoritySource.APPOINTMENT:
        return _rejected(state, _denied(
            AuthorityAction.DELEGATE_AUTHORITY, delegation.delegator_appointment_id,
            "delegated powers cannot be redelegated", evaluation.actor_role,
        ))
    if delegator is None or delegate is None or delegator.club_id != delegate.club_id:
        return _rejected(state, _denied(
            AuthorityAction.DELEGATE_AUTHORITY, delegation.delegator_appointment_id,
            "delegation parties must be registered at the same club", evaluation.actor_role,
        ))
    source_grant = delegator.grant_for(delegation.action)
    if source_grant is None or not source_grant.may_delegate:
        return _rejected(state, _denied(
            AuthorityAction.DELEGATE_AUTHORITY, delegation.delegator_appointment_id,
            "issuer has no direct delegable grant for this action", evaluation.actor_role,
        ))
    if delegation.action in state.policy.board_reserved_actions:
        return _rejected(state, _denied(
            AuthorityAction.DELEGATE_AUTHORITY, delegation.delegator_appointment_id,
            "board-reserved powers cannot be delegated", evaluation.actor_role,
        ))
    if delegation.action is AuthorityAction.ALLOCATE_BUDGET:
        threshold = state.policy.board_approval_above_minor
        if threshold is not None and (
            delegation.max_amount_minor is None or delegation.max_amount_minor > threshold
        ):
            return _rejected(state, _denied(
                AuthorityAction.DELEGATE_AUTHORITY, delegation.delegator_appointment_id,
                "delegated budget limit cannot cross the board approval threshold", evaluation.actor_role,
            ))
    if source_grant.max_amount_minor is not None and (
        delegation.max_amount_minor is None
        or delegation.max_amount_minor > source_grant.max_amount_minor
    ):
        return _rejected(state, _denied(
            AuthorityAction.DELEGATE_AUTHORITY, delegation.delegator_appointment_id,
            "delegation would exceed the issuer's direct amount limit", evaluation.actor_role,
        ))
    if delegation.starts_on < on or not delegator.active_on(delegation.starts_on) or not delegate.active_on(delegation.starts_on):
        return _rejected(state, _denied(
            AuthorityAction.DELEGATE_AUTHORITY, delegation.delegator_appointment_id,
            "delegation must begin while both appointments are active and not in the past", evaluation.actor_role,
        ))
    if delegator.expires_on is not None and (
        delegation.expires_on is None or delegation.expires_on > delegator.expires_on
    ):
        return _rejected(state, _denied(
            AuthorityAction.DELEGATE_AUTHORITY, delegation.delegator_appointment_id,
            "delegation cannot outlive the issuer appointment", evaluation.actor_role,
        ))
    if delegate.expires_on is not None and (
        delegation.expires_on is None or delegation.expires_on > delegate.expires_on
    ):
        return _rejected(state, _denied(
            AuthorityAction.DELEGATE_AUTHORITY, delegation.delegator_appointment_id,
            "delegation cannot outlive the receiving appointment", evaluation.actor_role,
        ))
    existing = next((item for item in state.delegations if item.delegation_id == delegation.delegation_id), None)
    if existing is not None:
        if existing == delegation:
            return GovernanceCommandResult(state, True, evaluation, replayed=True)
        raise ValueError("delegation ID was reused with different terms")
    decision = _record_decision(
        state, evaluation, AuthorityAction.DELEGATE_AUTHORITY,
        delegation.delegation_id, on, DecisionOutcome.EXECUTED,
        f"delegated {delegation.action.value} to {delegate.appointment_id}",
    )
    updated = replace(
        state,
        delegations=state.delegations + (delegation,),
        decisions=state.decisions + (decision,),
    )
    return GovernanceCommandResult(updated, True, evaluation, decision=decision)
