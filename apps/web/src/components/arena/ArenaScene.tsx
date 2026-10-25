"use client";

import { useEffect, useRef, useState } from "react";
import { AGENT_STATUS, EVENT_LABELS, actionLabel, actorName, itemNumber } from "@/lib/arena/labels";
import { ENV_LABELS, MODE_LABELS } from "@/lib/format";
import type { Projection } from "@/lib/arena/projection";
import "@/styles/arena.css";

export type ArenaSelection = { kind: "agent" | "entity" | "register"; id: string } | { kind: "event" | "violation"; seq: number } | { kind: "rule" };
export type ArenaSceneProps = {
  projection: Projection; ruleName?: string; selection?: ArenaSelection | null;
  onSelect?: (selection: ArenaSelection) => void; frozen?: boolean; reducedMotion?: boolean;
  evidence?: number[]; evidenceNodes?: string[]; compact?: boolean;
};
type Point = { x: number; y: number };
const ITEM_STATUS: Record<string, string> = { open: "Открыто", closed: "Закрыто", split: "Разделено", escalated: "Передано", todo: "К выполнению", in_progress: "В работе", accepted: "Принято" };
const CONFIRMATION: Record<string, string> = { pending: "ожидается", confirmed: "получено", rejected: "отклонено", unobserved: "не наблюдалось" };
const COMPLEXITY: Record<string, string> = { easy: "простая", medium: "средняя", hard: "сложная" };
function curve(from: Point, to: Point) {
  const bend = Math.max(35, Math.abs(to.y - from.y) * .55);
  return `M${from.x},${from.y} C${from.x + bend},${from.y + bend} ${to.x - bend},${to.y - bend} ${to.x},${to.y}`;
}

