"use client";

import { useQueryClient } from "@tanstack/react-query";
import { CircleCheck, Loader2, TriangleAlert } from "lucide-react";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Button, EmptyState, ErrorState, Loading, Notice, Pill } from "@/components/ui";
import { api, ApiError, errorMessage } from "@/lib/api";
import { dateTime } from "@/lib/format";
import { useMe, useProject, useScenarios } from "@/lib/queries";
import { SCENARIO_FIELDS, SECTIONS, type ScenarioField } from "@/lib/scenarioFields";
import type { Scenario } from "@/lib/types";

type SaveState = { kind: "idle" | "saving" | "saved" | "error" | "conflict"; message?: string; server?: Scenario };

function toInput(field: ScenarioField, value: unknown): string | boolean {
  if (field.kind === "bool") return Boolean(value);
  if (field.kind === "ppm") return String(Math.round((Number(value) / 10_000) * 100) / 100);
  return value === null || value === undefined ? "" : String(value);
}

function fromInput(field: ScenarioField, raw: string | boolean): unknown {
  if (field.kind === "bool") return Boolean(raw);
  if (field.kind === "enum") return raw;
  if (raw === "") return raw;
  if (field.kind === "ppm") return Math.round(Number(String(raw).replace(",", ".")) * 10_000);
  return Number(raw);
}

