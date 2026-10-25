"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { useAnnounceWorkspace } from "@/components/Shell";
import { Button, ButtonLink, ErrorState, IdChip, Loading, Notice, Pill, RunStatus, useToast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { count, dateTime, MODE_LABELS, VERDICT } from "@/lib/format";
import { isActive, useBatch, useProject } from "@/lib/queries";
import type { Run } from "@/lib/types";

function runHref(run: Run): string {
  return isActive(run.status) ? `/runs/${run.id}/live` : `/runs/${run.id}/replay`;
}

function Progress({ value, max, label }: { value: number; max: number; label: string }) {
  const pct = max > 0 ? Math.min(100, Math.round((value / max) * 100)) : 0;
  return (
    <div className="progress" role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={max} aria-valuenow={value}>
      <span style={{ width: `${pct}%` }} />
    </div>
  );
}

export default function BatchPage() {
  const { batch: batchId } = useParams<{ batch: string }>();
  const batch = useBatch(batchId);
  const project = useProject(batch.data?.project_id);
  useAnnounceWorkspace(project.data?.workspace_id);
  const queryClient = useQueryClient();
  const toast = useToast();
  const [canceling, setCanceling] = useState(false);

  if (batch.isLoading) return <Loading lines={8} />;
  if (batch.error || !batch.data) return <ErrorState error={batch.error} onRetry={() => batch.refetch()} />;
  const b = batch.data;
  const variants = b.plan.variants;
  const seeds = b.plan.seeds;
  const byCell = new Map(b.runs.map((r) => [`${r.variant_label}|${r.seed}`, r]));
  const active = b.runs.some((r) => isActive(r.status));
  const finished = b.counts.completed + b.counts.incomplete;
  const canRun = project.data?.role && project.data.role !== "viewer";
  const limits = b.budget as { max_model_calls?: number; max_wall_time_seconds?: number };
  const scriptedOnly = variants.every((v) => v.kind === "scripted");

  const cancel = async () => {
    setCanceling(true);
    try {
      await api(`/batches/${b.id}/cancel`, { body: {} });
      await queryClient.invalidateQueries({ queryKey: ["batch", b.id] });
      toast({ title: "Остановка запрошена", body: "Запуски завершат текущий тик и сохранят события до остановки." });
    } catch (err) {
      toast({ title: "Не удалось остановить серию", body: errorMessage(err), tone: "danger" });
    }
    setCanceling(false);
  };

  return (
    <>
      <nav className="crumbs" aria-label="Путь">
        {project.data ? (
          <>
            <Link href={`/w/${project.data.workspace_id}/projects`}>Проекты</Link>
            <span aria-hidden>/</span>
            <Link href={`/p/${project.data.id}/experiments`}>{project.data.name}</Link>
            <span aria-hidden>/</span>
          </>
        ) : null}
        <span>Серия</span>
      </nav>
      <header className="page-head">
        <div style={{ minWidth: 0 }}>
          <h1 className="t-page clamp-2">{b.title}</h1>
          <div className="row" style={{ gap: 8, marginTop: 8 }}>
            <RunStatus status={b.status} />
            <IdChip value={b.plan_hash} label="план" />
            <span className="t-caption">{dateTime(b.created_at)}</span>
          </div>
        </div>
        <div className="row">
          {b.comparison_id ? (
            <ButtonLink href={`/comparisons/${b.comparison_id}`} variant="primary">
              Открыть сравнение
            </ButtonLink>
          ) : null}
          {active && canRun ? (
            <Button variant="danger" busy={canceling} onClick={cancel}>
              Остановить серию
            </Button>
          ) : null}
        </div>
      </header>

      <div className="grid-3" style={{ marginBottom: 24 }}>
        <section className="panel stack" style={{ gap: 8 }}>
          <span className="t-caption">Выполнение</span>
          <span className="t-value">
            {finished} из {b.counts.planned}
          </span>
          <Progress value={finished} max={b.counts.planned} label="Завершено запусков" />
          <span className="t-caption">
            {count(b.counts.completed, "завершен", "завершено", "завершено")}
            {b.counts.incomplete ? `, ${count(b.counts.incomplete, "неполный", "неполных", "неполных")}` : ""}
            {b.counts.in_progress ? `, ${b.counts.in_progress} выполняется` : ""}
          </span>
        </section>
        <section className="panel stack" style={{ gap: 8 }}>
          <span className="t-caption">Вызовы модели</span>
          {scriptedOnly ? (
            <>
              <span className="t-value">0</span>
              <span className="t-caption">Сценарные агенты не обращаются к провайдеру</span>
            </>
          ) : (
            <>
              <span className="t-value">
                {(b.budget_used.calls ?? 0).toLocaleString("ru-RU")} из {(limits.max_model_calls ?? 0).toLocaleString("ru-RU")}
              </span>
              <Progress value={b.budget_used.calls ?? 0} max={limits.max_model_calls ?? 0} label="Использовано вызовов" />
              <span className="t-caption">
                Токенов: {(b.budget_used.input_tokens ?? 0).toLocaleString("ru-RU")} ввод, {(b.budget_used.output_tokens ?? 0).toLocaleString("ru-RU")} вывод
                {b.budget_used.unknown_usage_calls ? `; ${b.budget_used.unknown_usage_calls} с неизвестным использованием, ожидают сверки` : ""}
              </span>
            </>
          )}
        </section>
        <section className="panel stack" style={{ gap: 8 }}>
          <span className="t-caption">Условия</span>
          <span className="t-secondary">
            {count(variants.length, "вариант", "варианта", "вариантов")}, {count(seeds.length, "seed", "seed", "seed")}, горизонт {String(b.plan.horizon_ticks)} + {String(b.plan.observation_tail_ticks)} тиков
          </span>
          <span className="t-caption">Одна внешняя лента событий на каждый seed для всех вариантов. План неизменяем после старта.</span>
        </section>
      </div>

      {b.status === "completed_with_incomplete" ? (
        <div style={{ marginBottom: 16 }}>
          <Notice tone="warn">Часть запусков не завершилась. Сравнение использует только полные пары; неполные запуски перечислены в нем отдельно и не считаются запусками без нарушений.</Notice>
        </div>
      ) : null}

      <section className="panel" style={{ padding: 0 }}>
        <div className="panel-head" style={{ padding: "16px 20px 0" }}>
          <h2 className="t-panel">Запуски по парам</h2>
          <span className="t-caption">Строка — seed, столбец — вариант правила</span>
        </div>
        <div className="table-wrap">
          <table className="table run-grid">
            <thead>
              <tr>
                <th>Seed</th>
                {variants.map((v) => (
                  <th key={v.label}>
                    <div>{v.label}</div>
                    <div className="t-caption" style={{ fontWeight: 400 }}>
                      {MODE_LABELS[v.mode] ?? v.mode}, {v.kind === "model" ? "модель" : "сценарный"}
                    </div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {seeds.map((seed) => (
                <tr key={seed}>
                  <td className="num t-secondary">{seed}</td>
                  {variants.map((v) => {
                    const run = byCell.get(`${v.label}|${seed}`);
                    if (!run) return <td key={v.label}>—</td>;
                    const verdict = run.verdict ? VERDICT[run.verdict] : null;
                    const total = run.horizon_ticks + run.tail_ticks;
                    return (
                      <td key={v.label}>
                        <Link href={runHref(run)} className="run-cell" aria-label={`Запуск ${v.label}, seed ${seed}`}>
                          <span className="row" style={{ gap: 6 }}>
                            <RunStatus status={run.status} />
                            {verdict ? <Pill tone={verdict.tone}>{verdict.label}</Pill> : null}
                          </span>
                          {isActive(run.status) ? (
                            <>
                              <Progress value={Math.max(0, run.current_tick)} max={total} label="Тик" />
                              <span className="t-caption num">
                                тик {Math.max(0, run.current_tick)} из {total}
                              </span>
                            </>
                          ) : run.stop_reason && run.status !== "completed" ? (
                            <span className="t-caption">{run.stop_reason}</span>
                          ) : null}
                        </Link>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      {!b.comparison_id && !active && finished === b.counts.planned ? (
        <p className="t-caption" style={{ marginTop: 12 }}>
          Сравнение рассчитывается после аудита всех запусков.
        </p>
      ) : null}
    </>
  );
}
