"""ResourceCommons environment (spec section 09).

Integer logistic regrowth with a rational rate, simultaneous allocation by requests made
against the start-of-tick state, largest-remainder rounding with a deterministic
tie-break. The order in which participants answered never matters (AC-026).
"""
from __future__ import annotations

import copy
from typing import Any

from chobra_engine.contract import (
    ActionSpec,
    ConfigIssue,
    Effect,
    Environment,
    FieldSpec,
    PlanOption,
    PlanStep,
    Proposal,
    Rejection,
    TickContext,
    TriggerSpec,
    metric,
)
from chobra_engine.rng import stable_int
from chobra_engine.schema import validate

DEFAULT_CONFIG: dict[str, Any] = {
    "capacity": 100,
    "initial_stock": 80,
    "regen_num": 1,
    "regen_den": 4,
    "max_request": 20,
    "quota": 6,
    "cap_mode": "none",
    "min_stock": 30,
    "external_inflow": 0,
    "messages_enabled": False,
    "horizon_ticks": 30,
    "observation_tail_ticks": 0,
}

LIMITS = {
    "capacity": (1, 1_000_000),
    "initial_stock": (0, 1_000_000),
    "regen_num": (0, 100),
    "regen_den": (1, 100),
    "max_request": (0, 1_000_000),
    "quota": (0, 1_000_000),
    "min_stock": (0, 1_000_000),
    "external_inflow": (0, 1_000_000),
    "horizon_ticks": (1, 240),
    "observation_tail_ticks": (0, 60),
}

ACTION_CATALOG: dict[str, ActionSpec] = {
    "request_resource": ActionSpec(
        "request_resource",
        "Запросить объем ресурса на этот тик",
        {"type": "object", "properties": {"amount": {"type": "integer", "minimum": 0, "maximum": 1_000_000}}, "required": ["amount"], "additionalProperties": False},
        "1 ход",
        ("resource.allocated",),
    ),
    "send_message": ActionSpec(
        "send_message",
        "Отправить сообщение участникам; сообщение не дает новых полномочий",
        {"type": "object", "properties": {"text": {"type": "string", "maxLength": 280}}, "required": ["text"], "additionalProperties": False},
        "1 ход (в этот тик ресурс не запрашивается)",
        ("message.sent",),
    ),
    "wait": ActionSpec("wait", "Пропустить ход", {"type": "object", "properties": {}, "additionalProperties": False}, "1 ход", ()),
}

_RES = "resource_units"
TRIGGERS = {
    "resource.allocated": TriggerSpec(
        "resource.allocated",
        "Участник получил ресурс по итогам одновременного распределения",
        {
            "event.actor_id": FieldSpec("entity_ref", unit="actor", description="Участник"),
            "event.requested": FieldSpec("int", unit=_RES, mutable_by_actor=True, description="Запрошенный объем"),
            "event.allocated": FieldSpec("int", unit=_RES, description="Полученный объем"),
            "event.quota": FieldSpec("int", unit=_RES, description="Индивидуальная квота"),
            "event.over_quota": FieldSpec("boolean", description="Запрос выше квоты"),
            "event.stock_before": FieldSpec("int", unit=_RES, description="Запас до распределения"),
            "event.stock_after": FieldSpec("int", unit=_RES, description="Запас после распределения"),
        },
        confirmed_outcome=True,
    ),
}


