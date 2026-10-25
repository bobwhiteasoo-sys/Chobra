"use client";

import { useQuery } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { useState } from "react";

import { Button, ErrorState, Loading, Notice, Pill } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { dateTime } from "@/lib/format";
import { useProject } from "@/lib/queries";
import type { Report } from "@/lib/types";

type ReportDetail = Report & {
  snapshot: Record<string, unknown> | null;
  snapshot_summary?: unknown;
  link_expires_in_seconds?: number;
};

const FORMAT: Record<string, string> = { markdown: "Markdown", pdf: "PDF", json: "Пакет JSON", csv: "Таблицы CSV" };
const STATUS: Record<string, { label: string; tone: "neutral" | "info" | "danger" | "success" }> = {
  queued: { label: "В очереди", tone: "info" },
  running: { label: "Формируется", tone: "info" },
  ready: { label: "Готов", tone: "success" },
  failed: { label: "Ошибка", tone: "danger" },
};

function displaySummary(value: unknown): string {
  if (typeof value === "string") return value;
  if (value === null || value === undefined) return "Сводка снимка пока не предоставлена.";
  return JSON.stringify(value, null, 2);
}

export default function ReportDetailPage() {
  const { report: reportId } = useParams<{ report: string }>();
  const [downloadBusy, setDownloadBusy] = useState(false);
  const [expired, setExpired] = useState(false);
  const [downloadError, setDownloadError] = useState("");
  const [linkRefreshed, setLinkRefreshed] = useState(false);
  const report = useQuery({
    queryKey: ["report", reportId],
    queryFn: () => api<ReportDetail>(`/reports/${reportId}`),
    enabled: Boolean(reportId),
    refetchInterval: (query) => query.state.data && ["queued", "running"].includes(query.state.data.status) ? 1500 : false,
  });
  const project = useProject(report.data?.project_id);

  const refreshLink = async () => {
    setExpired(false);
    setDownloadError("");
    setLinkRefreshed(false);
    const result = await report.refetch();
    if (result.data?.download_url) setLinkRefreshed(true);
  };

  const download = async () => {
    const signedPath = report.data?.download_url;
    if (!signedPath || !reportId) return;
    const expectedStart = `/api/v1/reports/${encodeURIComponent(reportId)}/download?`;
    if (!signedPath.startsWith(expectedStart)) {
      setDownloadError("Сервер вернул некорректную ссылку скачивания. Обновите карточку отчета.");
      return;
    }
    setDownloadBusy(true);
    setDownloadError("");
    setExpired(false);
    try {
      // This is the API's same-origin signed path. It already includes /api/v1.
      const response = await fetch(signedPath, { credentials: "same-origin" });
      if (response.status === 410) {
        setExpired(true);
        return;
      }
      if (!response.ok) {
        let message = `Сервер ответил ${response.status}`;
        try {
          const payload = await response.json() as { message?: string };
          if (payload.message) message = payload.message;
        } catch { /* response was not a JSON error */ }
        throw new Error(message);
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      const disposition = response.headers.get("Content-Disposition") ?? "";
      const filename = disposition.match(/filename="?([^";]+)"?/i)?.[1] ?? `chobra-report-${reportId.slice(0, 8)}.${report.data?.format ?? "bin"}`;
      anchor.href = url;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      setLinkRefreshed(false);
    } catch (error) {
      setDownloadError(errorMessage(error));
    } finally {
      setDownloadBusy(false);
    }
  };

  if (report.isLoading) return <Loading lines={6} />;
  if (report.error) return <ErrorState error={report.error} onRetry={() => report.refetch()} />;
  const data = report.data!;
  const status = STATUS[data.status] ?? { label: data.status, tone: "neutral" as const };
  const summary = data.snapshot_summary ?? data.snapshot?.summary;

  return (
    <div className="stack-24" style={{ maxWidth: 1120, margin: "0 auto" }}>
      <header className="page-head">
        <div>
          <div className="crumbs">{project.data?.name ?? "Проект"} · Отчет</div>
          <h1 className="t-page">Отчет</h1>
          <p className="lead">Сохраненный результат для конкретной серии испытаний.</p>
        </div>
        <Pill tone={status.tone}>{status.label}</Pill>
      </header>
      {project.error ? <ErrorState error={project.error} onRetry={() => project.refetch()} /> : null}
      {data.status === "queued" || data.status === "running" ? (
        <Notice title={data.status === "queued" ? "Отчет ожидает обработки" : "Отчет формируется"}>Статус обновляется автоматически. Страница проверяет состояние примерно раз в полторы секунды.</Notice>
      ) : null}
      {data.status === "failed" ? (
        <Notice tone="danger" title="Не удалось сформировать отчет">{data.error || "Сервер не вернул описание ошибки."} Повторная генерация отчета не поддерживается API.</Notice>
      ) : null}
      <section className="panel stack">
        <h2 className="t-panel">Сведения</h2>
        <dl className="kv">
          <dt>Проект</dt><dd>{project.data?.name ?? data.project_id}</dd>
          <dt>Формат</dt><dd>{FORMAT[data.format] ?? data.format}</dd>
          <dt>Создан</dt><dd>{dateTime(data.created_at)}</dd>
          <dt>Серия</dt><dd>{data.batch_id ?? "Не указана"}</dd>
          <dt>Идентификатор отчета</dt><dd className="settings-inline-note">{data.id}</dd>
        </dl>
        {data.status === "ready" && data.download_url ? (
          <div className="stack">
            <div className="settings-actions">
              <Button variant="primary" busy={downloadBusy} onClick={() => void download()}>Скачать отчет</Button>
              {expired ? <Button compact onClick={() => void refreshLink()}>Обновить ссылку</Button> : null}
            </div>
            <p className="t-caption">Ссылка на скачивание действует около {Math.ceil((data.link_expires_in_seconds ?? 300) / 60)} минут. Запрос новой ссылки повторно проверяет доступ к проекту.</p>
            {linkRefreshed ? <p className="t-caption" role="status">Ссылка обновлена. Нажмите «Скачать отчет», чтобы получить файл.</p> : null}
            {expired ? <Notice tone="warn" title="Ссылка истекла">Обновите ссылку и затем нажмите «Скачать отчет» еще раз.</Notice> : null}
            {downloadError ? <Notice tone="danger" title="Не удалось скачать отчет">{downloadError}</Notice> : null}
          </div>
        ) : null}
        {data.status === "ready" && !data.download_url ? <Notice tone="warn">Сервер не предоставил ссылку. Обновите карточку, чтобы запросить актуальный подписанный адрес.</Notice> : null}
      </section>
      {summary !== undefined ? (
        <section className="panel stack">
          <h2 className="t-panel">Сводка снимка</h2>
          <pre className="code" style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", maxHeight: 360 }}>{displaySummary(summary)}</pre>
        </section>
      ) : null}
      <Notice title="Как читать результат">
        Отчет фиксирует данные серии на момент создания. Выводы относятся к указанным сценарию, правилам, среде и настройкам запуска; они сами по себе не доказывают поведение в других условиях или в реальной эксплуатации.
      </Notice>
    </div>
  );
}
