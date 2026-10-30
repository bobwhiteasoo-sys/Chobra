"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Check, OctagonAlert } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { Steps } from "@/components/flow/Steps";
import { useAnnounceWorkspace } from "@/components/Shell";
import { Button, ButtonLink, ErrorState, Loading, Notice, useToast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { count, ruleTitle } from "@/lib/format";
import { isActive, useBatch, useProject } from "@/lib/queries";
import type { Run } from "@/lib/types";

function RunChip({ run, index }: { run: Run; index: number }) {
  const active = isActive(run.status);
  const total = run.horizon_ticks + run.tail_ticks;
  const found = run.verdict === "observed_violation";
  const clean = run.verdict === "no_violation_observed";
  const state = active ? "идёт" : found ? "нашлась лазейка" : clean ? "лазеек нет" : "без вывода";
  return (
    <Link href={active ? `/runs/${run.id}/live` : `/runs/${run.id}/replay`} className={`lane-run${found ? " is-found" : clean ? " is-clean" : active ? "" : " is-stopped"}`} aria-label={`Прогон ${index + 1}: ${state}`} title={state}>
      {active ? <span className="lane-fill" style={{ width: `${(Math.max(0, run.current_tick) / Math.max(1, total)) * 100}%` }} /> : null}
      {found ? <OctagonAlert size={15} aria-hidden /> : clean ? <Check size={15} aria-hidden /> : null}
      <span>{index + 1}</span>
    </Link>
  );
}

export default function BatchPage() {
  const { batch: batchId } = useParams<{ batch: string }>();
  const batch = useBatch(batchId);
  const project = useProject(batch.data?.project_id);
  useAnnounceWorkspace(project.data?.workspace_id);
  const queryClient = useQueryClient();
  const toast = useToast();
  const router = useRouter();
  const [canceling, setCanceling] = useState(false);
  const watching = useRef(false);
  const active = Boolean(batch.data?.runs.some((r) => isActive(r.status)));
  const comparisonId = batch.data?.comparison_id;

  // Someone who watched the check finish wants the answer, not this screen.
  useEffect(() => {
    if (active) watching.current = true;
    if (watching.current && comparisonId) router.replace(`/comparisons/${comparisonId}`);
  }, [active, comparisonId, router]);

  if (batch.isLoading) return <Loading lines={8} />;
  if (batch.error || !batch.data) return <ErrorState error={batch.error} onRetry={() => batch.refetch()} />;
  const b = batch.data;
  const variants = b.plan.variants;
  const finished = b.counts.completed + b.counts.incomplete;
  const canRun = project.data?.role && project.data.role !== "viewer";
  const limits = b.budget as { max_model_calls?: number };
  const scriptedOnly = variants.every((v) => v.kind === "scripted");
  const percent = b.counts.planned ? Math.round((finished / b.counts.planned) * 100) : 0;

  const cancel = async () => {
    setCanceling(true);
    try {
      await api(`/batches/${b.id}/cancel`, { body: {} });
      await queryClient.invalidateQueries({ queryKey: ["batch", b.id] });
      toast({ title: "Останавливаем", body: "Всё, что уже случилось, сохранится." });
    } catch (err) {
      toast({ title: "Не удалось остановить", body: errorMessage(err), tone: "danger" });
    }
    setCanceling(false);
  };

  return (
    <>
      <Link className="back-link" href={`/p/${b.project_id}`}>
        <ArrowLeft size={16} aria-hidden /> {project.data?.name ?? "К проекту"}
      </Link>
      <Steps current={comparisonId ? 2 : 1} />
      <h1 className="running-title">{b.title}</h1>
      <p className="lead" role="status">
        {active ? "Участники пробуют заработать по вашим правилам. Можно подождать здесь: итог откроется сам." : comparisonId ? "Проверка закончена, итог готов." : finished < b.counts.planned ? "Прогоны стоят в очереди." : "Считаем итог."}
      </p>
      <div className="running-meter" role="progressbar" aria-label="Завершено прогонов" aria-valuemin={0} aria-valuemax={b.counts.planned} aria-valuenow={finished}>
        <span style={{ width: `${percent}%` }} />
      </div>
      <p className="t-caption num" style={{ margin: 0 }}>
        {finished} из {count(b.counts.planned, "прогона", "прогонов", "прогонов")}
        {b.counts.incomplete ? `, не завершено: ${b.counts.incomplete}` : ""}
      </p>
      <div className="result-actions">
        {comparisonId ? <ButtonLink variant="primary" href={`/comparisons/${comparisonId}`}>Открыть итог</ButtonLink> : null}
        {active && canRun ? <Button variant="danger" busy={canceling} onClick={cancel}>Остановить</Button> : null}
      </div>
      {b.status === "completed_with_incomplete" ? <Notice tone="warn">Часть прогонов не завершилась. В итог вошли только полные пары.</Notice> : null}
      {!scriptedOnly ? (
        <p className="t-caption">
          Вызовы модели: {(b.budget_used.calls ?? 0).toLocaleString("ru-RU")} из {(limits.max_model_calls ?? 0).toLocaleString("ru-RU")}. Токены: {(b.budget_used.input_tokens ?? 0).toLocaleString("ru-RU")} ввод, {(b.budget_used.output_tokens ?? 0).toLocaleString("ru-RU")} вывод.
          {b.budget_used.unknown_usage_calls ? ` С неизвестным расходом: ${b.budget_used.unknown_usage_calls}.` : ""}
        </p>
      ) : null}
      <div className="lanes">
        {variants.map((v) => (
          <section className="lane" key={v.label}>
            <h2>{ruleTitle(v.label)}</h2>
            <div className="lane-runs">
              {b.runs.filter((r) => r.variant_label === v.label).sort((x, y) => x.seed - y.seed).map((run, index) => <RunChip key={run.id} run={run} index={index} />)}
            </div>
          </section>
        ))}
      </div>
      <p className="lane-legend">
        <span><OctagonAlert size={14} aria-hidden /> нашлась лазейка</span>
        <span><Check size={14} aria-hidden /> лазеек нет</span>
        <span>Нажмите на прогон, чтобы посмотреть, что в нём случилось</span>
      </p>
    </>
  );
}
