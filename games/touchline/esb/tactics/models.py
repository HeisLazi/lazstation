"""Editable tactical intentions, references, conditions and restart routines."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import NewType

from games.touchline.esb.ids import derive_id, validate_id

TacticId = NewType("TacticId", str)


def new_tactic_id(namespace: str, *parts: str | int) -> TacticId:
    return TacticId(derive_id("tactic", namespace, *parts))


class TacticalPhase(str, Enum):
    BUILD_UP = "build_up"
    PROGRESSION = "progression"
    ESTABLISHED_ATTACK = "established_attack"
    DEFENSIVE_BLOCK = "defensive_block"
    ATTACKING_TRANSITION = "attacking_transition"
    DEFENSIVE_TRANSITION = "defensive_transition"
    KICKOFF_RESTART = "kickoff_restart"
    THROW_IN_RESTART = "throw_in_restart"


class SlotRole(str, Enum):
    GOALKEEPER = "goalkeeper"
    CENTER_BACK = "center_back"
    FULLBACK = "fullback"
    DEFENSIVE_MIDFIELDER = "defensive_midfielder"
    CENTRAL_MIDFIELDER = "central_midfielder"
    WIDE_FORWARD = "wide_forward"
    STRIKER = "striker"


class AnchorReference(str, Enum):
    TEAM_SHAPE = "team_shape"
    BALL = "ball"
    TEAMMATE = "teammate"
    OPPONENT = "opponent"
    SPACE = "space"


class TacticalAction(str, Enum):
    HOLD_WIDTH = "hold_width"
    MOVE_INSIDE = "move_inside"
    OVERLAP = "overlap"
    UNDERLAP = "underlap"
    SUPPORT = "support"
    OCCUPY_SPACE = "occupy_space"
    DROP_SHORT = "drop_short"
    RUN_BEHIND = "run_behind"
    COVER_DEPTH = "cover_depth"
    PRESS_RECEIVER = "press_receiver"
    BLOCK_RETURN = "block_return"
    CLOSE_PIVOT = "close_pivot"
    TRACK_OPPONENT = "track_opponent"
    HANDOVER_MARK = "handover_mark"
    RETREAT = "retreat"
    OFFER_OUTLET = "offer_outlet"
    DELIVER_LONG = "deliver_long"
    ADVANCE_WHILE_BALL_TRAVELS = "advance_while_ball_travels"
    SET_THROW_IN_TRAP = "set_throw_in_trap"
    ATTACK_NEAR_POST = "attack_near_post"
    ATTACK_CENTRAL = "attack_central"
    ATTACK_FAR_POST = "attack_far_post"
    RECYCLE_POSSESSION = "recycle_possession"


class RelationshipKind(str, Enum):
    OVERLAP = "overlap"
    UNDERLAP = "underlap"
    THIRD_PLAYER_RUN = "third_player_run"
    COVER = "cover"
    EXCHANGE_POSITIONS = "exchange_positions"
    WEAK_SIDE_OUTLET = "weak_side_outlet"
    PRESS_SUPPORT = "press_support"
    TRACK_AND_HANDOVER = "track_and_handover"


class Trigger(str, Enum):
    OWN_KICKOFF = "own_kickoff"
    OPPOSITION_THROW_IN = "opposition_throw_in"
    POOR_TOUCH = "poor_touch"
    BACKWARD_PASS = "backward_pass"
    SLOW_LATERAL_PASS = "slow_lateral_pass"
    RECEIVER_FACING_OWN_GOAL = "receiver_facing_own_goal"
    ISOLATED_RECEIVER = "isolated_receiver"
    BALL_TRAVELLING = "ball_travelling"
    BALL_WON = "ball_won"
    OPPONENT_ESCAPES_PRESS = "opponent_escapes_press"
    QUICK_RESTART = "quick_restart"
    SUPPORT_CANNOT_ARRIVE = "support_cannot_arrive"
    ROUTINE_TIMEOUT = "routine_timeout"


class PressingAngle(str, Enum):
    INSIDE_OUT = "inside_out"
    OUTSIDE_IN = "outside_in"
    DENY_CENTRAL_RETURN = "deny_central_return"


class MarkTargetKind(str, Enum):
    NAMED_OPPONENT = "named_opponent"
    POSITIONAL_COUNTERPART = "positional_counterpart"
    AREA_ENTRANT = "area_entrant"


class MarkingBehavior(str, Enum):
    TRACK_WITHIN_LIMIT = "track_within_limit"
    HOLD_AREA = "hold_area"
    HANDOVER_ON_ROTATION = "handover_on_rotation"


class TacticIssueSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class TacticSlot:
    slot_id: str
    role: SlotRole

    def __post_init__(self) -> None:
        validate_id(self.slot_id, kind="tactic slot ID")
        if not isinstance(self.role, SlotRole):
            raise TypeError("tactic slot requires a supported role")


@dataclass(frozen=True)
class RelativeAnchor:
    """Offsets are metres; longitudinal is positive toward the opponent goal."""

    reference: AnchorReference
    longitudinal_offset_m: float = 0.0
    lateral_offset_m: float = 0.0
    reference_slot_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.reference, AnchorReference):
            raise TypeError("anchor requires a defined reference frame")
        if type(self.longitudinal_offset_m) not in (int, float) or not math.isfinite(self.longitudinal_offset_m):
            raise ValueError("anchor longitudinal offset must be finite metres")
        if type(self.lateral_offset_m) not in (int, float) or not math.isfinite(self.lateral_offset_m):
            raise ValueError("anchor lateral offset must be finite metres")
        if self.reference in (AnchorReference.TEAMMATE, AnchorReference.OPPONENT):
            if self.reference_slot_id is None:
                raise ValueError("player-relative anchor requires a reference slot")
            validate_id(self.reference_slot_id, kind="anchor reference slot ID")
        elif self.reference_slot_id is not None:
            raise ValueError("only player-relative anchors accept a reference slot")


@dataclass(frozen=True)
class IndividualInstruction:
    slot_id: str
    actions: tuple[TacticalAction, ...]
    anchor: RelativeAnchor | None = None
    priority: int = 0

    def __post_init__(self) -> None:
        validate_id(self.slot_id, kind="instruction slot ID")
        if not isinstance(self.actions, tuple) or not self.actions:
            raise ValueError("instruction requires an immutable, non-empty action tuple")
        if any(not isinstance(action, TacticalAction) for action in self.actions):
            raise TypeError("instruction actions must use supported tactical components")
        if self.anchor is not None and not isinstance(self.anchor, RelativeAnchor):
            raise TypeError("instruction anchor must use RelativeAnchor")
        if len(self.actions) != len(set(self.actions)):
            raise ValueError("instruction cannot repeat the same action")
        if type(self.priority) is not int or self.priority < 0:
            raise ValueError("instruction priority must be a non-negative integer")


@dataclass(frozen=True)
class CoordinatedRelationship:
    relationship_id: str
    kind: RelationshipKind
    participants: tuple[str, ...]
    priority: int = 0

    def __post_init__(self) -> None:
        validate_id(self.relationship_id, kind="relationship ID")
        if not isinstance(self.kind, RelationshipKind):
            raise TypeError("relationship requires a supported relationship kind")
        if not isinstance(self.participants, tuple) or len(self.participants) < 2:
            raise ValueError("coordinated relationship requires at least two participants")
        if len(self.participants) != len(set(self.participants)):
            raise ValueError("relationship participants must be unique")
        for participant in self.participants:
            validate_id(participant, kind="relationship participant slot")
        if type(self.priority) is not int or self.priority < 0:
            raise ValueError("relationship priority must be non-negative")


@dataclass(frozen=True)
class PressingAssignment:
    first_presser_slot: str
    support_slots: tuple[str, ...]
    trigger: Trigger
    angle: PressingAngle
    commitment: float
    expires_after_ticks: int
    abort_if: Trigger
    fallback: tuple[IndividualInstruction, ...]

    def __post_init__(self) -> None:
        validate_id(self.first_presser_slot, kind="first presser slot")
        if not isinstance(self.trigger, Trigger) or not isinstance(self.abort_if, Trigger):
            raise TypeError("pressing trigger and abort condition must be observable trigger values")
        if not isinstance(self.angle, PressingAngle):
            raise TypeError("pressing angle must use a supported value")
        if not isinstance(self.support_slots, tuple):
            raise TypeError("press support slots must be an immutable tuple")
        for slot_id in self.support_slots:
            validate_id(slot_id, kind="press support slot")
        if len(self.support_slots) != len(set(self.support_slots)) or self.first_presser_slot in self.support_slots:
            raise ValueError("pressing roles must be unique")
        if type(self.commitment) not in (int, float) or not 0.0 <= self.commitment <= 1.0:
            raise ValueError("press commitment must be normalized to [0, 1]")
        if type(self.expires_after_ticks) is not int or self.expires_after_ticks <= 0:
            raise ValueError("press assignment expiry must be positive match ticks")
        if not isinstance(self.fallback, tuple) or not self.fallback:
            raise ValueError("pressing assignment requires a fallback")
        if any(not isinstance(item, IndividualInstruction) for item in self.fallback):
            raise TypeError("press fallback must contain individual instructions")


@dataclass(frozen=True)
class MarkTarget:
    kind: MarkTargetKind
    reference: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, MarkTargetKind):
            raise TypeError("mark target kind must be explicit")
        if self.kind is MarkTargetKind.NAMED_OPPONENT:
            if self.reference is None:
                raise ValueError("named-opponent marking requires an opponent reference")
            validate_id(self.reference, kind="opponent reference")
        elif self.kind is MarkTargetKind.POSITIONAL_COUNTERPART:
            if self.reference is None or not self.reference.startswith("opponent:"):
                raise ValueError("positional counterpart requires an opponent-role reference")
        elif self.reference is None:
            raise ValueError("area-entrant marking requires a named area reference")
        elif self.reference is not None:
            validate_id(self.reference, kind="marking target reference")


@dataclass(frozen=True)
class MarkingAssignment:
    marker_slot: str
    target: MarkTarget
    behavior: MarkingBehavior
    maximum_distance_m: float
    priority: int = 0
    handover_to_slot: str | None = None

    def __post_init__(self) -> None:
        validate_id(self.marker_slot, kind="marker slot")
        if not isinstance(self.target, MarkTarget) or not isinstance(self.behavior, MarkingBehavior):
            raise TypeError("marking assignment requires a target and supported behavior")
        if type(self.maximum_distance_m) not in (int, float) or not math.isfinite(self.maximum_distance_m) or self.maximum_distance_m <= 0:
            raise ValueError("marking limit must be positive metres")
        if type(self.priority) is not int or self.priority < 0:
            raise ValueError("marking priority must be non-negative")
        if self.behavior is MarkingBehavior.HANDOVER_ON_ROTATION:
            if self.handover_to_slot is None:
                raise ValueError("handover marking requires a receiving slot")
            validate_id(self.handover_to_slot, kind="handover slot")
            if self.handover_to_slot == self.marker_slot:
                raise ValueError("marking handover must name another slot")
        elif self.handover_to_slot is not None:
            validate_id(self.handover_to_slot, kind="handover slot")


@dataclass(frozen=True)
class ConditionalRule:
    rule_id: str
    trigger: Trigger
    priority: int
    expires_after_ticks: int
    abort_if: Trigger
    instructions: tuple[IndividualInstruction, ...]
    fallback: tuple[IndividualInstruction, ...]

    def __post_init__(self) -> None:
        validate_id(self.rule_id, kind="conditional rule ID")
        if not isinstance(self.trigger, Trigger) or not isinstance(self.abort_if, Trigger):
            raise TypeError("conditional rule needs observable trigger and abort conditions")
        if type(self.priority) is not int or self.priority < 0:
            raise ValueError("rule priority must be non-negative")
        if type(self.expires_after_ticks) is not int or self.expires_after_ticks <= 0:
            raise ValueError("rule expiry must be positive match ticks")
        if not isinstance(self.instructions, tuple) or not self.instructions:
            raise ValueError("conditional rule requires instructions")
        if not isinstance(self.fallback, tuple) or not self.fallback:
            raise ValueError("conditional rule requires explicit fallback instructions")
        if any(not isinstance(item, IndividualInstruction) for item in self.instructions + self.fallback):
            raise TypeError("conditional rules must contain individual instructions")


@dataclass(frozen=True)
class RoutineStep:
    sequence: int
    complete_when: Trigger
    timeout_ticks: int
    instructions: tuple[IndividualInstruction, ...]
    fallback: tuple[IndividualInstruction, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.complete_when, Trigger):
            raise TypeError("routine completion must use an observable trigger")
        if type(self.sequence) is not int or self.sequence < 0:
            raise ValueError("routine step sequence must be a non-negative integer")
        if type(self.timeout_ticks) is not int or self.timeout_ticks <= 0:
            raise ValueError("routine step timeout must be positive match ticks")
        if not isinstance(self.instructions, tuple) or not self.instructions:
            raise ValueError("routine step requires instructions")
        if not isinstance(self.fallback, tuple) or not self.fallback:
            raise ValueError("routine step requires fallback instructions")
        if any(not isinstance(item, IndividualInstruction) for item in self.instructions + self.fallback):
            raise TypeError("routine steps must contain individual instructions")


@dataclass(frozen=True)
class TacticalRoutine:
    routine_id: str
    start_trigger: Trigger
    priority: int
    expires_after_ticks: int
    abort_if: Trigger
    fallback: tuple[IndividualInstruction, ...]
    steps: tuple[RoutineStep, ...]

    def __post_init__(self) -> None:
        validate_id(self.routine_id, kind="tactical routine ID")
        if not isinstance(self.start_trigger, Trigger) or not isinstance(self.abort_if, Trigger):
            raise TypeError("routine needs observable start and abort conditions")
        if type(self.priority) is not int or self.priority < 0:
            raise ValueError("routine priority must be non-negative")
        if type(self.expires_after_ticks) is not int or self.expires_after_ticks <= 0:
            raise ValueError("routine expiry must be positive match ticks")
        if not isinstance(self.fallback, tuple) or not self.fallback:
            raise ValueError("routine requires explicit fallback instructions")
        if not isinstance(self.steps, tuple) or not self.steps:
            raise ValueError("routine requires at least one step")
        if any(not isinstance(item, RoutineStep) for item in self.steps):
            raise TypeError("tactical routine steps must use RoutineStep records")
        if any(not isinstance(item, IndividualInstruction) for item in self.fallback):
            raise TypeError("routine fallback must contain individual instructions")


@dataclass(frozen=True)
class PhasePlan:
    phase: TacticalPhase
    instructions: tuple[IndividualInstruction, ...] = ()
    relationships: tuple[CoordinatedRelationship, ...] = ()
    pressing: tuple[PressingAssignment, ...] = ()
    marking: tuple[MarkingAssignment, ...] = ()
    conditional_rules: tuple[ConditionalRule, ...] = ()
    routines: tuple[TacticalRoutine, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.phase, TacticalPhase):
            raise TypeError("phase plan must use a supported tactical phase")
        for name in ("instructions", "relationships", "pressing", "marking", "conditional_rules", "routines"):
            if not isinstance(getattr(self, name), tuple):
                raise TypeError(f"phase plan {name} must be an immutable tuple")
        expected = {
            "instructions": IndividualInstruction,
            "relationships": CoordinatedRelationship,
            "pressing": PressingAssignment,
            "marking": MarkingAssignment,
            "conditional_rules": ConditionalRule,
            "routines": TacticalRoutine,
        }
        for name, item_type in expected.items():
            if any(not isinstance(item, item_type) for item in getattr(self, name)):
                raise TypeError(f"phase plan {name} contains an unsupported record")


@dataclass(frozen=True)
class TacticDefinition:
    tactic_id: TacticId
    name: str
    slots: tuple[TacticSlot, ...]
    phases: tuple[PhasePlan, ...]
    version: int = 1

    def __post_init__(self) -> None:
        validate_id(self.tactic_id, kind="tactic ID")
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("tactic name must be non-empty")
        if not isinstance(self.slots, tuple) or not self.slots:
            raise ValueError("tactic requires immutable role slots")
        if not isinstance(self.phases, tuple) or not self.phases:
            raise ValueError("tactic requires immutable phase plans")
        if any(not isinstance(slot, TacticSlot) for slot in self.slots):
            raise TypeError("tactic slots must use TacticSlot records")
        if any(not isinstance(phase, PhasePlan) for phase in self.phases):
            raise TypeError("tactic phases must use PhasePlan records")
        if type(self.version) is not int or self.version < 1:
            raise ValueError("tactic version must be positive")


@dataclass(frozen=True)
class TacticIssue:
    severity: TacticIssueSeverity
    code: str
    message: str
    slot_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.severity, TacticIssueSeverity):
            raise TypeError("tactic issue severity must be explicit")
        if not self.code.strip() or not self.message.strip():
            raise ValueError("tactic validation issue requires a code and message")
