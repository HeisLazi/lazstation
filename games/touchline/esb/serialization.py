"""Strict versioned JSON codec for early Touchline domain records."""

from __future__ import annotations

import json
import math
import types
from dataclasses import fields, is_dataclass
from datetime import date
from enum import Enum
from typing import Any, Union, get_args, get_origin, get_type_hints

_FORMAT = "esb.core-record"
_SCHEMA_VERSION = 1


class SerializationError(ValueError):
    pass


def _to_data(value: Any, path: str = "$") -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: _to_data(getattr(value, item.name), f"{path}.{item.name}") for item in fields(value)}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, tuple):
        return [_to_data(item, f"{path}[{index}]") for index, item in enumerate(value)]
    if isinstance(value, list):
        return [_to_data(item, f"{path}[{index}]") for index, item in enumerate(value)]
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise SerializationError(f"{path} dictionary keys must be strings")
        return {key: _to_data(value[key], f"{path}.{key}") for key in sorted(value)}
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise SerializationError(f"{path} must be finite")
        return value
    raise SerializationError(f"{path} contains unsupported type {type(value).__name__}")


def _from_data(value: Any, expected: Any, path: str = "$") -> Any:
    if hasattr(expected, "__supertype__"):
        return expected(_from_data(value, expected.__supertype__, path))

    origin = get_origin(expected)
    args = get_args(expected)
    if origin is types.UnionType or origin is Union:
        if value is None and type(None) in args:
            return None
        failures = []
        for option in args:
            if option is type(None):
                continue
            try:
                return _from_data(value, option, path)
            except (TypeError, ValueError, SerializationError) as exc:
                failures.append(exc)
        raise SerializationError(f"{path} does not match any allowed union type") from (failures[-1] if failures else None)

    if origin is list:
        if not isinstance(value, list):
            raise SerializationError(f"{path} must be a JSON array")
        item_type = args[0] if args else Any
        return [_from_data(item, item_type, f"{path}[{index}]") for index, item in enumerate(value)]
    if origin is tuple:
        if not isinstance(value, list):
            raise SerializationError(f"{path} must be a JSON array")
        if not args:
            return tuple(value)
        if len(args) == 2 and args[1] is Ellipsis:
            return tuple(_from_data(item, args[0], f"{path}[{index}]") for index, item in enumerate(value))
        if len(value) != len(args):
            raise SerializationError(f"{path} tuple length does not match its record type")
        return tuple(_from_data(item, kind, f"{path}[{index}]") for index, (item, kind) in enumerate(zip(value, args)))
    if origin is dict:
        if not isinstance(value, dict):
            raise SerializationError(f"{path} must be a JSON object")
        key_type, value_type = args if len(args) == 2 else (str, Any)
        return {
            _from_data(key, key_type, f"{path}.<key>"): _from_data(item, value_type, f"{path}.{key}")
            for key, item in value.items()
        }

    if expected is Any:
        return value
    if expected is date:
        if not isinstance(value, str):
            raise SerializationError(f"{path} must be an ISO calendar date")
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise SerializationError(f"{path} must be an ISO calendar date") from exc
    if isinstance(expected, type) and issubclass(expected, Enum):
        try:
            return expected(value)
        except ValueError as exc:
            raise SerializationError(f"{path} has an unknown enum value") from exc
    if isinstance(expected, type) and is_dataclass(expected):
        if not isinstance(value, dict):
            raise SerializationError(f"{path} must be an object record")
        record_fields = fields(expected)
        required_names = {item.name for item in record_fields}
        if set(value) != required_names:
            raise SerializationError(f"{path} fields do not match {expected.__name__}")
        hints = get_type_hints(expected)
        return expected(**{
            item.name: _from_data(value[item.name], hints.get(item.name, Any), f"{path}.{item.name}")
            for item in record_fields
        })
    if expected is bool:
        if type(value) is not bool:
            raise SerializationError(f"{path} must be a boolean")
        return value
    if expected is int:
        if type(value) is not int:
            raise SerializationError(f"{path} must be an integer")
        return value
    if expected is float:
        if type(value) not in (float, int) or not math.isfinite(value):
            raise SerializationError(f"{path} must be a finite number")
        return float(value)
    if expected is str:
        if not isinstance(value, str):
            raise SerializationError(f"{path} must be a string")
        return value
    if expected is type(None):
        if value is not None:
            raise SerializationError(f"{path} must be null")
        return None
    if isinstance(expected, type) and isinstance(value, expected):
        return value
    raise SerializationError(f"{path} cannot be decoded as {expected}")


def dumps(record: Any) -> str:
    if not is_dataclass(record) or isinstance(record, type):
        raise SerializationError("top-level value must be a dataclass record")
    envelope = {
        "format": _FORMAT,
        "schema_version": _SCHEMA_VERSION,
        "record_type": f"{type(record).__module__}.{type(record).__qualname__}",
        "payload": _to_data(record),
    }
    try:
        return json.dumps(envelope, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise SerializationError("record cannot be encoded as versioned JSON") from exc


def loads(text: str, expected_type: type[Any]) -> Any:
    try:
        envelope = json.loads(text, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except (TypeError, json.JSONDecodeError, ValueError) as exc:
        raise SerializationError("input is not valid finite JSON") from exc
    if not isinstance(envelope, dict) or set(envelope) != {"format", "schema_version", "record_type", "payload"}:
        raise SerializationError("record envelope is malformed")
    if (
        envelope["format"] != _FORMAT
        or type(envelope["schema_version"]) is not int
        or envelope["schema_version"] != _SCHEMA_VERSION
    ):
        raise SerializationError("unsupported record format or schema version")
    expected_name = f"{expected_type.__module__}.{expected_type.__qualname__}"
    if envelope["record_type"] != expected_name:
        raise SerializationError(f"record type mismatch: expected {expected_name}")
    try:
        return _from_data(envelope["payload"], expected_type)
    except SerializationError:
        raise
    except (TypeError, ValueError, KeyError) as exc:
        raise SerializationError("record payload violates its domain contract") from exc
