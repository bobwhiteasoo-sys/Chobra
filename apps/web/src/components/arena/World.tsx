"use client";

import { CircleCheck, CircleDashed, CircleX, Clock3 } from "lucide-react";
import { useState } from "react";

import { actorName, itemNumber } from "@/lib/arena/labels";
import type { ItemView, Projection } from "@/lib/arena/projection";

export const DETAILED_LIMIT = 80;

type Props = {
  projection: Projection;
  selectedItem: string | null;
  highlighted: Set<string> | null;
  flashing: Set<string>;
  onSelect: (id: string) => void;
};

const COMPLEXITY: Record<string, string> = { easy: "простая", hard: "сложная" };
const STATUS: Record<string, string> = {
  open: "Открыто",
  closed: "Закрыто",
  escalated: "Во второй линии",
  split: "Разделено",
  todo: "Свободна",
  in_progress: "В работе",
  accepted: "Принята",
};
const CONFIRMATION: Record<string, string> = { pending: "ждет проверки клиента", confirmed: "клиент подтвердил", rejected: "клиент не подтвердил", unobserved: "клиент не ответил" };

function visibleItems(projection: Projection, expanded: boolean): { shown: ItemView[]; hidden: ItemView[] } {
  const all = projection.itemOrder.map((id) => projection.items[id]!).filter(Boolean);
  if (expanded || all.length <= DETAILED_LIMIT) return { shown: all, hidden: [] };
  // Keep arrival order (stable positions); fold finished objects first.
  const finished = (i: ItemView) => (i.status === "closed" && i.solved) || i.status === "accepted" || i.status === "split";
  const active = all.filter((i) => !finished(i));
  const shown = active.slice(0, DETAILED_LIMIT);
  const shownIds = new Set(shown.map((i) => i.id));
  return { shown: all.filter((i) => shownIds.has(i.id)), hidden: all.filter((i) => !shownIds.has(i.id)) };
}

function ItemCard({ item, projection, selected, dimmed, highlighted, flashing, onSelect }: { item: ItemView; projection: Projection; selected: boolean; dimmed: boolean; highlighted: boolean; flashing: boolean; onSelect: (id: string) => void }) {
  const isTask = projection.environment === "taskboard";
  const closedUnsolved = !isTask && item.status === "closed" && !item.solved;
  const doneUnaccepted = isTask && item.declaredDone && item.status !== "accepted";
  const progress = item.required ? Math.min(100, Math.round((item.completed / item.required) * 100)) : null;
  const complexity = item.trueComplexity && item.complexity && item.trueComplexity !== item.complexity ? `заявлена ${COMPLEXITY[item.complexity] ?? item.complexity}, факт ${COMPLEXITY[item.trueComplexity] ?? item.trueComplexity}` : COMPLEXITY[item.trueComplexity ?? item.complexity] ?? "";
  return (
    <button
      type="button"
      className={`item-card${selected ? " is-selected" : ""}${dimmed ? " is-dimmed" : ""}${highlighted ? " is-chain" : ""}${flashing ? " is-flash" : ""}${item.parent ? " is-child" : ""}`}
      data-anchor={`item:${item.id}`}
      aria-pressed={selected}
      aria-label={`${isTask ? "Задача" : "Обращение"} ${itemNumber(item.id)}`}
      onClick={() => onSelect(item.id)}
    >
      <span className="item-head">
        <span className="item-no">#{itemNumber(item.id)}</span>
        {item.importance === "high" ? <span className="item-tag">важная</span> : null}
        {item.overdue ? (
          <span className="item-tag is-danger">
            <Clock3 size={11} aria-hidden /> срок
          </span>
        ) : null}
      </span>
      <span className={`item-status${item.status === "closed" || item.declaredDone ? " is-formal" : ""}`}>{isTask && item.declaredDone && item.status !== "accepted" ? "Отмечена готовой" : STATUS[item.status] ?? item.status}</span>
      {isTask ? (
        item.status === "accepted" ? (
          <span className="item-outcome is-solved">
            <CircleCheck size={12} aria-hidden /> Принята проверкой
          </span>
        ) : doneUnaccepted ? (
          <span className="item-outcome is-unsolved">
            <CircleX size={12} aria-hidden /> Не принята
          </span>
        ) : null
      ) : item.solved ? (
        <span className="item-outcome is-solved">
          <CircleCheck size={12} aria-hidden /> Проблема решена
        </span>
      ) : closedUnsolved ? (
        <span className="item-outcome is-unsolved">
          <CircleX size={12} aria-hidden /> Проблема не решена
        </span>
      ) : (
        <span className="item-outcome">
          <CircleDashed size={12} aria-hidden /> Не решена
        </span>
      )}
      {progress !== null && item.status !== "split" ? (
        <span className="item-bar" aria-hidden>
          <span style={{ width: `${progress}%` }} />
        </span>
      ) : null}
      <span className="item-meta">
        {item.assignee ? actorName(item.assignee, projection.agentOrder) : "никто не взял"}
        {complexity ? `, ${complexity}` : ""}
      </span>
      {item.confirmation && item.confirmation !== "pending" ? <span className="item-meta">{CONFIRMATION[item.confirmation] ?? item.confirmation}</span> : null}
      {item.defects ? <span className="item-meta is-danger">дефектов: {item.defects}</span> : null}
      {item.reopened ? <span className="item-meta">открыто повторно: {item.reopened}</span> : null}
    </button>
  );
}

