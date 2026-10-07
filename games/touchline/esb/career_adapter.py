"""Explicit bridge between legacy career saves and spatial career matches.

The bridge is opt-in. A v2 career save stays on the legacy resolver unless a
caller supplies a valid spatial team sheet for the scheduled fixture. Legacy
player ratings are not silently translated into physical measurements or new
match capabilities.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import stat
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping

from games.touchline.esb.ids import (
    CareerId,
    ClubId,
    MatchId,
    derive_id,
    validate_id,
)
from games.touchline.esb.match.engine import (
    MatchPhase,
    MatchState,
    TeamSheet,
    create_match,
    step_match,
)
from games.touchline.esb.match.rules import MatchRules, STANDARD_RULES
from games.touchline.esb.match.spatial import Pitch
from games.touchline.esb.match.ball import BallPhysics
from games.touchline.esb.people import validate_profile
from games.touchline.esb.serialization import SerializationError, dumps, loads
from games.touchline.esb.world.preparation import (
    ExposureInput,
    PreparationState,
    SelectionStatus,
    prepared_profile,
    selection_assessment,
    settle_fixture_exposure,
)


LEGACY_ENGINE_ID = "touchline.legacy.v2"
SPATIAL_ENGINE_ID = "touchline.spatial.v1"
SAVE_VERSION = 4
SAVE_SCHEMA_VERSION = 1
SESSION_SCHEMA_VERSION = 1

_V3_CAREER_SAVE_FIELDS = frozenset({
    "career_id", "legacy_save_json", "default_engine_id", "current_match_engine_id",
    "current_match_id", "spatial_match_json", "historical_engine_labels",
    "settlement_fingerprints", "save_version", "schema_version",
})


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("career save must contain finite JSON values") from exc


def _legacy_payload(encoded: str) -> dict[str, Any]:
    try:
        value = json.loads(encoded, parse_constant=lambda item: (_ for _ in ()).throw(ValueError(item)))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("versioned save contains an invalid legacy payload") from exc
    if not isinstance(value, dict) or value.get("version") != 2:
        raise ValueError("legacy payload must be a save-v2 object")
    career = value.get("career")
    if not isinstance(career, dict) or career.get("version") != 2:
        raise ValueError("legacy payload must contain a career-v2 object")
    return value


def _legacy_history_labels(save: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    career = save["career"]
    labels: dict[str, str] = {}
    for result in career.get("results", []):
        if not isinstance(result, dict) or not isinstance(result.get("id"), str):
            continue
        labels[result["id"]] = str(result.get("engine_id") or LEGACY_ENGINE_ID)
    for match_id in career.get("played_ids", []):
        if isinstance(match_id, str):
            labels.setdefault(match_id, LEGACY_ENGINE_ID)
    return tuple(sorted(labels.items()))


@dataclass(frozen=True)
class VersionedCareerSave:
    """A v3 adapter envelope around the byte-stable v2 career payload."""

    career_id: CareerId
    legacy_save_json: str
    default_engine_id: str = LEGACY_ENGINE_ID
    current_match_engine_id: str | None = None
    current_match_id: MatchId | None = None
    spatial_match_json: str | None = None
    preparation_json: str | None = None
    historical_engine_labels: tuple[tuple[str, str], ...] = ()
    settlement_fingerprints: tuple[tuple[str, str], ...] = ()
    save_version: int = SAVE_VERSION
    schema_version: int = SAVE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if type(self.save_version) is not int or self.save_version != SAVE_VERSION:
            raise ValueError("unsupported career adapter save version")
        if type(self.schema_version) is not int or self.schema_version != SAVE_SCHEMA_VERSION:
            raise ValueError("unsupported career adapter schema version")
        validate_id(self.career_id, kind="career ID")
        validate_id(self.default_engine_id, kind="default match engine ID")
        if self.default_engine_id != LEGACY_ENGINE_ID:
            raise ValueError("P08 keeps the career default on the legacy engine")
        legacy_save = _legacy_payload(self.legacy_save_json)
        legacy_live_match = legacy_save["career"].get("live_match")
        if (self.current_match_engine_id is None) != (self.current_match_id is None):
            raise ValueError("active match engine and match ID must be present together")
        if self.current_match_engine_id is None and legacy_live_match is not None:
            raise ValueError("saved legacy live match requires its legacy engine label")
        if self.current_match_engine_id is not None:
            validate_id(self.current_match_engine_id, kind="active match engine ID")
            if self.current_match_engine_id not in (LEGACY_ENGINE_ID, SPATIAL_ENGINE_ID):
                raise ValueError("unsupported active career match engine")
            if self.current_match_engine_id == LEGACY_ENGINE_ID:
                if (not isinstance(legacy_live_match, dict)
                        or legacy_live_match.get("id") != str(self.current_match_id)):
                    raise ValueError("legacy active-match metadata must match the saved legacy match")
            elif legacy_live_match is not None:
                raise ValueError("legacy and spatial matches cannot be active at the same time")
        if self.spatial_match_json is not None:
            if self.current_match_engine_id != SPATIAL_ENGINE_ID:
                raise ValueError("spatial checkpoint must be labelled with its engine version")
            if self.current_match_id is None:
                raise ValueError("spatial checkpoint requires an active match ID")
            session = CareerMatchSession.from_json(self.spatial_match_json)
            if session.binding.match_id != self.current_match_id:
                raise ValueError("spatial checkpoint and active match IDs disagree")
            if session.binding.career_id != self.career_id:
                raise ValueError("spatial checkpoint and save career identities disagree")
        elif self.current_match_engine_id == SPATIAL_ENGINE_ID:
            raise ValueError("spatial active match requires a resumable checkpoint")
        if self.preparation_json is not None:
            if not isinstance(self.preparation_json, str) or not self.preparation_json.strip():
                raise ValueError("P09 preparation state must be non-empty versioned JSON")
        if not isinstance(self.historical_engine_labels, tuple):
            raise TypeError("historical engine labels must be immutable pairs")
        history_ids: list[str] = []
        for entry in self.historical_engine_labels:
            if not isinstance(entry, tuple) or len(entry) != 2:
                raise TypeError("historical engine labels must be (match ID, engine ID) pairs")
            validate_id(entry[0], kind="historical match ID")
            validate_id(entry[1], kind="historical engine ID")
            history_ids.append(entry[0])
        if len(history_ids) != len(set(history_ids)):
            raise ValueError("historical match engine labels cannot repeat a match")
        if not isinstance(self.settlement_fingerprints, tuple):
            raise TypeError("settlement fingerprints must be immutable pairs")
        receipt_ids: list[str] = []
        for entry in self.settlement_fingerprints:
            if not isinstance(entry, tuple) or len(entry) != 2:
                raise TypeError("settlement fingerprints must be (match ID, digest) pairs")
            validate_id(entry[0], kind="settled match ID")
            if (not isinstance(entry[1], str) or len(entry[1]) != 64
                    or any(char not in "0123456789abcdef" for char in entry[1])):
                raise ValueError("settlement fingerprint must be a lowercase SHA-256 digest")
            receipt_ids.append(entry[0])
        if len(receipt_ids) != len(set(receipt_ids)):
            raise ValueError("a match cannot have multiple settlement fingerprints")

    @property
    def legacy_save(self) -> dict[str, Any]:
        """Return a detached v2 value suitable for the legacy resolver."""
        return copy.deepcopy(_legacy_payload(self.legacy_save_json))

    def to_json(self) -> str:
        return dumps(self)

    @classmethod
    def from_json(cls, value: str) -> VersionedCareerSave:
        try:
            envelope = json.loads(
                value,
                parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
            )
            if (
                not isinstance(envelope, dict)
                or set(envelope) != {"format", "schema_version", "record_type", "payload"}
                or envelope.get("format") != "esb.core-record"
                or envelope.get("schema_version") != 1
                or envelope.get("record_type") != f"{cls.__module__}.{cls.__qualname__}"
                or not isinstance(envelope.get("payload"), dict)
            ):
                raise ValueError("career adapter envelope is malformed")
            payload = envelope["payload"]
            if payload.get("save_version") == 3:
                if set(payload) != _V3_CAREER_SAVE_FIELDS or payload.get("schema_version") != 1:
                    raise ValueError("version-3 career adapter fields are malformed")
                upgraded = dict(envelope)
                upgraded_payload = dict(payload)
                upgraded_payload["save_version"] = SAVE_VERSION
                upgraded_payload["preparation_json"] = None
                upgraded["payload"] = upgraded_payload
                envelope = upgraded
                value = json.dumps(
                    envelope,
                    ensure_ascii=False,
                    allow_nan=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            restored = loads(value, cls)
            if restored.preparation_json is not None:
                preparation = PreparationState.from_json(restored.preparation_json)
                if preparation.career_id != restored.career_id:
                    raise ValueError("P09 preparation state belongs to a different career")
            return restored
        except (SerializationError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid versioned career save: {exc}") from exc


def store_preparation_state(
    save: VersionedCareerSave, preparation: PreparationState
) -> VersionedCareerSave:
    """Persist P09 state in the v4 envelope without altering its legacy payload."""

    if not isinstance(save, VersionedCareerSave) or not isinstance(preparation, PreparationState):
        raise TypeError("P09 persistence requires a versioned save and preparation state")
    if save.career_id != preparation.career_id:
        raise ValueError("P09 preparation and career save identities must match")
    return replace(save, preparation_json=preparation.to_json())


def load_preparation_state(save: VersionedCareerSave) -> PreparationState | None:
    """Read saved P09 state; the query does not consume randomness or mutate the save."""

    if not isinstance(save, VersionedCareerSave):
        raise TypeError("P09 restore requires a VersionedCareerSave")
    if save.preparation_json is None:
        return None
    preparation = PreparationState.from_json(save.preparation_json)
    if preparation.career_id != save.career_id:
        raise ValueError("P09 preparation state belongs to a different career")
    return preparation


def migrate_v2_save(save: Mapping[str, Any]) -> VersionedCareerSave:
    """Wrap v2 without changing it or inventing state for a live legacy match."""
    if not isinstance(save, Mapping):
        raise TypeError("legacy save must be a mapping")
    raw = dict(save)
    encoded = _canonical_json(raw)
    checked = _legacy_payload(encoded)
    career = checked["career"]
    career_id = CareerId(derive_id(
        "career", "touchline-legacy-v2",
        hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
    ))
    live_match = career.get("live_match")
    current_match_id = None
    current_engine_id = None
    if live_match is not None:
        if not isinstance(live_match, dict):
            raise ValueError("legacy live match must be an object or null")
        legacy_id = live_match.get("id")
        if not isinstance(legacy_id, str):
            raise ValueError("legacy live match has no stable match ID")
        validate_id(legacy_id, kind="legacy match ID")
        current_match_id = MatchId(legacy_id)
        current_engine_id = LEGACY_ENGINE_ID
    return VersionedCareerSave(
        career_id=career_id,
        legacy_save_json=encoded,
        current_match_engine_id=current_engine_id,
        current_match_id=current_match_id,
        historical_engine_labels=_legacy_history_labels(checked),
    )


def migrate_v2_file(path: str | os.PathLike[str], *,
                    backup_path: str | os.PathLike[str] | None = None
                    ) -> tuple[VersionedCareerSave, Path]:
    """Atomically replace one v2 save after preserving its exact bytes.

    This low-level helper is not called by the current game UI. A caller must
    first ensure its loader understands the v3 envelope.
    """
    target = Path(path)
    original = target.read_bytes()
    try:
        parsed = json.loads(original, parse_constant=lambda item: (_ for _ in ()).throw(ValueError(item)))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("save file is not finite JSON") from exc
    migrated = migrate_v2_save(parsed)
    backup = Path(backup_path) if backup_path is not None else target.with_name(target.name + ".v2.bak")
    if backup.exists():
        raise FileExistsError(f"refusing to overwrite existing v2 backup: {backup}")
    mode = stat.S_IMODE(target.stat().st_mode)
    temp_name: str | None = None
    try:
        with backup.open("xb") as stream:
            stream.write(original)
            stream.flush()
            os.fsync(stream.fileno())
        descriptor, temp_name = tempfile.mkstemp(prefix=f".{target.name}.p08-", dir=target.parent)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write((migrated.to_json() + "\n").encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp_name, mode)
        if target.read_bytes() != original:
            raise RuntimeError("career save changed while migration was being prepared")
        os.replace(temp_name, target)
        temp_name = None
        directory_fd = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temp_name is not None:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
    return migrated, backup


@dataclass(frozen=True)
class CareerFixtureBinding:
    career_id: CareerId
    fixture_id: str
    season: int
    round_index: int
    competition_id: str
    home_club_id: ClubId
    away_club_id: ClubId
    match_id: MatchId
    seed: int
    engine_id: str = SPATIAL_ENGINE_ID
    engine_version: int = 1
    ruleset_id: str = STANDARD_RULES.ruleset_id
    ruleset_version: int = STANDARD_RULES.schema_version

    def __post_init__(self) -> None:
        validate_id(self.career_id, kind="career ID")
        validate_id(self.fixture_id, kind="fixture ID")
        validate_id(self.home_club_id, kind="home club ID")
        validate_id(self.away_club_id, kind="away club ID")
        validate_id(self.match_id, kind="match ID")
        validate_id(self.competition_id, kind="competition ID")
        validate_id(self.engine_id, kind="match engine ID")
        validate_id(self.ruleset_id, kind="ruleset ID")
        if self.home_club_id == self.away_club_id:
            raise ValueError("career fixture must have two different clubs")
        for label, value in (("season", self.season), ("round", self.round_index),
                             ("engine version", self.engine_version),
                             ("ruleset version", self.ruleset_version)):
            if type(value) is not int or value < (0 if label == "round" else 1):
                raise ValueError(f"career match {label} is out of range")
        if type(self.seed) is not int:
            raise TypeError("career match seed must be an integer")
        if self.engine_id != SPATIAL_ENGINE_ID or self.engine_version != 1:
            raise ValueError("unsupported spatial career engine version")
        expected_fixture_id = derive_id(
            "fixture", str(self.career_id), self.competition_id, self.season,
            self.round_index, str(self.home_club_id), str(self.away_club_id),
        )
        expected_match_id = derive_id(
            "match", "career-spatial-v1", str(self.career_id), self.competition_id,
            self.season, self.round_index, str(self.home_club_id), str(self.away_club_id),
        )
        if self.fixture_id != expected_fixture_id or str(self.match_id) != expected_match_id:
            raise ValueError("career fixture and match IDs must derive from their stable binding")


@dataclass(frozen=True)
class CareerMatchSession:
    binding: CareerFixtureBinding
    match: MatchState
    schema_version: int = SESSION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.binding, CareerFixtureBinding):
            raise TypeError("career match requires an explicit fixture binding")
        if not isinstance(self.match, MatchState):
            raise TypeError("career match requires a spatial MatchState")
        if self.match.match_id != self.binding.match_id:
            raise ValueError("career binding and match state IDs disagree")
        if (self.match.rules.ruleset_id != self.binding.ruleset_id
                or self.match.rules.schema_version != self.binding.ruleset_version):
            raise ValueError("career binding and spatial match rules disagree")
        if type(self.schema_version) is not int or self.schema_version != SESSION_SCHEMA_VERSION:
            raise ValueError("unsupported career match-session schema version")

    def to_json(self) -> str:
        return dumps(self)

    @classmethod
    def from_json(cls, value: str) -> CareerMatchSession:
        try:
            return loads(value, cls)
        except SerializationError as exc:
            raise ValueError(f"invalid career match checkpoint: {exc}") from exc


def _fixture_for_career(career: Mapping[str, Any]) -> tuple[str, str, str, int]:
    club_id = career.get("club_id")
    season = career.get("season")
    round_index = career.get("round")
    if not isinstance(club_id, str) or type(season) is not int or type(round_index) is not int:
        raise ValueError("career club, season and current round are required")
    if round_index < 0 or career.get("season_complete"):
        raise ValueError("career is not at an active fixture")
    clubs = career.get("clubs")
    fixtures = career.get("fixtures")
    if not isinstance(clubs, dict) or not isinstance(fixtures, dict):
        raise ValueError("career clubs and fixture schedule are required")
    club = clubs.get(club_id)
    if not isinstance(club, dict):
        raise ValueError("manager club is not registered in the career")
    competition_id = club.get("division")
    if not isinstance(competition_id, str) or competition_id not in fixtures:
        raise ValueError("manager club has no supported active competition")
    rounds = fixtures[competition_id]
    if not isinstance(rounds, (list, tuple)) or round_index >= len(rounds):
        raise ValueError("career round is outside its competition schedule")
    round_fixtures = rounds[round_index]
    if not isinstance(round_fixtures, (list, tuple)):
        raise ValueError("career round fixture list is malformed")
    selected = [pair for pair in round_fixtures
                if isinstance(pair, (list, tuple)) and len(pair) == 2 and club_id in pair]
    if len(selected) != 1:
        raise ValueError("manager club must have exactly one fixture this round")
    home, away = selected[0]
    if not isinstance(home, str) or not isinstance(away, str) or home == away:
        raise ValueError("scheduled fixture has invalid club identities")
    return competition_id, home, away, round_index


def next_spatial_match_id(save: VersionedCareerSave) -> MatchId:
    """Preview the stable ID used by P08 for the career's scheduled fixture."""

    if not isinstance(save, VersionedCareerSave):
        raise TypeError("fixture ID preview requires a VersionedCareerSave")
    career = save.legacy_save["career"]
    competition, home_id, away_id, round_index = _fixture_for_career(career)
    return MatchId(derive_id(
        "match", "career-spatial-v1", str(save.career_id), competition,
        int(career["season"]), round_index, home_id, away_id,
    ))


