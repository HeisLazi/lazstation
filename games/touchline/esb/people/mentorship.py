"""Evidence-backed mentorship activation, contacts and focus learning.

An accepted offer creates only an introduction until a named pair agree on
focuses and activate it. A mentorship record alone teaches nothing: learning
requires a completed contact with caller-asserted practice examples, time and
feedback. Example IDs and repetitions are not resolved against match history.
All coefficients below are explicit provisional mechanics, not psychological
or coaching research claims.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from enum import Enum
from typing import NewType

from games.touchline.esb.ids import EventId, derive_id, validate_id
from games.touchline.esb.people import PlayerProfile
from games.touchline.esb.people.learning import learning_adaptability
from games.touchline.esb.people.relationships import (
    MAX_RELATIONSHIP_DELTA,
    PersonId,
    RelationshipDimension,
    RelationshipEdge,
    WorldMoment,
    record_relationship_evidence,
)
from games.touchline.esb.people.social import (
    MENTOR_TRUST_THRESHOLD,
    MentorCapacity,
    OfferKind,
    OfferStatus,
    SocialLedger,
    SocialOffer,
)
from games.touchline.esb.time import WorldDate

MentorshipId = NewType("MentorshipId", str)

MIN_CONTACT_MINUTES = 15
MAX_DAILY_CONTACT_MINUTES = 240
MAX_CONTACT_REPETITIONS = 100
MAX_CONTACT_LEARNING_GAIN = 0.05
MAX_MENTOR_TRUST_EVIDENCE_AGE_DAYS = 30
MENTORSHIP_FORMULA_VERSION = "p13c-focus-learning-v1"
BASE_FOCUS_LEARNING_PER_REPETITION = 0.001
MIN_MENTOR_FOCUS_COMPETENCE = 0.55
MIN_MENTEE_FOCUS_INTEREST = 0.40
TRUST_FEEDBACK_SCALE = 0.02


class MentorshipFocus(str, Enum):
    SCANNING = "scanning"
    DECISION_MAKING = "decision_making"
    RECEIVING = "receiving"
    PASSING = "passing"
    POSITIONING = "positioning"
    COMMUNICATION = "communication"
    PERSONAL_WELLBEING = "personal_wellbeing"


class MentorshipOrigin(str, Enum):
    PLAYER_INITIATED = "player_initiated"


class MentorshipStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    ENDED = "ended"


class MentorshipAction(str, Enum):
    ACTIVATE = "activate"
    PAUSE = "pause"
    RESUME = "resume"
    END = "end"


def _normalized(value: float, label: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"{label} must be finite and normalized to [0, 1]")
    return float(value)


def _reason(value: str) -> str:
    validate_id(value, kind="mentorship reason code")
    return value


def _expected_transition_id(
    mentorship_id: MentorshipId,
    action: MentorshipAction,
    at: WorldMoment,
    actor_id: PersonId,
    reason: str,
) -> EventId:
    return EventId(derive_id(
        "event", "touchline-mentorship-transition-v1", str(mentorship_id),
        action.value, at.on.isoformat, str(at.sequence), str(actor_id), reason,
    ))


@dataclass(frozen=True)
class FocusAgreement:
    """A focus both people selected, with separate supporting observations."""

    focus: MentorshipFocus
    mentor_id: PersonId
    mentee_id: PersonId
    mentor_evidence_id: EventId
    mentee_evidence_id: EventId
    mentor_competence: float
    mentee_interest: float
    assessed_at: WorldMoment

    def __post_init__(self) -> None:
        if not isinstance(self.focus, MentorshipFocus):
            raise TypeError("mentorship focus must be explicit")
        validate_id(self.mentor_id, kind="focus agreement mentor ID")
        validate_id(self.mentee_id, kind="focus agreement mentee ID")
        if self.mentor_id == self.mentee_id:
            raise ValueError("focus agreement requires two distinct participants")
        validate_id(self.mentor_evidence_id, kind="mentor focus evidence ID")
        validate_id(self.mentee_evidence_id, kind="mentee focus evidence ID")
        if self.mentor_evidence_id == self.mentee_evidence_id:
            raise ValueError("mentor competence and mentee interest need distinct evidence")
        if not isinstance(self.assessed_at, WorldMoment):
            raise TypeError("focus agreement requires an assessment moment")
        _normalized(self.mentor_competence, "mentor focus competence")
        _normalized(self.mentee_interest, "mentee focus interest")
        if self.mentor_competence < MIN_MENTOR_FOCUS_COMPETENCE:
            raise ValueError("a selected focus needs sufficient mentor competence")
        if self.mentee_interest < MIN_MENTEE_FOCUS_INTEREST:
            raise ValueError("a selected focus needs sufficient mentee interest")


@dataclass(frozen=True)
class MentorshipTransition:
    event_id: EventId
    action: MentorshipAction
    at: WorldMoment
    actor_id: PersonId
    reason: str

    def __post_init__(self) -> None:
        validate_id(self.event_id, kind="mentorship transition event ID")
        if not isinstance(self.action, MentorshipAction):
            raise TypeError("mentorship transition action must be explicit")
        if not isinstance(self.at, WorldMoment):
            raise TypeError("mentorship transition requires a world moment")
        validate_id(self.actor_id, kind="mentorship transition actor ID")
        _reason(self.reason)


@dataclass(frozen=True)
class Mentorship:
    mentorship_id: MentorshipId
    offer_id: str
    source_event_id: EventId
    mentor_id: PersonId
    mentee_id: PersonId
    origin: MentorshipOrigin
    accepted_at: WorldMoment
    activation_trust_evidence_ids: tuple[EventId, ...]
    focus_agreements: tuple[FocusAgreement, ...]
    transitions: tuple[MentorshipTransition, ...]

    def __post_init__(self) -> None:
        validate_id(self.mentorship_id, kind="mentorship ID")
        validate_id(self.offer_id, kind="mentorship source offer ID")
        validate_id(self.source_event_id, kind="mentorship source event ID")
        validate_id(self.mentor_id, kind="mentorship mentor ID")
        validate_id(self.mentee_id, kind="mentorship mentee ID")
        if self.mentor_id == self.mentee_id:
            raise ValueError("mentorship participants must be different people")
        if self.origin is not MentorshipOrigin.PLAYER_INITIATED:
            raise ValueError("this slice only activates player-initiated accepted offers")
        if not isinstance(self.accepted_at, WorldMoment):
            raise TypeError("mentorship requires the accepted offer moment")
        if not isinstance(self.activation_trust_evidence_ids, tuple) or not self.activation_trust_evidence_ids:
            raise TypeError("mentorship activation must cite current directed trust evidence")
        for event_id in self.activation_trust_evidence_ids:
            validate_id(event_id, kind="activation trust evidence ID")
        if len(self.activation_trust_evidence_ids) != len(set(self.activation_trust_evidence_ids)):
            raise ValueError("activation trust evidence cannot repeat")
        if not isinstance(self.focus_agreements, tuple) or not self.focus_agreements:
            raise TypeError("mentorship requires immutable, non-empty focus agreements")
        if any(not isinstance(item, FocusAgreement) for item in self.focus_agreements):
            raise TypeError("mentorship focus agreements contain an invalid record")
        focuses = [item.focus for item in self.focus_agreements]
        if len(focuses) != len(set(focuses)):
            raise ValueError("mentorship focuses cannot repeat")
        if not isinstance(self.transitions, tuple) or not self.transitions:
            raise TypeError("mentorship requires an immutable transition history")
        if any(not isinstance(item, MentorshipTransition) for item in self.transitions):
            raise TypeError("mentorship transitions contain an invalid record")
        transition_ids = [item.event_id for item in self.transitions]
        if len(transition_ids) != len(set(transition_ids)):
            raise ValueError("mentorship transition events cannot repeat")
        if tuple(sorted(self.transitions, key=lambda item: (item.at, str(item.event_id)))) != self.transitions:
            raise ValueError("mentorship transitions must retain world chronology")
        if self.transitions[0].action is not MentorshipAction.ACTIVATE:
            raise ValueError("mentorship history must begin with activation")
        if self.transitions[0].at <= self.accepted_at:
            raise ValueError("mentorship activation must follow the accepted offer")
        if any(item.assessed_at >= self.transitions[0].at for item in self.focus_agreements):
            raise ValueError("mentorship focus agreements must precede activation")
        if any(item.assessed_at <= self.accepted_at for item in self.focus_agreements):
            raise ValueError("mentorship focus agreements must follow accepted consent")
        if any(
            item.mentor_id != self.mentor_id or item.mentee_id != self.mentee_id
            for item in self.focus_agreements
        ):
            raise ValueError("focus agreements must name the mentorship participants")
        if any(item.actor_id not in (self.mentor_id, self.mentee_id) for item in self.transitions):
            raise ValueError("only a mentorship participant can change its state")
        prior_action: MentorshipAction | None = None
        for index, transition in enumerate(self.transitions):
            if transition.event_id != _expected_transition_id(
                self.mentorship_id, transition.action, transition.at,
                transition.actor_id, transition.reason,
            ):
                raise ValueError("mentorship transition ID does not match its action")
            if index == 0:
                prior_action = transition.action
                continue
            allowed = {
                MentorshipAction.PAUSE: (MentorshipAction.ACTIVATE, MentorshipAction.RESUME),
                MentorshipAction.RESUME: MentorshipAction.PAUSE,
                MentorshipAction.END: (MentorshipAction.ACTIVATE, MentorshipAction.PAUSE,
                                       MentorshipAction.RESUME),
            }
            if transition.action not in allowed or prior_action not in (
                allowed[transition.action] if isinstance(allowed[transition.action], tuple)
                else (allowed[transition.action],)
            ):
                raise ValueError("mentorship state transition is not allowed")
            prior_action = transition.action

    @property
    def status(self) -> MentorshipStatus:
        return {
            MentorshipAction.ACTIVATE: MentorshipStatus.ACTIVE,
            MentorshipAction.PAUSE: MentorshipStatus.PAUSED,
            MentorshipAction.RESUME: MentorshipStatus.ACTIVE,
            MentorshipAction.END: MentorshipStatus.ENDED,
        }[self.transitions[-1].action]

    @property
    def started_at(self) -> WorldMoment:
        return self.transitions[0].at


@dataclass(frozen=True)
class MentorTimeBudget:
    mentor_id: PersonId
    on: WorldDate
    available_minutes: int
    existing_commitments_minutes: int = 0

    def __post_init__(self) -> None:
        validate_id(self.mentor_id, kind="mentor time-budget person ID")
        if not isinstance(self.on, WorldDate):
            raise TypeError("mentor time budget requires a calendar date")
        for label, value in (
            ("available mentor minutes", self.available_minutes),
            ("existing mentor commitments", self.existing_commitments_minutes),
        ):
            if type(value) is not int or value < 0 or value > MAX_DAILY_CONTACT_MINUTES:
                raise ValueError(f"{label} must be an integer in [0, {MAX_DAILY_CONTACT_MINUTES}]")

    @property
    def remaining_minutes(self) -> int:
        return max(0, self.available_minutes - self.existing_commitments_minutes)


@dataclass(frozen=True)
class DemonstratedBehavior:
    """Caller-asserted practice evidence attached to a focus-specific contact.

    The event ID and repetition count are validated and deduplicated within
    the mentorship ledger, but this slice does not resolve them against an
    authoritative match or training history.
    """

    event_id: EventId
    at: WorldMoment
    focus: MentorshipFocus
    participants: tuple[PersonId, PersonId]
    meaningful_repetitions: int

    def __post_init__(self) -> None:
        validate_id(self.event_id, kind="demonstrated behavior event ID")
        if not isinstance(self.at, WorldMoment):
            raise TypeError("demonstrated behavior requires a world moment")
        if not isinstance(self.focus, MentorshipFocus):
            raise TypeError("demonstrated behavior requires an explicit focus")
        if not isinstance(self.participants, tuple) or len(self.participants) != 2:
            raise TypeError("demonstrated behavior requires an immutable participant pair")
        for person_id in self.participants:
            validate_id(person_id, kind="demonstrated behavior participant ID")
        if self.participants[0] == self.participants[1]:
            raise ValueError("demonstrated behavior requires different participants")
        if type(self.meaningful_repetitions) is not int or not 1 <= self.meaningful_repetitions <= MAX_CONTACT_REPETITIONS:
            raise ValueError(f"demonstrated repetitions must be in 1..{MAX_CONTACT_REPETITIONS}")


@dataclass(frozen=True)
class MentorshipContact:
    contact_id: EventId
    mentorship_id: MentorshipId
    at: WorldMoment
    focus: MentorshipFocus
    duration_minutes: int
    examples: tuple[DemonstratedBehavior, ...]
    mentor_clarity: float
    mentee_usefulness: float
    mentor_trust_feedback: float
    mentee_trust_feedback: float
    learner_adaptability: float
    time_budget: MentorTimeBudget

    def __post_init__(self) -> None:
        validate_id(self.contact_id, kind="mentorship contact event ID")
        validate_id(self.mentorship_id, kind="mentorship contact mentorship ID")
        if not isinstance(self.at, WorldMoment):
            raise TypeError("mentorship contact requires a world moment")
        if not isinstance(self.focus, MentorshipFocus):
            raise TypeError("mentorship contact requires a focus")
        if type(self.duration_minutes) is not int or self.duration_minutes < MIN_CONTACT_MINUTES:
            raise ValueError(f"mentorship contact requires at least {MIN_CONTACT_MINUTES} whole minutes")
        if not isinstance(self.examples, tuple) or not self.examples:
            raise TypeError("mentorship contact requires immutable demonstrated examples")
        if any(not isinstance(item, DemonstratedBehavior) for item in self.examples):
            raise TypeError("mentorship contact has an invalid demonstrated example")
        example_ids = [item.event_id for item in self.examples]
        if len(example_ids) != len(set(example_ids)):
            raise ValueError("a mentorship contact cannot repeat a demonstration event")
        if any(item.focus is not self.focus or item.at >= self.at for item in self.examples):
            raise ValueError("demonstrations must match the contact focus and precede it")
        if sum(item.meaningful_repetitions for item in self.examples) > MAX_CONTACT_REPETITIONS:
            raise ValueError(
                f"a mentorship contact is limited to {MAX_CONTACT_REPETITIONS} meaningful repetitions"
            )
        _normalized(self.mentor_clarity, "mentor clarity feedback")
        _normalized(self.mentee_usefulness, "mentee usefulness feedback")
        _normalized(self.mentor_trust_feedback, "mentor trust feedback")
        _normalized(self.mentee_trust_feedback, "mentee trust feedback")
        _normalized(self.learner_adaptability, "learner adaptability snapshot")
        if not isinstance(self.time_budget, MentorTimeBudget) or self.time_budget.on != self.at.on:
            raise ValueError("mentorship contact must cite its mentor's dated time budget")
        if self.duration_minutes > self.time_budget.remaining_minutes:
            raise ValueError("mentorship contact exceeds the remaining mentor time budget")

    @property
    def meaningful_repetitions(self) -> int:
        return sum(item.meaningful_repetitions for item in self.examples)

    @property
    def compatibility(self) -> float:
        # Both people must report value; neither can be averaged away.
        return min(float(self.mentor_clarity), float(self.mentee_usefulness))


@dataclass(frozen=True)
class FocusLearningReceipt:
    mentorship_id: MentorshipId
    contact_id: EventId
    focus: MentorshipFocus
    example_event_ids: tuple[EventId, ...]
    meaningful_repetitions: int
    mentor_clarity: float
    mentee_usefulness: float
    learner_adaptability: float
    formula_version: str
    gain: float

    def __post_init__(self) -> None:
        validate_id(self.mentorship_id, kind="learning receipt mentorship ID")
        validate_id(self.contact_id, kind="learning receipt contact ID")
        if not isinstance(self.focus, MentorshipFocus):
            raise TypeError("learning receipt requires a focus")
        if not isinstance(self.example_event_ids, tuple) or not self.example_event_ids:
            raise TypeError("learning receipt requires immutable evidence references")
        for event_id in self.example_event_ids:
            validate_id(event_id, kind="learning demonstration event ID")
        if len(self.example_event_ids) != len(set(self.example_event_ids)):
            raise ValueError("learning receipt cannot repeat demonstration evidence")
        if type(self.meaningful_repetitions) is not int or self.meaningful_repetitions <= 0:
            raise ValueError("learning receipt requires positive meaningful repetitions")
        _normalized(self.mentor_clarity, "learning receipt mentor clarity")
        _normalized(self.mentee_usefulness, "learning receipt mentee usefulness")
        _normalized(self.learner_adaptability, "learning receipt adaptability")
        if self.formula_version != MENTORSHIP_FORMULA_VERSION:
            raise ValueError("focus learning receipt uses an unsupported formula version")
        _normalized(self.gain, "focus learning gain")
        expected = min(
            MAX_CONTACT_LEARNING_GAIN,
            round(
                self.meaningful_repetitions * BASE_FOCUS_LEARNING_PER_REPETITION
                * (0.5 + float(self.learner_adaptability))
                * min(float(self.mentor_clarity), float(self.mentee_usefulness)),
                8,
            ),
        )
        if not math.isclose(float(self.gain), expected, rel_tol=0.0, abs_tol=1e-8):
            raise ValueError("focus learning gain does not match its recorded evidence and feedback")


@dataclass(frozen=True)
class FocusLearning:
    mentee_id: PersonId
    focus: MentorshipFocus
    value: float
    receipts: tuple[FocusLearningReceipt, ...]

    def __post_init__(self) -> None:
        validate_id(self.mentee_id, kind="focus learning mentee ID")
        if not isinstance(self.focus, MentorshipFocus):
            raise TypeError("focus learning requires a named focus")
        _normalized(self.value, "focus learning value")
        if not isinstance(self.receipts, tuple) or any(
            not isinstance(item, FocusLearningReceipt) for item in self.receipts
        ):
            raise TypeError("focus learning receipts must be immutable records")
        if any(item.focus is not self.focus for item in self.receipts):
            raise ValueError("focus learning can contain receipts for only its named focus")
        if not self.receipts:
            raise ValueError("focus learning requires at least one completed contact receipt")
        contacts = [item.contact_id for item in self.receipts]
        if len(contacts) != len(set(contacts)):
            raise ValueError("one contact cannot count twice toward focus learning")
        expected = min(1.0, sum(float(item.gain) for item in self.receipts))
        if not math.isclose(float(self.value), expected, rel_tol=0.0, abs_tol=1e-8):
            raise ValueError("focus learning total does not match its receipts")


@dataclass(frozen=True)
class FocusProgress:
    focus: MentorshipFocus
    contact_count: int
    contact_minutes: int
    demonstrated_repetitions: int
    learning_value: float
    mean_mutual_utility: float | None

    def __post_init__(self) -> None:
        if not isinstance(self.focus, MentorshipFocus):
            raise TypeError("progress requires a focus")
        for label, value in (
            ("focus contact count", self.contact_count),
            ("focus contact minutes", self.contact_minutes),
            ("focus demonstrated repetitions", self.demonstrated_repetitions),
        ):
            if type(value) is not int or value < 0:
                raise ValueError(f"{label} must be non-negative whole units")
        _normalized(self.learning_value, "reviewed focus learning")
        if self.mean_mutual_utility is not None:
            _normalized(self.mean_mutual_utility, "reviewed mutual utility")
        if (self.contact_count == 0) != (self.mean_mutual_utility is None):
            raise ValueError("focus utility is unknown until a contact is reviewed")


@dataclass(frozen=True)
class DirectionalTrustSnapshot:
    source_person_id: PersonId
    target_person_id: PersonId
    value: float | None
    evidence_event_ids: tuple[EventId, ...]

    def __post_init__(self) -> None:
        validate_id(self.source_person_id, kind="trust snapshot source ID")
        validate_id(self.target_person_id, kind="trust snapshot target ID")
        if self.source_person_id == self.target_person_id:
            raise ValueError("trust snapshot requires two people")
        if self.value is not None:
            _normalized(self.value, "reviewed directional trust")
        if not isinstance(self.evidence_event_ids, tuple):
            raise TypeError("trust snapshot evidence IDs must be immutable")
        for event_id in self.evidence_event_ids:
            validate_id(event_id, kind="trust snapshot evidence ID")
        if len(self.evidence_event_ids) != len(set(self.evidence_event_ids)):
            raise ValueError("trust snapshot evidence cannot repeat")
        if (self.value is None) != (not self.evidence_event_ids):
            raise ValueError("trust snapshot value and evidence must be present together")


@dataclass(frozen=True)
class MentorshipReview:
    review_id: EventId
    mentorship_id: MentorshipId
    at: WorldMoment
    contact_ids: tuple[EventId, ...]
    focus_progress: tuple[FocusProgress, ...]
    trust_snapshots: tuple[DirectionalTrustSnapshot, ...]
    no_contact: bool

    def __post_init__(self) -> None:
        validate_id(self.review_id, kind="mentorship review ID")
        validate_id(self.mentorship_id, kind="mentorship review mentorship ID")
        if not isinstance(self.at, WorldMoment):
            raise TypeError("mentorship review requires a world moment")
        if not isinstance(self.contact_ids, tuple):
            raise TypeError("review contact references must be immutable")
        for event_id in self.contact_ids:
            validate_id(event_id, kind="review contact ID")
        if len(self.contact_ids) != len(set(self.contact_ids)):
            raise ValueError("review cannot repeat a contact")
        if not isinstance(self.focus_progress, tuple) or any(
            not isinstance(item, FocusProgress) for item in self.focus_progress
        ):
            raise TypeError("review progress must be immutable focus records")
        focuses = [item.focus for item in self.focus_progress]
        if len(focuses) != len(set(focuses)):
            raise ValueError("review cannot repeat a focus")
        if not isinstance(self.trust_snapshots, tuple) or any(
            not isinstance(item, DirectionalTrustSnapshot) for item in self.trust_snapshots
        ):
            raise TypeError("review trust snapshots must be immutable records")
        directions = [(item.source_person_id, item.target_person_id) for item in self.trust_snapshots]
        if len(directions) != len(set(directions)):
            raise ValueError("review cannot repeat a directed trust edge")
        if type(self.no_contact) is not bool or self.no_contact != (not self.contact_ids):
            raise ValueError("no-contact review flag must match its contact evidence")


@dataclass(frozen=True)
class MentorshipLedger:
    mentorships: tuple[Mentorship, ...] = ()
    contacts: tuple[MentorshipContact, ...] = ()
    focus_learning: tuple[FocusLearning, ...] = ()
    reviews: tuple[MentorshipReview, ...] = ()
    relationships: tuple[RelationshipEdge, ...] = ()

    def __post_init__(self) -> None:
        for label, values, record_type in (
            ("mentorships", self.mentorships, Mentorship),
            ("contacts", self.contacts, MentorshipContact),
            ("focus learning", self.focus_learning, FocusLearning),
            ("reviews", self.reviews, MentorshipReview),
            ("relationships", self.relationships, RelationshipEdge),
        ):
            if not isinstance(values, tuple) or any(not isinstance(item, record_type) for item in values):
                raise TypeError(f"mentorship ledger {label} must be immutable records")
        mentorship_ids = [item.mentorship_id for item in self.mentorships]
        offer_ids = [item.offer_id for item in self.mentorships]
        if len(mentorship_ids) != len(set(mentorship_ids)) or len(offer_ids) != len(set(offer_ids)):
            raise ValueError("mentorships cannot repeat IDs or accepted offers")
        if tuple(sorted(self.mentorships, key=lambda item: (item.started_at, str(item.mentorship_id)))) != self.mentorships:
            raise ValueError("mentorship ledger must retain activation chronology")
        pair_keys = [(item.source_person_id, item.target_person_id) for item in self.relationships]
        if len(pair_keys) != len(set(pair_keys)):
            raise ValueError("mentorship relationship edges cannot repeat a direction")
        if tuple(sorted(self.relationships, key=lambda item: (str(item.source_person_id), str(item.target_person_id)))) != self.relationships:
            raise ValueError("mentorship relationship edges must use canonical order")
        programs = {item.mentorship_id: item for item in self.mentorships}
        relationship_map = {
            (item.source_person_id, item.target_person_id): item
            for item in self.relationships
        }
        for program in self.mentorships:
            forward = relationship_map.get((program.mentor_id, program.mentee_id))
            trust, evidence_ids = _relationship_snapshot_as_of(
                forward, RelationshipDimension.TRUST, program.started_at
            )
            if (
                trust is None
                or trust < MENTOR_TRUST_THRESHOLD
                or evidence_ids != program.activation_trust_evidence_ids
                or not _trust_evidence_is_current(forward, program.started_at)
            ):
                raise ValueError("mentorship activation trust snapshot does not match directed evidence")
        contact_ids = [item.contact_id for item in self.contacts]
        if len(contact_ids) != len(set(contact_ids)):
            raise ValueError("mentorship contact IDs cannot repeat")
        if tuple(sorted(self.contacts, key=lambda item: (item.at, str(item.contact_id)))) != self.contacts:
            raise ValueError("mentorship contacts must retain world chronology")
        examples: list[EventId] = []
        for contact in self.contacts:
            program = programs.get(contact.mentorship_id)
            if program is None or contact.focus not in {item.focus for item in program.focus_agreements}:
                raise ValueError("mentorship contact must use an agreed focus")
            if set(contact.examples[0].participants) != {program.mentor_id, program.mentee_id}:
                raise ValueError("mentorship demonstration must involve its named pair")
            if contact.time_budget.mentor_id != program.mentor_id:
                raise ValueError("mentorship contact time must be charged to its named mentor")
            if any(set(item.participants) != {program.mentor_id, program.mentee_id} for item in contact.examples):
                raise ValueError("all demonstrated behavior must involve both mentorship participants")
            if _status_at(program, contact.at) is not MentorshipStatus.ACTIVE:
                raise ValueError("mentorship contact must occur while the mentorship is active")
            if contact.at <= program.started_at:
                raise ValueError("mentorship contact must follow activation")
            examples.extend(item.event_id for item in contact.examples)
        if len(examples) != len(set(examples)):
            raise ValueError("a demonstrated event cannot be counted in multiple mentoring contacts")
        self._validate_time_budgets()
        self._validate_learning(programs)
        self._validate_reviews(programs)
        moments = [item.at for program in self.mentorships for item in program.transitions]
        moments.extend(item.at for item in self.contacts)
        moments.extend(item.at for item in self.reviews)
        if len(moments) != len(set(moments)):
            raise ValueError("distinct mentorship actions require distinct world moments")

    def _validate_time_budgets(self) -> None:
        by_day: dict[tuple[PersonId, WorldDate], list[MentorshipContact]] = {}
        for contact in self.contacts:
            by_day.setdefault((contact.time_budget.mentor_id, contact.at.on), []).append(contact)
        for contacts in by_day.values():
            budgets = {item.time_budget for item in contacts}
            if len(budgets) != 1:
                raise ValueError("mentorship contacts on one day must share one mentor-time snapshot")
            budget = contacts[0].time_budget
            used = sum(item.duration_minutes for item in contacts) + budget.existing_commitments_minutes
            if used > budget.available_minutes:
                raise ValueError("mentorship contacts exceed the mentor's dated daily capacity")

    def _validate_learning(self, programs: dict[MentorshipId, Mentorship]) -> None:
        keys = [(item.mentee_id, item.focus) for item in self.focus_learning]
        if len(keys) != len(set(keys)):
            raise ValueError("focus learning cannot repeat a mentee/focus pair")
        receipt_contacts: list[EventId] = []
        contacts_by_id = {item.contact_id: item for item in self.contacts}
        for learning in self.focus_learning:
            for receipt in learning.receipts:
                program = programs.get(receipt.mentorship_id)
                contact = contacts_by_id.get(receipt.contact_id)
                if (
                    program is None or contact is None
                    or program.mentee_id != learning.mentee_id
                    or receipt.mentorship_id != contact.mentorship_id
                    or program.mentee_id not in contact.examples[0].participants
                    or receipt.contact_id != contact.contact_id
                    or receipt.focus is not contact.focus
                    or receipt.example_event_ids != tuple(item.event_id for item in contact.examples)
                    or receipt.meaningful_repetitions != contact.meaningful_repetitions
                    or not math.isclose(receipt.mentor_clarity, contact.mentor_clarity, rel_tol=0.0, abs_tol=1e-8)
                    or not math.isclose(receipt.mentee_usefulness, contact.mentee_usefulness, rel_tol=0.0, abs_tol=1e-8)
                    or not math.isclose(receipt.learner_adaptability, contact.learner_adaptability, rel_tol=0.0, abs_tol=1e-8)
                ):
                    raise ValueError("focus learning receipt does not match its mentorship contact")
                receipt_contacts.append(receipt.contact_id)
            expected_receipts = tuple(sorted(
                learning.receipts,
                key=lambda item: (contacts_by_id[item.contact_id].at, str(item.contact_id)),
            ))
            if learning.receipts != expected_receipts:
                raise ValueError("focus learning receipts must retain contact chronology")
        if len(receipt_contacts) != len(set(receipt_contacts)):
            raise ValueError("one mentorship contact cannot create several focus learning receipts")
        if set(receipt_contacts) != set(contacts_by_id):
            raise ValueError("each completed mentorship contact must create exactly one focus receipt")
        for learning in self.focus_learning:
            expected = min(1.0, sum(float(item.gain) for item in learning.receipts))
            if not math.isclose(learning.value, expected, rel_tol=0.0, abs_tol=1e-8):
                raise ValueError("focus learning total does not reconcile to its contact receipts")

    def _validate_reviews(self, programs: dict[MentorshipId, Mentorship]) -> None:
        review_ids = [item.review_id for item in self.reviews]
        if len(review_ids) != len(set(review_ids)):
            raise ValueError("mentorship review IDs cannot repeat")
        if tuple(sorted(self.reviews, key=lambda item: (item.at, str(item.review_id)))) != self.reviews:
            raise ValueError("mentorship reviews must retain world chronology")
        contact_map = {item.contact_id: item for item in self.contacts}
        for review in self.reviews:
            program = programs.get(review.mentorship_id)
            if program is None or review.at <= program.started_at:
                raise ValueError("mentorship review must follow a recorded activation")
            if any(
                contact_id not in contact_map
                or contact_map[contact_id].mentorship_id != review.mentorship_id
                or contact_map[contact_id].at > review.at
                for contact_id in review.contact_ids
            ):
                raise ValueError("mentorship review can cite only earlier contacts from its pair")
            expected_contact_ids = tuple(
                item.contact_id for item in self.contacts
                if item.mentorship_id == review.mentorship_id and item.at <= review.at
            )
            if review.contact_ids != expected_contact_ids:
                raise ValueError("mentorship review contact list does not match its as-of evidence")
            if review.focus_progress != _focus_progress(self, program, review.at):
                raise ValueError("mentorship review focus progress does not match its as-of contacts")
            if review.trust_snapshots != _trust_snapshots(self.relationships, program, review.at):
                raise ValueError("mentorship review trust does not match its as-of directed evidence")


def _status_at(mentorship: Mentorship, at: WorldMoment) -> MentorshipStatus | None:
    prior = [item for item in mentorship.transitions if item.at <= at]
    if not prior:
        return None
    return {
        MentorshipAction.ACTIVATE: MentorshipStatus.ACTIVE,
        MentorshipAction.PAUSE: MentorshipStatus.PAUSED,
        MentorshipAction.RESUME: MentorshipStatus.ACTIVE,
        MentorshipAction.END: MentorshipStatus.ENDED,
    }[prior[-1].action]


def _relationship_snapshot_as_of(
    edge: RelationshipEdge | None,
    dimension: RelationshipDimension,
    at: WorldMoment,
) -> tuple[float | None, tuple[EventId, ...]]:
    if edge is None:
        return None, ()
    evidence = tuple(
        item for item in edge.evidence
        if item.dimension is dimension and item.at <= at
    )
    if not evidence:
        return None, ()
    latest = max(evidence, key=lambda item: (item.at, str(item.event_id)))
    return float(latest.after), tuple(item.event_id for item in evidence)


def _trust_evidence_is_current(
    edge: RelationshipEdge | None,
    at: WorldMoment,
) -> bool:
    if edge is None:
        return False
    evidence = [
        item for item in edge.evidence
        if item.dimension is RelationshipDimension.TRUST and item.at <= at
    ]
    if not evidence:
        return False
    latest = max(evidence, key=lambda item: (item.at, str(item.event_id)))
    age_days = (at.on.day - latest.at.on.day).days
    return latest.at < at and 0 <= age_days <= MAX_MENTOR_TRUST_EVIDENCE_AGE_DAYS


def _reserved_social_slots(
    social: SocialLedger,
    ledger: MentorshipLedger,
    mentor_id: PersonId,
    at: WorldMoment,
    *,
    excluding_offer_id: str,
) -> int:
    reserved = 0
    mentorships_by_offer = {item.offer_id: item for item in ledger.mentorships}
    for offer in social.offers:
        if (
            offer.kind is not OfferKind.MENTORSHIP
            or offer.initiator_id != mentor_id
            or str(offer.offer_id) == excluding_offer_id
        ):
            continue
        mentorship = mentorships_by_offer.get(str(offer.offer_id))
        if mentorship is not None and at >= mentorship.started_at:
            # Once activated, this offer's slot is represented by its dated
            # mentorship state, including later pauses and endings.
            continue
        if _offer_reserves_slot_at(offer, at):
            reserved += 1
    return reserved


def _offer_reserves_slot_at(offer: SocialOffer, at: WorldMoment) -> bool:
    """Reconstruct an offer's reserved interval from its recorded chronology."""

    if at <= offer.offered_at:
        return False
    if offer.responded_at is None:
        return offer.status is OfferStatus.OFFERED and at < offer.expires_at
    if at < offer.responded_at:
        # A later acceptance, decline, capacity failure, or expiry does not
        # change the fact that the offer was still awaiting its response then.
        return at < offer.expires_at
    if offer.status is OfferStatus.ACCEPTED:
        return offer.reservation_until is not None and at < offer.reservation_until
    if offer.status is OfferStatus.EXPIRED:
        return at < offer.expires_at
    return False


