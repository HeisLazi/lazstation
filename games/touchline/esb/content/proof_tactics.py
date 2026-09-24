"""Three authored tactical templates expressed only with shared P02 components.

These are intentions for later simulation packages; no action resolves here and
no template supplies an engine bonus or guarantees a match outcome.
"""

from __future__ import annotations

from games.touchline.esb.tactics.models import (
    AnchorReference,
    ConditionalRule,
    CoordinatedRelationship,
    IndividualInstruction,
    MarkTarget,
    MarkTargetKind,
    MarkingAssignment,
    MarkingBehavior,
    PhasePlan,
    PressingAngle,
    PressingAssignment,
    RelativeAnchor,
    RelationshipKind,
    RoutineStep,
    SlotRole,
    TacticalAction,
    TacticalPhase,
    TacticalRoutine,
    TacticDefinition,
    TacticSlot,
    Trigger,
    new_tactic_id,
)

SLOTS = (
    TacticSlot("GK", SlotRole.GOALKEEPER),
    TacticSlot("LCB", SlotRole.CENTER_BACK),
    TacticSlot("RCB", SlotRole.CENTER_BACK),
    TacticSlot("LB", SlotRole.FULLBACK),
    TacticSlot("RB", SlotRole.FULLBACK),
    TacticSlot("DM", SlotRole.DEFENSIVE_MIDFIELDER),
    TacticSlot("LCM", SlotRole.CENTRAL_MIDFIELDER),
    TacticSlot("RCM", SlotRole.CENTRAL_MIDFIELDER),
    TacticSlot("LW", SlotRole.WIDE_FORWARD),
    TacticSlot("RW", SlotRole.WIDE_FORWARD),
    TacticSlot("ST", SlotRole.STRIKER),
)


def _instruction(slot: str, action: TacticalAction, anchor: RelativeAnchor | None = None, priority: int = 0):
    return IndividualInstruction(slot, (action,), anchor, priority)


_POSSESSION_BUILD = PhasePlan(
    phase=TacticalPhase.BUILD_UP,
    instructions=(
        _instruction("LB", TacticalAction.MOVE_INSIDE, RelativeAnchor(AnchorReference.TEAM_SHAPE, 7.0, -4.0)),
        _instruction("LW", TacticalAction.HOLD_WIDTH, RelativeAnchor(AnchorReference.TEAM_SHAPE, 18.0, -17.0)),
        _instruction("DM", TacticalAction.COVER_DEPTH, RelativeAnchor(AnchorReference.TEAM_SHAPE, -3.0, 0.0)),
        _instruction("RW", TacticalAction.OFFER_OUTLET, RelativeAnchor(AnchorReference.SPACE, 22.0, 18.0)),
    ),
    relationships=(
        CoordinatedRelationship("left-underlap", RelationshipKind.UNDERLAP, ("LB", "LW"), 2),
        CoordinatedRelationship("left-cover", RelationshipKind.COVER, ("DM", "LCB", "RB"), 1),
        CoordinatedRelationship("weak-side-outlet", RelationshipKind.WEAK_SIDE_OUTLET, ("RW", "RB"), 1),
    ),
)

_POSSESSION_ATTACK = PhasePlan(
    phase=TacticalPhase.ESTABLISHED_ATTACK,
    instructions=(
        _instruction("LB", TacticalAction.MOVE_INSIDE, RelativeAnchor(AnchorReference.BALL, 4.0, -6.0), 2),
        _instruction("LW", TacticalAction.HOLD_WIDTH, RelativeAnchor(AnchorReference.TEAM_SHAPE, 24.0, -18.0), 1),
        _instruction("LCM", TacticalAction.OCCUPY_SPACE, RelativeAnchor(AnchorReference.SPACE, 7.0, -7.0)),
        _instruction("ST", TacticalAction.RUN_BEHIND, RelativeAnchor(AnchorReference.OPPONENT, 5.0, 0.0, "opponent:last_line")),
        _instruction("DM", TacticalAction.COVER_DEPTH, RelativeAnchor(AnchorReference.TEAM_SHAPE, -5.0, 0.0)),
        _instruction("RW", TacticalAction.OFFER_OUTLET, RelativeAnchor(AnchorReference.TEAM_SHAPE, 12.0, 18.0)),
    ),
    relationships=(
        CoordinatedRelationship("rotate-left", RelationshipKind.UNDERLAP, ("LB", "LW", "LCM"), 3),
        CoordinatedRelationship("balance-behind-ball", RelationshipKind.COVER, ("DM", "LCB", "RCB"), 2),
        CoordinatedRelationship("third-player-combination", RelationshipKind.THIRD_PLAYER_RUN, ("LCM", "LW", "ST"), 2),
    ),
    conditional_rules=(
        ConditionalRule(
            rule_id="recycle-if-switch-is-closed",
            trigger=Trigger.SUPPORT_CANNOT_ARRIVE,
            priority=4,
            expires_after_ticks=32,
            abort_if=Trigger.OPPONENT_ESCAPES_PRESS,
            instructions=(_instruction("RW", TacticalAction.RECYCLE_POSSESSION),),
            fallback=(_instruction("DM", TacticalAction.COVER_DEPTH, RelativeAnchor(AnchorReference.TEAM_SHAPE, -4.0, 0.0)),),
        ),
    ),
)

