"""Which checks exist for which environment."""
from __future__ import annotations

from typing import Any

from .checks.base import Check
from .checks.supportdesk import SUPPORTDESK_CHECKS

CHECKS: dict[str, list[type[Check]]] = {
    "supportdesk": SUPPORTDESK_CHECKS,
}


def available_checks(environment: str) -> list[dict[str, Any]]:
    config_stub: dict[str, Any] = {"starvation_threshold_ticks": 8, "horizon_ticks": 30}
    out = []
    for cls in CHECKS.get(environment, []):
        check = cls(config_stub)
        out.append({"check_id": check.check_id, "version": check.version, "title": check.title, "formula": check.formula, "scope": check.scope, "threshold": check.threshold})
    return out


def build_checks(environment: str, config: dict[str, Any], ids: list[str] | None = None) -> list[Check]:
    classes = CHECKS.get(environment, [])
    selected = [cls for cls in classes if ids is None or cls.check_id in ids]
    if ids is not None:
        unknown = set(ids) - {cls.check_id for cls in classes}
        if unknown:
            raise ValueError(f"unknown checks: {sorted(unknown)}")
    return [cls(config) for cls in selected]