def _capacity_available(
    social: SocialLedger,
    ledger: MentorshipLedger,
    mentor_id: PersonId,
    capacity: MentorCapacity,
    at: WorldMoment,
    *,
    excluding_offer_id: str,
    excluding_mentorship_id: MentorshipId | None = None,
) -> bool:
    active = sum(
        1 for item in ledger.mentorships
        if item.mentor_id == mentor_id
        and _status_at(item, at) is MentorshipStatus.ACTIVE
        and item.mentorship_id != excluding_mentorship_id
    )
    reserved = _reserved_social_slots(
        social, ledger, mentor_id, at, excluding_offer_id=excluding_offer_id
    )
    return capacity.external_commitments + active + reserved < capacity.concurrent_slots


def _edge_map(edges: tuple[RelationshipEdge, ...]) -> dict[tuple[PersonId, PersonId], RelationshipEdge]:
    if not isinstance(edges, tuple) or any(not isinstance(item, RelationshipEdge) for item in edges):
        raise TypeError("mentorship relationship inputs must be immutable edge records")
    ordered = tuple(sorted(edges, key=lambda item: (str(item.source_person_id), str(item.target_person_id))))
    if edges != ordered:
        raise ValueError("mentorship relationship edges must use canonical order")
    result = {(item.source_person_id, item.target_person_id): item for item in edges}
    if len(result) != len(edges):
        raise ValueError("mentorship relationship inputs cannot repeat a direction")
    return result


