"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Loader2 } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useDeferredValue, useState } from "react";

import { useCurrentWorkspace } from "@/components/Shell";
import { ErrorState, Loading, Notice } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { dateTime, SITUATIONS } from "@/lib/format";
import { isActive, useMe, useProjects } from "@/lib/queries";
import type { Project } from "@/lib/types";

function state(project: Project): { label: string; tone: string } {
  const status = project.last_batch?.status;
  if (!status) return { label: "Ещё не проверяли", tone: "" };
  if (isActive(status)) return { label: "Идёт проверка", tone: "is-active" };
  return { label: "Есть итог", tone: "is-done" };
}

export default function HomePage() {
  const { workspace } = useParams<{ workspace: string }>();
  const { workspaceId } = useCurrentWorkspace();
  const id = workspace ?? workspaceId ?? undefined;
  const me = useMe();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [q, setQ] = useState("");
  const [archived, setArchived] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const projects = useProjects(id, { q: useDeferredValue(q), archived });
  const role = me.data?.workspaces.find((w) => w.id === id)?.role;
  const canCreate = role !== "viewer";

  const start = async (situation: (typeof SITUATIONS)[number]) => {
    setBusy(situation.id);
    setError(null);
    try {
      const project = await api<Project>("/projects", { body: { workspace_id: id, name: situation.title, environment_id: situation.id } });
      await queryClient.invalidateQueries({ queryKey: ["projects"] });
      router.push(`/p/${project.id}/experiments/new`);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(null);
    }
  };

  const items = projects.data?.items ?? [];
  return (
    <>
      <h1 className="home-title">Что проверим?</h1>
      <p className="lead">Выберите ситуацию. Участники, задачи и правила уже готовы: останется нажать одну кнопку.</p>
      {error ? <Notice tone="danger">{error}</Notice> : null}
      {canCreate ? (
        <ul className="situations">
          {SITUATIONS.map((s) => (
            <li key={s.id}>
              <button type="button" className="situation" aria-busy={busy === s.id} disabled={Boolean(busy)} onClick={() => void start(s)}>
                <span>
                  <span className="situation-title">{s.title}</span>
                  <span className="situation-text">{s.text}</span>
                </span>
                <span className="situation-go" aria-hidden>
                  {busy === s.id ? <Loader2 size={22} className="spin" /> : <ArrowRight size={22} />}
                </span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}

      {projects.isLoading ? <Loading lines={3} /> : projects.error ? <ErrorState error={projects.error} onRetry={() => projects.refetch()} /> : items.length || q || archived ? (
        <section aria-labelledby="history-title">
          <div className="history-head">
            <h2 className="t-section" id="history-title">{archived ? "Архив" : "Ваши проверки"}</h2>
            <div className="row" style={{ gap: 8 }}>
              {items.length > 5 || q ? (
                <>
                  <label className="sr-only" htmlFor="q">Поиск проверок</label>
                  <input id="q" className="input" style={{ width: 220 }} placeholder="Найти" value={q} onChange={(e) => setQ(e.target.value)} />
                </>
              ) : null}
              <button type="button" className="quiet-link" onClick={() => setArchived(!archived)}>{archived ? "Активные" : "Архив"}</button>
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
            <p className="t-secondary">{q ? "Ничего не нашлось. Попробуйте другое слово." : "Здесь пусто."}</p>
          )}
        </section>
      ) : null}
    </>
  );
}
