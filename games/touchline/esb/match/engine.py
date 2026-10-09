"""Rules, legal restarts and bounded full-match progression (P05).

This is a headless competition-match boundary around the P04 open-play core.
Competition settings are immutable match inputs; the current legacy career
does not create or consume these states.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Callable, Mapping

from games.touchline.esb.events import EventEnvelope
from games.touchline.esb.ids import EventId, MatchId, PlayerId, validate_id
from games.touchline.esb.match.actions import PassIntent, PassKind
from games.touchline.esb.match.ball import BALL_RADIUS_M, BallPhysics, BallState
from games.touchline.esb.match.possession import (
    ActionKind, Decision, FeasibleAction, OpenPlayState, PlayerState,
    _cap, create_state, execute_action,
    perceive, step_open_play,
)
from games.touchline.esb.match.rules import MatchRules, STANDARD_RULES
from games.touchline.esb.match.tactics import (
    TacticalFrame, TacticalRuntime, apply_tactical_frames,
)
from games.touchline.esb.match.spatial import PlayerMotion, Pitch, limits_from_profile
from games.touchline.esb.model import Position2D
from games.touchline.esb.people import PlayerProfile, PrimaryRole
from games.touchline.esb.randomness import RandomStreams
from games.touchline.esb.serialization import dumps, loads
from games.touchline.esb.tactics import TacticalPhase, Trigger
from games.touchline.esb.time import MatchClock


class MatchPhase(str, Enum):
    RESTART_READY = "restart_ready"
    IN_PLAY = "in_play"
    INTERVAL = "interval"
    SHOOTOUT = "shootout"
    FINISHED = "finished"
    ABANDONED = "abandoned"


class MatchPeriod(str, Enum):
    FIRST_HALF = "first_half"
    SECOND_HALF = "second_half"
    EXTRA_TIME_FIRST = "extra_time_first"
    EXTRA_TIME_SECOND = "extra_time_second"


class RestartKind(str, Enum):
    KICKOFF = "kickoff"
    THROW_IN = "throw_in"
    GOAL_KICK = "goal_kick"
    CORNER = "corner"
    FREE_KICK = "free_kick"
    PENALTY = "penalty"


class CardKind(str, Enum):
    YELLOW = "yellow"
    RED = "red"


@dataclass(frozen=True)
class TeamSheet:
    team_id: str
    starters: tuple[PlayerState, ...]
    substitutes: tuple[PlayerProfile, ...] = ()
    unavailable_player_ids: tuple[PlayerId, ...] = ()

    def __post_init__(self) -> None:
        validate_id(self.team_id, kind="team ID")
        if self.team_id not in ("home", "away"):
            raise ValueError("P05 proof match team IDs must be 'home' and 'away'")
        if not isinstance(self.starters, tuple) or not self.starters:
            raise ValueError("a team sheet requires at least one eligible starter")
        if not isinstance(self.substitutes, tuple) or not isinstance(self.unavailable_player_ids, tuple):
            raise TypeError("team-sheet players and unavailable IDs must be tuples")
        if any(not isinstance(item, PlayerState) or item.team_id != self.team_id for item in self.starters):
            raise ValueError("every starting player must belong to this match team")
        if any(not isinstance(item, PlayerProfile) for item in self.substitutes):
            raise TypeError("substitutes must be PlayerProfile records")
        ids = [item.profile.player_id for item in self.starters]
        ids.extend(item.player_id for item in self.substitutes)
        if len(ids) != len(set(ids)):
            raise ValueError("team sheet cannot repeat a starter or substitute")
        for player_id in self.unavailable_player_ids:
            validate_id(player_id, kind="unavailable player ID")
        if set(ids) & set(self.unavailable_player_ids):
            raise ValueError("an unavailable player cannot be named as a starter or substitute")


@dataclass(frozen=True)
class MatchInputSnapshot:
    """Immutable kickoff sheets retained after substitutions or dismissals."""

    home_sheet: TeamSheet
    away_sheet: TeamSheet

    def __post_init__(self) -> None:
        if (not isinstance(self.home_sheet, TeamSheet) or self.home_sheet.team_id != "home"
                or not isinstance(self.away_sheet, TeamSheet) or self.away_sheet.team_id != "away"):
            raise ValueError("match input snapshot requires home and away kickoff sheets")


def match_input_snapshot_sha256(snapshot: MatchInputSnapshot) -> str:
    """Fingerprint the exact kickoff sheets, including condition-derived limits."""
    if not isinstance(snapshot, MatchInputSnapshot):
        raise TypeError("match input fingerprint requires a kickoff snapshot")
    # Local import avoids making the base match engine depend on the world layer at import time.
    from games.touchline.esb.world.season import immutable_snapshot_json

    return hashlib.sha256(immutable_snapshot_json(snapshot).encode("utf-8")).hexdigest()


@dataclass
class TeamRoster:
    team_id: str
    starting_ids: tuple[PlayerId, ...]
    substitutes: list[PlayerProfile]
    unavailable_ids: tuple[PlayerId, ...] = ()
    sent_off_ids: list[PlayerId] = field(default_factory=list)
    substituted_off_ids: list[PlayerId] = field(default_factory=list)
    substitutions_made: int = 0
    substitution_windows_used: list[str] = field(default_factory=list)
    yellow_cards: dict[PlayerId, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        validate_id(self.team_id, kind="team ID")
        if self.team_id not in ("home", "away"):
            raise ValueError("match roster team ID must be home or away")
        if not isinstance(self.starting_ids, tuple) or not isinstance(self.substitutes, list):
            raise TypeError("match roster requires starter IDs and a mutable bench list")
        if not isinstance(self.unavailable_ids, tuple) or not isinstance(self.sent_off_ids, list):
            raise TypeError("match roster availability records have invalid containers")
        if not isinstance(self.substituted_off_ids, list) or not isinstance(self.substitution_windows_used, list):
            raise TypeError("match roster history must use lists")
        if not isinstance(self.yellow_cards, dict):
            raise TypeError("yellow-card counts must be keyed by player ID")
        if type(self.substitutions_made) is not int or self.substitutions_made < 0:
            raise ValueError("substitution count must be non-negative")

    def eligible_bench(self) -> tuple[PlayerProfile, ...]:
        blocked = set(self.unavailable_ids) | set(self.sent_off_ids) | set(self.substituted_off_ids)
        return tuple(player for player in self.substitutes if player.player_id not in blocked)


@dataclass(frozen=True)
class RestartState:
    kind: RestartKind
    team_id: str
    spot: Position2D
    designated_player_id: PlayerId
    awarded_tick: int
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, RestartKind):
            raise TypeError("restart state requires a registered kind")
        if self.team_id not in ("home", "away"):
            raise ValueError("restart team must be home or away")
        validate_id(self.designated_player_id, kind="restart taker ID")
        if not isinstance(self.spot, Position2D):
            raise TypeError("restart spot must be a position")
        if type(self.awarded_tick) is not int or self.awarded_tick < 0:
            raise ValueError("restart tick must be non-negative")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("restart reason must be explicit")


@dataclass(frozen=True)
class PendingAdvantage:
    team_id: str
    restart_kind: RestartKind
    spot: Position2D
    expires_tick: int
    fouled_player_id: PlayerId

    def __post_init__(self) -> None:
        if (self.team_id not in ("home", "away")
                or not isinstance(self.restart_kind, RestartKind)
                or not isinstance(self.spot, Position2D)):
            raise ValueError("advantage requires an awarded team and foul spot")
        if type(self.expires_tick) is not int or self.expires_tick < 0:
            raise ValueError("advantage expiry tick must be non-negative")
        validate_id(self.fouled_player_id, kind="fouled player ID")


@dataclass(frozen=True)
class ShootoutKick:
    index: int
    team_id: str
    taker_id: PlayerId
    goalkeeper_id: PlayerId | None
    scored: bool
    saved: bool


@dataclass
class ShootoutState:
    kicks_per_team: int
    attempts: dict[str, int] = field(default_factory=lambda: {"home": 0, "away": 0})
    goals: dict[str, int] = field(default_factory=lambda: {"home": 0, "away": 0})
    kicks: list[ShootoutKick] = field(default_factory=list)
    finished: bool = False

    def __post_init__(self) -> None:
        if type(self.kicks_per_team) is not int or self.kicks_per_team <= 0:
            raise ValueError("shootout requires a positive number of initial kicks")
        if set(self.attempts) != {"home", "away"} or set(self.goals) != {"home", "away"}:
            raise ValueError("shootout counters require home and away entries")
        if any(type(value) is not int or value < 0 for value in (*self.attempts.values(), *self.goals.values())):
            raise ValueError("shootout counters must be non-negative integers")
        if not isinstance(self.kicks, list) or type(self.finished) is not bool:
            raise TypeError("shootout history and completion flag are invalid")


@dataclass
class MatchState:
    match_id: MatchId
    rules: MatchRules
    play: OpenPlayState
    teams: dict[str, TeamRoster]
    phase: MatchPhase
    period: MatchPeriod
    period_start_tick: int
    initial_kickoff_team_id: str
    restart: RestartState | None = None
    pending_advantage: PendingAdvantage | None = None
    shootout: ShootoutState | None = None
    no_retouch_player_id: PlayerId | None = None
    offside_exempt_event_id: EventId | None = None
    last_touch_team_id: str | None = None
    finished_reason: str | None = None
    result_events: list[EventId] = field(default_factory=list)
    last_touch_player_id: PlayerId | None = None
    last_touch_event_id: EventId | None = None
    playing_ticks: dict[PlayerId, int] = field(default_factory=dict)
    keeper_replacement_team_id: str | None = None
    input_snapshot: MatchInputSnapshot | None = None

    def __post_init__(self) -> None:
        validate_id(self.match_id, kind="match ID")
        if self.play.match_id != self.match_id or not isinstance(self.rules, MatchRules):
            raise ValueError("match state, rules and open-play aggregate must agree")
        if not isinstance(self.phase, MatchPhase) or not isinstance(self.period, MatchPeriod):
            raise TypeError("match requires explicit phase and period")
        if type(self.period_start_tick) is not int or self.period_start_tick < 0:
            raise ValueError("period start tick must be non-negative")
        if self.initial_kickoff_team_id not in ("home", "away"):
            raise ValueError("initial kickoff team must be home or away")
        if set(self.teams) != {"home", "away"}:
            raise ValueError("match must contain both team rosters")
        if any(key != value.team_id for key, value in self.teams.items()):
            raise ValueError("team roster map keys must match team IDs")
        if self.last_touch_team_id not in (None, "home", "away"):
            raise ValueError("last-touch team must be home, away or unknown")
        if not isinstance(self.result_events, list):
            raise TypeError("match result event references must be a list")
        if self.last_touch_player_id is not None:
            validate_id(self.last_touch_player_id, kind="last-touch player ID")
        if self.last_touch_event_id is not None:
            validate_id(self.last_touch_event_id, kind="last-touch event ID")
        if self.keeper_replacement_team_id not in (None, "home", "away"):
            raise ValueError("keeper replacement team must be home, away or unset")
        if not isinstance(self.playing_ticks, dict):
            raise TypeError("playing-time projection must be keyed by player ID")
        if any(type(ticks) is not int or ticks < 0 for ticks in self.playing_ticks.values()):
            raise ValueError("playing time must use non-negative match ticks")
        if self.input_snapshot is not None and not isinstance(self.input_snapshot, MatchInputSnapshot):
            raise TypeError("match input snapshot must retain typed kickoff sheets")

    @property
    def input_snapshot_sha256(self) -> str | None:
        if self.input_snapshot is None:
            return None
        return match_input_snapshot_sha256(self.input_snapshot)

    def validate_playing_time_projection(self) -> None:
        """Rebuild playing ticks from the kickoff roster and roster-change events."""
        if self.input_snapshot is None:
            raise ValueError("match playing-time validation requires an immutable kickoff snapshot")
        snapshots = {"home": self.input_snapshot.home_sheet, "away": self.input_snapshot.away_sheet}
        player_teams: dict[PlayerId, str] = {}
        eligible_substitutes: set[PlayerId] = set()
        active = set()
        expected_ticks: dict[PlayerId, int] = {}
        for team_id, sheet in snapshots.items():
            for player in sheet.starters:
                player_id = player.profile.player_id
                player_teams[player_id] = team_id
                active.add(player_id)
                expected_ticks[player_id] = 0
            for player in sheet.substitutes:
                player_teams[player.player_id] = team_id
                eligible_substitutes.add(player.player_id)

        cursor = 0
        for event in self.events:
            tick = event.match_tick
            if type(tick) is not int or tick < cursor or tick > self.play.clock.tick:
                raise ValueError("match playing-time validation found an invalid event tick")
            elapsed = tick - cursor
            for player_id in active:
                expected_ticks[player_id] += elapsed
            cursor = tick

            payload = event.payload
            if event.kind == "substitution":
                incoming_value = payload.get("incoming_player_id")
                outgoing_value = payload.get("outgoing_player_id")
                team_id = payload.get("team_id")
                if not isinstance(incoming_value, str) or not isinstance(outgoing_value, str):
                    raise ValueError("match substitution event is missing its roster identities")
                incoming_id = PlayerId(incoming_value)
                outgoing_id = PlayerId(outgoing_value)
                actor_value = payload.get("actor_id")
                if (team_id not in snapshots or actor_value != incoming_value
                        or player_teams.get(incoming_id) != team_id
                        or player_teams.get(outgoing_id) != team_id
                        or incoming_id not in eligible_substitutes
                        or incoming_id in active or outgoing_id not in active):
                    raise ValueError("match substitution event does not reconcile to its kickoff roster")
                eligible_substitutes.remove(incoming_id)
                active.remove(outgoing_id)
                active.add(incoming_id)
                expected_ticks[incoming_id] = 0
            elif event.kind == "player_sent_off":
                actor_value = payload.get("actor_id")
                team_id = payload.get("team_id")
                if (not isinstance(actor_value, str) or team_id not in snapshots):
                    raise ValueError("match dismissal event is missing its roster identity")
                player_id = PlayerId(actor_value)
                if player_teams.get(player_id) != team_id or player_id not in active:
                    raise ValueError("match dismissal event does not reconcile to the active roster")
                active.remove(player_id)

        elapsed = self.play.clock.tick - cursor
        for player_id in active:
            expected_ticks[player_id] += elapsed
        if expected_ticks != self.playing_ticks:
            raise ValueError("match playing-time totals do not reconcile to roster events and match clock")
        if active != set(self.play.players):
            raise ValueError("match active roster does not reconcile to roster-change events")

    @property
    def home_score(self) -> int:
        return self.play.home_score

    @property
    def away_score(self) -> int:
        return self.play.away_score

    @property
    def events(self) -> tuple[EventEnvelope, ...]:
        return tuple(self.play.events)

    @property
    def player_statistics(self) -> dict[PlayerId, dict[str, int]]:
        """Project player totals from the authoritative chronological events."""
        totals: dict[PlayerId, dict[str, int]] = {}

        def credit(player_id: PlayerId | None, key: str) -> None:
            if player_id is not None:
                totals.setdefault(player_id, {})[key] = totals.setdefault(player_id, {}).get(key, 0) + 1

        for event in self.play.events:
            payload = event.payload
            actor_value = payload.get("actor_id")
            actor = PlayerId(str(actor_value)) if actor_value else None
            if event.kind == "shot":
                credit(actor, "shots")
                if event.outcome.get("saved"):
                    keeper_value = payload.get("goalkeeper_id")
                    if keeper_value:
                        credit(PlayerId(str(keeper_value)), "saves")
            elif event.kind == "goal":
                credit(actor, "goals")
                assist_value = payload.get("assist_player_id")
                credit(PlayerId(str(assist_value)) if assist_value else None, "assists")
                own_goal_value = payload.get("own_goal_player_id")
                credit(PlayerId(str(own_goal_value)) if own_goal_value else None, "own_goals")
            elif event.kind == "foul":
                credit(actor, "fouls_committed")
                victim_value = payload.get("victim_id")
                credit(PlayerId(str(victim_value)) if victim_value else None, "fouls_suffered")
            elif event.kind == "offside":
                credit(actor, "offsides")
            elif event.kind == "card":
                card = payload.get("card")
                credit(actor, "yellow_cards" if card == CardKind.YELLOW.value else "red_cards")
            elif event.kind == "player_sent_off" and payload.get("reason") == "second_yellow":
                credit(actor, "dismissals_after_second_yellow")
        return totals

    @property
    def minutes_played(self) -> dict[PlayerId, float]:
        milliseconds_per_minute = 60_000
        return {player_id: ticks * self.rules.tick_duration_ms / milliseconds_per_minute
                for player_id, ticks in self.playing_ticks.items()}

    def to_json(self) -> str:
        return dumps(self)

    @classmethod
    def from_json(cls, value: str) -> MatchState:
        return loads(value, cls)


def _emit(state: MatchState, kind: str, actor: PlayerId | None, payload: dict[str, object],
          outcome: dict[str, object], *, cause: EventId | None = None,
          parent: EventId | None = None, tick: int | None = None) -> EventId:
    play = state.play
    sequence = play.next_sequence
    event_id = EventId(f"event:{state.match_id}:{sequence:08d}")
    wrapped_payload = {
        "actor_id": str(actor) if actor is not None else None,
        "ruleset_id": state.rules.ruleset_id,
        "ruleset_version": state.rules.schema_version,
        **payload,
    }
    event = EventEnvelope(
        event_id, "match", str(state.match_id), sequence, kind,
        match_id=state.match_id, match_tick=play.clock.tick if tick is None else tick,
        cause_event_id=cause, parent_event_id=parent,
        payload_json=json.dumps(wrapped_payload, allow_nan=False, sort_keys=True),
        outcome_json=json.dumps(outcome, allow_nan=False, sort_keys=True),
    )
    play.events.append(event)
    play.next_sequence += 1
    state.result_events.append(event_id)
    return event_id


def _profile_team(state: MatchState, player_id: PlayerId) -> str | None:
    active = state.play.players.get(player_id)
    if active is not None:
        return active.team_id
    for team_id, roster in state.teams.items():
        if player_id in roster.starting_ids or any(p.player_id == player_id for p in roster.substitutes):
            return team_id
    return None


def _active(state: MatchState, team_id: str) -> tuple[PlayerState, ...]:
    return tuple(state.play.players[key] for key in sorted(state.play.players, key=str)
                 if state.play.players[key].team_id == team_id)


def _goalkeeper(state: MatchState, team_id: str) -> PlayerState | None:
    return next((p for p in _active(state, team_id)
                 if p.profile.primary_role is PrimaryRole.GOALKEEPER), None)


def _validate_engine_profile(profile: PlayerProfile) -> None:
    required = {
        "scanning", "decision_quality", "anticipation", "ball_carrying",
        "first_touch", "receiving", "short_passing", "long_passing",
        "distribution", "finishing", "defensive_positioning", "pressing_judgment",
    }
    if profile.primary_role is PrimaryRole.GOALKEEPER:
        required.update({"gk_reaction", "gk_handling"})
    available = {item.name for item in profile.capabilities.capabilities}
    missing = sorted(required - available)
    tendencies = {item.name for item in profile.tendencies.values}
    if "risk_tolerance" not in tendencies:
        missing.append("risk_tolerance tendency")
    if missing:
        raise ValueError(f"{profile.display_name} lacks required match inputs: {', '.join(missing)}")
    limits_from_profile(profile)


def _attack_right(state: MatchState, team_id: str) -> bool:
    home_right = state.period in (MatchPeriod.FIRST_HALF, MatchPeriod.EXTRA_TIME_FIRST)
    return home_right if team_id == "home" else not home_right


def _own_half_x(state: MatchState, team_id: str) -> tuple[float, float]:
    mid = state.play.pitch.length_m / 2.0
    return (0.0, mid) if _attack_right(state, team_id) else (mid, state.play.pitch.length_m)


def _validate_initial_kickoff(state: MatchState, taker_id: PlayerId) -> None:
    center = Position2D(state.play.pitch.length_m / 2.0, state.play.pitch.width_m / 2.0)
    taker = state.play.players[taker_id]
    if math.dist((taker.motion.position.x_m, taker.motion.position.y_m), (center.x_m, center.y_m)) > 1.0:
        raise ValueError("kickoff taker must start within one metre of the center spot")
    mid = center.x_m
    for player in state.play.players.values():
        if player.profile.player_id == taker_id:
            continue
        low, high = _own_half_x(state, player.team_id)
        if player.motion.position.x_m < low - 1e-9 or player.motion.position.x_m > high + 1e-9:
            raise ValueError("players must start in their own half at kickoff")
        if player.team_id != taker.team_id and abs(player.motion.position.x_m - mid) < 1e-9:
            raise ValueError("opponents must remain in their own half at kickoff")
        if math.dist((player.motion.position.x_m, player.motion.position.y_m),
                     (center.x_m, center.y_m)) < state.rules.restart_clearance_m - 1e-9:
            raise ValueError("non-kickers must be outside the kickoff center circle")


def create_match(home: TeamSheet, away: TeamSheet, *, rules: MatchRules = STANDARD_RULES,
                 seed: int = 1, pitch: Pitch = Pitch(), physics: BallPhysics = BallPhysics(),
                 match_id: MatchId | None = None, kickoff_team_id: str = "home") -> MatchState:
    """Validate eligible sheets and create a deterministic kickoff-ready match."""
    if not isinstance(home, TeamSheet) or home.team_id != "home":
        raise ValueError("home TeamSheet is required")
    if not isinstance(away, TeamSheet) or away.team_id != "away":
        raise ValueError("away TeamSheet is required")
    if not isinstance(rules, MatchRules):
        raise TypeError("match creation requires an immutable MatchRules snapshot")
    if rules.tick_duration_ms != round(physics.step_seconds * 1000):
        raise ValueError("rule clock duration must equal the selected physics step")
    if (rules.goal_half_width_m * 2.0 >= pitch.width_m
            or rules.goal_area_half_width_m * 2.0 > pitch.width_m
            or rules.penalty_area_half_width_m * 2.0 > pitch.width_m
            or rules.goal_area_depth_m > pitch.length_m / 2.0
            or rules.penalty_area_length_m > pitch.length_m / 2.0
            or rules.penalty_spot_distance_m > rules.penalty_area_length_m
            or rules.goal_half_width_m + BALL_RADIUS_M >= pitch.width_m / 2.0
            or rules.goal_half_width_m <= BALL_RADIUS_M
            or rules.goal_height_m <= BALL_RADIUS_M
            or rules.restart_clearance_m > math.hypot(pitch.length_m / 2.0, pitch.width_m / 2.0)
            or rules.throw_in_clearance_m > math.hypot(pitch.length_m / 2.0, pitch.width_m / 2.0)
            or rules.penalty_spot_distance_m + rules.restart_clearance_m >= pitch.length_m / 2.0):
        raise ValueError("selected pitch cannot contain the configured goal/restart geometry")
    if kickoff_team_id not in ("home", "away"):
        raise ValueError("kickoff team must be home or away")
    if any(len(sheet.starters) > rules.maximum_players_per_team for sheet in (home, away)):
        raise ValueError("starting lineup exceeds this competition's player limit")
    for sheet in (home, away):
        if len(sheet.starters) >= rules.minimum_players_to_continue and rules.goalkeeper_required:
            if sum(p.profile.primary_role is PrimaryRole.GOALKEEPER for p in sheet.starters) != 1:
                raise ValueError(f"{sheet.team_id} must field exactly one eligible goalkeeper")
    all_ids = [item.profile.player_id for sheet in (home, away) for item in sheet.starters]
    all_ids += [profile.player_id for sheet in (home, away) for profile in sheet.substitutes]
    unavailable = [player_id for sheet in (home, away) for player_id in sheet.unavailable_player_ids]
    all_ids += unavailable
    if len(all_ids) != len(set(all_ids)):
        raise ValueError("a player cannot appear, be unavailable, or be registered twice in one match")
    sheets = {"home": home, "away": away}
    for sheet in (home, away):
        for starter in sheet.starters:
            _validate_engine_profile(starter.profile)
            measured_limits = limits_from_profile(starter.profile)
            if (not math.isclose(starter.motion.limits.maximum_speed_mps,
                                 measured_limits.maximum_speed_mps, abs_tol=1e-9)
                    or not math.isclose(starter.motion.limits.acceleration_mps2,
                                        measured_limits.acceleration_mps2, abs_tol=1e-9)):
                raise ValueError(f"{starter.profile.display_name} motion limits do not match profile measurements")
        for substitute_profile in sheet.substitutes:
            _validate_engine_profile(substitute_profile)
    all_players = tuple(item for sheet in (home, away) for item in sheet.starters)
    selected_id = match_id or MatchId(f"match:p05:{seed}")
    center = Position2D(pitch.length_m / 2.0, pitch.width_m / 2.0)
    play = create_state(selected_id, all_players,
        BallState(center, BALL_RADIUS_M, 0.0, 0.0, 0.0), None,
        RandomStreams.seeded(seed), pitch=pitch, physics=physics)
    teams = {
        team_id: TeamRoster(team_id,
            tuple(player.profile.player_id for player in sheet.starters),
            list(sheet.substitutes), sheet.unavailable_player_ids)
        for team_id, sheet in sheets.items()
    }
    state = MatchState(selected_id, rules, play, teams, MatchPhase.RESTART_READY,
        MatchPeriod.FIRST_HALF, 0, kickoff_team_id,
        playing_ticks={player.profile.player_id: 0 for player in all_players},
        input_snapshot=MatchInputSnapshot(home, away))
    _emit(state, "match_started", None,
        {"kickoff_team_id": kickoff_team_id},
        {"phase": state.phase.value, "ruleset_id": rules.ruleset_id,
         "ruleset_version": rules.schema_version})
    if min(len(_active(state, "home")), len(_active(state, "away"))) < rules.minimum_players_to_continue:
        _abandon(state, "starting_players_below_competition_minimum")
        return state
    kicker = _select_taker(state, kickoff_team_id, center, RestartKind.KICKOFF)
    _validate_initial_kickoff(state, kicker)
    _award_restart(state, RestartKind.KICKOFF, kickoff_team_id, center,
                   reason="match_start", designated_player_id=kicker)
    if min(len(_active(state, "home")), len(_active(state, "away"))) < rules.minimum_players_to_continue:
        _abandon(state, "starting_players_below_competition_minimum")
    return state


def _select_taker(state: MatchState, team_id: str, spot: Position2D,
                  kind: RestartKind) -> PlayerId:
    players = _active(state, team_id)
    if not players:
        raise ValueError(f"{team_id} has no eligible player for a restart")
    if kind is RestartKind.GOAL_KICK:
        keeper = _goalkeeper(state, team_id)
        if keeper is not None:
            return keeper.profile.player_id
    if kind is RestartKind.PENALTY:
        return max(players, key=lambda p: (_cap(p.profile, "finishing"),
                                           str(p.profile.player_id))).profile.player_id
    return min(players, key=lambda p: (
        math.dist((p.motion.position.x_m, p.motion.position.y_m), (spot.x_m, spot.y_m)),
        str(p.profile.player_id))).profile.player_id


def _reset_player_motion(player: PlayerState, position: Position2D) -> PlayerState:
    motion = replace(player.motion, position=position, velocity_x_mps=0.0,
                      velocity_y_mps=0.0)
    return replace(player, motion=motion)


def _prepare_kickoff_positions(state: MatchState, team_id: str, taker_id: PlayerId) -> None:
    pitch = state.play.pitch
    mid, center_y = pitch.length_m / 2.0, pitch.width_m / 2.0
    clearance = state.rules.restart_clearance_m
    center = Position2D(mid, center_y)
    for player_id in sorted(state.play.players, key=str):
        item = state.play.players[player_id]
        if player_id == taker_id:
            state.play.players[player_id] = _reset_player_motion(item, center)
            continue
        low, high = _own_half_x(state, item.team_id)
        x = min(high, max(low, item.motion.position.x_m))
        position = Position2D(x, item.motion.position.y_m)
        if math.dist((position.x_m, position.y_m), (mid, center_y)) < clearance:
            side = -1.0 if high <= mid else 1.0
            position = Position2D(min(pitch.length_m, max(0.0, mid + side * (clearance + 0.05))),
                                  position.y_m)
        state.play.players[player_id] = _reset_player_motion(item, position)


def _prepare_clearance(state: MatchState, team_id: str, spot: Position2D,
                       taker_id: PlayerId) -> None:
    _prepare_clearance_with_rule(state, team_id, spot, taker_id,
                                 state.rules.throw_in_clearance_m)


def _move_out_of_penalty_area(state: MatchState, player: PlayerState,
                              defending_team: str, spot: Position2D) -> PlayerState:
    pitch = state.play.pitch
    goal_x = 0.0 if _attack_right(state, defending_team) else pitch.length_m
    toward_mid = 1.0 if goal_x == 0.0 else -1.0
    legal_x = goal_x + toward_mid * (state.rules.penalty_spot_distance_m
                                     + state.rules.restart_clearance_m + 0.05)
    x = player.motion.position.x_m
    y = player.motion.position.y_m
    in_box = (abs(goal_x - x) <= state.rules.penalty_area_length_m
              and abs(y - pitch.width_m / 2.0) <= state.rules.penalty_area_half_width_m)
    too_close_to_spot = math.dist((x, y), (spot.x_m, spot.y_m)) < state.rules.restart_clearance_m
    if in_box or too_close_to_spot:
        position = pitch.clamp(Position2D(legal_x, y))
        return _reset_player_motion(player, position)
    return _reset_player_motion(player, player.motion.position)


def _prepare_penalty_positions(state: MatchState, team_id: str, spot: Position2D,
                               taker_id: PlayerId) -> None:
    defending_team = "away" if team_id == "home" else "home"
    keeper = _goalkeeper(state, defending_team)
    if keeper is not None:
        goal_x = 0.0 if _attack_right(state, defending_team) else state.play.pitch.length_m
        facing = math.atan2(spot.y_m - state.play.pitch.width_m / 2.0, spot.x_m - goal_x)
        motion = replace(keeper.motion,
            position=Position2D(goal_x, state.play.pitch.width_m / 2.0),
            velocity_x_mps=0.0, velocity_y_mps=0.0, facing_radians=facing)
        state.play.players[keeper.profile.player_id] = replace(keeper, motion=motion)
    for player_id in sorted(state.play.players, key=str):
        if player_id in (taker_id, keeper.profile.player_id if keeper else None):
            continue
        item = state.play.players[player_id]
        state.play.players[player_id] = _move_out_of_penalty_area(
            state, item, defending_team, spot)


def _prepare_goal_kick_positions(state: MatchState, team_id: str, spot: Position2D,
                                 taker_id: PlayerId) -> None:
    pitch = state.play.pitch
    goal_x = 0.0 if _attack_right(state, team_id) else pitch.length_m
    for player_id in sorted(state.play.players, key=str):
        item = state.play.players[player_id]
        if item.team_id == team_id or player_id == taker_id:
            continue
        x, y = item.motion.position.x_m, item.motion.position.y_m
        if (abs(goal_x - x) <= state.rules.penalty_area_length_m
                and abs(y - pitch.width_m / 2.0) <= state.rules.penalty_area_half_width_m):
            exit_x = goal_x + (1.0 if goal_x == 0.0 else -1.0) * (state.rules.penalty_area_length_m + 0.05)
            state.play.players[player_id] = _reset_player_motion(
                item, pitch.clamp(Position2D(exit_x, y)))
        else:
            state.play.players[player_id] = _reset_player_motion(item, item.motion.position)


def _prepare_restart_positions(state: MatchState, kind: RestartKind, team_id: str,
                               spot: Position2D, taker_id: PlayerId) -> None:
    if kind is RestartKind.KICKOFF:
        _prepare_kickoff_positions(state, team_id, taker_id)
        return
    if kind is RestartKind.PENALTY:
        _prepare_penalty_positions(state, team_id, spot, taker_id)
        return
    if kind is RestartKind.GOAL_KICK:
        _prepare_goal_kick_positions(state, team_id, spot, taker_id)
        return
    if kind is RestartKind.THROW_IN:
        _prepare_clearance(state, team_id, spot, taker_id)
        return
    _prepare_clearance_with_rule(state, team_id, spot, taker_id,
                                 state.rules.restart_clearance_m)


def _prepare_clearance_with_rule(state: MatchState, team_id: str, spot: Position2D,
                                 taker_id: PlayerId, clearance: float) -> None:
    updates: dict[PlayerId, PlayerState] = {}
    for player_id in sorted(state.play.players, key=str):
        item = state.play.players[player_id]
        if item.team_id == team_id or player_id == taker_id:
            continue
        dx = item.motion.position.x_m - spot.x_m
        dy = item.motion.position.y_m - spot.y_m
        distance = math.hypot(dx, dy)
        if distance >= clearance:
            continue
        if distance <= 1e-9:
            dx = -1.0 if team_id == "home" else 1.0
            dy = 0.0
            distance = 1.0
        position = state.play.pitch.clamp(Position2D(
            spot.x_m + dx / distance * (clearance + 0.05),
            spot.y_m + dy / distance * (clearance + 0.05)))
        actual = math.dist((position.x_m, position.y_m), (spot.x_m, spot.y_m))
        if actual + 1e-9 < clearance:
            corners = (Position2D(0.0, 0.0), Position2D(0.0, state.play.pitch.width_m),
                       Position2D(state.play.pitch.length_m, 0.0),
                       Position2D(state.play.pitch.length_m, state.play.pitch.width_m))
            position = max(corners, key=lambda point: (
                math.dist((point.x_m, point.y_m), (spot.x_m, spot.y_m)),
                point.x_m, point.y_m))
            actual = math.dist((position.x_m, position.y_m), (spot.x_m, spot.y_m))
        if actual + 1e-9 < clearance:
            raise ValueError("selected rules require more restart clearance than this pitch can provide")
        updates[player_id] = _reset_player_motion(item, position)
    state.play.players.update(updates)


def _award_restart(state: MatchState, kind: RestartKind, team_id: str,
                   spot: Position2D, *, reason: str,
                   designated_player_id: PlayerId | None = None,
                   cause: EventId | None = None) -> RestartState:
    if state.phase in (MatchPhase.FINISHED, MatchPhase.ABANDONED, MatchPhase.SHOOTOUT):
        raise ValueError("cannot award a restart after the match has ended")
    spot = state.play.pitch.clamp(spot)
    if kind is RestartKind.PENALTY:
        goal_x = state.play.pitch.length_m if _attack_right(state, team_id) else 0.0
        sign = -1.0 if goal_x == state.play.pitch.length_m else 1.0
        spot = Position2D(goal_x + sign * state.rules.penalty_spot_distance_m,
                          state.play.pitch.width_m / 2.0)
    if kind is RestartKind.GOAL_KICK:
        goal_x = 0.0 if _attack_right(state, team_id) else state.play.pitch.length_m
        direction = 1.0 if goal_x == 0.0 else -1.0
        spot = Position2D(goal_x + direction * state.rules.goal_area_depth_m,
                          state.play.pitch.width_m / 2.0)
    taker = designated_player_id or _select_taker(state, team_id, spot, kind)
    requested_taker = taker
    if taker not in state.play.players or state.play.players[taker].team_id != team_id:
        taker = _select_taker(state, team_id, spot, kind)
        _emit(state, "restart_taker_fallback", taker,
              {"kind": kind.value, "requested_player_id": str(requested_taker)},
              {"designated_player_id": str(taker)}, cause=cause)
    if kind is RestartKind.KICKOFF:
        _prepare_restart_positions(state, kind, team_id, spot, taker)
        spot = Position2D(state.play.pitch.length_m / 2.0, state.play.pitch.width_m / 2.0)
    else:
        _prepare_restart_positions(state, kind, team_id, spot, taker)
        state.play.players[taker] = _reset_player_motion(state.play.players[taker], spot)
    state.play.ball = BallState(spot, BALL_RADIUS_M, 0.0, 0.0, 0.0)
    state.play.out_of_play_boundary = None
    state.play.possession_id = None
    state.play.possession_team_id = None
    restart = RestartState(kind, team_id, spot, taker, state.play.clock.tick, reason)
    state.restart = restart
    state.phase = MatchPhase.RESTART_READY
    _emit(state, "restart_awarded", taker,
        {"kind": kind.value, "team_id": team_id, "reason": reason,
         "spot_x_m": spot.x_m, "spot_y_m": spot.y_m},
        {"designated_player_id": str(taker)}, cause=cause)
    return restart


def _restart_action(state: MatchState, restart: RestartState,
                    delivery_override: Position2D | None = None) -> Decision:
    taker = state.play.players[restart.designated_player_id]
    if restart.kind is RestartKind.PENALTY:
        goal_x = state.play.pitch.length_m if _attack_right(state, restart.team_id) else 0.0
        action = FeasibleAction(ActionKind.SHOT, taker.profile.player_id,
            target=Position2D(goal_x, state.play.pitch.width_m / 2.0),
            provisional_value=0.72, explanation="Penalty restart; provisional chance estimate.")
        return Decision(taker.profile.player_id, perceive(state.play, taker.profile.player_id),
                        (action,), action, "Penalty restart selected by match rules.")
    if delivery_override is not None and restart.kind is not RestartKind.PENALTY:
        target = state.play.pitch.clamp(delivery_override)
        intent = PassIntent(PassKind.FLOATED, target,
                            intended_area_id=f"tactical:{restart.kind.value}:{state.play.clock.tick}")
        action = FeasibleAction(ActionKind.PASS, taker.profile.player_id,
            target=target, intent=intent, provisional_value=0.5,
            explanation=f"{restart.kind.value} is delivered toward the called tactical area.")
        return Decision(taker.profile.player_id, perceive(state.play, taker.profile.player_id),
                        (action,), action, "A declared tactical restart routine chose the target area.")
    teammates = [p for p in _active(state, restart.team_id)
                 if p.profile.player_id != taker.profile.player_id]
    forward_sign = 1.0 if _attack_right(state, restart.team_id) else -1.0
    if teammates:
        receiver = min(teammates, key=lambda p: (
            math.dist((p.motion.position.x_m, p.motion.position.y_m),
                      (restart.spot.x_m, restart.spot.y_m)),
            str(p.profile.player_id)))
        target = receiver.motion.position
        intent = PassIntent(PassKind.DRIVEN if restart.kind is RestartKind.KICKOFF else PassKind.FLOATED,
                            target, intended_receiver_id=receiver.profile.player_id)
        target_id = receiver.profile.player_id
    else:
        target = state.play.pitch.clamp(Position2D(
            restart.spot.x_m + forward_sign * 12.0, restart.spot.y_m))
        if math.dist((target.x_m, target.y_m), (restart.spot.x_m, restart.spot.y_m)) <= 0.1:
            target = state.play.pitch.clamp(Position2D(
                restart.spot.x_m - forward_sign * 12.0, restart.spot.y_m))
        intent = PassIntent(PassKind.FLOATED, target, intended_area_id=f"restart:{restart.kind.value}")
        target_id = None
    action = FeasibleAction(ActionKind.PASS, taker.profile.player_id, target_id,
        target, intent, 0.5, f"{restart.kind.value} is delivered from its marked spot.")
    return Decision(taker.profile.player_id, perceive(state.play, taker.profile.player_id),
                    (action,), action, f"Rules selected the designated {restart.kind.value} taker.")


def _take_restart(state: MatchState, *,
                  stop_on_contact: Callable[[PlayerId, dict[PlayerId, Position2D], Position2D], bool]
                  | None = None,
                  delivery_override: Position2D | None = None) -> tuple[EventEnvelope, ...]:
    restart = state.restart
    if state.phase is not MatchPhase.RESTART_READY or restart is None:
        raise ValueError("match is not waiting for a restart")
    if state.keeper_replacement_team_id is not None:
        return ()
    taker_id = restart.designated_player_id
    if taker_id not in state.play.players or state.play.players[taker_id].team_id != restart.team_id:
        taker_id = _select_taker(state, restart.team_id, restart.spot, restart.kind)
        _emit(state, "restart_taker_reassigned", taker_id,
              {"kind": restart.kind.value}, {"designated_player_id": str(taker_id)})
        restart = replace(restart, designated_player_id=taker_id)
        state.restart = restart
    state.play.players[taker_id] = _reset_player_motion(state.play.players[taker_id], restart.spot)
    state.play.ball = BallState(restart.spot, BALL_RADIUS_M, 0.0, 0.0, 0.0)
    state.play.possession_id = taker_id
    state.play.possession_team_id = restart.team_id
    before = len(state.play.events)
    _emit(state, "restart_taken", taker_id,
          {"kind": restart.kind.value, "team_id": restart.team_id,
           "spot_x_m": restart.spot.x_m, "spot_y_m": restart.spot.y_m},
          {"phase": MatchPhase.IN_PLAY.value})
    state.restart = None
    state.phase = MatchPhase.IN_PLAY
    decision = _restart_action(state, restart, delivery_override)
    execute_action(state.play, decision, stop_on_contact=stop_on_contact)
    created = tuple(state.play.events[before:])
    if restart.kind is RestartKind.THROW_IN:
        state.no_retouch_player_id = taker_id
    else:
        state.no_retouch_player_id = None
    pass_event = next((event for event in created if event.kind == "pass"), None)
    state.offside_exempt_event_id = (
        pass_event.event_id if pass_event and restart.kind in
        (RestartKind.THROW_IN, RestartKind.GOAL_KICK, RestartKind.CORNER) else None)
    state.last_touch_team_id = restart.team_id
    return created


def substitute(state: MatchState, outgoing_id: PlayerId, incoming_id: PlayerId,
               *, window_id: str) -> EventEnvelope:
    """Apply an explicitly selected, eligibility-checked substitution atomically."""
    validate_id(outgoing_id, kind="outgoing player ID")
    validate_id(incoming_id, kind="incoming player ID")
    validate_id(window_id, kind="substitution window ID")
    if state.phase not in (MatchPhase.RESTART_READY, MatchPhase.INTERVAL):
        raise ValueError("substitutions are only available at a stoppage or interval")
    outgoing = state.play.players.get(outgoing_id)
    if outgoing is None:
        raise ValueError("outgoing player must currently be active")
    team_id = outgoing.team_id
    roster = state.teams[team_id]
    if outgoing_id in roster.sent_off_ids or outgoing_id in roster.substituted_off_ids:
        raise ValueError("outgoing player is no longer eligible")
    incoming = next((p for p in roster.eligible_bench() if p.player_id == incoming_id), None)
    if incoming is None:
        raise ValueError("incoming player must be an eligible substitute for this team")
    if (state.keeper_replacement_team_id == team_id
            and incoming.primary_role is not PrimaryRole.GOALKEEPER):
        raise ValueError("a dismissed goalkeeper must be replaced by an eligible goalkeeper")
    if roster.substitutions_made >= state.rules.substitutions_allowed:
        raise ValueError("competition substitution limit has been reached")
    is_new_window = window_id not in roster.substitution_windows_used
    if is_new_window and len(roster.substitution_windows_used) >= state.rules.substitution_windows_allowed:
        raise ValueError("competition substitution-window limit has been reached")
    current_keepers = sum(p.team_id == team_id and p.profile.primary_role is PrimaryRole.GOALKEEPER
                          for p in state.play.players.values())
    after_keepers = current_keepers - int(outgoing.profile.primary_role is PrimaryRole.GOALKEEPER) \
                    + int(incoming.primary_role is PrimaryRole.GOALKEEPER)
    if state.rules.goalkeeper_required and after_keepers != 1:
        raise ValueError("substitution must leave exactly one eligible goalkeeper on the pitch")
    if state.play.possession_id == outgoing_id:
        raise ValueError("the current ball carrier cannot be substituted during live possession")
    motion = PlayerMotion(incoming.player_id, team_id, outgoing.motion.position,
        0.0, 0.0, outgoing.motion.facing_radians, limits_from_profile(incoming))
    replacement = PlayerState(incoming, motion, team_id)
    # All validation is complete; now apply the multi-record transition.
    del state.play.players[outgoing_id]
    state.play.players[incoming_id] = replacement
    roster.substitutes.remove(incoming)
    roster.substituted_off_ids.append(outgoing_id)
    roster.substitutions_made += 1
    if is_new_window:
        roster.substitution_windows_used.append(window_id)
    state.playing_ticks.setdefault(incoming_id, 0)
    if state.keeper_replacement_team_id == team_id:
        state.keeper_replacement_team_id = None
    if state.restart and state.restart.designated_player_id == outgoing_id:
        state.restart = replace(state.restart, designated_player_id=incoming_id)
    eid = _emit(state, "substitution", incoming_id,
        {"team_id": team_id, "outgoing_player_id": str(outgoing_id),
         "incoming_player_id": str(incoming_id), "window_id": window_id},
        {"substitutions_used": roster.substitutions_made,
         "goalkeepers_on_pitch": after_keepers})
    return next(event for event in reversed(state.play.events) if event.event_id == eid)


def _abandon(state: MatchState, reason: str) -> None:
    state.phase = MatchPhase.ABANDONED
    state.finished_reason = reason
    state.restart = None
    _emit(state, "match_abandoned", None,
          {"reason": reason}, {"home_score": state.home_score, "away_score": state.away_score})


def _send_off(state: MatchState, player_id: PlayerId, reason: str,
              *, cause: EventId | None = None) -> None:
    player = state.play.players.get(player_id)
    if player is None:
        return
    roster = state.teams[player.team_id]
    roster.sent_off_ids.append(player_id)
    del state.play.players[player_id]
    if state.play.possession_id == player_id:
        state.play.possession_id = None
        state.play.possession_team_id = None
    eid = _emit(state, "player_sent_off", player_id,
        {"team_id": player.team_id, "reason": reason},
        {"players_remaining": len(_active(state, player.team_id))}, cause=cause)
    if len(_active(state, player.team_id)) < state.rules.minimum_players_to_continue:
        _abandon(state, "team_below_competition_minimum")
    else:
        was_goalkeeper = player.profile.primary_role is PrimaryRole.GOALKEEPER
        if was_goalkeeper and state.rules.goalkeeper_required:
            roster = state.teams[player.team_id]
            has_keeper_cover = any(
                item.primary_role is PrimaryRole.GOALKEEPER
                for item in roster.eligible_bench())
            substitutions_available = (
                roster.substitutions_made < state.rules.substitutions_allowed
                and (state.rules.substitution_windows_allowed > len(roster.substitution_windows_used)
                     or bool(roster.substitution_windows_used)))
            if has_keeper_cover and substitutions_available:
                state.keeper_replacement_team_id = player.team_id
                _emit(state, "keeper_replacement_required", None,
                      {"team_id": player.team_id, "dismissed_goalkeeper_id": str(player_id)},
                      {"eligible_cover": True}, cause=eid)
            else:
                _abandon(state, "required_goalkeeper_unavailable_after_dismissal")
                return
        state.last_touch_team_id = player.team_id
        _award_restart(state, RestartKind.FREE_KICK,
            "away" if player.team_id == "home" else "home",
            state.play.ball.position, reason="dismissal_restart", cause=eid)


def _penalty_area(state: MatchState, attacking_team: str, spot: Position2D) -> bool:
    goal_x = state.play.pitch.length_m if _attack_right(state, attacking_team) else 0.0
    return (abs(goal_x - spot.x_m) <= state.rules.penalty_area_length_m
            and abs(spot.y_m - state.play.pitch.width_m / 2.0) <= state.rules.penalty_area_half_width_m)


def _award_foul(state: MatchState, fouler_id: PlayerId, victim_id: PlayerId,
                cause_event_id: EventId) -> None:
    fouler_team = _profile_team(state, fouler_id)
    victim_team = _profile_team(state, victim_id)
    if fouler_team is None or victim_team is None or fouler_team == victim_team:
        return
    spot = state.play.ball.position
    foul_id = _emit(state, "foul", fouler_id,
        {"victim_id": str(victim_id), "team_id": fouler_team,
         "spot_x_m": spot.x_m, "spot_y_m": spot.y_m},
        {"fouled_team_id": victim_team}, cause=cause_event_id, parent=cause_event_id)
    if state.rules.cards_enabled:
        stream = state.play.random_streams.stream("football")
        if stream.random() < state.rules.red_card_probability_per_foul:
            _emit(state, "card", fouler_id,
                {"card": CardKind.RED.value, "reason": "serious_foul"},
                {"sent_off": True}, cause=foul_id)
            _send_off(state, fouler_id, "direct_red_card", cause=foul_id)
            return
        if stream.random() < state.rules.yellow_card_probability_per_foul:
            roster = state.teams[fouler_team]
            count = roster.yellow_cards.get(fouler_id, 0) + 1
            roster.yellow_cards[fouler_id] = count
            second = count >= 2 and state.rules.second_yellow_sends_off
            card_id = _emit(state, "card", fouler_id,
                {"card": CardKind.YELLOW.value, "yellow_count": count},
                {"sent_off": second}, cause=foul_id)
            if second:
                _send_off(state, fouler_id, "second_yellow", cause=card_id)
                return
    kind = RestartKind.PENALTY if _penalty_area(state, victim_team, spot) else RestartKind.FREE_KICK
    if state.rules.advantage_enabled and state.play.possession_team_id == victim_team:
        state.pending_advantage = PendingAdvantage(victim_team, kind, spot,
            state.play.clock.tick + state.rules.advantage_window_ticks, victim_id)
        _emit(state, "advantage_played", victim_id,
            {"team_id": victim_team, "foul_event_id": str(foul_id)},
            {"expires_tick": state.pending_advantage.expires_tick}, cause=foul_id)
    else:
        _award_restart(state, kind, victim_team, spot,
            reason="foul_in_penalty_area" if kind is RestartKind.PENALTY else "foul", cause=foul_id)


def _process_challenges(state: MatchState, events: tuple[EventEnvelope, ...]) -> None:
    if not state.rules.fouls_enabled:
        return
    stream = state.play.random_streams.stream("football")
    for event in events:
        if event.kind != "challenge_contest":
            continue
        payload = event.payload
        if stream.random() >= state.rules.foul_probability_per_challenge:
            continue
        _award_foul(state, PlayerId(str(payload["actor_id"])),
                    PlayerId(str(payload["carrier_id"])), event.event_id)
        if state.phase in (MatchPhase.RESTART_READY, MatchPhase.ABANDONED):
            break


def _offside_candidates(state: MatchState, positions: dict[PlayerId, Position2D],
                        attacker_team: str, ball_position: Position2D) -> set[PlayerId]:
    if not state.rules.offside_enabled:
        return set()
    defenders = [positions[player_id].x_m for player_id in positions
                 if _profile_team(state, player_id) not in (None, attacker_team)]
    if len(defenders) < 2:
        return set()
    right = _attack_right(state, attacker_team)
    defenders.sort(reverse=right)
    second_last = defenders[1]
    mid = state.play.pitch.length_m / 2.0
    candidates = set()
    for player_id, position in positions.items():
        if _profile_team(state, player_id) != attacker_team:
            continue
        if right:
            ahead = position.x_m > max(ball_position.x_m, second_last) + 1e-9 and position.x_m > mid
        else:
            ahead = position.x_m < min(ball_position.x_m, second_last) - 1e-9 and position.x_m < mid
        if ahead:
            candidates.add(player_id)
    return candidates


def _process_offside(state: MatchState, events: tuple[EventEnvelope, ...],
                     positions: dict[PlayerId, Position2D], ball_before: Position2D) -> bool:
    pass_events = [event for event in events if event.kind == "pass"]
    contacts = [event for event in events if event.kind == "ball_contact"]
    for delivery in pass_events:
        if delivery.event_id == state.offside_exempt_event_id:
            state.offside_exempt_event_id = None
            continue
        passer_team = _profile_team(state, PlayerId(str(delivery.payload["actor_id"])))
        if passer_team is None:
            continue
        candidates = _offside_candidates(state, positions, passer_team, ball_before)
        for contact in contacts:
            if contact.parent_event_id != delivery.event_id:
                continue
            actor = PlayerId(str(contact.payload["actor_id"]))
            if actor not in candidates:
                continue
            spot = positions.get(actor, state.play.ball.position)
            contact_x = contact.outcome.get("position_x_m")
            contact_y = contact.outcome.get("position_y_m")
            if (type(contact_x) in (int, float) and type(contact_y) in (int, float)):
                spot = Position2D(float(contact_x), float(contact_y))
            defending = "away" if passer_team == "home" else "home"
            violation = _emit(state, "offside", actor,
                {"team_id": passer_team, "pass_event_id": str(delivery.event_id)},
                {"restart_team_id": defending}, cause=contact.event_id,
                parent=delivery.event_id, tick=contact.match_tick)
            state.play.possession_id = None
            state.play.possession_team_id = None
            _award_restart(state, RestartKind.FREE_KICK, defending, spot,
                reason="offside_involvement", cause=violation)
            return True
    return False


def _restart_after_goal(state: MatchState, scoring_team: str, cause: EventId | None) -> None:
    kickoff_team = "away" if scoring_team == "home" else "home"
    _award_restart(state, RestartKind.KICKOFF, kickoff_team,
        Position2D(state.play.pitch.length_m / 2.0, state.play.pitch.width_m / 2.0),
        reason="goal_conceded", cause=cause)


def _boundary_crossing(before: Position2D, after: Position2D, pitch: Pitch) -> tuple[str, Position2D, float] | None:
    dx, dy = after.x_m - before.x_m, after.y_m - before.y_m
    candidates: list[tuple[float, int, str, str, float]] = []
    if after.y_m < 0.0 and dy < 0.0:
        candidates.append(((0.0 - before.y_m) / dy, 0, "touchline", "y", 0.0))
    if after.y_m > pitch.width_m and dy > 0.0:
        candidates.append(((pitch.width_m - before.y_m) / dy, 0, "touchline", "y", pitch.width_m))
    if after.x_m < 0.0 and dx < 0.0:
        candidates.append(((0.0 - before.x_m) / dx, 1, "goal_line", "x", 0.0))
    if after.x_m > pitch.length_m and dx > 0.0:
        candidates.append(((pitch.length_m - before.x_m) / dx, 1, "goal_line", "x", pitch.length_m))
    if not candidates:
        return None
    fraction, _, boundary, axis, edge = min(candidates, key=lambda row: (row[0], row[1]))
    position = Position2D(
        edge if axis == "x" else before.x_m + dx * fraction,
        edge if axis == "y" else before.y_m + dy * fraction,
    )
    return boundary, position, max(0.0, min(1.0, fraction))


def _handle_out_of_play(state: MatchState, previous_ball: BallState | None = None) -> bool:
    ball = state.play.ball
    pitch = state.play.pitch
    p = ball.position
    boundary = state.play.out_of_play_boundary
    if boundary is None and pitch.contains(p):
        return False
    if boundary is None:
        crossing = _boundary_crossing(previous_ball.position if previous_ball else p, p, pitch)
        if crossing is None:
            return False
        boundary, crossing_position, fraction = crossing
        if previous_ball is not None:
            ball = replace(ball, position=crossing_position,
                height_m=max(BALL_RADIUS_M, previous_ball.height_m
                    + (ball.height_m - previous_ball.height_m) * fraction))
            state.play.ball = ball
            p = crossing_position
        state.play.out_of_play_boundary = boundary
    if boundary not in ("touchline", "goal_line"):
        raise ValueError("out-of-play state lost its crossed boundary")
    last_team = state.last_touch_team_id
    if boundary == "touchline":
        if last_team is None:
            raise RuntimeError("touchline restart requires a known last-touch team")
        restart_team = "away" if last_team == "home" else "home"
        spot = Position2D(min(pitch.length_m, max(0.0, p.x_m)),
                          0.0 if p.y_m < 0.0 else pitch.width_m)
        if math.isclose(p.y_m, 0.0, abs_tol=1e-9):
            spot = Position2D(spot.x_m, 0.0)
        _emit(state, "ball_out", None, {"last_touch_team_id": last_team,
                                       "last_touch_player_id": str(state.last_touch_player_id)
                                       if state.last_touch_player_id else None},
              {"restart": RestartKind.THROW_IN.value,
               "x_m": p.x_m, "y_m": p.y_m, "boundary": boundary})
        _award_restart(state, RestartKind.THROW_IN, restart_team, spot,
                       reason="ball_crossed_touchline")
        return True
    goal_line_x = 0.0 if math.isclose(p.x_m, 0.0, abs_tol=1e-9) else pitch.length_m
    goal_x_right = goal_line_x == pitch.length_m
    opening_half_width = state.rules.goal_half_width_m - BALL_RADIUS_M
    goal_y_min = pitch.width_m / 2.0 - opening_half_width
    goal_y_max = pitch.width_m / 2.0 + opening_half_width
    target_team = next(team for team in ("home", "away") if _attack_right(state, team) == goal_x_right)
    defending_team = "away" if target_team == "home" else "home"
    if (goal_y_min <= p.y_m <= goal_y_max
            and ball.height_m <= state.rules.goal_height_m - BALL_RADIUS_M):
        last_player_team = (_profile_team(state, state.last_touch_player_id)
                            if state.last_touch_player_id is not None else None)
        scorer = state.last_touch_player_id if last_player_team == target_team else None
        own_goal_player = (state.last_touch_player_id
                           if state.last_touch_player_id is not None and last_player_team == defending_team
                           else None)
        assist_player = state.play.shot_assist_player_id if scorer is not None else None
        if assist_player == scorer:
            assist_player = None
        assist_event = state.play.shot_assist_event_id if assist_player is not None else None
        state.play.home_score += int(target_team == "home")
        state.play.away_score += int(target_team == "away")
        state.play.statistics["goals"] = state.play.statistics.get("goals", 0) + 1
        goal = _emit(state, "goal", scorer,
            {"scoring_team_id": target_team, "last_touch_team_id": last_team,
             "own_goal_player_id": str(own_goal_player) if own_goal_player else None,
             "assist_player_id": str(assist_player) if assist_player else None,
             "assist_event_id": str(assist_event) if assist_event else None,
             "source": "ball_crossed_goal_line"},
            {"home_score": state.home_score, "away_score": state.away_score,
             "crossing_height_m": ball.height_m}, cause=state.last_touch_event_id,
            parent=assist_event)
        state.play.possession_id = None
        state.play.possession_team_id = None
        state.play.out_of_play_boundary = None
        _restart_after_goal(state, target_team, goal)
    else:
        if last_team is None:
            raise RuntimeError("goal-line restart requires a known last-touch team")
        corner_awarded = last_team == target_team
        kind = RestartKind.GOAL_KICK if not corner_awarded else RestartKind.CORNER
        restart_team = defending_team if kind is RestartKind.GOAL_KICK else target_team
        y = 0.0 if p.y_m < pitch.width_m / 2 else pitch.width_m
        spot = Position2D(goal_line_x, y) if kind is RestartKind.CORNER else Position2D(
            goal_line_x, pitch.width_m / 2.0)
        _emit(state, "ball_out", None, {"last_touch_team_id": last_team,
                                       "last_touch_player_id": str(state.last_touch_player_id)
                                       if state.last_touch_player_id else None},
              {"restart": kind.value, "x_m": p.x_m, "y_m": p.y_m,
               "boundary": boundary}, cause=state.last_touch_event_id)
        state.play.out_of_play_boundary = None
        _award_restart(state, kind, restart_team, spot, reason="ball_crossed_goal_line")
    return True


def _mirror_sides(state: MatchState) -> None:
    length = state.play.pitch.length_m
    for player_id in sorted(state.play.players, key=str):
        item = state.play.players[player_id]
        facing = math.remainder(math.pi - item.motion.facing_radians, 2.0 * math.pi)
        motion = replace(item.motion,
            position=Position2D(length - item.motion.position.x_m, item.motion.position.y_m),
            velocity_x_mps=-item.motion.velocity_x_mps, facing_radians=facing)
        state.play.players[player_id] = replace(item, motion=motion)
    ball = state.play.ball
    state.play.ball = replace(ball,
        position=Position2D(length - ball.position.x_m, ball.position.y_m),
        velocity_x_mps=-ball.velocity_x_mps)
    _emit(state, "sides_switched", None, {"period": state.period.value},
          {"tick": state.play.clock.tick})


def _start_period(state: MatchState, period: MatchPeriod, kickoff_team: str) -> None:
    state.period = period
    state.period_start_tick = state.play.clock.tick
    home_right = period in (MatchPeriod.FIRST_HALF, MatchPeriod.EXTRA_TIME_FIRST)
    state.play.attack_right_by_team = {"home": home_right, "away": not home_right}
    _mirror_sides(state)
    center = Position2D(state.play.pitch.length_m / 2.0, state.play.pitch.width_m / 2.0)
    _award_restart(state, RestartKind.KICKOFF, kickoff_team, center,
                   reason=f"period_start:{period.value}")


def _finish_period(state: MatchState) -> None:
    state.restart = None
    if state.pending_advantage is not None:
        pending = state.pending_advantage
        _emit(state, "advantage_ended_at_period", pending.fouled_player_id,
              {"team_id": pending.team_id, "restart_kind": pending.restart_kind.value},
              {"continued": True})
        state.pending_advantage = None
    finished_period = state.period
    _emit(state, "period_ended", None, {"period": finished_period.value},
          {"home_score": state.home_score, "away_score": state.away_score})
    tied = state.home_score == state.away_score
    if finished_period is MatchPeriod.FIRST_HALF:
        state.phase = MatchPhase.INTERVAL
        return
    if finished_period is MatchPeriod.EXTRA_TIME_FIRST:
        state.phase = MatchPhase.INTERVAL
        return
    if finished_period is MatchPeriod.SECOND_HALF and tied and state.rules.extra_time_duration_ticks > 0:
        state.phase = MatchPhase.INTERVAL
        return
    if finished_period is MatchPeriod.EXTRA_TIME_SECOND and tied and state.rules.shootout_kicks_per_team > 0:
        state.shootout = ShootoutState(state.rules.shootout_kicks_per_team)
        state.phase = MatchPhase.SHOOTOUT
        _emit(state, "shootout_started", None, {}, {"kicks_per_team": state.rules.shootout_kicks_per_team})
        return
    if finished_period is MatchPeriod.SECOND_HALF and tied and state.rules.shootout_kicks_per_team > 0:
        state.shootout = ShootoutState(state.rules.shootout_kicks_per_team)
        state.phase = MatchPhase.SHOOTOUT
        _emit(state, "shootout_started", None, {}, {"kicks_per_team": state.rules.shootout_kicks_per_team})
        return
    state.phase = MatchPhase.FINISHED
    state.finished_reason = "full_time_draw" if tied else "full_time"
    _emit(state, "match_finished", None, {"reason": state.finished_reason},
          {"home_score": state.home_score, "away_score": state.away_score})


def _advance_interval(state: MatchState) -> None:
    team = "away" if state.initial_kickoff_team_id == "home" else "home"
    if state.period is MatchPeriod.FIRST_HALF:
        _start_period(state, MatchPeriod.SECOND_HALF, team)
    elif state.period is MatchPeriod.SECOND_HALF:
        if state.home_score == state.away_score and state.rules.extra_time_duration_ticks > 0:
            _start_period(state, MatchPeriod.EXTRA_TIME_FIRST, team)
        else:
            state.phase = MatchPhase.FINISHED
            state.finished_reason = "regulation_draw" if state.home_score == state.away_score else "full_time"
            _emit(state, "match_finished", None, {"reason": state.finished_reason},
                  {"home_score": state.home_score, "away_score": state.away_score})
    elif state.period is MatchPeriod.EXTRA_TIME_FIRST:
        _start_period(state, MatchPeriod.EXTRA_TIME_SECOND,
                      "home" if team == "away" else "away")


def _period_duration(state: MatchState) -> int:
    regular = state.rules.half_duration_ticks + state.rules.stoppage_time_ticks
    if state.period in (MatchPeriod.EXTRA_TIME_FIRST, MatchPeriod.EXTRA_TIME_SECOND):
        return state.rules.extra_time_duration_ticks + state.rules.extra_time_stoppage_ticks
    return regular


def _after_events(state: MatchState, before: int, positions: dict[PlayerId, Position2D],
                  ball_before: BallState, score_before: tuple[int, int], *,
                  offside_positions: dict[PlayerId, Position2D] | None = None,
                  offside_ball_position: Position2D | None = None) -> None:
    events = tuple(state.play.events[before:])
    for event in events:
        if event.kind in ("pass", "carry", "shot", "ball_contact", "rebound_contact"):
            actor_value = event.payload.get("actor_id")
            if actor_value:
                team = _profile_team(state, PlayerId(str(actor_value)))
                if team is not None:
                    state.last_touch_team_id = team
                    state.last_touch_player_id = PlayerId(str(actor_value))
                    state.last_touch_event_id = event.event_id
    if state.no_retouch_player_id is not None:
        for event in events:
            if event.kind != "ball_contact":
                continue
            if event.payload.get("actor_id") == str(state.no_retouch_player_id):
                offender = state.play.players.get(state.no_retouch_player_id)
                if offender is not None:
                    team = offender.team_id
                    state.play.possession_id = None
                    state.play.possession_team_id = None
                    _emit(state, "restart_retouch_violation", state.no_retouch_player_id,
                          {"restart_kind": RestartKind.THROW_IN.value},
                          {"restart_team_id": "away" if team == "home" else "home"},
                          cause=event.event_id)
                    _award_restart(state, RestartKind.FREE_KICK,
                        "away" if team == "home" else "home", state.play.ball.position,
                        reason="throw_in_taker_touched_ball_twice", cause=event.event_id)
                    state.no_retouch_player_id = None
                    return
            else:
                state.no_retouch_player_id = None
                break
    if _process_offside(state, events, offside_positions or positions,
                        offside_ball_position or ball_before.position):
        return
    _process_challenges(state, events)
    if state.phase in (MatchPhase.RESTART_READY, MatchPhase.ABANDONED):
        return
    if (state.play.home_score, state.play.away_score) != score_before:
        if state.pending_advantage is not None:
            pending = state.pending_advantage
            state.pending_advantage = None
            _emit(state, "advantage_realized_by_goal", pending.fouled_player_id,
                  {"team_id": pending.team_id}, {"goal_recorded": True})
        scoring_team = "home" if state.play.home_score > score_before[0] else "away"
        latest_goal = next((event for event in reversed(state.play.events)
                            if event.kind == "goal"), None)
        _restart_after_goal(state, scoring_team,
                            latest_goal.event_id if latest_goal is not None else None)
        return
    if state.pending_advantage is not None:
        advantage = state.pending_advantage
        if state.play.possession_team_id != advantage.team_id:
            state.pending_advantage = None
            _emit(state, "advantage_recalled", advantage.fouled_player_id,
                  {"team_id": advantage.team_id}, {"restart": advantage.restart_kind.value})
            _award_restart(state, advantage.restart_kind, advantage.team_id,
                           advantage.spot, reason="advantage_lost")
            return
        if state.play.clock.tick >= advantage.expires_tick:
            state.pending_advantage = None
            _emit(state, "advantage_expired", advantage.fouled_player_id,
                  {"team_id": advantage.team_id}, {"continued": True})
    _handle_out_of_play(state, ball_before)


def _shootout_kick(state: MatchState) -> None:
    shootout = state.shootout
    if shootout is None or shootout.finished:
        raise ValueError("match has no active penalty shootout")
    index = len(shootout.kicks)
    team_id = "home" if index % 2 == 0 else "away"
    active = list(_active(state, team_id))
    if not active:
        _abandon(state, "no_eligible_shootout_taker")
        return
    eligible = [p for p in active if p.profile.primary_role is not PrimaryRole.GOALKEEPER]
    if not eligible:
        eligible = active
    attempt_index = shootout.attempts[team_id]
    taker = eligible[attempt_index % len(eligible)]
    keeper = _goalkeeper(state, "away" if team_id == "home" else "home")
    finishing = _cap(taker.profile, "finishing")
    reaction = _cap(keeper.profile, "gk_reaction") if keeper is not None else 0.5
    handling = _cap(keeper.profile, "gk_handling") if keeper is not None else 0.5
    score_probability = max(0.08, min(0.95, 0.72 + (finishing - 0.5) * 0.24
                                      - (reaction - 0.5) * 0.20 - (handling - 0.5) * 0.08))
    scored = state.play.random_streams.stream("football").random() < score_probability
    saved = not scored and state.play.random_streams.stream("football").random() < 0.55
    shootout.attempts[team_id] += 1
    if scored:
        shootout.goals[team_id] += 1
    event_id = _emit(state, "shootout_kick", taker.profile.player_id,
        {"team_id": team_id, "attempt": shootout.attempts[team_id],
         "finishing": finishing, "goalkeeper_id": str(keeper.profile.player_id) if keeper else None,
         "goalkeeper_reaction": reaction, "goalkeeper_handling": handling},
        {"scored": scored, "saved": saved})
    shootout.kicks.append(ShootoutKick(index, team_id, taker.profile.player_id,
        keeper.profile.player_id if keeper else None, scored, saved))
    _emit(state, "shootout_goal" if scored else "shootout_save" if saved else "shootout_miss",
        taker.profile.player_id, {"attempt_event_id": str(event_id)},
        {"home_shootout_goals": shootout.goals["home"],
         "away_shootout_goals": shootout.goals["away"]}, cause=event_id, parent=event_id)
    home_a, away_a = shootout.attempts["home"], shootout.attempts["away"]
    home_g, away_g = shootout.goals["home"], shootout.goals["away"]
    base = shootout.kicks_per_team
    if home_a >= base and away_a >= base and home_g != away_g:
        shootout.finished = True
    elif home_a == away_a and home_a > base and home_g != away_g:
        shootout.finished = True
    else:
        remaining_home = max(0, base - home_a)
        remaining_away = max(0, base - away_a)
        if home_g > away_g + remaining_away and away_a < base or \
                away_g > home_g + remaining_home and home_a < base:
            shootout.finished = True
    if shootout.finished:
        state.phase = MatchPhase.FINISHED
        state.finished_reason = "penalties_home" if home_g > away_g else "penalties_away"
        _emit(state, "match_finished", None,
              {"reason": state.finished_reason},
              {"home_score": state.home_score, "away_score": state.away_score,
               "home_shootout_goals": home_g, "away_shootout_goals": away_g})


def _tactical_phase(state: MatchState, team_id: str,
                    triggers: frozenset[Trigger]) -> TacticalPhase:
    restart = state.restart
    if state.phase is MatchPhase.RESTART_READY and restart is not None:
        if restart.kind is RestartKind.KICKOFF and restart.team_id == team_id:
            return TacticalPhase.KICKOFF_RESTART
        if restart.kind is RestartKind.THROW_IN and restart.team_id != team_id:
            return TacticalPhase.THROW_IN_RESTART
    if state.play.possession_team_id != team_id:
        if Trigger.OPPONENT_ESCAPES_PRESS in triggers:
            return TacticalPhase.DEFENSIVE_TRANSITION
        return TacticalPhase.DEFENSIVE_BLOCK
    if Trigger.BALL_WON in triggers:
        return TacticalPhase.ATTACKING_TRANSITION
    ball_x = state.play.ball.position.x_m
    progress = ball_x if state.play.attack_right_by_team[team_id] else state.play.pitch.length_m - ball_x
    fraction = progress / state.play.pitch.length_m
    if fraction < 0.34:
        return TacticalPhase.BUILD_UP
    if fraction < 0.68:
        return TacticalPhase.PROGRESSION
    return TacticalPhase.ESTABLISHED_ATTACK


def _tactical_triggers(state: MatchState, team_id: str,
                       runtime: TacticalRuntime) -> frozenset[Trigger]:
    triggers: set[Trigger] = set()
    restart = state.restart
    if restart is not None:
        if restart.kind is RestartKind.KICKOFF and restart.team_id == team_id:
            triggers.add(Trigger.OWN_KICKOFF)
        if restart.kind is RestartKind.THROW_IN and restart.team_id != team_id:
            triggers.add(Trigger.OPPOSITION_THROW_IN)
        if (restart.kind is not RestartKind.KICKOFF
                and state.play.clock.tick - restart.awarded_tick <= 1):
            triggers.add(Trigger.QUICK_RESTART)
    if state.play.ball.speed_mps > 1.0:
        triggers.add(Trigger.BALL_TRAVELLING)
    events = state.play.events[runtime.last_seen_event_count:]
    for event in events:
        actor_value = event.payload.get("actor_id")
        actor_id = PlayerId(str(actor_value)) if actor_value else None
        actor = state.play.players.get(actor_id) if actor_id is not None else None
        if event.kind == "possession_regained" and actor is not None and actor.team_id == team_id:
            triggers.add(Trigger.BALL_WON)
        elif event.kind in ("deflection", "ball_control_failed", "uncontrolled_touch"):
            triggers.add(Trigger.POOR_TOUCH)
        elif event.kind == "pass":
            triggers.add(Trigger.BALL_TRAVELLING)
            if actor is None:
                continue
            if actor.team_id != team_id:
                target_x = float(event.outcome.get("actual_x_m", actor.motion.position.x_m))
                target_y = float(event.outcome.get("actual_y_m", actor.motion.position.y_m))
                sign = 1.0 if state.play.attack_right_by_team[actor.team_id] else -1.0
                if (target_x - actor.motion.position.x_m) * sign < -0.5:
                    triggers.add(Trigger.BACKWARD_PASS)
                if abs(target_y - actor.motion.position.y_m) >= 8.0 and state.play.ball.speed_mps < 12.0:
                    triggers.add(Trigger.SLOW_LATERAL_PASS)
            elif actor.team_id == team_id:
                receiver_id = event.payload.get("receiver_id")
                receiver = state.play.players.get(PlayerId(str(receiver_id))) if receiver_id else None
                if receiver is not None:
                    forward_sign = 1.0 if state.play.attack_right_by_team[team_id] else -1.0
                    facing_forward = math.cos(receiver.motion.facing_radians) * forward_sign
                    if facing_forward < -0.25:
                        triggers.add(Trigger.RECEIVER_FACING_OWN_GOAL)
                    support = [item for item in state.play.players.values()
                               if item.team_id == team_id and item.profile.player_id != receiver.profile.player_id]
                    nearest = min((math.dist((item.motion.position.x_m, item.motion.position.y_m),
                                             (receiver.motion.position.x_m, receiver.motion.position.y_m))
                                   for item in support), default=float("inf"))
                    if nearest > 12.0:
                        triggers.add(Trigger.ISOLATED_RECEIVER)
    for active in runtime._active_presses.values():
        presser_id = runtime.slot_players.get(active.assignment.first_presser_slot)
        presser = state.play.players.get(presser_id) if presser_id is not None else None
        if presser is not None and math.dist(
                (presser.motion.position.x_m, presser.motion.position.y_m),
                (state.play.ball.position.x_m, state.play.ball.position.y_m)) > 16.0:
            triggers.add(Trigger.OPPONENT_ESCAPES_PRESS)
    if state.play.possession_id is not None and state.play.possession_team_id != team_id:
        carrier = state.play.players.get(state.play.possession_id)
        if carrier is not None:
            support_slots = {slot for phase in runtime.tactic.phases for press in phase.pressing
                             for slot in press.support_slots}
            supports = [state.play.players[runtime.slot_players[slot]]
                        for slot in support_slots if slot in runtime.slot_players
                        and runtime.slot_players[slot] in state.play.players]
            if supports and all(
                    math.dist((item.motion.position.x_m, item.motion.position.y_m),
                              (carrier.motion.position.x_m, carrier.motion.position.y_m))
                    / item.motion.limits.maximum_speed_mps > 4.0
                    for item in supports):
                triggers.add(Trigger.SUPPORT_CANNOT_ARRIVE)
    runtime.mark_events_seen(len(state.play.events))
    return frozenset(triggers)


def _apply_tactics(state: MatchState,
                   tactical_runtimes: Mapping[str, TacticalRuntime] | None
                   ) -> tuple[Position2D | None, frozenset[PlayerId]]:
    if not tactical_runtimes or state.phase not in (MatchPhase.RESTART_READY, MatchPhase.IN_PLAY):
        return None, frozenset()
    if set(tactical_runtimes) - {"home", "away"}:
        raise ValueError("tactical runtime keys must be home or away")
    frames: list[TacticalFrame] = []
    restart_target: Position2D | None = None
    for team_id in ("home", "away"):
        runtime = tactical_runtimes.get(team_id)
        if runtime is None:
            continue
        if not isinstance(runtime, TacticalRuntime) or runtime.team_id != team_id:
            raise ValueError("tactical runtime map key must match its runtime team")
        taker_id = (state.restart.designated_player_id
                    if state.restart is not None and state.restart.team_id == team_id else None)
        triggers = _tactical_triggers(state, team_id, runtime)
        frame = runtime.plan(
            state.play, _tactical_phase(state, team_id, triggers),
            triggers=triggers,
            restart_taker_id=taker_id,
        )
        frames.append(frame)
        if taker_id is not None and frame.restart_target is not None:
            restart_target = frame.restart_target
    apply_tactical_frames(state.play, frames)
    for frame in frames:
        for event in frame.events:
            actor = None
            if event.slot_ids:
                actor = tactical_runtimes[frame.team_id].slot_players.get(event.slot_ids[0])
            _emit(state, f"tactic_{event.code}", actor,
                {"team_id": frame.team_id, "tactic_id": frame.tactic_id,
                 "slot_ids": list(event.slot_ids), "detail": event.detail},
                {"phase": frame.phase.value})
    # Tactical movement has already consumed this tick's P03 movement budget.
    # Return the moved actors so open-play action execution does not advance
    # those same players a second time in the same fixed step.
    moved_players = frozenset(move.player_id for frame in frames for move in frame.movements)
    return restart_target, moved_players


def step_match(state: MatchState, *,
               tactical_runtimes: Mapping[str, TacticalRuntime] | None = None) -> MatchState:
    """Advance one rules-safe transition or open-play action round."""
    if state.phase in (MatchPhase.FINISHED, MatchPhase.ABANDONED):
        return state
    if state.keeper_replacement_team_id is not None:
        roster = state.teams[state.keeper_replacement_team_id]
        cover_available = (state.rules.goalkeeper_required
            and any(p.primary_role is PrimaryRole.GOALKEEPER for p in roster.eligible_bench())
            and roster.substitutions_made < state.rules.substitutions_allowed)
        if not cover_available:
            _abandon(state, "required_goalkeeper_unavailable_after_dismissal")
        return state
    if state.phase is MatchPhase.SHOOTOUT:
        _shootout_kick(state)
        return state
    if state.phase is MatchPhase.INTERVAL:
        _advance_interval(state)
        return state
    tactical_restart_target, tactical_moved_players = _apply_tactics(state, tactical_runtimes)
    before = len(state.play.events)
    score_before = (state.play.home_score, state.play.away_score)
    positions = {player_id: item.motion.position for player_id, item in state.play.players.items()}
    ball_before = state.play.ball
    tick_before = state.play.clock.tick
    active_before = tuple(state.play.players)
    offside_positions: dict[PlayerId, Position2D] | None = None
    offside_ball_position: Position2D | None = None
    def offside_contact_check(offside_team: str | None):
        def stop_for_offside(player_id: PlayerId,
                             launch_positions: dict[PlayerId, Position2D],
                             ball_position: Position2D) -> bool:
            nonlocal offside_positions, offside_ball_position
            offside_positions = launch_positions
            offside_ball_position = ball_position
            if offside_team is None:
                return False
            return player_id in _offside_candidates(
                state, launch_positions, offside_team, ball_position)
        return stop_for_offside if state.rules.offside_enabled else None

    if state.phase is MatchPhase.RESTART_READY:
        restart = state.restart
        check = None
        if (restart is not None and restart.kind not in
                (RestartKind.THROW_IN, RestartKind.GOAL_KICK, RestartKind.CORNER)):
            check = offside_contact_check(restart.team_id)
        _take_restart(state, stop_on_contact=check,
                      delivery_override=tactical_restart_target)
    else:
        step_open_play(state.play,
            stop_on_contact=offside_contact_check(state.play.possession_team_id),
            players_already_moved=tactical_moved_players)
    if state.play.clock.tick == tick_before:
        state.play.clock = state.play.clock.advance(1)
    elapsed_ticks = state.play.clock.tick - tick_before
    for player_id in active_before:
        state.playing_ticks[player_id] = state.playing_ticks.get(player_id, 0) + elapsed_ticks
    _after_events(state, before, positions, ball_before, score_before,
        offside_positions=offside_positions,
        offside_ball_position=offside_ball_position)
    if state.phase in (MatchPhase.FINISHED, MatchPhase.ABANDONED):
        return state
    elapsed = state.play.clock.tick - state.period_start_tick
    if elapsed >= _period_duration(state):
        _finish_period(state)
        return state
    if state.phase is MatchPhase.RESTART_READY:
        return state
    return state


def run_to_completion(state: MatchState, *, maximum_transitions: int = 500_000,
                       tactical_runtimes: Mapping[str, TacticalRuntime] | None = None) -> MatchState:
    if type(maximum_transitions) is not int or maximum_transitions <= 0:
        raise ValueError("maximum transition count must be positive")
    for _ in range(maximum_transitions):
        if state.phase in (MatchPhase.FINISHED, MatchPhase.ABANDONED):
            return state
        if state.keeper_replacement_team_id is not None:
            raise RuntimeError("an explicit eligible goalkeeper substitution is required to continue")
        step_match(state, tactical_runtimes=tactical_runtimes)
    raise RuntimeError("match did not reach a terminal state within the transition budget")


__all__ = [
    "CardKind", "MatchPeriod", "MatchPhase", "MatchState", "PendingAdvantage",
    "RestartKind", "RestartState", "ShootoutKick", "ShootoutState", "TeamRoster",
    "MatchInputSnapshot", "TeamSheet", "create_match", "match_input_snapshot_sha256",
    "run_to_completion", "step_match", "substitute",
]
