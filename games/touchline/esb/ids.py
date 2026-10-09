"""Stable, typed identifiers for the Touchline domain."""

from __future__ import annotations

import hashlib
import json
import re
from typing import NewType

PlayerId = NewType("PlayerId", str)
ClubId = NewType("ClubId", str)
MatchId = NewType("MatchId", str)
EventId = NewType("EventId", str)
CommandId = NewType("CommandId", str)
CareerId = NewType("CareerId", str)

IdPart = str | int | bool | None
_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")
_KIND_RE = re.compile(r"[a-z][a-z0-9-]{0,31}\Z")


def validate_id(value: str, *, kind: str = "identifier") -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise ValueError(f"invalid {kind}: expected a stable non-empty ID string")
    return value


def derive_id(kind: str, namespace: str, *parts: IdPart) -> str:
    """Derive a process-independent ID without Python's randomized ``hash``."""
    if not isinstance(kind, str) or not _KIND_RE.fullmatch(kind):
        raise ValueError("ID kind must be a lowercase token")
    if not isinstance(namespace, str) or not namespace.strip():
        raise ValueError("ID namespace must be non-empty")
    for part in parts:
        if part is not None and type(part) not in (str, int, bool):
            raise TypeError("ID parts must be JSON scalar values")
    payload = json.dumps(
        [namespace, *parts], ensure_ascii=False, allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.blake2b(
        kind.encode("ascii") + b"\0" + payload,
        digest_size=16,
        person=b"ESB-ID-v1",
    ).hexdigest()
    return f"{kind}:{digest}"


def new_player_id(namespace: str, *parts: IdPart) -> PlayerId:
    return PlayerId(derive_id("player", namespace, *parts))


def new_club_id(namespace: str, *parts: IdPart) -> ClubId:
    return ClubId(derive_id("club", namespace, *parts))


def new_match_id(namespace: str, *parts: IdPart) -> MatchId:
    return MatchId(derive_id("match", namespace, *parts))


def new_event_id(namespace: str, *parts: IdPart) -> EventId:
    return EventId(derive_id("event", namespace, *parts))


def new_command_id(namespace: str, *parts: IdPart) -> CommandId:
    return CommandId(derive_id("command", namespace, *parts))


def new_career_id(namespace: str, *parts: IdPart) -> CareerId:
    return CareerId(derive_id("career", namespace, *parts))
