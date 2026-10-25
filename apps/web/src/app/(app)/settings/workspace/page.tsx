"use client";

import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { Button, ErrorState, Loading, Notice, useToast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { useCurrentWorkspace } from "@/components/Shell";
import { useMe, useWorkspace } from "@/lib/queries";
import type { Workspace } from "@/lib/types";

const LIMITS = [
  { key: "max_concurrent_runs", label: "Одновременные запуски", ceiling: 4 },
  { key: "max_runs_per_series", label: "Запуски в одной серии", ceiling: 100 },
  { key: "max_agents", label: "Участники в сценарии", ceiling: 20 },
  { key: "max_horizon_ticks", label: "Горизонт сценария", ceiling: 240 },
] as const;
const RETENTION = [
  { key: "events_days", label: "События и результаты", ceiling: 180 },
  { key: "raw_model_io_days", label: "Ввод и вывод модели", ceiling: 30 },
  { key: "technical_logs_days", label: "Технические журналы", ceiling: 30 },
] as const;

export default function WorkspaceSettingsPage() {
  const { workspaceId } = useCurrentWorkspace();
  const workspaceQuery = useWorkspace(workspaceId ?? undefined);
  const me = useMe();
  const queryClient = useQueryClient();
  const toast = useToast();
  const workspace = workspaceQuery.data;
  const role = me.data?.workspaces.find((w) => w.id === workspaceId)?.role;
  const canManage = role === "owner" || role === "admin";
  const isOwner = role === "owner";
  const [name, setName] = useState("");
  const [limits, setLimits] = useState<Record<string, string>>({});
  const [retention, setRetention] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!workspace) return;
    setName(workspace.name);
    setLimits(Object.fromEntries(LIMITS.map(({ key }) => [key, String(workspace.limits[key] ?? "")])));
    setRetention(Object.fromEntries(RETENTION.map(({ key }) => [key, String(workspace.retention_policy[key] ?? "")])));
  }, [workspace]);

  const dirty = useMemo(() => {
    if (!workspace) return false;
    return name.trim() !== workspace.name || LIMITS.some(({ key }) => Number(limits[key]) !== workspace.limits[key]) || RETENTION.some(({ key }) => Number(retention[key]) !== workspace.retention_policy[key]);
  }, [limits, name, retention, workspace]);

  if (workspaceQuery.isLoading || me.isLoading) return <Loading lines={6} />;
  if (workspaceQuery.error) return <ErrorState error={workspaceQuery.error} onRetry={() => workspaceQuery.refetch()} />;
  if (!workspace) return <ErrorState error={new Error("Рабочее пространство не выбрано")} />;

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const nextLimits = Object.fromEntries(LIMITS.map(({ key }) => [key, Number(limits[key])]));
    const nextRetention = Object.fromEntries(RETENTION.map(({ key }) => [key, Number(retention[key])]));
    const invalidLimit = LIMITS.find(({ key, ceiling }) => {
      const value = nextLimits[key] ?? Number.NaN;
      return !Number.isInteger(value) || value < 1 || value > ceiling || (!isOwner && value > (workspace.limits[key] ?? ceiling));
    });
    const invalidRetention = RETENTION.find(({ key, ceiling }) => {
      const value = nextRetention[key] ?? Number.NaN;
      return !Number.isInteger(value) || value < 1 || value > ceiling;
    });
    if (invalidLimit) {
      toast({ title: "Проверьте пределы", body: `${invalidLimit.label}: допустимое значение от 1 до ${isOwner ? invalidLimit.ceiling : workspace.limits[invalidLimit.key]}.`, tone: "danger" });
      return;
    }
    if (invalidRetention) {
      toast({ title: "Проверьте сроки хранения", body: `${invalidRetention.label}: срок должен быть от 1 дня до установленного максимума.`, tone: "danger" });
      return;
    }
    setBusy(true);
    try {
      const updated = await api<Workspace>(`/workspaces/${workspace.id}`, { method: "PATCH", body: { name: name.trim(), limits: nextLimits, retention_policy: nextRetention } });
      queryClient.setQueryData(["workspace", workspace.id], updated);
      await queryClient.invalidateQueries({ queryKey: ["me"] });
      toast({ title: "Настройки сохранены", tone: "success" });
    } catch (error) {
      toast({ title: "Не удалось сохранить настройки", body: errorMessage(error), tone: "danger" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <header className="page-head">
        <div>
          <h1 className="t-page">Рабочее пространство</h1>
          <p className="lead">Название, пределы запусков и сроки хранения данных для «{workspace.name}».</p>
        </div>
      </header>
      {!canManage ? <Notice title="Только для администраторов и владельцев">Ваша роль «{role ?? "участник"}» позволяет просматривать эти настройки, но не менять их.</Notice> : null}
      <form className="stack-24" onSubmit={submit}>
        <section className="panel stack">
          <div>
            <h2 className="t-panel">Основные настройки</h2>
            <p className="t-caption" style={{ margin: "4px 0 0" }}>Изменение названия доступно администраторам и владельцам.</p>
          </div>
          <div className="field">
            <label htmlFor="workspace-name">Название пространства</label>
            <input id="workspace-name" className="input" value={name} maxLength={120} required disabled={!canManage} onChange={(event) => setName(event.target.value)} />
          </div>
        </section>
        <section className="panel stack">
          <div>
            <h2 className="t-panel">Пределы</h2>
            <p className="t-caption" style={{ margin: "4px 0 0" }}>Владелец может повысить значения до максимума. Администратор может только снизить текущие пределы.</p>
          </div>
          <div className="settings-fields">
            {LIMITS.map(({ key, label, ceiling }) => (
              <div className="field" key={key}>
                <label htmlFor={`limit-${key}`}>{label}</label>
                <input id={`limit-${key}`} className="input num" type="number" min={1} max={isOwner ? ceiling : workspace.limits[key]} step={1} value={limits[key] ?? ""} disabled={!canManage} onChange={(event) => setLimits((values) => ({ ...values, [key]: event.target.value }))} />
                <span className="hint">Максимум: {isOwner ? ceiling : workspace.limits[key]}.</span>
              </div>
            ))}
          </div>
        </section>
        <section className="panel stack">
          <div>
            <h2 className="t-panel">Сроки хранения</h2>
            <p className="t-caption" style={{ margin: "4px 0 0" }}>Менять сроки хранения может только владелец. Уменьшение срока может привести к более раннему удалению данных.</p>
          </div>
          <div className="settings-fields">
            {RETENTION.map(({ key, label, ceiling }) => (
              <div className="field" key={key}>
                <label htmlFor={`retention-${key}`}>{label}, дней</label>
                <input id={`retention-${key}`} className="input num" type="number" min={1} max={ceiling} step={1} value={retention[key] ?? ""} disabled={!isOwner} onChange={(event) => setRetention((values) => ({ ...values, [key]: event.target.value }))} />
                <span className="hint">Максимум: {ceiling} дней.</span>
              </div>
            ))}
          </div>
        </section>
        {canManage ? <div className="settings-actions"><Button type="submit" variant="primary" busy={busy} disabled={!dirty}>Сохранить настройки</Button></div> : null}
      </form>
    </>
  );
}
