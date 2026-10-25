"""Counterexample cards (spec section 15 "Структура контрпримера").

The explanation names the rule condition, the participant's action and the mechanism of
the mismatch, in a neutral tone. It never attributes intent to people.
"""
from __future__ import annotations

from typing import Any

from chobra_engine.rules.interpreter import rule_hash
from chobra_envs.registry import get_environment

POINT = 1_000_000


def _points(microunits: int) -> str:
    whole, frac = divmod(abs(microunits), POINT)
    sign = "-" if microunits < 0 else ""
    return f"{sign}{whole}" if frac == 0 else f"{sign}{whole}.{frac // 10_000:02d}"


def _related_events(events: list[dict[str, Any]], entity_ids: list[str], evidence: list[int], until_tick: int) -> list[dict[str, Any]]:
    wanted = set(entity_ids)
    roots = set(entity_ids)
    out = []
    for e in events:
        if e["event_class"] != "domain" or e["tick"] > until_tick:
            continue
        payload = e["payload"]
        touches = (
            e["seq"] in evidence
            or e.get("entity_id") in wanted
            or payload.get("root_issue_id") in roots
            or payload.get("root_task_id") in roots
            or payload.get("unit_ref") in roots
        )
        if touches and e["type"] not in ("tick.completed",):
            out.append({k: e[k] for k in ("seq", "domain_seq", "tick", "type", "actor_id", "entity_id", "payload")})
    return out[:80]


def _explain(check_id: str, violation: dict[str, Any], related: list[dict[str, Any]], rule_meta: dict[str, Any], trigger_text: str) -> str:
    name = rule_meta.get("name") or "действующее правило"
    rewards = [e for e in related if e["type"] == "reward.settled" and e["payload"]["reward_microunits"] > 0]
    paid = sum(e["payload"]["reward_microunits"] for e in rewards)
    closes = [e for e in related if e["type"] == "issue.closed"]
    if check_id == "rewarded_rejected_resolution_v1" and closes:
        close = closes[0]
        confirmation = next((e for e in related if e["type"] == "issue.confirmation_completed" and e["payload"]["confirmation_status"] == "rejected"), None)
        delay = confirmation["tick"] - close["tick"] if confirmation else "несколько"
        return (
            f"Правило «{name}» оплачивает событие «{trigger_text}». Участник {close['actor_id']} закрыл обращение {close['payload']['issue_id']} "
            f"до выполнения требуемой работы. Реестр начислил {_points(paid)} очк.; через {delay} тика проверка клиента отклонила решение и вернула обращение в очередь."
        )
    if check_id == "false_closure_v1" and closes:
        close = closes[0]
        paid_text = f"Реестр начислил {_points(paid)} очк." if paid else "Начисления за это закрытие не было."
        return f"Правило «{name}». Участник {close['actor_id']} закрыл обращение {close['payload']['issue_id']} до выполнения требуемой работы; статус изменился, проблема осталась нерешенной. {paid_text}"
    if check_id == "duplicate_root_reward_v1":
        return f"Правило «{name}» оплачивает событие «{trigger_text}». По одной исходной проблеме выплата начислена {len(rewards)} раза: единица учета правила — событие, а не исходная проблема."
    if check_id == "split_anomaly_v1":
        return f"Правило «{name}». Участник разделил обращение на части и закрывает их без решения; счетчик закрытий растет, исходная проблема не решена."
    if check_id == "tb_done_without_work_v1":
        return f"Правило «{name}» оплачивает событие «{trigger_text}». Участник отметил задачу готовой без выполненной работы; проверка результата кодом ее не принимала."
    if check_id == "rc_depletion_v1":
        return f"Правило «{name}» оплачивает полученный объем ресурса. Суммарные запросы превысили восстановление, и общий запас истощился в пределах горизонта."
    return f"Правило «{name}». {violation['message']}."


def build_findings(recipe: Any, events: list[dict[str, Any]], audit: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not audit:
        return []
    env = get_environment(recipe.environment)
    trigger = env.triggers().get(recipe.rule["trigger"])
    trigger_text = trigger.description if trigger else recipe.rule["trigger"]
    by_seq = {e["seq"]: e for e in events}
    agents = sorted({e["actor_id"] for e in events if e["type"] == "action.proposed" and e["actor_id"]})
    findings = []
    for result in audit["checks"]:
        if result["status"] != "fail" or not result["violations"]:
            continue
        violation = result["violations"][0]
        fail_event = next((e for e in events if e["type"] == "check.failed" and e["payload"]["check_id"] == result["check_id"] and e["payload"]["violation_key"] == violation["key"]), None)
        until = fail_event["tick"] if fail_event else audit["final_tick"]
        related = _related_events(events, violation["entity_ids"], violation["evidence_seqs"], until)
        findings.append(
            {
                "finding_id": f"{recipe.run_id}:{result['check_id']}",
                "run_id": recipe.run_id,
                "check_id": result["check_id"],
                "check_version": result["version"],
                "title": result["title"],
                "formula": result["formula"],
                "threshold": result["threshold"],
                "rule_version_id": recipe.rule_version_id,
                "rule_hash": rule_hash(recipe.rule),
                "rule_name": recipe.rule_meta.get("name", ""),
                "rule_condition": trigger_text,
                "environment": env.name,
                "environment_version": env.version,
                "seed": recipe.seed,
                "violation_count": len(result["violations"]),
                "violation": violation,
                "evidence_seqs": violation["evidence_seqs"],
                "check_failed_seq": fail_event["seq"] if fail_event else None,
                "violation_tick": until,
                "affected_entities": violation["entity_ids"],
                "events": related,
                "reward_microunits": sum(e["payload"]["reward_microunits"] for e in related if e["type"] in ("reward.settled", "reward.reversed")),
                "actual_outcome": audit["metrics"],
                "explanation": _explain(result["check_id"], violation, related, recipe.rule_meta, trigger_text),
                "scope": (
                    f"Нарушение наблюдалось в одном испытании: среда {env.name} {env.version}, seed {recipe.seed}, участников {len(agents)}, режим {recipe.agent_mode}. "
                    "Это свидетельство возможности такого поведения в модели среды, а не оценка его частоты у людей."
                ),
                "replay_status": "not_checked",
                "first_evidence": by_seq.get(violation["evidence_seqs"][0]) if violation["evidence_seqs"] else None,
            }
        )
    return findings
