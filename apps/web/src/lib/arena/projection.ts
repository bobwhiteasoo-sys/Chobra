/**
 * Local projection of a run built only from confirmed server events (spec section 23).
 * `applyEvent` is pure and is used by both Live and Replay. The scene never computes
 * rewards or business results: it shows what the events say.
 */
import type { RunEvent } from "@/lib/types";

export type AgentStatus = "ready" | "choosing" | "submitted" | "proposed" | "rejected" | "acted" | "error" | "idle";

export type AgentView = {
  id: string;
  mode: string;
  kind: string;
  status: AgentStatus;
  since: string | null;
  lastAction: string | null;
  lastRejection: string | null;
  reward: number;
  pending: number;
  degraded: boolean;
};

export type ItemView = {
  id: string;
  root: string;
  parent: string | null;
  status: string;
  solved: boolean;
  assignee: string | null;
  complexity: string;
  trueComplexity: string | null;
  required: number | null;
  completed: number;
  closes: number;
  reopened: number;
  confirmation: string | null;
  deadline: number | null;
  overdue: boolean;
  importance?: string;
  dependsOn?: string[];
  defects?: number;
  declaredDone?: boolean;
  lastSeq: number;
};

export type Marker = { id: number; kind: "action" | "reward" | "outcome" | "rejected"; from: string; to: string; label: string; tick: number };

export type Violation = { seq: number; tick: number; checkId: string; title: string; message: string; evidence: number[]; entities: string[] };

export type Projection = {
  lastSeq: number;
  lastDomainSeq: number;
  tick: number;
  phase: string;
  environment: string;
  status: "initializing" | "running" | "paused" | "finished";
  finalStatus: string | null;
  verdict: string | null;
  agents: Record<string, AgentView>;
  agentOrder: string[];
  items: Record<string, ItemView>;
  itemOrder: string[];
  commons: { stock: number; capacity: number; minStock: number; history: { tick: number; stock: number }[]; depletedTick: number | null } | null;
  registers: { reward: number; pending: number; outcome: number; outcomeDenominator: number | null; outcomeLabel: string; formal: number; formalLabel: string };
  markers: Marker[];
  violations: Violation[];
  scene: Record<string, unknown>;
  ruleTrigger: string | null;
};

export const MAX_MARKERS = 20;

export function emptyProjection(): Projection {
  return {
    lastSeq: 0,
    lastDomainSeq: 0,
    tick: 0,
    phase: "main",
    environment: "",
    status: "initializing",
    finalStatus: null,
    verdict: null,
    agents: {},
    agentOrder: [],
    items: {},
    itemOrder: [],
    commons: null,
    registers: { reward: 0, pending: 0, outcome: 0, outcomeDenominator: null, outcomeLabel: "", formal: 0, formalLabel: "" },
    markers: [],
    violations: [],
    scene: {},
    ruleTrigger: null,
  };
}

function str(value: unknown): string {
  return typeof value === "string" ? value : value === null || value === undefined ? "" : String(value);
}

function num(value: unknown, fallback = 0): number {
  return typeof value === "number" ? value : fallback;
}

function withMarker(state: Projection, marker: Marker): Marker[] {
  const next = [...state.markers, marker];
  return next.length > MAX_MARKERS ? next.slice(next.length - MAX_MARKERS) : next;
}

function updateItem(state: Projection, id: string, patch: Partial<ItemView>, seq: number): Projection {
  const current = state.items[id];
  if (!current) return state;
  return { ...state, items: { ...state.items, [id]: { ...current, ...patch, lastSeq: seq } } };
}

function newItem(id: string, root: string, seq: number, patch: Partial<ItemView>): ItemView {
  return {
    id, root, parent: null, status: "open", solved: false, assignee: null, complexity: "", trueComplexity: null, required: null, completed: 0, closes: 0,
    reopened: 0, confirmation: null, deadline: null, overdue: false, lastSeq: seq, ...patch,
  };
}

