"use client";

import { useQueries } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";

import { EmptyState, Loading, Pill } from "@/components/ui";
import { api } from "@/lib/api";
import { dateTime } from "@/lib/format";
import { useProjects } from "@/lib/queries";
import type { Report } from "@/lib/types";

const FORMAT: Record<string, string> = { markdown: "Markdown", pdf: "PDF", json: "Пакет JSON", csv: "Таблицы CSV" };

export default function ReportsPage() {
  const { workspace } = useParams<{ workspace: string }>();
  const projects = useProjects(workspace, {});
  const reports = useQueries({
    queries: (projects.data?.items ?? []).map((p) => ({
      queryKey: ["project-reports", p.id],
      queryFn: () => api<{ items: Report[] }>(`/projects/${p.id}/reports`),
    })),
  });
  const loading = projects.isLoading || reports.some((r) => r.isLoading);
  const rows = (projects.data?.items ?? []).flatMap((p, i) => (reports[i]?.data?.items ?? []).map((r) => ({ ...r, projectName: p.name })));
  rows.sort((a, b) => b.created_at.localeCompare(a.created_at));
  return (
    <>
      <header className="page-head">
        <div>
          <h1 className="t-page">Отчеты</h1>
          <p className="lead">Каждый отчет хранит снимок результатов на момент формирования. Новая серия не подменяет его значения.</p>
        </div>
      </header>
      {loading ? (
        <Loading lines={5} />
      ) : !rows.length ? (
        <EmptyState title="Отчетов пока нет">Сформируйте отчет со страницы сравнения или серии испытаний.</EmptyState>
      ) : (
        <div className="panel" style={{ padding: 0 }}>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Проект</th>
                  <th>Формат</th>
                  <th>Состояние</th>
                  <th>Создан</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id}>
                    <td>
                      <Link href={`/reports/${r.id}`} style={{ fontWeight: 600 }}>
                        {r.projectName}
                      </Link>
                    </td>
                    <td>{FORMAT[r.format] ?? r.format}</td>
                    <td>{r.status === "ready" ? <Pill tone="success">Готов</Pill> : r.status === "failed" ? <Pill tone="danger">Ошибка</Pill> : <Pill tone="info">Формируется</Pill>}</td>
                    <td className="t-secondary num">{dateTime(r.created_at)}</td>
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
