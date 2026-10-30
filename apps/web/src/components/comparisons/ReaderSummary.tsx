"use client";
import type { ReactNode } from "react";
import { ruleTitle } from "@/lib/format";

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
            {action}
    </section>
  );
}

function Card({ name, reward, benefit, benefitTitle, wins }: { name: string; reward?: string; benefit?: string; benefitTitle: string; wins: boolean }) {
  return (
    <article className={`rule-card${wins ? " is-winner" : ""}`}>
      <div className="rule-card-head">
        <h2>{name}</h2>
        {wins ? <span className="rule-card-badge">Лучше</span> : null}
      </div>
      <dl>
        {reward ? <div><dt>Премия</dt><dd className="is-reward">{reward.replace("очк.", "очков")}</dd></div> : null}
        {benefit ? <div><dt>{benefitTitle}</dt><dd className="is-benefit">{benefit}</dd></div> : null}
      </dl>
    </article>
  );
}

export function ReaderSummary({ data, actions }: { data: ReaderData; actions?: ReactNode }) {
  const main = data.metrics[0];
  const reward = data.metrics.find((m) => m.key === "reward_total");
  const benefit = main && main.key !== "reward_total" ? main : undefined;
  return (
    <>
      <VerdictBlock data={data} level="h1" />
      {benefit || reward ? (
        <div className="rule-cards">
          <Card name={ruleTitle(data.baseline ?? "Первое правило")} reward={reward?.baseline_text} benefit={benefit?.baseline_text} benefitTitle={benefit?.title ?? ""} wins={benefit?.effect === "worse"} />
          <Card name={ruleTitle(data.candidate ?? "Второе правило")} reward={reward?.candidate_text} benefit={benefit?.candidate_text} benefitTitle={benefit?.title ?? ""} wins={benefit?.effect === "better"} />
        </div>
      ) : null}
      {actions}
    </>
  );
}
