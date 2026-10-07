"""Evidence-backed relationships and once-only personal experience appraisal.

This is a headless P13 domain boundary. It stores explicit appraisals and their
bounded effects; it does not infer private reactions from football ability,
age, nationality, role or status. The small per-experience effect ceiling is a
provisional safety bound, not a calibrated psychological measurement.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from enum import Enum
from typing import NewType

from games.touchline.esb.ids import EventId, derive_id, validate_id
from games.touchline.esb.time import WorldDate

PersonId = NewType("PersonId", str)
ExperienceId = NewType("ExperienceId", str)

MAX_RELATIONSHIP_DELTA = 0.05
MAX_PERSONAL_EFFECT = 0.05


class RelationshipDimension(str, Enum):
    AFFINITY = "affinity"
    TRUST = "trust"
    RESPECT = "respect"
    RIVALRY = "rivalry"
    CONFLICT = "conflict"


class PersonalDimension(str, Enum):
    CONFIDENCE = "confidence"
    FRUSTRATION = "frustration"
    MOTIVATION = "motivation"
    PRESSURE = "pressure"
    BELONGING = "belonging"


class AwarenessBasis(str, Enum):
    DIRECT = "direct"
    REPORTED = "reported"
    RUMOURED = "rumoured"


@dataclass(frozen=True, order=True)
class WorldMoment:
    """A dated world event with a stable tie-break sequence for that date."""

    on: WorldDate
    sequence: int

    def __post_init__(self) -> None:
        if not isinstance(self.on, WorldDate):
            raise TypeError("world moment requires a WorldDate")
        if type(self.sequence) is not int or self.sequence < 0:
            raise ValueError("world moment sequence must be a non-negative integer")


@dataclass(frozen=True)
class RelationshipDimensionValue:
    dimension: RelationshipDimension
    value: float
    supporting_event_ids: tuple[EventId, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.dimension, RelationshipDimension):
            raise TypeError("relationship value requires a supported dimension")
        _bounded(self.value, 0.0, 1.0, "relationship value")
        _unique_ids(self.supporting_event_ids, "relationship value evidence", allow_empty=False)


@dataclass(frozen=True)
class RelationshipEvidence:
    event_id: EventId
    at: WorldMoment
    dimension: RelationshipDimension
    delta: float
    before: float
    after: float
    direct_contact: bool

    def __post_init__(self) -> None:
        validate_id(self.event_id, kind="relationship evidence event ID")
        if not isinstance(self.at, WorldMoment):
            raise TypeError("relationship evidence requires a world moment")
        if not isinstance(self.dimension, RelationshipDimension):
            raise TypeError("relationship evidence requires a supported dimension")
        _bounded(self.delta, -MAX_RELATIONSHIP_DELTA, MAX_RELATIONSHIP_DELTA,
                 "relationship evidence delta")
        _bounded(self.before, 0.0, 1.0, "relationship evidence before value")
        _bounded(self.after, 0.0, 1.0, "relationship evidence after value")
        if type(self.direct_contact) is not bool:
            raise TypeError("relationship contact flag must be explicit")
        expected = _clamp(float(self.before) + float(self.delta))
        if not math.isclose(float(self.after), expected, rel_tol=0.0, abs_tol=1e-8):
            raise ValueError("relationship evidence after value does not match its bounded delta")


@dataclass(frozen=True)
class RelationshipKnowledge:
    """One observer's sourced estimate; it is never copied from world truth."""

    disclosure_id: str
    observer_id: str
    dimension: RelationshipDimension
    perceived_value: float
    confidence: float
    at: WorldMoment
    supporting_event_ids: tuple[EventId, ...]

    def __post_init__(self) -> None:
        validate_id(self.disclosure_id, kind="relationship disclosure ID")
        validate_id(self.observer_id, kind="relationship observer ID")
        if not isinstance(self.dimension, RelationshipDimension):
            raise TypeError("relationship knowledge requires a supported dimension")
        _bounded(self.perceived_value, 0.0, 1.0, "perceived relationship value")
        _bounded(self.confidence, 0.0, 1.0, "relationship knowledge confidence")
        if not isinstance(self.at, WorldMoment):
            raise TypeError("relationship knowledge requires an observation moment")
        _unique_ids(self.supporting_event_ids, "relationship knowledge evidence", allow_empty=False)


