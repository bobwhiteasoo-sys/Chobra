/** Two-way mapping between rule trees and the structured constructor form. */
import type { EnvironmentInfo, RuleTree } from "./types";

export type Node = Record<string, unknown>;
export type Operator = "eq" | "ne" | "lt" | "le" | "gt" | "ge";
export type ConditionRow = { field: string; op: Operator; source: "literal" | "field"; value: string };
export type AmountForm =
  | { kind: "fixed"; points: string }
  | { kind: "rate"; field: string; ratePoints: string }
  | { kind: "weighted"; field: string; value: string; thenPoints: string; elsePoints: string; bonusField: string; bonusCap: string; bonusRatePoints: string }
  | { kind: "expr" };

export const OPERATORS: { value: Operator; label: string }[] = [
  { value: "eq", label: "равно" },
  { value: "ne", label: "не равно" },
  { value: "gt", label: "больше" },
  { value: "ge", label: "не меньше" },
  { value: "lt", label: "меньше" },
  { value: "le", label: "не больше" },
];

const POINT = 1_000_000;
type FieldSpec = EnvironmentInfo["triggers"][string]["fields"][string];

function isField(node: unknown): node is { field: string } {
  return typeof node === "object" && node !== null && typeof (node as Node).field === "string";
}

function isLiteral(node: unknown): node is { literal: unknown; type: string; unit?: string } {
  return typeof node === "object" && node !== null && "literal" in (node as Node);
}

export function parseCondition(node: unknown): ConditionRow[] | null {
  if (isLiteral(node) && node.literal === true) return [];
  const parts = typeof node === "object" && node !== null && (node as Node).op === "and" ? ((node as Node).args as unknown[]) : [node];
  const rows: ConditionRow[] = [];
  for (const part of parts) {
    const p = part as Node;
    if (!p || !OPERATORS.some((o) => o.value === p.op) || !isField(p.left)) return null;
    if (isLiteral(p.right)) rows.push({ field: p.left.field, op: p.op as Operator, source: "literal", value: String(p.right.literal) });
    else if (isField(p.right)) rows.push({ field: p.left.field, op: p.op as Operator, source: "field", value: p.right.field });
    else return null;
  }
  return rows;
}

export function literalFor(spec: FieldSpec | undefined, value: string): Node {
  if (!spec) return { literal: value, type: "enum" };
  if (spec.type === "boolean") return { literal: value === "true", type: "boolean" };
  if (spec.type === "enum") return { literal: value, type: "enum" };
  if (spec.type === "duration_ticks") return { literal: Number(value), type: "duration_ticks" };
  if (spec.type === "int") return spec.unit && spec.unit !== "none" ? { literal: Number(value), type: "int", unit: spec.unit } : { literal: Number(value), type: "int" };
  return { literal: value, type: spec.type };
}

export function buildCondition(rows: ConditionRow[], fields: Record<string, FieldSpec>): Node {
  const nodes = rows.map((r) => ({ op: r.op, left: { field: r.field }, right: r.source === "field" ? { field: r.value } : literalFor(fields[r.field], r.value) }));
  if (!nodes.length) return { literal: true, type: "boolean" };
  return nodes.length === 1 ? nodes[0]! : { op: "and", args: nodes };
}

function pts(node: unknown): string | null {
  return isLiteral(node) && typeof node.literal === "number" && (node.unit === "reward_microunits" || node.unit === undefined) ? String(node.literal / POINT) : null;
}

export function parseAmount(node: unknown): AmountForm {
  const n = node as Node;
  const fixed = pts(n);
  if (fixed !== null) return { kind: "fixed", points: fixed };
  if (n?.op === "mul") {
    const [a, b] = (n.args as unknown[]) ?? [];
    if (isField(a) && pts(b) !== null) return { kind: "rate", field: a.field, ratePoints: pts(b)! };
  }
  const weighted = (ifNode: Node, bonus: Node | null): AmountForm | null => {
    const cond = ifNode.cond as Node;
    if (cond?.op !== "eq" || !isField(cond.left) || !isLiteral(cond.right)) return null;
    const thenP = pts(ifNode.then);
    const elseP = pts(ifNode.else);
    if (thenP === null || elseP === null) return null;
    let bonusField = "";
    let bonusCap = "";
    let bonusRate = "0";
    if (bonus) {
      const [minNode, rate] = (bonus.args as unknown[]) ?? [];
      const m = minNode as Node;
      if (bonus.op !== "mul" || m?.op !== "min" || pts(rate) === null) return null;
      const [field, cap] = (m.args as unknown[]) ?? [];
      if (!isField(field) || !isLiteral(cap)) return null;
      bonusField = field.field;
      bonusCap = String(cap.literal);
      bonusRate = pts(rate)!;
    }
    return { kind: "weighted", field: cond.left.field, value: String(cond.right.literal), thenPoints: thenP, elsePoints: elseP, bonusField, bonusCap, bonusRatePoints: bonusRate };
  };
  if (n?.op === "if") return weighted(n, null) ?? { kind: "expr" };
  if (n?.op === "add") {
    const [first, second] = (n.args as unknown[]) ?? [];
    if ((first as Node)?.op === "if" && (n.args as unknown[]).length === 2) return weighted(first as Node, second as Node) ?? { kind: "expr" };
  }
  return { kind: "expr" };
}

function pointLiteral(value: string): Node {
  return { literal: Math.round(Number(value.replace(",", ".")) * POINT), type: "int", unit: "reward_microunits" };
}

export function buildAmount(form: AmountForm, fields: Record<string, FieldSpec>, previous: unknown): unknown {
  if (form.kind === "fixed") return pointLiteral(form.points);
  if (form.kind === "rate") return { op: "mul", args: [{ field: form.field }, pointLiteral(form.ratePoints)] };
  if (form.kind === "weighted") {
    const ifNode = { op: "if", cond: { op: "eq", left: { field: form.field }, right: literalFor(fields[form.field], form.value) }, then: pointLiteral(form.thenPoints), else: pointLiteral(form.elsePoints) };
    if (!form.bonusField || Number(form.bonusRatePoints) === 0) return ifNode;
    const capSpec = fields[form.bonusField];
    const cap = capSpec?.type === "duration_ticks" ? { literal: Number(form.bonusCap), type: "duration_ticks" } : literalFor(capSpec, form.bonusCap);
    return { op: "add", args: [ifNode, { op: "mul", args: [{ op: "min", args: [{ field: form.bonusField }, cap] }, pointLiteral(form.bonusRatePoints)] }] };
  }
  return previous;
}

export function fieldsOf(env: EnvironmentInfo | undefined, trigger: string): Record<string, FieldSpec> {
  return env?.triggers[trigger]?.fields ?? {};
}

export function blankRule(environment: string, trigger: string, fields: Record<string, FieldSpec>): RuleTree {
  const recipient = Object.keys(fields).find((f) => fields[f]!.unit === "actor") ?? "event.actor_id";
  return {
    schema_version: "1.0",
    environment,
    trigger,
    condition: { literal: true, type: "boolean" },
    amount: pointLiteral("10"),
    unit: "reward_microunits",
    recipient: { field: recipient },
    deduplication: { mode: "per_event", key_fields: [] },
    settlement: { mode: "immediate_after_trigger" },
  };
}

export const DEDUP_LABELS: Record<string, string> = {
  per_event: "Каждое событие отдельно",
  once_per_entity: "Один раз на объект",
  once_per_root: "Один раз на исходный объект",
  once_per_actor_per_tick: "Один раз участнику за тик",
};
