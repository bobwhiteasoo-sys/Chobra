"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";

import { ButtonLink, EmptyState, ErrorState, Loading, Pill, RunStatus } from "@/components/ui";
import { api } from "@/lib/api";
import { count, dateTime, MODE_LABELS } from "@/lib/format";
import { useProject } from "@/lib/queries";
import type { BatchBrief } from "@/lib/types";

export default function ExperimentsPage() {
  const { project: projectId } = useParams<{ project: string }>();
  const project = useProject(projectId);
  const router = useRouter();
  const batches = useQuery({
    queryKey: ["batches", projectId],
    queryFn: () => api<{ items: BatchBrief[] }>(`/projects/${projectId}/batches`),
    refetchInterval: (query) => (query.state.data?.items.some((b) => ["queued", "running"].includes(b.status)) ? 3000 : false),
  });
  if (batches.isLoading) return <Loading lines={6} />;
  if (batches.error) return <ErrorState error={batches.error} onRetry={() => batches.refetch()} />;
  const items = batches.data!.items;
  const canRun = project.data?.role !== "viewer";
  if (!items.length)
    return (
      <EmptyState
        title="Испытаний пока не было"
        action={canRun ? <ButtonLink href={`/p/${projectId}/experiments/new`} variant="primary">Новое испытание</ButtonLink> : undefined}
      >
        Серия запускает варианты правил на одних и тех же seed и внешней ленте событий, чтобы сравнение было парным.
      </EmptyState>
    );
  return (
    <div className="panel" style={{ padding: 0 }}>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Серия</th>
              <th>Режим агентов</th>
              <th className="r">Запусков</th>
              <th>Состояние</th>
              <th>Создана</th>
            </tr>
          </thead>
          <tbody>
            {items.map((b) => (
              <tr key={b.id} data-link onClick={() => router.push(`/experiments/${b.id}`)}>
                <td>
                  <Link href={`/experiments/${b.id}`} onClick={(e) => e.stopPropagation()} style={{ fontWeight: 600 }}>
                    {b.title}
                  </Link>
                </td>
                <td>
                  <div className="row" style={{ gap: 6 }}>
                    {b.modes.map((m) => (
                      <Pill key={m}>{MODE_LABELS[m] ?? m}</Pill>
                    ))}
                  </div>
                </td>
                <td className="r num">{count(b.planned_runs, "запуск", "запуска", "запусков")}</td>
                <td>
                  <RunStatus status={b.status} />
                </td>
                <td className="t-secondary num">{dateTime(b.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
