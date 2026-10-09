"""Deterministic structural checks and explainable tactical conflict warnings."""

from __future__ import annotations

from itertools import combinations

from .models import (
    AnchorReference,
    IndividualInstruction,
    PhasePlan,
    TacticalAction,
    TacticDefinition,
    TacticIssue,
    TacticIssueSeverity,
)

_CONFLICTS = {
    frozenset((TacticalAction.HOLD_WIDTH, TacticalAction.MOVE_INSIDE)),
    frozenset((TacticalAction.OVERLAP, TacticalAction.UNDERLAP)),
    frozenset((TacticalAction.PRESS_RECEIVER, TacticalAction.RETREAT)),
    frozenset((TacticalAction.COVER_DEPTH, TacticalAction.RUN_BEHIND)),
}
_ANCHOR_REQUIRED = {
    TacticalAction.HOLD_WIDTH, TacticalAction.MOVE_INSIDE, TacticalAction.OVERLAP,
    TacticalAction.UNDERLAP, TacticalAction.OCCUPY_SPACE, TacticalAction.RUN_BEHIND,
    TacticalAction.COVER_DEPTH, TacticalAction.OFFER_OUTLET, TacticalAction.DELIVER_LONG,
}


def _conflicting(actions: tuple[TacticalAction, ...]) -> bool:
    return any(pair.issubset(actions) for pair in _CONFLICTS)


def _warning_for_instruction(instruction: IndividualInstruction, phase: str) -> list[TacticIssue]:
    issues: list[TacticIssue] = []
    if _conflicting(instruction.actions):
        issues.append(TacticIssue(
            TacticIssueSeverity.WARNING,
            "conflicting_actions",
            f"{phase}: {instruction.slot_id} has simultaneous incompatible duties",
            (instruction.slot_id,),
        ))
    if instruction.anchor is None and any(action in _ANCHOR_REQUIRED for action in instruction.actions):
        issues.append(TacticIssue(
            TacticIssueSeverity.WARNING,
            "unanchored_movement",
            f"{phase}: {instruction.slot_id} movement has no relative anchor",
            (instruction.slot_id,),
        ))
    if instruction.anchor is not None and instruction.anchor.reference in (AnchorReference.TEAMMATE, AnchorReference.OPPONENT):
        if instruction.anchor.reference_slot_id == instruction.slot_id:
            issues.append(TacticIssue(
                TacticIssueSeverity.ERROR,
                "self_relative_anchor",
                f"{phase}: {instruction.slot_id} cannot anchor to itself",
                (instruction.slot_id,),
            ))
    return issues


def _check_instruction(
    instruction: IndividualInstruction,
    known_slots: set[str],
    phase: str,
) -> list[TacticIssue]:
    issues = _warning_for_instruction(instruction, phase)
    if instruction.slot_id not in known_slots:
        issues.append(TacticIssue(
            TacticIssueSeverity.ERROR,
            "unknown_slot",
            f"{phase}: instruction refers to undeclared slot {instruction.slot_id}",
            (instruction.slot_id,),
        ))
    anchor = instruction.anchor
    if anchor is not None and anchor.reference_slot_id is not None:
        invalid_reference = (
            anchor.reference is AnchorReference.TEAMMATE and anchor.reference_slot_id not in known_slots
        ) or (
            anchor.reference is AnchorReference.OPPONENT and not anchor.reference_slot_id.startswith("opponent:")
        )
        if invalid_reference:
            issues.append(TacticIssue(
                TacticIssueSeverity.ERROR,
                "unknown_anchor_slot",
                f"{phase}: anchor refers to undeclared {anchor.reference.value} slot {anchor.reference_slot_id}",
                (instruction.slot_id, anchor.reference_slot_id),
            ))
    return issues