@dataclass(frozen=True)
class RelationshipEdge:
    """One directed relationship; the reverse direction is a separate record."""

    source_person_id: PersonId
    target_person_id: PersonId
    dimensions: tuple[RelationshipDimensionValue, ...]
    supporting_event_ids: tuple[EventId, ...]
    evidence: tuple[RelationshipEvidence, ...] = ()
    last_contact_at: WorldMoment | None = None
    observer_knowledge: tuple[RelationshipKnowledge, ...] = ()

    def __post_init__(self) -> None:
        validate_id(self.source_person_id, kind="relationship source person ID")
        validate_id(self.target_person_id, kind="relationship target person ID")
        if self.source_person_id == self.target_person_id:
            raise ValueError("a relationship edge must connect two different people")
        if not isinstance(self.dimensions, tuple) or not self.dimensions:
            raise TypeError("relationship dimensions must be a non-empty immutable tuple")
        if any(not isinstance(item, RelationshipDimensionValue) for item in self.dimensions):
            raise TypeError("relationship edge contains an invalid dimension value")
        dimensions = [item.dimension for item in self.dimensions]
        if len(dimensions) != len(set(dimensions)):
            raise ValueError("relationship dimensions cannot be repeated")
        _unique_ids(self.supporting_event_ids, "relationship edge evidence", allow_empty=False)
        if not isinstance(self.evidence, tuple) or any(
            not isinstance(item, RelationshipEvidence) for item in self.evidence
        ):
            raise TypeError("relationship evidence must be an immutable tuple")
        evidence_ids = [item.event_id for item in self.evidence]
        evidence_keys = [(item.event_id, item.dimension) for item in self.evidence]
        if len(evidence_keys) != len(set(evidence_keys)):
            raise ValueError("one event cannot update one relationship dimension twice")
        support_ids = set(self.supporting_event_ids)
        if set(evidence_ids) != support_ids:
            raise ValueError("edge evidence must match its recorded relationship updates")
        for item in self.dimensions:
            if not set(item.supporting_event_ids).issubset(support_ids):
                raise ValueError("dimension evidence must be included in edge evidence")
        if not isinstance(self.observer_knowledge, tuple) or any(
            not isinstance(item, RelationshipKnowledge) for item in self.observer_knowledge
        ):
            raise TypeError("observer knowledge must be an immutable tuple")
        disclosure_ids = [item.disclosure_id for item in self.observer_knowledge]
        if len(disclosure_ids) != len(set(disclosure_ids)):
            raise ValueError("relationship disclosure IDs cannot be repeated")
        if any(not set(item.supporting_event_ids).issubset(support_ids)
               for item in self.observer_knowledge):
            raise ValueError("observer knowledge must cite relationship edge evidence")
        attributed = set(evidence_ids)
        for item in self.dimensions:
            attributed.update(item.supporting_event_ids)
        for item in self.observer_knowledge:
            attributed.update(item.supporting_event_ids)
        if attributed != support_ids:
            raise ValueError("edge evidence must be attributed to a dimension, update or disclosure")
        for item in self.evidence:
            if item.dimension not in dimensions:
                raise ValueError("relationship update references an unrecorded dimension")
        order_keys = tuple((item.at, str(item.event_id), item.dimension.value) for item in self.evidence)
        if tuple(sorted(order_keys)) != order_keys:
            raise ValueError("relationship evidence must retain world chronology")
        by_moment: dict[WorldMoment, set[EventId]] = {}
        by_event: dict[EventId, set[WorldMoment]] = {}
        for item in self.evidence:
            by_moment.setdefault(item.at, set()).add(item.event_id)
            by_event.setdefault(item.event_id, set()).add(item.at)
        if any(len(event_ids) > 1 for event_ids in by_moment.values()):
            raise ValueError("a world moment cannot identify multiple source events")
        if any(len(moments) > 1 for moments in by_event.values()):
            raise ValueError("one relationship source event cannot occupy multiple world moments")
        latest_by_dimension: dict[RelationshipDimension, RelationshipEvidence] = {}
        dimension_support = {
            item.dimension: set(item.supporting_event_ids) for item in self.dimensions
        }
        for item in self.evidence:
            prior = latest_by_dimension.get(item.dimension)
            if prior is not None and not math.isclose(
                float(prior.after), float(item.before), rel_tol=0.0, abs_tol=1e-8
            ):
                raise ValueError("relationship evidence chain has a discontinuity")
            latest_by_dimension[item.dimension] = item
            if item.event_id not in dimension_support[item.dimension]:
                raise ValueError("dimension state must cite each event that changed it")
        current_values = {item.dimension: float(item.value) for item in self.dimensions}
        for dimension, latest in latest_by_dimension.items():
            if not math.isclose(current_values[dimension], float(latest.after), rel_tol=0.0, abs_tol=1e-8):
                raise ValueError("relationship value does not match its latest evidence")
        expected_last_contact = max(
            (item.at for item in self.evidence if item.direct_contact), default=None
        )
        if self.last_contact_at != expected_last_contact:
            raise ValueError("last contact must come from recorded direct-contact evidence")


