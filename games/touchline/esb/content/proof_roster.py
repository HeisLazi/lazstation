"""Small, wholly fictional P02 roster with explicit units and provenance.

All figures below are authored scenario inputs, not measurements of real people,
legacy save facts, calibrated ratings, or predictions of player potential. Role
baselines reduce repetition; each row supplies independent person-level values.
"""

from __future__ import annotations

from datetime import date

from games.touchline.esb.ids import new_club_id, new_player_id
from games.touchline.esb.model import (
    Capability,
    CapabilitySnapshot,
    DataProvenance,
    Measurement,
    PlayerIdentity,
    ProvenanceKind,
)
from games.touchline.esb.people import (
    ActionTendency,
    ActionTendencies,
    PreferredFoot,
    PlayerPreference,
    PlayerProfile,
    PrimaryRole,
    ProofSquad,
    ReadinessSnapshot,
    validate_squad,
)
from games.touchline.esb.time import WorldDate

ROSTER_VERSION = 1
AUTHORED = DataProvenance(ProvenanceKind.AUTHORED, "p02-fictional-proof-roster-v1")
AUTHORED_ON = WorldDate(date(2026, 9, 24))

_GENERAL_CAPABILITIES = {
    "scanning": 0.50,
    "anticipation": 0.50,
    "decision_quality": 0.50,
    "response_speed": 0.50,
    "receiving": 0.50,
    "first_touch": 0.50,
    "short_passing": 0.50,
    "long_passing": 0.50,
    "distribution": 0.50,
    "crossing": 0.50,
    "ball_carrying": 0.50,
    "finishing": 0.50,
    "aerial_execution": 0.50,
    "aerial_timing": 0.50,
    "jump_timing": 0.50,
    "defensive_positioning": 0.50,
    "pressing_judgment": 0.50,
    "communication": 0.50,
    "adaptability": 0.50,
}

_ROLE_BASES = {
    PrimaryRole.GOALKEEPER: {"receiving": 0.54, "distribution": 0.62, "aerial_execution": 0.55},
    PrimaryRole.CENTER_BACK: {"anticipation": 0.61, "long_passing": 0.59, "aerial_execution": 0.69, "defensive_positioning": 0.70},
    PrimaryRole.FULLBACK: {"receiving": 0.59, "crossing": 0.57, "ball_carrying": 0.59, "pressing_judgment": 0.59},
    PrimaryRole.DEFENSIVE_MIDFIELDER: {"scanning": 0.60, "anticipation": 0.62, "short_passing": 0.63, "defensive_positioning": 0.66},
    PrimaryRole.CENTRAL_MIDFIELDER: {"scanning": 0.62, "receiving": 0.63, "first_touch": 0.63, "short_passing": 0.65},
    PrimaryRole.WIDE_FORWARD: {"receiving": 0.62, "ball_carrying": 0.65, "crossing": 0.61, "finishing": 0.57},
    PrimaryRole.STRIKER: {"anticipation": 0.60, "receiving": 0.61, "finishing": 0.68, "aerial_execution": 0.59},
}

_TENDENCY_BASES = {
    PrimaryRole.GOALKEEPER: {"risk_tolerance": 0.38, "early_release": 0.48, "carry_inside": 0.08, "run_in_behind": 0.02, "press_commitment": 0.25, "improvisation": 0.37},
    PrimaryRole.CENTER_BACK: {"risk_tolerance": 0.42, "early_release": 0.54, "carry_inside": 0.20, "run_in_behind": 0.06, "press_commitment": 0.55, "improvisation": 0.45},
    PrimaryRole.FULLBACK: {"risk_tolerance": 0.54, "early_release": 0.49, "carry_inside": 0.35, "run_in_behind": 0.48, "press_commitment": 0.63, "improvisation": 0.52},
    PrimaryRole.DEFENSIVE_MIDFIELDER: {"risk_tolerance": 0.43, "early_release": 0.57, "carry_inside": 0.30, "run_in_behind": 0.20, "press_commitment": 0.60, "improvisation": 0.42},
    PrimaryRole.CENTRAL_MIDFIELDER: {"risk_tolerance": 0.57, "early_release": 0.50, "carry_inside": 0.44, "run_in_behind": 0.34, "press_commitment": 0.53, "improvisation": 0.59},
    PrimaryRole.WIDE_FORWARD: {"risk_tolerance": 0.66, "early_release": 0.38, "carry_inside": 0.61, "run_in_behind": 0.70, "press_commitment": 0.64, "improvisation": 0.67},
    PrimaryRole.STRIKER: {"risk_tolerance": 0.61, "early_release": 0.42, "carry_inside": 0.36, "run_in_behind": 0.71, "press_commitment": 0.57, "improvisation": 0.56},
}


