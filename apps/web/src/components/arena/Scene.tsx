"use client";

import { Loader2, OctagonAlert } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

import { actionLabel, actorName, AGENT_STATUS } from "@/lib/arena/labels";
import { MAX_MARKERS, type AgentView, type Marker, type Projection, type Violation } from "@/lib/arena/projection";
import { MODE_LABELS, plural, points } from "@/lib/format";

import { World } from "./World";

export type Selection =
  | { kind: "agent"; id: string }
  | { kind: "item"; id: string }
  | { kind: "event"; seq: number }
  | { kind: "violation"; seq: number }
  | { kind: "register"; id: "reward" | "outcome" }
  | { kind: "rule" };

export type Chain = { violationSeq: number; seqs: Set<number>; entities: Set<string>; actors: Set<string>; reward: boolean; outcome: boolean };

type Props = {
  projection: Projection;
  ruleName: string;
  ruleCondition: string;
  selection: Selection | null;
  onSelect: (selection: Selection) => void;
  chain: Chain | null;
  onShowChain: (violation: Violation) => void;
  onClearChain: () => void;
  animate: boolean;
  waitingClock: number | null;
  findingHref: (checkId: string) => string | null;
  stacked: boolean;
};

type Link2 = { id: string; d: string };
type Flight = { id: number; kind: Marker["kind"]; d: string; label: string; target: string | null };

function sPath(x1: number, y1: number, x2: number, y2: number): string {
  const dx = Math.max(24, (x2 - x1) * 0.5);
  return `M${x1.toFixed(1)} ${y1.toFixed(1)} C${(x1 + dx).toFixed(1)} ${y1.toFixed(1)} ${(x2 - dx).toFixed(1)} ${y2.toFixed(1)} ${x2.toFixed(1)} ${y2.toFixed(1)}`;
}

function clamp(v: number, lo: number, hi: number) {
  return Math.min(hi, Math.max(lo, v));
}

const SHAPE: Record<string, string> = { cooperative: "shape-circle", incentive_seeking: "shape-diamond", adversarial_search: "shape-triangle" };

function pointsText(micro: number): string {
  const value = micro / 1_000_000;
  const word = Number.isInteger(value) ? plural(Math.abs(value), "очко", "очка", "очков") : "очка";
  return `${value > 0 ? "+" : ""}${points(micro)} ${word}`;
}

function AgentNode({ agent, index, selected, dimmed, chained, waitingClock, onSelect }: { agent: AgentView; index: number; selected: boolean; dimmed: boolean; chained: boolean; waitingClock: number | null; onSelect: () => void }) {
  const waited = agent.status === "choosing" && agent.since && waitingClock ? Math.max(0, Math.round((waitingClock - Date.parse(agent.since)) / 1000)) : null;
  return (
    <button
      type="button"
      className={`agent-node${selected ? " is-selected" : ""}${dimmed ? " is-dimmed" : ""}${chained ? " is-chain" : ""} status-${agent.status}`}
      data-anchor={`agent:${agent.id}`}
      aria-pressed={selected}
      onClick={onSelect}
    >
      <span className="agent-top">
        <span className={`agent-shape ${SHAPE[agent.mode] ?? "shape-circle"}`} aria-hidden />
        <span className="agent-name">Участник {index + 1}</span>
        {agent.kind === "model" ? <span className="item-tag">модель</span> : null}
      </span>
      <span className="agent-status">
        {agent.status === "choosing" && waitingClock !== null ? <Loader2 size={13} className="spin" aria-hidden /> : null}
        {AGENT_STATUS[agent.status]}
        {waited !== null ? `, ${waited} с` : ""}
      </span>
      <span className="agent-sub">
        {agent.status === "rejected" && agent.lastRejection ? agent.lastRejection : agent.lastAction ? `Последнее: ${actionLabel(agent.lastAction)}` : MODE_LABELS[agent.mode] ?? agent.mode}
      </span>
      <span className="agent-reward">
        {points(agent.reward)} очк.{agent.pending ? `, ждет ${points(agent.pending)}` : ""}
        {agent.degraded ? ", упрощенное решение" : ""}
      </span>
    </button>
  );
}