@dataclass(frozen=True)
class PersonalStateValue:
    dimension: PersonalDimension
    value: float

    def __post_init__(self) -> None:
        if not isinstance(self.dimension, PersonalDimension):
            raise TypeError("personal state requires a supported dimension")
        _bounded(self.value, 0.0, 1.0, "personal state value")


@dataclass(frozen=True)
class PersonalState:
    person_id: PersonId
    dimensions: tuple[PersonalStateValue, ...]

    def __post_init__(self) -> None:
        validate_id(self.person_id, kind="personal state person ID")
        if not isinstance(self.dimensions, tuple) or any(
            not isinstance(item, PersonalStateValue) for item in self.dimensions
        ):
            raise TypeError("personal state dimensions must be an immutable tuple")
        names = [item.dimension for item in self.dimensions]
        if set(names) != set(PersonalDimension) or len(names) != len(PersonalDimension):
            raise ValueError("personal state must provide each supported dimension exactly once")


@dataclass(frozen=True)
class PersonalAdjustment:
    """An explicit individual appraisal response and dimension sensitivity."""

    dimension: PersonalDimension
    response: float
    sensitivity: float

    def __post_init__(self) -> None:
        if not isinstance(self.dimension, PersonalDimension):
            raise TypeError("personal adjustment requires a supported state dimension")
        _bounded(self.response, -1.0, 1.0, "appraisal response")
        _bounded(self.sensitivity, 0.0, 1.0, "appraisal sensitivity")


@dataclass(frozen=True)
class PersonalAppraisal:
    assessed_at: WorldMoment
    confidence: float
    salience: float
    adjustments: tuple[PersonalAdjustment, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.assessed_at, WorldMoment):
            raise TypeError("personal appraisal requires a world moment")
        _bounded(self.confidence, 0.0, 1.0, "appraisal confidence")
        _bounded(self.salience, 0.0, 1.0, "appraisal salience")
        if not isinstance(self.adjustments, tuple) or any(
            not isinstance(item, PersonalAdjustment) for item in self.adjustments
        ):
            raise TypeError("appraisal adjustments must be an immutable tuple")
        dimensions = [item.dimension for item in self.adjustments]
        if len(dimensions) != len(set(dimensions)):
            raise ValueError("an appraisal can adjust each personal dimension at most once")


