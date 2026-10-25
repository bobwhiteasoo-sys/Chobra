"""Builds one report: a stored snapshot first, then the requested format from that snapshot."""
from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from chobra_audit.catalog import available_checks
from chobra_engine.contract import TickContext
from chobra_engine.rules import validate_rule
from chobra_envs.registry import TEMPLATES, get_environment

from chobra_api.models import Comparison, ExperimentBatch, Finding, Project, Report, RewardLedgerEntry, RuleVersion, Run, RunEvent
from chobra_api.objects import put_bytes

from .csv_safe import to_csv
from .package import build_package
from .pdf import html_to_pdf
from .render import html_document, markdown


def snapshot_for(db: Session, report: Report) -> dict[str, Any]:
    batch = db.get(ExperimentBatch, report.batch_id)
    project = db.get(Project, report.project_id)
    plan = batch.immutable_plan
    env = get_environment(plan["environment"])
    template_actions = [a.type for a in env.list_actions(env.build_initial_state(plan["config"], 1, ["agent_01"]), "agent_01", TickContext(1, 1, plan["config"]))]
    runs = db.execute(select(Run).where(Run.batch_id == batch.id).order_by(Run.variant_label, Run.seed)).scalars().all()
    comparison = db.execute(select(Comparison).where(Comparison.batch_id == batch.id).order_by(Comparison.created_at.desc()).limit(1)).scalar_one_or_none()
    variants = []
    for v in plan["variants"]:
        rule = db.get(RuleVersion, v["rule_version_id"])
        validation = validate_rule(rule.ast_json, env)
        variants.append({"label": v["label"], "rule_version_id": str(rule.id), "rule_hash": rule.ast_hash, "source_text": rule.source_text, "unit_of_account": validation.unit_of_account,
                         "warnings": [w.message for w in validation.warnings], "tree": rule.ast_json})
    checks = {c["check_id"]: c for c in available_checks(plan["environment"])}
    primary = comparison.result.get("primary") if comparison else None
    violations = []
    if primary and not primary.get("error"):
        for variant, per_check in primary["violations"].items():
            for check_id, row in per_check.items():
                violations.append({"variant": variant, "check_id": check_id, "title": checks.get(check_id, {}).get("title", check_id), **row})
    counts = {}
    for label in [v["label"] for v in plan["variants"]]:
        items = [r for r in runs if r.variant_label == label]
        counts[label] = {"planned": len(items), "completed": sum(1 for r in items if r.status == "completed"), "incomplete": sum(1 for r in items if r.status != "completed")}
    findings = db.execute(select(Finding).where(Finding.run_id.in_([r.id for r in runs]))).scalars().all()
    by_run = {r.id: r for r in runs}
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project": {"id": str(project.id), "name": project.name, "research_question": project.research_question, "desired_outcome": project.desired_outcome},
        "batch": {"id": str(batch.id), "title": batch.title, "plan_hash": batch.plan_hash, "status": batch.status},
        "environment": {"name": env.name, "version": env.version, "description": TEMPLATES[env.name]["description"], "actions": template_actions},
        "variants": variants,
        "conditions": {"seeds": plan["seeds"], "horizon_ticks": plan["horizon_ticks"], "observation_tail_ticks": plan["observation_tail_ticks"], "actor_count": plan["actor_count"],
                       "modes": plan["modes"], "agent_kind": ", ".join(sorted({v["kind"] for v in plan["variants"]})), "checks": plan["checks"]},
        "counts": counts,
        "comparison": primary,
        "violations": violations,
        "findings": [{"id": str(f.id), "check_id": f.check_id, "title": f.card["title"], "explanation": f.card["explanation"], "replay_status": f.replay_status,
                      "evidence_seqs": f.card["evidence_seqs"], "variant": by_run[f.run_id].variant_label, "seed": by_run[f.run_id].seed} for f in findings],
        "incomplete_runs": [{"run_id": str(r.id), "variant": r.variant_label, "seed": r.seed, "status": r.status, "stop_reason": r.stop_reason} for r in runs if r.status != "completed"],
        "runs": [{"run_id": str(r.id), "variant": r.variant_label, "seed": r.seed, "status": r.status, "verdict": r.verdict, "chain_root": r.chain_root} for r in runs],
        "summary": {"runs": len(runs), "completed": sum(1 for r in runs if r.status == "completed"), "findings": len(findings)},
    }


