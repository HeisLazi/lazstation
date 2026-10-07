"""Private, explicit personal preferences and dated opportunity reads.

Preferences are descriptive evidence. This module neither infers them from
identity or behaviour nor turns them into a transfer, selection or performance
decision. Histories are person-owned so callers can retain them behind the
same privacy boundary as personal experience records.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from enum import Enum
from typing import NewType

from games.touchline.esb.ids import EventId, derive_id, validate_id
from games.touchline.esb.people.relationships import PersonId, WorldMoment

PreferenceId = NewType("PreferenceId", str)
OpportunityId = NewType("OpportunityId", str)


class PreferenceDomain(str, Enum):
    PLACE = "place"
    COMPETITION = "competition"
    LIFESTYLE = "lifestyle"
    CLUB_POLICY = "club_policy"


class PreferenceStance(str, Enum):
    FAVOUR = "favour"
    OPEN = "open"
    AVOID = "avoid"


_DOMAIN_PREFIX = {
    PreferenceDomain.PLACE: "place:",
    PreferenceDomain.COMPETITION: "competition:",
    PreferenceDomain.LIFESTYLE: "lifestyle:",
    PreferenceDomain.CLUB_POLICY: "policy:",
}


def _feature_key(feature: PreferenceFeature) -> tuple[str, str]:
    return feature.domain.value, feature.feature_id


def _statement_key(statement: SelfReportedPreference) -> tuple[WorldMoment, str, str, str]:
    return (
        statement.at,
        str(statement.source_event_id),
        statement.feature.domain.value,
        statement.feature.feature_id,
    )


def _preference_id(
    person_id: PersonId, source_event_id: EventId, feature: PreferenceFeature
) -> PreferenceId:
    return PreferenceId(derive_id(
        "preference",
        "p13-explicit-preference-v1",
        str(person_id),
        str(source_event_id),
        feature.domain.value,
        feature.feature_id,
    ))


@dataclass(frozen=True, order=True)
class PreferenceFeature:
    """An exact, typed feature ID; parent regions and categories do not match."""

    domain: PreferenceDomain
    feature_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.domain, PreferenceDomain):
            raise TypeError("preference feature requires a supported domain")
        validate_id(self.feature_id, kind="preference feature ID")
        if not self.feature_id.startswith(_DOMAIN_PREFIX[self.domain]):
            raise ValueError("preference feature ID must use its domain's explicit prefix")


@dataclass(frozen=True)
class SelfReportedPreference:
    """One dated statement by a person about one exact feature."""

    preference_id: PreferenceId
    person_id: PersonId
    source_event_id: EventId
    at: WorldMoment
    feature: PreferenceFeature
    stance: PreferenceStance
    salience: float
    certainty: float

    def __post_init__(self) -> None:
        validate_id(self.preference_id, kind="personal preference ID")
        validate_id(self.person_id, kind="preference owner ID")
        validate_id(self.source_event_id, kind="preference statement event ID")
        if not isinstance(self.at, WorldMoment):
            raise TypeError("preference statement requires its source world moment")
        if not isinstance(self.feature, PreferenceFeature):
            raise TypeError("preference statement requires an exact typed feature")
        if not isinstance(self.stance, PreferenceStance):
            raise TypeError("preference statement requires an explicit stance")
        _unit_interval(self.salience, "preference salience")
        _unit_interval(self.certainty, "preference certainty")
        if self.preference_id != _preference_id(
            self.person_id, self.source_event_id, self.feature
        ):
            raise ValueError("preference ID does not match its person, event and feature")


@dataclass(frozen=True)
class PersonalPreferenceHistory:
    """Append-only preference evidence for exactly one person."""

    person_id: PersonId
    statements: tuple[SelfReportedPreference, ...] = ()

    def __post_init__(self) -> None:
        validate_id(self.person_id, kind="personal preference history owner ID")
        if not isinstance(self.statements, tuple) or any(
            not isinstance(item, SelfReportedPreference) for item in self.statements
        ):
            raise TypeError("personal preference statements must be an immutable tuple")
        if any(item.person_id != self.person_id for item in self.statements):
            raise ValueError("preference history cannot contain another person's statements")
        ids = [item.preference_id for item in self.statements]
        if len(ids) != len(set(ids)):
            raise ValueError("personal preference IDs cannot repeat")
        keys = tuple(_statement_key(item) for item in self.statements)
        if tuple(sorted(keys)) != keys:
            raise ValueError("preference statements must retain source chronology")
        source_moments: dict[EventId, WorldMoment] = {}
        moment_sources: dict[WorldMoment, EventId] = {}
        source_features: set[tuple[EventId, PreferenceFeature]] = set()
        for item in self.statements:
            prior_moment = source_moments.get(item.source_event_id)
            if prior_moment is not None and prior_moment != item.at:
                raise ValueError("a preference source event cannot occupy multiple world moments")
            prior_source = moment_sources.get(item.at)
            if prior_source is not None and prior_source != item.source_event_id:
                raise ValueError("a world moment cannot identify multiple preference source events")
            source_moments[item.source_event_id] = item.at
            moment_sources[item.at] = item.source_event_id
            source_feature = (item.source_event_id, item.feature)
            if source_feature in source_features:
                raise ValueError("one statement event cannot report the same feature twice")
            source_features.add(source_feature)


@dataclass(frozen=True)
class PreferenceOpportunity:
    """A dated, caller-supplied opportunity described by exact features."""

    opportunity_id: OpportunityId
    considered_at: WorldMoment
    features: tuple[PreferenceFeature, ...]

    def __post_init__(self) -> None:
        validate_id(self.opportunity_id, kind="preference opportunity ID")
        if not isinstance(self.considered_at, WorldMoment):
            raise TypeError("preference opportunity requires a world moment")
        if not isinstance(self.features, tuple) or not self.features:
            raise TypeError("preference opportunity requires an immutable feature tuple")
        if any(not isinstance(item, PreferenceFeature) for item in self.features):
            raise TypeError("preference opportunity contains an invalid feature")
        keys = tuple(_feature_key(item) for item in self.features)
        if len(keys) != len(set(keys)):
            raise ValueError("preference opportunity features cannot repeat")
        canonical = tuple(sorted(self.features, key=_feature_key))
        object.__setattr__(self, "features", canonical)


@dataclass(frozen=True)
class PreferenceReading:
    """An exact feature read, retaining unknown separately from open."""

    feature: PreferenceFeature
    stance: PreferenceStance | None
    preference_id: PreferenceId | None
    source_event_id: EventId | None
    stated_at: WorldMoment | None
    salience: float | None
    certainty: float | None

    def __post_init__(self) -> None:
        if not isinstance(self.feature, PreferenceFeature):
            raise TypeError("preference reading requires an exact typed feature")
        values = (
            self.stance,
            self.preference_id,
            self.source_event_id,
            self.stated_at,
            self.salience,
            self.certainty,
        )
        if all(item is None for item in values):
            return
        if any(item is None for item in values):
            raise ValueError("known preference readings require complete source evidence")
        if not isinstance(self.stance, PreferenceStance):
            raise TypeError("known preference reading requires an explicit stance")
        validate_id(self.preference_id, kind="preference reading ID")  # type: ignore[arg-type]
        validate_id(self.source_event_id, kind="preference reading source event ID")  # type: ignore[arg-type]
        if not isinstance(self.stated_at, WorldMoment):
            raise TypeError("known preference reading requires its source moment")
        _unit_interval(self.salience, "preference reading salience")  # type: ignore[arg-type]
        _unit_interval(self.certainty, "preference reading certainty")  # type: ignore[arg-type]


@dataclass(frozen=True)
class PreferenceAssessment:
    """Read-only, as-of evidence for one person considering one opportunity."""

    person_id: PersonId
    opportunity_id: OpportunityId
    considered_at: WorldMoment
    readings: tuple[PreferenceReading, ...]

    def __post_init__(self) -> None:
        validate_id(self.person_id, kind="preference assessment person ID")
        validate_id(self.opportunity_id, kind="preference assessment opportunity ID")
        if not isinstance(self.considered_at, WorldMoment):
            raise TypeError("preference assessment requires its opportunity moment")
        if not isinstance(self.readings, tuple) or any(
            not isinstance(item, PreferenceReading) for item in self.readings
        ):
            raise TypeError("preference assessment readings must be an immutable tuple")
        if not self.readings:
            raise ValueError("preference assessment requires at least one opportunity feature")
        keys = tuple(_feature_key(item.feature) for item in self.readings)
        if tuple(sorted(keys)) != keys or len(keys) != len(set(keys)):
            raise ValueError("preference assessment readings must be unique and canonical")
        for item in self.readings:
            if item.stated_at is not None:
                if item.stated_at > self.considered_at:
                    raise ValueError("preference assessment cannot reveal a future statement")
                if item.preference_id != _preference_id(
                    self.person_id,
                    item.source_event_id,  # type: ignore[arg-type]
                    item.feature,
                ):
                    raise ValueError(
                        "preference reading ID does not match its person, source and feature"
                    )


def new_self_reported_preference(
    *,
    person_id: PersonId,
    source_event_id: EventId,
    at: WorldMoment,
    feature: PreferenceFeature,
    stance: PreferenceStance,
    salience: float,
    certainty: float,
) -> SelfReportedPreference:
    """Create a preference only from an explicitly supplied person's statement."""

    validate_id(person_id, kind="preference owner ID")
    validate_id(source_event_id, kind="preference statement event ID")
    if not isinstance(feature, PreferenceFeature):
        raise TypeError("preference statement requires an exact typed feature")
    return SelfReportedPreference(
        _preference_id(person_id, source_event_id, feature),
        person_id,
        source_event_id,
        at,
        feature,
        stance,
        salience,
        certainty,
    )


