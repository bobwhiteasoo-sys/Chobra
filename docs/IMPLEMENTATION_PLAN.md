# Chobra Implementation Plan

**Goal:** build as much of the Chobra full version (spec `docs/spec/Chobra_Full_Technical_Specification.md`) as can be made to really work and be verified on this machine, starting with stage 1 and covering stages 2 to 4 as far as possible.

**Architecture:** a pure Python engine (`packages/engine`, `packages/environments`, `packages/agents`, `packages/audit`, `packages/reporting`) with no HTTP dependency. A FastAPI service persists everything in PostgreSQL. A worker process claims jobs with leases and executes runs tick by tick, one transaction per tick. A Next.js App Router web app renders the Arena from confirmed server events delivered over SSE.

**Tech stack:** Python 3.13, FastAPI, Pydantic 2, SQLAlchemy 2, Alembic, psycopg 3, PostgreSQL 18 (embedded binaries), pytest + hypothesis; Next.js 16, React 19, TypeScript strict, TanStack Query, Radix UI, lucide-react, Inter (local), Playwright.

## Environment decisions (deviations from section 16 of the spec)

| Spec | Here | Why |
| --- | --- | --- |
| PostgreSQL in Docker | PostgreSQL 18 binaries from the `embedded-postgres` npm package, `infra/localdb/pg.sh` | The machine has no Docker or Homebrew |
| Redis broker + Celery | Job table in PostgreSQL with `FOR UPDATE SKIP LOCKED`, leases and `lease_generation` | No Redis; PostgreSQL is already the source of truth for job state (section 16) |
| S3 object storage | Local directory `.objects/` with immutable keys behind the same interface | No S3 locally |
| OIDC via Keycloak | `CHOBRA_AUTH_MODE=dev` login with a server session cookie (HttpOnly, SameSite) and CSRF header; OIDC settings documented | No IdP locally; the dev mode is labelled in the UI |
| Real model provider | Anthropic adapter (structured output via tool use), plus a fake adapter for tests | No `ANTHROPIC_API_KEY` on the machine; without a key the product runs in "режим без провайдера" (section 34) |

## Global constraints (verbatim values from the spec)

- Reward amounts are integers in `reward_microunits`; 1 point = 1 000 000 microunits. No binary float in ledgers or resource allocation.
- Rule tree limits: depth ≤ 12, nodes ≤ 500, size ≤ 256 KB. No eval of Python, JS or SQL.
- Dedup modes: `per_event`, `once_per_entity`, `once_per_root`, `once_per_actor_per_tick`. Ledger states: `pending`, `settled`, `reversed`, `rejected`.
- Run states: `draft, validating, queued, initializing, running, pause_requested, paused, resume_requested, cancel_requested, canceled, auditing, completed, failed, budget_exhausted`.
- Check results: `pass, fail, not_applicable, inconclusive`. Run verdict: `observed_violation, no_violation_observed, inconclusive`. Replay: `replay_verified, replay_failed, replay_unavailable`.
- Defaults: 3 agents, 12 objects, 30 ticks, 3 repetitions. Limits: 20 agents, 2000 objects, 240 ticks, 60 tail ticks, 100 runs per series, 4 concurrent runs per workspace.
- Split: depth ≤ 2, ≤ 5 children, positive overhead. Minimization budget: 200 executions, 60 s CPU.
- Bootstrap only with ≥ 10 complete pairs: 2000 resamples, fixed seed, 95 %. Wilson interval for violation rates.
- Zero denominator → `not_applicable`, never 0. Never say "правило безопасно" without the scope.
- Motion: press 140 ms, inspector 220 ms, marker 260 ms, highlight 160 ms, `cubic-bezier(0.23, 1, 0.32, 1)`, honour `prefers-reduced-motion`. At most 20 moving markers, 80 detailed nodes.
- Brand: name `Chobra`, the supplied cobra mark unchanged, tokens from `packages/design-tokens/tokens.json`.

## Review focus (failure modes most likely to bite users)