POSITIONAL_POSSESSION = TacticDefinition(
    tactic_id=new_tactic_id("p02-proof-tactics-v1", "positional-possession"),
    name="Width, inverted full-back and weak-side outlet",
    slots=SLOTS,
    phases=(_POSSESSION_BUILD, _POSSESSION_ATTACK),
)

_PRESS_PLAN = PhasePlan(
    phase=TacticalPhase.DEFENSIVE_BLOCK,
    instructions=(
        _instruction("LW", TacticalAction.PRESS_RECEIVER, RelativeAnchor(AnchorReference.BALL, 0.0, -2.0), 4),
        _instruction("ST", TacticalAction.BLOCK_RETURN, RelativeAnchor(AnchorReference.OPPONENT, 0.0, 1.0, "opponent:center_back_left"), 4),
        _instruction("DM", TacticalAction.CLOSE_PIVOT, RelativeAnchor(AnchorReference.OPPONENT, 0.0, 0.0, "opponent:pivot"), 3),
        _instruction("RCB", TacticalAction.COVER_DEPTH, RelativeAnchor(AnchorReference.TEAM_SHAPE, -8.0, 4.0), 2),
    ),
    relationships=(
        CoordinatedRelationship("left-press-support", RelationshipKind.PRESS_SUPPORT, ("LW", "ST", "LCM"), 4),
        CoordinatedRelationship("cover-against-rotation", RelationshipKind.TRACK_AND_HANDOVER, ("RCM", "DM", "RCB"), 3),
    ),
    pressing=(
        PressingAssignment(
            first_presser_slot="LW",
            support_slots=("ST", "LCM"),
            trigger=Trigger.POOR_TOUCH,
            angle=PressingAngle.INSIDE_OUT,
            commitment=.86,
            expires_after_ticks=28,
            abort_if=Trigger.OPPONENT_ESCAPES_PRESS,
            fallback=(_instruction("LW", TacticalAction.RETREAT, RelativeAnchor(AnchorReference.TEAM_SHAPE, -6.0, -8.0)),),
        ),
    ),
    marking=(
        MarkingAssignment(
            marker_slot="RCM",
            target=MarkTarget(MarkTargetKind.POSITIONAL_COUNTERPART, "opponent:deep_playmaker"),
            behavior=MarkingBehavior.HANDOVER_ON_ROTATION,
            maximum_distance_m=9.0,
            priority=3,
            handover_to_slot="DM",
        ),
    ),
    conditional_rules=(
        ConditionalRule(
            rule_id="press-backpass-as-a-unit",
            trigger=Trigger.BACKWARD_PASS,
            priority=5,
            expires_after_ticks=24,
            abort_if=Trigger.SUPPORT_CANNOT_ARRIVE,
            instructions=(
                _instruction("LW", TacticalAction.PRESS_RECEIVER, RelativeAnchor(AnchorReference.BALL, 0.0, -2.0), 5),
                _instruction("ST", TacticalAction.BLOCK_RETURN, RelativeAnchor(AnchorReference.OPPONENT, 0.0, 1.0, "opponent:center_back_left"), 5),
                _instruction("LCM", TacticalAction.CLOSE_PIVOT, RelativeAnchor(AnchorReference.OPPONENT, 0.0, -1.0, "opponent:pivot"), 4),
            ),
            fallback=(
                _instruction("LW", TacticalAction.RETREAT, RelativeAnchor(AnchorReference.TEAM_SHAPE, -6.0, -8.0)),
                _instruction("DM", TacticalAction.COVER_DEPTH, RelativeAnchor(AnchorReference.TEAM_SHAPE, -5.0, 0.0)),
            ),
        ),
    ),
)

MAN_ORIENTED_PRESS = TacticDefinition(
    tactic_id=new_tactic_id("p02-proof-tactics-v1", "man-oriented-press"),
    name="Man-oriented press with cover and handover",
    slots=SLOTS,
    phases=(_PRESS_PLAN,),
)

