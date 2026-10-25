"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { Button, EmptyState, ErrorState, Loading, Notice, Pill, useToast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { count, MODE_LABELS } from "@/lib/format";
import { useProfiles, useProject } from "@/lib/queries";
import type { Profile } from "@/lib/types";

type Catalog = {
  default_model: string;
  models: { id: string; input_usd_per_mtok: string; output_usd_per_mtok: string; currency: string; price_source: string; price_as_of: string }[];
  modes: { id: string; label: string; defaults: Record<string, number | boolean | string> }[];
  deployment_key_present: boolean;
  note: string;
};
type Change = { id: string; name: string; changes: Record<string, { before: unknown; after: unknown }> };

const PARAMS: { key: string; label: string; hint: string; kind: "ppm" | "int" | "bool" }[] = [
  { key: "delay_discount_ppm", label: "Дисконт отложенной награды", hint: "Насколько агент ценит выплату, которая придет позже. 100 % — без дисконта.", kind: "ppm" },
  { key: "planning_horizon_ticks", label: "Горизонт планирования", hint: "Сколько тиков вперед агент учитывает при выборе действия.", kind: "int" },
  { key: "history_access", label: "Доступ к истории своих начислений", hint: "Видит ли агент, за что ему уже заплатили.", kind: "bool" },
  { key: "exploration_ppm", label: "Доля исследовательских действий", hint: "Как часто агент пробует вариант, который не выглядит лучшим.", kind: "ppm" },
];
const EFFORTS = [
  { value: "low", label: "Низкая" },
  { value: "medium", label: "Средняя" },
  { value: "high", label: "Высокая" },
];

function paramText(key: string, value: unknown): string {
  if (value === undefined || value === null) return "по умолчанию";
  if (typeof value === "boolean") return value ? "да" : "нет";
  if (key.endsWith("_ppm")) return `${Math.round(Number(value) / 10_000)} %`;
  if (key.endsWith("_ticks")) return `${value} тик.`;
  return String(value);
}