def activate_mentorship(
    social: SocialLedger,
    ledger: MentorshipLedger,
    *,
    offer_id: str,
    at: WorldMoment,
    actor_id: PersonId,
    focus_agreements: tuple[FocusAgreement, ...],
    mentor_capacity: MentorCapacity,
    relationships: tuple[RelationshipEdge, ...],
) -> tuple[MentorshipLedger, Mentorship]:
    """Activate one accepted mentorship offer as a focus-agreed pair."""

    if not isinstance(social, SocialLedger) or not isinstance(ledger, MentorshipLedger):
        raise TypeError("mentorship activation requires social and mentorship ledgers")
    validate_id(offer_id, kind="accepted mentoring offer ID")
    if not isinstance(at, WorldMoment):
        raise TypeError("mentorship activation requires a world moment")
    validate_id(actor_id, kind="mentorship activation actor ID")
    if not isinstance(mentor_capacity, MentorCapacity):
        raise TypeError("mentorship activation requires a current mentor capacity")
    if not isinstance(focus_agreements, tuple) or not focus_agreements or any(
        not isinstance(item, FocusAgreement) for item in focus_agreements
    ):
        raise TypeError("mentorship activation requires explicit focus agreements")
    offer = next((item for item in social.offers if str(item.offer_id) == offer_id), None)
    if offer is None or offer.kind is not OfferKind.MENTORSHIP:
        raise ValueError("only a recorded mentoring offer can activate mentorship")
    if offer.status is not OfferStatus.ACCEPTED:
        raise ValueError("only an accepted mentoring offer can activate mentorship")
    if offer.responded_at is None or offer.reservation_until is None:
        raise ValueError("accepted mentoring offer has no consent reservation interval")
    if not offer.responded_at < at < offer.reservation_until:
        raise ValueError("mentorship activation must occur inside the accepted consent window")
    if actor_id not in (offer.initiator_id, offer.recipient_id):
        raise ValueError("mentorship activation actor must be one of the named participants")
    if mentor_capacity.person_id != offer.initiator_id:
        raise ValueError("current mentor capacity must belong to the offer initiator")
    if any(
        item.mentor_id != offer.initiator_id or item.mentee_id != offer.recipient_id
        for item in focus_agreements
    ):
        raise ValueError("focus agreements must name the accepted offer participants")
    if any(item.assessed_at >= at for item in focus_agreements):
        raise ValueError("focus evidence must precede mentorship activation")

    edge_map = _edge_map(relationships)
    forward = edge_map.get((offer.initiator_id, offer.recipient_id))
    trust, trust_evidence_ids = _relationship_snapshot_as_of(
        forward, RelationshipDimension.TRUST, at
    )
    if (
        trust is None
        or trust < MENTOR_TRUST_THRESHOLD
        or not _trust_evidence_is_current(forward, at)
    ):
        raise ValueError("mentorship activation requires current directed trust evidence")
    mentorship_id = MentorshipId(derive_id(
        "mentorship", "touchline-mentorship-v1", str(offer.offer_id)
    ))
    activation = MentorshipTransition(
        _expected_transition_id(mentorship_id, MentorshipAction.ACTIVATE, at, actor_id, "accepted-focus-plan"),
        MentorshipAction.ACTIVATE, at, actor_id, "accepted-focus-plan",
    )
    mentorship = Mentorship(
        mentorship_id=mentorship_id,
        offer_id=str(offer.offer_id),
        source_event_id=offer.source_event_id,
        mentor_id=offer.initiator_id,
        mentee_id=offer.recipient_id,
        origin=MentorshipOrigin.PLAYER_INITIATED,
        accepted_at=offer.responded_at,
        activation_trust_evidence_ids=trust_evidence_ids,
        focus_agreements=tuple(sorted(focus_agreements, key=lambda item: item.focus.value)),
        transitions=(activation,),
    )
    previous = next((item for item in ledger.mentorships if item.mentorship_id == mentorship_id), None)
    if previous is not None:
        if previous != mentorship:
            raise ValueError("accepted offer activation was replayed with conflicting inputs")
        return ledger, previous

    pair_edges = {
        (offer.initiator_id, offer.recipient_id),
        (offer.recipient_id, offer.initiator_id),
    }
    if any(
        key in pair_edges and any(item.at > at for item in edge.evidence)
        for key, edge in edge_map.items()
    ):
        raise ValueError("mentorship activation cannot use relationship edges with future evidence")

    if not _capacity_available(
        social, ledger, offer.initiator_id, mentor_capacity, at,
        excluding_offer_id=str(offer.offer_id),
    ):
        raise ValueError("mentor has no available concurrent capacity for activation")
    prior_edges = _edge_map(ledger.relationships)
    for key, edge in edge_map.items():
        if key in prior_edges and prior_edges[key] != edge:
            raise ValueError("mentorship relationship input conflicts with the ledger snapshot")
    merged_edges = tuple(sorted(
        {**prior_edges, **edge_map}.values(),
        key=lambda item: (str(item.source_person_id), str(item.target_person_id)),
    ))
    updated = MentorshipLedger(
        mentorships=tuple(sorted(ledger.mentorships + (mentorship,),
                                 key=lambda item: (item.started_at, str(item.mentorship_id)))),
        contacts=ledger.contacts,
        focus_learning=ledger.focus_learning,
        reviews=ledger.reviews,
        relationships=merged_edges,
    )
    return updated, mentorship


