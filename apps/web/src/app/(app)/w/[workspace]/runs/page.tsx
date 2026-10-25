"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";

import { EmptyState, ErrorState, Loading, RunStatus, Verdict } from "@/components/ui";
import { api } from "@/lib/api";
import { dateTime, MODE_LABELS } from "@/lib/format";
import type { Run } from "@/lib/types";

export default function WorkspaceRunsPage() {
  const { workspace } = useParams<{ workspace: string }>();
  const router = useRouter();
  const runs = useQuery({
    queryKey: ["workspace-runs", workspace],
    queryFn: () => api<{ items: (Run & { project_name: string })[] }>(`/workspaces/${workspace}/runs?limit=100`),
    refetchInterval: 4000,
  });
  return (
    <>
      <header className="page-head">
        <div>
          <h1 className="t-page">Испытания</h1>
          <p className="lead">Запуски всех проектов пространства. Откройте запуск, чтобы смотреть арену вживую или воспроизвести события.</p>
        </div>
      </header>
      {runs.isLoading ? (
        <Loading lines={6} />
      ) : runs.error ? (
        <ErrorState error={runs.error} />
      ) : !runs.data?.items.length ? (
        <EmptyState title="Испытаний пока не было">Запустите серию из проекта: вкладка «Испытания», кнопка «Новое испытание».</EmptyState>
      ) : (
        <div className="panel" style={{ padding: 0 }}>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Проект и вариант</th>
                  <th>Режим</th>
                  <th className="r">Seed</th>
                  <th className="r">Тик</th>
                  <th>Состояние</th>
                  <th>Вывод проверки</th>
                  <th>Начат</th>
                </tr>
              </thead>
              <tbody>
                {runs.data.items.map((r) => (
                  <tr key={r.id} data-link onClick={() => router.push(`/runs/${r.id}/live`)}>
                    <td>
                      <Link href={`/runs/${r.id}/live`} onClick={(e) => e.stopPropagation()} style={{ fontWeight: 600 }}>
                        {r.project_name}
                      </Link>
                      <div className="t-caption">{r.variant_label}</div>
                    </td>
                    <td>
                      {MODE_LABELS[r.agent_mode] ?? r.agent_mode}
                      <div className="t-caption">{r.agent_kind === "model" ? "Модель" : "Сценарный агент"}</div>
                    </td>
                    <td className="r">{r.seed}</td>
                    <td className="r">
                      {Math.max(r.current_tick, 0)} из {r.horizon_ticks + r.tail_ticks}
                    </td>
                    <td>
                      <RunStatus status={r.status} />
                    </td>
                    <td>{r.status === "completed" || r.verdict ? <Verdict verdict={r.verdict} /> : <span className="t-muted">После аудита</span>}</td>
                    <td className="t-secondary num">{dateTime(r.started_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  );
}