@dataclass(frozen=True)
class PersonalStateChange:
    dimension: PersonalDimension
    before: float
    requested_delta: float
    after: float
    applied_delta: float

    def __post_init__(self) -> None:
        if not isinstance(self.dimension, PersonalDimension):
            raise TypeError("personal state change requires a supported dimension")
        _bounded(self.before, 0.0, 1.0, "personal state before value")
        _bounded(self.requested_delta, -MAX_PERSONAL_EFFECT, MAX_PERSONAL_EFFECT,
                 "personal state requested delta")
        _bounded(self.after, 0.0, 1.0, "personal state after value")
        _bounded(self.applied_delta, -MAX_PERSONAL_EFFECT, MAX_PERSONAL_EFFECT,
                 "personal state applied delta")
        expected_after = _clamp(float(self.before) + float(self.requested_delta))
        if not math.isclose(float(self.after), expected_after, rel_tol=0.0, abs_tol=1e-8):
            raise ValueError("personal state result does not match its bounded requested delta")
        if not math.isclose(float(self.applied_delta), float(self.after) - float(self.before),
                            rel_tol=0.0, abs_tol=1e-8):
            raise ValueError("personal state applied delta does not match before/after values")


@dataclass(frozen=True)
class PersonalExperience:
    experience_id: ExperienceId
    person_id: PersonId
    cause_event_id: EventId
    occurred_at: WorldMoment
    awareness: AwarenessBasis
    awareness_at: WorldMoment
    appraisal: PersonalAppraisal | None = None
    state_changes: tuple[PersonalStateChange, ...] = ()
    processed: bool = False

    def __post_init__(self) -> None:
        validate_id(self.experience_id, kind="personal experience ID")
        validate_id(self.person_id, kind="personal experience person ID")
        validate_id(self.cause_event_id, kind="personal experience cause event ID")
        if not isinstance(self.occurred_at, WorldMoment) or not isinstance(self.awareness_at, WorldMoment):
            raise TypeError("personal experience requires occurrence and awareness moments")
        if self.awareness_at < self.occurred_at:
            raise ValueError("awareness cannot precede the cause event")
        if not isinstance(self.awareness, AwarenessBasis):
            raise TypeError("personal experience awareness basis is required")
        if self.appraisal is not None:
            if not isinstance(self.appraisal, PersonalAppraisal):
                raise TypeError("personal experience appraisal has an invalid type")
            if self.appraisal.assessed_at < self.awareness_at:
                raise ValueError("an experience cannot be appraised before it is known")
        if not isinstance(self.state_changes, tuple) or any(
            not isinstance(item, PersonalStateChange) for item in self.state_changes
        ):
            raise TypeError("personal state changes must be an immutable tuple")
        if type(self.processed) is not bool:
            raise TypeError("personal experience processed flag must be explicit")
        if self.processed != (self.appraisal is not None):
            raise ValueError("processed experiences must retain exactly one appraisal")
        if self.processed:
            actual = {item.dimension for item in self.state_changes}
            assessed = {item.dimension for item in self.appraisal.adjustments}  # type: ignore[union-attr]
            if actual != assessed:
                raise ValueError("personal experience must retain every appraised state dimension")
            adjustments = {
                item.dimension: item for item in self.appraisal.adjustments  # type: ignore[union-attr]
            }
            for change in self.state_changes:
                adjustment = adjustments[change.dimension]
                requested = round(
                    MAX_PERSONAL_EFFECT
                    * float(adjustment.response)
                    * float(adjustment.sensitivity)
                    * float(self.appraisal.confidence)  # type: ignore[union-attr]
                    * float(self.appraisal.salience),  # type: ignore[union-attr]
                    8,
                )
                if not math.isclose(
                    float(change.requested_delta), requested, rel_tol=0.0, abs_tol=1e-8
                ):
                    raise ValueError("personal state change does not match its recorded appraisal")
        elif self.state_changes:
            raise ValueError("pending personal experiences cannot claim state changes")