def _validate_p09_selection(
    save: VersionedCareerSave,
    match_id: MatchId,
    home_id: str,
    away_id: str,
    home_sheet: TeamSheet,
    away_sheet: TeamSheet,
    career: Mapping[str, Any],
) -> None:
    preparation = load_preparation_state(save)
    if preparation is None:
        return
    managed_club_id = str(preparation.club_id)
    if managed_club_id not in (home_id, away_id):
        raise ValueError("P09 preparation club is not participating in the scheduled match")
    fixture = next(
        (item for item in preparation.fixtures if item.match_id == match_id),
        None,
    )
    if fixture is None or fixture.scheduled_on != preparation.world_date:
        raise ValueError("P09 preparation calendar is not on this scheduled match date")
    if match_id in preparation.completed_fixture_ids:
        raise ValueError("P09 preparation fixture exposure is already settled")
    club_state = career.get("clubs", {}).get(managed_club_id)
    registered = club_state.get("roster") if isinstance(club_state, dict) else None
    if not isinstance(registered, (list, tuple)) or set(map(str, registered)) != {
        str(profile.player_id) for profile in preparation.profiles
    }:
        raise ValueError("P09 preparation profiles must exactly match the managed club roster")
    managed_sheet = home_sheet if managed_club_id == home_id else away_sheet
    selected_profiles = [item.profile for item in managed_sheet.starters]
    selected_profiles.extend(managed_sheet.substitutes)
    for profile in selected_profiles:
        assessment = selection_assessment(preparation, profile.player_id)
        if assessment.status is not SelectionStatus.SELECTABLE:
            raise ValueError(
                f"{profile.display_name} is not selectable under P09: {assessment.status.value}"
            )
        if profile != prepared_profile(preparation, profile.player_id):
            raise ValueError(
                f"{profile.display_name} team-sheet profile is not the current P09 condition snapshot"
            )
    unavailable = {str(item) for item in managed_sheet.unavailable_player_ids}
    p09_unavailable = {
        str(profile.player_id)
        for profile in preparation.profiles
        if selection_assessment(preparation, profile.player_id).status is not SelectionStatus.SELECTABLE
    }
    if p09_unavailable - unavailable:
        raise ValueError("P09 medically unavailable or unready players must be listed as unavailable")


