"""Domain services shared by the routes and the worker."""
from __future__ import annotations

import copy
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from chobra_agents.budget import PRICES
from chobra_agents.profiles import MODES, PROFILES
from chobra_engine.canonical import sha256_hex
from chobra_engine.rules import rule_hash, validate_rule
from chobra_envs.registry import ENVIRONMENTS, TEMPLATES, get_environment
from chobra_envs.rules_catalog import starting_rules

from .errors import ApiError, conflict
from .models import (
    AgentProfile,
    AuditLog,
    EnvironmentVersion,
    ExperimentBatch,
    Job,
    Project,
    RuleVersion,
    Run,
    ScenarioVersion,
    Workspace,
)

FINAL_RUN_STATES = {"completed", "canceled", "failed", "budget_exhausted"}
RUN_COMMANDS = {
    "draft": [],
    "validating": ["cancel"],
    "queued": ["cancel"],
    "initializing": ["cancel"],
    "running": ["pause", "cancel"],
    "pause_requested": ["cancel"],
    "paused": ["resume", "cancel"],
    "resume_requested": ["cancel"],
    "cancel_requested": [],
    "auditing": ["cancel"],
    "completed": [],
    "canceled": [],
    "failed": [],
    "budget_exhausted": [],
}
MAX_RUNS_PER_BATCH = 100
LIMITS = {"agents": 20, "objects": 2000, "horizon": 240, "tail": 60}
DECISION_CALLS_UPPER_BOUND = 4  # 1 call + 1 format correction + 2 network retries


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def audit(db: Session, workspace_id: uuid.UUID, user_id: uuid.UUID | None, operation: str, object_ref: str, **details: Any) -> None:
    db.add(AuditLog(workspace_id=workspace_id, actor_user_id=user_id, operation=operation, object_ref=object_ref, details=details))


def seed_environment_versions(db: Session) -> None:
    for name, cls in ENVIRONMENTS.items():
        env = cls()
        exists = db.execute(select(EnvironmentVersion).where(EnvironmentVersion.name == name, EnvironmentVersion.version == env.version)).scalar_one_or_none()
        if exists is None:
            schemas = {k: [v.type, v.unit, list(v.enum_values), v.mutable_by_actor] for t in env.triggers().values() for k, v in t.fields.items()}
            db.add(EnvironmentVersion(name=name, version=env.version, schemas_hash=sha256_hex(schemas), engine_image_digest="local-python-package"))


# --- projects -----------------------------------------------------------------------

def default_profiles(environment: str) -> list[dict[str, Any]]:
    return [
        {"name": "Ищет награду (сценарный)", "mode": "incentive_seeking", "kind": "scripted", "params": PROFILES["incentive_seeking"].to_dict()},
        {"name": "Кооперативный (сценарный)", "mode": "cooperative", "kind": "scripted", "params": PROFILES["cooperative"].to_dict()},
        {"name": "Поиск лазеек (сценарный)", "mode": "adversarial_search", "kind": "scripted", "params": PROFILES["adversarial_search"].to_dict()},
        {"name": "Ищет награду (модель)", "mode": "incentive_seeking", "kind": "model", "params": PROFILES["incentive_seeking"].to_dict(),
         "model_config_json": {"provider": "anthropic", "model": "claude-opus-5-5", "effort": "low", "max_output_tokens": 2048, "timeout_seconds": 90, "refusal_fallback": True}},
    ]


