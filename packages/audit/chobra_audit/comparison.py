"""Paired comparison of rule variants (spec section 14).

Pairs share exogenous conditions (same seed, same tape). Differences are candidate minus
baseline, read in the metric's direction. Intervals appear only when there is enough data:
a percentile bootstrap needs at least ten complete pairs; violation rates use the Wilson
interval and always show how many runs were incomplete. Nothing is ever called "better"
in general; a mixed picture is named a trade-off.
"""
from __future__ import annotations

import math
import random
import statistics
from fractions import Fraction
from typing import Any

from chobra_envs.registry import TEMPLATES

Z95 = 1.959963984540054
BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 20261025

COMPARISON_METRICS: dict[str, list[tuple[str, str, str]]] = {
    "supportdesk": [
        ("resolved_rate", "higher", "Доля решенных исходных проблем"),
        ("confirmed_resolution_rate", "higher", "Доля подтвержденных клиентом решений"),
        ("false_closure_rate", "lower", "Доля ложных закрытий"),
        ("hard_coverage", "higher", "Покрытие сложных проблем"),
        ("overdue_roots", "lower", "Просроченные исходные проблемы"),
        ("duplicate_reward", "lower", "Дублирующие выплаты, микроединицы"),
        ("unresolved_effort", "lower", "Невыполненная работа"),
        ("reward_total", "neutral", "Начисленная награда, микроединицы"),
    ],
    "taskboard": [
        ("accepted_roots", "higher", "Принятые исходные задачи"),
        ("useful_work_per_effort", "higher", "Полезная работа на единицу ресурса"),
        ("late_ticks", "lower", "Суммарное опоздание"),
        ("defects", "lower", "Дефекты"),
        ("rework_effort", "lower", "Переделка"),
        ("high_importance_coverage", "higher", "Покрытие важных задач"),
        ("formal_done_nodes", "neutral", "Отметки «готово»"),
        ("reward_total", "neutral", "Начисленная награда, микроединицы"),
    ],
    "resourcecommons": [
        ("final_stock", "higher", "Запас в конце горизонта"),
        ("min_stock", "higher", "Минимальный запас"),
        ("sustainable_ticks", "higher", "Тики с запасом не ниже минимума"),
        ("total_use", "neutral", "Суммарное использование"),
        ("share_spread", "lower", "Неравномерность долей"),
        ("reward_total", "neutral", "Начисленная награда, микроединицы"),
    ],
}


def _fmt(value: Fraction | float | None, digits: int = 4) -> str | None:
    if value is None:
        return None
    return f"{float(value):.{digits}f}"


def wilson_interval(k: int, n: int) -> tuple[str, str] | None:
    """95 % Wilson score interval for k successes out of n."""
    if n == 0:
        return None
    p = k / n
    z2 = Z95 * Z95
    denom = 1 + z2 / n
    center = (p + z2 / (2 * n)) / denom
    half = Z95 * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / denom
    return _fmt(max(0.0, center - half)), _fmt(min(1.0, center + half))


def metric_number(sample: dict[str, Any] | None) -> Fraction | None:
    if not sample or sample.get("applicability") != "applicable" or sample.get("value") is None:
        return None
    if sample.get("unit") == "ratio":
        return Fraction(sample["numerator"], sample["denominator"])
    value = sample["value"]
    return Fraction(value) if isinstance(value, int) else None


def run_summary(recipe: Any, session: Any, *, variant: str, mode: str, model: str | None = None) -> dict[str, Any]:
    audit = session.audit or {}
    from chobra_engine.canonical import sha256_hex

    return {
        "run_id": session.spec.run_id,
        "variant": variant,
        "mode": mode,
        "model": model or "scripted",
        "seed": recipe.seed,
        "tape_hash": sha256_hex(session.tape),
        "status": session.status,
        "complete": session.status == "completed",
        "verdict": audit.get("verdict"),
        "metrics": audit.get("metrics", {}),
        "checks": {r["check_id"]: r["status"] for r in audit.get("checks", [])},
        "environment_version": session.env.version,
        "config_hash": sha256_hex(recipe.config),
    }


def _bootstrap(diffs: list[Fraction]) -> tuple[str, str] | None:
    if len(diffs) < 10:
        return None
    rng = random.Random(BOOTSTRAP_SEED)
    values = [float(d) for d in diffs]
    n = len(values)
    means = sorted(sum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(BOOTSTRAP_RESAMPLES))
    return _fmt(means[int(0.025 * BOOTSTRAP_RESAMPLES)]), _fmt(means[int(0.975 * BOOTSTRAP_RESAMPLES) - 1])