def _validate_sheet_against_career(sheet: TeamSheet, club_id: str,
                                   career: Mapping[str, Any]) -> None:
    if not isinstance(sheet, TeamSheet):
        raise TypeError("spatial career match requires a TeamSheet for each side")
    clubs = career["clubs"]
    players = career.get("players")
    if not isinstance(players, dict):
        raise ValueError("career player registry is missing")
    club_state = clubs.get(club_id)
    if not isinstance(club_state, dict):
        raise ValueError(f"fixture club {club_id} is not registered")
    roster_ids = club_state.get("roster", ())
    lineup = club_state.get("lineup")
    if (not isinstance(roster_ids, (list, tuple))
            or len(roster_ids) != len(set(roster_ids))
            or not isinstance(lineup, (list, tuple)) or not lineup
            or len(lineup) != len(set(lineup))):
        raise ValueError(f"fixture club {club_id} has no registered legacy lineup")
    roster = set(roster_ids)
    starter_ids = {str(item.profile.player_id) for item in sheet.starters}
    if starter_ids != set(lineup):
        raise ValueError(f"{sheet.team_id} starters must exactly match the saved career lineup")
    selected = [*sheet.starters, *sheet.substitutes]
    for item in selected:
        profile = item.profile if hasattr(item, "profile") else item
        player_id = str(profile.player_id)
        legacy_player = players.get(player_id)
        if player_id not in roster or not isinstance(legacy_player, dict):
            raise ValueError(f"{profile.display_name} is not registered at {club_id}")
        if legacy_player.get("club") != club_id or str(profile.club_id) != club_id:
            raise ValueError(f"{profile.display_name} does not belong to fixture club {club_id}")
        career_week = int(career.get("career_week", career.get("round", 0)))
        if int(legacy_player.get("injury_until_round", -1)) > career_week:
            raise ValueError(f"{profile.display_name} is unavailable through injury")
        issues = validate_profile(profile)
        if issues:
            first = issues[0]
            raise ValueError(f"{profile.display_name} profile {first.code}: {first.message}")
    for player_id in sheet.unavailable_player_ids:
        if str(player_id) not in roster or str(player_id) not in players:
            raise ValueError(f"unavailable {sheet.team_id} player is not registered at {club_id}")