export default function AgentsPage() {
  const { project: projectId } = useParams<{ project: string }>();
  const project = useProject(projectId);
  const profiles = useProfiles(projectId);
  const catalog = useQuery({ queryKey: ["model-catalog"], queryFn: () => api<Catalog>("/settings/models"), staleTime: Infinity });
  const queryClient = useQueryClient();
  const toast = useToast();
  const [selected, setSelected] = useState<string | null>(null);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [bulkKey, setBulkKey] = useState(PARAMS[0]!.key);
  const [bulkValue, setBulkValue] = useState("85");
  const [preview, setPreview] = useState<Change[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const canEdit = project.data?.role !== "viewer";

  useEffect(() => {
    if (!selected && profiles.data?.items[0]) setSelected(profiles.data.items[0].id);
  }, [profiles.data, selected]);

  if (profiles.isLoading) return <Loading lines={6} />;
  if (profiles.error) return <ErrorState error={profiles.error} onRetry={() => profiles.refetch()} />;
  const items = profiles.data!.items;
  const participants = profiles.data!.participants;
  const current = items.find((p) => p.id === selected) ?? null;

  const bulkParam = PARAMS.find((p) => p.key === bulkKey)!;
  const bulkParsed = bulkParam.kind === "bool" ? bulkValue === "true" : bulkParam.kind === "ppm" ? Math.round(Number(bulkValue) * 10_000) : Number(bulkValue);

  const runBulk = async (apply: boolean) => {
    setBusy(apply ? "apply" : "preview");
    try {
      const result = await api<{ changes: Change[] }>(`/projects/${projectId}/agents/bulk`, { body: { profile_ids: [...checked], params: { [bulkKey]: bulkParsed }, preview: !apply } });
      if (apply) {
        await queryClient.invalidateQueries({ queryKey: ["profiles", projectId] });
        const changed = result.changes.filter((c) => Object.keys(c.changes).length).length;
        toast({ title: "Изменения применены", body: `Обновлено ${count(changed, "профиль", "профиля", "профилей")}; номер версии каждого вырос на 1.`, tone: "success" });
        setPreview(null);
        setChecked(new Set());
      } else {
        setPreview(result.changes);
      }
    } catch (err) {
      toast({ title: "Не удалось изменить профили", body: errorMessage(err), tone: "danger" });
    }
    setBusy(null);
  };

  return (
    <div className="stack-24">
      <Notice>{catalog.data?.note ?? "Параметры профиля — настройки экспериментального агента, а не типы человеческой личности."} Профиль задает поведение всех участников варианта; в одной серии сравниваются только запуски с одинаковым режимом.</Notice>

      <div className="split">
        <div className="stack">
          <div className="row-between">
            <h2 className="t-section">Профили агентов</h2>
            {canEdit ? <NewProfile projectId={projectId} catalog={catalog.data} onCreated={(id) => setSelected(id)} /> : null}
          </div>
          {items.length === 0 ? (
            <EmptyState title="Профилей пока нет">Создайте профиль, чтобы запускать испытания. Скриптовый агент работает без внешней модели и без затрат.</EmptyState>
          ) : (
            <div className="panel" style={{ padding: 0 }}>
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      {canEdit ? <th style={{ width: 40 }}><span className="sr-only">Выбор</span></th> : null}
                      <th>Профиль</th>
                      <th>Режим</th>
                      <th>Исполнитель</th>
                      <th className="r">Версия</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((p) => (
                      <tr key={p.id} data-link aria-selected={p.id === selected} onClick={() => setSelected(p.id)}>
                        {canEdit ? (
                          <td onClick={(e) => e.stopPropagation()}>
                            <input
                              type="checkbox"
                              aria-label={`Выбрать ${p.name}`}
                              checked={checked.has(p.id)}
                              onChange={(e) => {
                                const next = new Set(checked);
                                if (e.target.checked) next.add(p.id);
                                else next.delete(p.id);
                                setChecked(next);
                                setPreview(null);
                              }}
                            />
                          </td>
                        ) : null}
                        <td style={{ fontWeight: 600 }}>{p.name}</td>
                        <td className="t-secondary">{MODE_LABELS[p.mode] ?? p.mode}</td>
                        <td>{p.kind === "model" ? <Pill tone="info">Модель {String(p.model.model ?? "")}</Pill> : <Pill>Скриптовый</Pill>}</td>
                        <td className="r">v{p.version}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {canEdit && checked.size > 0 ? (
            <section className="panel stack" aria-label="Массовое изменение">
              <h3 className="t-panel">Изменить {count(checked.size, "выбранный профиль", "выбранных профиля", "выбранных профилей")}</h3>
              <div className="grid-2">
                <div className="field">
                  <label htmlFor="bk">Параметр</label>
                  <select id="bk" className="select" value={bulkKey} onChange={(e) => { const next = PARAMS.find((p) => p.key === e.target.value)!; setBulkKey(next.key); setBulkValue(next.kind === "bool" ? "true" : next.kind === "ppm" ? "85" : "12"); setPreview(null); }}>
                    {PARAMS.map((p) => (
                      <option key={p.key} value={p.key}>
                        {p.label}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="field">
                  <label htmlFor="bv">Новое значение{bulkParam.kind === "ppm" ? ", %" : bulkParam.kind === "int" ? ", тиков" : ""}</label>
                  {bulkParam.kind === "bool" ? (
                    <select id="bv" className="select" value={bulkValue} onChange={(e) => { setBulkValue(e.target.value); setPreview(null); }}>
                      <option value="true">да</option>
                      <option value="false">нет</option>
                    </select>
                  ) : (
                    <input id="bv" className="input num" inputMode="numeric" value={bulkValue} onChange={(e) => { setBulkValue(e.target.value); setPreview(null); }} />
                  )}
                </div>
              </div>
              {preview ? (
                <div className="panel-quiet stack" style={{ gap: 6 }} aria-live="polite">
                  <strong>Что изменится</strong>
                  {preview.map((c) => (
                    <div key={c.id} className="row-between t-secondary">
                      <span>{c.name}</span>
                      <span className="num">{Object.keys(c.changes).length ? Object.entries(c.changes).map(([k, v]) => `${paramText(k, v.before)} → ${paramText(k, v.after)}`).join(", ") : "без изменений"}</span>
                    </div>
                  ))}
                  <span className="t-caption">Прошлые запуски сохраняют версию профиля, с которой выполнялись.</span>
                </div>
              ) : null}
              <div className="row">
                <Button compact busy={busy === "preview"} onClick={() => runBulk(false)}>
                  Показать изменения
                </Button>
                <Button compact variant="primary" busy={busy === "apply"} disabled={!preview} onClick={() => runBulk(true)}>
                  Применить
                </Button>
              </div>
            </section>
          ) : null}
        </div>

        <aside className="stack">
          {current ? <ProfileEditor key={current.id + current.version} profile={current} catalog={catalog.data} editable={canEdit} projectId={projectId} /> : null}
          <section className="panel">
            <h2 className="t-panel" style={{ marginBottom: 8 }}>
              Участники сценария
            </h2>
            <p className="t-caption" style={{ marginTop: 0 }}>
              Число участников задается опубликованным сценарием. Все участники одного запуска используют один профиль.
            </p>
            <ul className="plain-list">
              {participants.map((a) => (
                <li key={a.actor_id} className="row-between">
                  <span>{a.display_name}</span>
                  <span className="t-caption num">{a.actor_id}</span>
                </li>
              ))}
            </ul>
          </section>
        </aside>
      </div>
    </div>
  );
}

function ProfileEditor({ profile, catalog, editable, projectId }: { profile: Profile; catalog: Catalog | undefined; editable: boolean; projectId: string }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const defaults = catalog?.modes.find((m) => m.id === profile.mode)?.defaults ?? {};
  const [name, setName] = useState(profile.name);
  const [params, setParams] = useState<Record<string, unknown>>({ ...defaults, ...profile.params });
  const [model, setModel] = useState<Record<string, unknown>>({ model: catalog?.default_model ?? "claude-opus-5-5", effort: "low", max_output_tokens: 2048, ...profile.model });
  const [busy, setBusy] = useState(false);
  const dirty = name !== profile.name || PARAMS.some((p) => params[p.key] !== ({ ...defaults, ...profile.params } as Record<string, unknown>)[p.key]) || JSON.stringify(model) !== JSON.stringify({ model: catalog?.default_model ?? "claude-opus-5-5", effort: "low", max_output_tokens: 2048, ...profile.model });
  const price = catalog?.models.find((m) => m.id === model.model);

  const save = async () => {
    setBusy(true);
    try {
      await api(`/agents/${profile.id}`, { method: "PATCH", body: { name, params, model: profile.kind === "model" ? model : undefined } });
      await queryClient.invalidateQueries({ queryKey: ["profiles", projectId] });
      toast({ title: "Профиль сохранен", body: `Новая версия v${profile.version + 1}`, tone: "success" });
    } catch (err) {
      toast({ title: "Профиль не сохранен", body: errorMessage(err), tone: "danger" });
    }
    setBusy(false);
  };

  return (
    <section className="panel stack" aria-label={`Профиль ${profile.name}`}>
      <div className="row-between">
        <h2 className="t-panel">Настройки профиля</h2>
        <Pill>{MODE_LABELS[profile.mode] ?? profile.mode}</Pill>
      </div>
      <div className="field">
        <label htmlFor="pn">Название</label>
        <input id="pn" className="input" value={name} disabled={!editable} onChange={(e) => setName(e.target.value)} />
      </div>
      {PARAMS.map((p) => (
        <div key={p.key} className="field">
          <label htmlFor={p.key}>{p.label}</label>
          {p.kind === "bool" ? (
            <label className="check">
              <input id={p.key} type="checkbox" checked={Boolean(params[p.key])} disabled={!editable} onChange={(e) => setParams({ ...params, [p.key]: e.target.checked })} />
              {params[p.key] ? "Есть доступ" : "Нет доступа"}
            </label>
          ) : (
            <div className="row" style={{ gap: 8 }}>
              <input
                id={p.key}
                className="input num"
                style={{ maxWidth: 120 }}
                inputMode="numeric"
                value={p.kind === "ppm" ? String(Math.round(Number(params[p.key] ?? 0) / 10_000)) : String(params[p.key] ?? "")}
                disabled={!editable}
                onChange={(e) => setParams({ ...params, [p.key]: p.kind === "ppm" ? Math.round(Number(e.target.value) * 10_000) : Number(e.target.value) })}
              />
              <span className="t-caption">{p.kind === "ppm" ? "%" : "тиков"}</span>
            </div>
          )}
          <span className="hint">{p.hint}</span>
        </div>
      ))}
      {profile.kind === "model" ? (
        <>
          <hr className="divider" />
          <div className="field">
            <label htmlFor="mm">Модель</label>
            <select id="mm" className="select" value={String(model.model)} disabled={!editable} onChange={(e) => setModel({ ...model, model: e.target.value })}>
              {(catalog?.models ?? []).map((m) => (
                <option key={m.id} value={m.id}>
                  {m.id}
                </option>
              ))}
            </select>
            {price ? (
              <span className="hint">
                Цена: ввод ${price.input_usd_per_mtok}, вывод ${price.output_usd_per_mtok} за миллион токенов; источник {price.price_source}, {price.price_as_of}.
              </span>
            ) : (
              <span className="hint">Цена неизвестна: денежный предел для этой модели не гарантируется.</span>
            )}
          </div>
          <div className="grid-2">
            <div className="field">
              <label htmlFor="me">Глубина рассуждения</label>
              <select id="me" className="select" value={String(model.effort)} disabled={!editable} onChange={(e) => setModel({ ...model, effort: e.target.value })}>
                {EFFORTS.map((e) => (
                  <option key={e.value} value={e.value}>
                    {e.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="mo">Предел ответа, токенов</label>
              <input id="mo" className="input num" inputMode="numeric" value={String(model.max_output_tokens)} disabled={!editable} onChange={(e) => setModel({ ...model, max_output_tokens: Number(e.target.value) })} />
            </div>
          </div>
          {catalog && !catalog.deployment_key_present ? <Notice tone="warn">Ключ провайдера не задан. Добавьте ключ в настройках моделей, иначе запуск с этим профилем не начнется.</Notice> : null}
        </>
      ) : null}
      {editable ? (
        <div>
          <Button variant="primary" busy={busy} disabled={!dirty} onClick={save}>
            Сохранить профиль
          </Button>
        </div>
      ) : null}
    </section>
  );
}

function NewProfile({ projectId, catalog, onCreated }: { projectId: string; catalog: Catalog | undefined; onCreated: (id: string) => void }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [mode, setMode] = useState("incentive_seeking");
  const [kind, setKind] = useState<"scripted" | "model">("scripted");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const create = async () => {
    setBusy(true);
    setError(null);
    try {
      const defaults = catalog?.modes.find((m) => m.id === mode)?.defaults ?? {};
      const created = await api<Profile>(`/projects/${projectId}/agents`, {
        body: { name: name || `${MODE_LABELS[mode]}, ${kind === "model" ? "модель" : "скриптовый"}`, mode, kind, params: { ...defaults }, model: kind === "model" ? { model: catalog?.default_model ?? "claude-opus-5-5", effort: "low", max_output_tokens: 2048 } : {} },
      });
      await queryClient.invalidateQueries({ queryKey: ["profiles", projectId] });
      onCreated(created.id);
      setOpen(false);
      setName("");
    } catch (err) {
      setError(errorMessage(err));
    }
    setBusy(false);
  };

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        <Button compact>
          <Plus size={16} aria-hidden /> Новый профиль
        </Button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="overlay" />
        <Dialog.Content className="dialog">
          <Dialog.Title className="t-section">Новый профиль агентов</Dialog.Title>
          <Dialog.Description className="t-secondary" style={{ margin: "6px 0 16px" }}>
            Режим нельзя изменить после создания: от него зависит, с какими запусками допустимо сравнение.
          </Dialog.Description>
          <div className="stack">
            <div className="field">
              <label htmlFor="npn">Название</label>
              <input id="npn" className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Например, Ищет награду, горизонт 20" />
            </div>
            <fieldset className="stack" style={{ border: 0, padding: 0, margin: 0, gap: 8 }}>
              <legend style={{ fontWeight: 600, marginBottom: 6 }}>Режим</legend>
              {(catalog?.modes ?? []).map((m) => (
                <label key={m.id} className="check">
                  <input type="radio" name="mode" checked={mode === m.id} onChange={() => setMode(m.id)} />
                  {m.label}
                </label>
              ))}
            </fieldset>
            <div className="segmented" role="group" aria-label="Исполнитель">
              <button type="button" aria-pressed={kind === "scripted"} onClick={() => setKind("scripted")}>
                Скриптовый агент
              </button>
              <button type="button" aria-pressed={kind === "model"} onClick={() => setKind("model")}>
                Языковая модель
              </button>
            </div>
            <span className="hint">{kind === "model" ? "Каждое решение — вызов модели с бюджетом и записью использования. Повтор запуска не вызывает модель снова." : "Решения считаются локально тем же интерпретатором правил, без внешних вызовов."}</span>
            {error ? <Notice tone="danger">{error}</Notice> : null}
            <div className="row" style={{ justifyContent: "flex-end" }}>
              <Dialog.Close asChild>
                <Button variant="ghost">Отмена</Button>
              </Dialog.Close>
              <Button variant="primary" busy={busy} onClick={create}>
                Создать профиль
              </Button>
            </div>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
