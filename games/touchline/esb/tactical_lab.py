"""Headless scenario editing, spatial lab runs and event-position replay (P07).

The lab owns its synthetic team sheet, tactic plan and recorded view. It runs
the normal P05/P06 match transitions, but its controlled open-play checkpoint
is intentionally not a career fixture or a resumable career save.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, replace
from pathlib import Path

from games.touchline.esb.content.proof_roster import PROOF_SQUADS
from games.touchline.esb.content.proof_tactics import (
    COMPACT_BLOCK_COUNTER,
    MAN_ORIENTED_PRESS,
    POSITIONAL_POSSESSION,
    WIDE_ISOLATION,
)
from games.touchline.esb.events import EventEnvelope
from games.touchline.esb.ids import MatchId, PlayerId
from games.touchline.esb.match.ball import BALL_RADIUS_M, BallState
from games.touchline.esb.match.engine import (
    MatchPhase,
    MatchState,
    TeamSheet,
    create_match,
    step_match,
)
from games.touchline.esb.match.possession import PlayerState
from games.touchline.esb.match.rules import STANDARD_RULES
from games.touchline.esb.match.spatial import PlayerMotion, Pitch, limits_from_profile
from games.touchline.esb.match.tactics import TacticalRuntime
from games.touchline.esb.model import Position2D
from games.touchline.esb.serialization import dumps, loads
from games.touchline.esb.tactics import (
    AnchorReference,
    IndividualInstruction,
    PhasePlan,
    RelativeAnchor,
    TacticalAction,
    TacticalPhase,
    TacticDefinition,
    validate_tactic,
)


SLOT_INDEX = {
    "GK": 0, "LCB": 2, "RCB": 3, "LB": 5, "RB": 6,
    "DM": 8, "LCM": 10, "RCM": 11, "LW": 12, "RW": 13, "ST": 14,
}

HOME_POSITIONS = {
    "GK": (5.0, 34.0), "LCB": (20.0, 20.0), "RCB": (20.0, 48.0),
    "LB": (27.0, 8.0), "RB": (27.0, 60.0), "DM": (37.0, 34.0),
    "LCM": (43.0, 23.0), "RCM": (43.0, 45.0), "LW": (52.0, 8.0),
    "RW": (52.0, 60.0), "ST": (59.0, 34.0),
}
AWAY_POSITIONS = {
    "GK": (100.0, 34.0), "LCB": (88.0, 20.0), "RCB": (88.0, 48.0),
    "LB": (78.0, 8.0), "RB": (78.0, 60.0), "DM": (67.0, 34.0),
    "LCM": (61.0, 23.0), "RCM": (61.0, 45.0), "LW": (58.0, 8.0),
    "RW": (58.0, 60.0), "ST": (56.0, 34.0),
}
KICKOFF_HOME_POSITIONS = {
    "GK": (5.0, 34.0), "LCB": (18.0, 20.0), "RCB": (18.0, 48.0),
    "LB": (27.0, 7.0), "RB": (27.0, 61.0), "DM": (35.0, 34.0),
    "LCM": (40.0, 24.0), "RCM": (40.0, 44.0), "LW": (46.0, 7.0),
    "RW": (46.0, 61.0), "ST": (52.5, 34.0),
}
KICKOFF_AWAY_POSITIONS = {
    "GK": (100.0, 34.0), "LCB": (90.0, 20.0), "RCB": (90.0, 48.0),
    "LB": (80.0, 7.0), "RB": (80.0, 61.0), "DM": (72.0, 34.0),
    "LCM": (65.0, 24.0), "RCM": (65.0, 44.0), "LW": (62.0, 7.0),
    "RW": (62.0, 61.0), "ST": (63.0, 34.0),
}


@dataclass(frozen=True)
class TacticalLabScenario:
    scenario_id: str
    name: str
    description: str
    tactic: TacticDefinition
    possession_team_id: str
    carrier_slot_id: str
    ball_position: Position2D


LAB_SCENARIOS = (
    TacticalLabScenario(
        "build_up", "Build-up shape", "Home build-up against a settled opponent",
        POSITIONAL_POSSESSION, "home", "DM", Position2D(35.0, 34.0),
    ),
    TacticalLabScenario(
        "pressing", "Defensive block", "Home press and cover against away possession",
        MAN_ORIENTED_PRESS, "away", "DM", Position2D(67.0, 34.0),
    ),
    TacticalLabScenario(
        "compact", "Compact block", "Compact defensive shape with a forward outlet",
        COMPACT_BLOCK_COUNTER, "away", "DM", Position2D(67.0, 34.0),
    ),
    TacticalLabScenario(
        "wide_attack", "Wide attack", "Home wide isolation in an established attack",
        WIDE_ISOLATION, "home", "DM", Position2D(75.0, 34.0),
    ),
)
_SCENARIO_BY_ID = {scenario.scenario_id: scenario for scenario in LAB_SCENARIOS}


@dataclass(frozen=True)
class PlayerPlacement:
    slot_id: str
    position: Position2D

    def __post_init__(self) -> None:
        if not isinstance(self.slot_id, str) or not self.slot_id:
            raise ValueError("placement requires a tactical slot ID")
        if not isinstance(self.position, Position2D):
            raise TypeError("placement position must use Position2D metres")


@dataclass(frozen=True)
class TacticalLabPlan:
    schema_version: int
    scenario_id: str
    seed: int
    tactic: TacticDefinition
    placements: tuple[PlayerPlacement, ...]

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("unsupported Tactical Lab plan version")
        if not isinstance(self.scenario_id, str) or not self.scenario_id:
            raise ValueError("plan requires a scenario ID")
        if type(self.seed) is not int or self.seed < 0:
            raise ValueError("plan seed must be a non-negative integer")
        if not isinstance(self.tactic, TacticDefinition):
            raise TypeError("plan requires a shared tactical definition")
        if not isinstance(self.placements, tuple) or any(
            not isinstance(item, PlayerPlacement) for item in self.placements
        ):
            raise TypeError("plan placements must be an immutable tuple")


@dataclass(frozen=True)
class PositionSample:
    team_id: str
    slot_id: str | None
    player_id: PlayerId
    position: Position2D


@dataclass(frozen=True)
class PositionSnapshot:
    match_tick: int
    positions: tuple[PositionSample, ...]
    ball_position: Position2D
    possession_team_id: str | None
    possession_player_id: PlayerId | None

    def __post_init__(self) -> None:
        if type(self.match_tick) is not int or self.match_tick < 0:
            raise ValueError("position snapshot tick must be non-negative")
        if not isinstance(self.positions, tuple) or any(
            not isinstance(item, PositionSample) for item in self.positions
        ):
            raise TypeError("position snapshots require immutable player samples")
        if len({item.player_id for item in self.positions}) != len(self.positions):
            raise ValueError("position snapshots cannot repeat a player")
        pitch = Pitch()
        if not pitch.contains(self.ball_position) or any(
            not pitch.contains(item.position) for item in self.positions
        ):
            raise ValueError("snapshot positions must remain inside the pitch")
        if self.possession_team_id not in (None, "home", "away"):
            raise ValueError("snapshot possession team must be home, away or unset")
        if self.possession_player_id is not None:
            player = next((item for item in self.positions
                           if item.player_id == self.possession_player_id), None)
            if player is None or player.team_id != self.possession_team_id:
                raise ValueError("snapshot possession must name a player on the recorded team")


@dataclass(frozen=True)
class RecordedEvent:
    event: EventEnvelope
    snapshot: PositionSnapshot

    def __post_init__(self) -> None:
        if not isinstance(self.event, EventEnvelope) or not isinstance(self.snapshot, PositionSnapshot):
            raise TypeError("replay records require an event and immutable position snapshot")
        if self.event.match_tick > self.snapshot.match_tick:
            raise ValueError("a replay snapshot cannot precede its event tick")


@dataclass(frozen=True)
class LabCheckpoint:
    label: str
    snapshot: PositionSnapshot

    def __post_init__(self) -> None:
        if not isinstance(self.label, str) or not self.label.strip():
            raise ValueError("lab checkpoint requires an explanatory label")
        if not isinstance(self.snapshot, PositionSnapshot):
            raise TypeError("lab checkpoint requires an immutable position snapshot")


def scenario_by_id(scenario_id: str) -> TacticalLabScenario:
    try:
        return _SCENARIO_BY_ID[scenario_id]
    except KeyError as exc:
        raise ValueError(f"unknown Tactical Lab scenario {scenario_id!r}") from exc


def default_plan(scenario_id: str = "build_up", *, seed: int = 8217) -> TacticalLabPlan:
    scenario = scenario_by_id(scenario_id)
    positions = dict(HOME_POSITIONS)
    if scenario.possession_team_id == "home":
        positions[scenario.carrier_slot_id] = (
            scenario.ball_position.x_m, scenario.ball_position.y_m,
        )
    plan = TacticalLabPlan(
        1,
        scenario.scenario_id,
        seed,
        scenario.tactic,
        tuple(PlayerPlacement(slot, Position2D(*positions[slot]))
              for slot in SLOT_INDEX),
    )
    validate_plan(plan)
    return plan


def validate_plan(plan: TacticalLabPlan) -> None:
    if not isinstance(plan, TacticalLabPlan):
        raise TypeError("expected TacticalLabPlan")
    scenario_by_id(plan.scenario_id)
    issues = validate_tactic(plan.tactic)
    errors = [issue.message for issue in issues if issue.severity.value == "error"]
    if errors:
        raise ValueError("tactic plan is invalid: " + "; ".join(errors))
    slot_ids = tuple(slot.slot_id for slot in plan.tactic.slots)
    if set(slot_ids) != set(SLOT_INDEX):
        raise ValueError("Tactical Lab currently supports the declared 11 role slots")
    placement_ids = tuple(item.slot_id for item in plan.placements)
    if len(placement_ids) != len(set(placement_ids)):
        raise ValueError("a plan cannot place one tactical slot more than once")
    if set(placement_ids) != set(slot_ids):
        raise ValueError("plan must place every declared tactical slot exactly once")
    pitch = Pitch()
    for placement in plan.placements:
        if not pitch.contains(placement.position):
            raise ValueError(f"{placement.slot_id} placement must be within the pitch")


def set_player_placement(plan: TacticalLabPlan, slot_id: str,
                         position: Position2D) -> TacticalLabPlan:
    validate_plan(plan)
    if slot_id not in SLOT_INDEX:
        raise ValueError(f"unknown formation slot {slot_id!r}")
    if not Pitch().contains(position):
        raise ValueError("player placement must remain within the pitch")
    updated = replace(
        plan,
        placements=tuple(
            PlayerPlacement(item.slot_id, position if item.slot_id == slot_id else item.position)
            for item in plan.placements
        ),
    )
    validate_plan(updated)
    return updated


def set_instruction_action(plan: TacticalLabPlan, phase: TacticalPhase,
                           slot_id: str, action: TacticalAction) -> TacticalLabPlan:
    """Replace the chosen slot's action while retaining its declared anchor."""
    validate_plan(plan)
    if not isinstance(phase, TacticalPhase) or not isinstance(action, TacticalAction):
        raise TypeError("instruction editing requires shared phase and action values")
    if slot_id not in {slot.slot_id for slot in plan.tactic.slots}:
        raise ValueError(f"unknown tactic slot {slot_id!r}")

    phase_found = False
    phases: list[PhasePlan] = []
    for item in plan.tactic.phases:
        if item.phase is not phase:
            phases.append(item)
            continue
        phase_found = True
        instructions = list(item.instructions)
        instruction_index = next(
            (i for i, instruction in enumerate(instructions)
             if instruction.slot_id == slot_id),
            None,
        )
        if instruction_index is None:
            instructions.append(IndividualInstruction(
                slot_id,
                (action,),
                RelativeAnchor(AnchorReference.TEAM_SHAPE, 0.0, 0.0),
            ))
        else:
            instructions[instruction_index] = replace(
                instructions[instruction_index], actions=(action,),
            )
        phases.append(replace(item, instructions=tuple(instructions)))
    if not phase_found:
        phases.append(PhasePlan(
            phase,
            (IndividualInstruction(
                slot_id,
                (action,),
                RelativeAnchor(AnchorReference.TEAM_SHAPE, 0.0, 0.0),
            ),),
        ))
    updated = replace(
        plan,
        tactic=replace(
            plan.tactic,
            phases=tuple(phases),
            version=plan.tactic.version + 1,
        ),
    )
    validate_plan(updated)
    return updated


