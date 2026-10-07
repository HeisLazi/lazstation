"""Club-scoped, as-of reporting over authorized observations only."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date

from games.touchline.esb.ids import EventId, derive_id

from .metrics import MetricAggregation, MetricDefinition, MetricRegistry
from .model import (
    CoverageGrant,
    CoverageLevel,
    FieldRequest,
    MetricFinding,
    Observation,
    ObservationLedger,
    Report,
    ReportCache,
    ReportFieldFinding,
    ReportQuery,
)


_WILSON_Z_95 = 1.96


def _observation_order(item: Observation) -> tuple[date, int, int, str]:
    return (item.recorded_on.day, item.source_tick, item.source_sequence, item.observation_id)


def _grant_map(grants: tuple[CoverageGrant, ...]) -> dict[str, CoverageGrant]:
    result: dict[str, CoverageGrant] = {}
    for grant in grants:
        existing = result.get(grant.grant_id)
        if existing is not None and existing != grant:
            raise ValueError("coverage grant ID was reused with conflicting permissions")
        result[grant.grant_id] = grant
    return result


def _authorized_observation(
    observation: Observation,
    grants_by_id: dict[str, CoverageGrant],
    *,
    club_id: str,
    match_id: str,
    minimum_coverage: CoverageLevel,
) -> bool:
    grant = grants_by_id.get(observation.coverage_grant_id)
    return bool(
        grant is not None
        and observation.club_id == club_id == grant.club_id
        and observation.match_id == match_id == grant.match_id
        and grant.active_on(observation.recorded_on)
        and grant.permits_field(observation.field, minimum_coverage)
        and observation.coverage_level.rank <= grant.level.rank
    )


def _query_observations(
    ledger: ObservationLedger,
    query: ReportQuery,
    grants_by_id: dict[str, CoverageGrant],
    field: str,
    minimum_coverage: CoverageLevel,
) -> tuple[Observation, ...]:
    selected = [
        item for item in ledger.observations
        if item.club_id == query.club_id
        and item.match_id == query.match_id
        and item.field == field
        and item.recorded_on <= query.as_of
        and (query.subject_id is None or item.subject_id == query.subject_id)
        and _authorized_observation(
            item, grants_by_id, club_id=query.club_id, match_id=query.match_id,
            minimum_coverage=minimum_coverage,
        )
    ]
    selected.sort(key=_observation_order)
    return tuple(selected)


def _metric_definition_data(definition: MetricDefinition) -> dict[str, object]:
    return {
        "metric_id": definition.metric_id,
        "display_name": definition.display_name,
        "source_field": definition.source_field,
        "aggregation": definition.aggregation.value,
        "unit": definition.unit,
        "minimum_coverage": definition.minimum_coverage.value,
        "numerator_label": definition.numerator_label,
        "denominator_label": definition.denominator_label,
        "context": definition.context,
        "max_evidence_age_days": definition.max_evidence_age_days,
        "minimum_sample_size": definition.minimum_sample_size,
    }


def _grant_data(grant: CoverageGrant) -> dict[str, object]:
    return {
        "grant_id": grant.grant_id,
        "club_id": str(grant.club_id),
        "match_id": str(grant.match_id),
        "match_date": grant.match_date.isoformat,
        "starts_on": grant.starts_on.isoformat,
        "expires_on": grant.expires_on.isoformat,
        "level": grant.level.value,
        "permitted_fields": list(grant.permitted_fields),
        "permitted_event_kinds": list(grant.permitted_event_kinds),
        "method": grant.method,
        "minimum_work_units": grant.minimum_work_units,
    }


def _observation_data(observation: Observation) -> dict[str, object]:
    return {
        "observation_id": observation.observation_id,
        "club_id": str(observation.club_id),
        "match_id": str(observation.match_id),
        "subject_id": observation.subject_id,
        "field": observation.field,
        "value_json": observation.value_json,
        "evidence_date": observation.evidence_date.isoformat,
        "recorded_on": observation.recorded_on.isoformat,
        "source_tick": observation.source_tick,
        "source_sequence": observation.source_sequence,
        "method": observation.method,
        "coverage_level": observation.coverage_level.value,
        "coverage_grant_id": observation.coverage_grant_id,
        "staff_id": observation.staff_id,
        "source_event_ids": [str(item) for item in observation.source_event_ids],
        "provenance": {
            "kind": observation.provenance.kind.value,
            "source": observation.provenance.source,
            "evidence_date": observation.provenance.evidence_date.isoformat
            if observation.provenance.evidence_date is not None else None,
        },
    }


def _query_data(query: ReportQuery) -> dict[str, object]:
    return {
        "club_id": str(query.club_id),
        "match_id": str(query.match_id),
        "as_of": query.as_of.isoformat,
        "metric_ids": list(query.metric_ids),
        "fields": [{
            "field": item.field,
            "minimum_coverage": item.minimum_coverage.value,
            "max_evidence_age_days": item.max_evidence_age_days,
        } for item in query.fields],
        "subject_id": query.subject_id,
        "method_version": query.method_version,
    }


def _cache_key(
    query: ReportQuery,
    registry: MetricRegistry,
    grants: tuple[CoverageGrant, ...],
    observations: tuple[Observation, ...],
) -> str:
    requested_definitions = [
        _metric_definition_data(registry.get(metric_id)) for metric_id in query.metric_ids
    ]
    payload = {
        "query": _query_data(query),
        "registry_version": registry.version,
        "metrics": requested_definitions,
        "grants": [_grant_data(item) for item in sorted(grants, key=lambda item: item.grant_id)],
        "observations": [_observation_data(item) for item in observations],
    }
    canonical = json.dumps(payload, ensure_ascii=False, allow_nan=False,
                           sort_keys=True, separators=(",", ":"))
    return "report-cache:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _unavailable_reason(
    *,
    field: str,
    minimum_coverage: CoverageLevel,
    max_age_days: int,
    query: ReportQuery,
    ledger: ObservationLedger,
    grants: tuple[CoverageGrant, ...],
    authorized: tuple[Observation, ...],
) -> str:
    fresh = [item for item in authorized
             if (query.as_of.day - item.evidence_date.day).days <= max_age_days]
    if fresh:
        return "no_observations"
    if authorized:
        return "stale_evidence"

    known = [item for item in ledger.observations
             if item.club_id == query.club_id and item.match_id == query.match_id
             and item.field == field and item.recorded_on <= query.as_of
             and (query.subject_id is None or item.subject_id == query.subject_id)]
    if known:
        return "provenance_not_authorized"

    matching_grants = [item for item in grants
                       if item.club_id == query.club_id and item.match_id == query.match_id]
    if not matching_grants:
        return "no_match_access"
    if all(item.starts_on > query.as_of for item in matching_grants):
        return "coverage_not_started"
    active_or_historical = [item for item in matching_grants if item.starts_on <= query.as_of]
    if active_or_historical and all(item.expires_on < query.as_of for item in active_or_historical):
        return "access_expired"
    capable = [item for item in matching_grants
               if item.level.rank >= minimum_coverage.rank]
    if not capable:
        return "coverage_insufficient"
    if all(field not in item.permitted_fields for item in capable):
        return "field_not_covered"
    return "no_observations"


def _source_event_ids(observations: tuple[Observation, ...]) -> tuple[EventId, ...]:
    return tuple(dict.fromkeys(event_id for item in observations for event_id in item.source_event_ids))


def _unavailable_metric(
    definition: MetricDefinition,
    reason: str,
    stale_evidence: tuple[Observation, ...] = (),
) -> MetricFinding:
    return MetricFinding(
        metric_id=definition.metric_id,
        value=None,
        unit=definition.unit,
        numerator_label=definition.numerator_label,
        denominator_label=definition.denominator_label,
        context=definition.context,
        numerator=None,
        denominator=None,
        sample_size=0,
        lower_bound=None,
        upper_bound=None,
        uncertainty=None,
        source_observation_ids=tuple(item.observation_id for item in stale_evidence),
        source_event_ids=_source_event_ids(stale_evidence),
        unavailable_reason=reason,
    )


def _wilson_interval(successes: int, trials: int) -> tuple[float, float]:
    if type(successes) is not int or type(trials) is not int or trials <= 0 or not 0 <= successes <= trials:
        raise ValueError("Wilson interval requires valid success and trial counts")
    z_squared = _WILSON_Z_95 * _WILSON_Z_95
    p = successes / trials
    denominator = 1.0 + z_squared / trials
    centre = (p + z_squared / (2.0 * trials)) / denominator
    margin = (_WILSON_Z_95 * math.sqrt(
        p * (1.0 - p) / trials + z_squared / (4.0 * trials * trials)
    ) / denominator)
    return max(0.0, centre - margin), min(1.0, centre + margin)


def _make_metric_finding(
    definition: MetricDefinition,
    observations: tuple[Observation, ...],
    *,
    stale_sources_excluded: bool = False,
) -> MetricFinding:
    values = [json.loads(item.value_json) for item in observations]
    n = len(values)
    if definition.aggregation is MetricAggregation.RATE:
        if any(type(value) is not bool for value in values):
            raise ValueError(f"metric {definition.metric_id} requires boolean observations")
        successes = sum(values)
        low, high = _wilson_interval(successes, n)
        warnings = (("small_sample",) if n < definition.minimum_sample_size else ())
        if stale_sources_excluded:
            warnings += ("stale_sources_excluded",)
        return MetricFinding(
            metric_id=definition.metric_id,
            value=successes / n,
            unit=definition.unit,
            numerator_label=definition.numerator_label,
            denominator_label=definition.denominator_label,
            context=definition.context,
            numerator=successes,
            denominator=n,
            sample_size=n,
            lower_bound=low,
            upper_bound=high,
            uncertainty="95% Wilson score interval",
            source_observation_ids=tuple(item.observation_id for item in observations),
            source_event_ids=_source_event_ids(observations),
            warning_codes=warnings,
        )
    if definition.aggregation is MetricAggregation.COUNT_PER_REPORT:
        warnings = (("small_sample",) if n < definition.minimum_sample_size else ())
        if stale_sources_excluded:
            warnings += ("stale_sources_excluded",)
        return MetricFinding(
            metric_id=definition.metric_id,
            value=float(n),
            unit=definition.unit,
            numerator_label=definition.numerator_label,
            denominator_label=definition.denominator_label,
            context=definition.context,
            numerator=n,
            denominator=1,
            sample_size=n,
            lower_bound=None,
            upper_bound=None,
            uncertainty="exact count of recorded authorized samples",
            source_observation_ids=tuple(item.observation_id for item in observations),
            source_event_ids=_source_event_ids(observations),
            warning_codes=warnings,
        )
    raise ValueError(f"unsupported registered aggregation: {definition.aggregation}")


def _field_finding(
    request: FieldRequest,
    query: ReportQuery,
    ledger: ObservationLedger,
    grants: tuple[CoverageGrant, ...],
    grants_by_id: dict[str, CoverageGrant],
) -> ReportFieldFinding:
    authorized = _query_observations(
        ledger, query, grants_by_id, request.field, request.minimum_coverage
    )
    fresh = tuple(item for item in authorized
                  if (query.as_of.day - item.evidence_date.day).days <= request.max_evidence_age_days)
    if not fresh:
        reason = _unavailable_reason(
            field=request.field,
            minimum_coverage=request.minimum_coverage,
            max_age_days=request.max_evidence_age_days,
            query=query,
            ledger=ledger,
            grants=grants,
            authorized=authorized,
        )
        stale = authorized if reason == "stale_evidence" else ()
        return ReportFieldFinding(
            request.field,
            0,
            source_observation_ids=tuple(item.observation_id for item in stale),
            source_event_ids=_source_event_ids(stale),
            unavailable_reason=reason,
        )
    return ReportFieldFinding(
        field=request.field,
        sample_count=len(fresh),
        source_observation_ids=tuple(item.observation_id for item in fresh),
        source_event_ids=_source_event_ids(fresh),
        warning_codes=("stale_sources_excluded",) if len(fresh) < len(authorized) else (),
    )


def build_report(
    query: ReportQuery,
    ledger: ObservationLedger,
    grants: tuple[CoverageGrant, ...],
    registry: MetricRegistry,
    cache: ReportCache | None = None,
) -> tuple[Report, ReportCache]:
    """Build once from authorized evidence, then serve identical cached output."""

    if not isinstance(query, ReportQuery) or not isinstance(ledger, ObservationLedger):
        raise TypeError("report building requires a query and observation ledger")
    if not isinstance(grants, tuple) or any(not isinstance(item, CoverageGrant) for item in grants):
        raise TypeError("report building requires an immutable coverage grant tuple")
    if not isinstance(registry, MetricRegistry):
        raise TypeError("report building requires a metric registry")
    if cache is None:
        cache = ReportCache()
    if not isinstance(cache, ReportCache):
        raise TypeError("report cache has an invalid type")

    grants_by_id = _grant_map(grants)
    matching_grants = tuple(sorted(
        (item for item in grants if item.club_id == query.club_id and item.match_id == query.match_id),
        key=lambda item: item.grant_id,
    ))
    unknown_metrics = [metric_id for metric_id in query.metric_ids
                       if metric_id not in {item.metric_id for item in registry.definitions}]
    if unknown_metrics:
        raise KeyError(f"report requested an unregistered metric: {unknown_metrics[0]}")

    permitted_observations = []
    for observation in ledger.observations:
        if (observation.club_id != query.club_id or observation.match_id != query.match_id
                or observation.recorded_on > query.as_of
                or (query.subject_id is not None and observation.subject_id != query.subject_id)):
            continue
        if _authorized_observation(
            observation, grants_by_id,
            club_id=query.club_id, match_id=query.match_id,
            minimum_coverage=observation.coverage_level,
        ):
            permitted_observations.append(observation)
    permitted_observations.sort(key=_observation_order)
    evidence = tuple(permitted_observations)
    key = _cache_key(query, registry, matching_grants, evidence)
    cached = cache.get(key)
    if cached is not None:
        return cached, cache

    metric_findings: list[MetricFinding] = []
    for metric_id in query.metric_ids:
        definition = registry.get(metric_id)
        candidates = _query_observations(
            ledger, query, grants_by_id,
            definition.source_field, definition.minimum_coverage,
        )
        fresh = tuple(item for item in candidates
                      if (query.as_of.day - item.evidence_date.day).days <= definition.max_evidence_age_days)
        if not fresh:
            reason = _unavailable_reason(
                field=definition.source_field,
                minimum_coverage=definition.minimum_coverage,
                max_age_days=definition.max_evidence_age_days,
                query=query,
                ledger=ledger,
                grants=matching_grants,
                authorized=candidates,
            )
            stale = candidates if reason == "stale_evidence" else ()
            metric_findings.append(_unavailable_metric(definition, reason, stale))
        else:
            metric_findings.append(_make_metric_finding(
                definition, fresh, stale_sources_excluded=len(fresh) < len(candidates),
            ))

    field_findings = tuple(
        _field_finding(request, query, ledger, matching_grants, grants_by_id)
        for request in query.fields
    )
    report = Report(
        report_id=derive_id("report", "p10-report-v1", key),
        cache_key=key,
        query=query,
        generated_on=query.as_of,
        method_version=query.method_version,
        metric_findings=tuple(metric_findings),
        field_findings=field_findings,
    )
    return report, cache.add(report)