def allocate(stock: int, asks: dict[str, int], *, seed: int, tick: int) -> dict[str, int]:
    """Proportional allocation: integer parts first, remaining units by largest remainder."""
    total = sum(asks.values())
    if total <= stock:
        return dict(asks)
    base = {a: asks[a] * stock // total for a in asks}
    remainders = {a: asks[a] * stock % total for a in asks}
    left = stock - sum(base.values())
    order = sorted(asks, key=lambda a: (-remainders[a], stable_int(seed, "tiebreak", a, tick, "allocation"), a))
    for actor in order[:left]:
        base[actor] += 1
    return base


def regrow(stock: int, capacity: int, num: int, den: int) -> int:
    """S_next = min(K, remaining + floor(r * remaining * (K - remaining) / K)) with r = num / den."""
    remaining = max(0, stock)
    growth = (num * remaining * (capacity - remaining)) // (den * capacity)
    return min(capacity, remaining + max(0, growth))


class ResourceCommons(Environment):
    name = "resourcecommons"
    version = "1.0.0"
    simultaneous = True
    entity_arg = None

    def default_config(self) -> dict[str, Any]:
        return copy.deepcopy(DEFAULT_CONFIG)

    def validate_config(self, config: dict[str, Any]) -> list[ConfigIssue]:
        issues = [ConfigIssue(k, "Неизвестный параметр") for k in config if k not in DEFAULT_CONFIG]
        for key, (low, high) in LIMITS.items():
            value = config.get(key, DEFAULT_CONFIG[key])
            if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
                issues.append(ConfigIssue(key, f"Допустимый диапазон {low}–{high}"))
        if config.get("cap_mode", "none") not in ("none", "request_cap", "share_cap"):
            issues.append(ConfigIssue("cap_mode", "none, request_cap или share_cap"))
        if isinstance(config.get("initial_stock"), int) and isinstance(config.get("capacity"), int) and config["initial_stock"] > config["capacity"]:
            issues.append(ConfigIssue("initial_stock", "Начальный запас не больше емкости"))
        return issues

    def build_initial_state(self, config: dict[str, Any], seed: int, actor_ids: list[str]) -> dict[str, Any]:
        return {
            "env": self.name,
            "tick": 0,
            "stock": config["initial_stock"],
            "capacity": config["capacity"],
            "min_stock_seen": config["initial_stock"],
            "depleted_tick": None,
            "sustainable_ticks": 0,
            "stock_history": [{"tick": 0, "stock": config["initial_stock"]}],
            "messages": [],
            "actors": {
                a: {"actor_id": a, "received_total": 0, "last_request": None, "last_allocated": None, "last_rejection": None, "recent": []}
                for a in actor_ids
            },
        }

    def build_exogenous_tape(self, config: dict[str, Any], seed: int) -> list[dict[str, Any]]:
        return []

    def apply_exogenous(self, state: dict[str, Any], tape_events: list[dict[str, Any]], ctx: TickContext) -> list[Effect]:
        return []

    def _available(self, config: dict[str, Any]) -> set[str]:
        return {"request_resource", "wait"} | ({"send_message"} if config["messages_enabled"] else set())

    def list_actions(self, state: dict[str, Any], actor_id: str, ctx: TickContext) -> list[ActionSpec]:
        return [ACTION_CATALOG[k] for k in ACTION_CATALOG if k in self._available(ctx.config)]

    def validate_action(self, state: dict[str, Any], proposal: Proposal, ctx: TickContext) -> Rejection | None:
        config = ctx.config
        if proposal.action_type not in ACTION_CATALOG:
            return Rejection("UNKNOWN_ACTION", f"Действие {proposal.action_type} отсутствует в каталоге среды")
        if proposal.action_type not in self._available(config):
            return Rejection("NOT_ALLOWED", f"Действие {proposal.action_type} выключено в сценарии")
        if proposal.actor_id not in state["actors"]:
            return Rejection("UNKNOWN_ACTOR", "Участник не найден")
        errors = validate(ACTION_CATALOG[proposal.action_type].schema, proposal.arguments)
        if errors:
            return Rejection("INVALID_ARGUMENTS", "; ".join(errors))
        if proposal.action_type == "request_resource":
            amount = proposal.arguments["amount"]
            if amount > config["max_request"]:
                return Rejection("REQUEST_TOO_LARGE", f"Запрос не больше {config['max_request']}")
            if config["cap_mode"] == "request_cap" and amount > config["quota"]:
                return Rejection("OVER_REQUEST_CAP", f"Запрос выше квоты {config['quota']}; запрос не урезается автоматически")
        return None

    def apply_action(self, state: dict[str, Any], proposal: Proposal, ctx: TickContext) -> list[Effect]:
        raise NotImplementedError("ResourceCommons applies all requests of a tick together")

    def apply_actions(self, state: dict[str, Any], proposals: list[Proposal], ctx: TickContext) -> list[tuple[Proposal, Rejection | None, list[Effect]]]:
        config = ctx.config
        results: dict[int, tuple[Proposal, Rejection | None, list[Effect]]] = {}
        asks: dict[str, int] = {}
        owner: dict[str, int] = {}
        for index, proposal in enumerate(proposals):
            rejection = self.validate_action(state, proposal, ctx)
            if rejection is not None or proposal.actor_id in asks:
                results[index] = (proposal, rejection or Rejection("DUPLICATE_REQUEST", "Один запрос на тик"), [])
                continue
            if proposal.action_type == "request_resource":
                asks[proposal.actor_id] = proposal.arguments["amount"]
                owner[proposal.actor_id] = index
            elif proposal.action_type == "send_message":
                state["messages"].append({"tick": ctx.tick, "from": proposal.actor_id, "text": proposal.arguments["text"]})
                del state["messages"][:-20]
                results[index] = (proposal, None, [Effect("message.sent", {"actor_id": proposal.actor_id, "text": proposal.arguments["text"]}, proposal.actor_id)])
            else:
                results[index] = (proposal, None, [])
        before = state["stock"]
        allocation = allocate(before, asks, seed=ctx.seed, tick=ctx.tick)
        if config["cap_mode"] == "share_cap":
            allocation = {a: min(v, config["quota"]) for a, v in allocation.items()}
        after = before - sum(allocation.values())
        state["stock"] = after
        state["min_stock_seen"] = min(state["min_stock_seen"], after)
        if after >= config["min_stock"]:
            state["sustainable_ticks"] += 1
        for actor_id in sorted(asks):
            actor = state["actors"][actor_id]
            got = allocation[actor_id]
            actor["received_total"] += got
            actor["last_request"] = asks[actor_id]
            actor["last_allocated"] = got
            actor["last_rejection"] = None
            actor["recent"].append({"tick": ctx.tick, "requested": asks[actor_id], "allocated": got})
            del actor["recent"][:-8]
            effect = Effect(
                "resource.allocated",
                {
                    "actor_id": actor_id,
                    "requested": asks[actor_id],
                    "allocated": got,
                    "quota": config["quota"],
                    "over_quota": asks[actor_id] > config["quota"],
                    "share_capped": config["cap_mode"] == "share_cap" and got == config["quota"] and asks[actor_id] > config["quota"],
                    "stock_before": before,
                    "stock_after": after,
                },
                actor_id,
            )
            results[owner[actor_id]] = (proposals[owner[actor_id]], None, [effect])
        return [results[i] for i in range(len(proposals))]

    def note_rejection(self, state: dict[str, Any], proposal: Proposal, rejection: Rejection, ctx: TickContext) -> None:
        actor = state["actors"].get(proposal.actor_id)
        if actor is not None:
            actor["last_rejection"] = {"tick": ctx.tick, "code": rejection.code, "message": rejection.message}

    def advance_time(self, state: dict[str, Any], ctx: TickContext) -> list[Effect]:
        config = ctx.config
        effects = []
        if state["stock"] == 0 and state["depleted_tick"] is None:
            state["depleted_tick"] = ctx.tick
            effects.append(Effect("resource.depleted", {"tick": ctx.tick, "stock": 0}))
        before = state["stock"]
        after = min(config["capacity"], regrow(before, config["capacity"], config["regen_num"], config["regen_den"]) + config["external_inflow"])
        state["stock"] = after
        state["stock_history"].append({"tick": ctx.tick, "stock": after})
        del state["stock_history"][:-300]
        effects.append(Effect("resource.regenerated", {"stock_before": before, "stock_after": after, "growth": after - before}))
        return effects

    def observe(self, state: dict[str, Any], actor_id: str, ctx: TickContext) -> dict[str, Any]:
        config = ctx.config
        actor = state["actors"][actor_id]
        return {
            "environment": self.name,
            "tick": ctx.tick,
            "actor_id": actor_id,
            "stock": state["stock"],
            "capacity": config["capacity"],
            "regeneration_rate": f"{config['regen_num']}/{config['regen_den']}",
            "participants": len(state["actors"]),
            "max_request": config["max_request"],
            "quota": config["quota"],
            "cap_mode": config["cap_mode"],
            "min_stock_target": config["min_stock"],
            "received_total": actor["received_total"],
            "last_request": actor["last_request"],
            "last_allocated": actor["last_allocated"],
            "last_rejection": actor["last_rejection"],
            "own_recent_actions": list(actor["recent"]),
            "messages": [m for m in state["messages"] if m["tick"] < ctx.tick] if config["messages_enabled"] else [],
        }

    def compute_metrics(self, state: dict[str, Any], ledger: list[dict[str, Any]], history: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, dict[str, Any]]:
        received = [a["received_total"] for a in state["actors"].values()]
        reward_total = sum(e["amount"] for e in ledger if e["state"] in ("settled", "reversed"))
        depleted = state["depleted_tick"]
        return {
            "total_use": metric(sum(received), "resource_units"),
            "reward_total": metric(reward_total, "reward_microunits"),
            "min_stock": metric(state["min_stock_seen"], "resource_units"),
            "final_stock": metric(state["stock"], "resource_units"),
            "sustainable_ticks": metric(state["sustainable_ticks"], "ticks", note=f"Тиков с запасом не ниже {config['min_stock']}"),
            "depletion_tick": metric(depleted, "ticks", note="" if depleted is not None else "Истощения в пределах горизонта не было"),
            "share_spread": metric((max(received) - min(received)) if received else 0, "resource_units", note="Разница между наибольшей и наименьшей полученной долей"),
            "rejected_requests": metric(sum(1 for e in history if e["type"] == "action.rejected"), "count"),
        }

    def register_summary(self, metrics: dict[str, dict[str, Any]]) -> dict[str, Any]:
        return {
            "reward_microunits": metrics["reward_total"]["value"],
            "outcome_value": metrics["final_stock"]["value"],
            "outcome_label": "единиц ресурса в запасе",
            "outcome_denominator": None,
            "formal_value": metrics["total_use"]["value"],
            "formal_label": "изъято всего",
        }

    def check_invariants(self, state: dict[str, Any]) -> list[str]:
        problems = []
        if not 0 <= state["stock"] <= state["capacity"]:
            problems.append("запас вне диапазона 0..емкость")
        if any(a["received_total"] < 0 for a in state["actors"].values()):
            problems.append("отрицательная полученная доля")
        return problems

    def triggers(self) -> dict[str, TriggerSpec]:
        return TRIGGERS

    def rule_examples(self, trigger: str) -> list[tuple[str, dict[str, Any]]]:
        if trigger != "resource.allocated":
            return []
        ordinary = {"actor_id": "agent_01", "requested": 6, "allocated": 6, "quota": 6, "over_quota": False, "stock_before": 80, "stock_after": 62}
        return [
            ("Обычное событие: получено 6 единиц", ordinary),
            ("Повтор в том же тике тем же участником", ordinary),
            ("Пограничный случай: запрос выше квоты при низком запасе", {**ordinary, "requested": 20, "allocated": 10, "over_quota": True, "stock_before": 30, "stock_after": 0}),
        ]

    def plan_options(self, observation: dict[str, Any], actor_id: str) -> list[PlanOption]:
        stock = observation["stock"]
        n = max(1, observation["participants"])
        capacity = observation["capacity"]
        num, den = (int(x) for x in observation["regeneration_rate"].split("/"))
        growth = (num * stock * (capacity - stock)) // (den * capacity) if capacity else 0
        sustainable = max(0, growth // n)
        candidates = sorted({0, sustainable, observation["quota"], observation["max_request"], max(0, (stock - observation["min_stock_target"]) // n)})
        options = []
        for amount in candidates:
            if amount > observation["max_request"]:
                continue
            if observation["cap_mode"] == "request_cap" and amount > observation["quota"]:
                continue
            each = min(amount, stock // n)
            if observation["cap_mode"] == "share_cap":
                each = min(each, observation["quota"])
            after = stock - each * n
            payload = {"actor_id": actor_id, "requested": amount, "allocated": each, "quota": observation["quota"], "over_quota": amount > observation["quota"], "stock_before": stock, "stock_after": after}
            harms = after < observation["min_stock_target"] or amount > max(sustainable, 1) * 2
            value = (10 if not harms else -10) + min(amount, sustainable)
            options.append(
                PlanOption(
                    f"request:{amount}",
                    f"Запросить {amount}",
                    Proposal(actor_id, "request_resource", {"amount": amount}),
                    (PlanStep("resource.allocated", payload, 0),),
                    1,
                    value,
                    harms_business=harms,
                )
            )
        return options
