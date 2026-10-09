"""Small, ownership-specific domain records used by early packages."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum

from .ids import CareerId, ClubId, EventId, MatchId, PlayerId, validate_id
from .time import MatchClock, WorldDate


class HistoryKind(str, Enum):
    IDENTITY = "identity"
    EXPERIENCE = "experience"
    PREFERENCE = "preference"
    CULTURE = "culture"


class ProvenanceKind(str, Enum):
    AUTHORED = "authored"
    MEASURED = "measured"
    OBSERVED = "observed"
    INFERRED = "inferred"
    LEGACY_CONVERSION = "legacy_conversion"


@dataclass(frozen=True)
class DataProvenance:
    kind: ProvenanceKind
    source: str
    evidence_date: WorldDate | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ProvenanceKind):
            raise TypeError("provenance kind must be explicit")
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("data provenance requires an explicit source")
        if self.evidence_date is not None and not isinstance(self.evidence_date, WorldDate):
            raise TypeError("evidence date must be an explicit world date")
        if self.kind in (ProvenanceKind.MEASURED, ProvenanceKind.OBSERVED) and self.evidence_date is None:
            raise ValueError("measured and observed data require an evidence date")


@dataclass(frozen=True)
class Measurement:
    name: str
    value: float
    unit: str
    provenance: DataProvenance | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("measurement name must be non-empty")
        if type(self.value) not in (float, int) or not math.isfinite(self.value):
            raise ValueError("measurement value must be finite")
        if not isinstance(self.unit, str) or not self.unit.strip():
            raise ValueError("measurement unit must be explicit")
        if self.provenance is not None and not isinstance(self.provenance, DataProvenance):
            raise TypeError("measurement provenance must use DataProvenance")


@dataclass(frozen=True)
class Position2D:
    """Pitch-plane position in metres; pitch bounds are a later match rule."""

    x_m: float
    y_m: float

    def __post_init__(self) -> None:
        if type(self.x_m) not in (float, int) or type(self.y_m) not in (float, int):
            raise ValueError("position coordinates must be numeric metres")
        if not math.isfinite(self.x_m) or not math.isfinite(self.y_m):
            raise ValueError("position coordinates must be finite metres")


@dataclass(frozen=True)
class Money:
    """Signed integer minor units plus an explicit ISO-style currency code."""

    amount_minor: int
    currency_id: str

    def __post_init__(self) -> None:
        if type(self.amount_minor) is not int:
            raise TypeError("money must use integer minor units")
        if not isinstance(self.currency_id, str) or not re.fullmatch(r"[A-Z]{3}", self.currency_id):
            raise ValueError("currency_id must be a three-letter uppercase code")


@dataclass(frozen=True)
class Capability:
    name: str
    normalized_value: float
    provenance: DataProvenance | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("capability name must be non-empty")
        if type(self.normalized_value) not in (float, int):
            raise ValueError("normalized capability must be numeric")
        if not math.isfinite(self.normalized_value) or not 0.0 <= self.normalized_value <= 1.0:
            raise ValueError("normalized capability must be finite and in [0, 1]")
        if self.provenance is not None and not isinstance(self.provenance, DataProvenance):
            raise TypeError("capability provenance must use DataProvenance")


@dataclass(frozen=True)
class CapabilitySnapshot:
    player_id: PlayerId
    version: int
    capabilities: tuple[Capability, ...] = ()
    measurements: tuple[Measurement, ...] = ()
    provenance: str = "authored"

    def __post_init__(self) -> None:
        validate_id(self.player_id, kind="player ID")
        if not isinstance(self.capabilities, tuple) or not isinstance(self.measurements, tuple):
            raise TypeError("capability snapshots require immutable tuples")
        if type(self.version) is not int or self.version < 1:
            raise ValueError("capability snapshot version must be positive")
        if not isinstance(self.provenance, str) or not self.provenance.strip():
            raise ValueError("capability provenance must be explicit")
        names = [item.name for item in self.capabilities]
        if len(names) != len(set(names)):
            raise ValueError("capability names must be unique within a snapshot")
        measurement_names = [item.name for item in self.measurements]
        if len(measurement_names) != len(set(measurement_names)):
            raise ValueError("measurement names must be unique within a snapshot")


@dataclass(frozen=True)
class HistoryReference:
    kind: HistoryKind
    event_id: EventId
    recorded_on: WorldDate

    def __post_init__(self) -> None:
        validate_id(self.event_id, kind="event ID")
        if not isinstance(self.recorded_on, WorldDate):
            raise TypeError("history reference requires an explicit world date")


@dataclass(frozen=True)
class PlayerIdentity:
    """Identity facts and references; empty history means no history is known."""

    player_id: PlayerId
    birth_date: date | None = None
    birth_date_provenance: str | None = None
    physical_facts: tuple[Measurement, ...] = ()
    history: tuple[HistoryReference, ...] = ()

    def __post_init__(self) -> None:
        validate_id(self.player_id, kind="player ID")
        if isinstance(self.birth_date, datetime):
            raise TypeError("birth date must not contain a time of day")
        if self.birth_date is not None and not isinstance(self.birth_date, date):
            raise TypeError("birth date must be a calendar date")
        if not isinstance(self.physical_facts, tuple) or not isinstance(self.history, tuple):
            raise TypeError("identity facts and history references must be immutable tuples")
        if (self.birth_date is None) != (self.birth_date_provenance is None):
            raise ValueError("birth date and its provenance must be present together")
        if self.birth_date_provenance is not None and (
            not isinstance(self.birth_date_provenance, str) or not self.birth_date_provenance.strip()
        ):
            raise ValueError("birth date provenance must be non-empty")


@dataclass
class MatchState:
    """Mutable match-owned state; immutable player capability is snapshotted separately."""

    match_id: MatchId
    home_club_id: ClubId
    away_club_id: ClubId
    clock: MatchClock
    phase: str = "pre_match"
    home_score: int = 0
    away_score: int = 0
    revision: int = 0

    def __post_init__(self) -> None:
        validate_id(self.match_id, kind="match ID")
        validate_id(self.home_club_id, kind="club ID")
        validate_id(self.away_club_id, kind="club ID")
        if not isinstance(self.clock, MatchClock):
            raise TypeError("match state requires an explicit match clock")
        if self.home_club_id == self.away_club_id:
            raise ValueError("a match requires distinct clubs")
        if not self.phase.strip():
            raise ValueError("match phase must be explicit")
        if type(self.home_score) is not int or self.home_score < 0:
            raise ValueError("home score must be a non-negative integer")
        if type(self.away_score) is not int or self.away_score < 0:
            raise ValueError("away score must be a non-negative integer")
        if type(self.revision) is not int or self.revision < 0:
            raise ValueError("match revision must be a non-negative integer")


@dataclass
class CareerState:
    """Mutable career/world progression, not a projection of a match record."""

    career_id: CareerId
    club_id: ClubId
    world_date: WorldDate
    active_match_id: MatchId | None = None
    revision: int = 0

    def __post_init__(self) -> None:
        validate_id(self.career_id, kind="career ID")
        validate_id(self.club_id, kind="club ID")
        if not isinstance(self.world_date, WorldDate):
            raise TypeError("career state requires a calendar world date")
        if self.active_match_id is not None:
            validate_id(self.active_match_id, kind="match ID")
        if type(self.revision) is not int or self.revision < 0:
            raise ValueError("career revision must be a non-negative integer")


@dataclass(frozen=True)
class KnowledgeEntry:
    """One club's permitted observation, or an explicit reason it is unknown."""

    subject_id: str
    field: str
    value_json: str | None = None
    unavailable_reason: str | None = None
    source_event_ids: tuple[EventId, ...] = ()

    def __post_init__(self) -> None:
        validate_id(self.subject_id, kind="knowledge subject ID")
        if not isinstance(self.source_event_ids, tuple):
            raise TypeError("knowledge source references must be an immutable tuple")
        if not isinstance(self.field, str) or not self.field.strip():
            raise ValueError("knowledge field must be non-empty")
        if self.value_json is None:
            if self.unavailable_reason is None or not self.unavailable_reason.strip():
                raise ValueError("unknown knowledge requires an explicit coverage reason")
        else:
            if self.unavailable_reason is not None:
                raise ValueError("known values cannot also have an unavailable reason")
            try:
                parsed = json.loads(
                    self.value_json,
                    parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
                )
                json.dumps(parsed, allow_nan=False)
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError("knowledge value must be JSON") from exc
            if parsed is None or not isinstance(parsed, (str, int, float, bool, list, dict)):
                raise ValueError("known value must be an explicit JSON value")
        for event_id in self.source_event_ids:
            validate_id(event_id, kind="source event ID")


@dataclass(frozen=True)
class ClubKnowledge:
    club_id: ClubId
    as_of: WorldDate
    entries: tuple[KnowledgeEntry, ...] = ()
    schema_version: int = 1

    def __post_init__(self) -> None:
        validate_id(self.club_id, kind="club ID")
        if not isinstance(self.as_of, WorldDate):
            raise TypeError("club knowledge requires an as-of world date")
        if not isinstance(self.entries, tuple):
            raise TypeError("club knowledge entries must be an immutable tuple")
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("unsupported club-knowledge schema version")
        keys = [(item.subject_id, item.field) for item in self.entries]
        if len(keys) != len(set(keys)):
            raise ValueError("club knowledge cannot repeat a subject/field pair")
