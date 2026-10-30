"use client";
import type { ReactNode } from "react";
import { plainText, ruleTitle } from "@/lib/format";

type Brief = { heading: string; context: string; conclusion: string; tested: string; outcome: string; concern: string; next_step: string };
export type ReaderData = { title: string; description: string; baseline?: string; candidate?: string; pairs: number; next_step: string; limits: string[]; brief?: Brief; metrics: { key: string; title: string; unit: string; baseline: number; candidate: number; baseline_text: string; candidate_text: string; change: string; effect: string; pairs: number }[] };

function tone(data: ReaderData): string {
  const effects = data.metrics.map((m) => m.effect);
  if (effects.includes("better") && effects.includes("worse")) return "mixed";
  if (data.metrics[0]?.effect === "better") return "good";
  if (data.metrics[0]?.effect === "worse") return "bad";
  return "mixed";
}

/** The answer first, at the size of an answer. Colour follows the verdict, not decoration. */
export function VerdictBlock({ data, action, level = "h2" }: { data: ReaderData; action?: ReactNode; level?: "h1" | "h2" }) {
  const Heading = level;
  const brief = data.brief;
  return (
    <section className={`verdict verdict-${tone(data)}`} aria-label="Краткий итог проверки">
      <Heading className="verdict-title">{brief?.conclusion ?? data.title}</Heading>
      <p className="verdict-outcome">{plainText(brief?.outcome ?? data.description)}</p>
      {action}
    </section>
  );
}

export function ReaderSummary({ data, actions }: { data: ReaderData; actions?: ReactNode }) {
  const brief = data.brief;
  const a = ruleTitle(data.baseline ?? "Первое правило");
  const b = ruleTitle(data.candidate ?? "Второе правило");
  return (
    <>
      <VerdictBlock data={data} level="h1" />
      {data.metrics.length ? (
        <section className="duel" aria-label="Сравнение правил в цифрах">
          <div className="duel-legend">
            <span><i className="mark-a">А</i>{a}</span>
            <span><i className="mark-b">Б</i>{b}</span>
          </div>
          {data.metrics.map((m) => {
            const max = Math.max(m.baseline, m.candidate, 1);
            const reward = m.key === "reward_total";
            return (
              <article className="duel-metric" key={m.key}>
                <div className="duel-head">
                  <h2>{reward ? "Начислено награды" : m.title}</h2>
                  <span className={`duel-change is-${m.effect}`}>{m.change.replace("п.п.", "пунктов")}</span>
                </div>
                <div className="duel-row">
                  <i className="mark-a" aria-hidden>А</i>
                  <div className="duel-track"><div className="duel-bar is-a" style={{ width: `${Math.max(1.5, (m.baseline / max) * 100)}%` }} /></div>
                  <strong>{m.baseline_text}</strong>
                </div>
                <div className="duel-row">
                  <i className="mark-b" aria-hidden>Б</i>
                  <div className="duel-track"><div className={`duel-bar ${reward ? "is-reward" : "is-benefit"}`} style={{ width: `${Math.max(1.5, (m.candidate / max) * 100)}%` }} /></div>
                  <strong>{m.candidate_text}</strong>
                </div>
              </article>
            );
          })}
        </section>
      ) : null}
      {brief?.next_step ? <p className="next-step"><strong>Что дальше.</strong> {plainText(brief.next_step)}</p> : null}
      {actions}
      {data.limits.length ? (
        <details className="advanced">
          <summary>Насколько можно доверять выводу</summary>
          {data.limits.map((s) => <p key={s} className="t-secondary">{s}</p>)}
        </details>
      ) : null}
    </>
  );
}
