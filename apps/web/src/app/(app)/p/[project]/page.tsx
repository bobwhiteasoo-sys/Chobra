"use client";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect } from "react";
import { Loading, RunStatus } from "@/components/ui";
import { VerdictBlock } from "@/components/comparisons/ReaderSummary";
import { dateTime, plainText } from "@/lib/format";
import { useComparison, useProject } from "@/lib/queries";
import type { Comparison } from "@/lib/types";
import type { ReaderData } from "@/components/comparisons/ReaderSummary";

export default function ProjectOverview() {
  const { project: id } = useParams<{ project: string }>();
  const router = useRouter();
  const { data: p } = useProject(id);
  const comparison = useComparison(p?.last_comparison?.id);
  // A project with no checks has nothing to overview: go straight to the first check.
  useEffect(() => {
    if (p && !p.last_batch && p.role !== "viewer" && !p.archived_at) router.replace(`/p/${id}/experiments/new`);
  }, [p, id, router]);
  if (!p) return null;
  if (!p.last_batch && p.role !== "viewer" && !p.archived_at) return <Loading />;
  const summary = (comparison.data as (Comparison & { reader_summaries?: ReaderData[] }) | undefined)?.reader_summaries?.[0];
  const findings = Array.from(new Map((p.findings ?? []).map((f) => [f.check_id, f])).values()).slice(0, 3);
  return (
    <>
      <h1 className="project-question">{p.name}</h1>
      <p className="project-want">{p.research_question}</p>
      {summary && p.last_comparison ? (
        <VerdictBlock data={summary} action={<Link className="verdict-link" href={`/comparisons/${p.last_comparison.id}`}>Открыть итог</Link>} />
      ) : p.last_batch ? (
        <div className="row"><RunStatus status={p.last_batch.status} /><Link className="btn btn-secondary btn-compact" href={`/experiments/${p.last_batch.id}`}>Открыть проверку</Link></div>
      ) : (
        <p className="t-secondary">Проверок пока не было.</p>
      )}
      {findings.length ? (
        <section className="section-gap">
          <h2 className="t-section" style={{ marginBottom: 12 }}>Найденные лазейки</h2>
          <div className="history-list">
            {findings.map((f) => (
              <Link key={f.id} className="history-row" href={`/findings/${f.id}`}>
                <span style={{ minWidth: 0 }}>
                  <strong>{plainText(f.title)}</strong>
                  <span className="t-caption clamp-2">{plainText(f.explanation)}</span>
                </span>
              </Link>
            ))}
          </div>
        </section>
      ) : null}
      {(p.batches?.length ?? 0) > 1 ? (
        <section className="section-gap">
          <h2 className="t-section" style={{ marginBottom: 12 }}>Прошлые проверки</h2>
          <div className="history-list">
            {p.batches!.slice(0, 6).map((b) => (
              <Link key={b.id} className="history-row" href={`/experiments/${b.id}`}>
                <span>{dateTime(b.created_at)}</span>
                <RunStatus status={b.status} />
              </Link>
            ))}
          </div>
        </section>
      ) : null}
      <p className="t-caption section-gap">Проверка идёт в симуляции. Она помогает найти лазейки, но не предсказывает поведение конкретных людей.</p>
    </>
  );
}
