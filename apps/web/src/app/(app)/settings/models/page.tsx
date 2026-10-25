"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState, type FormEvent } from "react";

import { useCurrentWorkspace } from "@/components/Shell";
import { Button, EmptyState, ErrorState, Loading, Notice, Pill, useToast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { useMe, useWorkspace } from "@/lib/queries";
import type { Workspace } from "@/lib/types";

type Catalog = {
  default_model: string;
  models: { id: string; input_usd_per_mtok: string; output_usd_per_mtok: string; currency: string; price_source: string; price_as_of: string }[];
  deployment_key_present: boolean;
  note: string;
};
type ProviderKey = { id: string; provider: string; last4: string; created_at: string };
type KeyList = { items: ProviderKey[]; deployment_key_present: boolean };
type KeyCheck = { status: "ok" | "no_key" | "auth_failed" | "unavailable"; message?: string; models?: string[] };
type ModelSettings = { default_model: string; allowed_models: string[] };

export default function ModelSettingsPage() {
  const { workspaceId } = useCurrentWorkspace();
  const me = useMe();
  const workspaceQuery = useWorkspace(workspaceId ?? undefined);
  const queryClient = useQueryClient();
  const toast = useToast();
  const role = me.data?.workspaces.find((workspace) => workspace.id === workspaceId)?.role;
  const canManage = role === "owner" || role === "admin";
  const isOwner = role === "owner";
  const catalog = useQuery({ queryKey: ["model-catalog"], queryFn: () => api<Catalog>("/settings/models"), staleTime: Infinity });
  const keys = useQuery({
    queryKey: ["provider-keys", workspaceId],
    queryFn: () => api<KeyList>(`/workspaces/${workspaceId}/provider-keys`),
    enabled: Boolean(workspaceId && canManage),
  });
  const [keyDraft, setKeyDraft] = useState("");
  const [defaultModel, setDefaultModel] = useState("");
  const [allowedModels, setAllowedModels] = useState<string[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [check, setCheck] = useState<KeyCheck | null>(null);
  const workspace = workspaceQuery.data;
  const currentSettings = (workspace?.model_settings ?? {}) as Partial<ModelSettings>;
  const modelOptions = catalog.data?.models ?? [];
  const dirty = useMemo(() => {
    if (!workspace) return false;
    const saved = workspace.model_settings as Partial<ModelSettings>;
    return defaultModel !== (saved.default_model ?? catalog.data?.default_model ?? "") || JSON.stringify([...allowedModels].sort()) !== JSON.stringify([...(saved.allowed_models ?? modelOptions.map((model) => model.id))].sort());
  }, [allowedModels, catalog.data?.default_model, defaultModel, modelOptions, workspace]);

  useEffect(() => {
    if (!workspace || !catalog.data) return;
    const settings = workspace.model_settings as Partial<ModelSettings>;
    const fallback = settings.default_model ?? catalog.data.default_model;
    const allowed = settings.allowed_models?.length ? settings.allowed_models : catalog.data.models.map((model) => model.id);
    setDefaultModel(fallback);
    setAllowedModels(allowed.includes(fallback) ? allowed : [...allowed, fallback]);
  }, [catalog.data, workspace]);

  const refreshKeys = async () => queryClient.invalidateQueries({ queryKey: ["provider-keys", workspaceId] });

  const addKey = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!workspaceId || !keyDraft) return;
    setBusy("add-key");
    try {
      await api<ProviderKey>(`/workspaces/${workspaceId}/provider-keys`, { body: { provider: "anthropic", api_key: keyDraft } });
      setKeyDraft("");
      setCheck(null);
      await refreshKeys();
      toast({ title: "Ключ сохранен", body: "Сервер вернул только последние четыре символа.", tone: "success" });
    } catch (error) {
      toast({ title: "Не удалось сохранить ключ", body: errorMessage(error), tone: "danger" });
    } finally {
      setBusy(null);
    }
  };

  const revokeKey = async (key: ProviderKey) => {
    setBusy(key.id);
    try {
      await api(`/provider-keys/${key.id}`, { method: "DELETE" });
      setCheck(null);
      await refreshKeys();
      toast({ title: "Ключ отозван", tone: "success" });
    } catch (error) {
      toast({ title: "Не удалось отозвать ключ", body: errorMessage(error), tone: "danger" });
    } finally {
      setBusy(null);
    }
  };

  const checkKey = async () => {
    if (!workspaceId) return;
    setBusy("check");
    setCheck(null);
    try {
      setCheck(await api<KeyCheck>(`/workspaces/${workspaceId}/provider-keys/check`, { body: {} }));
    } catch (error) {
      toast({ title: "Проверка подключения завершилась ошибкой", body: errorMessage(error), tone: "danger" });
    } finally {
      setBusy(null);
    }
  };

  const saveModels = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!workspace) return;
    const selected = [...new Set([...allowedModels, defaultModel])];
    setBusy("models");
    try {
      const updated = await api<Workspace>(`/workspaces/${workspace.id}`, { method: "PATCH", body: { model_settings: { default_model: defaultModel, allowed_models: selected } } });
      queryClient.setQueryData(["workspace", workspace.id], updated);
      toast({ title: "Настройки моделей сохранены", tone: "success" });
    } catch (error) {
      toast({ title: "Не удалось сохранить настройки моделей", body: errorMessage(error), tone: "danger" });
    } finally {
      setBusy(null);
    }
  };

  if (workspaceQuery.isLoading || me.isLoading) return <Loading lines={6} />;
  if (workspaceQuery.error) return <ErrorState error={workspaceQuery.error} onRetry={() => workspaceQuery.refetch()} />;
  if (!workspace) return <ErrorState error={new Error("Рабочее пространство не выбрано")} />;

  return (
    <>
      <header className="page-head">
        <div>
          <h1 className="t-page">Модели и ключи</h1>
          <p className="lead">Подключение Anthropic и ограничения выбора моделей в пространстве «{workspace.name}».</p>
        </div>
      </header>
      {!canManage ? <Notice title="Ключами управляют администраторы и владельцы">Ваша роль «{role ?? "участник"}» не позволяет просматривать ключи провайдера или менять параметры пространства.</Notice> : null}
      <section className="panel stack">
        <div className="row-between">
          <div>
            <h2 className="t-panel">Ключ провайдера</h2>
            <p className="t-caption" style={{ margin: "4px 0 0" }}>Ключ хранится на сервере. Интерфейс получает только его последние четыре символа.</p>
          </div>
          {keys.data?.deployment_key_present ? <Pill tone="info">Ключ развертывания настроен</Pill> : null}
        </div>
        {canManage && keys.isLoading ? <Loading lines={2} /> : null}
        {canManage && keys.error ? <ErrorState error={keys.error} onRetry={() => keys.refetch()} /> : null}
        {canManage && keys.data && keys.data.items.length === 0 ? <EmptyState title="Ключ пространства не задан">Проверка может использовать ключ развертывания, если он настроен.</EmptyState> : null}
        {canManage && keys.data?.items.map((key) => (
          <div key={key.id} className="row-between panel-quiet">
            <div>
              <strong>Anthropic · •••• {key.last4}</strong>
              <div className="t-caption">Добавлен {new Date(key.created_at).toLocaleDateString("ru-RU")}</div>
            </div>
            {isOwner ? <Button compact variant="danger" busy={busy === key.id} onClick={() => void revokeKey(key)}>Отозвать</Button> : <span className="t-caption">Отозвать может только владелец</span>}
          </div>
        ))}
        {isOwner ? (
          <form className="stack" onSubmit={addKey}>
            <div className="field">
              <label htmlFor="provider-key">Новый ключ Anthropic</label>
              <input id="provider-key" className="input" type="password" autoComplete="new-password" autoCapitalize="none" spellCheck={false} minLength={10} maxLength={300} required value={keyDraft} onChange={(event) => setKeyDraft(event.target.value)} />
              <span className="hint">Значение отправляется напрямую API и не сохраняется в браузерном хранилище.</span>
            </div>
            <div className="settings-actions"><Button type="submit" variant="primary" busy={busy === "add-key"}>Сохранить ключ</Button></div>
          </form>
        ) : canManage ? <p className="t-caption">Добавлять и отзывать ключ может только владелец.</p> : null}
        {canManage ? (
          <div className="stack">
            <div className="settings-actions">
              <Button compact busy={busy === "check"} onClick={() => void checkKey()}>Проверить подключение</Button>
              <span className="t-caption">Проверка обращается к API провайдера и может тарифицироваться.</span>
            </div>
            {check ? (
              <div className="panel-quiet stack" aria-live="polite">
                <strong>{check.status === "ok" ? "Подключение работает" : check.status === "no_key" ? "Ключ не задан" : check.status === "auth_failed" ? "Провайдер отклонил ключ" : "Провайдер временно недоступен"}</strong>
                {check.message ? <span className="t-secondary">{check.message}</span> : null}
                {check.models?.length ? <span className="t-caption">Доступные модели: {check.models.join(", ")}</span> : null}
              </div>
            ) : null}
          </div>
        ) : null}
      </section>

      <form className="panel stack" onSubmit={saveModels}>
        <div>
          <h2 className="t-panel">Параметры моделей</h2>
          <p className="t-caption" style={{ margin: "4px 0 0" }}>Задайте модель по умолчанию и разрешенные модели для пространства.</p>
        </div>
        {catalog.isLoading ? <Loading lines={3} /> : null}
        {catalog.error ? <ErrorState error={catalog.error} onRetry={() => catalog.refetch()} /> : null}
        {catalog.data ? (
          <>
            {!isOwner ? <Notice>Настройки можно просматривать; изменять их может только владелец. Модели с указанными ценами — каталог сервера и могут измениться при обновлении.</Notice> : null}
            <div className="field">
              <label htmlFor="default-model">Модель по умолчанию</label>
              <select id="default-model" className="select" value={defaultModel} disabled={!isOwner} onChange={(event) => { const value = event.target.value; setDefaultModel(value); setAllowedModels((current) => current.includes(value) ? current : [...current, value]); }}>
                {modelOptions.map((model) => <option key={model.id} value={model.id}>{model.id}</option>)}
              </select>
            </div>
            <fieldset className="stack" style={{ border: 0, padding: 0, margin: 0 }} disabled={!isOwner}>
              <legend className="t-panel" style={{ marginBottom: 8 }}>Разрешенные модели</legend>
              {modelOptions.map((model) => (
                <label key={model.id} className="check">
                  <input type="checkbox" checked={allowedModels.includes(model.id)} disabled={!isOwner || model.id === defaultModel} onChange={(event) => setAllowedModels((current) => event.target.checked ? [...current, model.id] : current.filter((id) => id !== model.id))} />
                  <span>{model.id} <span className="t-caption">· вход ${model.input_usd_per_mtok} / выход ${model.output_usd_per_mtok} за 1 млн токенов</span></span>
                </label>
              ))}
            </fieldset>
            {isOwner ? <div className="settings-actions"><Button type="submit" variant="primary" busy={busy === "models"} disabled={!dirty || !defaultModel || allowedModels.length === 0}>Сохранить модели</Button></div> : null}
            <p className="t-caption">Параметры профилей агентов управляют экспериментальным поведением. Они не описывают личность человека.</p>
          </>
        ) : null}
      </form>
    </>
  );
}