def _runs_for_package(db: Session, batch: ExperimentBatch) -> list[dict[str, Any]]:
    out = []
    for run in db.execute(select(Run).where(Run.batch_id == batch.id).order_by(Run.variant_label, Run.seed)).scalars():
        rule = db.get(RuleVersion, run.rule_version_id)
        events = db.execute(select(RunEvent).where(RunEvent.run_id == run.id).order_by(RunEvent.seq)).scalars().all()
        ledger = db.execute(select(RewardLedgerEntry).where(RewardLedgerEntry.run_id == run.id).order_by(RewardLedgerEntry.id)).scalars().all()
        snap = run.snapshot
        out.append({
            "run_id": str(run.id), "variant": run.variant_label, "seed": run.seed, "status": run.status, "verdict": run.verdict, "chain_root": run.chain_root,
            "environment": snap["environment"], "environment_version": snap["environment_version"], "config": snap["config"], "actor_ids": snap["actor_ids"], "checks": snap["checks"],
            "agent_mode": run.agent_mode, "agent_kind": run.agent_kind, "tape_hash": run.tape_hash,
            "rule": {"version_id": str(rule.id), "name": rule.name, "hash": rule.ast_hash, "tree": rule.ast_json},
            "events": [{"run_id": str(run.id), "seq": e.seq, "domain_seq": e.domain_seq, "event_class": e.event_class, "tick": e.tick, "type": e.type, "actor_id": e.actor_id,
                        "entity_id": e.entity_id, "payload": e.payload, "prev_hash": e.prev_hash, "event_hash": e.event_hash, "state_hash": e.state_hash, "schema_version": "1.0"} for e in events],
            "ledger": [{"entry_id": l.entry_id, "actor_id": l.actor_id, "amount": l.amount, "state": l.state, "reason": l.reason, "unit_ref": l.unit_ref, "tick": l.tick} for l in ledger],
            "audit": run.audit,
        })
    return out


def build_report(db: Session, report: Report) -> tuple[str, dict[str, Any]]:
    snapshot = snapshot_for(db, report)
    base = f"{report.workspace_id}/reports/{report.id}"
    if report.format == "json":
        batch = db.get(ExperimentBatch, report.batch_id)
        package = build_package(snapshot, _runs_for_package(db, batch))
        key = f"{base}/package.json"
        put_bytes(key, json.dumps(package, ensure_ascii=False, indent=1).encode("utf-8"))
    elif report.format == "csv":
        key = f"{base}/tables.zip"
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("runs.csv", to_csv(["run_id", "variant", "seed", "status", "verdict", "chain_root"], ([r["run_id"], r["variant"], r["seed"], r["status"], r["verdict"], r["chain_root"]] for r in snapshot["runs"])))
            archive.writestr("violations.csv", to_csv(["variant", "check_id", "title", "failed", "applicable", "incomplete", "wilson_low", "wilson_high"],
                                                      ([v["variant"], v["check_id"], v["title"], v["failed"], v["applicable"], v["incomplete"], *(v["wilson"] or ["", ""])] for v in snapshot["violations"])))
            comp = snapshot["comparison"] or {}
            archive.writestr("metric_differences.csv", to_csv(["metric", "seed", "baseline", "candidate", "diff"],
                                                              ([m, p["seed"], p["baseline"], p["candidate"], p["diff"]] for m, item in comp.get("metrics", {}).items() for p in item["pair_values"])))
            rewards = []
            for run in db.execute(select(Run).where(Run.batch_id == report.batch_id)).scalars():
                for l in db.execute(select(RewardLedgerEntry).where(RewardLedgerEntry.run_id == run.id).order_by(RewardLedgerEntry.id)).scalars():
                    rewards.append([str(run.id), run.variant_label, l.entry_id, l.actor_id, l.amount, l.state, l.reason, l.unit_ref, l.tick])
            archive.writestr("rewards.csv", to_csv(["run_id", "variant", "entry_id", "actor_id", "amount_microunits", "state", "reason", "unit_ref", "tick"], rewards))
            archive.writestr("README.txt", "Ячейки, начинающиеся с =, +, -, @, табуляции или возврата каретки, экранированы апострофом.\n".encode("utf-8"))
        put_bytes(key, buffer.getvalue())
    elif report.format == "markdown":
        key = f"{base}/report.md"
        put_bytes(key, markdown(snapshot).encode("utf-8"))
    else:
        key = f"{base}/report.pdf"
        put_bytes(key, html_to_pdf(html_document(snapshot)))
    return key, snapshot
