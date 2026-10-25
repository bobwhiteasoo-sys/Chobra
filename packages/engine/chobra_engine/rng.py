"""Named, call-order independent randomness (spec section 06).

Every random value is derived from a stable key: seed, stream name and the identifiers
of what is being decided (object id, tick, transition type). Nothing is consumed from a
shared generator, so the order of model calls or the branch a run takes cannot shift
the values another branch sees. This is what makes paired comparisons fair.
"""
from __future__ import annotations

import hashlib

from .canonical import canonical_dumps

STREAMS = frozenset({"arrivals", "object_traits", "confirmations", "external_changes", "tiebreak", "agents"})

PPM = 1_000_000


def stable_int(seed: int, stream: str, *keys: object) -> int:
    """Uniform 64-bit integer for (seed, stream, keys)."""
    if stream not in STREAMS:
        raise ValueError(f"unknown random stream: {stream}")
    material = canonical_dumps([int(seed), stream, [str(k) for k in keys]]).encode("utf-8")
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big")


def stable_below(seed: int, stream: str, upper: int, *keys: object) -> int:
    """Integer in [0, upper)."""
    if upper <= 0:
        raise ValueError("upper must be positive")
    return stable_int(seed, stream, *keys) % upper


def chance_ppm(seed: int, stream: str, ppm: int, *keys: object) -> bool:
    """True with probability ppm / 1_000_000."""
    if ppm <= 0:
        return False
    if ppm >= PPM:
        return True
    return stable_below(seed, stream, PPM, *keys) < ppm


def stable_order(seed: int, stream: str, items: list[str], *keys: object) -> list[str]:
    """Deterministic permutation of ids; ties broken by id so the result is total."""
    return sorted(items, key=lambda item: (stable_int(seed, stream, item, *keys), item))