@dataclass(frozen=True)
class PersonalHistory:
    person_id: PersonId
    state: PersonalState
    experiences: tuple[PersonalExperience, ...] = ()
    initial_state: PersonalState | None = None

    def __post_init__(self) -> None:
        validate_id(self.person_id, kind="personal history person ID")
        if not isinstance(self.state, PersonalState) or self.state.person_id != self.person_id:
            raise ValueError("personal history state must belong to its person")
        initial_state = self.initial_state
        if initial_state is None:
            initial_state = self.state
            object.__setattr__(self, "initial_state", initial_state)
        if not isinstance(initial_state, PersonalState) or initial_state.person_id != self.person_id:
            raise ValueError("personal history initial state must belong to its person")
        if not isinstance(self.experiences, tuple) or any(
            not isinstance(item, PersonalExperience) for item in self.experiences
        ):
            raise TypeError("personal experiences must be an immutable tuple")
        ids = [item.experience_id for item in self.experiences]
        causes = [item.cause_event_id for item in self.experiences]
        if len(ids) != len(set(ids)):
            raise ValueError("personal experience IDs cannot repeat")
        if len(causes) != len(set(causes)):
            raise ValueError("one cause event cannot create duplicate personal experiences")
        if any(item.person_id != self.person_id for item in self.experiences):
            raise ValueError("personal history cannot contain another person's experience")
        if tuple(sorted(item.occurred_at for item in self.experiences)) != tuple(
            item.occurred_at for item in self.experiences
        ):
            raise ValueError("personal experiences must retain occurrence chronology")
        occurrence_moments = [item.occurred_at for item in self.experiences]
        if len(occurrence_moments) != len(set(occurrence_moments)):
            raise ValueError("personal experiences need distinct world moments")
        assessed = [item.appraisal.assessed_at for item in self.experiences if item.appraisal is not None]
        if tuple(sorted(assessed)) != tuple(assessed):
            raise ValueError("personal appraisals must retain processing chronology")
        if len(assessed) != len(set(assessed)):
            raise ValueError("personal appraisals need distinct world moments")
        running_values = {item.dimension: float(item.value) for item in initial_state.dimensions}
        for experience in self.experiences:
            if not experience.processed:
                continue
            for change in experience.state_changes:
                if not math.isclose(
                    running_values[change.dimension],
                    float(change.before),
                    rel_tol=0.0,
                    abs_tol=1e-8,
                ):
                    raise ValueError("personal state change history is discontinuous")
                running_values[change.dimension] = float(change.after)
        final_values = {item.dimension: float(item.value) for item in self.state.dimensions}
        if any(
            not math.isclose(running_values[dimension], final_values[dimension],
                             rel_tol=0.0, abs_tol=1e-8)
            for dimension in PersonalDimension
        ):
            raise ValueError("current personal state does not match recorded appraisal changes")


def new_personal_experience(
    person_id: PersonId,
    cause_event_id: EventId,
    occurred_at: WorldMoment,
    awareness: AwarenessBasis,
    awareness_at: WorldMoment,
) -> PersonalExperience:
    """Create a stable once-per-person record for one cause event."""

    validate_id(person_id, kind="personal experience person ID")
    validate_id(cause_event_id, kind="personal experience cause event ID")
    return PersonalExperience(
        experience_id=ExperienceId(
            derive_id("experience", "p13-personal-experience-v1", person_id, cause_event_id)
        ),
        person_id=person_id,
        cause_event_id=cause_event_id,
        occurred_at=occurred_at,
        awareness=awareness,
        awareness_at=awareness_at,
    )


