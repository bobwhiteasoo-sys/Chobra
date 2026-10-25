"""Scripted participants ("сценарные агенты", section 34).

A scripted participant asks the environment for candidate plans built from its own
observation, prices each plan with the declared rule through the engine's interpreter,
discounts delayed payouts by its delay tolerance and picks according to its mode. No
rule-specific shortcuts: a loophole is found only if the rule actually pays for it.
"""
from __future__ import annotations

from fractions import Fraction
from typing import Any, Callable

from chobra_engine.agent import AgentDecision
from chobra_engine.contract import Environment, PlanOption, TickContext
from chobra_engine.rng import chance_ppm, stable_int
from chobra_engine.rules.interpreter import EvalError, _Scope, evaluate_expr, evaluate_rule

from .profiles import Profile


class ScriptedAgent:
    kind = "scripted"

    def __init__(self, actor_id: str, env: Environment, rule: dict[str, Any], profile: Profile, seed: int):
        self.actor_id = actor_id
        self.env = env
        self.rule = rule
        self.profile = profile
        self.mode = profile.mode
        self.seed = seed

    def get_state(self) -> dict[str, Any]:
        return {}

    def set_state(self, state: dict[str, Any]) -> None:
        return None

    # --- pricing ----------------------------------------------------------------------
    def expected_payout(self, option: PlanOption, observation: dict[str, Any]) -> Fraction:
        rule = self.rule
        settlement = rule["settlement"]
        discount = Fraction(self.profile.delay_discount_ppm, 1_000_000)
        horizon = self.profile.planning_horizon_ticks
        paid = {r["unit_ref"] for r in observation.get("own_rewards", {}).get("recent", []) if r["state"] in ("settled", "pending")}
        used_keys: set[str] = set()
        total = Fraction(0)
        for step in option.steps:
            if step.event_type != rule["trigger"] or step.delay > horizon:
                continue
            try:
                outcome = evaluate_rule(rule, self.env, step.event_type, step.payload, tick=observation["tick"] + step.delay)
            except EvalError:
                continue
            if not outcome.fired:
                continue
            if outcome.dedup_key and (outcome.dedup_key in used_keys or (rule["deduplication"]["mode"] in ("once_per_root", "once_per_entity") and outcome.unit_ref in paid)):
                continue
            if outcome.dedup_key:
                used_keys.add(outcome.dedup_key)
            pay_delay = step.delay
            if settlement["mode"] == "hold_until_confirmation":
                match = settlement["match_field"].partition(".")[2]
                confirm = next((s for s in option.steps if s.event_type == settlement["confirm_event"] and s.payload.get(match) == step.payload.get(match) and s.delay >= step.delay), None)
                if confirm is None or confirm.delay > horizon:
                    continue
                if not evaluate_expr(settlement["confirm_condition"], _Scope(confirm.payload, None, observation["tick"], []), "confirm"):
                    continue
                pay_delay = confirm.delay
            value = Fraction(outcome.amount) * discount ** pay_delay
            claw = settlement.get("clawback")
            if claw:
                match = claw["match_field"].partition(".")[2]
                back = next((s for s in option.steps if s.event_type == claw["event"] and s.payload.get(match) == step.payload.get(match) and s.delay >= step.delay), None)
                if back is not None and back.delay <= horizon:
                    value -= Fraction(outcome.amount) * discount ** back.delay
            total += value
        return total

    # --- choice -------------------------------------------------------------------------
    def decide(self, observation: dict[str, Any], ctx: TickContext, notify: Callable[[str, dict[str, Any]], None]) -> AgentDecision:
        options = self.env.plan_options(observation, self.actor_id)
        scored = []
        for option in options:
            payout = self.expected_payout(option, observation)
            rate = payout / max(option.duration, 1)
            jitter = stable_int(self.seed, "agents", self.actor_id, option.key) % 1000
            scored.append((option, payout, rate, jitter))
        if self.mode == "cooperative":
            pool = [s for s in scored if not s[0].harms_business]
            best = max(pool, key=lambda s: (s[0].business_value, s[2], s[3]))
        elif self.mode == "incentive_seeking":
            best = max(scored, key=lambda s: (s[2], s[0].business_value, s[3]))
        else:
            loopholes = sorted((s for s in scored if s[0].harms_business and s[1] > 0), key=lambda s: (s[2], s[3]), reverse=True)
            if loopholes:
                best = loopholes[0]
                if len(loopholes) > 1 and chance_ppm(self.seed, "agents", self.profile.exploration_ppm, self.actor_id, ctx.tick, "explore"):
                    best = loopholes[1]
            else:
                best = max(scored, key=lambda s: (s[2], s[0].business_value, s[3]))
        option, payout, rate, _ = best
        points = float(payout) / 1_000_000
        summary = f"{option.label}: ожидаемая награда {points:.1f} очк. за {option.duration} ход."
        proposal = option.first_action
        proposal.decision_summary = summary[:500]
        return AgentDecision(proposal, note=option.key)
