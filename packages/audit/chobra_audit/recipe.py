"""Everything needed to (re)build one run: the immutable snapshot of section 06."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from chobra_engine.runner import RunSession, RunSpec
from chobra_envs.registry import TEMPLATES, get_environment

from .catalog import build_checks


@dataclass(frozen=True)
class RunRecipe:
    run_id: str
    environment: str
    config: dict[str, Any]
    rule: dict[str, Any]
    rule_version_id: str
    seed: int
    actor_ids: list[str]
    rule_meta: dict[str, Any] = field(default_factory=dict)
    check_ids: list[str] | None = None
    tape: list[dict[str, Any]] | None = None
    agent_mode: str = "incentive_seeking"

    def checks(self) -> list[str]:
        return self.check_ids if self.check_ids is not None else TEMPLATES[self.environment]["default_checks"]

    def spec(self, agents: list[Any], *, rule: dict[str, Any] | None = None, run_id: str | None = None) -> RunSpec:
        env = get_environment(self.environment)
        return RunSpec(
            run_id=run_id or self.run_id,
            env=env,
            config=self.config,
            rule=rule or self.rule,
            rule_version_id=self.rule_version_id if rule is None else f"{self.rule_version_id}:candidate",
            seed=self.seed,
            agents=agents,
            checks=build_checks(self.environment, self.config, self.checks()),
            tape=self.tape,
            rule_meta=self.rule_meta,
            agent_mode=self.agent_mode,
        )

    def with_rule(self, rule: dict[str, Any], rule_version_id: str, rule_meta: dict[str, Any] | None = None) -> "RunRecipe":
        return replace(self, rule=rule, rule_version_id=rule_version_id, rule_meta=rule_meta or {})


def execute(recipe: RunRecipe, agents: list[Any], *, rule: dict[str, Any] | None = None, stop_on_check: str | None = None, until_tick: int | None = None) -> RunSession:
    session = RunSession(recipe.spec(agents, rule=rule))
    session.initialize()
    while not session.finished:
        if until_tick is not None and session.tick >= until_tick:
            break
        events = session.step()
        if stop_on_check and any(e.type == "check.failed" and e.payload["check_id"] == stop_on_check for e in events):
            break
    return session