def record_personal_experience(
    history: PersonalHistory, experience: PersonalExperience
) -> PersonalHistory:
    """Append a pending experience once; a reused cause cannot be farmed."""

    if not isinstance(history, PersonalHistory) or not isinstance(experience, PersonalExperience):
        raise TypeError("recording an experience requires personal history and experience records")
    if experience.person_id != history.person_id:
        raise ValueError("experience belongs to a different person")
    if experience.processed:
        raise ValueError("new experiences must enter the history before appraisal")
    prior = next((item for item in history.experiences
                  if item.experience_id == experience.experience_id), None)
    if prior is not None:
        if prior == experience:
            return history
        raise ValueError("personal experience ID was reused with conflicting content")
    same_cause = next((item for item in history.experiences
                       if item.cause_event_id == experience.cause_event_id), None)
    if same_cause is not None:
        raise ValueError("cause event already has a personal experience for this person")
    if history.experiences and experience.occurred_at < history.experiences[-1].occurred_at:
        raise ValueError("personal experiences must be recorded in world chronology")
    if any(item.occurred_at == experience.occurred_at for item in history.experiences):
        raise ValueError("personal experiences need distinct world moments")
    return replace(history, experiences=history.experiences + (experience,))


def appraise_personal_experience(
    history: PersonalHistory,
    experience_id: ExperienceId,
    appraisal: PersonalAppraisal,
) -> PersonalHistory:
    """Apply a sourced appraisal once and retain its exact bounded state effects.

    Each explicit response is multiplied by that dimension's supplied personal
    sensitivity, the appraiser's confidence and salience, then by the versioned
    0.05 per-experience ceiling. These inputs are intentionally independent of
    football capability and are provisional until P13 adds the life-event and
    preference mechanisms that author them.
    """

    if not isinstance(history, PersonalHistory) or not isinstance(appraisal, PersonalAppraisal):
        raise TypeError("appraisal requires personal history and appraisal records")
    validate_id(experience_id, kind="personal experience ID")
    index = next((i for i, item in enumerate(history.experiences)
                  if item.experience_id == experience_id), None)
    if index is None:
        raise ValueError("personal experience must be recorded before appraisal")
    experience = history.experiences[index]
    if experience.processed:
        if experience.appraisal == appraisal:
            return history
        raise ValueError("personal experience was already appraised with different inputs")
    if appraisal.assessed_at < experience.awareness_at:
        raise ValueError("appraisal cannot precede the person's awareness")
    if any(
        not item.processed and item.occurred_at < experience.occurred_at
        for item in history.experiences[:index]
    ):
        raise ValueError("earlier personal experiences must be appraised first")
    previous_appraisals = [item.appraisal.assessed_at for item in history.experiences
                           if item.appraisal is not None]
    if previous_appraisals and appraisal.assessed_at < max(previous_appraisals):
        raise ValueError("personal experiences must be appraised in world chronology")
    if appraisal.assessed_at in previous_appraisals:
        raise ValueError("personal appraisals need distinct world moments")

    current_values = {item.dimension: float(item.value) for item in history.state.dimensions}
    changes: list[PersonalStateChange] = []
    for adjustment in sorted(appraisal.adjustments, key=lambda item: item.dimension.value):
        before = current_values[adjustment.dimension]
        requested = round(
            MAX_PERSONAL_EFFECT
            * float(adjustment.response)
            * float(adjustment.sensitivity)
            * float(appraisal.confidence)
            * float(appraisal.salience),
            8,
        )
        after = _clamp(before + requested)
        actual = round(after - before, 8)
        changes.append(PersonalStateChange(
            dimension=adjustment.dimension,
            before=before,
            requested_delta=requested,
            after=after,
            applied_delta=actual,
        ))
        current_values[adjustment.dimension] = after

    new_state = PersonalState(
        history.person_id,
        tuple(PersonalStateValue(dimension, current_values[dimension])
              for dimension in sorted(PersonalDimension, key=lambda item: item.value)),
    )
    settled_experience = replace(
        experience,
        appraisal=appraisal,
        state_changes=tuple(changes),
        processed=True,
    )
    experiences = history.experiences[:index] + (settled_experience,) + history.experiences[index + 1:]
    return replace(history, state=new_state, experiences=experiences)