def start_spatial_career_match(
    save: VersionedCareerSave,
    *,
    home_sheet: TeamSheet,
    away_sheet: TeamSheet,
    seed: int,
    rules: MatchRules = STANDARD_RULES,
    pitch: Pitch = Pitch(),
    physics: BallPhysics = BallPhysics(),
    kickoff_team_id: str | None = None,
) -> VersionedCareerSave:
    """Start one explicitly opted-in spatial fixture and persist its checkpoint."""
    if not isinstance(save, VersionedCareerSave):
        raise TypeError("start_spatial_career_match requires a versioned career save")
    if save.spatial_match_json is not None:
        raise ValueError("career already has an active spatial match")
    career = save.legacy_save["career"]
    if career.get("live_match") is not None:
        raise ValueError("resume the active legacy match with the legacy engine")
    if save.current_match_id is not None:
        raise ValueError("career already has an active match checkpoint")
    competition, home_id, away_id, round_index = _fixture_for_career(career)
    if str(home_sheet.team_id) != "home" or str(away_sheet.team_id) != "away":
        raise ValueError("fixture sheets must be supplied in scheduled home/away order")
    _validate_sheet_against_career(home_sheet, home_id, career)
    _validate_sheet_against_career(away_sheet, away_id, career)
    if type(seed) is not int:
        raise TypeError("match seed must be an integer")
    if not isinstance(rules, MatchRules):
        raise TypeError("spatial career match requires an explicit MatchRules snapshot")
    season = int(career["season"])
    fixture_id = derive_id("fixture", str(save.career_id), competition, season,
                           round_index, home_id, away_id)
    match_id = MatchId(derive_id("match", "career-spatial-v1", str(save.career_id),
                                 competition, season, round_index, home_id, away_id))
    _validate_p09_selection(
        save, match_id, home_id, away_id, home_sheet, away_sheet, career
    )
    existing_results = career.get("results", [])
    if any(isinstance(item, dict) and item.get("season") == season
           and item.get("round") == round_index + 1
           and item.get("home") == home_id and item.get("away") == away_id
           for item in existing_results):
        raise ValueError("scheduled fixture already has a settled career result")
    if str(match_id) in career.get("played_ids", []):
        raise ValueError("career already contains this spatial fixture ID")
    match = create_match(home_sheet, away_sheet, rules=rules, seed=seed, pitch=pitch,
                         physics=physics, match_id=match_id,
                         kickoff_team_id=kickoff_team_id if kickoff_team_id is not None else "home")
    binding = CareerFixtureBinding(
        career_id=save.career_id,
        fixture_id=fixture_id,
        season=season,
        round_index=round_index,
        competition_id=competition,
        home_club_id=ClubId(home_id),
        away_club_id=ClubId(away_id),
        match_id=match_id,
        seed=seed,
        ruleset_id=rules.ruleset_id,
        ruleset_version=rules.schema_version,
    )
    session = CareerMatchSession(binding, match)
    return replace(save, current_match_engine_id=SPATIAL_ENGINE_ID,
                   current_match_id=match_id, spatial_match_json=session.to_json())


