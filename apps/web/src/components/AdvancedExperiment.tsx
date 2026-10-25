"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Loader2, Plus, Trash2 } from "lucide-react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";

import { Button, ErrorState, Loading, Notice, Pill } from "@/components/ui";
import { api, ApiError, errorMessage } from "@/lib/api";
import { count, MODE_LABELS, plural } from "@/lib/format";
import { useEnvironment, useProfiles, useProject, useRules, useScenarios } from "@/lib/queries";

type Variant = { label: string; rule_version_id: string; agent_profile_id: string };
type Estimate = {
  planned_runs: number;
  actor_count: number;
  horizon_ticks: number;
  observation_tail_ticks: number;
  seeds: number[];
  checks: string[];
  variants: { label: string; mode: string; kind: string; model: string }[];
  limits: { max_model_calls: number; max_output_tokens_per_call: number; max_wall_time_seconds: number; money_limit_microusd: number | null };
  estimate: {
    agent_decisions: number;
    model_calls_upper_bound: number;
    model_calls_reserved: number;
    money_upper_bound_microusd: number | null;
    price: { model: string; input_usd_per_mtok: string; output_usd_per_mtok: string; currency: string; source: string; as_of: string } | null;
    scripted_only: boolean;
  };
  differences: string[];
};

function usd(micro: number | null | undefined): string {
  if (micro === null || micro === undefined) return "—";
  return `$${(micro / 1_000_000).toFixed(2)}`;
}

function newKey(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
}

