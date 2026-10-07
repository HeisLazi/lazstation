"""Evidence-limited recruitment and opposition reports over P10 observations.

The current observation registry supports intended-receiver pass completion as
the only player-level event rate. Reports therefore describe observed passing
outcomes, not hidden ability, tactical roles, or cross-league talent.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum

from games.touchline.esb.events import EventEnvelope
from games.touchline.esb.ids import ClubId, EventId, MatchId, validate_id
from games.touchline.esb.ids import derive_id
from games.touchline.esb.knowledge.metrics import CORE_METRICS, MetricAggregation, MetricRegistry
from games.touchline.esb.knowledge.model import (
    CoverageGrant,
    CoverageLevel,
    Observation,
    ObservationLedger,
)
from games.touchline.esb.time import WorldDate


_WILSON_Z_95 = 1.96


class Recommendation(str, Enum):
    SHORTLIST = "shortlist"
    REVIEW = "review"
    NEEDS_MORE_EVIDENCE = "needs_more_evidence"
    CRITERION_NOT_MET = "criterion_not_met"


class ComparisonOutcome(str, Enum):
    FIRST_LEADS = "first_leads"
    SECOND_LEADS = "second_leads"
    INCONCLUSIVE = "inconclusive"


class DossierDimensionStatus(str, Enum):
    SUPPORTED = "supported"
    MIXED = "mixed"
    NOT_SUPPORTED = "not_supported"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class RoleProfile:
    """A declared recruitment requirement over a registered observed metric."""

    role_id: str
    display_name: str
    metric_id: str
    minimum_rate: float
    minimum_attempts: int
    minimum_matches: int

    def __post_init__(self) -> None:
        validate_id(self.role_id, kind="scouting role ID")
        if not isinstance(self.display_name, str) or not self.display_name.strip():
            raise ValueError("scouting role requires a display name")
        if not isinstance(self.metric_id, str) or not self.metric_id.strip():
            raise ValueError("scouting role requires a registered metric ID")
        if type(self.minimum_rate) not in (int, float) or not math.isfinite(self.minimum_rate):
            raise ValueError("role minimum rate must be finite")
        if not 0.0 <= self.minimum_rate <= 1.0:
            raise ValueError("role minimum rate must be between zero and one")
        if type(self.minimum_attempts) is not int or self.minimum_attempts < 1:
            raise ValueError("role minimum attempts must be positive")
        if type(self.minimum_matches) is not int or self.minimum_matches < 1:
            raise ValueError("role minimum matches must be positive")


@dataclass(frozen=True)
class ScoutingQuery:
    club_id: ClubId
    as_of: WorldDate
    player_ids: tuple[str, ...]
    lookback_days: int

    def __post_init__(self) -> None:
        validate_id(self.club_id, kind="scouting club ID")
        if not isinstance(self.as_of, WorldDate):
            raise TypeError("scouting query requires an as-of world date")
        if not isinstance(self.player_ids, tuple) or not self.player_ids:
            raise TypeError("scouting query requires an immutable candidate tuple")
        for player_id in self.player_ids:
            validate_id(player_id, kind="scouting candidate ID")
        if len(self.player_ids) != len(set(self.player_ids)):
            raise ValueError("scouting query cannot repeat candidates")
        if type(self.lookback_days) is not int or self.lookback_days < 0:
            raise ValueError("scouting lookback must be a non-negative number of days")


@dataclass(frozen=True)
class EvidenceSlice:
    """One player's evidence from one match and one observing staff member."""

    match_id: MatchId
    evidence_date: WorldDate
    staff_id: str
    successes: int
    attempts: int
    source_observation_ids: tuple[str, ...]
    source_event_ids: tuple[EventId, ...]

    def __post_init__(self) -> None:
        validate_id(self.match_id, kind="scouting evidence match ID")
        validate_id(self.staff_id, kind="scouting evidence staff ID")
        if not isinstance(self.evidence_date, WorldDate):
            raise TypeError("scouting evidence requires its match date")
        if type(self.attempts) is not int or self.attempts < 1:
            raise ValueError("evidence slice attempts must be positive")
        if type(self.successes) is not int or not 0 <= self.successes <= self.attempts:
            raise ValueError("evidence slice successes must be within its attempts")
        if not isinstance(self.source_observation_ids, tuple) or len(self.source_observation_ids) != self.attempts:
            raise ValueError("evidence slice must cite each observation in its denominator")
        if not isinstance(self.source_event_ids, tuple) or not self.source_event_ids:
            raise ValueError("evidence slice must cite its source events")
        if len(self.source_observation_ids) != len(set(self.source_observation_ids)):
            raise ValueError("evidence slice cannot repeat observation IDs")
        if len(self.source_event_ids) != len(set(self.source_event_ids)):
            raise ValueError("evidence slice cannot repeat source event IDs")
        for value in self.source_observation_ids:
            validate_id(value, kind="scouting observation ID")
        for value in self.source_event_ids:
            validate_id(value, kind="scouting source event ID")

    @property
    def rate(self) -> float:
        return self.successes / self.attempts