def _row(name, role, foot, height_m, mass_kg, speed_mps, acceleration_mps2,
         skills, habits, readiness, fatigue):
    return (name, role, foot, height_m, mass_kg, speed_mps, acceleration_mps2,
            skills, habits, readiness, fatigue)


# Rows are roster depth, not a starting XI sorted by an overall rating.
# role, foot, height (m), mass (kg), max-speed sample (m/s), acceleration
# (m/s^2), selected independent capability overrides, tendency overrides,
# readiness, and accumulated fatigue follow each fictional name.
_COAST_ROWS = (
    _row("Lena Orr", PrimaryRole.GOALKEEPER, PreferredFoot.RIGHT, 1.81, 72, 7.0, 4.4, {"anticipation": .67, "decision_quality": .62, "gk_reaction": .78, "gk_handling": .69, "gk_claiming": .74, "gk_one_v_one": .71, "gk_sweeping": .59, "gk_distribution": .72}, {"risk_tolerance": .35, "early_release": .69}, .88, .10),
    _row("Dara Vei", PrimaryRole.GOALKEEPER, PreferredFoot.LEFT, 1.87, 79, 6.6, 3.9, {"anticipation": .59, "decision_quality": .68, "gk_reaction": .70, "gk_handling": .78, "gk_claiming": .73, "gk_one_v_one": .66, "gk_sweeping": .52, "gk_distribution": .64}, {"risk_tolerance": .28, "early_release": .51}, .82, .16),
    _row("Miro Tane", PrimaryRole.CENTER_BACK, PreferredFoot.RIGHT, 1.88, 84, 7.5, 5.0, {"anticipation": .72, "decision_quality": .61, "receiving": .57, "distribution": .64, "aerial_execution": .76, "aerial_timing": .74}, {"risk_tolerance": .38, "press_commitment": .53}, .80, .17),
    _row("Nia Sol", PrimaryRole.CENTER_BACK, PreferredFoot.LEFT, 1.80, 75, 8.1, 5.6, {"anticipation": .66, "decision_quality": .70, "receiving": .67, "distribution": .72, "aerial_execution": .59, "aerial_timing": .57}, {"risk_tolerance": .52, "carry_inside": .34}, .76, .21),
    _row("Rafi Taal", PrimaryRole.CENTER_BACK, PreferredFoot.RIGHT, 1.92, 88, 7.2, 4.8, {"anticipation": .76, "decision_quality": .55, "receiving": .54, "distribution": .57, "aerial_execution": .83, "aerial_timing": .80}, {"risk_tolerance": .31, "press_commitment": .69}, .73, .26),
    _row("Tali Venn", PrimaryRole.FULLBACK, PreferredFoot.LEFT, 1.70, 64, 9.2, 6.8, {"anticipation": .61, "decision_quality": .63, "receiving": .67, "distribution": .63, "crossing": .72, "ball_carrying": .71}, {"carry_inside": .30, "run_in_behind": .68}, .86, .12),
    _row("Oren Pell", PrimaryRole.FULLBACK, PreferredFoot.RIGHT, 1.78, 71, 8.4, 6.2, {"anticipation": .67, "decision_quality": .59, "receiving": .60, "distribution": .68, "crossing": .61, "ball_carrying": .58}, {"carry_inside": .53, "run_in_behind": .46}, .71, .29),
    _row("Iri Kade", PrimaryRole.FULLBACK, PreferredFoot.BOTH, 1.73, 67, 8.8, 6.5, {"anticipation": .58, "decision_quality": .74, "receiving": .72, "distribution": .70, "crossing": .55, "ball_carrying": .65}, {"carry_inside": .66, "run_in_behind": .38}, .91, .08),
    _row("Mara Drift", PrimaryRole.DEFENSIVE_MIDFIELDER, PreferredFoot.RIGHT, 1.76, 73, 8.0, 5.8, {"scanning": .75, "anticipation": .78, "decision_quality": .72, "receiving": .64, "distribution": .76, "defensive_positioning": .74}, {"risk_tolerance": .36, "early_release": .67}, .84, .14),
    _row("Jalen Voss", PrimaryRole.DEFENSIVE_MIDFIELDER, PreferredFoot.LEFT, 1.82, 78, 7.7, 5.4, {"scanning": .61, "anticipation": .68, "decision_quality": .63, "receiving": .59, "distribution": .68, "defensive_positioning": .79}, {"risk_tolerance": .51, "carry_inside": .46}, .68, .33),
    # Matched execution profiles for PLAYER-01: only scanning, anticipation,
    # and decision quality differ; technique, physical facts, habits and state match.
    _row("Neri Vale", PrimaryRole.CENTRAL_MIDFIELDER, PreferredFoot.RIGHT, 1.77, 70, 8.2, 5.9, {"scanning": .39, "anticipation": .48, "decision_quality": .43, "receiving": .68, "first_touch": .72, "short_passing": .73, "long_passing": .64, "distribution": .70}, {"risk_tolerance": .55, "early_release": .48}, .79, .18),
    _row("Neri Sela", PrimaryRole.CENTRAL_MIDFIELDER, PreferredFoot.RIGHT, 1.77, 70, 8.2, 5.9, {"scanning": .84, "anticipation": .81, "decision_quality": .86, "receiving": .68, "first_touch": .72, "short_passing": .73, "long_passing": .64, "distribution": .70}, {"risk_tolerance": .55, "early_release": .48}, .79, .18),
    _row("Kesa Rook", PrimaryRole.WIDE_FORWARD, PreferredFoot.RIGHT, 1.67, 61, 9.6, 7.2, {"scanning": .64, "anticipation": .68, "decision_quality": .61, "receiving": .71, "crossing": .75, "ball_carrying": .82, "finishing": .62}, {"carry_inside": .75, "run_in_behind": .84}, .85, .13),
    _row("Eli Varo", PrimaryRole.WIDE_FORWARD, PreferredFoot.LEFT, 1.75, 68, 9.1, 6.6, {"scanning": .71, "anticipation": .74, "decision_quality": .72, "receiving": .65, "crossing": .66, "ball_carrying": .73, "finishing": .70}, {"carry_inside": .81, "run_in_behind": .57}, .72, .28),
    _row("Aro Kelm", PrimaryRole.STRIKER, PreferredFoot.RIGHT, 1.84, 79, 8.9, 6.4, {"anticipation": .76, "decision_quality": .69, "receiving": .70, "first_touch": .71, "finishing": .81, "aerial_execution": .66}, {"risk_tolerance": .72, "run_in_behind": .82}, .90, .09),
    _row("Pia Dune", PrimaryRole.STRIKER, PreferredFoot.LEFT, 1.72, 66, 9.3, 6.9, {"anticipation": .65, "decision_quality": .77, "receiving": .75, "first_touch": .79, "finishing": .71, "aerial_execution": .48}, {"risk_tolerance": .52, "early_release": .37}, .66, .35),
)