function NewExperiment() {
  const { project: projectId } = useParams<{ project: string }>();
  const search = useSearchParams();
  const router = useRouter();
  const project = useProject(projectId);
  const env = useEnvironment(project.data?.environment_id);
  const scenarios = useScenarios(projectId);
  const rules = useRules(projectId);
  const profiles = useProfiles(projectId);

  const [title, setTitle] = useState("");
  const [scenarioId, setScenarioId] = useState("");
  const [variants, setVariants] = useState<Variant[]>([]);
  const [repeats, setRepeats] = useState(3);
  const [baseSeed, setBaseSeed] = useState(101);
  const [horizon, setHorizon] = useState<string>("");
  const [tail, setTail] = useState<string>("");
  const [checks, setChecks] = useState<string[] | null>(null);
  const [maxCalls, setMaxCalls] = useState("");
  const [maxOutput, setMaxOutput] = useState("512");
  const [wallMinutes, setWallMinutes] = useState("30");
  const [moneyUsd, setMoneyUsd] = useState("");
  const [failurePolicy, setFailurePolicy] = useState<"wait" | "stop">("wait");
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);
  const initialized = useRef(false);

  const published = useMemo(() => (rules.data?.items ?? []).filter((r) => r.status === "published"), [rules.data]);
  const publishedScenarios = useMemo(() => (scenarios.data?.items ?? []).filter((s) => s.status === "published").sort((a, b) => b.version - a.version), [scenarios.data]);
  const profileList = profiles.data?.items ?? [];

  useEffect(() => {
    if (initialized.current || !published.length || !publishedScenarios.length || !profileList.length || !env.data) return;
    initialized.current = true;
    setScenarioId(publishedScenarios[0]!.id);
    const requestedSeed = Number(search.get("seed"));
    if (search.has("seed") && Number.isSafeInteger(requestedSeed) && requestedSeed >= 0) setBaseSeed(requestedSeed);
    const seeking = profileList.find((p) => p.mode === "incentive_seeking" && p.kind === "scripted") ?? profileList[0]!;
    const templates = published.filter((r) => r.template_key).sort((a, b) => String(a.template_key).localeCompare(String(b.template_key)));
    const baseline = templates[0] ?? published[0]!;
    const requested = search.get("rule");
    let initial: Variant[];
    if (requested && requested !== baseline.id && published.some((r) => r.id === requested)) {
      const candidate = published.find((r) => r.id === requested)!;
      initial = [
        { label: baseline.name, rule_version_id: baseline.id, agent_profile_id: seeking.id },
        { label: candidate.name, rule_version_id: candidate.id, agent_profile_id: seeking.id },
      ];
      setTitle(`${candidate.name} против ${baseline.name}`);
    } else {
      const second = templates[1] ?? published.find((r) => r.id !== baseline.id);
      initial = [{ label: baseline.name, rule_version_id: baseline.id, agent_profile_id: seeking.id }];
      if (second) initial.push({ label: second.name, rule_version_id: second.id, agent_profile_id: seeking.id });
      setTitle(search.get("preset") === "first" ? "Первое испытание: стартовые правила" : "Серия испытаний");
    }
    setVariants(initial);
    setChecks(env.data.template.default_checks);
  }, [published, publishedScenarios, profileList, env.data, search]);

  const seeds = useMemo(() => Array.from({ length: Math.max(0, Math.min(repeats, 100)) }, (_, i) => baseSeed + i), [repeats, baseSeed]);
  const hasModel = variants.some((v) => profileList.find((p) => p.id === v.agent_profile_id)?.kind === "model");

  const body = useMemo(
    () =>
      scenarioId && variants.length
        ? {
            project_id: projectId,
            scenario_version_id: scenarioId,
            title,
            variants,
            conditions: { seeds, ...(horizon ? { horizon_ticks: Number(horizon) } : {}), ...(tail ? { observation_tail_ticks: Number(tail) } : {}), paired_exogenous_tape: true },
            checks: checks ?? undefined,
            failure_policy: failurePolicy,
            limits: {
              ...(maxCalls ? { max_model_calls: Number(maxCalls) } : {}),
              max_output_tokens_per_call: Number(maxOutput) || 512,
              max_wall_time_seconds: Math.round((Number(wallMinutes) || 30) * 60),
              ...(moneyUsd ? { money_limit_microusd: Math.round(Number(moneyUsd.replace(",", ".")) * 1_000_000) } : {}),
            },
          }
        : null,
    [projectId, scenarioId, title, variants, seeds, horizon, tail, checks, failurePolicy, maxCalls, maxOutput, wallMinutes, moneyUsd],
  );
  const bodyKey = JSON.stringify(body);
  // One key per exact request body: a double click or a retried request returns the same series.
  const lastKey = useRef<{ body: string; key: string } | null>(null);

  const estimate = useQuery({
    queryKey: ["estimate", bodyKey],
    queryFn: ({ signal }) => api<Estimate>("/batches/estimate", { body, signal }),
    enabled: Boolean(body),
    placeholderData: keepPreviousData,
    retry: false,
  });

  if (project.isLoading || rules.isLoading || scenarios.isLoading || profiles.isLoading) return <Loading lines={8} />;
  const loadError = project.error ?? rules.error ?? scenarios.error ?? profiles.error;
  if (loadError) return <ErrorState error={loadError} />;
  if (project.data?.role === "viewer") return <Notice tone="warn">Роль наблюдателя не позволяет запускать испытания.</Notice>;
  if (!published.length) return <Notice tone="warn">В проекте нет опубликованных правил. Опубликуйте версию правила, чтобы испытать ее.</Notice>;
  if (!publishedScenarios.length) return <Notice tone="warn">Нет опубликованной версии сценария.</Notice>;

  const scenario = publishedScenarios.find((s) => s.id === scenarioId);
  const profileIds = new Set(variants.map((v) => v.agent_profile_id));
  const est = estimate.data;
  const estError = estimate.error instanceof ApiError ? estimate.error : null;

  const start = async () => {
    if (!body) return;
    setStarting(true);
    setStartError(null);
    if (lastKey.current?.body !== bodyKey) lastKey.current = { body: bodyKey, key: newKey() };
    try {
      const created = await api<{ batch_id: string }>("/batches", { body, headers: { "Idempotency-Key": lastKey.current.key } });
      router.push(`/experiments/${created.batch_id}`);
    } catch (err) {
      setStartError(errorMessage(err));
      setStarting(false);
    }
  };

  const setVariant = (index: number, patch: Partial<Variant>) => setVariants(variants.map((v, i) => (i === index ? { ...v, ...patch } : v)));

  return (
    <div className="split">
      <div className="stack-24">
        <section className="panel stack">
          <div className="field">
            <label htmlFor="title">Название серии</label>
            <input id="title" className="input" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} />
          </div>
          <div className="field">
            <label htmlFor="scenario">Версия сценария</label>
            <select id="scenario" className="select" value={scenarioId} onChange={(e) => setScenarioId(e.target.value)}>
              {publishedScenarios.map((s) => (
                <option key={s.id} value={s.id}>
                  Версия {s.version}: {count(s.actor_count, "участник", "участника", "участников")}, горизонт {String(s.config.horizon_ticks ?? "—")} тиков
                </option>
              ))}
            </select>
            <span className="hint">Запуски используют только опубликованные версии. Черновик сценария сюда не попадает.</span>
          </div>
        </section>

        <section className="panel stack">
          <div className="row-between">
            <h2 className="t-panel">Варианты правил</h2>
            <span className="t-caption">от одного до четырех</span>
          </div>
          {variants.map((v, index) => (
            <div key={index} className="variant-row">
              <div className="field">
                <label htmlFor={`vl${index}`}>Подпись</label>
                <input id={`vl${index}`} className="input" value={v.label} onChange={(e) => setVariant(index, { label: e.target.value })} />
              </div>
              <div className="field">
                <label htmlFor={`vr${index}`}>Правило</label>
                <select
                  id={`vr${index}`}
                  className="select"
                  value={v.rule_version_id}
                  onChange={(e) => {
                    const rule = published.find((r) => r.id === e.target.value)!;
                    setVariant(index, { rule_version_id: rule.id, label: rule.name });
                  }}
                >
                  {published.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.name}, v{r.version}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label htmlFor={`vp${index}`}>Профиль агентов</label>
                <select id={`vp${index}`} className="select" value={v.agent_profile_id} onChange={(e) => setVariant(index, { agent_profile_id: e.target.value })}>
                  {profileList.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </div>
              <Button variant="ghost" className="btn-icon" aria-label={`Удалить вариант ${v.label}`} disabled={variants.length === 1} onClick={() => setVariants(variants.filter((_, i) => i !== index))}>
                <Trash2 size={16} aria-hidden />
              </Button>
            </div>
          ))}
          {profileIds.size > 1 ? (
            <Notice tone="warn" title="Профили вариантов различаются">
              Это дополнительный измененный фактор: он будет записан в план и отчет. Для чистого сравнения правил выберите один профиль.
            </Notice>
          ) : null}
          {variants.length < 4 ? (
            <div>
              <Button
                compact
                variant="ghost"
                onClick={() => {
                  const used = new Set(variants.map((v) => v.rule_version_id));
                  const rule = published.find((r) => !used.has(r.id)) ?? published[0]!;
                  setVariants([...variants, { label: rule.name, rule_version_id: rule.id, agent_profile_id: variants[0]?.agent_profile_id ?? profileList[0]!.id }]);
                }}
              >
                <Plus size={16} aria-hidden /> Добавить вариант
              </Button>
            </div>
          ) : null}
        </section>

        <section className="panel stack">
          <h2 className="t-panel">Условия</h2>
          <div className="grid-2">
            <div className="field">
              <label htmlFor="rep">Повторений на вариант</label>
              <input id="rep" className="input num" inputMode="numeric" value={repeats} onChange={(e) => setRepeats(Math.max(1, Number(e.target.value) || 1))} />
              <span className="hint">Интервал bootstrap показывается только при десяти и более полных парах.</span>
            </div>
            <div className="field">
              <label htmlFor="seed">Первый seed</label>
              <input id="seed" className="input num" inputMode="numeric" value={baseSeed} onChange={(e) => setBaseSeed(Number(e.target.value) || 0)} />
              <span className="hint num">{seeds.length > 6 ? `${seeds.slice(0, 3).join(", ")} … ${seeds.at(-1)}` : seeds.join(", ")}</span>
            </div>
            <div className="field">
              <label htmlFor="hor">Основной горизонт, тиков</label>
              <input id="hor" className="input num" inputMode="numeric" placeholder={String(scenario?.config.horizon_ticks ?? "")} value={horizon} onChange={(e) => setHorizon(e.target.value.replace(/\D/g, ""))} />
              <span className="hint">Пусто: как в сценарии. Не больше 240.</span>
            </div>
            <div className="field">
              <label htmlFor="tail">Период наблюдения, тиков</label>
              <input id="tail" className="input num" inputMode="numeric" placeholder={String(est?.observation_tail_ticks ?? "")} value={tail} onChange={(e) => setTail(e.target.value.replace(/\D/g, ""))} />
              <span className="hint">После горизонта новые действия запрещены, отложенные события досчитываются. Не больше 60.</span>
            </div>
          </div>
          <p className="t-caption" style={{ margin: 0 }}>
            Все варианты получают одну и ту же внешнюю ленту событий для каждого seed.
          </p>
        </section>

        <section className="panel stack">
          <h2 className="t-panel">Проверки</h2>
          {(env.data?.checks ?? []).map((c) => (
            <label key={c.check_id} className="check" style={{ alignItems: "flex-start" }}>
              <input
                type="checkbox"
                checked={checks?.includes(c.check_id) ?? true}
                onChange={(e) => {
                  const current = checks ?? env.data!.template.default_checks;
                  setChecks(e.target.checked ? [...current, c.check_id] : current.filter((id) => id !== c.check_id));
                }}
              />
              <span>
                {c.title}
                <span className="t-caption" style={{ display: "block" }}>
                  {c.check_id}
                </span>
              </span>
            </label>
          ))}
        </section>

        <section className="panel stack">
          <h2 className="t-panel">Пределы</h2>
          <div className="grid-2">
            <div className="field">
              <label htmlFor="wall">Реальное время серии, минут</label>
              <input id="wall" className="input num" inputMode="numeric" value={wallMinutes} onChange={(e) => setWallMinutes(e.target.value.replace(/[^\d.]/g, ""))} />
            </div>
            {hasModel ? (
              <>
                <div className="field">
                  <label htmlFor="calls">Вызовов модели, не больше</label>
                  <input id="calls" className="input num" inputMode="numeric" placeholder={String(est?.estimate.model_calls_upper_bound ?? "")} value={maxCalls} onChange={(e) => setMaxCalls(e.target.value.replace(/\D/g, ""))} />
                </div>
                <div className="field">
                  <label htmlFor="out">Токенов ответа на вызов</label>
                  <input id="out" className="input num" inputMode="numeric" value={maxOutput} onChange={(e) => setMaxOutput(e.target.value.replace(/\D/g, ""))} />
                </div>
                <div className="field">
                  <label htmlFor="money">Денежный предел, USD</label>
                  <input id="money" className="input num" inputMode="decimal" placeholder="без предела" value={moneyUsd} onChange={(e) => setMoneyUsd(e.target.value.replace(/[^\d.,]/g, ""))} />
                  <span className="hint">Доступен только при известной таблице цен модели.</span>
                </div>
              </>
            ) : null}
          </div>
          <fieldset className="stack" style={{ border: 0, padding: 0, margin: 0, gap: 8 }}>
            <legend style={{ fontWeight: 600, marginBottom: 6 }}>Если запуск завершится ошибкой</legend>
            <label className="check">
              <input type="radio" name="fp" checked={failurePolicy === "wait"} onChange={() => setFailurePolicy("wait")} />
              Продолжить остальные запуски; неполный запуск не попадет в сравнение
            </label>
            <label className="check">
              <input type="radio" name="fp" checked={failurePolicy === "stop"} onChange={() => setFailurePolicy("stop")} />
              Остановить серию
            </label>
          </fieldset>
        </section>
      </div>

      <aside className="stack" style={{ position: "sticky", top: 24 }}>
        <section className="panel stack" aria-live="polite" aria-busy={estimate.isFetching}>
          <div className="row-between">
            <h2 className="t-panel">План серии</h2>
            {estimate.isFetching ? <Loader2 size={16} className="spin" aria-label="Пересчитываем" /> : null}
          </div>
          {estError ? (
            <Notice tone="danger" title="План не прошел проверку">
              {estError.message}
              {Array.isArray(estError.details.issues)
                ? (estError.details.issues as { path: string; message: string }[]).map((i) => (
                    <span key={i.path} style={{ display: "block" }}>
                      {i.path}: {i.message}
                    </span>
                  ))
                : null}
            </Notice>
          ) : null}
          {est ? (
            <>
              <div className="plan-figure">
                <span className="t-value">{est.planned_runs}</span>
                <span className="t-secondary">{plural(est.planned_runs, "запуск", "запуска", "запусков")}: {count(est.variants.length, "вариант", "варианта", "вариантов")} × {count(est.seeds.length, "seed", "seed", "seed")}</span>
              </div>
              <dl className="facts">
                <dt>Участников в запуске</dt>
                <dd>{est.actor_count}</dd>
                <dt>Горизонт и наблюдение</dt>
                <dd>
                  {est.horizon_ticks} + {est.observation_tail_ticks} тиков
                </dd>
                <dt>Решений агентов</dt>
                <dd>{est.estimate.agent_decisions.toLocaleString("ru-RU")}</dd>
                <dt>Проверок</dt>
                <dd>{est.checks.length}</dd>
                {est.estimate.scripted_only ? (
                  <>
                    <dt>Вызовов модели</dt>
                    <dd>0, только сценарные агенты</dd>
                  </>
                ) : (
                  <>
                    <dt>Верхняя граница вызовов</dt>
                    <dd>{est.estimate.model_calls_upper_bound.toLocaleString("ru-RU")}</dd>
                    <dt>Резерв вызовов</dt>
                    <dd>{est.estimate.model_calls_reserved.toLocaleString("ru-RU")}</dd>
                    <dt>Верхняя граница стоимости</dt>
                    <dd>{usd(est.estimate.money_upper_bound_microusd)}</dd>
                  </>
                )}
              </dl>
              {est.estimate.price ? (
                <p className="t-caption" style={{ margin: 0 }}>
                  Тариф {est.estimate.price.model}: ${est.estimate.price.input_usd_per_mtok} ввод, ${est.estimate.price.output_usd_per_mtok} вывод за миллион токенов, {est.estimate.price.currency}; {est.estimate.price.source}, {est.estimate.price.as_of}. Оценка не заменяет фактические данные провайдера.
                </p>
              ) : null}
              <div className="row" style={{ gap: 6 }}>
                {est.variants.map((v, i) => (
                  <Pill key={i}>
                    {v.label}: {MODE_LABELS[v.mode] ?? v.mode}
                  </Pill>
                ))}
              </div>
              {est.differences.map((d) => (
                <Notice key={d} tone="warn">
                  {d}
                </Notice>
              ))}
            </>
          ) : !estError ? (
            <Loading lines={4} />
          ) : null}
          {startError ? <Notice tone="danger">{startError}</Notice> : null}
          <Button variant="primary" busy={starting} disabled={!est || Boolean(estError) || estimate.isFetching} onClick={start}>
            {starting ? "Создаем серию" : "Запустить испытания"}
          </Button>
          <p className="t-caption" style={{ margin: 0 }}>
            После старта план неизменяем. Сервер сам разворачивает варианты и seed; число запусков выше вычислено им.
          </p>
        </section>
      </aside>
    </div>
  );
}

export default function NewExperimentPage() {
  return (
    <Suspense fallback={<Loading lines={8} />}>
      <NewExperiment />
    </Suspense>
  );
}