1. Duplicate or out-of-order SSE delivery must not double rewards or move cards twice (client reducer dedups by `seq`, refetches gaps).
2. A worker that crashes mid-tick, or loses its lease, must not double-apply a tick or a payout (tick commit checks `lease_generation`, unique `(run_id, seq)`).
3. A rule that pays on a field the agent can change (reported complexity) must be flagged in the editor and report, never silently accepted.
4. Incomplete runs (canceled, failed, budget) must never turn into "нарушения не обнаружены".
5. Replay must never call a model; a new model run must be labelled "Новый эксперимент".

## File structure

```
packages/engine/chobra_engine/     canonical.py rng.py contract.py events.py ledger.py runner.py replay.py
  rules/                           types.py validator.py interpreter.py examples.py diff.py
packages/environments/chobra_envs/ supportdesk.py taskboard.py resourcecommons.py registry.py
packages/agents/chobra_agents/     policies.py scoring.py llm.py anthropic_adapter.py budget.py memory.py
packages/audit/chobra_audit/       checks/ metrics.py minimize.py comparison.py findings.py fixes.py
packages/reporting/chobra_reporting/ export.py csv_safe.py markdown.py pdf.py
services/api/chobra_api/           app.py config.py db.py models.py security.py routers/ sse.py idempotency.py
services/api/migrations/           Alembic
services/worker/chobra_worker/     main.py jobs.py executor.py
apps/web/                          Next.js app (routes from spec section 20)
tests/                             engine, environments, rules, audit, api, e2e
```

## Tasks

Each task ends with passing tests and a commit.

1. **Engine core.** Canonical JSON and SHA-256 hashing, named hash-based RNG streams (`stable_int(seed, stream, *keys)`), environment contract (12 operations from section 06), event log with `seq`, `domain_seq`, `event_class`, hash chain. Tests: identical inputs give identical hashes; RNG streams are independent of call order.
2. **SupportDesk.** Section 07 semantics, actions and preconditions, confirmation and reopen through the `confirmations` stream, split with root identity and overhead, observation tail. Tests: AC-015, AC-018, AC-019, AC-020, AC-022, property test "split preserves remaining work".
3. **Rule language and ledger.** Typed JSON tree, validator with path errors (`RULE_TYPE_MISMATCH` and others), interpreter, three examples (RULE-003), field mutability flags (RULE-001), ledger with dedup and compensating entries. Tests: AC-008, AC-009, AC-012, AC-013, AC-014, AC-016, AC-017.
4. **Runner and checks.** Tick order from section 06, initiative order from seed, rewards from domain events, online checks emitting `check.failed`, final audit with verdicts, metrics with `not_applicable`. Tests: control event order from section 34 for the `issue_004` fixture; invariants.
5. **TaskBoard and ResourceCommons.** Sections 08 and 09, integer logistic regrowth, largest-remainder allocation. Tests: AC-023 to AC-028, property tests for allocation sum and non-negative stock.
6. **Agents.** Scripted policies for the three modes, scored by previewing rule payouts with delay tolerance; LLM adapter protocol, fake adapter, Anthropic adapter with one format correction and two network retries; budget reservations. Tests: AC-029, AC-030, AC-031, AC-036, AC-037, AC-038.
7. **Replay, minimization, comparison, fixes.** Replay with per-tick hash verification, ddmin minimization with re-execution, paired comparison with bootstrap and Wilson, heuristic fix proposals validated by the same validator. Tests: AC-034, AC-035, AC-051, AC-056 to AC-064.
8. **API and worker.** Tables from section 17 with RLS, Alembic migration, dev auth with roles, routes from section 18, idempotency keys, `If-Match` revisions, run state machine with 409 `allowed_commands`, worker with leases, SSE with `Last-Event-ID` and 15 s heartbeat. Tests: AC-002 to AC-006, AC-011, AC-032, AC-033, AC-039 to AC-042, AC-046, AC-047.
9. **Web app.** Brand assets and tokens, navigation, onboarding, projects, scenario editor, rule constructor with examples and diff, agents, experiment plan, live arena, replay, finding card, comparison, reports, settings, mobile layout, PWA shell. Tests: Playwright flows and widths.
10. **Reporting and docs.** JSON package with manifest and chain root, safe CSV, Markdown and PDF from the same snapshot, README, architecture, acceptance matrix filled with real evidence.