_RIDGE_ROWS = (
    _row("Omi Korr", PrimaryRole.GOALKEEPER, PreferredFoot.LEFT, 1.90, 86, 6.4, 3.8, {"anticipation": .71, "decision_quality": .59, "gk_reaction": .73, "gk_handling": .82, "gk_claiming": .78, "gk_one_v_one": .71, "gk_sweeping": .61, "gk_distribution": .55}, {"risk_tolerance": .26, "early_release": .42}, .80, .19),
    _row("Vela Tesh", PrimaryRole.GOALKEEPER, PreferredFoot.RIGHT, 1.78, 69, 7.4, 4.7, {"anticipation": .64, "decision_quality": .76, "gk_reaction": .82, "gk_handling": .65, "gk_claiming": .61, "gk_one_v_one": .78, "gk_sweeping": .77, "gk_distribution": .79}, {"risk_tolerance": .49, "early_release": .75}, .74, .24),
    _row("Boro Ilan", PrimaryRole.CENTER_BACK, PreferredFoot.RIGHT, 1.86, 82, 7.8, 5.2, {"anticipation": .69, "decision_quality": .73, "receiving": .63, "distribution": .70, "aerial_execution": .71, "aerial_timing": .74}, {"risk_tolerance": .58, "press_commitment": .64}, .83, .15),
    _row("Suri Pell", PrimaryRole.CENTER_BACK, PreferredFoot.LEFT, 1.91, 87, 7.1, 4.6, {"anticipation": .78, "decision_quality": .62, "receiving": .56, "distribution": .61, "aerial_execution": .81, "aerial_timing": .77}, {"risk_tolerance": .34, "press_commitment": .61}, .78, .22),
    _row("Evo Marr", PrimaryRole.CENTER_BACK, PreferredFoot.RIGHT, 1.79, 74, 8.4, 6.1, {"anticipation": .57, "decision_quality": .78, "receiving": .71, "distribution": .74, "aerial_execution": .55, "aerial_timing": .58}, {"risk_tolerance": .63, "carry_inside": .39}, .70, .30),
    _row("Rima Vale", PrimaryRole.FULLBACK, PreferredFoot.RIGHT, 1.72, 65, 9.4, 7.0, {"anticipation": .73, "decision_quality": .68, "receiving": .69, "distribution": .65, "crossing": .77, "ball_carrying": .70}, {"carry_inside": .27, "run_in_behind": .73}, .89, .11),
    _row("Tavo Aran", PrimaryRole.FULLBACK, PreferredFoot.LEFT, 1.80, 72, 8.2, 5.9, {"anticipation": .62, "decision_quality": .65, "receiving": .62, "distribution": .73, "crossing": .60, "ball_carrying": .56}, {"carry_inside": .61, "run_in_behind": .34}, .75, .25),
    _row("Mina Senn", PrimaryRole.FULLBACK, PreferredFoot.BOTH, 1.68, 62, 9.0, 6.7, {"anticipation": .66, "decision_quality": .80, "receiving": .74, "distribution": .68, "crossing": .57, "ball_carrying": .69}, {"carry_inside": .71, "run_in_behind": .49}, .69, .31),
    _row("Koro Drift", PrimaryRole.DEFENSIVE_MIDFIELDER, PreferredFoot.LEFT, 1.83, 79, 7.6, 5.3, {"scanning": .78, "anticipation": .81, "decision_quality": .77, "receiving": .70, "distribution": .73, "defensive_positioning": .80}, {"risk_tolerance": .41, "early_release": .76}, .81, .17),
    _row("Sena Rell", PrimaryRole.DEFENSIVE_MIDFIELDER, PreferredFoot.RIGHT, 1.75, 69, 8.5, 6.3, {"scanning": .65, "anticipation": .64, "decision_quality": .68, "receiving": .76, "distribution": .81, "defensive_positioning": .62}, {"risk_tolerance": .67, "carry_inside": .62}, .77, .23),
    _row("Una Malk", PrimaryRole.CENTRAL_MIDFIELDER, PreferredFoot.LEFT, 1.74, 67, 8.8, 6.5, {"scanning": .80, "anticipation": .74, "decision_quality": .82, "receiving": .78, "first_touch": .82, "short_passing": .84, "long_passing": .75, "distribution": .83}, {"risk_tolerance": .69, "early_release": .38}, .92, .07),
    _row("Dalen Orr", PrimaryRole.CENTRAL_MIDFIELDER, PreferredFoot.RIGHT, 1.89, 83, 7.6, 5.2, {"scanning": .59, "anticipation": .67, "decision_quality": .65, "receiving": .58, "first_touch": .64, "short_passing": .66, "long_passing": .79, "distribution": .74}, {"risk_tolerance": .43, "early_release": .70}, .65, .36),
    _row("Luma Nair", PrimaryRole.WIDE_FORWARD, PreferredFoot.LEFT, 1.70, 63, 9.7, 7.3, {"scanning": .70, "anticipation": .72, "decision_quality": .68, "receiving": .76, "crossing": .71, "ball_carrying": .86, "finishing": .68}, {"carry_inside": .58, "run_in_behind": .79}, .87, .12),
    _row("Ilan Quill", PrimaryRole.WIDE_FORWARD, PreferredFoot.RIGHT, 1.82, 75, 8.8, 6.3, {"scanning": .77, "anticipation": .65, "decision_quality": .75, "receiving": .67, "crossing": .62, "ball_carrying": .69, "finishing": .76}, {"carry_inside": .82, "run_in_behind": .54}, .73, .27),
    _row("Maren Kade", PrimaryRole.STRIKER, PreferredFoot.BOTH, 1.87, 81, 8.6, 6.0, {"anticipation": .81, "decision_quality": .73, "receiving": .68, "first_touch": .75, "finishing": .84, "aerial_execution": .78}, {"risk_tolerance": .67, "run_in_behind": .77}, .84, .16),
    _row("Jori Fen", PrimaryRole.STRIKER, PreferredFoot.RIGHT, 1.73, 68, 9.1, 6.8, {"anticipation": .68, "decision_quality": .80, "receiving": .78, "first_touch": .83, "finishing": .73, "aerial_execution": .53}, {"risk_tolerance": .55, "early_release": .36}, .70, .30),
)


