"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button, Notice } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";

export function ReportAction({ projectId, batchId, label = "Создать отчет" }: { projectId: string; batchId: string; label?: string }) {
  const router = useRouter();
  const [format, setFormat] = useState("pdf");
  const [raw, setRaw] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  return <form className="stack" onSubmit={async (e) => {
    e.preventDefault(); setBusy(true); setError("");
    try { const report = await api<{ id: string }>("/reports", { body: { project_id: projectId, batch_id: batchId, format, include_raw_model_io: raw } }); router.push(`/reports/${report.id}`); }
    catch (err) { setError(errorMessage(err)); setBusy(false); }
  }}>
    <div className="field"><label htmlFor="report-format">Формат отчета</label><select id="report-format" className="select" value={format} onChange={(e) => setFormat(e.target.value)}><option value="pdf">PDF</option><option value="markdown">Markdown</option><option value="json">JSON · переносимый пакет</option><option value="csv">CSV</option></select></div>
    <label className="check"><input type="checkbox" checked={raw} onChange={(e) => setRaw(e.target.checked)} />Включить исходные запросы и ответы моделей</label>
    <p className="t-caption">Отчет включает данные серии, находки и ограничения анализа. Исходные ответы могут содержать чувствительные данные.</p>
    {error ? <Notice tone="danger">{error}</Notice> : null}
    <Button variant="primary" type="submit" busy={busy}>{label}</Button>
  </form>;
}