def create_project(db: Session, *, workspace_id: uuid.UUID, user_id: uuid.UUID, name: str, environment: str, description: str = "", tags: list[str] | None = None, is_demo: bool = False) -> Project:
    if environment not in ENVIRONMENTS:
        raise ApiError(422, "UNKNOWN_ENVIRONMENT", f"Среда {environment} не найдена")
    template = TEMPLATES[environment]
    project = Project(workspace_id=workspace_id, name=name, description=description or template["description"], environment_id=environment, tags=tags or [],
                      owner_id=user_id, is_demo=is_demo, research_question=template["problem"], desired_outcome=template["desired_outcome"])
    db.add(project)
    db.flush()
    env = get_environment(environment)
    config = env.default_config()
    scenario = ScenarioVersion(workspace_id=workspace_id, project_id=project.id, version=1, status="published", config_json=config, actor_count=3,
                               snapshot_hash=sha256_hex({"environment": environment, "version": env.version, "config": config, "actors": 3}), created_by=user_id, published_at=utcnow())
    db.add(scenario)
    for index, (key, rule) in enumerate(starting_rules(environment).items(), start=1):
        db.add(RuleVersion(workspace_id=workspace_id, project_id=project.id, version=index, name=f"{key} {rule['name']}", template_key=key, status="published",
                           ast_json=rule["tree"], ast_hash=rule_hash(rule["tree"]), source_text=rule["source_text"], description=rule["description"],
                           origin="template", created_by=user_id, published_at=utcnow()))
    for item in default_profiles(environment):
        db.add(AgentProfile(workspace_id=workspace_id, project_id=project.id, name=item["name"], mode=item["mode"], kind=item["kind"], params=item["params"],
                            model_config_json=item.get("model_config_json", {}), observation_policy={"history_access": True}, memory_config={"recent_observations": 4}))
    audit(db, workspace_id, user_id, "project.create", f"project:{project.id}", environment=environment)
    db.flush()
    return project


# --- versions ------------------------------------------------------------------------

def next_version(db: Session, model: type, project_id: uuid.UUID) -> int:
    return (db.execute(select(func.max(model.version)).where(model.project_id == project_id)).scalar() or 0) + 1


def check_revision(current: int, if_match: str | None) -> None:
    if if_match is None:
        raise ApiError(428, "PRECONDITION_REQUIRED", "Нужен заголовок If-Match с ревизией")
    if if_match.strip('"') != str(current):
        raise conflict("REVISION_CONFLICT", "Объект изменен другим пользователем", {"current_revision": current})


# --- batch planning --------------------------------------------------------------------