function setAgent(state: Projection, id: string | null, patch: Partial<AgentView>): Projection {
  if (!id || !state.agents[id]) return state;
  return { ...state, agents: { ...state.agents, [id]: { ...state.agents[id]!, ...patch } } };
}

/** Returns the same object when the event was already applied (duplicates never double anything). */
export function applyEvent(state: Projection, event: RunEvent): Projection {
  if (event.seq <= state.lastSeq) return state;
  let s: Projection = { ...state, lastSeq: event.seq, lastDomainSeq: event.domain_seq ?? state.lastDomainSeq, tick: Math.max(state.tick, event.tick) };
  const p = event.payload;
  switch (event.type) {
    case "run.initialized": {
      const agents: Record<string, AgentView> = {};
      const order: string[] = [];
      for (const raw of (p.agents as { actor_id: string; mode: string; kind: string }[]) ?? []) {
        agents[raw.actor_id] = { id: raw.actor_id, mode: raw.mode, kind: raw.kind, status: "ready", since: null, lastAction: null, lastRejection: null, reward: 0, pending: 0, degraded: false };
        order.push(raw.actor_id);
      }
      const scene = (p.scene as Record<string, unknown>) ?? {};
      s = { ...s, environment: str(p.environment), agents, agentOrder: order, scene, status: "running", ruleTrigger: str(p.rule_trigger) || null };
      if (s.environment === "resourcecommons") {
        const stock = num(scene.initial_stock);
        s.commons = { stock, capacity: num(scene.capacity, 100), minStock: num(scene.min_stock), history: [{ tick: 0, stock }], depletedTick: null };
      }
      return s;
    }
    case "model_call.started":
      return setAgent(s, event.actor_id, { status: "choosing", since: event.created_at });
    case "model_call.completed":
      return setAgent(s, event.actor_id, { status: "submitted", since: null });
    case "model_call.failed":
      return setAgent(s, event.actor_id, { status: "error", since: null });
    case "action.proposed":
      return setAgent(s, event.actor_id, { status: "proposed", lastAction: str(p.action_type), degraded: Boolean(p.degraded) });
    case "action.rejected": {
      s = setAgent(s, event.actor_id, { status: "rejected", lastRejection: `${str(p.action_type)}: ${str(p.message)}` });
      if (event.actor_id && event.entity_id && s.items[event.entity_id]) {
        s = { ...s, markers: withMarker(s, { id: event.seq, kind: "rejected", from: event.actor_id, to: event.entity_id, label: str(p.code), tick: event.tick }) };
      }
      return s;
    }
    case "action.committed": {
      s = setAgent(s, event.actor_id, { status: "acted", lastAction: str(p.action_type), lastRejection: null });
      if (event.actor_id && event.entity_id && p.action_type !== "wait") {
        s = { ...s, markers: withMarker(s, { id: event.seq, kind: "action", from: event.actor_id, to: event.entity_id, label: str(p.action_type), tick: event.tick }) };
      }
      return s;
    }
    case "issue.arrived":
    case "task.arrived": {
      const id = str(p.issue_id || p.task_id);
      const item = newItem(id, str(p.root_issue_id || p.root_task_id), event.seq, {
        assignee: (p.assignee_id as string) ?? null,
        complexity: str(p.reported_complexity),
        trueComplexity: (p.true_complexity as string) ?? null,
        required: typeof p.required_effort_units === "number" ? p.required_effort_units : null,
        deadline: typeof p.deadline_tick === "number" ? p.deadline_tick : null,
        status: event.type === "task.arrived" ? (p.assignee_id ? "in_progress" : "todo") : "open",
        importance: (p.importance as string) ?? undefined,
        dependsOn: (p.depends_on as string[]) ?? undefined,
        defects: 0,
        declaredDone: false,
      });
      return { ...s, items: { ...s.items, [id]: item }, itemOrder: [...s.itemOrder, id] };
    }
    case "issue.claimed":
    case "task.taken":
      return updateItem(s, str(p.issue_id || p.task_id), { assignee: str(p.actor_id), status: event.type === "task.taken" ? "in_progress" : "open" }, event.seq);
    case "issue.work_done":
    case "task.work_done":
      return updateItem(s, str(p.issue_id || p.task_id), { completed: num(p.completed_effort_units) }, event.seq);
    case "issue.problem_solved": {
      const id = str(p.issue_id);
      s = updateItem(s, id, { solved: true }, event.seq);
      if (p.root_problem_solved && s.items[str(p.root_issue_id)]) s = updateItem(s, str(p.root_issue_id), { solved: true }, event.seq);
      return { ...s, markers: withMarker(s, { id: event.seq, kind: "outcome", from: id, to: "outcome", label: "решено", tick: event.tick }) };
    }
    case "issue.closed": {
      const item = s.items[str(p.issue_id)];
      return updateItem(s, str(p.issue_id), { status: "closed", closes: (item?.closes ?? 0) + 1, confirmation: "pending" }, event.seq);
    }
    case "issue.confirmation_completed":
      return updateItem(s, str(p.issue_id), { confirmation: str(p.confirmation_status) }, event.seq);
    case "issue.reopened": {
      const item = s.items[str(p.issue_id)];
      return updateItem(s, str(p.issue_id), { status: "open", assignee: p.reason === "participant" ? item?.assignee ?? null : null, reopened: (item?.reopened ?? 0) + 1 }, event.seq);
    }
    case "issue.split":
    case "task.split": {
      const parentId = str(p.issue_id || p.task_id);
      const parent = s.items[parentId];
      const children = (p.child_ids as string[]) ?? [];
      const items = { ...s.items };
      const order = [...s.itemOrder];
      for (const child of children) {
        items[child] = newItem(child, parent?.root ?? parentId, event.seq, {
          parent: parentId, assignee: str(p.actor_id), complexity: parent?.complexity ?? "", trueComplexity: parent?.trueComplexity ?? null,
          deadline: parent?.deadline ?? null, status: event.type === "task.split" ? "in_progress" : "open", importance: parent?.importance, dependsOn: parent?.dependsOn,
        });
        order.push(child);
      }
      if (parent) items[parentId] = { ...parent, status: "split", lastSeq: event.seq };
      return { ...s, items, itemOrder: order };
    }
    case "issue.complexity_reported":
      return updateItem(s, str(p.issue_id), { complexity: str(p.complexity) }, event.seq);
    case "issue.escalated":
      return updateItem(s, str(p.issue_id), { status: "escalated", assignee: null }, event.seq);
    case "issue.escalation_returned":
      return updateItem(s, str(p.issue_id), { status: "open", completed: num(p.completed_effort_units) }, event.seq);
    case "issue.overdue":
    case "task.overdue":
      return updateItem(s, str(p.issue_id || p.task_id), { overdue: true }, event.seq);
    case "task.declared_done":
      return updateItem(s, str(p.task_id), { declaredDone: true }, event.seq);
    case "task.defect_introduced": {
      const item = s.items[str(p.task_id)];
      return updateItem(s, str(p.task_id), { defects: (item?.defects ?? 0) + 1 }, event.seq);
    }
    case "task.fixed": {
      const item = s.items[str(p.task_id)];
      return updateItem(s, str(p.task_id), { defects: Math.max(0, (item?.defects ?? 0) - 1) }, event.seq);
    }
    case "task.accepted": {
      const id = str(p.task_id);
      s = updateItem(s, id, { status: "accepted", solved: true }, event.seq);
      if (p.root_accepted && s.items[str(p.root_task_id)]) s = updateItem(s, str(p.root_task_id), { solved: true, status: "accepted" }, event.seq);
      return { ...s, markers: withMarker(s, { id: event.seq, kind: "outcome", from: id, to: "outcome", label: "принято", tick: event.tick }) };
    }
    case "task.rejected":
      return updateItem(s, str(p.task_id), { status: "in_progress" }, event.seq);
    case "task.handed_off":
      return updateItem(s, str(p.task_id), { assignee: str(p.to_actor_id) }, event.seq);
    case "resource.allocated": {
      if (!s.commons) return s;
      const actor = str(p.actor_id);
      s = { ...s, commons: { ...s.commons, stock: num(p.stock_after) } };
      return { ...s, markers: withMarker(s, { id: event.seq, kind: "action", from: actor, to: "commons", label: `−${num(p.allocated)}`, tick: event.tick }) };
    }
    case "resource.regenerated":
      if (!s.commons) return s;
      return { ...s, commons: { ...s.commons, stock: num(p.stock_after), history: [...s.commons.history, { tick: event.tick, stock: num(p.stock_after) }].slice(-300) } };
    case "resource.depleted":
      return s.commons ? { ...s, commons: { ...s.commons, depletedTick: event.tick } } : s;
    case "reward.pending": {
      const amount = num(p.reward_microunits);
      s = setAgent(s, str(p.actor_id), { pending: (s.agents[str(p.actor_id)]?.pending ?? 0) + amount });
      return { ...s, registers: { ...s.registers, pending: s.registers.pending + amount } };
    }
    case "reward.settled":
    case "reward.reversed": {
      const amount = num(p.reward_microunits);
      const actor = str(p.actor_id);
      const fromHold = Boolean(p.related_entry_id) && event.type === "reward.settled";
      s = setAgent(s, actor, { reward: (s.agents[actor]?.reward ?? 0) + amount, pending: fromHold ? Math.max(0, (s.agents[actor]?.pending ?? 0) - amount) : s.agents[actor]?.pending ?? 0 });
      s = { ...s, registers: { ...s.registers, reward: s.registers.reward + amount, pending: fromHold ? Math.max(0, s.registers.pending - amount) : s.registers.pending } };
      if (amount !== 0) {
        s = { ...s, markers: withMarker(s, { id: event.seq, kind: "reward", from: actor, to: "reward", label: amount > 0 ? `+${amount / 1_000_000}` : `${amount / 1_000_000}`, tick: event.tick }) };
      }
      return s;
    }
    case "check.failed": {
      const violation: Violation = {
        seq: event.seq, tick: event.tick, checkId: str(p.check_id), title: str(p.title), message: str(p.message),
        evidence: (p.evidence_seqs as number[]) ?? [], entities: (p.entity_ids as string[]) ?? [],
      };
      return { ...s, violations: [...s.violations, violation] };
    }
    case "tick.completed": {
      const r = (p.registers as Record<string, unknown>) ?? {};
      const agents: Record<string, AgentView> = {};
      for (const [id, agent] of Object.entries(s.agents)) agents[id] = { ...agent, status: agent.status === "choosing" ? "choosing" : "ready", since: agent.status === "choosing" ? agent.since : null };
      return {
        ...s,
        phase: str(p.phase) || s.phase,
        agents,
        registers: {
          ...s.registers,
          reward: typeof r.reward_microunits === "number" ? r.reward_microunits : s.registers.reward,
          outcome: num(r.outcome_value, s.registers.outcome),
          outcomeDenominator: typeof r.outcome_denominator === "number" ? r.outcome_denominator : null,
          outcomeLabel: str(r.outcome_label) || s.registers.outcomeLabel,
          formal: num(r.formal_value, s.registers.formal),
          formalLabel: str(r.formal_label) || s.registers.formalLabel,
        },
      };
    }
    case "run.paused":
      return { ...s, status: "paused" };
    case "run.completed":
    case "run.canceled":
    case "run.failed":
    case "run.budget_exhausted":
      return { ...s, status: "finished", finalStatus: event.type.slice(4), verdict: str(p.verdict) || null };
    default:
      return s;
  }
}

export function project(events: RunEvent[], upToSeq = Number.POSITIVE_INFINITY): Projection {
  let state = emptyProjection();
  for (const event of events) {
    if (event.seq > upToSeq) break;
    state = applyEvent(state, event);
  }
  return state;
}