@dataclass(frozen=True)
class CandidateFinding:
    player_id: str
    successes: int
    attempts: int
    value: float | None
    lower_bound: float | None
    upper_bound: float | None
    match_count: int
    slices: tuple[EvidenceSlice, ...]
    recommendation: Recommendation
    warning_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        validate_id(self.player_id, kind="scouted player ID")
        if type(self.attempts) is not int or self.attempts < 0:
            raise ValueError("candidate attempts must be non-negative")
        if type(self.successes) is not int or not 0 <= self.successes <= self.attempts:
            raise ValueError("candidate successes must be within attempts")
        if type(self.match_count) is not int or self.match_count < 0:
            raise ValueError("candidate match count must be non-negative")
        if not isinstance(self.slices, tuple) or any(not isinstance(item, EvidenceSlice) for item in self.slices):
            raise TypeError("candidate evidence must be immutable slices")
        if sum(item.attempts for item in self.slices) != self.attempts:
            raise ValueError("candidate denominator must equal its cited evidence slices")
        if sum(item.successes for item in self.slices) != self.successes:
            raise ValueError("candidate numerator must equal its cited evidence slices")
        if len({item.match_id for item in self.slices}) != self.match_count:
            raise ValueError("candidate match count must equal its cited match cohort")
        if not isinstance(self.recommendation, Recommendation):
            raise TypeError("candidate recommendation must be explicit")
        if not isinstance(self.warning_codes, tuple) or any(
            not isinstance(item, str) for item in self.warning_codes
        ):
            raise TypeError("candidate warnings must be immutable")
        if self.attempts == 0:
            if any(value is not None for value in (self.value, self.lower_bound, self.upper_bound)):
                raise ValueError("a candidate with no evidence cannot have a numeric estimate")
            if self.recommendation is not Recommendation.NEEDS_MORE_EVIDENCE:
                raise ValueError("a candidate without observations needs more evidence")
        elif self.value is None or self.lower_bound is None or self.upper_bound is None:
            raise ValueError("observed candidates require a rate and uncertainty interval")
        elif self.value != self.successes / self.attempts:
            raise ValueError("candidate rate must match its numerator and denominator")
        elif not (0.0 <= self.lower_bound <= self.value <= self.upper_bound <= 1.0):
            raise ValueError("candidate uncertainty interval must contain its rate")

    @property
    def source_observation_ids(self) -> tuple[str, ...]:
        return tuple(item for sample in self.slices for item in sample.source_observation_ids)

    @property
    def source_event_ids(self) -> tuple[EventId, ...]:
        return tuple(dict.fromkeys(item for sample in self.slices for item in sample.source_event_ids))


