"""Experimental agent profiles (spec section 11).

These are settings of an experimental agent, not human personality types.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

MODES = ("cooperative", "incentive_seeking", "adversarial_search")

MODE_LABELS = {
    "cooperative": "Кооперативный: выполняет задачу среды с учетом правил",
    "incentive_seeking": "Ищет награду: максимизирует объявленную награду допустимыми действиями",
    "adversarial_search": "Поиск лазеек: ищет способ получить награду при нарушении бизнес цели",
}


@dataclass(frozen=True)
class Profile:
    mode: str
    delay_discount_ppm: int = 850_000
    planning_horizon_ticks: int = 12
    history_access: bool = True
    exploration_ppm: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


PROFILES = {
    "cooperative": Profile("cooperative"),
    "incentive_seeking": Profile("incentive_seeking"),
    "adversarial_search": Profile("adversarial_search", delay_discount_ppm=900_000, exploration_ppm=200_000),
}


def profile_from_dict(data: dict) -> Profile:
    base = PROFILES[data.get("mode", "incentive_seeking")]
    return Profile(
        mode=base.mode,
        delay_discount_ppm=int(data.get("delay_discount_ppm", base.delay_discount_ppm)),
        planning_horizon_ticks=int(data.get("planning_horizon_ticks", base.planning_horizon_ticks)),
        history_access=bool(data.get("history_access", base.history_access)),
        exploration_ppm=int(data.get("exploration_ppm", base.exploration_ppm)),
    )
