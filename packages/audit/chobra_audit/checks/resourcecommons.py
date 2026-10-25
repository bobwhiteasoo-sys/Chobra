"""ResourceCommons properties (spec section 09). Sustainability is judged only within the executed horizon."""
from __future__ import annotations

from .base import Check, violation


class QuotaExceeded(Check):
    check_id = "rc_quota_exceeded_v1"
    title = "Превышение квоты"
    formula = "полученный объем каждого участника за тик не выше квоты"
    scope = "Каждое распределение"

    def detect(self, new_events, state, history, env):
        return [
            violation(f"{e['payload']['actor_id']}@{e['tick']}", f"{e['payload']['actor_id']} получил {e['payload']['allocated']} при квоте {e['payload']['quota']}", [e["seq"]], [e["payload"]["actor_id"]])
            for e in new_events
            if e["type"] == "resource.allocated" and e["payload"]["allocated"] > e["payload"]["quota"]
        ]

    def applicability(self, state, history, metrics, env):
        return any(e["type"] == "resource.allocated" for e in history), "Распределений не было"


class BelowMinimum(Check):
    check_id = "rc_below_min_stock_v1"
    title = "Падение ниже установленного запаса"

    @property
    def threshold(self) -> str:  # type: ignore[override]
        return f"{self.config['min_stock']} единиц"

    @property
    def formula(self) -> str:  # type: ignore[override]
        return f"запас после распределения не ниже {self.config['min_stock']}"

    scope = "Каждый тик основного горизонта"

    def detect(self, new_events, state, history, env):
        for e in new_events:
            if e["type"] == "resource.allocated" and e["payload"]["stock_after"] < self.config["min_stock"]:
                return [violation(f"tick{e['tick']}", f"Запас упал до {e['payload']['stock_after']} при минимуме {self.config['min_stock']}", [e["seq"]], [])]
        return []

    def applicability(self, state, history, metrics, env):
        return any(e["type"] == "resource.allocated" for e in history), "Распределений не было"


class InvalidRequest(Check):
    check_id = "rc_invalid_request_v1"
    title = "Недопустимый запрос"
    formula = "запросы участников проходят проверку среды"
    scope = "Каждое предложение действия"

    def detect(self, new_events, state, history, env):
        return [
            violation(f"{e['seq']}", f"{e['actor_id']}: запрос отклонен ({e['payload']['code']})", [e["seq"]], [e["actor_id"]])
            for e in new_events
            if e["type"] == "action.rejected" and e["payload"]["code"] in ("REQUEST_TOO_LARGE", "OVER_REQUEST_CAP", "INVALID_ARGUMENTS")
        ]

    def applicability(self, state, history, metrics, env):
        return any(e["type"] == "action.proposed" for e in history), "Запросов не было"


class Depletion(Check):
    check_id = "rc_depletion_v1"
    title = "Истощение до конца горизонта"
    formula = "запас не достигает нуля в пределах основного горизонта"
    scope = "Весь основной горизонт"

    def detect(self, new_events, state, history, env):
        return [violation("depleted", f"Ресурс истощен на тике {e['tick']}", [e["seq"]], []) for e in new_events if e["type"] == "resource.depleted"]


RESOURCECOMMONS_CHECKS = [QuotaExceeded, BelowMinimum, InvalidRequest, Depletion]
