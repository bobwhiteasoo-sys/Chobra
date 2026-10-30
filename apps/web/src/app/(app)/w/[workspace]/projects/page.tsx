"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useDeferredValue, useState } from "react";

import { Situations } from "@/components/flow/Situations";
import { useCurrentWorkspace } from "@/components/Shell";
import { ErrorState, Loading } from "@/components/ui";
import { dateTime } from "@/lib/format";
import { isActive, useMe, useProjects } from "@/lib/queries";
import type { Project } from "@/lib/types";

function state(project: Project): { label: string; tone: string } {
  const status = project.last_batch?.status;
  if (!status) return { label: "Ещё не проверяли", tone: "" };
  if (isActive(status)) return { label: "Идёт проверка", tone: "is-active" };
  return { label: "Открыть ответ", tone: "is-done" };
}

export default function HomePage() {
  const { workspace } = useParams<{ workspace: string }>();
  const { workspaceId } = useCurrentWorkspace();
  const id = workspace ?? workspaceId ?? undefined;
  const me = useMe();
  const [q, setQ] = useState("");
  const [archived, setArchived] = useState(false);
  const projects = useProjects(id, { q: useDeferredValue(q), archived });
  const canCreate = me.data?.workspaces.find((w) => w.id === id)?.role !== "viewer";
  const items = projects.data?.items ?? [];
  return (
    <>
      <h1 className="home-title">Что проверим?</h1>
      <p className="lead">Нажмите на ситуацию. Ответ будет через несколько секунд.</p>
      {canCreate ? <Situations workspace={async () => id!} /> : null}
      {projects.isLoading ? <Loading lines={3} /> : projects.error ? <ErrorState error={projects.error} onRetry={() => projects.refetch()} /> : items.length || q || archived ? (
        <section aria-labelledby="history-title">
          <div className="history-head">
            <h2 className="t-section" id="history-title">{archived ? "Архив" : "Прошлые проверки"}</h2>
            <div className="row" style={{ gap: 8 }}>
              {items.length > 5 || q ? (
                <>
                  <label className="sr-only" htmlFor="q">Поиск проверок</label>
                  <input id="q" className="input" style={{ width: 220 }} placeholder="Найти" value={q} onChange={(e) => setQ(e.target.value)} />
                </>
              ) : null}
              <button type="button" className="quiet-link" onClick={() => setArchived(!archived)}>{archived ? "Назад" : "Архив"}</button>
            </div>
          </div>
          {items.length ? (
            <div className="history-list">
              {items.map((p) => {
                const s = state(p);
                return (
                  <Link className="history-row" href={`/p/${p.id}`} key={p.id}>
                    <span style={{ minWidth: 0 }}>
                      <strong className="clamp-2">{p.name}</strong>
                      <span className="t-caption">{dateTime(p.updated_at)}</span>
                    </span>
                    <span className="history-state">
                      <i className={`history-dot ${s.tone}`} aria-hidden />
                      {s.label}
                    </span>
                  </Link>
                );
              })}
            </div>
          ) : (
            <p className="t-secondary">{q ? "Ничего не нашлось." : "Здесь пусто."}</p>
          )}
        </section>
      ) : null}
    </>
  );
}