_PLAN_NAME = re.compile(r"[A-Za-z0-9_-]{1,48}\Z")


def save_plan(plan: TacticalLabPlan, data_dir: str | os.PathLike[str], *,
              name: str = "current") -> Path:
    """Atomically save one validated tactic plan, never a match or career."""
    validate_plan(plan)
    if not _PLAN_NAME.fullmatch(name):
        raise ValueError("plan name may contain only letters, numbers, '_' or '-'")
    directory = Path(data_dir)
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{name}.json"
    temporary = directory / f".{name}.tmp"
    encoded = dumps(plan)
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(encoded)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    return destination


def load_plan(data_dir: str | os.PathLike[str], *,
              name: str = "current") -> TacticalLabPlan:
    if not _PLAN_NAME.fullmatch(name):
        raise ValueError("plan name may contain only letters, numbers, '_' or '-'")
    source = Path(data_dir) / f"{name}.json"
    plan = loads(source.read_text(encoding="utf-8"), TacticalLabPlan)
    validate_plan(plan)
    return plan


def _team_sheet(team_id: str, squad, positions: dict[str, tuple[float, float]]) -> tuple[TeamSheet, dict[str, PlayerId]]:
    starters = []
    bindings: dict[str, PlayerId] = {}
    for slot, index in SLOT_INDEX.items():
        profile = squad.players[index]
        motion = PlayerMotion(
            profile.player_id,
            team_id,
            Position2D(*positions[slot]),
            0.0,
            0.0,
            0.0,
            limits_from_profile(profile),
        )
        starters.append(PlayerState(profile, motion, team_id))
        bindings[slot] = profile.player_id
    selected = set(bindings.values())
    substitutes = tuple(player for player in squad.players if player.player_id not in selected)
    return TeamSheet(team_id, tuple(starters), substitutes), bindings