def _transition(
    ledger: MentorshipLedger,
    mentorship_id: MentorshipId,
    action: MentorshipAction,
    *,
    at: WorldMoment,
    actor_id: PersonId,
    reason: str,
) -> tuple[MentorshipLedger, Mentorship]:
    if not isinstance(ledger, MentorshipLedger) or not isinstance(at, WorldMoment):
        raise TypeError("mentorship transition requires a ledger and world moment")
    validate_id(actor_id, kind="mentorship transition actor ID")
    _reason(reason)
    index = next((i for i, item in enumerate(ledger.mentorships)
                  if item.mentorship_id == mentorship_id), None)
    if index is None:
        raise ValueError("cannot change an unknown mentorship")
    current = ledger.mentorships[index]
    event_id = _expected_transition_id(mentorship_id, action, at, actor_id, reason)
    existing = next((item for item in current.transitions if item.event_id == event_id), None)
    if existing is not None:
        if existing == MentorshipTransition(event_id, action, at, actor_id, reason):
            return ledger, current
        raise ValueError("mentorship transition event was reused with conflicting content")
    if actor_id not in (current.mentor_id, current.mentee_id):
        raise ValueError("only a mentorship participant can change its state")
    if at <= current.transitions[-1].at:
        raise ValueError("mentorship transitions must follow world chronology")
    if action is MentorshipAction.PAUSE and current.status is not MentorshipStatus.ACTIVE:
        raise ValueError("only an active mentorship can pause")
    if action is MentorshipAction.RESUME and current.status is not MentorshipStatus.PAUSED:
        raise ValueError("only a paused mentorship can resume")
    if action is MentorshipAction.END and current.status is MentorshipStatus.ENDED:
        raise ValueError("an ended mentorship cannot end again")
    transition = MentorshipTransition(event_id, action, at, actor_id, reason)
    changed = replace(current, transitions=current.transitions + (transition,))
    programs = ledger.mentorships[:index] + (changed,) + ledger.mentorships[index + 1:]
    updated = replace(ledger, mentorships=tuple(sorted(
        programs, key=lambda item: (item.started_at, str(item.mentorship_id))
    )))
    return updated, changed


