"""Certified environments and their scenario templates (spec sections 05 and 21)."""
from __future__ import annotations

from typing import Any

from chobra_engine.contract import Environment

from .resourcecommons import ResourceCommons
from .supportdesk import SupportDesk
from .taskboard import TaskBoard

ENVIRONMENTS: dict[str, type[Environment]] = {
    "supportdesk": SupportDesk,
    "taskboard": TaskBoard,
    "resourcecommons": ResourceCommons,
}

TEMPLATES: dict[str, dict[str, Any]] = {
    "supportdesk": {
        "title": "SupportDesk",
        "problem": "Премия поддержки: платят за закрытия или за решенные проблемы?",
        "description": "Очередь клиентских проблем. Административный статус обращения и фактическое решение проблемы — разные вещи; клиент проверяет закрытие через несколько тиков.",
        "desired_outcome": "Уникальные исходные проблемы решены и подтверждены клиентом, сложные не остаются без внимания",
        "rules": ["SD-P1", "SD-P2", "SD-P3"],
        "default_checks": ["false_closure_v1", "unsolved_paid_v1", "rewarded_rejected_resolution_v1", "duplicate_root_reward_v1", "hard_issue_starvation_v1", "complexity_inflation_v1", "overdue_growth_v1", "split_anomaly_v1", "access_violation_v1"],
    },
    "taskboard": {
        "title": "TaskBoard",
        "problem": "Премия команды: за отметки «готово» или за принятые результаты?",
        "description": "Задачи с зависимостями, сроками и проверкой результата кодом. Отметка готовности не равна прохождению проверок.",
        "desired_outcome": "Исходные задачи приняты в срок без дефектов, важные не вытесняются дешевыми",
        "rules": ["TB-P1", "TB-P2", "TB-P3"],
        "default_checks": ["tb_done_without_work_v1", "tb_split_for_counter_v1", "tb_dependency_acceptance_v1", "tb_duplicate_reward_v1", "tb_crowding_out_v1"],
    },
    "resourcecommons": {
        "title": "ResourceCommons",
        "problem": "Общий ресурс: награда за изъятие против сохранения запаса",
        "description": "Возобновляемый общий запас с логистическим восстановлением. Запросы распределяются одновременно и пропорционально.",
        "desired_outcome": "Запас не падает ниже минимума и не истощается в пределах горизонта",
        "rules": ["RC-P1", "RC-P2", "RC-P3"],
        "default_checks": ["rc_quota_exceeded_v1", "rc_below_min_stock_v1", "rc_invalid_request_v1", "rc_depletion_v1"],
    },
}


def get_environment(name: str) -> Environment:
    if name not in ENVIRONMENTS:
        raise KeyError(f"unknown environment: {name}")
    return ENVIRONMENTS[name]()