def _set_position(state: MatchState, player_id: PlayerId, position: Position2D) -> None:
    player = state.play.players[player_id]
    motion = replace(
        player.motion,
        position=position,
        velocity_x_mps=0.0,
        velocity_y_mps=0.0,
    )
    state.play.players[player_id] = replace(player, motion=motion)


def _position_snapshot(state: MatchState,
                       slot_players: dict[str, dict[PlayerId, str]]) -> PositionSnapshot:
    samples = []
    for player_id, player in sorted(state.play.players.items(), key=lambda item: str(item[0])):
        slot_id = next(
            (slot for slot, bound_id in slot_players[player.team_id].items()
             if bound_id == player_id),
            None,
        )
        samples.append(PositionSample(
            player.team_id,
            slot_id,
            player_id,
            player.motion.position,
        ))
    return PositionSnapshot(
        state.play.clock.tick,
        tuple(samples),
        state.play.ball.position,
        state.play.possession_team_id,
        state.play.possession_id,
    )


class TacticalLabRun:
    """One deterministic lab run with transition-bound event snapshots."""

    def __init__(self, plan: TacticalLabPlan):
        validate_plan(plan)
        self.plan = plan
        self.scenario = scenario_by_id(plan.scenario_id)
        home_sheet, self.home_slots = _team_sheet(
            "home", PROOF_SQUADS[0], KICKOFF_HOME_POSITIONS,
        )
        away_sheet, self.away_slots = _team_sheet(
            "away", PROOF_SQUADS[1], KICKOFF_AWAY_POSITIONS,
        )
        rules = STANDARD_RULES.with_overrides(
            "rules:p07-tactical-lab-v1",
            half_duration_ticks=300,
            stoppage_time_ticks=0,
            extra_time_duration_ticks=0,
            extra_time_stoppage_ticks=0,
            offside_enabled=False,
            foul_probability_per_challenge=0.0,
        )
        match_id = MatchId(f"match:p07-lab:{plan.seed}:{plan.scenario_id}")
        self.match = create_match(
            home_sheet,
            away_sheet,
            rules=rules,
            seed=plan.seed,
            match_id=match_id,
        )
        slot_players = {"home": self.home_slots, "away": self.away_slots}

        self.recorded_events: list[RecordedEvent] = []
        # Match creation events are captured at their actual pre-kickoff state.
        self._record_new_events(0, _position_snapshot(self.match, slot_players))
        # Take one ordinary, legal kickoff before laying out the synthetic
        # open-play checkpoint. Events from this engine transition retain the
        # resulting transition snapshot and their original tick/sequence.
        kickoff_event_count = len(self.match.events)
        step_match(self.match)
        self._record_new_events(
            kickoff_event_count,
            _position_snapshot(self.match, slot_players),
        )

        for placement in plan.placements:
            _set_position(self.match, self.home_slots[placement.slot_id], placement.position)
        for slot_id, values in AWAY_POSITIONS.items():
            _set_position(self.match, self.away_slots[slot_id], Position2D(*values))

        carrier_slots = self.home_slots if self.scenario.possession_team_id == "home" else self.away_slots
        carrier_id = carrier_slots[self.scenario.carrier_slot_id]
        carrier_position = self.match.play.players[carrier_id].motion.position
        self.match.play.ball = BallState(carrier_position, BALL_RADIUS_M, 0.0, 0.0, 0.0)
        self.match.play.possession_id = carrier_id
        self.match.play.possession_team_id = self.scenario.possession_team_id
        self.match.play.last_pass_event_id = None
        self.match.play.last_pass_receiver_id = None
        self.match.play.shot_assist_event_id = None
        self.match.play.shot_assist_player_id = None
        self.match.play.out_of_play_boundary = None
        self.match.no_retouch_player_id = None
        self.match.restart = None
        self.match.phase = MatchPhase.IN_PLAY
        self.checkpoint = LabCheckpoint(
            "Controlled open-play checkpoint after legal kickoff",
            _position_snapshot(self.match, slot_players),
        )

        references = {
            "opponent:deep_playmaker": self.away_slots["DM"],
            "opponent:center_back_left": self.away_slots["LCB"],
            "opponent:pivot": self.away_slots["DM"],
            "opponent:last_line": self.away_slots["ST"],
            "opponent:throw_receiver": self.away_slots["LW"],
            "deep_touchline_runner": self.away_slots["LW"],
        }
        self.tactical_runtime = TacticalRuntime.bind(
            self.match.play,
            plan.tactic,
            "home",
            self.home_slots,
            opponent_slots=references,
        )
        self._slot_players = slot_players
        self._recorded_event_count = len(self.match.events)
        self.transition_count = 1

    @property
    def events(self) -> tuple[RecordedEvent, ...]:
        return tuple(self.recorded_events)

    @property
    def finished(self) -> bool:
        return self.match.phase in (MatchPhase.FINISHED, MatchPhase.ABANDONED)

    def _record_new_events(self, start: int, snapshot: PositionSnapshot) -> None:
        for event in self.match.events[start:]:
            self.recorded_events.append(RecordedEvent(event, snapshot))

    def step(self) -> tuple[RecordedEvent, ...]:
        if self.finished:
            return ()
        before = self._recorded_event_count
        step_match(self.match, tactical_runtimes={"home": self.tactical_runtime})
        snapshot = _position_snapshot(self.match, self._slot_players)
        self.transition_count += 1
        self._record_new_events(before, snapshot)
        self._recorded_event_count = len(self.match.events)
        return tuple(self.recorded_events[before:])

    def run_steps(self, count: int) -> tuple[RecordedEvent, ...]:
        if type(count) is not int or count < 0:
            raise ValueError("step count must be a non-negative integer")
        first = len(self.recorded_events)
        for _ in range(count):
            if self.finished:
                break
            self.step()
        return tuple(self.recorded_events[first:])

    def run_to_completion(self, *, maximum_transitions: int = 10_000) -> MatchState:
        if type(maximum_transitions) is not int or maximum_transitions <= 0:
            raise ValueError("transition budget must be a positive integer")
        for _ in range(maximum_transitions):
            if self.finished:
                return self.match
            self.step()
        raise RuntimeError("Tactical Lab run exceeded its transition budget")

    def inspect_event(self, event_id: str | EventEnvelope) -> RecordedEvent:
        """Return the immutable event/snapshot pair without changing simulation."""
        selected = event_id.event_id if isinstance(event_id, EventEnvelope) else str(event_id)
        for record in self.recorded_events:
            if str(record.event.event_id) == selected:
                return record
        raise KeyError(f"no recorded Tactical Lab event {selected!r}")


def create_run(plan: TacticalLabPlan) -> TacticalLabRun:
    return TacticalLabRun(plan)


__all__ = [
    "AWAY_POSITIONS", "HOME_POSITIONS", "LAB_SCENARIOS", "SLOT_INDEX",
    "LabCheckpoint", "PlayerPlacement", "PositionSample", "PositionSnapshot",
    "RecordedEvent", "TacticalLabPlan", "TacticalLabRun", "TacticalLabScenario",
    "create_run", "default_plan", "load_plan", "save_plan", "scenario_by_id",
    "set_instruction_action", "set_player_placement", "validate_plan",
]