export function ArenaScene({ projection: s, ruleName, selection, onSelect, frozen = true, reducedMotion = false, evidence = [], evidenceNodes = [], compact = false }: ArenaSceneProps) {
  const [page, setPage] = useState(0);
  const [agentPage, setAgentPage] = useState(0);
  const [now, setNow] = useState(0);
  const [geometry, setGeometry] = useState<{ width: number; height: number; nodes: Record<string, Point> }>({ width: 1, height: 1, nodes: {} });
  const scene = useRef<HTMLElement>(null);
  useEffect(() => { if (frozen) return; setNow(Date.now()); const timer = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(timer); }, [frozen]);
  const agentPages = Math.max(1, Math.ceil(s.agentOrder.length / 20));
  const agents = s.agentOrder.slice(Math.min(agentPage, agentPages - 1) * 20, (Math.min(agentPage, agentPages - 1) + 1) * 20);
  const capacity = Math.max(1, 76 - agents.length);
  const pages = Math.max(1, Math.ceil(s.itemOrder.length / capacity));
  const items = s.itemOrder.slice(Math.min(page, pages - 1) * capacity, (Math.min(page, pages - 1) + 1) * capacity);
  const nodeKey = [...agents, ...items].join("|");
  useEffect(() => {
    const element = scene.current;
    if (!element) return;
    const measure = () => {
      const bounds = element.getBoundingClientRect();
      const nodes: Record<string, Point> = {};
      element.querySelectorAll<HTMLElement>("[data-arena-node]").forEach(node => {
        const rect = node.getBoundingClientRect();
        nodes[node.dataset.arenaNode!] = { x: rect.left - bounds.left + rect.width / 2, y: rect.top - bounds.top + rect.height / 2 };
      });
      setGeometry({ width: bounds.width, height: bounds.height, nodes });
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [nodeKey, Boolean(s.commons)]);
  const selected = (kind: string, id: string) => selection && "id" in selection && selection.kind === kind && selection.id === id;
  const chain = (id: string) => evidenceNodes.includes(id) ? " chain-node" : "";
  const routes = [
    ...agents.map(id => ({ from: "rule", to: id })),
    ...agents.map(id => ({ from: id, to: "world" })),
    { from: "world", to: "reward" }, { from: "world", to: "outcome" },
  ];
  return <section ref={scene} className={`arena-scene ${frozen ? "arena-frozen" : ""} ${reducedMotion ? "arena-reduced" : ""} ${compact ? "arena-compact" : ""}`} aria-label="Арена подтвержденных событий">
    <svg className="arena-wires" viewBox={`0 0 ${geometry.width} ${geometry.height}`} aria-label="Связи и события арены">
      {routes.map(({ from, to }) => geometry.nodes[from] && geometry.nodes[to] ? <path aria-hidden="true" key={`${from}-${to}`} className={evidenceNodes.includes(from) && evidenceNodes.includes(to) ? "chain-route" : ""} d={curve(geometry.nodes[from]!, geometry.nodes[to]!)} /> : null)}
      {s.markers.slice(-20).map(marker => {
        const from = geometry.nodes[marker.from] ?? geometry.nodes.world;
        const to = geometry.nodes[marker.to] ?? geometry.nodes.world;
        if (!from || !to) return null;
        const path = curve(from, to);
        const label = `${marker.kind === "rejected" ? "Действие отклонено" : actionLabel(marker.label)} · событие #${marker.id}`;
        return <g key={marker.id}>
          <path role="button" tabIndex={0} aria-label={`Открыть: ${label}`} className={`arena-event-route ${marker.kind === "rejected" ? "route-rejected" : ""} ${evidence.includes(marker.id) ? "is-evidence" : ""}`} d={path} onClick={() => onSelect?.({kind:"event",seq:marker.id})} onKeyDown={e => {if(e.key === "Enter" || e.key === " "){e.preventDefault();onSelect?.({kind:"event",seq:marker.id});}}}/>
          <g aria-hidden="true" className={`arena-marker marker-${marker.kind} ${evidence.includes(marker.id) ? "evidence" : ""}`}>
            <circle r="5" cx={reducedMotion || frozen ? to.x : undefined} cy={reducedMotion || frozen ? to.y : undefined}>
              <title>{label}</title>
              {!reducedMotion && !frozen && <animateMotion dur="260ms" fill="freeze" path={path} />}
            </circle>
          </g>
        </g>;
      })}
    </svg>
    <button data-arena-node="rule" className={`arena-rule arena-node ${selection?.kind === "rule" ? "selected" : ""}${chain("rule")}`} onClick={() => onSelect?.({ kind: "rule" })}><span className="arena-eyebrow">Действующее правило</span><strong>{ruleName || "Правило запуска"}</strong><small>{s.ruleTrigger ? EVENT_LABELS[s.ruleTrigger] ?? s.ruleTrigger : "Ожидаем инициализации мира"}</small></button>
    <div className="arena-section-label">Участники <span>{s.agentOrder.length}</span></div>
    <div className="arena-agents">{agents.map(id => {
      const i = s.agentOrder.indexOf(id), a = s.agents[id]!;
      const elapsed = a.since && now ? Math.max(0, Math.floor((now - Date.parse(a.since)) / 1000)) : null;
      return <button data-arena-node={id} key={id} className={`arena-node arena-agent ${selected("agent", id) ? "selected" : ""}${chain(id)}`} onClick={() => onSelect?.({ kind: "agent", id })}><span className={`arena-avatar profile-${i % 3}`}>{String(i + 1).padStart(2, "0")}</span><strong>{actorName(id, s.agentOrder)}</strong><small>{a.kind === "model" ? "Модель" : "Сценарий"} · {MODE_LABELS[a.mode] ?? a.mode}</small><span className={`arena-agent-state state-${a.status}`}>{a.status === "choosing" && frozen ? "Ожидание · обновление на паузе" : AGENT_STATUS[a.status]}{a.status === "choosing" && !frozen && elapsed !== null ? ` · ${elapsed} с` : ""}</span>{a.lastAction && <small>{actionLabel(a.lastAction)}</small>}</button>;
    })}</div>
    {agentPages > 1 && <div className="arena-controls"><span>Группа участников {agentPage + 1}/{agentPages}</span><button className="btn btn-compact" disabled={agentPage === 0} onClick={() => setAgentPage(p => p - 1)}>Предыдущие участники</button><button className="btn btn-compact" disabled={agentPage >= agentPages - 1} onClick={() => setAgentPage(p => p + 1)}>Следующие участники</button></div>}
    <div data-arena-node="world" className={`arena-world${chain("world")}`}><div className="arena-section-label">Среда <span>{(ENV_LABELS[s.environment] ?? s.environment) || "Подготовка"}</span></div>
      {s.commons ? <button data-arena-node="commons" className={`arena-commons arena-node${chain("commons")}`} onClick={() => onSelect?.({ kind: "entity", id: "commons" })}><span>Общий ресурс</span><strong>{s.commons.stock} <small>/ {s.commons.capacity}</small></strong><meter min={0} max={Math.max(1, s.commons.capacity)} value={s.commons.stock} aria-label="Запас ресурса" /><small>Минимальный запас: {s.commons.minStock}{s.commons.depletedTick !== null ? ` · исчерпан на тике ${s.commons.depletedTick}` : ""}</small></button> : <div className="arena-items">{items.map(id => {
        const item = s.items[id]!;
        return <button data-arena-node={id} key={id} className={`arena-node arena-item ${selected("entity", id) ? "selected" : ""} ${item.solved ? "solved" : ""}${chain(id)}`} onClick={() => onSelect?.({ kind: "entity", id })}><strong>#{itemNumber(id)} <span>{item.overdue ? "Просрочено" : ITEM_STATUS[item.status] ?? item.status}</span></strong><small>Сложность: {(COMPLEXITY[item.complexity] ?? item.complexity) || "—"} · работа {item.completed}{item.required !== null ? `/${item.required}` : ""}</small><small>{item.parent ? `↳ ${itemNumber(item.parent)} · корень ${itemNumber(item.root)}` : `Корень ${itemNumber(item.root || id)}`}</small><span className={item.solved ? "arena-success" : "t-caption"}>{item.solved ? "✓ Фактически решено" : "Фактический результат не подтвержден"}</span>{item.status === "closed" && <small>Закрыто · подтверждение {CONFIRMATION[item.confirmation ?? ""] ?? "—"}</small>}</button>;
      })}{!items.length && <p className="arena-empty">Объекты появятся после подтвержденных событий сервера.</p>}</div>}
      {pages > 1 && <div className="arena-controls"><span>Агрегировано: {s.itemOrder.length} объектов · группа {Math.min(page, pages - 1) + 1}/{pages}</span><button className="btn btn-compact" disabled={page === 0} onClick={() => setPage(p => p - 1)}>Предыдущая группа</button><button className="btn btn-compact" disabled={page >= pages - 1} onClick={() => setPage(p => p + 1)}>Раскрыть следующую</button></div>}
    </div>
    <div className="arena-registers"><button data-arena-node="reward" className={`arena-register reward${chain("reward")}`} onClick={() => onSelect?.({ kind: "register", id: "reward" })}><span>Начисленная награда</span><strong>{s.registers.reward / 1_000_000} <small>очк.</small></strong><small>Ожидает подтверждения: {s.registers.pending / 1_000_000}</small></button><button data-arena-node="outcome" className={`arena-register outcome${chain("outcome")}`} onClick={() => onSelect?.({ kind: "register", id: "outcome" })}><span>Фактический результат</span><strong>{s.registers.outcome}{s.registers.outcomeDenominator !== null && <small> / {s.registers.outcomeDenominator}</small>}</strong><small>{s.registers.outcomeLabel || "Подтвержденное значение"}</small><small>{s.registers.formalLabel && `${s.registers.formalLabel}: ${s.registers.formal}`}</small></button></div>
  </section>;
}