def resume_spatial_career_match(save: VersionedCareerSave) -> CareerMatchSession:
    if save.spatial_match_json is None:
        raise ValueError("career has no active spatial match checkpoint")
    session = CareerMatchSession.from_json(save.spatial_match_json)
    career = save.legacy_save["career"]
    _validate_binding_against_career(session.binding, save.career_id, career)
    _validate_session_rosters(session, career)
    return session


def advance_spatial_career_match(save: VersionedCareerSave, transitions: int = 1,
                                *, tactical_runtimes: Mapping[str, Any] | None = None
                                ) -> VersionedCareerSave:
    if type(transitions) is not int or transitions <= 0:
        raise ValueError("spatial match advance must request positive transitions")
    session = resume_spatial_career_match(save)
    for _ in range(transitions):
        if session.match.phase in (MatchPhase.FINISHED, MatchPhase.ABANDONED):
            break
        step_match(session.match, tactical_runtimes=tactical_runtimes)
    return replace(save, spatial_match_json=session.to_json())


def run_spatial_career_match(save: VersionedCareerSave, *, maximum_transitions: int = 500_000,
                             tactical_runtimes: Mapping[str, Any] | None = None
                             ) -> VersionedCareerSave:
    if type(maximum_transitions) is not int or maximum_transitions <= 0:
        raise ValueError("maximum transition count must be positive")
    session = resume_spatial_career_match(save)
    for _ in range(maximum_transitions):
        if session.match.phase in (MatchPhase.FINISHED, MatchPhase.ABANDONED):
            break
        step_match(session.match, tactical_runtimes=tactical_runtimes)
        if session.match.phase in (MatchPhase.FINISHED, MatchPhase.ABANDONED):
            break
    else:
        raise RuntimeError("spatial career match did not finish within its transition budget")
    if session.match.phase is MatchPhase.ABANDONED:
        raise RuntimeError("abandoned spatial career match requires an explicit result policy")
    return replace(save, spatial_match_json=session.to_json())


