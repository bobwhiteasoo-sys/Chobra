export type Role = "owner" | "admin" | "analyst" | "viewer";

export type Me = {
  id: string;
  display_name: string;
  email: string | null;
  locale: "ru" | "en";
  auth_mode: string;
  csrf_token: string;
  last_workspace_id: string | null;
  workspaces: { id: string; name: string; role: Role }[];
};

export type Workspace = {
  id: string;
  name: string;
  role: Role;
  limits: Record<string, number>;
  retention_policy: Record<string, number>;
  model_settings: Record<string, unknown>;
};

export type Scenario = {
  id: string;
  project_id: string;
  version: number;
  status: "draft" | "published";
  revision: number;
  config: Record<string, unknown>;
  actor_count: number;
  snapshot_hash: string | null;
  parent_id: string | null;
  published_at: string | null;
};

export type RuleTree = Record<string, unknown> & { trigger: string; deduplication: { mode: string; key_fields?: string[] }; settlement: Record<string, unknown> };

export type Rule = {
  id: string;
  project_id: string;
  version: number;
  name: string;
  template_key: string | null;
  status: "draft" | "published";
  revision: number;
  ast_hash: string;
  parent_id: string | null;
  origin: string;
  description: string;
  source_text: string;
  published_at: string | null;
  tree?: RuleTree;
};

export type RuleIssue = { code: string; message: string; path: string; details: Record<string, unknown> };
export type Validation = { ok: boolean; errors: RuleIssue[]; warnings: RuleIssue[]; node_count: number; depth: number; mutable_fields: string[]; unit_of_account: string };
export type RuleExample = { kind: string; label: string; payload: Record<string, unknown>; tick: number; fired: boolean; amount: number; ledger_states: string[]; ledger_reasons?: (string | null)[]; payout: number; error: RuleIssue | null };
export type DiffRow = { kind: string; title: string; before: unknown; after: unknown; important: boolean };

export type BatchBrief = { id: string; title: string; status: string; planned_runs: number; created_at: string; modes: string[] };

export type FindingBrief = { id: string; run_id: string; check_id: string; title: string; explanation: string; replay_status: string; status: string; created_at: string };

export type Project = {
  id: string;
  workspace_id: string;
  name: string;
  description: string;
  environment_id: string;
  tags: string[];
  restricted: boolean;
  is_demo: boolean;
  research_question: string;
  desired_outcome: string;
  archived_at: string | null;
  updated_at: string | null;
  created_at: string | null;
  role?: Role;
  scenarios?: Scenario[];
  rules?: Rule[];
  batches?: BatchBrief[];
  findings?: FindingBrief[];
  last_comparison?: { id: string; batch_id: string; created_at: string; summary: string[]; tradeoffs: string[] } | null;
  last_batch?: { id: string; status: string; created_at: string } | null;
};

export type Profile = {
  id: string;
  name: string;
  mode: "cooperative" | "incentive_seeking" | "adversarial_search";
  kind: "scripted" | "model";
  model: Record<string, unknown>;
  params: Record<string, unknown>;
  version: number;
};

export type Run = {
  id: string;
  batch_id: string;
  project_id: string;
  variant_label: string;
  seed: number;
  agent_mode: string;
  agent_kind: string;
  status: string;
  stop_reason: string | null;
  verdict: string | null;
  current_tick: number;
  horizon_ticks: number;
  tail_ticks: number;
  last_seq: number;
  allowed_commands: string[];
  chain_root: string | null;
  snapshot_hash: string;
  tape_hash: string;
  rule_version_id: string;
  started_at: string | null;
  finished_at: string | null;
};

export type CheckResult = { check_id: string; version: string; title: string; formula: string; status: "pass" | "fail" | "not_applicable" | "inconclusive"; reason: string; violations: unknown[] };
export type MetricSample = { value: string | number | null; unit: string; numerator: number | null; denominator: number | null; applicability: string; note: string };

export type RunDetail = Run & {
  project: { id: string; name: string; environment_id: string };
  rule: { id: string; name: string; version: number; ast_hash: string; source_text: string };
  batch: { id: string; title: string; status: string };
  audit: { status: string; complete: boolean; verdict: string; checks: CheckResult[]; metrics: Record<string, MetricSample>; stop_reason: string | null } | null;
  snapshot: { actor_ids: string[]; environment: string; seed: number; config: Record<string, unknown>; checks: string[] };
  findings: { id: string; check_id: string; title: string; replay_status: string }[];
  model_calls: number;
};

