"""Dated, authorized staff appointments across annual world boundaries.

This headless ledger composes existing per-club governance histories. It does
not hire people or silently end contracts: appointments are immutable and an
expired manager can be replaced from the following day onward.
"""

from __future__ import annotations

import hashlib
from calendar import monthrange
from dataclasses import dataclass
from datetime import date

from games.touchline.esb.club.governance import (
    Appointment,
    AuthorityAction,
    Delegation,
    ClubGovernance,
    ClubRole,
    DecisionLogEntry,
    DecisionOutcome,
    StaffProfile,
    add_staff_appointment,
    add_staff_member,
    change_authority_policy,
    delegate_authority,
)
from games.touchline.esb.ids import validate_id
from games.touchline.esb.serialization import dumps, loads
from games.touchline.esb.time import WorldDate


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _valid_digest(value: str, label: str) -> None:
    if (not isinstance(value, str) or len(value) != 64
            or any(char not in "0123456789abcdef" for char in value)):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")


def _next_anniversary(current: WorldDate) -> WorldDate:
    year = current.day.year + 1
    return WorldDate(date(
        year, current.day.month,
        min(current.day.day, monthrange(year, current.day.month)[1]),
    ))


def _canonical_clubs(clubs: tuple[ClubGovernance, ...]) -> tuple[ClubGovernance, ...]:
    if not isinstance(clubs, tuple) or any(not isinstance(item, ClubGovernance) for item in clubs):
        raise TypeError("staff continuity requires an immutable tuple of club governance records")
    result = tuple(sorted(clubs, key=lambda item: str(item.club_id)))
    ids = [str(item.club_id) for item in result]
    if not result or len(ids) != len(set(ids)):
        raise ValueError("staff continuity requires unique club governance snapshots")
    return result


def _snapshot_sha256(world_id: str, as_of: WorldDate, clubs: tuple[ClubGovernance, ...]) -> str:
    return _sha256(dumps(_SnapshotMaterial(world_id, as_of, clubs)))


@dataclass(frozen=True)
class _SnapshotMaterial:
    world_id: str
    as_of: WorldDate
    clubs: tuple[ClubGovernance, ...]


@dataclass(frozen=True, order=True)
class GovernanceRecordRef:
    """An unambiguous club-local governance record reference."""

    club_id: str
    record_id: str

    def __post_init__(self) -> None:
        validate_id(self.club_id, kind="governance reference club ID")
        validate_id(self.record_id, kind="governance reference record ID")


@dataclass(frozen=True)
class ManagerCoverage:
    club_id: str
    appointment_id: str
    person_id: str

    def __post_init__(self) -> None:
        validate_id(self.club_id, kind="manager coverage club ID")
        validate_id(self.appointment_id, kind="manager coverage appointment ID")
        validate_id(self.person_id, kind="manager coverage person ID")


@dataclass(frozen=True)
class _StaffReceiptMaterial:
    sequence: int
    source_as_of: WorldDate
    boundary_on: WorldDate
    source_sha256: str
    request_sha256: str
    result_sha256: str
    added_appointment_ids: tuple[GovernanceRecordRef, ...]
    added_staff_ids: tuple[GovernanceRecordRef, ...]
    expired_appointment_ids: tuple[GovernanceRecordRef, ...]
    active_managers: tuple[ManagerCoverage, ...]
    governance_decision_ids: tuple[GovernanceRecordRef, ...]
    clubs_snapshot: tuple[ClubGovernance, ...]


def _receipt_material(receipt: StaffContinuityReceipt) -> str:
    return dumps(_StaffReceiptMaterial(
        receipt.sequence,
        receipt.source_as_of,
        receipt.boundary_on,
        receipt.source_sha256,
        receipt.request_sha256,
        receipt.result_sha256,
        receipt.added_appointment_ids,
        receipt.added_staff_ids,
        receipt.expired_appointment_ids,
        receipt.active_managers,
        receipt.governance_decision_ids,
        receipt.clubs_snapshot,
    ))


