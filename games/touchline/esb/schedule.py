"""Value contracts for dated work and once-only settlement references."""

from __future__ import annotations

import json
from dataclasses import dataclass

from .ids import EventId, derive_id, validate_id
from .model import Money
from .time import WorldDate


@dataclass(frozen=True)
class ScheduledWork:
    work_id: str
    due_date: WorldDate
    sequence: int
    work_type: str
    payload_json: str = "{}"

    def __post_init__(self) -> None:
        validate_id(self.work_id, kind="scheduled work ID")
        if not isinstance(self.due_date, WorldDate):
            raise TypeError("scheduled work requires an explicit world date")
        if type(self.sequence) is not int or self.sequence < 0:
            raise ValueError("scheduled work sequence must be non-negative")
        if not self.work_type.strip():
            raise ValueError("scheduled work type must be non-empty")
        try:
            payload = json.loads(
                self.payload_json,
                parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
            )
            json.dumps(payload, allow_nan=False)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("scheduled work payload must be JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("scheduled work payload must be a JSON object")


def order_scheduled_work(items: tuple[ScheduledWork, ...]) -> tuple[ScheduledWork, ...]:
    """Order due work by calendar date, then explicit sequence; reject ambiguous ties."""
    slots = [(item.due_date.day, item.sequence) for item in items]
    if len(slots) != len(set(slots)):
        raise ValueError("scheduled work must have unique date/sequence pairs")
    return tuple(sorted(items, key=lambda item: (item.due_date.day, item.sequence, item.work_id)))


@dataclass(frozen=True)
class SettlementKey:
    family: str
    source_id: str

    def __post_init__(self) -> None:
        validate_id(self.family, kind="settlement family")
        validate_id(self.source_id, kind="settlement source ID")

    @property
    def idempotency_key(self) -> str:
        return f"settlement/{derive_id('settlement', self.family, self.source_id)}"


@dataclass(frozen=True)
class SettlementReceipt:
    key: SettlementKey
    settled_on: WorldDate
    event_id: EventId
    amount: Money | None = None

    def __post_init__(self) -> None:
        validate_id(self.event_id, kind="settlement event ID")
        if not isinstance(self.settled_on, WorldDate):
            raise TypeError("settlement receipt requires an explicit world date")
        if self.amount is not None and not isinstance(self.amount, Money):
            raise TypeError("settlement amount must use the Money value type")