function FlightPath({ flight, onDone }: { flight: Flight; onDone: (flight: Flight) => void }) {
  const pathRef = useRef<SVGPathElement>(null);
  const dotRef = useRef<SVGGElement>(null);
  useLayoutEffect(() => {
    const path = pathRef.current;
    const dot = dotRef.current;
    if (!path || !dot) return;
    const total = path.getTotalLength();
    const stop = flight.kind === "rejected" ? 0.5 : 1;
    const frames: Keyframe[] = [];
    for (let i = 0; i <= 16; i++) {
      const p = path.getPointAtLength((total * stop * i) / 16);
      frames.push({ transform: `translate(${p.x}px, ${p.y}px)`, opacity: flight.kind === "rejected" && i === 16 ? 0 : 1 });
    }
    const motion = dot.animate(frames, { duration: 260, easing: "linear", fill: "forwards" });
    const trail = path.animate([{ opacity: 0.9 }, { opacity: 0.9, offset: 0.6 }, { opacity: 0 }], { duration: 640, easing: "cubic-bezier(0.23, 1, 0.32, 1)", fill: "forwards" });
    motion.onfinish = () => onDone(flight);
    return () => {
      motion.cancel();
      trail.cancel();
    };
  }, [flight, onDone]);
  return (
    <g className={`flight flight-${flight.kind}`}>
      <path ref={pathRef} d={flight.d} className="flight-trail" />
      <g ref={dotRef} style={{ transform: "translate(-100px, -100px)" }}>
        <circle r={5} className="flight-dot" />
        {flight.label && flight.kind !== "action" ? (
          <text y={-10} textAnchor="middle" className="flight-label">
            {flight.label}
          </text>
        ) : null}
      </g>
    </g>
  );
}