export type RunEvent = {
  schema_version: string;
  run_id: string;
  seq: number;
  event_class: "domain" | "operational";
  domain_seq: number | null;
  tick: number;
  type: string;
  actor_id: string | null;
  entity_id: string | null;
  created_at: string | null;
  payload: Record<string, unknown>;
  state_hash: string | null;
};

export type Batch = {
  id: string;
  project_id: string;
  title: string;
  status: string;
  plan: Record<string, unknown> & { variants: { label: string; rule_version_id: string; mode: string; kind: string }[]; seeds: number[]; environment: string };
  plan_hash: string;
  counts: { planned: number; started: number; completed: number; incomplete: number; in_progress: number };
  budget: Record<string, unknown>;
  budget_used: Record<string, number>;
  runs: Run[];
  comparison_id: string | null;
  created_at: string;
};

export type MetricComparison = {
  title: string;
  direction: "higher" | "lower" | "neutral";
  pairs: number;
  excluded_not_applicable: number;
  mean_diff: string | null;
  median_diff: string | null;
  range: [string, string] | null;
  pair_values: { seed: number; baseline: string; candidate: string; diff: string }[];
  bootstrap_ci: [string, string] | null;
  effect: "improved" | "worsened" | null;
};

export type ComparisonPair = {
  error?: string;
  message?: string;
  baseline: string;
  candidate: string;
  mode: string;
  counts: Record<string, { planned: number; completed: number; incomplete: number }>;
  pairs_complete: number;
  pairing: { tapes_match: boolean | null; changed_factors: string[]; seeds: number[] };
  metrics: Record<string, MetricComparison>;
  violations: Record<string, Record<string, { failed: number; applicable: number; incomplete: number; rate: string | null; wilson: [string, string] | null }>>;
  improved: string[];
  worsened: string[];
  tradeoffs: string[];
  summary: string[];
  interpretation: string;
  bootstrap_policy: string;
};

export type Comparison = {
  id: string;
  batch_id: string;
  project_id: string;
  result: { variants: string[]; pairs: ComparisonPair[]; primary: ComparisonPair | null; single_variant: boolean };
  completeness: Record<string, number>;
  excluded_runs: { run_id: string; reason: string }[];
  decision: { accepted_variant: string; note: string; at: string } | null;
  runs: Run[];
  plan: Batch["plan"];
};

export type FindingCard = {
  title: string;
  formula: string;
  threshold: string;
  check_id: string;
  check_version: string;
  rule_name: string;
  rule_condition: string;
  rule_hash: string;
  environment: string;
  environment_version: string;
  seed: number;
  explanation: string;
  scope: string;
  evidence_seqs: number[];
  check_failed_seq: number | null;
  violation_tick: number;
  affected_entities: string[];
  reward_microunits: number;
  events: RunEvent[];
  violation_count: number;
};

export type FixCandidate = { key: string; title: string; explanation: string; tradeoff: string; tree: RuleTree; validation: Validation; status: string };

export type Finding = {
  id: string;
  run_id: string;
  project_id: string;
  check_id: string;
  status: string;
  replay_status: string;
  replay_result: { status: string; ticks_compared: number; first_divergent_tick: number | null; property_reproduced: boolean | null; model_calls: number; checked_at?: string } | null;
  minimization: { status: string; label?: string; actions?: { tick: number; actor_id: string; action_type: string; arguments: Record<string, unknown> }[]; original_count?: number; executions?: number; verified?: boolean } | null;
  fix_candidates: FixCandidate[] | null;
  card: FindingCard;
  run: Run;
};

export type EnvironmentInfo = {
  name: string;
  version: string;
  template: { title: string; problem: string; description: string; desired_outcome: string; rules: string[]; default_checks: string[] };
  default_config: Record<string, unknown>;
  actions: { type: string; description: string; cost: string; events: string[] }[];
  triggers: Record<string, { description: string; confirmed_outcome: boolean; repeatable_per_root: boolean; fields: Record<string, { type: string; unit: string; enum: string[]; mutable_by_actor: boolean; description: string }> }>;
  checks: { check_id: string; title: string; formula: string; scope: string; threshold: string }[];
  comparison_metrics: { id: string; direction: string; title: string }[];
};

export type Report = { id: string; project_id: string; batch_id: string | null; format: string; status: string; error: string | null; created_at: string; download_url?: string; link_expires_in_seconds?: number };
