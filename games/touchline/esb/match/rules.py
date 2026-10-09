"""Versioned and configurable competition rules for spatial matches (P05).

The standard profile is an authored simulation default, not a federation-law
claim. A match snapshots one immutable profile so later UI choices or edits
cannot change a result that is already in progress.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, fields, replace

from games.touchline.esb.ids import validate_id
from games.touchline.esb.serialization import SerializationError, dumps, loads


@dataclass(frozen=True)
class MatchRules:
    ruleset_id: str = "rules:proof-standard-v1"
    schema_version: int = 1
    tick_duration_ms: int = 20
    half_duration_ticks: int = 135_000
    stoppage_time_ticks: int = 0
    extra_time_duration_ticks: int = 0
    extra_time_stoppage_ticks: int = 0
    shootout_kicks_per_team: int = 5
    offside_enabled: bool = True
    fouls_enabled: bool = True
    foul_probability_per_challenge: float = 0.025
    advantage_enabled: bool = True
    advantage_window_ticks: int = 150
    cards_enabled: bool = True
    yellow_card_probability_per_foul: float = 0.08
    red_card_probability_per_foul: float = 0.004
    second_yellow_sends_off: bool = True
    substitutions_allowed: int = 5
    substitution_windows_allowed: int = 3
    maximum_players_per_team: int = 11
    minimum_players_to_continue: int = 7
    goalkeeper_required: bool = True
    restart_clearance_m: float = 9.15
    throw_in_clearance_m: float = 2.0
    goal_half_width_m: float = 3.66
    goal_height_m: float = 2.44
    goal_area_depth_m: float = 5.5
    goal_area_half_width_m: float = 9.16
    penalty_area_length_m: float = 16.5
    penalty_area_half_width_m: float = 20.15
    penalty_spot_distance_m: float = 11.0

    def __post_init__(self) -> None:
        validate_id(self.ruleset_id, kind="ruleset ID")
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("unsupported match-rules schema version")
        for label, value in (
            ("tick duration", self.tick_duration_ms),
            ("half duration", self.half_duration_ticks),
            ("maximum players", self.maximum_players_per_team),
            ("minimum players", self.minimum_players_to_continue),
        ):
            if type(value) is not int or value <= 0:
                raise ValueError(f"{label} must be a positive integer")
        for label, value in (
            ("stoppage duration", self.stoppage_time_ticks),
            ("extra-time duration", self.extra_time_duration_ticks),
            ("extra-time stoppage duration", self.extra_time_stoppage_ticks),
            ("shootout kicks", self.shootout_kicks_per_team),
            ("advantage window", self.advantage_window_ticks),
            ("substitution limit", self.substitutions_allowed),
            ("substitution windows", self.substitution_windows_allowed),
        ):
            if type(value) is not int or value < 0:
                raise ValueError(f"{label} must be a non-negative integer")
        if self.minimum_players_to_continue > self.maximum_players_per_team:
            raise ValueError("minimum players cannot exceed the maximum lineup")
        for name in ("offside_enabled", "fouls_enabled", "advantage_enabled", "cards_enabled",
                     "second_yellow_sends_off", "goalkeeper_required"):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be a boolean rule setting")
        for label, value in (
            ("foul probability", self.foul_probability_per_challenge),
            ("yellow-card probability", self.yellow_card_probability_per_foul),
            ("red-card probability", self.red_card_probability_per_foul),
        ):
            if type(value) not in (int, float) or not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"{label} must be finite and in [0, 1]")
        for label, value in (
            ("restart clearance", self.restart_clearance_m),
            ("throw-in clearance", self.throw_in_clearance_m),
            ("goal half-width", self.goal_half_width_m),
            ("goal height", self.goal_height_m),
            ("goal-area depth", self.goal_area_depth_m),
            ("goal-area half-width", self.goal_area_half_width_m),
            ("penalty-area length", self.penalty_area_length_m),
            ("penalty-area half-width", self.penalty_area_half_width_m),
            ("penalty spot distance", self.penalty_spot_distance_m),
        ):
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{label} must be positive finite metres")

    def with_overrides(self, ruleset_id: str, /, **overrides: object) -> MatchRules:
        """Return a validated custom profile; unknown settings fail explicitly."""
        allowed = {item.name for item in fields(self)} - {"ruleset_id", "schema_version"}
        unknown = set(overrides) - allowed
        if unknown:
            names = ", ".join(sorted(unknown))
            raise ValueError(f"unsupported match-rule setting(s): {names}")
        return replace(self, ruleset_id=ruleset_id, **overrides)

    def to_json(self) -> str:
        return dumps(self)

    @classmethod
    def from_json(cls, value: str) -> MatchRules:
        try:
            return loads(value, cls)
        except SerializationError as exc:
            raise ValueError(f"invalid serialized match rules: {exc}") from exc


STANDARD_RULES = MatchRules()


__all__ = ["MatchRules", "STANDARD_RULES"]
