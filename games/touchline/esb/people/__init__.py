"""Person/capability records and synthetic proof-roster validation."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from games.touchline.esb.ids import ClubId, PlayerId, validate_id
from games.touchline.esb.model import (
    CapabilitySnapshot,
    DataProvenance,
    Measurement,
    PlayerIdentity,
)
from games.touchline.esb.time import WorldDate


class PrimaryRole(str, Enum):
    GOALKEEPER = "goalkeeper"
    CENTER_BACK = "center_back"
    FULLBACK = "fullback"
    DEFENSIVE_MIDFIELDER = "defensive_midfielder"
    CENTRAL_MIDFIELDER = "central_midfielder"
    WIDE_FORWARD = "wide_forward"
    STRIKER = "striker"


class PreferredFoot(str, Enum):
    LEFT = "left"
    RIGHT = "right"
    BOTH = "both"
    UNKNOWN = "unknown"


SUPPORTED_CAPABILITIES = frozenset({
    "scanning", "anticipation", "decision_quality", "response_speed",
    "receiving", "first_touch", "short_passing", "long_passing", "distribution",
    "crossing", "ball_carrying", "finishing", "aerial_execution", "aerial_timing",
    "jump_timing", "defensive_positioning", "pressing_judgment", "communication",
    "adaptability", "gk_reaction", "gk_handling", "gk_claiming", "gk_one_v_one",
    "gk_sweeping", "gk_distribution",
})
REQUIRED_OUTFIELD_CAPABILITIES = frozenset({
    "scanning", "anticipation", "decision_quality", "receiving", "first_touch",
    "short_passing", "long_passing", "distribution",
})
REQUIRED_GOALKEEPER_CAPABILITIES = frozenset({
    "gk_reaction", "gk_handling", "gk_claiming", "gk_one_v_one", "gk_sweeping", "gk_distribution",
})
SUPPORTED_TENDENCIES = (
    "risk_tolerance", "early_release", "carry_inside", "run_in_behind",
    "press_commitment", "improvisation",
)


@dataclass(frozen=True)
class PlayerPreference:
    player_id: PlayerId
    preferred_foot: PreferredFoot = PreferredFoot.UNKNOWN
    provenance: DataProvenance | None = None

    def __post_init__(self) -> None:
        validate_id(self.player_id, kind="player ID")
        if not isinstance(self.preferred_foot, PreferredFoot):
            raise TypeError("preferred foot must use a known preference value")
        if self.preferred_foot is PreferredFoot.UNKNOWN:
            if self.provenance is not None:
                raise ValueError("unknown preference cannot claim an authored or observed preference")
        elif self.provenance is None:
            raise ValueError("known preference requires provenance")
        elif not isinstance(self.provenance, DataProvenance):
            raise TypeError("preference provenance must use DataProvenance")


@dataclass(frozen=True)
class ActionTendency:
    name: str
    value: float
    provenance: DataProvenance

    def __post_init__(self) -> None:
        if self.name not in SUPPORTED_TENDENCIES:
            raise ValueError(f"unsupported action tendency: {self.name}")
        if type(self.value) not in (int, float) or not math.isfinite(self.value) or not 0.0 <= self.value <= 1.0:
            raise ValueError("action tendency must be normalized to [0, 1]")
        if not isinstance(self.provenance, DataProvenance):
            raise TypeError("action tendency provenance is required")


@dataclass(frozen=True)
class ActionTendencies:
    player_id: PlayerId
    values: tuple[ActionTendency, ...]

    def __post_init__(self) -> None:
        validate_id(self.player_id, kind="player ID")
        if not isinstance(self.values, tuple):
            raise TypeError("action tendencies must be an immutable tuple")
        names = [value.name for value in self.values]
        if len(names) != len(set(names)):
            raise ValueError("action tendencies cannot repeat a dimension")


@dataclass(frozen=True)
class ReadinessSnapshot:
    player_id: PlayerId
    sampled_on: WorldDate
    match_readiness: float
    accumulated_fatigue: float
    provenance: DataProvenance

    def __post_init__(self) -> None:
        validate_id(self.player_id, kind="player ID")
        if not isinstance(self.sampled_on, WorldDate):
            raise TypeError("readiness requires an explicit sample date")
        for label, value in (
            ("match readiness", self.match_readiness),
            ("accumulated fatigue", self.accumulated_fatigue),
        ):
            if type(value) not in (int, float) or not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"{label} must be normalized to [0, 1]")
        if not isinstance(self.provenance, DataProvenance):
            raise TypeError("readiness provenance is required")


@dataclass(frozen=True)
class PlayerProfile:
    """A football profile; identity, ability, preference, readiness and tendencies stay separate."""

    player_id: PlayerId
    display_name: str
    club_id: ClubId
    primary_role: PrimaryRole
    identity: PlayerIdentity
    capabilities: CapabilitySnapshot
    preference: PlayerPreference
    readiness: ReadinessSnapshot
    tendencies: ActionTendencies
    provenance: DataProvenance

    def __post_init__(self) -> None:
        validate_id(self.player_id, kind="player ID")
        validate_id(self.club_id, kind="club ID")
        if not isinstance(self.display_name, str) or not self.display_name.strip():
            raise ValueError("player display name must be non-empty")
        if not isinstance(self.primary_role, PrimaryRole):
            raise TypeError("player requires a supported primary role")
        if not isinstance(self.identity, PlayerIdentity) or not isinstance(self.capabilities, CapabilitySnapshot):
            raise TypeError("player profile requires identity and capability records")
        if not isinstance(self.preference, PlayerPreference) or not isinstance(self.readiness, ReadinessSnapshot):
            raise TypeError("player profile requires preference and readiness records")
        if not isinstance(self.tendencies, ActionTendencies):
            raise TypeError("player profile requires an action-tendency record")
        for record in (self.identity, self.capabilities, self.preference, self.readiness, self.tendencies):
            if record.player_id != self.player_id:
                raise ValueError("player profile components must share the same player ID")
        if not isinstance(self.provenance, DataProvenance):
            raise TypeError("player profile provenance is required")


@dataclass(frozen=True)
class ProfileIssue:
    code: str
    message: str


@dataclass(frozen=True)
class ProofSquad:
    club_id: ClubId
    name: str
    players: tuple[PlayerProfile, ...]

    def __post_init__(self) -> None:
        validate_id(self.club_id, kind="club ID")
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("squad name must be non-empty")
        if not isinstance(self.players, tuple):
            raise TypeError("squad profiles must be immutable tuples")
        if any(not isinstance(player, PlayerProfile) for player in self.players):
            raise TypeError("squad entries must be PlayerProfile records")


def validate_profile(profile: PlayerProfile) -> tuple[ProfileIssue, ...]:
    issues: list[ProfileIssue] = []
    values = {item.name: item for item in profile.capabilities.capabilities}
    allowed = SUPPORTED_CAPABILITIES
    for name in sorted(set(values) - allowed):
        issues.append(ProfileIssue("unsupported_capability", f"{name} is not in the P02 capability registry"))
    required = set(REQUIRED_OUTFIELD_CAPABILITIES)
    if profile.primary_role is PrimaryRole.GOALKEEPER:
        required.update(REQUIRED_GOALKEEPER_CAPABILITIES)
    for name in sorted(required - set(values)):
        issues.append(ProfileIssue("missing_capability", f"{profile.primary_role.value} requires {name}"))
    for capability in profile.capabilities.capabilities:
        if capability.provenance is None:
            issues.append(ProfileIssue("missing_provenance", f"capability {capability.name} has no provenance"))
    for measurement in profile.identity.physical_facts + profile.capabilities.measurements:
        if measurement.provenance is None:
            issues.append(ProfileIssue("missing_provenance", f"measurement {measurement.name} has no provenance"))
    if profile.preference.preferred_foot is not PreferredFoot.UNKNOWN and profile.preference.provenance is None:
        issues.append(ProfileIssue("missing_provenance", "preferred foot has no provenance"))
    tendency_names = {item.name for item in profile.tendencies.values}
    for name in SUPPORTED_TENDENCIES:
        if name not in tendency_names:
            issues.append(ProfileIssue("missing_tendency", f"profile has no {name} tendency"))
    for tendency in profile.tendencies.values:
        if tendency.provenance is None:
            issues.append(ProfileIssue("missing_provenance", f"tendency {tendency.name} has no provenance"))
    return tuple(issues)


def validate_squad(squad: ProofSquad) -> tuple[ProfileIssue, ...]:
    issues: list[ProfileIssue] = []
    if len(squad.players) < 16:
        issues.append(ProfileIssue("insufficient_depth", "proof squad needs 16 players for an XI and substitutions"))
    player_ids = [profile.player_id for profile in squad.players]
    if len(player_ids) != len(set(player_ids)):
        issues.append(ProfileIssue("duplicate_player_id", "squad player IDs must be unique"))
    names = [profile.display_name.casefold() for profile in squad.players]
    if len(names) != len(set(names)):
        issues.append(ProfileIssue("duplicate_player_name", "squad display names must be unique"))
    role_counts = {role: sum(profile.primary_role is role for profile in squad.players) for role in PrimaryRole}
    minimums = {
        PrimaryRole.GOALKEEPER: 2,
        PrimaryRole.CENTER_BACK: 2,
        PrimaryRole.FULLBACK: 2,
        PrimaryRole.DEFENSIVE_MIDFIELDER: 1,
        PrimaryRole.CENTRAL_MIDFIELDER: 2,
        PrimaryRole.WIDE_FORWARD: 2,
        PrimaryRole.STRIKER: 1,
    }
    for role, count in minimums.items():
        if role_counts[role] < count:
            issues.append(ProfileIssue("role_depth", f"squad needs at least {count} {role.value} players"))
    for profile in squad.players:
        if profile.club_id != squad.club_id:
            issues.append(ProfileIssue("wrong_club", f"{profile.display_name} belongs to another club"))
        issues.extend(validate_profile(profile))
    return tuple(issues)
