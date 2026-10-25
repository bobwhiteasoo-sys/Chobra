"""Portable JSON package and its verification (spec sections 19 and 36, AC-065, AC-066).

The manifest lists the versions and the SHA-256 of every part plus each run's chain root.
API keys, session tokens and raw model responses are never part of a package.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from chobra_engine.canonical import sha256_hex
from chobra_engine.events import GENESIS_HASH, Event

FORMAT = "chobra-package/1"


def build_package(report: dict[str, Any], runs: list[dict[str, Any]]) -> dict[str, Any]:
    parts = {"report": report, "runs": runs}
    manifest = {
        "format": FORMAT,
        "created_at": report["generated_at"],
        "engine": "chobra_engine 1.0.0",
        "environment": report["environment"]["name"],
        "environment_version": report["environment"]["version"],
        "hashes": {"report": sha256_hex(report), **{f"run:{r['run_id']}": sha256_hex(r) for r in runs}},
        "chain_roots": {r["run_id"]: r["chain_root"] for r in runs},
        "excluded": ["API ключи", "токены сессий", "сырые ответы моделей"],
    }
    return {"manifest": manifest, **parts}


def verify_chain(events: list[dict[str, Any]]) -> bool:
    prev = GENESIS_HASH
    for data in events:
        event = Event(**{k: data[k] for k in Event.__dataclass_fields__})
        if event.prev_hash != prev or sha256_hex(event.hash_material()) != event.event_hash:
            return False
        prev = event.event_hash
    return True


def verify_package(package: dict[str, Any], *, replay: bool = True) -> dict[str, Any]:
    from chobra_audit.recipe import RunRecipe
    from chobra_audit.replay_verify import verify_replay

    manifest = package["manifest"]
    problems = []
    if sha256_hex(package["report"]) != manifest["hashes"]["report"]:
        problems.append("report hash mismatch")
    results = []
    for run in package["runs"]:
        if sha256_hex(run) != manifest["hashes"].get(f"run:{run['run_id']}"):
            problems.append(f"run {run['run_id']}: hash mismatch")
        chain_ok = verify_chain(run["events"])
        if not chain_ok or (run["events"] and run["events"][-1]["event_hash"] != manifest["chain_roots"].get(run["run_id"])):
            problems.append(f"run {run['run_id']}: event chain broken")
        replay_result = None
        if replay:
            recipe = RunRecipe(run_id=run["run_id"], environment=run["environment"], config=run["config"], rule=run["rule"]["tree"], rule_version_id=run["rule"]["version_id"],
                               seed=run["seed"], actor_ids=run["actor_ids"], check_ids=run["checks"], rule_meta={"name": run["rule"]["name"]}, agent_mode=run["agent_mode"])
            replay_result = verify_replay(recipe, run["events"], check_id=None)
        results.append({"run_id": run["run_id"], "chain_ok": chain_ok, "replay": replay_result["status"] if replay_result else None})
    return {"ok": not problems and all(r["replay"] in (None, "replay_verified") for r in results), "problems": problems, "runs": results}


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify a Chobra JSON package and replay its runs locally")
    parser.add_argument("package")
    parser.add_argument("--no-replay", action="store_true")
    args = parser.parse_args()
    with open(args.package, encoding="utf-8") as fh:
        package = json.load(fh)
    result = verify_package(package, replay=not args.no_replay)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