export default function ScenarioPage() {
  const { project: projectId } = useParams<{ project: string }>();
  const project = useProject(projectId);
  const scenarios = useScenarios(projectId);
  const me = useMe();
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const items = scenarios.data?.items ?? [];
  const selected = items.find((s) => s.id === selectedId) ?? items.find((s) => s.status === "draft") ?? items[0];
  const env = project.data?.environment_id ?? "supportdesk";
  const fields = SCENARIO_FIELDS[env] ?? [];
  const editable = selected?.status === "draft" && project.data?.role !== "viewer";

  const [config, setConfig] = useState<Record<string, unknown>>({});
  const [actors, setActors] = useState(3);
  const [revision, setRevision] = useState(1);
  const [issues, setIssues] = useState<{ path: string; message: string }[]>([]);
  const [save, setSave] = useState<SaveState>({ kind: "idle" });
  const [busy, setBusy] = useState<string | null>(null);
  const timer = useRef<number | null>(null);
  const localKey = me.data && selected ? `chobra.scenario-draft.${me.data.id}.${projectId}.${selected.id}` : null;

  useEffect(() => {
    if (!selected) return;
    setConfig(selected.config);
    setActors(selected.actor_count);
    setRevision(selected.revision);
    setSave({ kind: "idle" });
  }, [selected?.id, selected?.revision]); // reset only when another version or revision arrives

  const validate = useCallback(
    async (nextConfig: Record<string, unknown>, nextActors: number) => {
      const result = await api<{ ok: boolean; issues: { path: string; message: string }[] }>("/scenarios/validate", { body: { environment: env, config: nextConfig, actor_count: nextActors } });
      setIssues(result.issues);
    },
    [env],
  );

  const persist = useCallback(
    async (nextConfig: Record<string, unknown>, nextActors: number, currentRevision: number) => {
      if (!selected) return;
      setSave({ kind: "saving" });
      try {
        const saved = await api<Scenario>(`/scenarios/${selected.id}`, { method: "PATCH", body: { config: nextConfig, actor_count: nextActors }, headers: { "If-Match": String(currentRevision) } });
        setRevision(saved.revision);
        setSave({ kind: "saved" });
        if (localKey) {
          try {
            window.localStorage.removeItem(localKey);
          } catch {
            /* ignore */
          }
        }
      } catch (err) {
        if (err instanceof ApiError && err.status === 409) {
          const server = await api<Scenario>(`/scenarios/${selected.id}`);
          setSave({ kind: "conflict", message: err.message, server });
        } else {
          setSave({ kind: "error", message: errorMessage(err) });
        }
      }
    },
    [selected, localKey],
  );

  const change = (field: ScenarioField, raw: string | boolean) => {
    const next = { ...config, [field.key]: fromInput(field, raw) };
    setConfig(next);
    if (localKey) {
      try {
        window.localStorage.setItem(localKey, JSON.stringify({ config: next, actors, at: Date.now() }));
      } catch {
        /* storage may be unavailable */
      }
    }
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      void validate(next, actors);
      void persist(next, actors, revision);
    }, 800);
  };

  const flushOnBlur = () => {
    if (!timer.current) return;
    window.clearTimeout(timer.current);
    timer.current = null;
    void validate(config, actors);
    void persist(config, actors, revision);
  };

  const createDraft = async () => {
    if (!selected) return;
    setBusy("draft");
    const draft = await api<Scenario>("/scenarios", { body: { project_id: projectId, from_version_id: selected.id } });
    await queryClient.invalidateQueries({ queryKey: ["scenarios", projectId] });
    setSelectedId(draft.id);
    setBusy(null);
  };

  const publish = async () => {
    if (!selected) return;
    setBusy("publish");
    try {
      await api(`/scenarios/${selected.id}/publish`, { body: {} });
      await queryClient.invalidateQueries({ queryKey: ["scenarios", projectId] });
      await queryClient.invalidateQueries({ queryKey: ["project", projectId] });
    } catch (err) {
      const details = err instanceof ApiError ? (err.details.issues as { path: string; message: string }[] | undefined) : undefined;
      if (details) setIssues(details);
      setSave({ kind: "error", message: errorMessage(err) });
    }
    setBusy(null);
  };

  const saveCopy = async () => {
    setBusy("copy");
    const copy = await api<Scenario>("/scenarios", { body: { project_id: projectId, config, actor_count: actors } });
    await queryClient.invalidateQueries({ queryKey: ["scenarios", projectId] });
    setSelectedId(copy.id);
    setBusy(null);
  };

  const issueFor = (key: string) => issues.find((i) => i.path === key || i.path.startsWith(`${key}[`));
  const summary = useMemo(() => buildSummary(env, config, actors), [env, config, actors]);

  if (scenarios.isLoading || project.isLoading) return <Loading lines={8} />;
  if (scenarios.error) return <ErrorState error={scenarios.error} />;
  if (!selected) return <EmptyState title="Сценариев нет" />;

  return (
    <div className="split">
      <div className="stack-24">
        <div className="row-between">
          <div className="row">
            <label htmlFor="version" className="sr-only">
              Версия сценария
            </label>
            <select id="version" className="select" style={{ width: 260 }} value={selected.id} onChange={(e) => setSelectedId(e.target.value)}>
              {items.map((s) => (
                <option key={s.id} value={s.id}>
                  Версия {s.version}, {s.status === "published" ? "опубликована" : "черновик"}
                </option>
              ))}
            </select>
            <SaveIndicator state={save} />
          </div>
          <div className="row">
            {selected.status === "published" ? (
              project.data?.role !== "viewer" ? (
                <Button busy={busy === "draft"} onClick={createDraft}>
                  Изменить в новой версии
                </Button>
              ) : null
            ) : (
              <Button variant="primary" busy={busy === "publish"} disabled={issues.length > 0} onClick={publish}>
                Опубликовать версию
              </Button>
            )}
          </div>
        </div>
        {selected.status === "published" ? (
          <Notice tone="info">Опубликованная версия неизменяема; запуски используют ее снимок. Изменения делаются в новой версии.</Notice>
        ) : null}
        {save.kind === "conflict" && save.server ? (
          <Notice tone="warn" title="Черновик изменен другим пользователем">
            <span>Ваши изменения не записаны поверх чужих. Текущая ревизия на сервере {save.server.revision}.</span>
            <div className="row" style={{ marginTop: 10 }}>
              <Button compact onClick={() => { setConfig(save.server!.config); setActors(save.server!.actor_count); setRevision(save.server!.revision); setSave({ kind: "idle" }); }}>
                Загрузить версию с сервера
              </Button>
              <Button compact busy={busy === "copy"} onClick={saveCopy}>
                Сохранить мои изменения копией
              </Button>
            </div>
          </Notice>
        ) : null}
        {issues.length ? (
          <Notice tone="danger" title={`Ошибок проверки: ${issues.length}`}>
            <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
              {issues.map((i) => (
                <li key={i.path}>
                  <a href={`#field-${i.path.split("[")[0]}`} style={{ textDecoration: "underline" }}>
                    {fields.find((f) => f.key === i.path.split("[")[0])?.label ?? i.path}
                  </a>
                  : {i.message}
                </li>
              ))}
            </ul>
          </Notice>
        ) : null}
        <section className="panel">
          <h2 className="t-panel" style={{ marginBottom: 12 }}>
            Участники
          </h2>
          <div className="field" style={{ maxWidth: 280 }}>
            <label htmlFor="field-actors">Число участников</label>
            <div className="input-unit">
              <input
                id="field-actors"
                className="input num"
                type="number"
                min={1}
                max={20}
                value={actors}
                disabled={!editable}
                onChange={(e) => {
                  const value = Number(e.target.value);
                  setActors(value);
                  if (timer.current) window.clearTimeout(timer.current);
                  timer.current = window.setTimeout(() => { void validate(config, value); void persist(config, value, revision); }, 800);
                }}
                onBlur={flushOnBlur}
              />
              <span className="unit">от 1 до 20</span>
            </div>
          </div>
        </section>
        {SECTIONS.map((section) => {
          const sectionFields = fields.filter((f) => f.section === section);
          if (!sectionFields.length) return null;
          return (
            <section key={section} className="panel" aria-labelledby={`s-${section}`}>
              <h2 id={`s-${section}`} className="t-panel" style={{ marginBottom: 12 }}>
                {section}
              </h2>
              <div className="grid-2">
                {sectionFields.map((field) => {
                  const issue = issueFor(field.key);
                  const value = toInput(field, config[field.key]);
                  const id = `field-${field.key}`;
                  return (
                    <div key={field.key} className="field">
                      {field.kind === "bool" ? (
                        <label className="check" htmlFor={id}>
                          <input id={id} type="checkbox" checked={Boolean(value)} disabled={!editable} onChange={(e) => change(field, e.target.checked)} onBlur={flushOnBlur} />
                          <span>{field.label}</span>
                        </label>
                      ) : (
                        <>
                          <label htmlFor={id}>{field.label}</label>
                          {field.kind === "enum" ? (
                            <select id={id} className="select" value={String(value)} disabled={!editable} onChange={(e) => change(field, e.target.value)} onBlur={flushOnBlur}>
                              {field.options!.map((o) => (
                                <option key={o.value} value={o.value}>
                                  {o.label}
                                </option>
                              ))}
                            </select>
                          ) : (
                            <div className="input-unit">
                              <input
                                id={id}
                                className="input num"
                                inputMode="decimal"
                                value={String(value)}
                                disabled={!editable}
                                aria-invalid={issue ? true : undefined}
                                aria-describedby={`${id}-hint`}
                                onChange={(e) => change(field, e.target.value)}
                                onBlur={flushOnBlur}
                              />
                              <span className="unit">{field.unit}</span>
                            </div>
                          )}
                        </>
                      )}
                      <span id={`${id}-hint`} className="hint">
                        {field.hint ? `${field.hint}. ` : ""}
                        {field.min !== undefined ? `Диапазон ${field.min}–${field.max}. ` : ""}Влияет на: {field.affects}.
                      </span>
                      {issue ? <span className="error">{issue.message}</span> : null}
                    </div>
                  );
                })}
              </div>
            </section>
          );
        })}
      </div>
      <aside className="panel" style={{ position: "sticky", top: 24 }} aria-label="Сводка исполняемых условий">
        <h2 className="t-panel" style={{ marginBottom: 10 }}>
          Исполняемые условия
        </h2>
        <ul className="stack" style={{ margin: 0, paddingLeft: 18, gap: 8 }}>
          {summary.map((line) => (
            <li key={line} className="t-secondary">
              {line}
            </li>
          ))}
        </ul>
        <hr className="divider" />
        <dl className="kv">
          <dt>Версия</dt>
          <dd className="num">v{selected.version}</dd>
          <dt>Состояние</dt>
          <dd>{selected.status === "published" ? <Pill tone="success">Опубликована</Pill> : <Pill>Черновик, ревизия {revision}</Pill>}</dd>
          <dt>Опубликована</dt>
          <dd>{dateTime(selected.published_at)}</dd>
        </dl>
      </aside>
    </div>
  );
}