def expand_plan(db: Session, project: Project, plan: dict[str, Any]) -> dict[str, Any]:
    """Validate a series plan and expand it server-side; the client count is never trusted."""
    scenario = db.get(ScenarioVersion, uuid.UUID(str(plan["scenario_version_id"])))
    if scenario is None or scenario.project_id != project.id:
        raise ApiError(422, "BAD_PLAN", "Версия сценария не найдена в проекте")
    if scenario.status != "published":
        raise ApiError(422, "BAD_PLAN", "Запуски используют только опубликованный сценарий")
    workspace = db.get(Workspace, project.workspace_id)
    model_settings = workspace.model_settings or {}
    variants = []
    for item in plan.get("variants", []):
        rule = db.get(RuleVersion, uuid.UUID(str(item["rule_version_id"])))
        if rule is None or rule.project_id != project.id:
            raise ApiError(422, "BAD_PLAN", "Версия правила не найдена в проекте")
        if rule.status != "published":
            raise ApiError(422, "BAD_PLAN", f"Правило «{rule.name}» не опубликовано")
        profile_id = item.get("agent_profile_id") or plan.get("agent_profile_id")
        profile = db.get(AgentProfile, uuid.UUID(str(profile_id))) if profile_id else None
        if profile is None or profile.project_id != project.id:
            raise ApiError(422, "BAD_PLAN", "Профиль агентов не найден")
        model = profile.model_config_json.get("model") or model_settings.get("default_model", "claude-opus-5-5")
        if profile.kind == "model" and model not in model_settings.get("allowed_models", list(PRICES)):
            raise ApiError(422, "MODEL_NOT_ALLOWED", "Модель профиля не разрешена в настройках пространства")
        variants.append({"label": item.get("label") or rule.name, "rule_version_id": str(rule.id), "rule_hash": rule.ast_hash, "agent_profile_id": str(profile.id),
                         "mode": profile.mode, "kind": profile.kind, "model": model if profile.kind == "model" else "scripted"})
    if not 1 <= len(variants) <= 4:
        raise ApiError(422, "BAD_PLAN", "В серии от одного до четырех вариантов правил")
    seeds = [int(s) for s in plan.get("conditions", {}).get("seeds", [])]
    if not seeds or len(set(seeds)) != len(seeds):
        raise ApiError(422, "BAD_PLAN", "Нужен список различных seed")
    runs = len(variants) * len(seeds)
    if runs > MAX_RUNS_PER_BATCH:
        raise ApiError(422, "BAD_PLAN", f"Не больше {MAX_RUNS_PER_BATCH} запусков в серии; сейчас {runs}")
    config = copy.deepcopy(scenario.config_json)
    conditions = plan.get("conditions", {})
    if conditions.get("horizon_ticks"):
        config["horizon_ticks"] = int(conditions["horizon_ticks"])
    if conditions.get("observation_tail_ticks") is not None and "observation_tail_ticks" in config:
        config["observation_tail_ticks"] = int(conditions["observation_tail_ticks"])
    env = get_environment(project.environment_id)
    issues = env.validate_config(config)
    if issues:
        raise ApiError(422, "BAD_PLAN", "Условия серии не прошли проверку", {"issues": [{"path": i.path, "message": i.message} for i in issues]})
    agents = scenario.actor_count
    if agents > LIMITS["agents"] or config["horizon_ticks"] > LIMITS["horizon"] or env.tail_ticks(config) > LIMITS["tail"]:
        raise ApiError(422, "BAD_PLAN", "Превышены пределы запуска: 20 агентов, 240 тиков, 60 тиков наблюдения")
    checks = plan.get("checks") or TEMPLATES[project.environment_id]["default_checks"]
    unknown = set(checks) - set(TEMPLATES[project.environment_id]["default_checks"])
    if unknown:
        raise ApiError(422, "BAD_PLAN", f"Неизвестные проверки: {sorted(unknown)}")
    modes = {v["mode"] for v in variants}
    differences = []
    if len({v["agent_profile_id"] for v in variants}) > 1:
        differences.append("Варианты используют разные профили агентов: это дополнительный измененный фактор")
    if len(modes) > 1:
        differences.append("Варианты используют разные режимы агентов; статистика будет показана раздельно")
    model_variants = [v for v in variants if v["kind"] == "model"]
    limits = plan.get("limits", {})
    decisions = agents * config["horizon_ticks"] * len(seeds)
    upper_calls = len(model_variants) * decisions * DECISION_CALLS_UPPER_BOUND
    max_calls = int(limits.get("max_model_calls", upper_calls))
    max_output = int(limits.get("max_output_tokens_per_call", 2048))
    price = None
    money = None
    if model_variants:
        model_name = model_variants[0]["model"]
        price = PRICES.get(model_name)
        est_input = 6000
        calls = min(max_calls, upper_calls)
        if price:
            money = price.cost_microusd(calls * est_input, calls * max_output)
        if limits.get("money_limit_microusd") is not None and price is None:
            raise ApiError(422, "PRICE_UNKNOWN", "Денежный предел нельзя гарантировать без таблицы цен; задайте пределы токенов и вызовов")
    return {
        "project_id": str(project.id),
        "environment": project.environment_id,
        "environment_version": env.version,
        "scenario_version_id": str(scenario.id),
        "scenario_snapshot_hash": scenario.snapshot_hash,
        "config": config,
        "actor_count": agents,
        "variants": variants,
        "seeds": seeds,
        "checks": checks,
        "horizon_ticks": config["horizon_ticks"],
        "observation_tail_ticks": env.tail_ticks(config),
        "paired_exogenous_tape": True,
        "planned_runs": runs,
        "limits": {
            "max_model_calls": max_calls,
            "max_output_tokens_per_call": max_output,
            "max_wall_time_seconds": int(limits.get("max_wall_time_seconds", 1800)),
            "money_limit_microusd": limits.get("money_limit_microusd"),
        },
        "estimate": {
            "planned_runs": runs,
            "agent_decisions": decisions * len(variants),
            "model_calls_upper_bound": upper_calls,
            "model_calls_reserved": min(max_calls, upper_calls),
            "money_upper_bound_microusd": money,
            "price": {"model": price.model, "input_usd_per_mtok": f"{price.input_microusd_per_mtok / 1_000_000:.2f}", "output_usd_per_mtok": f"{price.output_microusd_per_mtok / 1_000_000:.2f}",
                      "currency": price.currency, "source": price.source, "as_of": price.as_of} if price else None,
            "scripted_only": not model_variants,
        },
        "differences": differences,
        "failure_policy": plan.get("failure_policy", "wait"),
        "modes": sorted(modes),
    }