def _validate_binding_against_career(binding: CareerFixtureBinding,
                                     career_id: CareerId,
                                     career: Mapping[str, Any]) -> None:
    if binding.career_id != career_id:
        raise ValueError("spatial match checkpoint belongs to a different career identity")
    if binding.season != career.get("season") or binding.round_index != career.get("round"):
        raise ValueError("spatial match checkpoint belongs to a different career season or round")
    competition, home, away, round_index = _fixture_for_career(career)
    if (binding.competition_id != competition or binding.round_index != round_index
            or str(binding.home_club_id) != home or str(binding.away_club_id) != away):
        raise ValueError("spatial match checkpoint no longer matches the scheduled fixture")


def _validate_session_rosters(session: CareerMatchSession,
                              career: Mapping[str, Any]) -> None:
    players = career.get("players")
    clubs = career.get("clubs")
    if not isinstance(players, dict) or not isinstance(clubs, dict):
        raise ValueError("career registries are missing from the spatial checkpoint")
    for team_id, club_id in (("home", str(session.binding.home_club_id)),
                             ("away", str(session.binding.away_club_id))):
        club = clubs.get(club_id)
        roster = session.match.teams.get(team_id)
        if not isinstance(club, dict) or roster is None:
            raise ValueError(f"spatial checkpoint has no registered {team_id} career side")
        roster_ids = club.get("roster", ())
        lineup_ids = club.get("lineup", ())
        if (not isinstance(roster_ids, (list, tuple))
                or len(roster_ids) != len(set(roster_ids))
                or not isinstance(lineup_ids, (list, tuple))
                or len(lineup_ids) != len(set(lineup_ids))):
            raise ValueError(f"{team_id} saved roster or lineup is malformed")
        registered = set(roster_ids)
        active_ids = {str(player_id) for player_id, state in session.match.play.players.items()
                      if state.team_id == team_id}
        expected_lineup = active_ids | {str(player_id) for player_id in roster.sent_off_ids}
        if set(map(str, lineup_ids)) != expected_lineup:
            raise ValueError(
                f"{team_id} current career lineup disagrees with active and sent-off match players"
            )
        # starting_ids retain the immutable kickoff XI; career.lineup may
        # reflect a legal matchday substitution, and dismissals can reduce
        # the active side without rewriting that kickoff record.
        profile_ids = [*map(str, roster.starting_ids),
                       *(str(profile.player_id) for profile in roster.substitutes),
                       *map(str, roster.unavailable_ids)]
        profile_ids.extend(str(player_id) for player_id, state in session.match.play.players.items()
                           if state.team_id == team_id)
        if any(player_id not in registered for player_id in profile_ids):
            raise ValueError(f"{team_id} spatial checkpoint references an unregistered player")
        profiles = [player.profile for player in session.match.play.players.values()
                    if player.team_id == team_id]
        profiles.extend(roster.substitutes)
        for profile in profiles:
            player_id = str(profile.player_id)
            legacy = players.get(player_id)
            if (player_id not in registered or not isinstance(legacy, dict)
                    or legacy.get("club") != club_id
                    or str(profile.club_id) != club_id):
                raise ValueError(f"spatial checkpoint player {player_id} changed club identity")
            if validate_profile(profile):
                raise ValueError(f"spatial checkpoint profile {player_id} is no longer valid")


