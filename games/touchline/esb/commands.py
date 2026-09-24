"""Validate-before-mutate command processing with serializable idempotency receipts."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Callable, Generic, TypeVar

from .events import EventEnvelope
from .ids import CommandId, validate_id

StateT = TypeVar("StateT")


def canonical_object_json(text: str, label: str) -> str:
    try:
        value = json.loads(text)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} must contain JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class CommandEnvelope:
    command_id: CommandId
    idempotency_key: str
    command_type: str
    payload_json: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        validate_id(self.command_id, kind="command ID")
        if not self.idempotency_key.strip():
            raise ValueError("command idempotency key must be non-empty")
        if not self.command_type.strip():
            raise ValueError("command type must be non-empty")
        canonical_object_json(self.payload_json, "command payload")
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("unsupported command-envelope schema version")

    @property
    def canonical_payload_json(self) -> str:
        return canonical_object_json(self.payload_json, "command payload")

    @property
    def fingerprint(self) -> str:
        material = f"{self.command_type}\0{self.canonical_payload_json}".encode("utf-8")
        return hashlib.sha256(material).hexdigest()

    @property
    def payload(self) -> dict[str, object]:
        return json.loads(self.canonical_payload_json)


@dataclass(frozen=True)
class CommandRejection:
    code: str
    message: str

    def __post_init__(self) -> None:
        if not self.code.strip() or not self.message.strip():
            raise ValueError("command rejection requires a code and explanation")


@dataclass(frozen=True)
class CommandReceipt:
    idempotency_key: str
    request_fingerprint: str
    accepted: bool
    event_ids: tuple[str, ...] = ()
    result_json: str = "{}"
    rejection: CommandRejection | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.event_ids, tuple):
            raise TypeError("command receipt event IDs must be an immutable tuple")
        if type(self.accepted) is not bool:
            raise TypeError("command receipt acceptance must be boolean")
        if not self.idempotency_key.strip():
            raise ValueError("receipt idempotency key must be non-empty")
        if not re.fullmatch(r"[0-9a-f]{64}", self.request_fingerprint):
            raise ValueError("receipt request fingerprint must be SHA-256 hex")
        if self.accepted == (self.rejection is not None):
            raise ValueError("accepted receipts have no rejection; rejected receipts require one")
        if not self.accepted and self.event_ids:
            raise ValueError("rejected commands cannot record completed events")
        for event_id in self.event_ids:
            validate_id(event_id, kind="receipt event ID")
        canonical_object_json(self.result_json, "command result")


@dataclass(frozen=True)
class CommandLedger:
    receipts: tuple[CommandReceipt, ...] = ()
    events: tuple[EventEnvelope, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.receipts, tuple) or not isinstance(self.events, tuple):
            raise TypeError("command ledger records must be immutable tuples")
        keys = [item.idempotency_key for item in self.receipts]
        if len(keys) != len(set(keys)):
            raise ValueError("command ledger cannot repeat an idempotency key")
        event_ids = [item.event_id for item in self.events]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("command ledger cannot repeat an event ID")


@dataclass(frozen=True)
class CommandEffect:
    events: tuple[EventEnvelope, ...] = ()
    result_json: str = "{}"

    def __post_init__(self) -> None:
        if not isinstance(self.events, tuple):
            raise TypeError("command effect events must be an immutable tuple")
        canonical_object_json(self.result_json, "command result")
        event_ids = [event.event_id for event in self.events]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("one command cannot emit a duplicate event ID")


@dataclass(frozen=True)
class CommandExecution(Generic[StateT]):
    state: StateT
    ledger: CommandLedger
    receipt: CommandReceipt
    replayed: bool


class CommandProcessor(Generic[StateT]):
    """Run pure domain callbacks against copies and publish only successful state."""

    def __init__(
        self,
        validate: Callable[[StateT, CommandEnvelope], CommandRejection | None],
        apply: Callable[[StateT, CommandEnvelope], CommandEffect],
    ) -> None:
        self._validate = validate
        self._apply = apply

    def execute(
        self,
        state: StateT,
        ledger: CommandLedger,
        command: CommandEnvelope,
    ) -> CommandExecution[StateT]:
        fingerprint = command.fingerprint
        existing = next((r for r in ledger.receipts if r.idempotency_key == command.idempotency_key), None)
        if existing is not None:
            if existing.request_fingerprint == fingerprint:
                return CommandExecution(state, ledger, existing, replayed=True)
            rejection = CommandRejection(
                "idempotency_key_reused",
                "this idempotency key was already used for a different request",
            )
            receipt = CommandReceipt(command.idempotency_key, fingerprint, False, rejection=rejection)
            return CommandExecution(state, ledger, receipt, replayed=False)

        validation_state = copy.deepcopy(state)
        rejection = self._validate(validation_state, command)
        if rejection is not None:
            receipt = CommandReceipt(command.idempotency_key, fingerprint, False, rejection=rejection)
            return CommandExecution(state, ledger, receipt, replayed=False)

        working_state = copy.deepcopy(state)
        effect = self._apply(working_state, command)
        if not isinstance(effect, CommandEffect):
            raise TypeError("command apply callback must return CommandEffect")
        known_event_ids = {event.event_id for event in ledger.events}
        if any(event.event_id in known_event_ids for event in effect.events):
            raise ValueError("command emitted an event ID already present in the ledger")
        receipt = CommandReceipt(
            idempotency_key=command.idempotency_key,
            request_fingerprint=fingerprint,
            accepted=True,
            event_ids=tuple(event.event_id for event in effect.events),
            result_json=effect.result_json,
        )
        next_ledger = CommandLedger(
            receipts=ledger.receipts + (receipt,),
            events=ledger.events + effect.events,
        )
        return CommandExecution(working_state, next_ledger, receipt, replayed=False)