def _canonical_refs(values: tuple[GovernanceRecordRef, ...], label: str) -> None:
    if (not isinstance(values, tuple)
            or any(not isinstance(item, GovernanceRecordRef) for item in values)
            or values != tuple(sorted(set(values)))):
        raise ValueError(f"{label} must be unique sorted governance references")


@dataclass(frozen=True)
class StaffContinuityReceipt:
    sequence: int
    source_as_of: WorldDate
    boundary_on: WorldDate
    source_sha256: str
    request_sha256: str
    result_sha256: str
    added_appointment_ids: tuple[GovernanceRecordRef, ...]
    added_staff_ids: tuple[GovernanceRecordRef, ...]
    expired_appointment_ids: tuple[GovernanceRecordRef, ...]
    active_managers: tuple[ManagerCoverage, ...]
    governance_decision_ids: tuple[GovernanceRecordRef, ...]
    clubs_snapshot: tuple[ClubGovernance, ...]
    receipt_sha256: str

    def __post_init__(self) -> None:
        if type(self.sequence) is not int or self.sequence <= 0:
            raise ValueError("staff continuity receipt sequence must be positive")
        if not isinstance(self.source_as_of, WorldDate) or not isinstance(self.boundary_on, WorldDate):
            raise TypeError("staff continuity receipt requires source and boundary dates")
        if self.boundary_on != _next_anniversary(self.source_as_of):
            raise ValueError("staff continuity receipt must advance one annual anniversary")
        for value, label in (
            (self.source_sha256, "staff continuity source"),
            (self.request_sha256, "staff continuity request"),
            (self.result_sha256, "staff continuity result"),
        ):
            _valid_digest(value, label)
        _canonical_refs(self.added_appointment_ids, "added appointments")
        _canonical_refs(self.added_staff_ids, "added staff")
        _canonical_refs(self.expired_appointment_ids, "expired appointments")
        _canonical_refs(self.governance_decision_ids, "governance decisions")
        canonical_snapshot = _canonical_clubs(self.clubs_snapshot)
        if canonical_snapshot != self.clubs_snapshot:
            raise ValueError("staff receipt governance snapshot must be sorted by club ID")
        if (not isinstance(self.active_managers, tuple)
                or any(not isinstance(item, ManagerCoverage) for item in self.active_managers)):
            raise TypeError("active managers must be an immutable coverage tuple")
        keys = [(item.club_id, item.appointment_id) for item in self.active_managers]
        if keys != sorted(set(keys)):
            raise ValueError("active manager coverage must be unique and sorted")
        _valid_digest(self.receipt_sha256, "staff continuity receipt")
        if _sha256(_receipt_material(self)) != self.receipt_sha256:
            raise ValueError("staff continuity receipt does not match its sealed evidence")


def _overlaps(left: Appointment, right: Appointment) -> bool:
    left_end = left.expires_on.day if left.expires_on is not None else date.max
    right_end = right.expires_on.day if right.expires_on is not None else date.max
    return left.starts_on.day <= right_end and right.starts_on.day <= left_end


def _manager_coverage(
    clubs: tuple[ClubGovernance, ...], as_of: WorldDate,
) -> tuple[ManagerCoverage, ...]:
    terms = [
        appointment
        for club in clubs
        for appointment in club.appointments
        if appointment.role is ClubRole.MANAGER
    ]
    for index, left in enumerate(terms):
        for right in terms[index + 1:]:
            if left.club_id == right.club_id and _overlaps(left, right):
                raise ValueError(f"club {left.club_id} has overlapping manager appointments")
            if (left.person_id == right.person_id and left.club_id != right.club_id
                    and _overlaps(left, right)):
                raise ValueError(f"manager {left.person_id} has overlapping cross-club appointments")
    active = [item for item in terms if item.active_on(as_of)]
    slots = [item.club_id for item in active]
    people = [item.person_id for item in active]
    if len(slots) != len(set(slots)):
        raise ValueError("a club cannot have more than one active manager")
    if len(people) != len(set(people)):
        raise ValueError("a person cannot actively manage multiple clubs")
    return tuple(sorted(
        (ManagerCoverage(str(item.club_id), item.appointment_id, item.person_id) for item in active),
        key=lambda item: (item.club_id, item.appointment_id),
    ))


