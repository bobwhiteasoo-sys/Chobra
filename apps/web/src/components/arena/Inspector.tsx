"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import { IdChip } from "@/components/ui";
import { actionLabel, actorName, AGENT_STATUS, eventDetail, eventLabel, itemNumber } from "@/lib/arena/labels";
import type { Projection } from "@/lib/arena/projection";
import { MODE_LABELS, points } from "@/lib/format";
import type { RunDetail, RunEvent } from "@/lib/types";

import type { Selection } from "./Scene";

type Props = {
  selection: Selection | null;
  projection: Projection;
  log: RunEvent[];
  run: RunDetail;
  onSelect: (selection: Selection) => void;
  onJump: ((seq: number) => void) | null;
  findingHref: (checkId: string) => string | null;
};

function Facts({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="facts">
      {rows
        .filter(([, v]) => v !== null && v !== undefined && v !== "")
        .map(([k, v]) => (
          <div key={k} style={{ display: "contents" }}>
            <dt>{k}</dt>
            <dd>{v}</dd>
          </div>
        ))}
    </dl>
  );
}

function EventList({ events, onSelect }: { events: RunEvent[]; onSelect: (s: Selection) => void }) {
  if (!events.length) return <p className="t-caption">Событий пока нет</p>;
  return (
    <ul className="plain-list inspector-events">
      {events.map((e) => (
        <li key={e.seq}>
          <button type="button" className="event-link" onClick={() => onSelect({ kind: "event", seq: e.seq })}>
            <span className="num t-caption">#{e.seq}</span>
            <span>
              {eventLabel(e)}
              {eventDetail(e) ? <span className="t-caption">, {eventDetail(e)}</span> : null}
            </span>
            <span className="num t-caption">т{e.tick}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}

function value(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

export function Inspector({ selection, projection, log, run, onSelect, onJump, findingHref }: Props) {
  const order = projection.agentOrder;
  if (!selection) {
    return (
      <div className="stack" style={{ gap: 12 }}>
        <h2 className="t-panel">Инспектор</h2>
        <p className="t-secondary" style={{ margin: 0 }}>
          Выберите правило, участника, объект, регистр или нарушение, чтобы увидеть исходные события.
        </p>
        <Facts
          rows={[
            ["Seed", run.seed],
            ["Режим агентов", MODE_LABELS[run.agent_mode] ?? run.agent_mode],
            ["Последнее событие", `#${projection.lastSeq}`],
            ["Снимок", <IdChip key="s" value={run.snapshot_hash} />],
            ["Внешняя лента", <IdChip key="t" value={run.tape_hash} />],
            ["Корень цепочки", run.chain_root ? <IdChip key="c" value={run.chain_root} /> : "после завершения"],
          ]}
        />
      </div>
    );
  }

  if (selection.kind === "rule") {
    return (
      <div className="stack" style={{ gap: 12 }}>
        <h2 className="t-panel">Правило</h2>
        <strong>{run.rule.name}</strong>
        <p className="t-secondary" style={{ margin: 0 }}>
          {run.rule.source_text || "Текстовое описание не задано"}
        </p>
        <Facts rows={[["Версия", `v${run.rule.version}`], ["Хеш дерева", <IdChip key="h" value={run.rule.ast_hash} />], ["Событие начисления", projection.ruleTrigger ?? "—"]]} />
        <Link href={`/p/${run.project_id}/rules/${run.rule.id}`} className="btn btn-secondary btn-compact">
          Открыть правило
        </Link>
      </div>
    );
  }

  if (selection.kind === "agent") {
    const a = projection.agents[selection.id];
    if (!a) return <p className="t-secondary">Участник не найден в текущем состоянии</p>;
    const events = log.filter((e) => e.actor_id === a.id || e.payload.actor_id === a.id).slice(-10).reverse();
    return (
      <div className="stack" style={{ gap: 12 }}>
        <h2 className="t-panel">{actorName(a.id, order)}</h2>
        <Facts
          rows={[
            ["Идентификатор", a.id],
            ["Режим", MODE_LABELS[a.mode] ?? a.mode],
            ["Исполнитель", a.kind === "model" ? "языковая модель" : "сценарный агент"],
            ["Состояние", AGENT_STATUS[a.status]],
            ["Последнее действие", actionLabel(a.lastAction) || "—"],
            ["Последний отказ", a.lastRejection ?? "—"],
            ["Начислено", `${points(a.reward)} очк.`],
            ["Ожидает подтверждения", a.pending ? `${points(a.pending)} очк.` : "0"],
            ["Упрощенное решение", a.degraded ? "да, модель не ответила по схеме" : ""],
          ]}
        />
        <h3 className="t-caption">Последние события участника</h3>
        <EventList events={events} onSelect={onSelect} />
      </div>
    );
  }

  if (selection.kind === "item") {
    const item = projection.items[selection.id];
    if (!item) return <p className="t-secondary">Объект еще не поступил в этот момент истории</p>;
    const events = log.filter((e) => e.entity_id === item.id || e.payload.issue_id === item.id || e.payload.task_id === item.id).slice(-12).reverse();
    const isTask = projection.environment === "taskboard";
    return (
      <div className="stack" style={{ gap: 12 }}>
        <h2 className="t-panel">
          {isTask ? "Задача" : "Обращение"} #{itemNumber(item.id)}
        </h2>
        <Facts
          rows={[
            ["Исходный объект", item.root !== item.id ? `#${itemNumber(item.root)}` : "это исходный объект"],
            ["Часть объекта", item.parent ? `#${itemNumber(item.parent)}` : ""],
            ["Административный статус", item.status],
            [isTask ? "Принята проверкой" : "Проблема фактически решена", item.solved ? "да" : "нет"],
            ["Исполнитель", item.assignee ? actorName(item.assignee, order) : "нет"],
            ["Заявленная сложность", item.complexity],
            ["Истинная сложность", item.trueComplexity ?? ""],
            ["Работа", item.required !== null ? `${item.completed} из ${item.required} квантов` : ""],
            ["Срок", item.deadline !== null ? `тик ${item.deadline}${item.overdue ? ", истек" : ""}` : ""],
            ["Закрытий", item.closes || ""],
            ["Повторных открытий", item.reopened || ""],
            ["Проверка клиента", item.confirmation ?? ""],
            ["Отметка «готово»", isTask ? (item.declaredDone ? "есть" : "нет") : ""],
            ["Дефекты", isTask ? item.defects ?? 0 : ""],
          ]}
        />
        <h3 className="t-caption">История объекта</h3>
        <EventList events={events} onSelect={onSelect} />
      </div>
    );
  }

  if (selection.kind === "register") {
    const r = projection.registers;
    return selection.id === "reward" ? (
      <div className="stack" style={{ gap: 12 }}>
        <h2 className="t-panel">Начисленная награда</h2>
        <p className="t-secondary" style={{ margin: 0 }}>
          Сумма подтвержденных записей реестра наград по событиям reward.settled и reward.reversed. Сцена не пересчитывает награды: значение берется из событий сервера.
        </p>
        <Facts rows={[["Начислено", `${points(r.reward)} очк.`], ["Ожидает подтверждения", `${points(r.pending)} очк.`], [r.formalLabel || "Формальный показатель", r.formal]]} />
      </div>
    ) : (
      <div className="stack" style={{ gap: 12 }}>
        <h2 className="t-panel">Фактический результат</h2>
        <p className="t-secondary" style={{ margin: 0 }}>
          Бизнес-показатель среды, рассчитанный сервером на каждом тике по фактическому состоянию мира, а не по административным отметкам.
        </p>
        <Facts rows={[["Значение", `${r.outcome} ${r.outcomeLabel}`], ["Знаменатель", r.outcomeDenominator ?? "не применяется"]]} />
      </div>
    );
  }

  if (selection.kind === "violation") {
    const v = projection.violations.find((x) => x.seq === selection.seq);
    if (!v) return <p className="t-secondary">Нарушение появится позже в истории запуска</p>;
    const evidence = log.filter((e) => v.evidence.includes(e.seq));
    const href = findingHref(v.checkId);
    return (
      <div className="stack" style={{ gap: 12 }}>
        <span className="violation-tag" style={{ alignSelf: "flex-start" }}>
          Нарушение
        </span>
        <h2 className="t-panel">{v.title}</h2>
        <p className="t-secondary" style={{ margin: 0 }}>
          {v.message}
        </p>
        <Facts rows={[["Проверка", v.checkId], ["Тик", v.tick], ["Событие проверки", `#${v.seq}`], ["Объекты", v.entities.map((e) => `#${itemNumber(e)}`).join(", ")]]} />
        <h3 className="t-caption">Звенья доказательства, по номерам событий</h3>
        <EventList events={evidence} onSelect={onSelect} />
        {href ? (
          <Link href={href} className="btn btn-secondary btn-compact">
            Открыть карточку нарушения
          </Link>
        ) : (
          <p className="t-caption">Карточка нарушения появится после завершения аудита запуска.</p>
        )}
      </div>
    );
  }

  const event = log.find((e) => e.seq === selection.seq);
  if (!event) return <p className="t-secondary">Событие #{selection.seq} не загружено</p>;
  return (
    <div className="stack" style={{ gap: 12 }}>
      <h2 className="t-panel">{eventLabel(event)}</h2>
      <Facts
        rows={[
          ["Номер", `#${event.seq}`],
          ["Предметный номер", event.domain_seq !== null ? `#${event.domain_seq}` : "операционное событие"],
          ["Тик", event.tick],
          ["Тип", event.type],
          ["Участник", event.actor_id ? actorName(event.actor_id, order) : ""],
          ["Объект", event.entity_id ? `#${itemNumber(event.entity_id)}` : ""],
          ["Хеш состояния", event.state_hash ? <IdChip key="h" value={event.state_hash} /> : ""],
        ]}
      />
      <h3 className="t-caption">Данные события</h3>
      <dl className="facts payload">
        {Object.entries(event.payload).map(([k, v]) => (
          <div key={k} style={{ display: "contents" }}>
            <dt>{k}</dt>
            <dd>{value(v)}</dd>
          </div>
        ))}
      </dl>
      {onJump ? (
        <button type="button" className="btn btn-secondary btn-compact" onClick={() => onJump(event.seq)}>
          Показать состояние на этом событии
        </button>
      ) : null}
    </div>
  );
}