def _event_data(event: Any) -> dict[str, Any]:
    payload = event.payload
    outcome = event.outcome
    return {
        "event_id": str(event.event_id),
        "sequence": event.sequence,
        "tick": event.match_tick,
        "kind": event.kind,
        "actor_id": payload.get("actor_id"),
        "cause_event_id": str(event.cause_event_id) if event.cause_event_id else None,
        "parent_event_id": str(event.parent_event_id) if event.parent_event_id else None,
        "payload": payload,
        "outcome": outcome,
    }


def _lineage(session: CareerMatchSession) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    events = session.match.events
    by_id = {str(event.event_id): event for event in events}
    goals = [event for event in events if event.kind == "goal"]
    retained: set[str] = set()
    goal_rows: list[dict[str, Any]] = []
    for goal in goals:
        payload = goal.payload
        actor_id = payload.get("actor_id")
        assist_id = payload.get("assist_player_id")
        goal_rows.append({
            "goal_event_id": str(goal.event_id),
            "sequence": goal.sequence,
            "tick": goal.match_tick,
            "scorer_id": actor_id,
            "own_goal_id": payload.get("own_goal_player_id"),
            "assist_id": assist_id,
            "assist_event_id": payload.get("assist_event_id"),
            "cause_event_id": str(goal.cause_event_id) if goal.cause_event_id else None,
            "parent_event_id": str(goal.parent_event_id) if goal.parent_event_id else None,
        })
        pending = [str(reference) for reference in (goal.cause_event_id, goal.parent_event_id)
                   if reference is not None]
        while pending:
            event_id = pending.pop()
            if event_id in retained or event_id not in by_id:
                continue
            retained.add(event_id)
            ancestor = by_id[event_id]
            pending.extend(str(reference) for reference in
                           (ancestor.cause_event_id, ancestor.parent_event_id)
                           if reference is not None)
        retained.add(str(goal.event_id))
    lineage_events = [_event_data(event) for event in events
                      if str(event.event_id) in retained]
    return goal_rows, lineage_events


def _result_record(session: CareerMatchSession) -> dict[str, Any]:
    match = session.match
    binding = session.binding
    goal_lineages, lineage_events = _lineage(session)
    return {
        "id": str(binding.match_id),
        "season": binding.season,
        "division": str(binding.competition_id),
        "round": binding.round_index + 1,
        "home": str(binding.home_club_id),
        "away": str(binding.away_club_id),
        "home_goals": match.home_score,
        "away_goals": match.away_score,
        "engine_id": binding.engine_id,
        "engine_version": binding.engine_version,
        "ruleset_id": binding.ruleset_id,
        "ruleset_version": binding.ruleset_version,
        "stats": {
            "player": {str(player_id): stats
                       for player_id, stats in match.player_statistics.items()},
            "minutes": {str(player_id): minutes
                        for player_id, minutes in match.minutes_played.items()},
        },
        "goal_lineages": goal_lineages,
        "lineage_events": lineage_events,
    }


def _settle_result(career: dict[str, Any], result: dict[str, Any]) -> None:
    home, away = result["home"], result["away"]
    if home not in career["table"] or away not in career["table"]:
        raise ValueError("career table does not contain both fixture clubs")
    home_goals, away_goals = result["home_goals"], result["away_goals"]
    if type(home_goals) is not int or type(away_goals) is not int:
        raise ValueError("spatial match result has invalid score values")
    home_line, away_line = career["table"][home], career["table"][away]
    for line in (home_line, away_line):
        if not isinstance(line, dict) or any(type(line.get(key)) is not int for key in
                                             ("played", "won", "drawn", "lost", "gf", "ga", "points")):
            raise ValueError("career standings row is incomplete or malformed")
    player_registry = career.get("players")
    if not isinstance(player_registry, dict):
        raise ValueError("career player registry is missing")
    player_minutes = result["stats"]["minutes"]
    player_stats = result["stats"]["player"]
    for player_id in set(player_minutes) | set(player_stats):
        player = player_registry.get(player_id)
        if not isinstance(player, dict) or player.get("club") not in (home, away):
            raise ValueError(f"spatial match statistic references unregistered career player {player_id}")
    for player_id, minutes in player_minutes.items():
        if type(minutes) not in (int, float) or minutes < 0:
            raise ValueError("spatial match player minutes are invalid")
        if minutes <= 0:
            continue
        player = player_registry[player_id]
        stats = player_stats.get(player_id, {})
        player["career_apps"] = int(player.get("career_apps", 0)) + 1
        player["career_goals"] = int(player.get("career_goals", 0)) + int(stats.get("goals", 0))
        player["career_assists"] = int(player.get("career_assists", 0)) + int(stats.get("assists", 0))
    home_line["played"] += 1
    away_line["played"] += 1
    home_line["gf"] += home_goals
    home_line["ga"] += away_goals
    away_line["gf"] += away_goals
    away_line["ga"] += home_goals
    if home_goals > away_goals:
        home_line["won"] += 1
        home_line["points"] += 3
        away_line["lost"] += 1
        career["clubs"][home]["wins"] = int(career["clubs"][home].get("wins", 0)) + 1
    elif away_goals > home_goals:
        away_line["won"] += 1
        away_line["points"] += 3
        home_line["lost"] += 1
        career["clubs"][away]["wins"] = int(career["clubs"][away].get("wins", 0)) + 1
    else:
        home_line["drawn"] += 1
        away_line["drawn"] += 1
        home_line["points"] += 1
        away_line["points"] += 1
    career.setdefault("played_ids", []).append(result["id"])
    career.setdefault("results", []).append(result)
    career["results"] = career["results"][-200:]


