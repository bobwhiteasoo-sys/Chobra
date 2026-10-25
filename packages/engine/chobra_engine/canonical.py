"""Canonical JSON and hashing.

Canonical form: UTF-8, sorted keys, no insignificant whitespace. Binary floats are
rejected so that hashes of states, events and ledgers never depend on float formatting
(spec section 06 "Представление чисел").
"""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Any

CANONICALIZATION_VERSION = "chobra-c14n-1"


def _check(value: Any, path: str = "$") -> None:
    if isinstance(value, float):
        raise TypeError(f"binary float is not allowed in canonical data at {path}")
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"non-string key at {path}")
            _check(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _check(item, f"{path}[{index}]")


def _default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    raise TypeError(f"not canonical-serializable: {type(value).__name__}")


def canonical_dumps(value: Any) -> str:
    _check(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=_default)


def sha256_hex(value: Any) -> str:
    return hashlib.sha256(canonical_dumps(value).encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