def pause_mentorship(
    ledger: MentorshipLedger,
    *,
    mentorship_id: MentorshipId,
    at: WorldMoment,
    actor_id: PersonId,
    reason: str = "contact-paused",
) -> tuple[MentorshipLedger, Mentorship]:
    return _transition(ledger, mentorship_id, MentorshipAction.PAUSE,
                       at=at, actor_id=actor_id, reason=reason)


def resume_mentorship(
    social: SocialLedger,
    ledger: MentorshipLedger,
    *,
    mentorship_id: MentorshipId,
    at: WorldMoment,
    actor_id: PersonId,
    mentor_willing: bool,
    mentee_willing: bool,
    mentor_available: bool,
    mentee_available: bool,
    mentor_capacity: MentorCapacity,
    reason: str = "participants-ready",
) -> tuple[MentorshipLedger, Mentorship]:
    if not isinstance(social, SocialLedger) or not isinstance(ledger, MentorshipLedger):
        raise TypeError("mentorship resume requires social and mentorship ledgers")
    if not isinstance(at, WorldMoment):
        raise TypeError("mentorship resume requires a world moment")
    validate_id(actor_id, kind="mentorship resume actor ID")
    _reason(reason)
    if not isinstance(mentor_capacity, MentorCapacity):
        raise TypeError("mentorship resume requires current mentor capacity")
    current = next((item for item in ledger.mentorships if item.mentorship_id == mentorship_id), None)
    if current is None:
        raise ValueError("cannot resume an unknown mentorship")

    # Replay is identified by the persisted transition itself. Its original
    # consent and capacity checks are already committed, so changed caller
    # snapshots must not make an exact retry fail.
    event_id = _expected_transition_id(
        mentorship_id, MentorshipAction.RESUME, at, actor_id, reason
    )
    existing = next((item for item in current.transitions if item.event_id == event_id), None)
    expected = MentorshipTransition(event_id, MentorshipAction.RESUME, at, actor_id, reason)
    if existing is not None:
        if existing == expected:
            return ledger, current
        raise ValueError("mentorship transition event was reused with conflicting content")

    flags = (mentor_willing, mentee_willing, mentor_available, mentee_available)
    if any(type(item) is not bool for item in flags):
        raise TypeError("mentorship resume requires explicit consent and availability")
    if not all(flags):
        raise ValueError("both participants must be willing and available to resume")
    if mentor_capacity.person_id != current.mentor_id:
        raise ValueError("current capacity must belong to the named mentor")
    if not _capacity_available(
        social, ledger, current.mentor_id, mentor_capacity, at,
        excluding_offer_id=current.offer_id,
        excluding_mentorship_id=current.mentorship_id,
    ):
        raise ValueError("mentor has no available concurrent capacity to resume")
    return _transition(ledger, mentorship_id, MentorshipAction.RESUME,
                       at=at, actor_id=actor_id, reason=reason)


