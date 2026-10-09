"""Career-facing team-sheet and tactic inputs for the spatial match engine.

The playable career still stores its original 1–99 scouting/skill ratings. This
module converts those inputs through one named compatibility profile so P05
can consume them. Converted physical values are estimates, never measurements.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import date
from typing import Any, Mapping

from games.touchline import content
from games.touchline.esb.content.proof_tactics import (
    COMPACT_BLOCK_COUNTER,
    DIRECT_SECOND_BALL,
    FLUID_COMBINATION,
    MAN_ORIENTED_PRESS,
    POSITIONAL_POSSESSION,
    SLOTS,
    VERTICAL_COMBINATION,
    WIDE_ISOLATION,
)
from games.touchline.esb.ids import PlayerId
from games.touchline.esb.match.engine import MatchState, TeamSheet
from games.touchline.esb.match.possession import PlayerState
from games.touchline.esb.match.rules import MatchRules, STANDARD_RULES
from games.touchline.esb.match.spatial import Pitch, PlayerMotion, limits_from_profile
from games.touchline.esb.match.tactics import TacticalRuntime
from games.touchline.esb.model import (
    Capability,
    CapabilitySnapshot,
    DataProvenance,
    Measurement,
    PlayerIdentity,
    Position2D,
    ProvenanceKind,
)
from games.touchline.esb.people import (
    ActionTendencies,
    ActionTendency,
    PlayerPreference,
    PlayerProfile,
    PrimaryRole,
    PreferredFoot,
    ReadinessSnapshot,
)
from games.touchline.esb.tactics import (
    PhasePlan,
    SlotRole,
    TacticDefinition,
    TacticSlot,
    TacticalPhase,
    new_tactic_id,
)
from games.touchline.esb.time import WorldDate


PROFILE_MAPPING_VERSION = "legacy-career-profile-v1"
PROFILE_PROVENANCE = DataProvenance(
    ProvenanceKind.LEGACY_CONVERSION,
    "touchline:" + PROFILE_MAPPING_VERSION,
)
MATCHDAY_PROFILE_STYLES = (
    ("possession", "Positional possession"),
    ("press", "Man-oriented press"),
    ("compact", "Compact block and counter"),
    ("wide", "Wide isolation"),
    ("fluid", "Fluid combinations"),
    ("vertical", "Vertical third-player runs"),
)
MATCHDAY_RULES = STANDARD_RULES.with_overrides(
    "rules:career-spatial-v1",
    tick_duration_ms=100,
    half_duration_ticks=27_000,
    stoppage_time_ticks=0,
    extra_time_duration_ticks=0,
    extra_time_stoppage_ticks=0,
)

# Matchday formations keep their real shape-specific slots. The P06 tactic
# language remains 4-3-3-shaped, so `tactical_slot_bindings` below maps the
# closest like-for-like role into that vocabulary and retains unmatched
# players as declared, un-instructed slots instead of mislabelling their role.
FORMATION_SLOT_IDS: dict[str, tuple[str, ...]] = {
    "4-4-2": ("GK", "LCB", "RCB", "LB", "RB", "LM", "LCM", "RCM", "RM", "ST1", "ST2"),
    "4-3-3": ("GK", "LCB", "RCB", "LB", "RB", "DM", "LCM", "RCM", "LW", "RW", "ST"),
    "3-5-2": ("GK", "LCB", "CB", "RCB", "LWB", "DM", "LCM", "RCM", "RWB", "STL", "STR"),
}
SLOT_ROLES = {
    "GK": PrimaryRole.GOALKEEPER,
    "LCB": PrimaryRole.CENTER_BACK,
    "CB": PrimaryRole.CENTER_BACK,
    "RCB": PrimaryRole.CENTER_BACK,
    "LB": PrimaryRole.FULLBACK,
    "RB": PrimaryRole.FULLBACK,
    "LWB": PrimaryRole.FULLBACK,
    "RWB": PrimaryRole.FULLBACK,
    "DM": PrimaryRole.DEFENSIVE_MIDFIELDER,
    "LCM": PrimaryRole.CENTRAL_MIDFIELDER,
    "RCM": PrimaryRole.CENTRAL_MIDFIELDER,
    "LW": PrimaryRole.WIDE_FORWARD,
    "RW": PrimaryRole.WIDE_FORWARD,
    "LM": PrimaryRole.WIDE_FORWARD,
    "RM": PrimaryRole.WIDE_FORWARD,
    "ST": PrimaryRole.STRIKER,
    "ST1": PrimaryRole.STRIKER,
    "ST2": PrimaryRole.STRIKER,
    "STL": PrimaryRole.STRIKER,
    "STR": PrimaryRole.STRIKER,
}
_SLOT_POSITIONS: dict[str, dict[str, Position2D]] = {
    "4-4-2": {
        "GK": Position2D(4, 34), "LCB": Position2D(18, 20), "RCB": Position2D(18, 48),
        "LB": Position2D(25, 7), "RB": Position2D(25, 61),
        "LM": Position2D(36, 7), "LCM": Position2D(36, 26),
        "RCM": Position2D(36, 42), "RM": Position2D(36, 61),
        "ST1": Position2D(52.5, 34), "ST2": Position2D(43.0, 46),
    },
    "4-3-3": {
        "GK": Position2D(4, 34), "LCB": Position2D(18, 20), "RCB": Position2D(18, 48),
        "LB": Position2D(25, 7), "RB": Position2D(25, 61), "DM": Position2D(36, 34),
        "LCM": Position2D(40, 23), "RCM": Position2D(40, 45), "LW": Position2D(50, 7),
        "RW": Position2D(50, 61), "ST": Position2D(52.5, 34),
    },
    "3-5-2": {
        "GK": Position2D(4, 34), "LCB": Position2D(18, 18), "CB": Position2D(15, 34),
        "RCB": Position2D(18, 50), "LWB": Position2D(37, 7), "DM": Position2D(32, 34),
        "LCM": Position2D(38, 22), "RCM": Position2D(38, 46), "RWB": Position2D(37, 61),
        "STL": Position2D(52.5, 34), "STR": Position2D(43.0, 46),
    },
}
CENTER_KICKER_SLOTS = {"4-4-2": "ST1", "4-3-3": "ST", "3-5-2": "STL"}
_TACTICAL_SLOT_ALIASES: dict[str, dict[str, str]] = {
    "4-4-2": {"LM": "LW", "RM": "RW", "ST1": "ST"},
    "4-3-3": {},
    "3-5-2": {"LWB": "LB", "RWB": "RB", "STL": "ST"},
}
_EXTRA_TACTICAL_SLOTS = (
    TacticSlot("CB", SlotRole.CENTER_BACK),
    TacticSlot("ST2", SlotRole.STRIKER),
    TacticSlot("STR", SlotRole.STRIKER),
)


@dataclass(frozen=True)
class CareerTeamSheet:
    sheet: TeamSheet
    slot_bindings: tuple[tuple[str, PlayerId], ...]
    local_positions: tuple[tuple[str, Position2D], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.sheet, TeamSheet):
            raise TypeError("career team-sheet bridge requires a TeamSheet")
        if not isinstance(self.slot_bindings, tuple) or not isinstance(self.local_positions, tuple):
            raise TypeError("career matchday bindings and positions must be immutable")


def formation_slots(shape: str) -> tuple[str, ...]:
    try:
        slots = FORMATION_SLOT_IDS[shape]
    except KeyError as exc:
        raise ValueError(f"unsupported spatial career formation {shape!r}") from exc
    if len(content.FORMATIONS.get(shape, ())) != len(slots):
        raise ValueError(f"formation {shape!r} has no complete spatial slot mapping")
    return slots


def tactical_slot_bindings(shape: str,
                           formation_bindings: Mapping[str, PlayerId]) -> dict[str, PlayerId]:
    """Map real formation slots onto the compatible P06 role vocabulary.

    Additional centre-backs and strikers retain their own slot IDs. No
    duplicate player is assigned a second tactical identity.
    """
    slots = formation_slots(shape)
    if set(formation_bindings) != set(slots):
        raise ValueError("tactical bindings must cover the selected formation exactly")
    aliases = _TACTICAL_SLOT_ALIASES[shape]
    output = {aliases.get(slot, slot): player_id
              for slot, player_id in formation_bindings.items()}
    if len(output) != len(formation_bindings):
        raise ValueError("formation maps multiple players to one tactical slot")
    return output


def default_formation_positions(shape: str) -> dict[str, Position2D]:
    formation_slots(shape)
    return dict(_SLOT_POSITIONS[shape])


def legal_formation_positions(
    team_id: str,
    positions: Mapping[str, Position2D],
    *,
    pitch: Pitch = Pitch(),
    kickoff_team_id: str = "home",
) -> dict[str, Position2D]:
    """Project local-half placements into legal kickoff positions.

    The editor and match use this same projection, so a saved dot never jumps
    into the centre circle when the engine validates the opening restart.
    Coordinates are stored in the team's own attacking-left-to-right frame.
    """
    if team_id not in ("home", "away") or kickoff_team_id not in ("home", "away"):
        raise ValueError("formation placement requires known match sides")
    if set(positions) - set(SLOT_ROLES):
        raise ValueError("formation placement contains an unknown slot")
    centre_x = pitch.length_m / 2.0
    centre_y = pitch.width_m / 2.0
    clearance = MATCHDAY_RULES.restart_clearance_m + 0.1
    local_limit = max(0.0, centre_x - 0.5)
    output: dict[str, Position2D] = {}
    for slot, raw in positions.items():
        if not isinstance(raw, Position2D):
            raise TypeError("formation positions must be pitch coordinates")
        local = Position2D(
            min(local_limit, max(0.0, raw.x_m)),
            min(pitch.width_m, max(0.0, raw.y_m)),
        )
        world_x = local.x_m if team_id == "home" else pitch.length_m - local.x_m
        world_y = local.y_m
        is_kicker = (team_id == kickoff_team_id
                     and slot in set(CENTER_KICKER_SLOTS.values()))
        if is_kicker:
            world_x, world_y = centre_x, centre_y
        elif math.hypot(world_x - centre_x, world_y - centre_y) < clearance:
            # Moving along the length axis preserves the user's chosen lane
            # while keeping the opening circle clear for either team.
            world_x = (centre_x - clearance if team_id == "home"
                       else centre_x + clearance)
        local_x = world_x if team_id == "home" else pitch.length_m - world_x
        output[slot] = Position2D(local_x, world_y)
    return output


def legacy_profile(player: Mapping[str, Any], club_id: str,
                   role: PrimaryRole | None = None) -> PlayerProfile:
    """Map career ratings to the P02 profile contract with explicit provenance.

    The pace-to-metres conversion is a presentation/compatibility estimate for
    the new engine. It is deliberately versioned and must not be presented as
    tracking or laboratory measurement. Unrecorded action habits use neutral
    values instead of role-based bonuses.
    """
    player_id = PlayerId(str(player.get("id", "")))
    if not player_id or not club_id:
        raise ValueError("legacy player conversion requires stable player and club IDs")

    def rating(name: str, fallback: int = 50) -> float:
        raw = player.get(name, fallback)
        if type(raw) not in (int, float) or not math.isfinite(raw):
            raise ValueError(f"legacy {name} value must be finite")
        return max(0.0, min(100.0, float(raw))) / 100.0

    selected_role = role or {
        "GK": PrimaryRole.GOALKEEPER,
        "DEF": PrimaryRole.CENTER_BACK,
        "MID": PrimaryRole.CENTRAL_MIDFIELDER,
        "WNG": PrimaryRole.WIDE_FORWARD,
        "FWD": PrimaryRole.STRIKER,
    }.get(str(player.get("position", "MID")), PrimaryRole.CENTRAL_MIDFIELDER)

    passing = rating("passing")
    first_touch = rating("first_touch", int(player.get("technique", 50)))
    technique = rating("technique", int(player.get("first_touch", 50)))
    positioning = rating("positioning", int(player.get("defending", 50)))
    decisions = rating("decisions", 50)
    pace = rating("pace")
    aerial = rating("aerial", int(player.get("defending", 50)))
    vision = rating("vision", int(player.get("passing", 50)))
    work_rate = rating("work_rate", int(player.get("stamina", 50)))
    finishing = rating("finishing")
    goalkeeper = selected_role is PrimaryRole.GOALKEEPER
    kicking = rating("kicking", int(player.get("passing", 50)))
    reflexes = rating("reflexes", int(player.get("defending", 50)))
    handling = rating("handling", int(player.get("defending", 50)))

    values = {
        "scanning": vision,
        "anticipation": positioning,
        "decision_quality": decisions,
        "response_speed": pace,
        "receiving": first_touch,
        "first_touch": first_touch,
        "short_passing": passing,
        "long_passing": passing,
        "distribution": kicking if goalkeeper else passing,
        "crossing": technique,
        "ball_carrying": technique,
        "finishing": finishing,
        "aerial_execution": aerial,
        "aerial_timing": aerial,
        "jump_timing": aerial,
        "defensive_positioning": positioning,
        "pressing_judgment": decisions,
        "communication": work_rate,
        "adaptability": decisions,
        "gk_reaction": reflexes,
        "gk_handling": handling,
        "gk_claiming": handling,
        "gk_one_v_one": reflexes,
        "gk_sweeping": positioning,
        "gk_distribution": kicking,
    }
    capabilities = CapabilitySnapshot(
        player_id,
        version=1,
        capabilities=tuple(
            Capability(name, value, PROFILE_PROVENANCE)
            for name, value in sorted(values.items())
        ),
        measurements=(
            Measurement("maximum_speed", 5.2 + pace * 4.2, "m/s", PROFILE_PROVENANCE),
            Measurement("acceleration", 3.0 + pace * 4.0, "m/s^2", PROFILE_PROVENANCE),
        ),
        provenance=PROFILE_MAPPING_VERSION,
    )
    readiness_value = rating("fitness", 90)
    readiness = ReadinessSnapshot(
        player_id,
        WorldDate(date(2026, 1, 1)),
        readiness_value,
        0.0,
        PROFILE_PROVENANCE,
    )
    tendencies = ActionTendencies(
        player_id,
        tuple(ActionTendency(name, 0.5, PROFILE_PROVENANCE) for name in (
            "risk_tolerance", "early_release", "carry_inside", "run_in_behind",
            "press_commitment", "improvisation",
        )),
    )
    return PlayerProfile(
        player_id=player_id,
        display_name=str(player.get("name", "Unknown player")),
        club_id=club_id,
        primary_role=selected_role,
        identity=PlayerIdentity(player_id),
        capabilities=capabilities,
        preference=PlayerPreference(player_id, PreferredFoot.UNKNOWN),
        readiness=readiness,
        tendencies=tendencies,
        provenance=PROFILE_PROVENANCE,
    )


def _shape_configuration(career: Mapping[str, Any], club_id: str, shape: str,
                         lineup_ids: tuple[str, ...]) -> tuple[dict[str, Position2D], str]:
    club = career.get("clubs", {}).get(club_id)
    saved = club.get("spatial_formation_v1") if isinstance(club, Mapping) else None
    defaults = default_formation_positions(shape)
    if (isinstance(saved, Mapping) and saved.get("schema_version") == 1
            and saved.get("shape") == shape and isinstance(saved.get("positions"), Mapping)):
        positions = dict(defaults)
        for slot, player_id in zip(formation_slots(shape), lineup_ids):
            raw = saved["positions"].get(player_id)
            if (isinstance(raw, (list, tuple)) and len(raw) == 2
                    and all(type(item) in (int, float) and math.isfinite(item) for item in raw)):
                positions[slot] = Position2D(float(raw[0]), float(raw[1]))
        style_id = str(saved.get("style_id", "possession"))
    else:
        positions = defaults
        style_id = "possession"
    if style_id not in {key for key, _label in MATCHDAY_PROFILE_STYLES}:
        style_id = "possession"
    return positions, style_id


def build_team_sheet(
    career: Mapping[str, Any],
    club_id: str,
    team_id: str,
    lineup_ids: tuple[str, ...] | list[str],
    *,
    shape: str | None = None,
    pitch: Pitch = Pitch(),
    prepared_profiles: Mapping[str, PlayerProfile] | None = None,
    unavailable_profiles: tuple[PlayerId, ...] | list[PlayerId] = (),
) -> CareerTeamSheet:
    """Build a validated career sheet; the slot map is retained for tactics."""
    if team_id not in ("home", "away"):
        raise ValueError("career matchday team must be home or away")
    club = career.get("clubs", {}).get(club_id)
    players = career.get("players")
    if not isinstance(club, Mapping) or not isinstance(players, Mapping):
        raise ValueError("career matchday needs registered clubs and players")
    selected_shape = shape or str(club.get("tactics", {}).get("in_shape", "4-3-3"))
    slots = formation_slots(selected_shape)
    starters = tuple(map(str, lineup_ids))
    if len(starters) != len(slots) or len(set(starters)) != len(starters):
        raise ValueError("career formation must bind exactly one player to every starting slot")
    local_positions, style_id = _shape_configuration(career, club_id, selected_shape, starters)
    local_positions = legal_formation_positions(team_id, local_positions, pitch=pitch)
    if prepared_profiles is None:
        prepared_profiles = {}

    def profile_for(player_id: str, role: PrimaryRole) -> PlayerProfile:
        prepared = prepared_profiles.get(player_id)
        if prepared is not None:
            if prepared.player_id != PlayerId(player_id):
                raise ValueError("prepared player profile key and identity disagree")
            return prepared
        legacy = players.get(player_id)
        if not isinstance(legacy, Mapping) or legacy.get("club") != club_id:
            raise ValueError(f"career player {player_id!r} is not registered at {club_id}")
        return legacy_profile(legacy, club_id, role)

    slot_bindings: list[tuple[str, PlayerId]] = []
    starter_states: list[PlayerState] = []
    used_profiles: dict[str, PlayerProfile] = {}
    unavailable_profile_ids = {str(item) for item in unavailable_profiles}
    for slot_id, player_id in zip(slots, starters):
        if player_id in unavailable_profile_ids:
            raise ValueError(f"career player {player_id!r} is unavailable under preparation rules")
        profile = profile_for(player_id, SLOT_ROLES[slot_id])
        legacy = players[player_id]
        if int(legacy.get("injury_until_round", -1)) > int(career.get("career_week", career.get("round", 0))):
            raise ValueError(f"{profile.display_name} is unavailable through injury")
        local = local_positions[slot_id]
        position = Position2D(local.x_m, local.y_m)
        if team_id == "away":
            position = Position2D(pitch.length_m - local.x_m, local.y_m)
        motion = PlayerMotion(
            profile.player_id,
            team_id,
            position,
            0.0,
            0.0,
            0.0 if team_id == "home" else math.pi,
            limits_from_profile(profile),
        )
        starter_states.append(PlayerState(profile, motion, team_id))
        slot_bindings.append((slot_id, profile.player_id))
        used_profiles[player_id] = profile

    roster_ids = tuple(str(item) for item in club.get("roster", ()))
    selected_set = set(starters)
    unavailable_values = [
        PlayerId(player_id) for player_id in roster_ids
        if isinstance(players.get(player_id), Mapping)
        and int(players[player_id].get("injury_until_round", -1))
            > int(career.get("career_week", career.get("round", 0)))
    ]
    unavailable_values.extend(
        PlayerId(player_id) for player_id in sorted(unavailable_profile_ids)
        if player_id in roster_ids
    )
    unavailable = tuple(dict.fromkeys(unavailable_values))
    bench: list[PlayerProfile] = []
    for player_id in roster_ids:
        if player_id in selected_set or player_id in {str(value) for value in unavailable}:
            continue
        legacy = players.get(player_id)
        if not isinstance(legacy, Mapping) or legacy.get("club") != club_id:
            continue
        bench_role = {
            "GK": PrimaryRole.GOALKEEPER,
            "DEF": PrimaryRole.CENTER_BACK,
            "MID": PrimaryRole.CENTRAL_MIDFIELDER,
            "WNG": PrimaryRole.WIDE_FORWARD,
            "FWD": PrimaryRole.STRIKER,
        }.get(str(legacy.get("position", "MID")), PrimaryRole.CENTRAL_MIDFIELDER)
        profile = profile_for(player_id, bench_role)
        bench.append(profile)
        used_profiles[player_id] = profile
    sheet = TeamSheet(
        team_id,
        tuple(starter_states),
        tuple(bench[:7]),
        unavailable,
    )
    # The caller persists these exact local coordinates before it starts the
    # match, so both the editor and the match checkpoint name the same XI.
    active_local = tuple((player_id, local_positions[slot_id])
                         for slot_id, player_id in zip(slots, starters))
    return CareerTeamSheet(sheet, tuple(slot_bindings), active_local)


def _stateless_phase(plan: PhasePlan) -> PhasePlan:
    """Keep authored movement/relationships while excluding temporal scripts.

    Career matchday checkpoints currently persist MatchState, not the mutable
    routine/pressing clocks. Those temporal components stay in Tactical Lab
    until the career-save contract stores their full runtime state.
    """
    return replace(plan, pressing=(), marking=(), conditional_rules=(), routines=())


def career_tactic(style_id: str) -> TacticDefinition:
    templates = {
        "possession": POSITIONAL_POSSESSION,
        "press": MAN_ORIENTED_PRESS,
        "compact": COMPACT_BLOCK_COUNTER,
        "wide": WIDE_ISOLATION,
        "fluid": FLUID_COMBINATION,
        "vertical": VERTICAL_COMBINATION,
    }
    try:
        selected = templates[style_id]
    except KeyError as exc:
        raise ValueError(f"unknown career matchday style {style_id!r}") from exc

    by_phase: dict[TacticalPhase, PhasePlan] = {}
    # Base phases provide safe defaults. The selected style then replaces its
    # own phase, so a wide or fluid plan is not silently shadowed by possession.
    sources = (POSITIONAL_POSSESSION, COMPACT_BLOCK_COUNTER,
               DIRECT_SECOND_BALL, VERTICAL_COMBINATION, selected)
    for definition in sources:
        for phase in definition.phases:
            by_phase[phase.phase] = _stateless_phase(phase)
    tactic_id = new_tactic_id("p17-career-matchday-v1", style_id)
    return TacticDefinition(
        tactic_id,
        f"{dict(MATCHDAY_PROFILE_STYLES)[style_id]} · career matchday",
        SLOTS + _EXTRA_TACTICAL_SLOTS,
        tuple(by_phase[phase] for phase in sorted(by_phase, key=lambda item: item.value)),
    )


def tactical_runtimes(session: Any, career: Mapping[str, Any]) -> dict[str, TacticalRuntime]:
    """Rebuild stateless tactical plans around the saved kickoff shapes."""
    match: MatchState = session.match
    binding = session.binding
    clubs = career.get("clubs")
    if not isinstance(clubs, Mapping) or match.input_snapshot is None:
        return {}
    team_clubs = {
        "home": str(binding.home_club_id),
        "away": str(binding.away_club_id),
    }
    current_slot_players: dict[str, dict[str, PlayerId]] = {}
    shape_positions: dict[str, dict[str, Position2D]] = {}
    for team_id, club_id in team_clubs.items():
        club = clubs.get(club_id)
        saved = club.get("spatial_formation_v1") if isinstance(club, Mapping) else None
        if not isinstance(saved, Mapping):
            return {}
        original = dict(saved.get("slot_bindings", {}))
        formation_shape = str(saved.get("shape", "4-3-3"))
        formation_bindings = {
            str(slot): PlayerId(str(player_id)) for slot, player_id in original.items()
        }
        for event in match.events:
            if event.kind != "substitution" or event.payload.get("team_id") != team_id:
                continue
            outgoing = str(event.payload.get("outgoing_player_id", ""))
            incoming = str(event.payload.get("incoming_player_id", ""))
            for slot_id, player_id in tuple(formation_bindings.items()):
                if str(player_id) == outgoing:
                    formation_bindings[slot_id] = PlayerId(incoming)
        slots = tactical_slot_bindings(formation_shape, formation_bindings)
        active = match.play.players
        slots = {slot: player_id for slot, player_id in slots.items()
                 if player_id in active and active[player_id].team_id == team_id}
        current_slot_players[team_id] = slots
        sheet = (match.input_snapshot.home_sheet if team_id == "home"
                 else match.input_snapshot.away_sheet)
        original_positions = {str(item.profile.player_id): item.motion.position
                              for item in sheet.starters}
        shape_positions[team_id] = {
            slot: original_positions[str(player_id)]
            for slot, player_id in tactical_slot_bindings(
                formation_shape,
                {str(key): PlayerId(str(value)) for key, value in original.items()},
            ).items()
            if str(player_id) in original_positions
        }

    runtimes: dict[str, TacticalRuntime] = {}
    for team_id, club_id in team_clubs.items():
        club = clubs[club_id]
        saved = club["spatial_formation_v1"]
        style_id = str(saved.get("style_id", "possession"))
        own = current_slot_players[team_id]
        other_team = "away" if team_id == "home" else "home"
        opposition = current_slot_players[other_team]
        opponent_references = {
            "opponent:deep_playmaker": opposition.get("DM"),
            "opponent:center_back_left": opposition.get("LCB"),
            "opponent:pivot": opposition.get("DM"),
            "opponent:last_line": opposition.get("ST"),
            "opponent:throw_receiver": opposition.get("LW"),
            "deep_touchline_runner": opposition.get("LW"),
        }
        opponent_references = {key: value for key, value in opponent_references.items()
                               if value is not None}
        tactic = career_tactic(style_id)
        runtime = TacticalRuntime.bind(
            match.play, tactic, team_id, own,
            opponent_slots=opponent_references,
        )
        runtime.shape_positions = {
            slot: position for slot, position in shape_positions[team_id].items()
            if slot in own
        }
        runtime.last_seen_event_count = len(match.events)
        runtimes[team_id] = runtime
    return runtimes


__all__ = [
    "CareerTeamSheet", "FORMATION_SLOT_IDS", "MATCHDAY_PROFILE_STYLES",
    "MATCHDAY_RULES", "PROFILE_MAPPING_VERSION", "build_team_sheet",
    "career_tactic", "default_formation_positions", "formation_slots",
    "legacy_profile", "legal_formation_positions", "tactical_runtimes",
]