@dataclass(frozen=True)
class RoleSearchReport:
    report_id: str
    club_id: ClubId
    role: RoleProfile
    as_of: WorldDate
    lookback_days: int
    context: str
    candidates: tuple[CandidateFinding, ...]

    def __post_init__(self) -> None:
        validate_id(self.report_id, kind="scouting report ID")
        validate_id(self.club_id, kind="scouting report club ID")
        if not isinstance(self.role, RoleProfile) or not isinstance(self.as_of, WorldDate):
            raise TypeError("role search report requires its role and as-of date")
        if not isinstance(self.context, str) or not self.context.strip():
            raise ValueError("role search report requires a metric context")
        if type(self.lookback_days) is not int or self.lookback_days < 0:
            raise ValueError("role search report requires a non-negative lookback")
        if not isinstance(self.candidates, tuple) or any(
            not isinstance(item, CandidateFinding) for item in self.candidates
        ):
            raise TypeError("role search report candidates must be immutable findings")
        ids = [item.player_id for item in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("role search report cannot repeat candidates")

    @property
    def shortlist_player_ids(self) -> tuple[str, ...]:
        return tuple(item.player_id for item in self.candidates
                     if item.recommendation is Recommendation.SHORTLIST)


@dataclass(frozen=True)
class CandidateComparison:
    comparison_id: str
    role: RoleProfile
    as_of: WorldDate
    context: str
    first: CandidateFinding
    second: CandidateFinding
    outcome: ComparisonOutcome
    explanation: str

    def __post_init__(self) -> None:
        validate_id(self.comparison_id, kind="candidate comparison ID")
        if self.first.player_id == self.second.player_id:
            raise ValueError("candidate comparison requires two different players")
        if not isinstance(self.outcome, ComparisonOutcome):
            raise TypeError("candidate comparison requires an explicit outcome")
        if not isinstance(self.role, RoleProfile) or not isinstance(self.as_of, WorldDate):
            raise TypeError("candidate comparison requires its role and as-of date")
        if not isinstance(self.context, str) or not self.context.strip():
            raise ValueError("candidate comparison requires its metric context")
        if not isinstance(self.explanation, str) or not self.explanation.strip():
            raise ValueError("candidate comparison requires an explanation")


@dataclass(frozen=True)
class OppositionBrief:
    brief_id: str
    club_id: ClubId
    as_of: WorldDate
    player_ids: tuple[str, ...]
    lookback_days: int
    minimum_attempts: int
    minimum_matches: int
    leading_observed_player_id: str | None
    observed_distributor_id: str | None
    successes: int
    attempts: int
    match_count: int
    completion_rate: float | None
    recommendation: str | None
    unavailable_reason: str | None
    slices: tuple[EvidenceSlice, ...]
    context: str
    caveat: str

    def __post_init__(self) -> None:
        validate_id(self.brief_id, kind="opposition brief ID")
        validate_id(self.club_id, kind="opposition brief club ID")
        if self.leading_observed_player_id is not None:
            validate_id(self.leading_observed_player_id, kind="leading observed passer ID")
        if self.observed_distributor_id is not None:
            validate_id(self.observed_distributor_id, kind="recommended opposition target ID")
        if (self.observed_distributor_id is None) != (self.recommendation is None):
            raise ValueError("an opposition recommendation requires an observed target")
        if (self.recommendation is None) != (self.unavailable_reason is not None):
            raise ValueError("brief must explain unavailable evidence or provide a recommendation")
        if (type(self.successes) is not int or type(self.attempts) is not int
                or type(self.minimum_attempts) is not int or type(self.minimum_matches) is not int):
            raise TypeError("opposition evidence requires integer numerator and denominator")
        if self.minimum_attempts < 1 or self.minimum_matches < 1:
            raise ValueError("opposition evidence thresholds must be positive")
        if not 0 <= self.successes <= self.attempts:
            raise ValueError("opposition completion numerator must be within its denominator")
        if type(self.match_count) is not int or self.match_count < 0:
            raise ValueError("opposition match count must be non-negative")
        if not isinstance(self.player_ids, tuple) or not self.player_ids:
            raise ValueError("opposition brief requires its caller-supplied player cohort")
        for player_id in self.player_ids:
            validate_id(player_id, kind="opposition cohort player ID")
        if len(self.player_ids) != len(set(self.player_ids)):
            raise ValueError("opposition cohort cannot repeat players")
        if not isinstance(self.slices, tuple) or any(
            not isinstance(item, EvidenceSlice) for item in self.slices
        ):
            raise TypeError("opposition evidence must be immutable slices")
        if sum(item.attempts for item in self.slices) != self.attempts:
            raise ValueError("opposition denominator must equal its cited evidence slices")
        if sum(item.successes for item in self.slices) != self.successes:
            raise ValueError("opposition numerator must equal its cited evidence slices")
        if len({item.match_id for item in self.slices}) != self.match_count:
            raise ValueError("opposition match count must equal its cited match cohort")
        if (self.attempts == 0) != (self.leading_observed_player_id is None):
            raise ValueError("leading observed player must match the presence of pass evidence")
        if self.observed_distributor_id is not None and self.observed_distributor_id != self.leading_observed_player_id:
            raise ValueError("recommended opposition target must be the leading observed passer")
        if self.attempts == 0 and self.completion_rate is not None:
            raise ValueError("an empty opposition sample cannot have a numeric completion rate")
        if self.attempts > 0 and self.completion_rate != self.successes / self.attempts:
            raise ValueError("opposition rate must match its recorded numerator and denominator")
        if self.completion_rate is not None and not 0.0 <= self.completion_rate <= 1.0:
            raise ValueError("opposition completion rate must be a fraction")
        if not self.context.strip():
            raise ValueError("opposition brief requires its metric context")
        if not self.caveat.strip():
            raise ValueError("opposition brief requires its evidence limitation")

    @property
    def source_observation_ids(self) -> tuple[str, ...]:
        return tuple(item for sample in self.slices for item in sample.source_observation_ids)

    @property
    def source_event_ids(self) -> tuple[EventId, ...]:
        return tuple(dict.fromkeys(item for sample in self.slices for item in sample.source_event_ids))


@dataclass(frozen=True)
class DossierDimension:
    dimension_id: str
    status: DossierDimensionStatus
    explanation: str
    source_observation_ids: tuple[str, ...] = ()
    source_event_ids: tuple[EventId, ...] = ()

    def __post_init__(self) -> None:
        validate_id(self.dimension_id, kind="recruitment dossier dimension ID")
        if not isinstance(self.status, DossierDimensionStatus):
            raise TypeError("dossier dimension requires an explicit evidence status")
        if not isinstance(self.explanation, str) or not self.explanation.strip():
            raise ValueError("dossier dimension requires its evidence explanation")
        if not isinstance(self.source_observation_ids, tuple) or not isinstance(self.source_event_ids, tuple):
            raise TypeError("dossier dimension evidence references must be immutable")
        for item in self.source_observation_ids:
            validate_id(item, kind="dossier observation ID")
        for item in self.source_event_ids:
            validate_id(item, kind="dossier event ID")


@dataclass(frozen=True)
class RecruitmentDossier:
    dossier_id: str
    source_report_id: str
    player_id: str
    role: RoleProfile
    as_of: WorldDate
    recommendation: Recommendation
    context: str
    finding: CandidateFinding
    dimensions: tuple[DossierDimension, ...]
    next_action: str

    def __post_init__(self) -> None:
        validate_id(self.dossier_id, kind="recruitment dossier ID")
        validate_id(self.source_report_id, kind="dossier source report ID")
        validate_id(self.player_id, kind="dossier player ID")
        if self.finding.player_id != self.player_id:
            raise ValueError("dossier finding must belong to its player")
        if not isinstance(self.role, RoleProfile) or not isinstance(self.as_of, WorldDate):
            raise TypeError("dossier requires its role and as-of date")
        if not isinstance(self.recommendation, Recommendation):
            raise TypeError("dossier requires its recruitment recommendation")
        if self.recommendation is not self.finding.recommendation:
            raise ValueError("dossier recommendation must match its source finding")
        if not isinstance(self.context, str) or not self.context.strip():
            raise ValueError("dossier requires the source metric context")
        if not isinstance(self.dimensions, tuple) or any(
            not isinstance(item, DossierDimension) for item in self.dimensions
        ):
            raise TypeError("dossier dimensions must be immutable evidence records")
        ids = [item.dimension_id for item in self.dimensions]
        if len(ids) != len(set(ids)):
            raise ValueError("dossier dimensions cannot repeat")
        if not isinstance(self.next_action, str) or not self.next_action.strip():
            raise ValueError("dossier requires an actionable next step")

    @property
    def source_observation_ids(self) -> tuple[str, ...]:
        return self.finding.source_observation_ids

    @property
    def source_event_ids(self) -> tuple[EventId, ...]:
        return self.finding.source_event_ids


@dataclass(frozen=True)
class MatchEvidenceReplay:
    match_id: MatchId
    evidence_date: WorldDate
    events: tuple[EventEnvelope, ...]

    def __post_init__(self) -> None:
        validate_id(self.match_id, kind="replay match ID")
        if not isinstance(self.evidence_date, WorldDate):
            raise TypeError("evidence replay requires a match date")
        if not isinstance(self.events, tuple) or not self.events:
            raise ValueError("evidence replay must contain cited events")
        if any(event.match_id != self.match_id for event in self.events):
            raise ValueError("replay events must belong to the cited match")
        chronology = [(event.match_tick, event.sequence) for event in self.events]
        if chronology != sorted(chronology):
            raise ValueError("replay events must preserve match chronology")


def _grant_map(grants: tuple[CoverageGrant, ...]) -> dict[str, CoverageGrant]:
    result: dict[str, CoverageGrant] = {}
    for grant in grants:
        if not isinstance(grant, CoverageGrant):
            raise TypeError("scouting requires coverage grants")
        previous = result.get(grant.grant_id)
        if previous is not None and previous != grant:
            raise ValueError("coverage grant ID was reused with conflicting permissions")
        result[grant.grant_id] = grant
    return result


def _authorized(observation: Observation, grants: dict[str, CoverageGrant], club_id: ClubId,
                as_of: WorldDate, lookback_days: int) -> bool:
    grant = grants.get(observation.coverage_grant_id)
    age = (as_of.day - observation.evidence_date.day).days
    return bool(
        observation.club_id == club_id
        and observation.field == "pass_completion"
        and observation.recorded_on <= as_of
        and 0 <= age <= lookback_days
        and observation.coverage_level.rank >= CoverageLevel.EVENTS.rank
        and grant is not None
        and grant.club_id == club_id
        and grant.match_id == observation.match_id
        and grant.active_on(observation.recorded_on)
        and grant.permits_field("pass_completion", CoverageLevel.EVENTS)
    )


def _eligible_observations(
    ledger: ObservationLedger,
    grants: tuple[CoverageGrant, ...],
    query: ScoutingQuery,
) -> dict[str, tuple[Observation, ...]]:
    if not isinstance(ledger, ObservationLedger):
        raise TypeError("scouting requires an observation ledger")
    if not isinstance(grants, tuple):
        raise TypeError("scouting requires immutable coverage grants")
    grants_by_id = _grant_map(grants)
    selected: dict[str, list[Observation]] = {player_id: [] for player_id in query.player_ids}
    for observation in ledger.observations:
        if observation.subject_id not in selected:
            continue
        if _authorized(observation, grants_by_id, query.club_id, query.as_of, query.lookback_days):
            selected[observation.subject_id].append(observation)

    seen_source_events: set[tuple[MatchId, EventId]] = set()
    for player_id, items in selected.items():
        items.sort(key=lambda item: (item.evidence_date.day, str(item.match_id), item.source_tick,
                                     item.source_sequence, item.staff_id, item.observation_id))
        # Ledger idempotency blocks identical chains. This stricter report check also
        # blocks an overlapping/reshaped source chain from becoming another attempt.
        for item in items:
            for event_id in item.source_event_ids:
                source_key = (item.match_id, event_id)
                if source_key in seen_source_events:
                    raise ValueError(f"source event is counted more than once for {player_id}")
                seen_source_events.add(source_key)
            if type(json.loads(item.value_json)) is not bool:
                raise ValueError("pass-completion observation must be boolean")
    return {player_id: tuple(items) for player_id, items in selected.items()}


def _wilson_interval(successes: int, trials: int) -> tuple[float, float]:
    proportion = successes / trials
    z_squared = _WILSON_Z_95 * _WILSON_Z_95
    denominator = 1.0 + z_squared / trials
    center = (proportion + z_squared / (2.0 * trials)) / denominator
    margin = (_WILSON_Z_95 * math.sqrt(
        proportion * (1.0 - proportion) / trials + z_squared / (4.0 * trials * trials)
    ) / denominator)
    return max(0.0, center - margin), min(1.0, center + margin)


def _slices(observations: tuple[Observation, ...]) -> tuple[EvidenceSlice, ...]:
    groups: dict[tuple[MatchId, WorldDate, str], list[Observation]] = defaultdict(list)
    for item in observations:
        groups[(item.match_id, item.evidence_date, item.staff_id)].append(item)
    result = []
    for (match_id, evidence_date, staff_id), items in sorted(
        groups.items(), key=lambda pair: (pair[0][1].day, str(pair[0][0]), pair[0][2])
    ):
        values = [json.loads(item.value_json) for item in items]
        result.append(EvidenceSlice(
            match_id=match_id,
            evidence_date=evidence_date,
            staff_id=staff_id,
            successes=sum(value is True for value in values),
            attempts=len(values),
            source_observation_ids=tuple(item.observation_id for item in items),
            source_event_ids=tuple(dict.fromkeys(
                event_id for item in items for event_id in item.source_event_ids
            )),
        ))
    return tuple(result)


def _finding(player_id: str, observations: tuple[Observation, ...], role: RoleProfile) -> CandidateFinding:
    samples = _slices(observations)
    attempts = sum(item.attempts for item in samples)
    successes = sum(item.successes for item in samples)
    match_count = len({item.match_id for item in samples})
    warnings: list[str] = []
    if attempts < role.minimum_attempts:
        warnings.append("small_sample")
    if match_count < role.minimum_matches:
        warnings.append("too_few_matches")

    by_match: dict[MatchId, list[EvidenceSlice]] = defaultdict(list)
    for sample in samples:
        by_match[sample.match_id].append(sample)
    if any(len({sample.rate for sample in group}) > 1 for group in by_match.values()):
        warnings.append("staff_sample_rates_differ")
    match_rates = {
        match_id: sum(sample.successes for sample in group) / sum(sample.attempts for sample in group)
        for match_id, group in by_match.items()
    }
    if len(set(match_rates.values())) > 1:
        warnings.append("match_context_rates_differ")

    if attempts == 0:
        recommendation = Recommendation.NEEDS_MORE_EVIDENCE
        rate = lower = upper = None
    else:
        rate = successes / attempts
        lower, upper = _wilson_interval(successes, attempts)
        enough = attempts >= role.minimum_attempts and match_count >= role.minimum_matches
        if not enough:
            recommendation = Recommendation.NEEDS_MORE_EVIDENCE
        elif lower >= role.minimum_rate:
            recommendation = Recommendation.SHORTLIST
        elif upper < role.minimum_rate:
            recommendation = Recommendation.CRITERION_NOT_MET
        else:
            recommendation = Recommendation.REVIEW
    return CandidateFinding(
        player_id, successes, attempts, rate, lower, upper, match_count, samples,
        recommendation, tuple(warnings),
    )


def _role_metric(role: RoleProfile, registry: MetricRegistry):
    if not isinstance(registry, MetricRegistry):
        raise TypeError("scouting requires a metric registry")
    definition = registry.get(role.metric_id)
    if definition.aggregation is not MetricAggregation.RATE or definition.source_field != "pass_completion":
        raise ValueError("P11 role search currently supports registered pass-completion rates only")
    if definition.minimum_coverage.rank > CoverageLevel.EVENTS.rank:
        raise ValueError("pass-completion search requires event-level coverage")
    return definition


def _report_id(kind: str, namespace: str, payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return derive_id("report", namespace, kind, digest)


def _observation_fingerprint(item: Observation) -> tuple[object, ...]:
    return (
        item.observation_id,
        str(item.club_id),
        str(item.match_id),
        item.subject_id,
        item.field,
        item.value_json,
        item.evidence_date.isoformat,
        item.recorded_on.isoformat,
        item.source_tick,
        item.source_sequence,
        item.method,
        item.coverage_level.value,
        item.coverage_grant_id,
        item.staff_id,
        tuple(map(str, item.source_event_ids)),
        item.provenance.kind.value,
        item.provenance.source,
        item.provenance.evidence_date.isoformat if item.provenance.evidence_date else None,
    )


def role_search(
    query: ScoutingQuery,
    role: RoleProfile,
    ledger: ObservationLedger,
    grants: tuple[CoverageGrant, ...],
    registry: MetricRegistry,
) -> RoleSearchReport:
    """Recommend a shortlist from current, permitted multi-match observations."""

    if not isinstance(query, ScoutingQuery) or not isinstance(role, RoleProfile):
        raise TypeError("role search requires a scouting query and profile")
    definition = _role_metric(role, registry)
    if role.minimum_attempts < definition.minimum_sample_size:
        raise ValueError(
            f"role minimum attempts cannot undercut the registered metric minimum "
            f"sample size ({definition.minimum_sample_size})"
        )
    if query.lookback_days > definition.max_evidence_age_days:
        raise ValueError("scouting lookback exceeds the registered metric evidence age")
    selected = _eligible_observations(ledger, grants, query)
    findings = tuple(_finding(player_id, selected[player_id], role) for player_id in query.player_ids)
    priority = {
        Recommendation.SHORTLIST: 0,
        Recommendation.REVIEW: 1,
        Recommendation.NEEDS_MORE_EVIDENCE: 2,
        Recommendation.CRITERION_NOT_MET: 3,
    }
    findings = tuple(sorted(findings, key=lambda item: (
        priority[item.recommendation], -(item.lower_bound if item.lower_bound is not None else -1.0),
        -item.attempts, item.player_id,
    )))
    evidence_key = tuple(
        _observation_fingerprint(item)
        for player_id in sorted(selected) for item in selected[player_id]
    )
    context = (f"P11 aggregates one authorized boolean observation per resolved pass across the "
               f"selected matches; the P10 source metric definition is: {definition.context} "
               f"Numerator: {definition.numerator_label}; denominator: "
               f"{definition.denominator_label}. Window: last {query.lookback_days} days as of "
               f"{query.as_of.isoformat}; only club-authorized event coverage is included. "
               f"Candidate cohort: {len(query.player_ids)} caller-supplied player IDs. "
               f"Shortlist threshold: {role.minimum_rate:.3f} with a 95% Wilson lower bound, "
               f"at least {role.minimum_attempts} resolved passes across "
               f"{role.minimum_matches} matches.")
    report_id = _report_id("role-search", "p11-role-search-v1", (
        str(query.club_id), query.as_of.isoformat, query.lookback_days,
        tuple(sorted(query.player_ids)),
        role.role_id, role.metric_id, role.minimum_rate,
        role.minimum_attempts, role.minimum_matches, registry.version,
        definition.display_name, definition.numerator_label,
        definition.denominator_label, definition.context, evidence_key,
    ))
    return RoleSearchReport(report_id, query.club_id, role, query.as_of,
                            query.lookback_days, context, findings)


def compare_candidates(
    query: ScoutingQuery,
    role: RoleProfile,
    ledger: ObservationLedger,
    grants: tuple[CoverageGrant, ...],
    registry: MetricRegistry,
) -> CandidateComparison:
    if len(query.player_ids) != 2:
        raise ValueError("candidate comparison requires exactly two player IDs")
    report = role_search(query, role, ledger, grants, registry)
    first = next(item for item in report.candidates if item.player_id == query.player_ids[0])
    second = next(item for item in report.candidates if item.player_id == query.player_ids[1])
    enough = all(
        item.attempts >= role.minimum_attempts and item.match_count >= role.minimum_matches
        for item in (first, second)
    )
    if (enough and first.lower_bound is not None and second.upper_bound is not None
            and first.lower_bound > second.upper_bound):
        outcome = ComparisonOutcome.FIRST_LEADS
        explanation = "The first player's observed-rate interval is above the second's; this is limited to the registered role metric."
    elif (enough and second.lower_bound is not None and first.upper_bound is not None
          and second.lower_bound > first.upper_bound):
        outcome = ComparisonOutcome.SECOND_LEADS
        explanation = "The second player's observed-rate interval is above the first's; this is limited to the registered role metric."
    else:
        outcome = ComparisonOutcome.INCONCLUSIVE
        explanation = "Evidence is insufficient or the observed-rate intervals overlap; review the match and staff samples before deciding."
    comparison_id = _report_id("comparison", "p11-candidate-comparison-v1", (
        report.report_id, first.player_id, second.player_id, outcome.value,
    ))
    return CandidateComparison(comparison_id, role, query.as_of, report.context,
                               first, second, outcome, explanation)


def opposition_brief(
    query: ScoutingQuery,
    ledger: ObservationLedger,
    grants: tuple[CoverageGrant, ...],
    *,
    minimum_attempts: int = 10,
    minimum_matches: int = 2,
) -> OppositionBrief:
    """Find a frequently observed passer without inferring an unseen tactic."""

    if type(minimum_attempts) is not int or minimum_attempts < 1:
        raise ValueError("opposition brief minimum attempts must be positive")
    if type(minimum_matches) is not int or minimum_matches < 1:
        raise ValueError("opposition brief minimum matches must be positive")
    metric = CORE_METRICS.get("pass_completion_rate")
    if minimum_attempts < metric.minimum_sample_size:
        raise ValueError(
            f"opposition minimum attempts cannot undercut the registered metric minimum "
            f"sample size ({metric.minimum_sample_size})"
        )
    if query.lookback_days > metric.max_evidence_age_days:
        raise ValueError("opposition lookback exceeds the registered metric evidence age")
    selected = _eligible_observations(ledger, grants, query)
    findings = [_finding(player_id, selected[player_id], RoleProfile(
        "role:opposition-distributor", "Observed distributor", "pass_completion_rate",
        0.0, minimum_attempts, minimum_matches,
    )) for player_id in query.player_ids]
    findings.sort(key=lambda item: (-item.attempts, -item.match_count, item.player_id))
    qualified = [item for item in findings
                 if item.attempts >= minimum_attempts and item.match_count >= minimum_matches]
    top = qualified[0] if qualified else findings[0]
    enough = bool(qualified)
    if enough:
        player_id = top.player_id
        recommendation = (
            f"Consider rehearsing coordinated pressure on {player_id} when they receive in build-up; "
            f"{top.attempts} resolved passes were observed across {top.match_count} matches."
        )
        unavailable = None
        rate = top.value
        slices = top.slices
    else:
        player_id = None
        recommendation = None
        unavailable = ("no_current_observations" if top.attempts == 0
                       else "minimum_evidence_threshold_not_met")
        rate = top.value
        slices = top.slices
    brief_id = _report_id("opposition-brief", "p11-opposition-brief-v1", (
        str(query.club_id), query.as_of.isoformat, query.lookback_days,
        query.player_ids, minimum_attempts, minimum_matches,
        CORE_METRICS.version,
        tuple(_observation_fingerprint(item)
              for person in selected.values() for item in person),
    ))
    caveat = (
        "This is a pressure hypothesis from authorized, resolved pass observations. It does not reveal "
        "the opponent's configured tactic or establish a fixed role; no tracking feed is available here."
    )
    definition = CORE_METRICS.get("pass_completion_rate")
    context = (
        f"Observed pass activity among the caller-supplied opposition players over the last "
        f"{query.lookback_days} days as of {query.as_of.isoformat}. Numerator: "
        f"{definition.numerator_label}; denominator: {definition.denominator_label}. "
        f"Opposition cohort: {len(query.player_ids)} caller-supplied player IDs. "
        f"Pressure recommendation requires {minimum_attempts} attempts across "
        f"{minimum_matches} matches."
    )
    return OppositionBrief(
        brief_id=brief_id,
        club_id=query.club_id,
        as_of=query.as_of,
        player_ids=query.player_ids,
        lookback_days=query.lookback_days,
        minimum_attempts=minimum_attempts,
        minimum_matches=minimum_matches,
        leading_observed_player_id=top.player_id if top.attempts else None,
        observed_distributor_id=player_id,
        successes=top.successes,
        attempts=top.attempts,
        match_count=top.match_count,
        completion_rate=rate,
        recommendation=recommendation,
        unavailable_reason=unavailable,
        slices=slices,
        context=context,
        caveat=caveat,
    )


def _resolve_replays(
    slices: tuple[EvidenceSlice, ...],
    events: tuple[EventEnvelope, ...],
) -> tuple[MatchEvidenceReplay, ...]:
    if not isinstance(events, tuple) or any(not isinstance(item, EventEnvelope) for item in events):
        raise TypeError("evidence replay requires an immutable event tuple")
    expected: dict[MatchId, dict[EventId, WorldDate]] = defaultdict(dict)
    for sample in slices:
        for event_id in sample.source_event_ids:
            prior = expected[sample.match_id].get(event_id)
            if prior is not None and prior != sample.evidence_date:
                raise ValueError("one cited event has conflicting evidence dates")
            expected[sample.match_id][event_id] = sample.evidence_date
    event_map: dict[EventId, EventEnvelope] = {}
    for event in events:
        previous = event_map.get(event.event_id)
        if previous is not None and previous != event:
            raise ValueError("event ID was reused with conflicting replay content")
        event_map[event.event_id] = event
    missing = [str(event_id) for match_events in expected.values() for event_id in match_events
               if event_id not in event_map]
    if missing:
        raise KeyError(f"cited replay event is missing: {missing[0]}")
    replays = []
    for match_id, refs in expected.items():
        selected = []
        for event_id in refs:
            event = event_map[event_id]
            if event.match_id != match_id or event.aggregate_type != "match" or event.aggregate_id != str(match_id):
                raise ValueError("cited replay event does not belong to its source match")
            selected.append(event)
        selected.sort(key=lambda event: (event.match_tick, event.sequence, str(event.event_id)))
        replay_date = next(iter(refs.values()))
        replays.append(MatchEvidenceReplay(match_id, replay_date, tuple(selected)))
    replays.sort(key=lambda item: (item.evidence_date.day, str(item.match_id)))
    return tuple(replays)


def replay_role_search(report: RoleSearchReport, events: tuple[EventEnvelope, ...]) -> tuple[MatchEvidenceReplay, ...]:
    slices = tuple(sample for candidate in report.candidates for sample in candidate.slices)
    return _resolve_replays(slices, events)


def replay_comparison(report: CandidateComparison, events: tuple[EventEnvelope, ...]) -> tuple[MatchEvidenceReplay, ...]:
    return _resolve_replays(report.first.slices + report.second.slices, events)


def replay_opposition_brief(report: OppositionBrief, events: tuple[EventEnvelope, ...]) -> tuple[MatchEvidenceReplay, ...]:
    return _resolve_replays(report.slices, events)


def build_recruitment_dossier(report: RoleSearchReport, player_id: str) -> RecruitmentDossier:
    """Create a role dossier and make unsupported resilience/fit factors explicit."""

    if not isinstance(report, RoleSearchReport):
        raise TypeError("recruitment dossier requires a role-search report")
    validate_id(player_id, kind="dossier candidate ID")
    finding = next((item for item in report.candidates if item.player_id == player_id), None)
    if finding is None:
        raise KeyError(f"candidate is not in the role-search report: {player_id}")

    recommendation_status = {
        Recommendation.SHORTLIST: DossierDimensionStatus.SUPPORTED,
        Recommendation.REVIEW: DossierDimensionStatus.MIXED,
        Recommendation.NEEDS_MORE_EVIDENCE: DossierDimensionStatus.UNKNOWN,
        Recommendation.CRITERION_NOT_MET: DossierDimensionStatus.NOT_SUPPORTED,
    }[finding.recommendation]
    dimensions = [DossierDimension(
        "role_metric_fit",
        recommendation_status,
        f"Observed intended-receiver pass completion: {finding.successes}/{finding.attempts}; "
        f"role threshold {report.role.minimum_rate:.3f} with current evidence requirements. "
        "This does not estimate hidden passing skill.",
        finding.source_observation_ids,
        finding.source_event_ids,
    )]

    match_groups: dict[MatchId, list[EvidenceSlice]] = defaultdict(list)
    for sample in finding.slices:
        match_groups[sample.match_id].append(sample)
    match_rates = {
        match_id: sum(item.successes for item in group) / sum(item.attempts for item in group)
        for match_id, group in match_groups.items()
    }
    if len(match_rates) < 2:
        consistency_status = DossierDimensionStatus.UNKNOWN
        consistency_text = "Fewer than two observed matches are available to compare match-to-match rates."
    elif len(set(match_rates.values())) == 1:
        consistency_status = DossierDimensionStatus.SUPPORTED
        consistency_text = (
            "The recorded pass-completion rate was consistent across observed matches; this does not "
            "prove resilience or explain the cause."
        )
    else:
        consistency_status = DossierDimensionStatus.MIXED
        consistency_text = (
            f"Observed match rates varied from {min(match_rates.values()):.3f} to "
            f"{max(match_rates.values()):.3f}; match context and sample differences are not controlled."
        )
    dimensions.append(DossierDimension(
        "match_rate_consistency",
        consistency_status,
        consistency_text,
        finding.source_observation_ids,
        finding.source_event_ids,
    ))

    staff_groups: dict[MatchId, list[EvidenceSlice]] = {
        match_id: group for match_id, group in match_groups.items() if len(group) > 1
    }
    if not staff_groups:
        staff_status = DossierDimensionStatus.UNKNOWN
        staff_text = "No match has separate staff samples that can be compared for agreement."
        staff_observations: tuple[str, ...] = ()
        staff_events: tuple[EventId, ...] = ()
    else:
        staff_observations = tuple(dict.fromkeys(
            observation_id for group in staff_groups.values() for sample in group
            for observation_id in sample.source_observation_ids
        ))
        staff_events = tuple(dict.fromkeys(
            event_id for group in staff_groups.values() for sample in group
            for event_id in sample.source_event_ids
        ))
        disagreement = any(len({sample.rate for sample in group}) > 1
                           for group in staff_groups.values())
        staff_status = DossierDimensionStatus.MIXED if disagreement else DossierDimensionStatus.SUPPORTED
        staff_text = (
            "Separate staff samples have different observed rates; inspect the cited sequences before "
            "treating them as disagreement about the player."
            if disagreement else "Separate staff samples report the same observed rate in each shared match."
        )
    dimensions.append(DossierDimension(
        "staff_sample_agreement", staff_status, staff_text, staff_observations, staff_events,
    ))

    dimensions.extend((
        DossierDimension(
            "competitive_adaptation", DossierDimensionStatus.UNKNOWN,
            "Competition and league identifiers are absent from P10 pass observations; adaptation across levels is unknown.",
        ),
        DossierDimension(
            "tactical_compatibility", DossierDimensionStatus.UNKNOWN,
            "P10 does not record this candidate's role assignments, off-ball movement, or team instructions; tactical fit is unknown.",
        ),
        DossierDimension(
            "physical_resilience", DossierDimensionStatus.UNKNOWN,
            "No authorized workload, health, or physical-tracking evidence is available for this candidate.",
        ),
    ))

    next_action = {
        Recommendation.SHORTLIST:
            "Advance to the shortlist, then gather availability, value, health, and broader role evidence before an offer.",
        Recommendation.REVIEW:
            "Keep under review and assign an independent observation focused on the role requirement.",
        Recommendation.NEEDS_MORE_EVIDENCE:
            "Gather additional current match observations before a recruitment decision.",
        Recommendation.CRITERION_NOT_MET:
            "Do not shortlist on this role criterion alone; review alternatives or revise the role requirement.",
    }[finding.recommendation]
    dossier_id = _report_id("recruitment-dossier", "p11-recruitment-dossier-v1", (
        report.report_id, player_id, finding.recommendation.value,
        tuple((item.dimension_id, item.status.value, item.explanation) for item in dimensions),
    ))
    return RecruitmentDossier(
        dossier_id, report.report_id, player_id, report.role, report.as_of,
        finding.recommendation, report.context, finding, tuple(dimensions), next_action,
    )


def replay_dossier(dossier: RecruitmentDossier, events: tuple[EventEnvelope, ...]) -> tuple[MatchEvidenceReplay, ...]:
    if not isinstance(dossier, RecruitmentDossier):
        raise TypeError("dossier replay requires a recruitment dossier")
    return _resolve_replays(dossier.finding.slices, events)
