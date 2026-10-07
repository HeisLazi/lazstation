"""Tactical intent resolution over the spatial match state (P06).

Tactics produce movement targets and named state transitions. Player movement
still goes through P03 kinematics; tactical instructions never add outcome
probability or skill bonuses.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Iterable, Mapping

from games.touchline.esb.ids import PlayerId
from games.touchline.esb.match.possession import OpenPlayState, PlayerState
from games.touchline.esb.match.spatial import MovementIntent, PlayerMotion, advance_player
from games.touchline.esb.model import Position2D
from games.touchline.esb.tactics import (
    AnchorReference, ConditionalRule, CoordinatedRelationship, IndividualInstruction,
    MarkingAssignment, MarkingBehavior, PhasePlan, PressingAssignment,
    RelationshipKind, TacticalAction, TacticalPhase, TacticalRoutine, TacticDefinition,
    Trigger, validate_tactic,
)


@dataclass(frozen=True)
class TacticalTraceEvent:
    code: str
    tick: int
    detail: str
    slot_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class TacticalMovement:
    slot_id: str
    player_id: PlayerId
    action: TacticalAction
    source: str
    priority: int
    start: Position2D
    target: Position2D
    result: PlayerMotion
    rationale: str


@dataclass(frozen=True)
class TacticalFrame:
    team_id: str
    tactic_id: str
    tick: int
    phase: TacticalPhase
    triggers: tuple[Trigger, ...]
    movements: tuple[TacticalMovement, ...]
    events: tuple[TacticalTraceEvent, ...]
    restart_taker_id: PlayerId | None = None
    restart_target: Position2D | None = None


@dataclass(frozen=True)
class _Order:
    slot_id: str
    action: TacticalAction
    target: Position2D | None
    source: str
    priority: int
    rationale: str


@dataclass
class _ActiveRule:
    rule: ConditionalRule
    started_tick: int


@dataclass
class _ActivePress:
    assignment: PressingAssignment
    started_tick: int


@dataclass
class _ActiveRoutine:
    plan: PhasePlan
    routine: TacticalRoutine
    started_tick: int
    step_index: int = 0
    step_started_tick: int = 0


@dataclass
class TacticalRuntime:
    """A match-local tactic with explicit role bindings and observable trace.

    Slot bindings are supplied by a scenario/team sheet, not inferred from a
    universal player rating. The stable starting shape gives TEAM_SHAPE anchors
    a fixed reference instead of making them drift on every physics tick.
    """

    tactic: TacticDefinition
    team_id: str
    slot_players: dict[str, PlayerId]
    opponent_slots: dict[str, PlayerId] = field(default_factory=dict)
    shape_positions: dict[str, Position2D] = field(default_factory=dict)
    trace: list[TacticalFrame] = field(default_factory=list)
    last_seen_event_count: int = 0
    _active_rules: dict[str, _ActiveRule] = field(default_factory=dict, repr=False)
    _active_presses: dict[str, _ActivePress] = field(default_factory=dict, repr=False)
    _active_routine: _ActiveRoutine | None = field(default=None, repr=False)
    _handover_slots: dict[str, str] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.tactic, TacticDefinition):
            raise TypeError("tactical runtime requires a shared TacticDefinition")
        if self.team_id not in ("home", "away"):
            raise ValueError("tactical runtime team must be home or away")
        if not isinstance(self.slot_players, dict) or not isinstance(self.opponent_slots, dict):
            raise TypeError("tactical player bindings must be dictionaries")
        known = {slot.slot_id for slot in self.tactic.slots}
        if set(self.slot_players) - known:
            raise ValueError("tactical runtime binds an undeclared slot")
        if len(set(self.slot_players.values())) != len(self.slot_players):
            raise ValueError("one player cannot occupy multiple tactical slots")
        if not self.shape_positions:
            self.shape_positions = {}
        for slot, position in self.shape_positions.items():
            if slot not in known or not isinstance(position, Position2D):
                raise ValueError("tactical shape positions must belong to declared slots")
        issues = validate_tactic(self.tactic)
        errors = [issue.message for issue in issues if issue.severity.value == "error"]
        if errors:
            raise ValueError("invalid tactical definition: " + "; ".join(errors))

    @classmethod
    def bind(cls, play: OpenPlayState, tactic: TacticDefinition, team_id: str,
             slot_players: Mapping[str, PlayerId], *,
             opponent_slots: Mapping[str, PlayerId] | None = None) -> TacticalRuntime:
        if team_id not in ("home", "away"):
            raise ValueError("tactical runtime team must be home or away")
        bindings = dict(slot_players)
        origins: dict[str, Position2D] = {}
        for slot, player_id in bindings.items():
            player = play.players.get(player_id)
            if player is None or player.team_id != team_id:
                raise ValueError(f"slot {slot} must bind to an active player on {team_id}")
            origins[slot] = player.motion.position
        other_bindings = dict(opponent_slots or {})
        for slot, player_id in other_bindings.items():
            player = play.players.get(player_id)
            if player is None or player.team_id == team_id:
                raise ValueError(f"opponent slot {slot} must bind to an active opposing player")
        return cls(tactic, team_id, bindings, other_bindings, origins)

    def plan(self, play: OpenPlayState, phase: TacticalPhase, *,
             triggers: Iterable[Trigger] = (),
             restart_taker_id: PlayerId | None = None) -> TacticalFrame:
        """Resolve stateful rules and movement from one immutable position snapshot."""
        if not isinstance(play, OpenPlayState) or not isinstance(phase, TacticalPhase):
            raise TypeError("tactical planning requires open play and a defined phase")
        trigger_set = frozenset(triggers)
        if any(not isinstance(item, Trigger) for item in trigger_set):
            raise TypeError("tactical triggers must use shared Trigger values")
        tick = play.clock.tick
        plan = next((item for item in self.tactic.phases if item.phase is phase), None)
        orders: list[_Order] = []
        events: list[TacticalTraceEvent] = []
        if plan is not None:
            orders.extend(self._orders_from_instructions(
                play, plan.instructions, source=f"phase:{phase.value}", priority_offset=0))
            orders.extend(self._relationship_orders(play, plan.relationships))
            orders.extend(self._marking_orders(play, plan.marking, events, tick))
            routine_orders, restart_target = self._routine_orders(
                play, plan, trigger_set, events, tick, restart_taker_id)
            orders.extend(routine_orders)
        else:
            restart_target = None
            # A triggered multi-phase routine remains active across possession
            # changes and restarts until its declared completion/abort/timeout.
            if self._active_routine is not None:
                routine_orders, restart_target = self._continue_routine(
                    play, trigger_set, events, tick, restart_taker_id)
                orders.extend(routine_orders)
        orders.extend(self._pressing_orders(play, plan, trigger_set, events, tick))
        orders.extend(self._conditional_orders(play, plan, trigger_set, events, tick))

        selected = self._select_orders(orders)
        movements: list[TacticalMovement] = []
        # Kickoff formation legality is owned by P05. The long-delivery routine
        # can choose its pass target, while players hold their validated setup.
        if phase is not TacticalPhase.KICKOFF_RESTART:
            for order in selected:
                if order.target is None:
                    continue
                player_id = self.slot_players.get(order.slot_id)
                player = play.players.get(player_id) if player_id is not None else None
                if player is None or player.team_id != self.team_id:
                    continue
                moved = advance_player(
                    player.motion,
                    MovementIntent(player_id, order.target, order.target),
                    play.physics.step_seconds,
                    play.pitch,
                )
                movements.append(TacticalMovement(
                    order.slot_id, player_id, order.action, order.source, order.priority,
                    player.motion.position, order.target, moved, order.rationale,
                ))
        frame = TacticalFrame(
            self.team_id, str(self.tactic.tactic_id), tick, phase,
            tuple(sorted(trigger_set, key=lambda item: item.value)),
            tuple(sorted(movements, key=lambda item: (str(item.player_id), item.slot_id))),
            tuple(events), restart_taker_id, restart_target,
        )
        self.trace.append(frame)
        return frame

    def step(self, play: OpenPlayState, phase: TacticalPhase, *,
             triggers: Iterable[Trigger] = (),
             restart_taker_id: PlayerId | None = None) -> TacticalFrame:
        """Plan and apply one tactic in isolation from any other team runtime."""
        frame = self.plan(play, phase, triggers=triggers,
                          restart_taker_id=restart_taker_id)
        apply_tactical_frames(play, (frame,))
        return frame

    def _orders_from_instructions(self, play: OpenPlayState,
                                  instructions: Iterable[IndividualInstruction], *,
                                  source: str, priority_offset: int) -> list[_Order]:
        orders = []
        for instruction in instructions:
            if instruction.slot_id not in self.slot_players:
                continue
            action = instruction.actions[0]
            target = self._instruction_target(play, instruction, action)
            orders.append(_Order(instruction.slot_id, action, target, source,
                                 priority_offset + instruction.priority,
                                 f"{source} assigned {action.value}"))
        return orders

    def _instruction_target(self, play: OpenPlayState,
                            instruction: IndividualInstruction,
                            action: TacticalAction) -> Position2D | None:
        if action is TacticalAction.DELIVER_LONG:
            return self._resolve_anchor(play, instruction.slot_id, instruction.anchor)
        if instruction.anchor is not None:
            target = self._resolve_anchor(play, instruction.slot_id, instruction.anchor)
            origin = self.shape_positions.get(instruction.slot_id, target)
            mid_y = play.pitch.width_m / 2.0
            if action is TacticalAction.MOVE_INSIDE:
                lateral = abs(instruction.anchor.lateral_offset_m)
                inward = 1.0 if origin.y_m < mid_y else -1.0
                return play.pitch.clamp(Position2D(
                    target.x_m, origin.y_m + inward * max(1.0, lateral)))
            if action is TacticalAction.HOLD_WIDTH:
                # A width duty may move a player farther from the centre, but
                # never erases width by pulling the player into the same lane.
                if abs(target.y_m - mid_y) < abs(origin.y_m - mid_y):
                    return Position2D(target.x_m, origin.y_m)
            return target
        player_id = self.slot_players[instruction.slot_id]
        player = play.players.get(player_id)
        origin = (self.shape_positions.get(instruction.slot_id)
                  or (player.motion.position if player else Position2D(0.0, 0.0)))
        sign = 1.0 if play.attack_right_by_team[self.team_id] else -1.0
        if action is TacticalAction.RETREAT:
            return play.pitch.clamp(Position2D(origin.x_m - sign * 6.0, origin.y_m))
        if action in (TacticalAction.PRESS_RECEIVER, TacticalAction.CLOSE_PIVOT,
                      TacticalAction.BLOCK_RETURN):
            return play.ball.position
        if action in (TacticalAction.SUPPORT, TacticalAction.OFFER_OUTLET,
                      TacticalAction.RECYCLE_POSSESSION):
            return origin
        if action is TacticalAction.ATTACK_NEAR_POST:
            return Position2D(play.pitch.clamp(Position2D(
                play.pitch.length_m - sign * 4.0 if sign > 0 else 4.0,
                play.pitch.width_m * .25)).x_m, play.pitch.width_m * .25)
        if action is TacticalAction.ATTACK_FAR_POST:
            return Position2D(play.pitch.clamp(Position2D(
                play.pitch.length_m - sign * 4.0 if sign > 0 else 4.0,
                play.pitch.width_m * .75)).x_m, play.pitch.width_m * .75)
        if action is TacticalAction.ATTACK_CENTRAL:
            x = play.pitch.length_m - sign * 4.0 if sign > 0 else 4.0
            return play.pitch.clamp(Position2D(x, play.pitch.width_m / 2.0))
        if action in (TacticalAction.HOLD_WIDTH, TacticalAction.MOVE_INSIDE,
                      TacticalAction.OVERLAP, TacticalAction.UNDERLAP,
                      TacticalAction.OCCUPY_SPACE, TacticalAction.COVER_DEPTH,
                      TacticalAction.DROP_SHORT, TacticalAction.RUN_BEHIND,
                      TacticalAction.ADVANCE_WHILE_BALL_TRAVELS):
            return origin
        return None

    def _resolve_anchor(self, play: OpenPlayState, slot: str,
                        anchor) -> Position2D:
        origin = self.shape_positions.get(slot)
        player_id = self.slot_players.get(slot)
        current = play.players.get(player_id) if player_id is not None else None
        base = origin or (current.motion.position if current else play.ball.position)
        if anchor is None:
            point = base
        elif anchor.reference is AnchorReference.BALL:
            point = play.ball.position
        elif anchor.reference is AnchorReference.TEAMMATE:
            ref_id = self.slot_players.get(anchor.reference_slot_id or "")
            reference = play.players.get(ref_id) if ref_id is not None else None
            point = reference.motion.position if reference else base
        elif anchor.reference is AnchorReference.OPPONENT:
            ref_id = self.opponent_slots.get(anchor.reference_slot_id or "")
            reference = play.players.get(ref_id) if ref_id is not None else None
            point = reference.motion.position if reference else base
        else:
            point = base
        sign = 1.0 if play.attack_right_by_team[self.team_id] else -1.0
        desired = play.pitch.clamp(Position2D(
            point.x_m + sign * anchor.longitudinal_offset_m if anchor else point.x_m,
            point.y_m + anchor.lateral_offset_m if anchor else point.y_m,
        ))
        if anchor is not None and anchor.reference is AnchorReference.SPACE:
            return self._open_space(play, desired)
        return desired

    def _open_space(self, play: OpenPlayState, desired: Position2D) -> Position2D:
        opponents = [item.motion.position for item in play.players.values()
                     if item.team_id != self.team_id]
        if not opponents:
            return desired
        candidates = []
        for dx in (-4.0, -2.0, 0.0, 2.0, 4.0):
            for dy in (-4.0, -2.0, 0.0, 2.0, 4.0):
                point = play.pitch.clamp(Position2D(desired.x_m + dx, desired.y_m + dy))
                nearest = min(math.dist((point.x_m, point.y_m), (op.x_m, op.y_m))
                              for op in opponents)
                candidates.append((nearest, -math.dist((point.x_m, point.y_m),
                                                        (desired.x_m, desired.y_m)),
                                   -point.x_m, -point.y_m, point))
        return max(candidates, key=lambda item: item[:4])[4]

    def _relationship_orders(self, play: OpenPlayState,
                             relationships: Iterable[CoordinatedRelationship]) -> list[_Order]:
        orders: list[_Order] = []
        sign = 1.0 if play.attack_right_by_team[self.team_id] else -1.0
        mid_y = play.pitch.width_m / 2.0
        for relationship in relationships:
            slots = [slot for slot in relationship.participants if slot in self.slot_players]
            if len(slots) < 2:
                continue
            if relationship.kind is RelationshipKind.EXCHANGE_POSITIONS:
                for slot, other in zip(slots, slots[1:] + slots[:1]):
                    target = self.shape_positions.get(other)
                    if target is not None:
                        orders.append(_Order(slot, TacticalAction.SUPPORT, target,
                            f"relationship:{relationship.relationship_id}", relationship.priority,
                            "exchange the declared teammate anchors"))
            elif relationship.kind is RelationshipKind.PRESS_SUPPORT:
                for index, slot in enumerate(slots[1:], 1):
                    side = -1.0 if index % 2 else 1.0
                    target = play.pitch.clamp(Position2D(
                        play.ball.position.x_m - sign * (2.0 + index),
                        play.ball.position.y_m + side * (2.0 + index),
                    ))
                    orders.append(_Order(slot, TacticalAction.BLOCK_RETURN, target,
                        f"relationship:{relationship.relationship_id}", relationship.priority,
                        "support the press by occupying a return lane"))
            elif relationship.kind is RelationshipKind.COVER:
                for slot in slots[1:]:
                    origin = self.shape_positions.get(slot, play.ball.position)
                    target = play.pitch.clamp(Position2D(
                        play.ball.position.x_m - sign * 6.0, origin.y_m))
                    orders.append(_Order(slot, TacticalAction.COVER_DEPTH, target,
                        f"relationship:{relationship.relationship_id}", relationship.priority,
                        "hold a cover position behind the ball"))
            elif relationship.kind in (RelationshipKind.UNDERLAP,
                                       RelationshipKind.OVERLAP):
                runner, wide = slots[0], slots[1]
                wide_player = play.players.get(self.slot_players[wide])
                if wide_player is None:
                    continue
                y = wide_player.motion.position.y_m
                if relationship.kind is RelationshipKind.UNDERLAP:
                    y += math.copysign(min(7.0, abs(mid_y - y) * .45), mid_y - y)
                    x = wide_player.motion.position.x_m + sign * 3.0
                    action = TacticalAction.UNDERLAP
                else:
                    y += -5.0 if y < mid_y else 5.0
                    x = wide_player.motion.position.x_m + sign * 5.0
                    action = TacticalAction.OVERLAP
                target = play.pitch.clamp(Position2D(x, y))
                orders.append(_Order(runner, action, target,
                    f"relationship:{relationship.relationship_id}", relationship.priority,
                    f"coordinate a {relationship.kind.value} outside the wide player's lane"))
            elif relationship.kind is RelationshipKind.THIRD_PLAYER_RUN:
                runner = slots[-1]
                pair = [play.players.get(self.slot_players[slot]) for slot in slots[:-1]]
                pair = [item for item in pair if item is not None]
                y = (sum(item.motion.position.y_m for item in pair) / len(pair)
                     if pair else mid_y)
                target = play.pitch.clamp(Position2D(
                    play.ball.position.x_m + sign * 7.0, y))
                orders.append(_Order(runner, TacticalAction.RUN_BEHIND, target,
                    f"relationship:{relationship.relationship_id}", relationship.priority,
                    "make the declared third-player run into the next lane"))
            elif relationship.kind is RelationshipKind.WEAK_SIDE_OUTLET:
                slot = slots[-1]
                y = 5.0 if play.ball.position.y_m >= mid_y else play.pitch.width_m - 5.0
                target = play.pitch.clamp(Position2D(
                    play.ball.position.x_m + sign * 5.0, y))
                orders.append(_Order(slot, TacticalAction.OFFER_OUTLET, target,
                    f"relationship:{relationship.relationship_id}", relationship.priority,
                    "keep a wide weak-side outlet available"))
            # TRACK_AND_HANDOVER is implemented by explicit marking assignments.
        return orders

    def _marking_orders(self, play: OpenPlayState,
                        assignments: Iterable[MarkingAssignment],
                        events: list[TacticalTraceEvent], tick: int) -> list[_Order]:
        orders = []
        for index, marking in enumerate(assignments):
            marker_slot = self._handover_slots.get(marking.marker_slot, marking.marker_slot)
            marker_id = self.slot_players.get(marker_slot)
            target_id = self.opponent_slots.get(marking.target.reference or "")
            marker = play.players.get(marker_id) if marker_id is not None else None
            target = play.players.get(target_id) if target_id is not None else None
            if marker is None or target is None:
                events.append(TacticalTraceEvent(
                    "mark_target_unavailable", tick,
                    f"marking assignment {index} has no active marker or referenced opponent",
                    (marking.marker_slot,),
                ))
                continue
            distance = math.dist((marker.motion.position.x_m, marker.motion.position.y_m),
                                 (target.motion.position.x_m, target.motion.position.y_m))
            if (marking.behavior is MarkingBehavior.HANDOVER_ON_ROTATION
                    and distance > marking.maximum_distance_m
                    and marker_slot != marking.handover_to_slot
                    and marking.handover_to_slot in self.slot_players):
                old = marker_slot
                marker_slot = marking.handover_to_slot
                self._handover_slots[marking.marker_slot] = marker_slot
                marker_id = self.slot_players[marker_slot]
                marker = play.players.get(marker_id)
                events.append(TacticalTraceEvent(
                    "marking_handover", tick,
                    f"{old} handed {marking.target.reference} to {marker_slot} at {distance:.2f} m",
                    (old, marker_slot),
                ))
            if marker is None:
                continue
            orders.append(_Order(marker_slot, TacticalAction.TRACK_OPPONENT,
                target.motion.position, f"marking:{index}", 80 + marking.priority,
                f"track {marking.target.reference} under {marking.behavior.value}"))
        return orders

    def _pressing_orders(self, play: OpenPlayState, plan: PhasePlan | None,
                         triggers: frozenset[Trigger],
                         events: list[TacticalTraceEvent], tick: int) -> list[_Order]:
        orders = []
        assignments = ({f"{plan.phase.value}:{index}": assignment
                        for index, assignment in enumerate(plan.pressing)}
                       if plan is not None else {})
        for key, active in self._active_presses.items():
            assignments.setdefault(key, active.assignment)
        for key in sorted(assignments):
            assignment = assignments[key]
            active = self._active_presses.get(key)
            if active is not None:
                age = tick - active.started_tick
                if assignment.abort_if in triggers or age >= assignment.expires_after_ticks:
                    reason = ("abort condition" if assignment.abort_if in triggers
                              else "tick expiry")
                    events.append(TacticalTraceEvent(
                        "press_fallback", tick,
                        f"press assignment {key} returned to fallback after {reason}",
                        (assignment.first_presser_slot, *assignment.support_slots),
                    ))
                    orders.extend(self._orders_from_instructions(
                        play, assignment.fallback, source=f"press-fallback:{key}",
                        priority_offset=100))
                    self._active_presses.pop(key, None)
                    continue
            elif assignment.trigger in triggers:
                active = _ActivePress(assignment, tick)
                self._active_presses[key] = active
                events.append(TacticalTraceEvent(
                    "press_activated", tick,
                    f"press assignment {key} activated on {assignment.trigger.value}",
                    (assignment.first_presser_slot, *assignment.support_slots),
                ))
            if active is None:
                continue
            first = assignment.first_presser_slot
            support = assignment.support_slots
            if first in self.slot_players:
                ball = play.ball.position
                if assignment.angle.value == "inside_out":
                    y = ball.y_m + (2.0 if ball.y_m < play.pitch.width_m / 2 else -2.0)
                    target = Position2D(ball.x_m, y)
                elif assignment.angle.value == "outside_in":
                    y = ball.y_m + (-2.0 if ball.y_m < play.pitch.width_m / 2 else 2.0)
                    target = Position2D(ball.x_m, y)
                else:
                    sign = 1.0 if play.attack_right_by_team[self.team_id] else -1.0
                    target = Position2D(ball.x_m - sign * 2.0, ball.y_m)
                orders.append(_Order(first, TacticalAction.PRESS_RECEIVER,
                    play.pitch.clamp(target), f"press:{key}", 100,
                    f"first presser closes on the ball from {assignment.angle.value}"))
            support_radius = 2.0 + 8.0 * (1.0 - float(assignment.commitment))
            for support_index, slot in enumerate(support):
                if slot not in self.slot_players:
                    continue
                side = -1.0 if support_index % 2 == 0 else 1.0
                target = play.pitch.clamp(Position2D(
                    play.ball.position.x_m - (1.0 if support_index % 2 == 0 else -1.0)
                    * support_radius,
                    play.ball.position.y_m + side * support_radius,
                ))
                orders.append(_Order(slot, TacticalAction.BLOCK_RETURN, target,
                    f"press-support:{key}", 100,
                    f"support presses at a {support_radius:.2f} m return-lane offset"))
        return orders

    def _conditional_orders(self, play: OpenPlayState, plan: PhasePlan | None,
                            triggers: frozenset[Trigger],
                            events: list[TacticalTraceEvent], tick: int) -> list[_Order]:
        orders = []
        matched = []
        applicable = {rule.rule_id: rule for rule in (plan.conditional_rules if plan else ())}
        applicable.update({rule_id: active.rule for rule_id, active in self._active_rules.items()})
        for rule_id in sorted(applicable):
            rule = applicable[rule_id]
            active = self._active_rules.get(rule.rule_id)
            if active is None and plan is not None and rule.trigger in triggers:
                active = _ActiveRule(rule, tick)
                self._active_rules[rule.rule_id] = active
                events.append(TacticalTraceEvent(
                    "conditional_activated", tick,
                    f"rule {rule.rule_id} activated on {rule.trigger.value}",
                    tuple(item.slot_id for item in rule.instructions),
                ))
            if active is None:
                continue
            age = tick - active.started_tick
            if rule.abort_if in triggers or age >= rule.expires_after_ticks:
                reason = "abort condition" if rule.abort_if in triggers else "tick expiry"
                events.append(TacticalTraceEvent(
                    "conditional_fallback", tick,
                    f"rule {rule.rule_id} returned to fallback after {reason}",
                    tuple(item.slot_id for item in rule.fallback),
                ))
                orders.extend(self._orders_from_instructions(
                    play, rule.fallback, source=f"rule-fallback:{rule.rule_id}",
                    priority_offset=200))
                self._active_rules.pop(rule.rule_id, None)
                continue
            matched.append((rule, active))
        if matched:
            rule, _active = max(matched, key=lambda item: (item[0].priority, item[0].rule_id))
            orders.extend(self._orders_from_instructions(
                play, rule.instructions, source=f"rule:{rule.rule_id}",
                priority_offset=200 + rule.priority))
        return orders

    def _routine_orders(self, play: OpenPlayState, plan: PhasePlan,
                        triggers: frozenset[Trigger],
                        events: list[TacticalTraceEvent], tick: int,
                        restart_taker_id: PlayerId | None
                        ) -> tuple[list[_Order], Position2D | None]:
        if self._active_routine is None:
            eligible = [routine for routine in plan.routines
                        if routine.start_trigger in triggers]
            if eligible:
                routine = max(eligible, key=lambda item: (item.priority, item.routine_id))
                self._active_routine = _ActiveRoutine(plan, routine, tick, 0, tick)
                events.append(TacticalTraceEvent(
                    "routine_started", tick,
                    f"routine {routine.routine_id} started on {routine.start_trigger.value}",
                ))
        return self._continue_routine(play, triggers, events, tick, restart_taker_id)

    def _continue_routine(self, play: OpenPlayState, triggers: frozenset[Trigger],
                          events: list[TacticalTraceEvent], tick: int,
                          restart_taker_id: PlayerId | None
                          ) -> tuple[list[_Order], Position2D | None]:
        active = self._active_routine
        if active is None:
            return [], None
        routine = active.routine
        step = routine.steps[active.step_index]
        if routine.abort_if in triggers or tick - active.started_tick >= routine.expires_after_ticks:
            reason = "abort condition" if routine.abort_if in triggers else "routine expiry"
            events.append(TacticalTraceEvent(
                "routine_fallback", tick,
                f"routine {routine.routine_id} returned to fallback after {reason}",
            ))
            self._active_routine = None
            return self._orders_from_instructions(
                play, routine.fallback, source=f"routine-fallback:{routine.routine_id}",
                priority_offset=300), None
        if tick - active.step_started_tick >= step.timeout_ticks:
            events.append(TacticalTraceEvent(
                "routine_step_fallback", tick,
                f"routine {routine.routine_id} step {step.sequence} timed out",
                tuple(item.slot_id for item in step.fallback),
            ))
            self._active_routine = None
            return self._orders_from_instructions(
                play, step.fallback, source=f"routine-step-fallback:{routine.routine_id}",
                priority_offset=300), None
        if step.complete_when in triggers:
            if active.step_index + 1 >= len(routine.steps):
                events.append(TacticalTraceEvent(
                    "routine_completed", tick,
                    f"routine {routine.routine_id} completed after step {step.sequence}",
                ))
                self._active_routine = None
                return [], None
            active.step_index += 1
            active.step_started_tick = tick
            step = routine.steps[active.step_index]
            events.append(TacticalTraceEvent(
                "routine_step_advanced", tick,
                f"routine {routine.routine_id} advanced to step {step.sequence}",
                tuple(item.slot_id for item in step.instructions),
            ))
        orders = self._orders_from_instructions(
            play, step.instructions, source=f"routine:{routine.routine_id}:{step.sequence}",
            priority_offset=300 + routine.priority)
        restart_target = None
        if restart_taker_id is not None and restart_taker_id in self.slot_players.values():
            for order in orders:
                if (order.action is TacticalAction.DELIVER_LONG
                        and self.slot_players.get(order.slot_id) == restart_taker_id):
                    restart_target = order.target
                    break
        return orders, restart_target

    @staticmethod
    def _select_orders(orders: Iterable[_Order]) -> tuple[_Order, ...]:
        by_slot: dict[str, list[_Order]] = {}
        for order in orders:
            by_slot.setdefault(order.slot_id, []).append(order)
        selected = []
        for slot_id in sorted(by_slot):
            selected.append(max(by_slot[slot_id], key=lambda item: (
                item.priority, item.source, item.action.value,
                item.target.x_m if item.target else -1.0,
                item.target.y_m if item.target else -1.0)))
        return tuple(selected)

    def mark_events_seen(self, event_count: int) -> None:
        if type(event_count) is not int or event_count < self.last_seen_event_count:
            raise ValueError("tactical event cursor must be a non-decreasing event count")
        self.last_seen_event_count = event_count


def apply_tactical_frames(play: OpenPlayState,
                          frames: Iterable[TacticalFrame]) -> None:
    """Apply planned movement simultaneously from the same starting snapshot."""
    frames = tuple(frames)
    moving = [move for frame in frames for move in frame.movements]
    ids = [move.player_id for move in moving]
    if len(ids) != len(set(ids)):
        raise ValueError("a player cannot receive tactical movement from two teams")
    updates: dict[PlayerId, PlayerState] = {}
    for move in moving:
        current = play.players.get(move.player_id)
        if current is None or current.motion.position != move.start:
            raise ValueError("tactical movement frame no longer matches the shared snapshot")
        updates[move.player_id] = replace(current, motion=move.result)
    play.players.update(updates)


__all__ = [
    "TacticalFrame", "TacticalMovement", "TacticalRuntime", "TacticalTraceEvent",
    "apply_tactical_frames",
]
