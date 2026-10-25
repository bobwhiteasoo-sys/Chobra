"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";

import { Button, ErrorState, Loading, Notice, Pill } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { dateTime } from "@/lib/format";
import { useEnvironment, useProject, useRules } from "@/lib/queries";
import { blankRule, fieldsOf } from "@/lib/ruleForm";
import type { Rule } from "@/lib/types";

const ORIGIN: Record<string, string> = { template: "Стартовая схема", manual: "Вручную", text: "Из текста", finding_fix: "Кандидат исправления" };

export default function RulesPage() {
  const { project: projectId } = useParams<{ project: string }>();
  const project = useProject(projectId);
  const rules = useRules(projectId);
  const env = useEnvironment(project.data?.environment_id);
  const router = useRouter();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [base, setBase] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const canEdit = project.data?.role !== "viewer";

  const create = async () => {
    setBusy(true);
    setError(null);
    try {
      let created: Rule;
      if (base) {
        const source = rules.data!.items.find((r) => r.id === base)!;
        created = await api<Rule>(`/rules/${source.id}/new-version`, { body: {} });
        if (name) await api(`/rules/${created.id}`, { method: "PATCH", body: { name }, headers: { "If-Match": String(created.revision) } });
      } else {
        const trigger = Object.keys(env.data!.triggers)[0]!;
        created = await api<Rule>("/rules", { body: { project_id: projectId, name: name || "Новое правило", tree: blankRule(project.data!.environment_id, trigger, fieldsOf(env.data, trigger)) } });
      }
      await queryClient.invalidateQueries({ queryKey: ["rules", projectId] });
      router.push(`/p/${projectId}/rules/${created.id}`);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  };

  if (rules.isLoading) return <Loading lines={6} />;
  if (rules.error) return <ErrorState error={rules.error} />;
  const items = rules.data!.items;
  return (
    <>
      <div className="row-between" style={{ marginBottom: 16 }}>
        <p className="t-secondary measure" style={{ margin: 0 }}>
          Опубликованная версия неизменяема. Изменение создает новую версию со ссылкой на исходную; прошлые запуски продолжают ссылаться на старую.
        </p>
        {canEdit ? (
          <Dialog.Root open={open} onOpenChange={setOpen}>
            <Dialog.Trigger asChild>
              <Button variant="primary">
                <Plus size={18} aria-hidden /> Новое правило
              </Button>
            </Dialog.Trigger>
            <Dialog.Portal>
              <Dialog.Overlay className="overlay" />
              <Dialog.Content className="dialog">
                <Dialog.Title className="t-section">Новое правило</Dialog.Title>
                <Dialog.Description className="t-secondary" style={{ margin: "6px 0 16px" }}>
                  Начните с существующей версии или с пустого правила. Правило можно также описать словами в конструкторе.
                </Dialog.Description>
                <div className="stack">
                  <div className="field">
                    <label htmlFor="rname">Название</label>
                    <input id="rname" className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Например, Оплата подтвержденных решений, вариант 2" />
                  </div>
                  <div className="field">
                    <label htmlFor="rbase">Основа</label>
                    <select id="rbase" className="select" value={base} onChange={(e) => setBase(e.target.value)}>
                      <option value="">Пустое правило</option>
                      {items.map((r) => (
                        <option key={r.id} value={r.id}>
                          {r.name}, v{r.version}
                        </option>
                      ))}
                    </select>
                  </div>
                  {error ? <Notice tone="danger">{error}</Notice> : null}
                  <div className="row" style={{ justifyContent: "flex-end" }}>
                    <Dialog.Close asChild>
                      <Button variant="ghost">Отмена</Button>
                    </Dialog.Close>
                    <Button variant="primary" busy={busy} onClick={create}>
                      Создать черновик
                    </Button>
                  </div>
                </div>
              </Dialog.Content>
            </Dialog.Portal>
          </Dialog.Root>
        ) : null}
      </div>
      <div className="panel" style={{ padding: 0 }}>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Правило</th>
                <th className="r">Версия</th>
                <th>Происхождение</th>
                <th>Состояние</th>
                <th>Опубликовано</th>
              </tr>
            </thead>
            <tbody>
              {items.map((r) => (
                <tr key={r.id} data-link onClick={() => router.push(`/p/${projectId}/rules/${r.id}`)}>
                  <td style={{ maxWidth: 460 }}>
                    <Link href={`/p/${projectId}/rules/${r.id}`} onClick={(e) => e.stopPropagation()} style={{ fontWeight: 600 }} className="clamp-2">
                      {r.name}
                    </Link>
                    <div className="t-caption clamp-2">{r.source_text || r.description}</div>
                  </td>
                  <td className="r">v{r.version}</td>
                  <td className="t-secondary">{ORIGIN[r.origin] ?? r.origin}</td>
                  <td>{r.status === "published" ? <Pill tone="success">Опубликовано</Pill> : <Pill>Черновик</Pill>}</td>
                  <td className="t-secondary num">{dateTime(r.published_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