def _record_maps(clubs: tuple[ClubGovernance, ...], attribute: str, id_field: str):
    return {
        str(club.club_id): {
            getattr(item, id_field): item for item in getattr(club, attribute)
        }
        for club in clubs
    }


def _validate_receipt_evidence(
    genesis_clubs: tuple[ClubGovernance, ...],
    clubs: tuple[ClubGovernance, ...],
    receipts: tuple[StaffContinuityReceipt, ...],
    world_id: str,
) -> None:
    expected_club_ids = {str(item.club_id) for item in genesis_clubs}
    if {str(item.club_id) for item in clubs} != expected_club_ids:
        raise ValueError("staff continuity cannot add or remove clubs after genesis")
    previous_clubs = genesis_clubs

    for receipt in receipts:
        boundary_clubs = receipt.clubs_snapshot
        if {str(item.club_id) for item in boundary_clubs} != expected_club_ids:
            raise ValueError("staff receipt cannot add or remove clubs after genesis")
        snapshot_hash = _snapshot_sha256(world_id, receipt.boundary_on, boundary_clubs)
        if (receipt.result_sha256 != snapshot_hash
                or receipt.request_sha256 != snapshot_hash):
            raise ValueError("staff receipt governance snapshot differs from its sealed request or result")

        previous_by_id = {str(item.club_id): item for item in previous_clubs}
        boundary_by_id = {str(item.club_id): item for item in boundary_clubs}
        expected_added_appointments: list[GovernanceRecordRef] = []
        expected_added_staff: list[GovernanceRecordRef] = []
        expected_expired: list[GovernanceRecordRef] = []
        expected_decisions: list[GovernanceRecordRef] = []

        for club_id in sorted(expected_club_ids):
            previous = previous_by_id[club_id]
            current = boundary_by_id[club_id]
            previous_appointments = {item.appointment_id: item for item in previous.appointments}
            current_appointments = {item.appointment_id: item for item in current.appointments}
            previous_staff = {item.staff_id: item for item in previous.staff}
            current_staff = {item.staff_id: item for item in current.staff}
            previous_decisions = {item.decision_id: item for item in previous.decisions}
            current_decisions = {item.decision_id: item for item in current.decisions}

            for label, prior, latest in (
                ("appointments", previous_appointments, current_appointments),
                ("staff", previous_staff, current_staff),
                ("decisions", previous_decisions, current_decisions),
            ):
                for record_id, record in prior.items():
                    if latest.get(record_id) != record:
                        raise ValueError(f"annual governance cannot remove or rewrite prior {label}")

            new_appointments = {
                key: item for key, item in current_appointments.items()
                if key not in previous_appointments
            }
            new_staff = {
                key: item for key, item in current_staff.items() if key not in previous_staff
            }
            new_decisions = [
                item for item in current.decisions if item.decision_id not in previous_decisions
            ]
            new_decisions_by_id = {item.decision_id: item for item in new_decisions}

            for appointment_id, appointment in new_appointments.items():
                if appointment.starts_on != receipt.boundary_on:
                    raise ValueError("every post-genesis appointment must start on a recorded annual boundary")
                expected_added_appointments.append(GovernanceRecordRef(club_id, appointment_id))
            for staff_id, profile in new_staff.items():
                appointment = current_appointments.get(profile.appointment_id)
                if appointment is None or not appointment.active_on(receipt.boundary_on):
                    raise ValueError("staff registration must reference an active same-club appointment")
                expected_added_staff.append(GovernanceRecordRef(club_id, staff_id))
            for appointment in previous.appointments:
                if (appointment.expires_on is not None
                        and receipt.source_as_of <= appointment.expires_on < receipt.boundary_on):
                    expected_expired.append(
                        GovernanceRecordRef(club_id, appointment.appointment_id),
                    )

            # Replay staff and policy commands against the governance snapshot
            # available at each recorded decision. This checks the actual
            # authority policy and mandate, not just the shape of a decision row.
            replay = previous
            generated_decisions: dict[str, DecisionLogEntry] = {}
            relevant_actions = {
                AuthorityAction.APPOINT_STAFF,
                AuthorityAction.REGISTER_STAFF,
                AuthorityAction.GRANT_MANDATE,
                AuthorityAction.CHANGE_AUTHORITY_POLICY,
                AuthorityAction.DELEGATE_AUTHORITY,
            }
            policy_changes = sum(
                item.action is AuthorityAction.CHANGE_AUTHORITY_POLICY
                for item in new_decisions
            )
            if policy_changes > 1:
                raise ValueError("multiple same-boundary authority policy changes lack intermediate snapshots")

            for decision in new_decisions:
                if decision.action not in relevant_actions:
                    continue
                if decision.action is AuthorityAction.GRANT_MANDATE:
                    if generated_decisions.get(decision.decision_id) != decision:
                        raise ValueError("GRANT_MANDATE evidence must be emitted by an authorized appointment command")
                    continue
                if decision.decided_on != receipt.boundary_on or decision.outcome is not DecisionOutcome.EXECUTED:
                    raise ValueError("staff and authority-policy commands require dated executed decisions")

                if decision.action is AuthorityAction.APPOINT_STAFF:
                    appointment = new_appointments.get(decision.subject_id)
                    if appointment is None:
                        raise ValueError("APPOINT_STAFF decision does not reference a new appointment")
                    command = add_staff_appointment(
                        replay, decision.actor_appointment_id, appointment, receipt.boundary_on,
                    )
                    if not command.accepted:
                        raise ValueError(
                            "APPOINT_STAFF decision fails current governance authority: "
                            f"{command.rejection}"
                        )
                elif decision.action is AuthorityAction.REGISTER_STAFF:
                    profile = new_staff.get(decision.subject_id)
                    if profile is None:
                        raise ValueError("REGISTER_STAFF decision does not reference a new staff profile")
                    command = add_staff_member(
                        replay, decision.actor_appointment_id, profile, receipt.boundary_on,
                    )
                    if not command.accepted:
                        raise ValueError(
                            "REGISTER_STAFF decision fails current governance authority: "
                            f"{command.rejection}"
                        )
                elif decision.action is AuthorityAction.DELEGATE_AUTHORITY:
                    delegation = next((item for item in current.delegations
                                       if item.delegation_id == decision.subject_id
                                       and item.delegation_id not in {
                                           value.delegation_id for value in previous.delegations
                                       }), None)
                    if delegation is None:
                        raise ValueError("DELEGATE_AUTHORITY decision does not reference a new delegation")
                    command = delegate_authority(replay, delegation, receipt.boundary_on)
                    if not command.accepted:
                        raise ValueError(
                            "delegation decision fails current governance authority: "
                            f"{command.rejection}"
                        )
                else:
                    command = change_authority_policy(
                        replay, decision.actor_appointment_id, current.policy,
                        receipt.boundary_on,
                    )
                    if not command.accepted:
                        raise ValueError(
                            "authority-policy decision fails current governance authority: "
                            f"{command.rejection}"
                        )

                emitted = [item for item in command.state.decisions
                           if item.decision_id not in {value.decision_id for value in replay.decisions}]
                for item in emitted:
                    if new_decisions_by_id.get(item.decision_id) != item:
                        raise ValueError("governance command evidence differs from its dated decision snapshot")
                    generated_decisions[item.decision_id] = item
                replay = command.state

            actual_relevant = {
                item.decision_id for item in new_decisions if item.action in relevant_actions
            }
            if actual_relevant != set(generated_decisions):
                raise ValueError("staff or policy decision evidence is incomplete or uncommanded")
            if ({item.appointment_id for item in replay.appointments}
                    != {item.appointment_id for item in current.appointments}
                    or {item.staff_id for item in replay.staff}
                    != {item.staff_id for item in current.staff}
                    or set(replay.delegations) != set(current.delegations)
                    or replay.policy != current.policy):
                raise ValueError("governance staffing or policy snapshot cannot be reconstructed from authorized commands")

            expected_decisions.extend(
                GovernanceRecordRef(club_id, item.decision_id)
                for item in generated_decisions.values()
                if item.action in {
                    AuthorityAction.APPOINT_STAFF,
                    AuthorityAction.GRANT_MANDATE,
                    AuthorityAction.REGISTER_STAFF,
                    AuthorityAction.DELEGATE_AUTHORITY,
                    AuthorityAction.CHANGE_AUTHORITY_POLICY,
                }
            )

        expected_active = _manager_coverage(boundary_clubs, receipt.boundary_on)
        expected_values = (
            (receipt.added_appointment_ids, tuple(sorted(expected_added_appointments)), "appointment additions"),
            (receipt.added_staff_ids, tuple(sorted(expected_added_staff)), "staff additions"),
            (receipt.expired_appointment_ids, tuple(sorted(expected_expired)), "expired appointments"),
            (receipt.governance_decision_ids, tuple(sorted(expected_decisions)), "governance decision references"),
            (receipt.active_managers, expected_active, "active manager coverage"),
        )
        for actual, expected, label in expected_values:
            if actual != expected:
                raise ValueError(f"staff continuity receipt has false or incomplete {label}")
        previous_clubs = boundary_clubs

    if previous_clubs != clubs:
        raise ValueError("current governance history differs from the last retained annual snapshot")