def _check_phase(phase: PhasePlan, known_slots: set[str]) -> list[TacticIssue]:
    label = phase.phase.value
    issues: list[TacticIssue] = []
    for instruction in phase.instructions:
        issues.extend(_check_instruction(instruction, known_slots, label))

    by_slot: dict[str, list[IndividualInstruction]] = {}
    for instruction in phase.instructions:
        by_slot.setdefault(instruction.slot_id, []).append(instruction)
    for slot_id, instructions in by_slot.items():
        for left, right in combinations(instructions, 2):
            if left.priority == right.priority and _conflicting(left.actions + right.actions):
                issues.append(TacticIssue(
                    TacticIssueSeverity.WARNING,
                    "same_priority_conflict",
                    f"{label}: {slot_id} receives incompatible duties at priority {left.priority}",
                    (slot_id,),
                ))

    for relation in phase.relationships:
        for slot_id in relation.participants:
            if slot_id not in known_slots:
                issues.append(TacticIssue(
                    TacticIssueSeverity.ERROR,
                    "unknown_relationship_slot",
                    f"{label}: relationship {relation.relationship_id} refers to undeclared slot {slot_id}",
                    (slot_id,),
                ))

    for assignment in phase.pressing:
        assigned = (assignment.first_presser_slot, *assignment.support_slots)
        for slot_id in assigned:
            if slot_id not in known_slots:
                issues.append(TacticIssue(
                    TacticIssueSeverity.ERROR,
                    "unknown_pressing_slot",
                    f"{label}: pressing assignment refers to undeclared slot {slot_id}",
                    (slot_id,),
                ))
        if not assignment.support_slots:
            issues.append(TacticIssue(
                TacticIssueSeverity.WARNING,
                "unsupported_press",
                f"{label}: first presser {assignment.first_presser_slot} has no supporting assignment",
                (assignment.first_presser_slot,),
            ))
        for instruction in assignment.fallback:
            issues.extend(_check_instruction(instruction, known_slots, f"{label} press fallback"))

    for assignment in phase.marking:
        if assignment.marker_slot not in known_slots:
            issues.append(TacticIssue(
                TacticIssueSeverity.ERROR,
                "unknown_marker_slot",
                f"{label}: marking assignment refers to undeclared marker {assignment.marker_slot}",
                (assignment.marker_slot,),
            ))
        if assignment.handover_to_slot is not None and assignment.handover_to_slot not in known_slots:
            issues.append(TacticIssue(
                TacticIssueSeverity.ERROR,
                "unknown_handover_slot",
                f"{label}: handover refers to undeclared slot {assignment.handover_to_slot}",
                (assignment.marker_slot, assignment.handover_to_slot),
            ))

    rule_ids = [rule.rule_id for rule in phase.conditional_rules]
    if len(rule_ids) != len(set(rule_ids)):
        issues.append(TacticIssue(
            TacticIssueSeverity.ERROR,
            "duplicate_rule_id",
            f"{label}: conditional rule IDs must be unique within a phase",
        ))
    for rule in phase.conditional_rules:
        for instruction in rule.instructions + rule.fallback:
            issues.extend(_check_instruction(instruction, known_slots, f"{label} rule {rule.rule_id}"))
    for left, right in combinations(phase.conditional_rules, 2):
        if left.trigger is not right.trigger or left.priority != right.priority:
            continue
        left_by_slot = {item.slot_id: set(item.actions) for item in left.instructions}
        right_by_slot = {item.slot_id: set(item.actions) for item in right.instructions}
        for slot_id in sorted(left_by_slot.keys() & right_by_slot.keys()):
            if any(pair.issubset(left_by_slot[slot_id] | right_by_slot[slot_id]) for pair in _CONFLICTS):
                issues.append(TacticIssue(
                    TacticIssueSeverity.WARNING,
                    "overlapping_rule_conflict",
                    f"{label}: rules {left.rule_id} and {right.rule_id} can conflict for {slot_id} at equal priority",
                    (slot_id,),
                ))

    routine_ids = [routine.routine_id for routine in phase.routines]
    if len(routine_ids) != len(set(routine_ids)):
        issues.append(TacticIssue(
            TacticIssueSeverity.ERROR,
            "duplicate_routine_id",
            f"{label}: routine IDs must be unique within a phase",
        ))
    for routine in phase.routines:
        sequences = [step.sequence for step in routine.steps]
        if sequences != list(range(len(sequences))):
            issues.append(TacticIssue(
                TacticIssueSeverity.ERROR,
                "routine_sequence_gap",
                f"{label}: routine {routine.routine_id} steps must be ordered from sequence zero",
            ))
        for instruction in routine.fallback:
            issues.extend(_check_instruction(instruction, known_slots, f"{label} routine {routine.routine_id} fallback"))
        for step in routine.steps:
            for instruction in step.instructions + step.fallback:
                issues.extend(_check_instruction(instruction, known_slots, f"{label} routine {routine.routine_id} step {step.sequence}"))
    return issues


def validate_tactic(tactic: TacticDefinition) -> tuple[TacticIssue, ...]:
    """Return errors for malformed references and warnings for legal but conflicting plans."""
    issues: list[TacticIssue] = []
    slot_ids = [slot.slot_id for slot in tactic.slots]
    if len(slot_ids) != len(set(slot_ids)):
        issues.append(TacticIssue(
            TacticIssueSeverity.ERROR,
            "duplicate_tactic_slot",
            "tactic slot IDs must be unique",
        ))
    phases = [phase.phase for phase in tactic.phases]
    if len(phases) != len(set(phases)):
        issues.append(TacticIssue(
            TacticIssueSeverity.ERROR,
            "duplicate_phase_plan",
            "a tactic can contain at most one plan per phase",
        ))
    known_slots = set(slot_ids)
    for phase in tactic.phases:
        issues.extend(_check_phase(phase, known_slots))
    return tuple(issues)
