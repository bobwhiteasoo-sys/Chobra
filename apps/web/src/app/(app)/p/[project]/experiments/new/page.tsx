"use client";
import { useQuery } from "@tanstack/react-query";
import { useParams, useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import AdvancedExperiment from "@/components/AdvancedExperiment";
import { Steps } from "@/components/flow/Steps";
import { Button, ErrorState, Loading, Notice } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { count, ruleTitle } from "@/lib/format";
import { useProfiles, useRules, useScenarios } from "@/lib/queries";

const WHO = [
  { id: "incentive_seeking", title: "Ищут выгоду", text: "Хотят максимум награды" },
  { id: "cooperative", title: "Стараются", text: "Хотят принести пользу" },
  { id: "adversarial_search", title: "Ищут лазейки", text: "Специально обходят правило" },
];
const MARKS = ["А", "Б", "В", "Г"];

export default function QuickExperiment() {
  const { project } = useParams<{ project: string }>();
  const router = useRouter();
  const rules = useRules(project);
  const scenarios = useScenarios(project);
  const profiles = useProfiles(project);
  const published = useMemo(() => (rules.data?.items ?? []).filter((r) => r.status === "published").sort((a, b) => a.version - b.version), [rules.data]);
  const [selected, setSelected] = useState<string[] | null>(null);
  const [mode, setMode] = useState("incentive_seeking");
  const [repeats, setRepeats] = useState(3);
  const [advanced, setAdvanced] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const picked = selected ?? published.slice(0, 2).map((r) => r.id);
  const profile = profiles.data?.items.find((p) => p.kind === "scripted" && p.mode === mode);
  const scenario = scenarios.data?.items.filter((s) => s.status === "published").sort((a, b) => b.version - a.version)[0];
  const pickedKey = picked.join(",");
  const body = useMemo(
    () => ({
      project_id: project,
      title: "Проверка правил",
      scenario_version_id: scenario?.id,
      agent_profile_id: profile?.id,
      variants: published.filter((r) => pickedKey.includes(r.id)).map((r) => ({ label: r.name, rule_version_id: r.id })),
      conditions: { seeds: Array.from({ length: Math.max(1, Math.min(20, repeats)) }, (_, i) => 101 + i) },
      limits: { max_wall_time_seconds: 600 },
    }),
    [project, scenario?.id, profile?.id, published, pickedKey, repeats],
  );
  const estimate = useQuery({ queryKey: ["quick-estimate", body], queryFn: () => api<{ planned_runs: number }>("/batches/estimate", { body }), enabled: !!scenario && !!profile && picked.length > 0, retry: false });
  if (rules.isLoading || scenarios.isLoading || profiles.isLoading) return <Loading />;
  const loadError = rules.error ?? scenarios.error ?? profiles.error;
  if (loadError) return <ErrorState error={loadError} />;
  if (advanced)
    return (
      <>
        <button type="button" className="quiet-link" onClick={() => setAdvanced(false)}>Вернуться к простой проверке</button>
        <AdvancedExperiment />
      </>
    );
  const start = async () => {
    setBusy(true);
    setError("");
    try {
      const b = await api<{ batch_id: string }>("/batches", { body, headers: { "Idempotency-Key": crypto.randomUUID() } });
      router.push(`/experiments/${b.batch_id}`);
    } catch (e) {
      setError(errorMessage(e));
      setBusy(false);
    }
  };
  const runs = picked.length * repeats;
  return (
    <section>
      <Steps current={0} />
      <h1 className="pick-title">Какие правила сравним?</h1>
      <p className="lead">Участники попробуют заработать по каждому правилу в одинаковых условиях.</p>
      <fieldset className="pick-list">
        <legend className="sr-only">Правила для сравнения</legend>
        {published.map((r) => {
          const index = picked.indexOf(r.id);
          return (
            <label key={r.id} className="pick">
              <input type="checkbox" checked={index >= 0} onChange={(e) => setSelected(e.target.checked ? [...picked, r.id].slice(0, 4) : picked.filter((id) => id !== r.id))} />
              <span className="pick-mark" aria-hidden>{index >= 0 ? MARKS[index] : "+"}</span>
              <span>
                <strong>{ruleTitle(r.name)}</strong>
                <span className="pick-text">{r.source_text || r.description}</span>
              </span>
            </label>
          );
        })}
      </fieldset>
      <section className="who" aria-labelledby="who-title">
        <h2 id="who-title">Как ведут себя участники</h2>
        <div className="who-options" role="group" aria-labelledby="who-title">
          {WHO.map((w) => (
            <button key={w.id} type="button" className="who-option" aria-pressed={mode === w.id} onClick={() => setMode(w.id)}>
              {w.title}
              <small>{w.text}</small>
            </button>
          ))}
        </div>
      </section>
      {error ? <Notice tone="danger">{error}</Notice> : null}
      {estimate.error ? <Notice tone="danger">{errorMessage(estimate.error)}</Notice> : null}
      <div className="launch-bar">
        <div>
          <strong>{picked.length ? `${count(runs, "прогон", "прогона", "прогонов")}, бесплатно` : "Выберите хотя бы одно правило"}</strong>
          <span>Без ИИ и ключей. Займёт несколько секунд.</span>
        </div>
        <Button variant="primary" className="btn-big" busy={busy} disabled={!picked.length || !estimate.data || estimate.isFetching || repeats < 1 || repeats > 20} onClick={() => void start()}>
          Проверить правила
        </Button>
      </div>
      <details className="advanced" style={{ marginTop: 16 }}>
        <summary>Ещё настройки</summary>
        <div className="stack">
          <label className="field" style={{ maxWidth: 220 }}>
            <span className="label">Повторов на правило</span>
            <input className="input" type="number" min={1} max={20} value={repeats} onChange={(e) => setRepeats(Number(e.target.value))} />
          </label>
          <p className="t-caption" style={{ margin: 0 }}>Каждый повтор — другой набор событий. Для точных выводов нужно от 10 повторов.</p>
          <div><button type="button" className="quiet-link" onClick={() => setAdvanced(true)}>Подробный конструктор и ИИ-участники</button></div>
        </div>
      </details>
    </section>
  );
}