def record_relationship_evidence(
    edge: RelationshipEdge | None,
    *,
    source_person_id: PersonId,
    target_person_id: PersonId,
    dimension: RelationshipDimension,
    delta: float,
    event_id: EventId,
    at: WorldMoment,
    direct_contact: bool,
    initial_value: float | None = None,
) -> RelationshipEdge:
    """Apply one bounded directed update; first observations need an explicit prior."""

    validate_id(source_person_id, kind="relationship source person ID")
    validate_id(target_person_id, kind="relationship target person ID")
    validate_id(event_id, kind="relationship evidence event ID")
    if source_person_id == target_person_id:
        raise ValueError("a relationship edge must connect two different people")
    if not isinstance(dimension, RelationshipDimension):
        raise TypeError("relationship update requires a supported dimension")
    if not isinstance(at, WorldMoment):
        raise TypeError("relationship update requires a world moment")
    if type(direct_contact) is not bool:
        raise TypeError("relationship contact flag must be explicit")
    _bounded(delta, -MAX_RELATIONSHIP_DELTA, MAX_RELATIONSHIP_DELTA,
             "relationship update delta")

    if edge is not None:
        if not isinstance(edge, RelationshipEdge):
            raise TypeError("relationship update requires a RelationshipEdge")
        if (edge.source_person_id, edge.target_person_id) != (source_person_id, target_person_id):
            raise ValueError("relationship update cannot change edge direction or people")
        existing = next((item for item in edge.evidence
                         if item.event_id == event_id and item.dimension is dimension), None)
        if existing is not None:
            prior_matches = True
            if initial_value is not None:
                prior = _bounded(initial_value, 0.0, 1.0, "initial relationship value")
                prior_matches = math.isclose(
                    prior, float(existing.before), rel_tol=0.0, abs_tol=1e-8
                )
            matching = (
                existing.dimension is dimension
                and math.isclose(float(existing.delta), float(delta), rel_tol=0.0, abs_tol=1e-8)
                and existing.at == at
                and existing.direct_contact is direct_contact
                and prior_matches
            )
            if matching:
                return edge
            raise ValueError("relationship evidence event ID was reused with conflicting content")
        same_event = [item for item in edge.evidence if item.event_id == event_id]
        if same_event and any(item.at != at or item.direct_contact is not direct_contact for item in same_event):
            raise ValueError("relationship event ID was reused at a different moment or contact state")
        if any(item.at == at and item.event_id != event_id for item in edge.evidence):
            raise ValueError("world moment is already attributed to a different relationship event")
        if edge.evidence and at < max(item.at for item in edge.evidence):
            raise ValueError("relationship evidence must be applied in world chronology")
        values = {item.dimension: item for item in edge.dimensions}
        prior_value = values.get(dimension)
        if prior_value is None:
            if initial_value is None:
                raise ValueError("a new relationship dimension needs an explicit initial value")
            before = _bounded(initial_value, 0.0, 1.0, "initial relationship value")
            dimension_evidence: tuple[EventId, ...] = ()
        else:
            if initial_value is not None:
                raise ValueError("initial relationship value only applies to a new dimension")
            before = float(prior_value.value)
            dimension_evidence = prior_value.supporting_event_ids
        prior_values = edge.dimensions
        prior_support = edge.supporting_event_ids
        prior_evidence = edge.evidence
        prior_knowledge = edge.observer_knowledge
    else:
        if initial_value is None:
            raise ValueError("first relationship evidence requires an explicit initial value")
        before = _bounded(initial_value, 0.0, 1.0, "initial relationship value")
        dimension_evidence = ()
        prior_values = ()
        prior_support = ()
        prior_evidence = ()
        prior_knowledge = ()

    after = _clamp(before + float(delta))
    change = RelationshipEvidence(event_id, at, dimension, float(delta), before, after, direct_contact)
    dimension_value = RelationshipDimensionValue(
        dimension, after, dimension_evidence + (event_id,)
    )
    values_by_dimension = {item.dimension: item for item in prior_values}
    values_by_dimension[dimension] = dimension_value
    dimensions = tuple(values_by_dimension[key] for key in sorted(values_by_dimension, key=lambda item: item.value))
    evidence = tuple(sorted(
        prior_evidence + (change,),
        key=lambda item: (item.at, str(item.event_id), item.dimension.value),
    ))
    last_contact = max((item.at for item in evidence if item.direct_contact), default=None)
    return RelationshipEdge(
        source_person_id=source_person_id,
        target_person_id=target_person_id,
        dimensions=dimensions,
        supporting_event_ids=prior_support if event_id in prior_support else prior_support + (event_id,),
        evidence=evidence,
        last_contact_at=last_contact,
        observer_knowledge=prior_knowledge,
    )