function Commons({ projection }: { projection: Projection }) {
  const c = projection.commons!;
  const pct = c.capacity ? Math.round((c.stock / c.capacity) * 100) : 0;
  const minPct = c.capacity ? (c.minStock / c.capacity) * 100 : 0;
  const history = c.history.slice(-120);
  const maxTick = Math.max(1, ...history.map((h) => h.tick));
  const points = history.map((h) => `${((h.tick / maxTick) * 100).toFixed(1)},${(40 - (h.stock / Math.max(1, c.capacity)) * 40).toFixed(1)}`).join(" ");
  const below = c.stock < c.minStock;
  return (
    <div className="commons" data-anchor="commons">
      <div className="row-between">
        <span className="t-caption">Общий запас</span>
        {c.depletedTick !== null ? <span className="item-tag is-danger">исчерпан на тике {c.depletedTick}</span> : below ? <span className="item-tag is-danger">ниже минимума</span> : null}
      </div>
      <div className="commons-figure">
        <span className="t-value">{c.stock.toLocaleString("ru-RU")}</span>
        <span className="t-secondary">из {c.capacity.toLocaleString("ru-RU")} единиц</span>
      </div>
      <div className="commons-bar" role="meter" aria-label="Общий запас" aria-valuemin={0} aria-valuemax={c.capacity} aria-valuenow={c.stock}>
        <span className={below ? "is-low" : ""} style={{ width: `${pct}%` }} />
        <i style={{ left: `${minPct}%` }} title={`Минимальный запас ${c.minStock}`} />
      </div>
      <span className="t-caption">Минимум {c.minStock.toLocaleString("ru-RU")}; линия показывает его положение</span>
      {history.length > 1 ? (
        <svg className="commons-spark" viewBox="0 0 100 40" preserveAspectRatio="none" role="img" aria-label={`Запас по тикам: от ${history[0]!.stock} до ${history.at(-1)!.stock}`}>
          <line x1="0" x2="100" y1={40 - (c.minStock / Math.max(1, c.capacity)) * 40} y2={40 - (c.minStock / Math.max(1, c.capacity)) * 40} className="spark-min" />
          <polyline points={points} className="spark-line" />
        </svg>
      ) : null}
    </div>
  );
}

export function World({ projection, selectedItem, highlighted, flashing, onSelect }: Props) {
  const [expanded, setExpanded] = useState(false);
  if (projection.environment === "resourcecommons" && projection.commons) return <Commons projection={projection} />;
  const { shown, hidden } = visibleItems(projection, expanded);
  if (!shown.length && !hidden.length) {
    return <p className="t-secondary world-empty">{projection.status === "initializing" ? "Мир готовится" : "Объекты еще не поступили"}</p>;
  }
  const isTask = projection.environment === "taskboard";
  const hiddenSolved = hidden.filter((i) => i.solved).length;
  return (
    <>
      <div className="item-grid" role="list" aria-label={isTask ? "Задачи" : "Обращения"}>
        {shown.map((item) => (
          <div role="listitem" key={item.id} className="item-cell">
            <ItemCard
              item={item}
              projection={projection}
              selected={selectedItem === item.id}
              dimmed={Boolean(highlighted) && !highlighted!.has(item.id) && !highlighted!.has(item.root)}
              highlighted={Boolean(highlighted?.has(item.id))}
              flashing={flashing.has(item.id)}
              onSelect={onSelect}
            />
          </div>
        ))}
      </div>
      {hidden.length ? (
        <button type="button" className="aggregate" onClick={() => setExpanded(true)}>
          Еще {hidden.length} завершенных: решено {hiddenSolved}. Показать все
        </button>
      ) : expanded && projection.itemOrder.length > DETAILED_LIMIT ? (
        <button type="button" className="aggregate" onClick={() => setExpanded(false)}>
          Свернуть завершенные
        </button>
      ) : null}
    </>
  );
}