def compare_runs(runs: list[dict[str, Any]], *, baseline: str, candidate: str, environment: str) -> dict[str, Any]:
    modes = {r["mode"] for r in runs}
    if len(modes) > 1:
        return {"error": "mixed_modes", "message": "Запуски разных режимов агентов не объединяются в одну статистику; сравнивайте режимы раздельно", "modes": sorted(modes)}
    variants = {baseline: [r for r in runs if r["variant"] == baseline], candidate: [r for r in runs if r["variant"] == candidate]}
    counts = {v: {"planned": len(items), "completed": sum(1 for r in items if r["complete"]), "incomplete": sum(1 for r in items if not r["complete"])} for v, items in variants.items()}
    by_seed_a = {r["seed"]: r for r in variants[baseline]}
    by_seed_b = {r["seed"]: r for r in variants[candidate]}
    pairs = [(by_seed_a[s], by_seed_b[s]) for s in sorted(set(by_seed_a) & set(by_seed_b)) if by_seed_a[s]["complete"] and by_seed_b[s]["complete"]]
    tapes_match = all(a["tape_hash"] == b["tape_hash"] for a, b in pairs) if pairs else None
    changed = ["rule"]
    for key, label in (("model", "model"), ("environment_version", "environment_version"), ("config_hash", "scenario_config")):
        if any(a[key] != b[key] for a, b in pairs):
            changed.append(label)
    metrics: dict[str, Any] = {}
    improved, worsened = [], []
    for metric_id, direction, title in COMPARISON_METRICS.get(environment, []):
        rows = []
        excluded = 0
        for a, b in pairs:
            va, vb = metric_number(a["metrics"].get(metric_id)), metric_number(b["metrics"].get(metric_id))
            if va is None or vb is None:
                excluded += 1
                continue
            rows.append((a["seed"], va, vb, vb - va))
        diffs = [r[3] for r in rows]
        mean = sum(diffs, Fraction(0)) / len(diffs) if diffs else None
        median = Fraction(statistics.median(diffs)) if diffs else None
        effect = None
        if mean is not None and direction != "neutral" and mean != 0:
            effect = "improved" if (mean > 0) == (direction == "higher") else "worsened"
            (improved if effect == "improved" else worsened).append(title)
        metrics[metric_id] = {
            "title": title,
            "direction": direction,
            "pairs": len(rows),
            "excluded_not_applicable": excluded,
            "mean_diff": _fmt(mean),
            "median_diff": _fmt(median),
            "range": [_fmt(min(diffs)), _fmt(max(diffs))] if diffs else None,
            "pair_values": [{"seed": s, "baseline": _fmt(va), "candidate": _fmt(vb), "diff": _fmt(d)} for s, va, vb, d in rows],
            "bootstrap_ci": _bootstrap(diffs),
            "effect": effect,
        }
    violations: dict[str, dict[str, Any]] = {}
    check_ids = TEMPLATES[environment]["default_checks"]
    for variant, items in variants.items():
        per_check = {}
        for check_id in check_ids:
            complete = [r for r in items if r["complete"] and r["checks"].get(check_id) in ("pass", "fail")]
            fails = sum(1 for r in complete if r["checks"][check_id] == "fail")
            per_check[check_id] = {
                "failed": fails,
                "applicable": len(complete),
                "incomplete": sum(1 for r in items if not r["complete"]),
                "rate": _fmt(Fraction(fails, len(complete))) if complete else None,
                "wilson": wilson_interval(fails, len(complete)),
            }
        violations[variant] = per_check
    summary = []
    for metric_id, item in metrics.items():
        if item["mean_diff"] is not None:
            summary.append(f"{item['title']}: средняя разность «{candidate}» минус «{baseline}» = {item['mean_diff']} (пар: {item['pairs']})")
    tradeoffs = []
    if improved and worsened:
        tradeoffs.append(f"Компромисс: улучшились {', '.join(improved)}; ухудшились {', '.join(worsened)}")
    return {
        "baseline": baseline,
        "candidate": candidate,
        "mode": next(iter(modes)) if modes else None,
        "counts": counts,
        "pairs_complete": len(pairs),
        "pairing": {"tapes_match": tapes_match, "changed_factors": changed, "seeds": [a["seed"] for a, _ in pairs]},
        "metrics": metrics,
        "violations": violations,
        "improved": improved,
        "worsened": worsened,
        "tradeoffs": tradeoffs,
        "summary": summary,
        "interpretation": "Результаты описывают выбранную модель среды, генератор условий и конфигурацию агентов, а не поведение реальных сотрудников. Интервал Уилсона и bootstrap характеризуют разброс между выполненными испытаниями.",
        "bootstrap_policy": f"Bootstrap 95 % считается только при 10 и более полных парах: {BOOTSTRAP_RESAMPLES} повторных выборок, seed {BOOTSTRAP_SEED}",
    }