function SaveIndicator({ state }: { state: SaveState }) {
  if (state.kind === "saving")
    return (
      <span className="row t-caption" style={{ gap: 6 }} role="status">
        <Loader2 size={14} className="spin" aria-hidden /> Сохраняем
      </span>
    );
  if (state.kind === "saved")
    return (
      <span className="row t-caption" style={{ gap: 6 }} role="status">
        <CircleCheck size={14} color="#4BD49A" aria-hidden /> Сохранено
      </span>
    );
  if (state.kind === "error")
    return (
      <span className="row t-caption" style={{ gap: 6, color: "#FF9AAC" }} role="alert">
        <TriangleAlert size={14} aria-hidden /> {state.message}
      </span>
    );
  return null;
}

function buildSummary(env: string, c: Record<string, unknown>, actors: number): string[] {
  const n = (k: string) => Number(c[k] ?? 0);
  const pct = (k: string) => `${Math.round(n(k) / 10_000)} %`;
  if (env === "supportdesk")
    return [
      `${actors} участника, по ${n("actor_effort_per_tick")} кванту работы за тик`,
      `${n("issue_count")} обращений, сложных ${pct("hard_share_ppm")}, поступают в первые ${n("arrival_window_ticks")} тиков`,
      `Основной горизонт ${n("horizon_ticks")} тиков, проверка клиента через ${n("confirmation_delay_ticks")}`,
      c.allow_close_unsolved ? "Закрыть можно и нерешенное обращение" : "Закрыть можно только решенное",
      c.allow_split ? `Разбиение до ${n("split_max_children")} частей, глубина ${n("split_max_depth")}` : "Разбиение выключено",
      c.allow_report_complexity ? "Участник может заявлять сложность" : "Заявленная сложность не меняется",
    ];
  if (env === "taskboard")
    return [
      `${actors} участника, ${n("task_count")} задач объемом ${n("effort_min")}–${n("effort_max")} квантов`,
      c.dependency_mode === "forbid" ? "Работа до готовности входов запрещена" : `Работа до готовности входов разрешена, риск переделки ${pct("rework_ppm")}`,
      `Дефект на квант ${pct("defect_ppm")}, лимит незавершенной работы ${n("wip_limit")}`,
      `Основной горизонт ${n("horizon_ticks")} тиков`,
    ];
  return [
    `${actors} участника делят запас ${n("initial_stock")} из ${n("capacity")}`,
    `Восстановление r = ${n("regen_num")}/${n("regen_den")}, внешняя подпитка ${n("external_inflow")}`,
    `Квота ${n("quota")}, механизм ограничения: ${String(c.cap_mode)}`,
    `Минимальный запас для проверки ${n("min_stock")}, горизонт ${n("horizon_ticks")} тиков`,
  ];
}