def settle_spatial_career_match(
    save: VersionedCareerSave,
    session: CareerMatchSession | None = None,
    *,
    exertion_by_player: Mapping[PlayerId, float] | None = None,
) -> tuple[VersionedCareerSave, bool]:
    """Settle the current spatial fixture into score/table/history once.

    This package owns fixture standings and a replayable result projection.
    Legacy wages, board reactions, injuries and the rest-of-round simulation
    remain owned by the existing career engine until their parity work lands.
    """
    active_json = save.spatial_match_json
    if active_json is not None:
        stored_session = CareerMatchSession.from_json(active_json)
        if session is not None and session.to_json() != active_json:
            raise ValueError("settlement request does not match the active checkpoint")
        session = stored_session
    elif session is None:
        raise ValueError("career has no active spatial match to settle")
    assert session is not None
    if session.match.phase is not MatchPhase.FINISHED:
        raise ValueError("spatial career match must finish before settlement")
    match_id = str(session.binding.match_id)
    fingerprint = hashlib.sha256(session.to_json().encode("utf-8")).hexdigest()
    previous = dict(save.settlement_fingerprints).get(match_id)
    if previous is not None:
        if previous != fingerprint:
            raise ValueError("settled match ID was reused with a different result")
        return save, False
    if active_json is None:
        raise ValueError("spatial checkpoint was already consumed by another settlement")
    _validate_binding_against_career(session.binding, save.career_id,
                                     save.legacy_save["career"])
    _validate_session_rosters(session, save.legacy_save["career"])
    result = _result_record(session)
    preparation = load_preparation_state(save)
    updated_preparation: PreparationState | None = None
    if preparation is not None:
        if exertion_by_player is None or not isinstance(exertion_by_player, Mapping):
            raise ValueError("P09 spatial settlement requires explicit per-player match exertion")
        match_id = session.binding.match_id
        if preparation.club_id not in (
            session.binding.home_club_id,
            session.binding.away_club_id,
        ):
            raise ValueError("P09 preparation club is not part of the settled match")
        expected_players = {profile.player_id for profile in preparation.profiles}
        if set(exertion_by_player) != expected_players:
            raise ValueError("P09 exertion inputs must include every managed-club player exactly once")
        played_minutes = session.match.minutes_played
        exposure_inputs = tuple(
            ExposureInput(
                profile.player_id,
                played_minutes.get(profile.player_id, 0.0),
                exertion_by_player[profile.player_id],
            )
            for profile in preparation.profiles
        )
        updated_preparation = settle_fixture_exposure(
            preparation,
            match_id,
            exposure_inputs,
        )
    elif exertion_by_player is not None:
        raise ValueError("P09 exertion inputs require saved preparation state")
    working_save = save.legacy_save
    career = working_save["career"]
    if career.get("live_match") is not None:
        raise ValueError("cannot settle a spatial fixture over a live legacy match")
    played_ids = career.setdefault("played_ids", [])
    if match_id in played_ids:
        raise ValueError("spatial match ID is already present in legacy played history")
    if any(isinstance(item, dict) and item.get("season") == result["season"]
           and item.get("round") == result["round"]
           and item.get("home") == result["home"] and item.get("away") == result["away"]
           for item in career.get("results", [])):
        raise ValueError("scheduled fixture already has a settled career result")
    _settle_result(career, result)
    labels = dict(save.historical_engine_labels)
    labels[match_id] = SPATIAL_ENGINE_ID
    fingerprints = dict(save.settlement_fingerprints)
    fingerprints[match_id] = fingerprint
    settled = replace(
        save,
        legacy_save_json=_canonical_json(working_save),
        current_match_engine_id=None,
        current_match_id=None,
        spatial_match_json=None,
        preparation_json=(
            updated_preparation.to_json()
            if updated_preparation is not None else save.preparation_json
        ),
        historical_engine_labels=tuple(sorted(labels.items())),
        settlement_fingerprints=tuple(sorted(fingerprints.items())),
    )
    return settled, True


__all__ = [
    "CareerFixtureBinding",
    "CareerMatchSession",
    "LEGACY_ENGINE_ID",
    "SAVE_SCHEMA_VERSION",
    "SAVE_VERSION",
    "SPATIAL_ENGINE_ID",
    "VersionedCareerSave",
    "advance_spatial_career_match",
    "load_preparation_state",
    "migrate_v2_file",
    "migrate_v2_save",
    "next_spatial_match_id",
    "resume_spatial_career_match",
    "run_spatial_career_match",
    "settle_spatial_career_match",
    "start_spatial_career_match",
    "store_preparation_state",
]