def record_relationship_knowledge(
    edge: RelationshipEdge, knowledge: RelationshipKnowledge
) -> RelationshipEdge:
    """Attach an explicit observer estimate only when it cites known edge evidence."""

    if not isinstance(edge, RelationshipEdge) or not isinstance(knowledge, RelationshipKnowledge):
        raise TypeError("relationship disclosure requires an edge and knowledge record")
    if knowledge.dimension not in {item.dimension for item in edge.dimensions}:
        raise ValueError("observer knowledge cannot disclose an unrecorded dimension")
    if not set(knowledge.supporting_event_ids).issubset(edge.supporting_event_ids):
        raise ValueError("observer knowledge must cite evidence already recorded on the edge")
    source_moments = [item.at for item in edge.evidence
                      if item.event_id in knowledge.supporting_event_ids]
    if source_moments and knowledge.at < max(source_moments):
        raise ValueError("observer knowledge cannot precede its cited evidence")
    prior = next((item for item in edge.observer_knowledge
                  if item.disclosure_id == knowledge.disclosure_id), None)
    if prior is not None:
        if prior == knowledge:
            return edge
        raise ValueError("relationship disclosure ID was reused with conflicting content")
    return replace(edge, observer_knowledge=edge.observer_knowledge + (knowledge,))


def _bounded(value: float, low: float, high: float, label: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{label} must be finite and in [{low}, {high}]")
    return float(value)


def _clamp(value: float) -> float:
    return round(min(1.0, max(0.0, value)), 8)


def _unique_ids(values: tuple[str, ...], label: str, *, allow_empty: bool = True) -> None:
    if not isinstance(values, tuple):
        raise TypeError(f"{label} must be an immutable tuple")
    if not allow_empty and not values:
        raise ValueError(f"{label} must not be empty")
    for value in values:
        validate_id(value, kind=label)
    if len(values) != len(set(values)):
        raise ValueError(f"{label} cannot repeat an ID")


__all__ = [
    "AwarenessBasis",
    "ExperienceId",
    "MAX_PERSONAL_EFFECT",
    "MAX_RELATIONSHIP_DELTA",
    "PersonalAdjustment",
    "PersonalAppraisal",
    "PersonalDimension",
    "PersonalExperience",
    "PersonalHistory",
    "PersonalState",
    "PersonalStateChange",
    "PersonalStateValue",
    "PersonId",
    "RelationshipDimension",
    "RelationshipDimensionValue",
    "RelationshipEdge",
    "RelationshipEvidence",
    "RelationshipKnowledge",
    "WorldMoment",
    "appraise_personal_experience",
    "new_personal_experience",
    "record_personal_experience",
    "record_relationship_evidence",
    "record_relationship_knowledge",
]