def _build_squad(team_key: str, name: str, rows) -> ProofSquad:
    club_id = new_club_id("p02-proof-roster-v1", team_key)
    profiles = []
    for index, row in enumerate(rows, start=1):
        (display_name, role, foot, height_m, mass_kg, speed_mps, acceleration_mps2,
         skill_overrides, tendency_overrides, readiness, fatigue) = row
        player_id = new_player_id("p02-proof-roster-v1", team_key, index)
        skills = dict(_GENERAL_CAPABILITIES)
        skills.update(_ROLE_BASES[role])
        skills.update(skill_overrides)
        if role is PrimaryRole.GOALKEEPER:
            skills.update({
                "gk_reaction": .50, "gk_handling": .50, "gk_claiming": .50,
                "gk_one_v_one": .50, "gk_sweeping": .50, "gk_distribution": .50,
            })
        capability_values = tuple(
            Capability(name, value, provenance=AUTHORED)
            for name, value in sorted(skills.items())
        )
        measured_values = (
            Measurement("maximum_speed", speed_mps, "m/s", AUTHORED),
            Measurement("acceleration", acceleration_mps2, "m/s^2", AUTHORED),
        )
        capability_snapshot = CapabilitySnapshot(
            player_id=player_id,
            version=ROSTER_VERSION,
            capabilities=capability_values,
            measurements=measured_values,
            provenance="authored:p02-fictional-proof-roster-v1",
        )
        identity = PlayerIdentity(
            player_id=player_id,
            physical_facts=(
                Measurement("height", height_m, "m", AUTHORED),
                Measurement("mass", mass_kg, "kg", AUTHORED),
            ),
            history=(),
        )
        tendencies = dict(_TENDENCY_BASES[role])
        tendencies.update(tendency_overrides)
        action_tendencies = ActionTendencies(
            player_id,
            tuple(ActionTendency(key, value, AUTHORED) for key, value in sorted(tendencies.items())),
        )
        profiles.append(PlayerProfile(
            player_id=player_id,
            display_name=display_name,
            club_id=club_id,
            primary_role=role,
            identity=identity,
            capabilities=capability_snapshot,
            preference=PlayerPreference(player_id, foot, AUTHORED),
            readiness=ReadinessSnapshot(player_id, AUTHORED_ON, readiness, fatigue, AUTHORED),
            tendencies=action_tendencies,
            provenance=AUTHORED,
        ))
    return ProofSquad(club_id, name, tuple(profiles))


PROOF_SQUADS = (
    _build_squad("coast", "Coast United", _COAST_ROWS),
    _build_squad("ridge", "Ridge Athletic", _RIDGE_ROWS),
)

# Same technical/physical profile but different information and decision traits.
PLAYER_DECISION_PAIR = (PROOF_SQUADS[0].players[10], PROOF_SQUADS[0].players[11])


def validate_proof_rosters():
    return tuple((squad.name, validate_squad(squad)) for squad in PROOF_SQUADS)