def end_mentorship(
    ledger: MentorshipLedger,
    *,
    mentorship_id: MentorshipId,
    at: WorldMoment,
    actor_id: PersonId,
    reason: str = "participants-ended",
) -> tuple[MentorshipLedger, Mentorship]:
    return _transition(ledger, mentorship_id, MentorshipAction.END,
                       at=at, actor_id=actor_id, reason=reason)


def record_mentorship_contact(
    ledger: MentorshipLedger,
    *,
    mentorship_id: MentorshipId,
    contact_id: EventId,
    at: WorldMoment,
    focus: MentorshipFocus,
    duration_minutes: int,
    examples: tuple[DemonstratedBehavior, ...],
    mentor_clarity: float,
    mentee_usefulness: float,
    mentor_trust_feedback: float,
    mentee_trust_feedback: float,
    mentee_profile: PlayerProfile,
    time_budget: MentorTimeBudget,
) -> MentorshipLedger:
    """Record caller-asserted practice, one focus receipt, and directed trust feedback.

    Demonstration IDs are deduplicated within this ledger; the caller-supplied
    IDs and repetition counts are not resolved against match or training history.
    """

    if not isinstance(ledger, MentorshipLedger):
        raise TypeError("mentorship contact requires its ledger")
    program = next((item for item in ledger.mentorships if item.mentorship_id == mentorship_id), None)
    if program is None:
        raise ValueError("mentorship contact requires an activated pair")
    if not isinstance(at, WorldMoment):
        raise TypeError("mentorship contact requires a world moment")
    if not isinstance(focus, MentorshipFocus):
        raise TypeError("mentorship contact requires a named focus")
    if not isinstance(time_budget, MentorTimeBudget):
        raise TypeError("mentorship contact requires a dated mentor-time budget")
    if not isinstance(mentee_profile, PlayerProfile) or str(mentee_profile.player_id) != str(program.mentee_id):
        raise ValueError("learning profile must belong to the named mentee")
    if focus not in {item.focus for item in program.focus_agreements}:
        raise ValueError("mentorship contact focus was not agreed by the pair")
    if _status_at(program, at) is not MentorshipStatus.ACTIVE:
        raise ValueError("mentorship contact requires an active mentorship at its event time")
    if at <= program.started_at:
        raise ValueError("mentorship contact must follow activation")
    if time_budget.mentor_id != program.mentor_id:
        raise ValueError("mentorship contact budget must belong to the named mentor")
    contact = MentorshipContact(
        contact_id=contact_id,
        mentorship_id=mentorship_id,
        at=at,
        focus=focus,
        duration_minutes=duration_minutes,
        examples=examples,
        mentor_clarity=mentor_clarity,
        mentee_usefulness=mentee_usefulness,
        mentor_trust_feedback=mentor_trust_feedback,
        mentee_trust_feedback=mentee_trust_feedback,
        learner_adaptability=learning_adaptability(mentee_profile),
        time_budget=time_budget,
    )
    prior_contact = next((item for item in ledger.contacts if item.contact_id == contact_id), None)
    if prior_contact is not None:
        if prior_contact != contact:
            raise ValueError("mentorship contact event was replayed with conflicting content")
        return ledger
    prior_events = [item.at for item in program.transitions]
    prior_events.extend(item.at for item in ledger.contacts if item.mentorship_id == mentorship_id)
    prior_events.extend(item.at for item in ledger.reviews if item.mentorship_id == mentorship_id)
    if prior_events and at <= max(prior_events):
        raise ValueError("mentorship contact must follow the latest pair event")
    used_today = sum(
        item.duration_minutes for item in ledger.contacts
        if item.time_budget.mentor_id == program.mentor_id and item.at.on == at.on
    )
    if used_today + duration_minutes + time_budget.existing_commitments_minutes > time_budget.available_minutes:
        raise ValueError("mentorship contact exceeds the mentor's remaining daily time")
    if any(item.time_budget.mentor_id == time_budget.mentor_id
           and item.at.on == at.on and item.time_budget != time_budget for item in ledger.contacts):
        raise ValueError("mentorship contacts on one day must use the same time-budget snapshot")
    if any(
        example.event_id == prior_example.event_id
        for example in examples for prior in ledger.contacts for prior_example in prior.examples
    ):
        raise ValueError("demonstrated behavior cannot be reused for another contact")

    repetitions = contact.meaningful_repetitions
    receipt = FocusLearningReceipt(
        mentorship_id=mentorship_id,
        contact_id=contact_id,
        focus=focus,
        example_event_ids=tuple(item.event_id for item in examples),
        meaningful_repetitions=repetitions,
        mentor_clarity=contact.mentor_clarity,
        mentee_usefulness=contact.mentee_usefulness,
        learner_adaptability=contact.learner_adaptability,
        formula_version=MENTORSHIP_FORMULA_VERSION,
        gain=min(
            MAX_CONTACT_LEARNING_GAIN,
            round(repetitions * BASE_FOCUS_LEARNING_PER_REPETITION
                  * (0.5 + contact.learner_adaptability)
                  * contact.compatibility, 8),
        ),
    )
    learning_by_key = {(item.mentee_id, item.focus): item for item in ledger.focus_learning}
    prior_learning = learning_by_key.get((program.mentee_id, focus))
    receipt_times = {item.contact_id: item.at for item in ledger.contacts}
    receipt_times[contact_id] = at
    receipts = tuple(sorted(
        (prior_learning.receipts if prior_learning is not None else ()) + (receipt,),
        key=lambda item: (receipt_times[item.contact_id], str(item.contact_id)),
    ))
    learning_by_key[(program.mentee_id, focus)] = FocusLearning(
        program.mentee_id, focus, min(1.0, sum(item.gain for item in receipts)), receipts
    )

    relationships = _edge_map(ledger.relationships)
    for source, target, feedback in (
        (program.mentor_id, program.mentee_id, contact.mentor_trust_feedback),
        (program.mentee_id, program.mentor_id, contact.mentee_trust_feedback),
    ):
        edge = relationships.get((source, target))
        if edge is None or RelationshipDimension.TRUST not in {item.dimension for item in edge.dimensions}:
            continue
        delta = round((float(feedback) - 0.5) * TRUST_FEEDBACK_SCALE, 8)
        if abs(delta) > MAX_RELATIONSHIP_DELTA:
            raise ValueError("mentorship trust feedback exceeds the relationship update bound")
        trust_event = EventId(derive_id(
            "event", "touchline-mentorship-trust-feedback-v1",
            str(contact.contact_id), str(source), str(target),
        ))
        relationships[(source, target)] = record_relationship_evidence(
            edge,
            source_person_id=source,
            target_person_id=target,
            dimension=RelationshipDimension.TRUST,
            delta=delta,
            event_id=trust_event,
            at=at,
            direct_contact=True,
        )

    return MentorshipLedger(
        mentorships=ledger.mentorships,
        contacts=tuple(sorted(ledger.contacts + (contact,), key=lambda item: (item.at, str(item.contact_id)))),
        focus_learning=tuple(sorted(learning_by_key.values(), key=lambda item: (str(item.mentee_id), item.focus.value))),
        reviews=ledger.reviews,
        relationships=tuple(sorted(relationships.values(), key=lambda item: (str(item.source_person_id), str(item.target_person_id)))),
    )