def create_batch(db: Session, project: Project, user_id: uuid.UUID, expanded: dict[str, Any], title: str = "") -> ExperimentBatch:
    plan_hash = sha256_hex(expanded)
    batch = ExperimentBatch(workspace_id=project.workspace_id, project_id=project.id, title=title or "Серия испытаний", immutable_plan=expanded, plan_hash=plan_hash,
                            status="queued", planned_runs=expanded["planned_runs"], budget=expanded["limits"], budget_used={"calls": 0, "input_tokens": 0, "output_tokens": 0, "unknown_usage_calls": 0},
                            created_by=user_id)
    db.add(batch)
    db.flush()
    env = get_environment(expanded["environment"])
    for variant in expanded["variants"]:
        for seed in expanded["seeds"]:
            tape = env.build_exogenous_tape(expanded["config"], seed)
            snapshot = {
                "environment": expanded["environment"],
                "environment_version": expanded["environment_version"],
                "config": expanded["config"],
                "actor_ids": [f"agent_{i + 1:02d}" for i in range(expanded["actor_count"])],
                "rule_version_id": variant["rule_version_id"],
                "rule_hash": variant["rule_hash"],
                "agent_profile_id": variant["agent_profile_id"],
                "checks": expanded["checks"],
                "seed": seed,
                "tape_hash": sha256_hex(tape),
                "failure_policy": expanded["failure_policy"],
            }
            run = Run(workspace_id=project.workspace_id, project_id=project.id, batch_id=batch.id, variant_id=variant["rule_version_id"], variant_label=variant["label"],
                      rule_version_id=uuid.UUID(variant["rule_version_id"]), scenario_version_id=uuid.UUID(expanded["scenario_version_id"]), seed=seed,
                      agent_mode=variant["mode"], agent_kind=variant["kind"], status="queued", horizon_ticks=expanded["horizon_ticks"], tail_ticks=expanded["observation_tail_ticks"],
                      snapshot=snapshot, snapshot_hash=sha256_hex(snapshot), tape_hash=snapshot["tape_hash"])
            db.add(run)
            db.flush()
            enqueue(db, project.workspace_id, "run.execute", run.id)
    audit(db, project.workspace_id, user_id, "batch.create", f"batch:{batch.id}", planned_runs=expanded["planned_runs"])
    return batch


def enqueue(db: Session, workspace_id: uuid.UUID, kind: str, target_id: uuid.UUID, args: dict[str, Any] | None = None, priority: int = 0) -> Job:
    job = Job(workspace_id=workspace_id, kind=kind, target_id=target_id, args=args or {}, priority=priority)
    db.add(job)
    return job


def run_command(db: Session, run: Run, command: str) -> Run:
    allowed = RUN_COMMANDS.get(run.status, [])
    if command not in allowed:
        raise conflict("INVALID_STATE", f"Команда {command} недоступна в состоянии {run.status}", {"current_state": run.status, "allowed_commands": allowed})
    if command == "pause":
        run.status = "pause_requested"
    elif command == "resume":
        run.status = "resume_requested"
        enqueue(db, run.workspace_id, "run.execute", run.id)
    elif command == "cancel":
        if run.status in ("queued", "draft", "validating"):
            run.status = "canceled"
            run.stop_reason = "user"
            run.verdict = "inconclusive"
            run.finished_at = utcnow()
        elif run.status == "paused":
            run.status = "cancel_requested"
            enqueue(db, run.workspace_id, "run.execute", run.id)
        else:
            run.status = "cancel_requested"
    return run
