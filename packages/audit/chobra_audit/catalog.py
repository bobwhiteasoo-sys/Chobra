"""Which checks exist for which environment."""
from __future__ import annotations

from typing import Any

from .checks.base import Check
from .checks.resourcecommons import RESOURCECOMMONS_CHECKS
from .checks.supportdesk import SUPPORTDESK_CHECKS
from .checks.taskboard import TASKBOARD_CHECKS

CHECKS: dict[str, list[type[Check]]] = {
    "supportdesk": SUPPORTDESK_CHECKS,
    "taskboard": TASKBOARD_CHECKS,
    "resourcecommons": RESOURCECOMMONS_CHECKS,
}


def available_checks(environment: str) -> list[dict[str, Any]]:
    from chobra_envs.registry import get_environment

    config_stub = get_environment(environment).default_config()
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
