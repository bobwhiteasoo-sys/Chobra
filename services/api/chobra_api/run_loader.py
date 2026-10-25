"""Rebuild a run's recipe and participants from its immutable snapshot."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from chobra_agents.llm import AnthropicAdapter, ModelAgent, ModelConfig
from chobra_agents.policies import ScriptedAgent
from chobra_agents.profiles import profile_from_dict
from chobra_audit.recipe import RunRecipe
from chobra_envs.registry import get_environment

from .config import settings
from .models import AgentProfile, ProviderKey, RuleVersion, Run
from .security import decrypt_secret


class ModelKeyMissing(Exception):
    pass


def recipe_for_run(db: Session, run: Run, rule: RuleVersion | None = None) -> RunRecipe:
    snap = run.snapshot
    rule = rule or db.get(RuleVersion, run.rule_version_id)
    return RunRecipe(
        run_id=str(run.id),
        environment=snap["environment"],
        config=snap["config"],
        rule=rule.ast_json,
        rule_version_id=str(rule.id),
        rule_meta={"name": rule.name, "source_text": rule.source_text, "description": rule.description},
        seed=int(snap["seed"]),
        actor_ids=list(snap["actor_ids"]),
        check_ids=list(snap["checks"]),
        agent_mode=run.agent_mode,
    )


def provider_key(db: Session, workspace_id) -> str | None:  # noqa: ANN001
    key = db.execute(select(ProviderKey).where(ProviderKey.workspace_id == workspace_id, ProviderKey.provider == "anthropic", ProviderKey.status == "active")).scalars().first()
    if key is not None:
        return decrypt_secret(key.ciphertext)
    return settings.anthropic_api_key or None


def build_agents(db: Session, run: Run, recipe: RunRecipe, budget: Any) -> list[Any]:
    profile = db.get(AgentProfile, run.snapshot["agent_profile_id"])
    params = {"mode": profile.mode, **(profile.params or {})}
    agent_profile = profile_from_dict(params)
    env = get_environment(recipe.environment)
    if profile.kind == "scripted":
        return [ScriptedAgent(actor, env, recipe.rule, agent_profile, recipe.seed) for actor in recipe.actor_ids]
    secret = provider_key(db, run.workspace_id)
    if not secret:
        raise ModelKeyMissing("Не задан ключ провайдера модели: доступны сценарные агенты и replay")
    adapter = AnthropicAdapter(api_key=secret)
    raw = profile.model_config_json or {}
    config = ModelConfig(
        model=raw.get("model", "claude-opus-5-5"),
        effort=raw.get("effort", "low"),
        max_output_tokens=int(raw.get("max_output_tokens", 2048)),
        timeout_seconds=int(raw.get("timeout_seconds", 90)),
        refusal_fallback=bool(raw.get("refusal_fallback", True)),
    )
    policy = run.snapshot.get("failure_policy", "wait")
    return [ModelAgent(actor, env, adapter, config, agent_profile, budget, failure_policy=policy) for actor in recipe.actor_ids]
