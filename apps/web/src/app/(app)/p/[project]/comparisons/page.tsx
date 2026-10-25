"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ButtonLink, EmptyState, ErrorState, Loading, Pill } from "@/components/ui";
import { api } from "@/lib/api";
import { dateTime, MODE_LABELS } from "@/lib/format";
import type { Comparison } from "@/lib/types";
import "@/styles/comparisons.css";

type ComparisonListItem = Pick<Comparison,"id"|"batch_id"|"result"|"completeness"|"decision"> & { created_at: string; batch_title: string };
export default function ProjectComparisonsPage() {
  const { project } = useParams<{project:string}>();
  const query = useQuery({queryKey:["project-comparisons",project],queryFn:() => api<{items:ComparisonListItem[]}>(`/projects/${project}/comparisons`)});
  if(query.isLoading) return <Loading lines={6}/>;
  if(query.error || !query.data) return <ErrorState error={query.error} onRetry={() => query.refetch()}/>;
  if(!query.data.items.length) return <EmptyState title="Сравнений пока нет" action={<ButtonLink variant="primary" href={`/p/${project}/experiments/new`}>Новое испытание</ButtonLink>}>После завершения серии здесь появятся результаты вариантов на одинаковых seed.</EmptyState>;
  return <div className="analysis-page stack"><p className="t-secondary">Сравнения сохраненных серий. Режимы агентов анализируются раздельно.</p><div className="panel"><div className="table-wrap" tabIndex={0} role="region" aria-label="Сравнения проекта, горизонтальная прокрутка"><table className="table"><thead><tr><th>Серия и варианты</th><th>Режимы</th><th className="r">Завершено / план</th><th className="r">Неполных</th><th>Решение</th><th>Создано</th></tr></thead><tbody>{query.data.items.map((c) => <tr key={c.id}><td><Link className="t-panel" href={`/comparisons/${c.id}`}>{c.batch_title || "Сравнение серии"}</Link><p className="t-caption">{c.result.variants.join(" / ")}</p><Link className="t-caption" href={`/experiments/${c.batch_id}`}>План испытания</Link></td><td><div className="row">{Array.from(new Set(c.result.pairs.map((p) => p.mode))).map((mode) => <Pill key={mode}>{MODE_LABELS[mode] ?? mode}</Pill>)}</div>{c.result.single_variant ? <Pill>Один вариант</Pill> : null}</td><td className="r">{c.completeness.completed ?? "—"} / {c.completeness.planned ?? "—"}</td><td className="r">{c.completeness.incomplete ?? "—"}</td><td>{c.decision?.accepted_variant ?? "Не записано"}</td><td className="t-caption">{dateTime(c.created_at)}</td></tr>)}</tbody></table></div></div><p className="t-caption">Показаны последние 100 сравнений проекта.</p></div>;
}
