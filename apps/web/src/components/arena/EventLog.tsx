"use client";

import { useMemo, useState } from "react";

import { actorName, eventDetail, eventLabel, itemNumber } from "@/lib/arena/labels";
import type { RunEvent } from "@/lib/types";

const CATEGORIES: { id: string; label: string; test: (e: RunEvent) => boolean }[] = [
  { id: "all", label: "Все события", test: () => true },
  { id: "actions", label: "Действия участников", test: (e) => e.type.startsWith("action.") || e.type.startsWith("model_call.") },
  { id: "rewards", label: "Награды", test: (e) => e.type.startsWith("reward.") },
  { id: "world", label: "Изменения мира", test: (e) => /^(issue|task|resource)\./.test(e.type) },
  { id: "checks", label: "Нарушения", test: (e) => e.type === "check.failed" },
];
const LIMIT = 400;

type Props = {
  log: RunEvent[];
  cursorSeq: number | null;
  agentOrder: string[];
  selectedSeq: number | null;
  onSelect: (seq: number) => void;
};

export function EventLog({ log, cursorSeq, agentOrder, selectedSeq, onSelect }: Props) {
  const [category, setCategory] = useState("all");
  const [domainOnly, setDomainOnly] = useState(true);
  const rows = useMemo(() => {
    const test = CATEGORIES.find((c) => c.id === category)!.test;
    const out: RunEvent[] = [];
    for (let i = log.length - 1; i >= 0 && out.length < LIMIT; i--) {
      const e = log[i]!;
      if (cursorSeq !== null && e.seq > cursorSeq) continue;
      if (domainOnly && e.event_class !== "domain") continue;
      if (e.type === "tick.completed" && category === "all") continue;
      if (test(e)) out.push(e);
    }
    return out;
  }, [log, cursorSeq, category, domainOnly]);

  return (
    <div className="stack" style={{ gap: 12 }}>
      <div className="row" style={{ gap: 12, flexWrap: "wrap" }}>
        <label className="field" style={{ minWidth: 200 }}>
          <span className="label">Показывать</span>
          <select className="select" value={category} onChange={(e) => setCategory(e.target.value)}>
            {CATEGORIES.map((c) => (
              <option key={c.id} value={c.id}>
                {c.label}
              </option>
            ))}
          </select>
        </label>
        <label className="check" style={{ alignSelf: "flex-end", minHeight: 44 }}>
          <input type="checkbox" checked={domainOnly} onChange={(e) => setDomainOnly(e.target.checked)} />
          Только предметные события
        </label>
        <span className="t-caption" style={{ alignSelf: "flex-end", paddingBottom: 12 }}>
          {rows.length === LIMIT ? `последние ${LIMIT}` : `${rows.length}`} из {log.length} в журнале
        </span>
      </div>
      <div className="table-wrap event-log">
        <table className="table">
          <thead>
            <tr>
              <th className="r">№</th>
              <th className="r">Тик</th>
              <th>Событие</th>
              <th>Участник</th>
              <th>Объект</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((e) => (
              <tr key={e.seq} aria-selected={selectedSeq === e.seq} className={e.type === "check.failed" ? "is-violation" : undefined}>
                <td className="r num t-caption">{e.seq}</td>
                <td className="r num t-caption">{e.tick}</td>
                <td>
                  <button type="button" className="event-link" onClick={() => onSelect(e.seq)}>
                    {eventLabel(e)}
                    {eventDetail(e) ? <span className="t-caption">, {eventDetail(e)}</span> : null}
                  </button>
                </td>
                <td className="t-secondary">{actorName(e.actor_id, agentOrder)}</td>
                <td className="t-secondary num">{e.entity_id ? `#${itemNumber(e.entity_id)}` : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