@dataclass(frozen=True)
class StaffContinuityState:
    world_id: str
    genesis_as_of: WorldDate
    genesis_clubs: tuple[ClubGovernance, ...]
    as_of: WorldDate
    clubs: tuple[ClubGovernance, ...]
    receipts: tuple[StaffContinuityReceipt, ...] = ()
    schema_version: int = 1

    def __post_init__(self) -> None:
        validate_id(self.world_id, kind="staff continuity world ID")
        if not isinstance(self.genesis_as_of, WorldDate) or not isinstance(self.as_of, WorldDate):
            raise TypeError("staff continuity requires explicit genesis and as-of dates")
        if self.as_of < self.genesis_as_of:
            raise ValueError("staff continuity cannot precede its genesis date")
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("unsupported staff continuity schema version")
        canonical_genesis = _canonical_clubs(self.genesis_clubs)
        canonical_current = _canonical_clubs(self.clubs)
        if self.genesis_clubs != canonical_genesis or self.clubs != canonical_current:
            raise ValueError("staff continuity clubs must be sorted by club ID")
        if not isinstance(self.receipts, tuple) or any(
            not isinstance(item, StaffContinuityReceipt) for item in self.receipts
        ):
            raise TypeError("staff continuity receipts must be immutable validated records")
        for club in self.genesis_clubs:
            if any(item.starts_on > self.genesis_as_of for item in club.appointments):
                raise ValueError("genesis cannot contain future appointments outside a boundary receipt")
            if any(item.decided_on > self.genesis_as_of for item in club.decisions):
                raise ValueError("genesis cannot contain future governance decisions")
        previous: StaffContinuityReceipt | None = None
        for sequence, receipt in enumerate(self.receipts, start=1):
            if receipt.sequence != sequence:
                raise ValueError("staff continuity receipts must have consecutive sequence numbers")
            expected_source_date = self.genesis_as_of if previous is None else previous.boundary_on
            expected_source_hash = (
                _snapshot_sha256(self.world_id, self.genesis_as_of, self.genesis_clubs)
                if previous is None else previous.result_sha256
            )
            if (receipt.source_as_of != expected_source_date
                    or receipt.boundary_on != _next_anniversary(expected_source_date)):
                raise ValueError("staff continuity receipt does not follow its annual genesis/boundary date")
            if receipt.source_sha256 != expected_source_hash:
                raise ValueError("staff continuity receipt source does not continue its snapshot hash chain")
            previous = receipt
        if self.receipts:
            last = self.receipts[-1]
            if (last.boundary_on != self.as_of
                    or last.result_sha256 != _snapshot_sha256(self.world_id, self.as_of, self.clubs)):
                raise ValueError("staff continuity state differs from its latest sealed receipt")
        elif self.as_of != self.genesis_as_of or self.clubs != self.genesis_clubs:
            raise ValueError("staff continuity without receipts must equal its genesis snapshot")
        _validate_receipt_evidence(
            self.genesis_clubs, self.clubs, self.receipts, self.world_id,
        )
        _manager_coverage(self.clubs, self.as_of)

    @property
    def genesis_sha256(self) -> str:
        return _snapshot_sha256(self.world_id, self.genesis_as_of, self.genesis_clubs)

    def to_json(self) -> str:
        return dumps(self)

    @classmethod
    def from_json(cls, value: str) -> StaffContinuityState:
        return loads(value, cls)


