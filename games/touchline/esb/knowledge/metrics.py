"""Explicit metric definitions used by observation-backed reports."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .model import OBSERVATION_FIELDS, CoverageLevel


class MetricAggregation(str, Enum):
    RATE = "rate"
    COUNT_PER_REPORT = "count_per_report"


@dataclass(frozen=True)
class MetricDefinition:
    metric_id: str
    display_name: str
    source_field: str
    aggregation: MetricAggregation
    unit: str
    minimum_coverage: CoverageLevel
    numerator_label: str
    denominator_label: str
    context: str
    max_evidence_age_days: int
    minimum_sample_size: int

    def __post_init__(self) -> None:
        for label, value in (
            ("metric ID", self.metric_id), ("display name", self.display_name),
            ("source field", self.source_field), ("unit", self.unit),
            ("numerator label", self.numerator_label),
            ("denominator label", self.denominator_label), ("context", self.context),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"metric {label} must be explicit")
        if not isinstance(self.aggregation, MetricAggregation):
            raise TypeError("metric aggregation must be registered")
        if not isinstance(self.minimum_coverage, CoverageLevel):
            raise TypeError("metric requires an explicit coverage level")
        if self.source_field not in OBSERVATION_FIELDS:
            raise ValueError("metric source field is not implemented or observable in P10")
        if type(self.max_evidence_age_days) is not int or self.max_evidence_age_days < 0:
            raise ValueError("metric evidence age must be a non-negative number of days")
        if type(self.minimum_sample_size) is not int or self.minimum_sample_size < 1:
            raise ValueError("metric minimum sample size must be positive")


@dataclass(frozen=True)
class MetricRegistry:
    version: str
    definitions: tuple[MetricDefinition, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.version, str) or not self.version.strip():
            raise ValueError("metric registry requires a version")
        if not isinstance(self.definitions, tuple) or any(
            not isinstance(item, MetricDefinition) for item in self.definitions
        ):
            raise TypeError("metric registry definitions must be immutable records")
        ids = [item.metric_id for item in self.definitions]
        if len(ids) != len(set(ids)):
            raise ValueError("metric registry IDs must be unique")

    def get(self, metric_id: str) -> MetricDefinition:
        definition = next((item for item in self.definitions if item.metric_id == metric_id), None)
        if definition is None:
            raise KeyError(f"metric is not registered: {metric_id}")
        return definition


CORE_METRICS = MetricRegistry(
    version="touchline-metrics-v1",
    definitions=(
        MetricDefinition(
            metric_id="pass_completion_rate",
            display_name="Observed intended-receiver pass completion",
            source_field="pass_completion",
            aggregation=MetricAggregation.RATE,
            unit="fraction",
            minimum_coverage=CoverageLevel.EVENTS,
            numerator_label="passes controlled by the intended receiver",
            denominator_label="passes with a recorded intended receiver and possession outcome",
            context="A single match; counts exclude passes without a recorded control outcome.",
            max_evidence_age_days=90,
            minimum_sample_size=10,
        ),
        MetricDefinition(
            metric_id="tracked_position_samples",
            display_name="Recorded player-position samples",
            source_field="tracked_position",
            aggregation=MetricAggregation.COUNT_PER_REPORT,
            unit="samples/report",
            minimum_coverage=CoverageLevel.TRACKING,
            numerator_label="authorized player-position samples",
            denominator_label="one report window",
            context="Counts only positions explicitly present in an authorized tracking event.",
            max_evidence_age_days=14,
            minimum_sample_size=20,
        ),
        MetricDefinition(
            metric_id="observed_goal_events",
            display_name="Observed goal events",
            source_field="goal_event",
            aggregation=MetricAggregation.COUNT_PER_REPORT,
            unit="events/report",
            minimum_coverage=CoverageLevel.RESULTS,
            numerator_label="authorized goal events recorded",
            denominator_label="one match report window",
            context="A goal-event count; it does not imply a final score or a completed match.",
            max_evidence_age_days=90,
            minimum_sample_size=1,
        ),
    ),
)
