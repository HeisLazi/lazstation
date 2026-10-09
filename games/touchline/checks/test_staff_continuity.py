"""Mechanism tests for P16d-c annual staff and manager history."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
import hashlib
import subprocess
import sys
import unittest

from games.touchline.checks.world_career_probe import (
    CLUBS,
    MANAGERS,
    INITIAL_ON,
    WORLD_ID,
    _governance,
    _move_managers,
    initial_staff_state,
)
from games.touchline.esb.club.governance import (
    Appointment,
    AuthorityAction,
    AuthorityGrant,
    AuthorityPolicy,
    AuthoritySource,
    BudgetBook,
    ClubGovernance,
    ClubRole,
    DecisionLogEntry,
    DecisionOutcome,
    add_staff_appointment,
)
from games.touchline.esb.serialization import dumps
from games.touchline.esb.time import WorldDate
from games.touchline.esb.world.staff_continuity import (
    StaffContinuityState,
    _StaffReceiptMaterial,
    _snapshot_sha256,
    advance_staff_continuity,
    create_staff_continuity,
)


BOUNDARY = WorldDate(date(2027, 10, 1))


class StaffContinuityTests(unittest.TestCase):
    def test_authorized_manager_move_preserves_terms_and_dated_decisions(self):
        source = initial_staff_state()
        updated = _move_managers(source, BOUNDARY, 1)
        receipt = updated.receipts[-1]
        self.assertEqual(receipt.sequence, 1)
        self.assertEqual(len(receipt.source_sha256), 64)
        self.assertEqual(len(receipt.added_appointment_ids), 2)
        self.assertEqual(len(receipt.added_staff_ids), 2)
        self.assertEqual(len(receipt.expired_appointment_ids), 2)
        self.assertEqual(len(receipt.governance_decision_ids), 4)
        self.assertEqual(
            {(item.club_id, item.person_id) for item in receipt.active_managers},
            {(CLUBS[0], MANAGERS[1]), (CLUBS[1], MANAGERS[0])},
        )
        for club_id in CLUBS:
            before = next(item for item in source.clubs if item.club_id == club_id)
            after = next(item for item in updated.clubs if item.club_id == club_id)
            self.assertTrue(set(before.appointments).issubset(after.appointments))
            self.assertTrue(set(before.staff).issubset(after.staff))
            self.assertTrue(set(before.decisions).issubset(after.decisions))
        self.assertEqual(StaffContinuityState.from_json(updated.to_json()), updated)

    def test_same_date_retry_is_identity_preserving_and_conflict_rejects(self):
        updated = _move_managers(initial_staff_state(), BOUNDARY, 1)
        self.assertIs(advance_staff_continuity(updated, BOUNDARY, updated.clubs), updated)
        changed = list(updated.clubs)
        changed[0] = replace(
            changed[0], budget=replace(changed[0].budget, cash_on_hand_minor=999_999),
        )
        with self.assertRaisesRegex(ValueError, "same-date.*conflicts"):
            advance_staff_continuity(updated, BOUNDARY, tuple(changed))

    def test_resealed_receipt_cannot_forge_manager_coverage_or_genesis_date(self):
        updated = _move_managers(initial_staff_state(), BOUNDARY, 1)
        receipt = updated.receipts[-1]
        forged_material = _StaffReceiptMaterial(
            receipt.sequence,
            receipt.source_as_of,
            receipt.boundary_on,
            receipt.source_sha256,
            receipt.request_sha256,
            receipt.result_sha256,
            receipt.added_appointment_ids,
            receipt.added_staff_ids,
            receipt.expired_appointment_ids,
            (),
            receipt.governance_decision_ids,
            receipt.clubs_snapshot,
        )
        forged = replace(
            receipt,
            active_managers=(),
            receipt_sha256=hashlib.sha256(dumps(forged_material).encode("utf-8")).hexdigest(),
        )
        with self.assertRaisesRegex(ValueError, "active manager coverage"):
            replace(updated, receipts=(forged,))
        with self.assertRaisesRegex(ValueError, "annual genesis/boundary"):
            replace(updated, genesis_as_of=WorldDate(date(2026, 10, 2)))

    def test_resealed_historical_appointment_term_cannot_rewrite_boundary_snapshot(self):
        first = _move_managers(initial_staff_state(), BOUNDARY, 1)
        second = _move_managers(first, WorldDate(date(2028, 10, 1)), 2)
        ref = first.receipts[0].added_appointment_ids[0]
        changed_clubs = []
        for club in second.clubs:
            if str(club.club_id) != ref.club_id:
                changed_clubs.append(club)
                continue
            changed_appointments = tuple(
                replace(item, expires_on=WorldDate(date(2028, 8, 31)))
                if item.appointment_id == ref.record_id else item
                for item in club.appointments
            )
            changed_clubs.append(replace(club, appointments=changed_appointments))
        changed_clubs_tuple = tuple(changed_clubs)
        final_hash = _snapshot_sha256(WORLD_ID, second.as_of, changed_clubs_tuple)
        last = second.receipts[-1]
        forged_material = _StaffReceiptMaterial(
            last.sequence,
            last.source_as_of,
            last.boundary_on,
            last.source_sha256,
            final_hash,
            final_hash,
            last.added_appointment_ids,
            last.added_staff_ids,
            last.expired_appointment_ids,
            last.active_managers,
            last.governance_decision_ids,
            last.clubs_snapshot,
        )
        forged_last = replace(
            last,
            request_sha256=final_hash,
            result_sha256=final_hash,
            receipt_sha256=hashlib.sha256(dumps(forged_material).encode("utf-8")).hexdigest(),
        )
        with self.assertRaisesRegex(ValueError, "snapshot differs"):
            replace(
                second,
                clubs=changed_clubs_tuple,
                receipts=(second.receipts[0], forged_last),
            )

    def test_granted_appointment_requires_one_actor_to_hold_both_decisions(self):
        coast = _governance(CLUBS[0])
        owner = next(item for item in coast.appointments if item.role is ClubRole.OWNER)
        appointment_actor = replace(
            owner,
            grants=(AuthorityGrant(AuthorityAction.APPOINT_STAFF),),
        )
        mandate_actor = Appointment(
            "appointment:board-coast", CLUBS[0], "person:board-coast", ClubRole.BOARD,
            WorldDate(date(2020, 1, 1)), None,
            (AuthorityGrant(AuthorityAction.GRANT_MANDATE),),
        )
        coast = replace(
            coast,
            appointments=(appointment_actor, mandate_actor),
        )
        source = create_staff_continuity(
            WORLD_ID, INITIAL_ON, (coast, _governance(CLUBS[1])),
        )
        granted = Appointment(
            "appointment:split-authority", CLUBS[0], "person:split-authority",
            ClubRole.MANAGER, BOUNDARY, WorldDate(date(2028, 9, 30)),
            (AuthorityGrant(AuthorityAction.CREATE_TASK),),
        )
        rejected = add_staff_appointment(
            coast, appointment_actor.appointment_id, granted, BOUNDARY,
        )
        self.assertFalse(rejected.accepted)
        self.assertIs(rejected.state, coast)

        appointment_decision = DecisionLogEntry(
            "decision:split-appointment", granted.appointment_id, None,
            AuthorityAction.APPOINT_STAFF, appointment_actor.appointment_id,
            appointment_actor.role, AuthoritySource.APPOINTMENT,
            appointment_actor.appointment_id, BOUNDARY, DecisionOutcome.EXECUTED,
            "test split authorization",
        )
        mandate_decision = DecisionLogEntry(
            "decision:split-mandate", granted.appointment_id, None,
            AuthorityAction.GRANT_MANDATE, mandate_actor.appointment_id,
            mandate_actor.role, AuthoritySource.APPOINTMENT,
            mandate_actor.appointment_id, BOUNDARY, DecisionOutcome.EXECUTED,
            "test split authorization",
        )
        candidate_club = replace(
            coast,
            appointments=coast.appointments + (granted,),
            decisions=coast.decisions + (appointment_decision, mandate_decision),
        )
        with self.assertRaisesRegex(ValueError, "same-actor"):
            advance_staff_continuity(
                source, BOUNDARY,
                (candidate_club, next(item for item in source.clubs if item.club_id == CLUBS[1])),
            )

    def test_new_appointment_without_governance_decision_is_rejected(self):
        source = initial_staff_state()
        forged = Appointment(
            "appointment:forged-manager", CLUBS[0], "person:forged-manager",
            ClubRole.MANAGER, BOUNDARY, WorldDate(date(2028, 9, 30)), (),
        )
        clubs = list(source.clubs)
        club_index = next(i for i, item in enumerate(clubs) if item.club_id == CLUBS[0])
        clubs[club_index] = replace(
            clubs[club_index], appointments=clubs[club_index].appointments + (forged,),
        )
        with self.assertRaisesRegex(ValueError, "APPOINT_STAFF decision"):
            advance_staff_continuity(source, BOUNDARY, tuple(clubs))

    def test_policy_reserved_appointment_cannot_be_forged_as_executed(self):
        base = initial_staff_state()
        coast = base.clubs[0]
        head_coach = Appointment(
            "appointment:policy-head-coach", CLUBS[0], "person:policy-head-coach",
            ClubRole.HEAD_COACH, WorldDate(date(2020, 1, 1)), None,
            (AuthorityGrant(AuthorityAction.APPOINT_STAFF),),
        )
        coast = replace(
            coast,
            policy=AuthorityPolicy(
                CLUBS[0], board_reserved_actions=(AuthorityAction.APPOINT_STAFF,),
            ),
            appointments=coast.appointments + (head_coach,),
        )
        source = create_staff_continuity(WORLD_ID, INITIAL_ON, (coast, base.clubs[1]))
        forged_appointment = Appointment(
            "appointment:policy-forged", CLUBS[0], "person:policy-forged",
            ClubRole.MANAGER, BOUNDARY, WorldDate(date(2028, 9, 30)), (),
        )
        forged_decision = DecisionLogEntry(
            "decision:policy-forged", forged_appointment.appointment_id, None,
            AuthorityAction.APPOINT_STAFF, head_coach.appointment_id,
            ClubRole.HEAD_COACH, AuthoritySource.APPOINTMENT,
            head_coach.appointment_id, BOUNDARY, DecisionOutcome.EXECUTED,
            "forged policy-reserved appointment",
        )
        candidate = replace(
            coast,
            appointments=coast.appointments + (forged_appointment,),
            decisions=coast.decisions + (forged_decision,),
        )
        self.assertFalse(add_staff_appointment(
            coast, head_coach.appointment_id, forged_appointment, BOUNDARY,
        ).accepted)
        with self.assertRaisesRegex(ValueError, "fails current governance authority"):
            advance_staff_continuity(source, BOUNDARY, (candidate, source.clubs[1]))

    def test_manager_cannot_overlap_between_clubs(self):
        source = initial_staff_state()
        valley_id = "club:valley"
        valley = _governance(valley_id)
        manager = next(
            item for item in source.clubs[0].appointments
            if item.role is ClubRole.MANAGER
        )
        manager = Appointment(
            "appointment:duplicate-manager", valley_id, manager.person_id, ClubRole.MANAGER,
            manager.starts_on, manager.expires_on, (),
        )
        valley = replace(valley, appointments=valley.appointments + (manager,))
        with self.assertRaisesRegex(ValueError, "overlapping cross-club"):
            create_staff_continuity(
                WORLD_ID, WorldDate(date(2026, 10, 1)), source.clubs + (valley,),
            )

    def test_fresh_process_import_does_not_open_files_or_sqlite(self):
        script = """
import builtins, sqlite3
def blocked(*args, **kwargs):
    raise AssertionError('import performed file or sqlite I/O')
builtins.open = blocked
sqlite3.connect = blocked
import games.touchline.esb.world.staff_continuity
import games.touchline.esb.world.archive_series
print('headless-import-ok')
"""
        result = subprocess.run(
            [sys.executable, "-c", script], check=True, capture_output=True, text=True,
        )
        self.assertEqual(result.stdout.strip(), "headless-import-ok")


if __name__ == "__main__":
    unittest.main()