def create_staff_continuity(
    world_id: str,
    as_of: WorldDate,
    clubs: tuple[ClubGovernance, ...],
) -> StaffContinuityState:
    """Seed a world ledger from the caller's immutable governance snapshots."""
    canonical = _canonical_clubs(clubs)
    return StaffContinuityState(world_id, as_of, canonical, as_of, canonical)


def advance_staff_continuity(
    state: StaffContinuityState,
    boundary_on: WorldDate,
    clubs: tuple[ClubGovernance, ...],
) -> StaffContinuityState:
    """Accept exactly one authorized annual governance update, with safe retry."""
    if not isinstance(state, StaffContinuityState) or not isinstance(boundary_on, WorldDate):
        raise TypeError("staff continuity advancement requires state and explicit boundary date")
    current_hash = _snapshot_sha256(state.world_id, state.as_of, state.clubs)
    candidate = _canonical_clubs(clubs)
    request_hash = _snapshot_sha256(state.world_id, boundary_on, candidate)
    if boundary_on == state.as_of:
        if state.receipts and state.receipts[-1].request_sha256 == request_hash:
            return state
        if not state.receipts and current_hash == request_hash:
            return state
        raise ValueError("same-date staff continuity retry conflicts with its recorded request")
    expected = _next_anniversary(state.as_of)
    if boundary_on != expected:
        raise ValueError(f"staff continuity boundary must be the next annual anniversary ({expected.isoformat})")
    if tuple(str(item.club_id) for item in candidate) != tuple(str(item.club_id) for item in state.clubs):
        raise ValueError("staff continuity cannot add or remove clubs during an annual boundary")

    old_by_club = {str(item.club_id): item for item in state.clubs}
    new_by_club = {str(item.club_id): item for item in candidate}
    added_appointments: list[GovernanceRecordRef] = []
    added_staff: list[GovernanceRecordRef] = []
    decision_refs: list[GovernanceRecordRef] = []
    expired_appointments: list[GovernanceRecordRef] = []
    for club_id in sorted(old_by_club):
        old, new = old_by_club[club_id], new_by_club[club_id]
        for field_name, id_field in (
            ("appointments", "appointment_id"),
            ("staff", "staff_id"),
            ("decisions", "decision_id"),
        ):
            old_records = getattr(old, field_name)
            new_by_id = {getattr(item, id_field): item for item in getattr(new, field_name)}
            for previous in old_records:
                if new_by_id.get(getattr(previous, id_field)) != previous:
                    raise ValueError(f"annual governance update cannot remove or rewrite prior {field_name}")
        old_appointments = {item.appointment_id: item for item in old.appointments}
        new_appointments = {item.appointment_id: item for item in new.appointments}
        old_staff = {item.staff_id: item for item in old.staff}
        new_staff = {item.staff_id: item for item in new.staff}
        prior_decisions = {item.decision_id for item in old.decisions}
        decisions = [item for item in new.decisions if item.decision_id not in prior_decisions]
        for appointment_id, appointment in new_appointments.items():
            if appointment_id in old_appointments:
                continue
            if appointment.starts_on != boundary_on:
                raise ValueError("new staff appointment must start on the annual boundary")
            matching = [item for item in decisions if (
                item.action is AuthorityAction.APPOINT_STAFF
                and item.outcome is DecisionOutcome.EXECUTED
                and item.subject_id == appointment_id
                and item.decided_on == boundary_on
            )]
            if len(matching) != 1:
                raise ValueError("new appointment requires one same-club executed APPOINT_STAFF decision")
            mandate_decisions = [item for item in decisions if (
                item.action is AuthorityAction.GRANT_MANDATE
                and item.outcome is DecisionOutcome.EXECUTED
                and item.subject_id == appointment_id
                and item.decided_on == boundary_on
            )]
            if appointment.grants:
                if (len(mandate_decisions) != 1
                        or mandate_decisions[0].actor_appointment_id != matching[0].actor_appointment_id):
                    raise ValueError("appointment authority grants require one same-actor GRANT_MANDATE decision")
            elif mandate_decisions:
                raise ValueError("appointment without grants cannot carry a GRANT_MANDATE decision")
            added_appointments.append(GovernanceRecordRef(club_id, appointment_id))
            decision_refs.extend(
                GovernanceRecordRef(club_id, item.decision_id)
                for item in matching + mandate_decisions
            )
        for staff_id, profile in new_staff.items():
            if staff_id in old_staff:
                continue
            appointment = new_appointments.get(profile.appointment_id)
            if appointment is None or not appointment.active_on(boundary_on):
                raise ValueError("new staff registration must reference an active appointment")
            matching = [item for item in decisions if (
                item.action is AuthorityAction.REGISTER_STAFF
                and item.outcome is DecisionOutcome.EXECUTED
                and item.subject_id == staff_id
                and item.decided_on == boundary_on
            )]
            if len(matching) != 1:
                raise ValueError("new staff profile requires one same-club executed REGISTER_STAFF decision")
            added_staff.append(GovernanceRecordRef(club_id, staff_id))
            decision_refs.extend(
                GovernanceRecordRef(club_id, item.decision_id) for item in matching
            )
        for appointment in old.appointments:
            if (appointment.expires_on is not None
                    and state.as_of <= appointment.expires_on < boundary_on):
                expired_appointments.append(GovernanceRecordRef(club_id, appointment.appointment_id))

    active_managers = _manager_coverage(candidate, boundary_on)
    result_hash = _snapshot_sha256(state.world_id, boundary_on, candidate)
    values = dict(
        sequence=len(state.receipts) + 1,
        source_as_of=state.as_of,
        boundary_on=boundary_on,
        source_sha256=current_hash,
        request_sha256=request_hash,
        result_sha256=result_hash,
        added_appointment_ids=tuple(sorted(added_appointments)),
        added_staff_ids=tuple(sorted(added_staff)),
        expired_appointment_ids=tuple(sorted(expired_appointments)),
        active_managers=active_managers,
        governance_decision_ids=tuple(sorted(set(decision_refs))),
        clubs_snapshot=candidate,
    )
    receipt = StaffContinuityReceipt(
        **values,
        receipt_sha256=_sha256(dumps(_StaffReceiptMaterial(**values))),
    )
    return StaffContinuityState(
        state.world_id, state.genesis_as_of, state.genesis_clubs, boundary_on,
        candidate, state.receipts + (receipt,),
    )


__all__ = [
    "GovernanceRecordRef", "ManagerCoverage", "StaffContinuityReceipt",
    "StaffContinuityState", "advance_staff_continuity", "create_staff_continuity",
]