def _trust_snapshots(
    edges: tuple[RelationshipEdge, ...],
    mentorship: Mentorship,
    at: WorldMoment,
) -> tuple[DirectionalTrustSnapshot, ...]:
    result = []
    for source, target in (
        (mentorship.mentor_id, mentorship.mentee_id),
        (mentorship.mentee_id, mentorship.mentor_id),
    ):
        edge = next((item for item in edges
                     if item.source_person_id == source and item.target_person_id == target), None)
        value, evidence_ids = _relationship_snapshot_as_of(
            edge, RelationshipDimension.TRUST, at
        )
        result.append(DirectionalTrustSnapshot(source, target, value, evidence_ids))
    return tuple(result)


def _focus_progress(
    ledger: MentorshipLedger,
    mentorship: Mentorship,
    at: WorldMoment,
) -> tuple[FocusProgress, ...]:
    result: list[FocusProgress] = []
    for agreement in sorted(mentorship.focus_agreements, key=lambda item: item.focus.value):
        contacts = [item for item in ledger.contacts
                    if item.mentorship_id == mentorship.mentorship_id
                    and item.focus is agreement.focus and item.at <= at]
        receipts = [receipt for learning in ledger.focus_learning
                    if learning.mentee_id == mentorship.mentee_id
                    and learning.focus is agreement.focus
                    for receipt in learning.receipts
                    if receipt.mentorship_id == mentorship.mentorship_id
                    and receipt.contact_id in {item.contact_id for item in contacts}]
        utilities = [item.compatibility for item in contacts]
        result.append(FocusProgress(
            focus=agreement.focus,
            contact_count=len(contacts),
            contact_minutes=sum(item.duration_minutes for item in contacts),
            demonstrated_repetitions=sum(item.meaningful_repetitions for item in contacts),
            learning_value=min(1.0, sum(item.gain for item in receipts)),
            mean_mutual_utility=(round(sum(utilities) / len(utilities), 8) if utilities else None),
        ))
    return tuple(result)


