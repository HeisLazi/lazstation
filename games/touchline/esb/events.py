"""Versioned domain event envelopes; observations and debug traces stay separate."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date

from .ids import EventId, MatchId, validate_id
from .time import WorldDate


def _json_object(text: str, label: str) -> dict[str, object]:
    try:
        value = json.loads(
            text,
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} must contain JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


@dataclass(frozen=True)
class EventEnvelope:
    event_id: EventId
    aggregate_type: str
    aggregate_id: str
    sequence: int
    kind: str
    match_id: MatchId | None = None
    match_tick: int | None = None
    world_date: WorldDate | None = None
    cause_event_id: EventId | None = None
    parent_event_id: EventId | None = None
    payload_json: str = "{}"
    outcome_json: str = "{}"
    schema_version: int = 1

    def __post_init__(self) -> None:
        validate_id(self.event_id, kind="event ID")
        if self.match_id is not None:
            validate_id(self.match_id, kind="match ID")
        if self.cause_event_id is not None:
            validate_id(self.cause_event_id, kind="cause event ID")
        if self.parent_event_id is not None:
            validate_id(self.parent_event_id, kind="parent event ID")
        if not self.aggregate_type.strip() or not self.aggregate_id.strip():
            raise ValueError("event aggregate type and ID must be explicit")
        if self.world_date is not None and not isinstance(self.world_date, WorldDate):
            raise TypeError("event world date must be an explicit WorldDate")
        if type(self.sequence) is not int or self.sequence < 0:
            raise ValueError("event sequence must be a non-negative integer")
        if not self.kind.strip():
            raise ValueError("event kind must be non-empty")
        if (self.match_id is None) != (self.match_tick is None):
            raise ValueError("match ID and match tick must be supplied together")
        if self.match_tick is not None and (type(self.match_tick) is not int or self.match_tick < 0):
            raise ValueError("event match tick must be a non-negative integer")
        if self.match_id is None and self.world_date is None:
            raise ValueError("event requires a match tick or a world date")
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("unsupported event-envelope schema version")
        _json_object(self.payload_json, "event payload")
        _json_object(self.outcome_json, "event outcome")

    @property
    def payload(self) -> dict[str, object]:
        return _json_object(self.payload_json, "event payload")

    @property
    def outcome(self) -> dict[str, object]:
        return _json_object(self.outcome_json, "event outcome")

    @property
    def calendar_day(self) -> date | None:
        return self.world_date.day if self.world_date is not None else None