def record_self_reported_preference(
    history: PersonalPreferenceHistory,
    statement: SelfReportedPreference,
) -> PersonalPreferenceHistory:
    """Append one statement once, preserving the original world chronology."""

    if not isinstance(history, PersonalPreferenceHistory) or not isinstance(
        statement, SelfReportedPreference
    ):
        raise TypeError("preference recording requires a history and self-reported statement")
    if statement.person_id != history.person_id:
        raise ValueError("preference statement belongs to another person")
    prior = next((item for item in history.statements
                  if item.preference_id == statement.preference_id), None)
    if prior is not None:
        if prior == statement:
            return history
        raise ValueError("preference ID was reused with conflicting statement content")
    if history.statements and statement.at < history.statements[-1].at:
        raise ValueError("preference statements must be recorded in world chronology")
    return replace(
        history,
        statements=tuple(sorted(history.statements + (statement,), key=_statement_key)),
    )


def assess_opportunity_preferences(
    history: PersonalPreferenceHistory,
    *,
    person_id: PersonId,
    opportunity: PreferenceOpportunity,
) -> PreferenceAssessment:
    """Return the latest known exact-feature preferences without scoring them."""

    if not isinstance(history, PersonalPreferenceHistory):
        raise TypeError("opportunity assessment requires a personal preference history")
    if not isinstance(opportunity, PreferenceOpportunity):
        raise TypeError("opportunity assessment requires a dated preference opportunity")
    validate_id(person_id, kind="preference assessment person ID")
    if history.person_id != person_id:
        raise ValueError("preference history belongs to another person")
    latest: dict[PreferenceFeature, SelfReportedPreference] = {}
    for statement in history.statements:
        if statement.at <= opportunity.considered_at:
            latest[statement.feature] = statement
    readings = []
    for feature in opportunity.features:
        statement = latest.get(feature)
        if statement is None:
            readings.append(PreferenceReading(feature, None, None, None, None, None, None))
        else:
            readings.append(PreferenceReading(
                feature,
                statement.stance,
                statement.preference_id,
                statement.source_event_id,
                statement.at,
                statement.salience,
                statement.certainty,
            ))
    return PreferenceAssessment(
        person_id,
        opportunity.opportunity_id,
        opportunity.considered_at,
        tuple(readings),
    )


def _unit_interval(value: float, name: str) -> None:
    if type(value) not in (float, int) or not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be finite and between zero and one")