def record_mentorship_review(
    ledger: MentorshipLedger,
    *,
    mentorship_id: MentorshipId,
    at: WorldMoment,
) -> tuple[MentorshipLedger, MentorshipReview]:
    """Append a stable as-of review; repeated review does not create new learning."""

    if not isinstance(ledger, MentorshipLedger) or not isinstance(at, WorldMoment):
        raise TypeError("mentorship review requires a ledger and world moment")
    mentorship = next((item for item in ledger.mentorships
                       if item.mentorship_id == mentorship_id), None)
    if mentorship is None:
        raise ValueError("cannot review an unknown mentorship")
    if at <= mentorship.started_at:
        raise ValueError("mentorship review must follow activation")
    review_id = EventId(derive_id(
        "event", "touchline-mentorship-review-v1", str(mentorship_id),
        at.on.isoformat, str(at.sequence),
    ))
    prior = next((item for item in ledger.reviews if item.review_id == review_id), None)
    contact_ids = tuple(item.contact_id for item in ledger.contacts
                        if item.mentorship_id == mentorship_id and item.at <= at)
    trust_snapshots = _trust_snapshots(ledger.relationships, mentorship, at)
    review = MentorshipReview(
        review_id=review_id,
        mentorship_id=mentorship_id,
        at=at,
        contact_ids=contact_ids,
        focus_progress=_focus_progress(ledger, mentorship, at),
        trust_snapshots=trust_snapshots,
        no_contact=not contact_ids,
    )
    if prior is not None:
        if prior != review:
            raise ValueError("mentorship review was replayed with conflicting as-of evidence")
        return ledger, prior
    if ledger.reviews and at <= ledger.reviews[-1].at:
        raise ValueError("mentorship reviews must retain world chronology")
    updated = replace(
        ledger,
        reviews=tuple(sorted(ledger.reviews + (review,), key=lambda item: (item.at, str(item.review_id)))),
    )
    return updated, review


__all__ = [
    "BASE_FOCUS_LEARNING_PER_REPETITION",
    "DemonstratedBehavior",
    "DirectionalTrustSnapshot",
    "FocusAgreement",
    "FocusLearning",
    "FocusLearningReceipt",
    "FocusProgress",
    "MentorTimeBudget",
    "Mentorship",
    "MentorshipAction",
    "MentorshipContact",
    "MentorshipFocus",
    "MentorshipId",
    "MentorshipLedger",
    "MentorshipOrigin",
    "MentorshipReview",
    "MentorshipStatus",
    "MentorshipTransition",
    "MENTORSHIP_FORMULA_VERSION",
    "MAX_MENTOR_TRUST_EVIDENCE_AGE_DAYS",
    "activate_mentorship",
    "end_mentorship",
    "pause_mentorship",
    "record_mentorship_contact",
    "record_mentorship_review",
    "resume_mentorship",
]
