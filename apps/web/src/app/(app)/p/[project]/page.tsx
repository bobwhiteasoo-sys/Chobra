"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Archive, ArchiveRestore, OctagonAlert } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { Button, EmptyState, Pill, RunStatus } from "@/components/ui";
import { api } from "@/lib/api";
import { count, dateTime, MODE_LABELS, REPLAY_STATUS } from "@/lib/format";
import { useProject } from "@/lib/queries";

export default function ProjectOverview() {
  const { project: id } = useParams<{ project: string }>();
  const project = useProject(id);
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);
  const p = project.data;
  if (!p) return null;
  const published = (p.rules ?? []).filter((r) => r.status === "published");
  const drafts = (p.rules ?? []).filter((r) => r.status === "draft");
  const scenario = (p.scenarios ?? []).find((s) => s.status === "published");
  const verified = (p.findings ?? []).filter((f) => f.replay_status === "replay_verified");
  const unverified = (p.findings ?? []).filter((f) => f.replay_status !== "replay_verified");

  const toggleArchive = async () => {
    setBusy(true);
    await api(`/projects/${p.id}/${p.archived_at ? "restore" : "archive"}`, { body: {} });
    await queryClient.invalidateQueries({ queryKey: ["project", p.id] });
    setBusy(false);
  };

  return (
    <div className="split">
      <div className="stack-24">
        <section className="panel">
          <h2 className="t-panel">Вопрос исследования</h2>
          <p style={{ margin: "8px 0" }}>{p.research_question}</p>
          <p className="t-secondary" style={{ margin: 0 }}>
            Желаемый результат: {p.desired_outcome}
          </p>
        </section>

        <section className="panel">
          <div className="panel-head">
            <h2 className="t-panel">Последнее сравнение</h2>
            {p.last_comparison ? <Link href={`/comparisons/${p.last_comparison.id}`} className="btn btn-secondary btn-compact">Открыть сравнение</Link> : null}
          </div>
          {p.last_comparison ? (
            <div className="stack" style={{ gap: 8 }}>
              {p.last_comparison.summary.map((line) => (
                <p key={line} style={{ margin: 0 }} className="num">
                  {line}
                </p>
              ))}
              {p.last_comparison.tradeoffs.map((t) => (
                <p key={t} className="t-secondary" style={{ margin: 0 }}>
                  {t}
                </p>
              ))}
              <p className="t-caption">{dateTime(p.last_comparison.created_at)}</p>
            </div>
          ) : (
            <EmptyState title="Сравнений еще не было">Запустите серию из двух правил: результат появится здесь с числом пар и разностями показателей.</EmptyState>
          )}
        </section>

        <section className="panel">
          <div className="panel-head">
            <h2 className="t-panel">Проверенные нарушения</h2>
            <Pill tone={verified.length ? "danger" : "neutral"}>{verified.length}</Pill>
          </div>
          {verified.length ? (
            <div>
              {verified.map((f) => (
                <Link key={f.id} href={`/findings/${f.id}`} className="list-row">
                  <div style={{ minWidth: 0 }}>
                    <div className="row" style={{ gap: 8 }}>
                      <OctagonAlert size={16} color="#FF637D" aria-hidden />
                      <strong>{f.title}</strong>
                    </div>
                    <p className="t-secondary clamp-2" style={{ margin: "4px 0 0" }}>
                      {f.explanation}
                    </p>
                  </div>
                  <Pill tone="success">Воспроизведено</Pill>
                </Link>
              ))}
            </div>
          ) : (
            <p className="t-secondary" style={{ margin: 0 }}>
              Подтвержденных воспроизведением нарушений пока нет.
            </p>
          )}
          {unverified.length ? (
            <>
              <hr className="divider" />
              <h3 className="t-body" style={{ fontWeight: 600, margin: "0 0 8px" }}>
                Наблюдались, воспроизведение не проверено
              </h3>
              {unverified.slice(0, 8).map((f) => (
                <Link key={f.id} href={`/findings/${f.id}`} className="list-row">
                  <span>{f.title}</span>
                  <span className="t-caption">{REPLAY_STATUS[f.replay_status] ?? f.replay_status}</span>
                </Link>
              ))}
            </>
          ) : null}
        </section>
      </div>

      <aside className="stack-24">
        <section className="panel">
          <div className="panel-head">
            <h2 className="t-panel">Правила</h2>
            <Link href={`/p/${p.id}/rules`} className="btn btn-ghost btn-compact">
              Все
            </Link>
          </div>
          <h3 className="t-caption" style={{ margin: "0 0 6px" }}>
            Опубликованные варианты
          </h3>
          {published.slice(0, 5).map((r) => (
            <Link key={r.id} href={`/p/${p.id}/rules/${r.id}`} className="list-row">
              <span className="clamp-2">{r.name}</span>
              <span className="t-caption num">v{r.version}</span>
            </Link>
          ))}
          {drafts.length ? (
            <>
              <h3 className="t-caption" style={{ margin: "14px 0 6px" }}>
                Черновики
              </h3>
              {drafts.map((r) => (
                <Link key={r.id} href={`/p/${p.id}/rules/${r.id}`} className="list-row">
                  <span className="clamp-2">{r.name}</span>
                  <Pill>Черновик</Pill>
                </Link>
              ))}
            </>
          ) : null}
        </section>
        <section className="panel">
          <div className="panel-head">
            <h2 className="t-panel">Сценарий</h2>
            <Link href={`/p/${p.id}/scenario`} className="btn btn-ghost btn-compact">
              Открыть
            </Link>
          </div>
          {scenario ? (
            <dl className="kv">
              <dt>Версия</dt>
              <dd className="num">v{scenario.version}</dd>
              <dt>Участников</dt>
              <dd className="num">{scenario.actor_count}</dd>
              <dt>Горизонт</dt>
              <dd className="num">{String(scenario.config.horizon_ticks)} тиков</dd>
            </dl>
          ) : (
            <p className="t-secondary">Нет опубликованной версии.</p>
          )}
        </section>
        <section className="panel">
          <h2 className="t-panel" style={{ marginBottom: 10 }}>
            Серии
          </h2>
          {(p.batches ?? []).length ? (
            (p.batches ?? []).slice(0, 6).map((b) => (
              <Link key={b.id} href={`/experiments/${b.id}`} className="list-row">
                <span>
                  <span className="clamp-2">{b.title}</span>
                  <span className="t-caption" style={{ display: "block" }}>
                    {count(b.planned_runs, "запуск", "запуска", "запусков")}, {b.modes.map((m) => (MODE_LABELS[m] ?? m).toLowerCase()).join(", ")}
                  </span>
                </span>
                <RunStatus status={b.status} />
              </Link>
            ))
          ) : (
            <p className="t-secondary" style={{ margin: 0 }}>
              Серий еще не было.
            </p>
          )}
        </section>
        <Button variant="ghost" compact busy={busy} onClick={toggleArchive}>
          {p.archived_at ? <ArchiveRestore size={16} aria-hidden /> : <Archive size={16} aria-hidden />}
          {p.archived_at ? "Восстановить проект" : "Перенести в архив"}
        </Button>
      </aside>
    </div>
  );
}