_KICKOFF_ROUTINE = TacticalRoutine(
    routine_id="kickoff-to-touchline-trap",
    start_trigger=Trigger.OWN_KICKOFF,
    priority=6,
    expires_after_ticks=240,
    abort_if=Trigger.QUICK_RESTART,
    fallback=(
        _instruction("LW", TacticalAction.RETREAT, RelativeAnchor(AnchorReference.TEAM_SHAPE, -8.0, -12.0)),
        _instruction("ST", TacticalAction.RETREAT, RelativeAnchor(AnchorReference.TEAM_SHAPE, -8.0, 0.0)),
    ),
    steps=(
        RoutineStep(
            sequence=0,
            complete_when=Trigger.BALL_TRAVELLING,
            timeout_ticks=48,
            instructions=(
                _instruction("GK", TacticalAction.DELIVER_LONG, RelativeAnchor(AnchorReference.SPACE, 44.0, -28.0), 6),
            ),
            fallback=(_instruction("GK", TacticalAction.RECYCLE_POSSESSION),),
        ),
        RoutineStep(
            sequence=1,
            complete_when=Trigger.OPPOSITION_THROW_IN,
            timeout_ticks=160,
            instructions=(
                _instruction("LW", TacticalAction.ADVANCE_WHILE_BALL_TRAVELS, RelativeAnchor(AnchorReference.TEAM_SHAPE, 14.0, -12.0), 5),
                _instruction("ST", TacticalAction.BLOCK_RETURN, RelativeAnchor(AnchorReference.TEAM_SHAPE, 12.0, 0.0), 4),
                _instruction("DM", TacticalAction.COVER_DEPTH, RelativeAnchor(AnchorReference.TEAM_SHAPE, 2.0, 0.0), 3),
            ),
            fallback=(
                _instruction("LW", TacticalAction.RETREAT, RelativeAnchor(AnchorReference.TEAM_SHAPE, -7.0, -10.0)),
            ),
        ),
        RoutineStep(
            sequence=2,
            complete_when=Trigger.BALL_WON,
            timeout_ticks=32,
            instructions=(
                _instruction("LW", TacticalAction.PRESS_RECEIVER, RelativeAnchor(AnchorReference.BALL, 0.0, -2.0), 6),
                _instruction("ST", TacticalAction.BLOCK_RETURN, RelativeAnchor(AnchorReference.OPPONENT, 0.0, 1.0, "opponent:throw_receiver"), 6),
                _instruction("LCM", TacticalAction.CLOSE_PIVOT, RelativeAnchor(AnchorReference.OPPONENT, 0.0, 0.0, "opponent:pivot"), 5),
                _instruction("RB", TacticalAction.COVER_DEPTH, RelativeAnchor(AnchorReference.TEAM_SHAPE, -5.0, 10.0), 4),
            ),
            fallback=(
                _instruction("LW", TacticalAction.RETREAT, RelativeAnchor(AnchorReference.TEAM_SHAPE, -6.0, -8.0)),
                _instruction("DM", TacticalAction.COVER_DEPTH, RelativeAnchor(AnchorReference.TEAM_SHAPE, -5.0, 0.0)),
            ),
        ),
    ),
)

_KICKOFF_PLAN = PhasePlan(
    phase=TacticalPhase.KICKOFF_RESTART,
    routines=(_KICKOFF_ROUTINE,),
    pressing=(
        PressingAssignment(
            first_presser_slot="LW",
            support_slots=("ST", "LCM"),
            trigger=Trigger.OPPOSITION_THROW_IN,
            angle=PressingAngle.DENY_CENTRAL_RETURN,
            commitment=.78,
            expires_after_ticks=32,
            abort_if=Trigger.OPPONENT_ESCAPES_PRESS,
            fallback=(
                _instruction("LW", TacticalAction.RETREAT, RelativeAnchor(AnchorReference.TEAM_SHAPE, -6.0, -8.0)),
            ),
        ),
    ),
    marking=(
        MarkingAssignment(
            marker_slot="RB",
            target=MarkTarget(MarkTargetKind.AREA_ENTRANT, "deep_touchline_runner"),
            behavior=MarkingBehavior.HANDOVER_ON_ROTATION,
            maximum_distance_m=5.0,
            priority=4,
            handover_to_slot="RCB",
        ),
    ),
    conditional_rules=(
        ConditionalRule(
            rule_id="opposition-throw-in-trap",
            trigger=Trigger.OPPOSITION_THROW_IN,
            priority=7,
            expires_after_ticks=32,
            abort_if=Trigger.OPPONENT_ESCAPES_PRESS,
            instructions=(
                _instruction("LW", TacticalAction.PRESS_RECEIVER, RelativeAnchor(AnchorReference.BALL, 0.0, -2.0), 7),
                _instruction("ST", TacticalAction.BLOCK_RETURN, RelativeAnchor(AnchorReference.OPPONENT, 0.0, 1.0, "opponent:throw_receiver"), 7),
                _instruction("LCM", TacticalAction.CLOSE_PIVOT, RelativeAnchor(AnchorReference.OPPONENT, 0.0, 0.0, "opponent:pivot"), 6),
            ),
            fallback=(
                _instruction("LW", TacticalAction.RETREAT, RelativeAnchor(AnchorReference.TEAM_SHAPE, -6.0, -8.0)),
                _instruction("DM", TacticalAction.COVER_DEPTH, RelativeAnchor(AnchorReference.TEAM_SHAPE, -5.0, 0.0)),
            ),
        ),
    ),
)

KICKOFF_TOUCHLINE_TRAP = TacticDefinition(
    tactic_id=new_tactic_id("p02-proof-tactics-v1", "kickoff-touchline-trap"),
    name="Long kickoff into a recoverable touchline trap",
    slots=SLOTS,
    phases=(_KICKOFF_PLAN,),
)

PROOF_TACTICS = (POSITIONAL_POSSESSION, MAN_ORIENTED_PRESS, KICKOFF_TOUCHLINE_TRAP)