export function Scene(props: Props) {
  const { projection, selection, onSelect, chain, animate, stacked } = props;
  const container = useRef<HTMLDivElement>(null);
  const [links, setLinks] = useState<Link2[]>([]);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [flights, setFlights] = useState<Flight[]>([]);
  const [flashing, setFlashing] = useState<Set<string>>(new Set());
  const [merged, setMerged] = useState<number | null>(null);
  const seen = useRef<{ marker: number; seq: number }>({ marker: 0, seq: 0 });

  const anchor = useCallback((key: string) => {
    const root = container.current;
    if (!root) return null;
    const el = root.querySelector<HTMLElement>(`[data-anchor="${CSS.escape(key)}"]`);
    if (!el) return null;
    const base = root.getBoundingClientRect();
    const r = el.getBoundingClientRect();
    return { left: r.left - base.left, top: r.top - base.top, right: r.right - base.left, bottom: r.bottom - base.top, cx: r.left - base.left + r.width / 2, cy: r.top - base.top + r.height / 2 };
  }, []);

  const agentKey = projection.agentOrder.join(",");
  const layout = useCallback(() => {
    const root = container.current;
    if (!root || stacked) return;
    setSize({ w: root.clientWidth, h: root.clientHeight });
    const world = anchor("world");
    if (!world) return;
    const next: Link2[] = [];
    const rule = anchor("rule");
    if (rule) next.push({ id: "rule", d: `M${rule.right} ${rule.cy} C${world.cx} ${rule.cy} ${world.cx} ${rule.cy} ${world.cx} ${world.top}` });
    for (const id of projection.agentOrder) {
      const a = anchor(`agent:${id}`);
      if (a) next.push({ id: `agent:${id}`, d: sPath(a.right, a.cy, world.left, clamp(a.cy, world.top + 20, world.bottom - 20)) });
    }
    for (const id of ["reward", "outcome"] as const) {
      const r = anchor(id);
      if (r) next.push({ id, d: sPath(world.right, clamp(r.cy, world.top + 20, world.bottom - 20), r.left, r.cy) });
    }
    setLinks(next);
  }, [anchor, stacked, projection.agentOrder]);

  useLayoutEffect(() => {
    layout();
    const root = container.current;
    if (!root || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => layout());
    observer.observe(root);
    const world = root.querySelector('[data-anchor="world"]');
    if (world) observer.observe(world);
    return () => observer.disconnect();
    // Re-measure when the set of nodes changes, not on every tick.
  }, [layout, agentKey, projection.environment, stacked]);

  // Turn newly arrived markers into short flights; a large batch is shown at once with a count.
  useEffect(() => {
    const prev = seen.current;
    const fresh = projection.markers.filter((m) => m.id > prev.marker);
    const delta = projection.lastSeq - prev.seq;
    seen.current = { marker: projection.markers.at(-1)?.id ?? prev.marker, seq: projection.lastSeq };
    if (projection.lastSeq < prev.seq) {
      setFlights([]);
      return;
    }
    // The first projection (page load, opened history) is shown as a state, not replayed as motion.
    if (prev.seq === 0 || !fresh.length) return;
    const flash = fresh.filter((m) => m.kind === "action" || m.kind === "rejected").map((m) => m.to);
    if (!animate || stacked || delta > MAX_MARKERS * 3) {
      if (delta > MAX_MARKERS) setMerged(delta);
      if (flash.length) setFlashing(new Set(flash));
      return;
    }
    const linkFor = (id: string) => links.find((l) => l.id === id)?.d ?? null;
    const made: Flight[] = [];
    for (const m of fresh.slice(-MAX_MARKERS)) {
      let d: string | null = null;
      if (m.kind === "reward") d = linkFor("reward");
      else if (m.kind === "outcome") d = linkFor("outcome");
      else {
        const from = anchor(`agent:${m.from}`);
        const to = m.kind === "action" ? anchor(`item:${m.to}`) : null;
        d = from && to && to.top >= 0 ? sPath(from.right, from.cy, to.left, to.cy) : linkFor(`agent:${m.from}`);
      }
      if (d) made.push({ id: m.id, kind: m.kind, d, label: m.label, target: m.kind === "action" || m.kind === "rejected" ? m.to : null });
    }
    setFlights((current) => [...current, ...made].slice(-MAX_MARKERS));
  }, [projection.markers, projection.lastSeq, animate, stacked, links, anchor]);

  useEffect(() => {
    if (merged === null) return;
    const id = window.setTimeout(() => setMerged(null), 1800);
    return () => window.clearTimeout(id);
  }, [merged]);

  useEffect(() => {
    if (!flashing.size) return;
    const id = window.setTimeout(() => setFlashing(new Set()), 700);
    return () => window.clearTimeout(id);
  }, [flashing]);

  const landed = useCallback((flight: Flight) => {
    setFlights((current) => current.filter((f) => f.id !== flight.id));
    if (flight.target) setFlashing(new Set([flight.target]));
  }, []);

  const r = projection.registers;
  const violation = chain ? projection.violations.find((v) => v.seq === chain.violationSeq) ?? null : null;
  const firstViolation = projection.violations[0] ?? null;
  const shownViolation = violation ?? projection.violations.at(-1) ?? null;
  const dim = Boolean(chain);
  const lastReward = [...projection.markers].reverse().find((m) => m.kind === "reward");
  const lastOutcome = [...projection.markers].reverse().find((m) => m.kind === "outcome");
  const findingHref = shownViolation ? props.findingHref(shownViolation.checkId) : null;
  const sel = (kind: Selection["kind"], id?: string | number) =>
    selection?.kind === kind && (id === undefined || ("id" in selection && selection.id === id) || ("seq" in selection && selection.seq === id));

  return (
    <div ref={container} className={`arena${stacked ? " arena-stacked" : ""}${dim ? " has-chain" : ""}`}>
      {!stacked ? (
        <svg className="arena-links" width={size.w} height={size.h} aria-hidden>
          {links.map((l) => {
            const active =
              chain &&
              ((l.id === "rule") || (l.id === "reward" && chain.reward) || (l.id === "outcome" && chain.outcome) || (l.id.startsWith("agent:") && chain.actors.has(l.id.slice(6))));
            return <path key={l.id} d={l.d} className={`arena-link${active ? " is-chain" : ""}${l.id === "outcome" ? " is-outcome" : ""}`} />;
          })}
          {flights.map((f) => (
            <FlightPath key={f.id} flight={f} onDone={landed} />
          ))}
        </svg>
      ) : null}

      <div className="arena-left">
        <button type="button" className={`rule-node${sel("rule") ? " is-selected" : ""}${chain ? " is-chain" : ""}`} data-anchor="rule" aria-pressed={sel("rule")} onClick={() => onSelect({ kind: "rule" })}>
          <span className="t-caption">Правило</span>
          <span className="rule-name">{props.ruleName}</span>
          {props.ruleCondition ? <span className="rule-cond">{props.ruleCondition}</span> : null}
        </button>
        <div className="agent-list" role="list" aria-label="Участники">
          {projection.agentOrder.map((id, index) => (
            <div role="listitem" key={id}>
              <AgentNode
                agent={projection.agents[id]!}
                index={index}
                selected={sel("agent", id)}
                dimmed={dim && !chain!.actors.has(id)}
                chained={Boolean(chain?.actors.has(id))}
                waitingClock={props.waitingClock}
                onSelect={() => onSelect({ kind: "agent", id })}
              />
            </div>
          ))}
          {!projection.agentOrder.length ? <p className="t-secondary">Участники появятся после подготовки мира</p> : null}
        </div>
      </div>

      <section className="arena-world" data-anchor="world" aria-label="Среда">
        <div className="world-head">
          <span className="world-title">Среда {projection.environment === "supportdesk" ? "SupportDesk" : projection.environment === "taskboard" ? "TaskBoard" : projection.environment === "resourcecommons" ? "ResourceCommons" : ""}</span>
          <span className="t-caption num">
            тик {projection.tick}
            {projection.phase === "tail" ? ", период наблюдения" : ""}
          </span>
        </div>
        <World
          projection={projection}
          selectedItem={selection?.kind === "item" ? selection.id : null}
          highlighted={chain ? chain.entities : null}
          flashing={flashing}
          onSelect={(id) => onSelect({ kind: "item", id })}
        />
        {merged !== null ? (
          <span className="merged-chip" role="status">
            Показано сразу: {merged} {plural(merged, "событие", "события", "событий")}
          </span>
        ) : null}
      </section>

      <div className="arena-right">
        <button type="button" className={`register register-reward${sel("register", "reward") ? " is-selected" : ""}${chain?.reward ? " is-chain" : ""}${dim && !chain?.reward ? " is-dimmed" : ""}`} data-anchor="reward" aria-pressed={sel("register", "reward")} onClick={() => onSelect({ kind: "register", id: "reward" })}>
          <span className="register-label">Начисленная награда</span>
          <span className="register-value">{pointsText(r.reward)}</span>
          {r.pending ? <span className="register-sub">ожидает подтверждения: {points(r.pending)} очк.</span> : null}
          {r.formalLabel ? (
            <span className="register-sub">
              {r.formalLabel}: {r.formal}
            </span>
          ) : null}
          {lastReward ? <span className="register-src">последнее начисление: тик {lastReward.tick}</span> : null}
        </button>
        <button type="button" className={`register register-outcome${sel("register", "outcome") ? " is-selected" : ""}${chain?.outcome ? " is-chain" : ""}${dim && !chain?.outcome ? " is-dimmed" : ""}`} data-anchor="outcome" aria-pressed={sel("register", "outcome")} onClick={() => onSelect({ kind: "register", id: "outcome" })}>
          <span className="register-label">Фактический результат</span>
          <span className="register-value">
            {r.outcome.toLocaleString("ru-RU")} {r.outcomeLabel}
          </span>
          {r.outcomeDenominator !== null ? <span className="register-sub">из {r.outcomeDenominator} исходных</span> : null}
          {lastOutcome ? <span className="register-src">последнее изменение: тик {lastOutcome.tick}</span> : null}
        </button>
      </div>

      {shownViolation ? (
        <section className={`violation-callout${violation ? " is-open" : ""}`} aria-label="Нарушение">
          <div className="violation-head">
            <span className="violation-tag">
              <OctagonAlert size={14} aria-hidden /> Нарушение
            </span>
            <span className="t-caption num">
              тик {shownViolation.tick}, событие #{shownViolation.seq}
            </span>
          </div>
          <strong className="violation-title">{shownViolation.title}</strong>
          <p className="violation-text">{shownViolation.message}</p>
          <div className="row" style={{ gap: 8 }}>
            {violation ? (
              <button type="button" className="btn btn-secondary btn-compact" onClick={props.onClearChain}>
                Снять подсветку
              </button>
            ) : (
              <button type="button" className="btn btn-secondary btn-compact" onClick={() => props.onShowChain(shownViolation)}>
                Показать цепочку
              </button>
            )}
            <button type="button" className="btn btn-ghost btn-compact" onClick={() => onSelect({ kind: "violation", seq: shownViolation.seq })}>
              Доказательства
            </button>
            {findingHref ? (
              <Link className="btn btn-ghost btn-compact" href={findingHref}>
                Карточка нарушения
              </Link>
            ) : null}
          </div>
          {projection.violations.length > 1 ? (
            <span className="t-caption">
              Всего {projection.violations.length} {plural(projection.violations.length, "нарушение", "нарушения", "нарушений")}, первое на тике {firstViolation!.tick}
            </span>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}
