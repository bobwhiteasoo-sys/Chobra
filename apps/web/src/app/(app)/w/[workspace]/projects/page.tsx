"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { useQueryClient } from "@tanstack/react-query";
import { Plus, Search } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useDeferredValue, useState, type FormEvent } from "react";

import { useCurrentWorkspace } from "@/components/Shell";
import { Button, EmptyState, ErrorState, Loading, Notice, Pill, RunStatus } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { dateTime, ENV_LABELS } from "@/lib/format";
import { useEnvironments, useProjects } from "@/lib/queries";
import type { Project } from "@/lib/types";

export default function ProjectsPage() {
  const { workspace } = useParams<{ workspace: string }>();
  const { workspaceId } = useCurrentWorkspace();
  const [q, setQ] = useState("");
  const [environment, setEnvironment] = useState("");
  const [archived, setArchived] = useState(false);
  const [mine, setMine] = useState(false);
  const deferredQ = useDeferredValue(q);
  const projects = useProjects(workspace ?? workspaceId ?? undefined, { q: deferredQ, environment, archived, owner: mine ? "me" : "" });
  const filtered = Boolean(q || environment || archived || mine);

  return (
    <>
      <header className="page-head">
        <div>
          <h1 className="t-page">Проекты</h1>
          <p className="lead">Один проект отвечает на один вопрос: например, как изменить систему премий поддержки.</p>
        </div>
        <NewProject workspaceId={workspace} />
      </header>
      <div className="row" style={{ marginBottom: 20 }}>
        <div className="input-unit" style={{ minWidth: 260, flex: "1 1 260px", maxWidth: 420, position: "relative" }}>
          <label htmlFor="q" className="sr-only">
            Поиск по названию и тегам
          </label>
          <Search size={16} aria-hidden style={{ position: "absolute", left: 12, top: 14, color: "var(--color-text-muted)" }} />
          <input id="q" className="input" style={{ paddingLeft: 36 }} placeholder="Поиск по названию и тегам" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <label className="sr-only" htmlFor="env">
          Среда
        </label>
        <select id="env" className="select" style={{ width: 200 }} value={environment} onChange={(e) => setEnvironment(e.target.value)}>
          <option value="">Все среды</option>
          {Object.entries(ENV_LABELS).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
        <div className="segmented" role="group" aria-label="Фильтры">
          <button type="button" aria-pressed={!archived} onClick={() => setArchived(false)}>
            Активные
          </button>
          <button type="button" aria-pressed={archived} onClick={() => setArchived(true)}>
            Архив
          </button>
          <button type="button" aria-pressed={mine} onClick={() => setMine(!mine)}>
            Мои
          </button>
        </div>
      </div>
      {projects.isLoading ? (
        <Loading lines={5} />
      ) : projects.error ? (
        <ErrorState error={projects.error} onRetry={() => projects.refetch()} />
      ) : !projects.data?.items.length ? (
        filtered ? (
          <EmptyState title="Ничего не найдено">Измените поиск или фильтры.</EmptyState>
        ) : (
          <EmptyState title="Проектов пока нет" action={<NewProject workspaceId={workspace} />}>
            Создайте проект из шаблона: в нем уже будут сценарий, три стартовых правила и профили агентов.
          </EmptyState>
        )
      ) : (
        <div className="panel" style={{ padding: 0 }}>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Проект</th>
                  <th>Среда</th>
                  <th>Последняя серия</th>
                  <th>Изменен</th>
                </tr>
              </thead>
              <tbody>
                {projects.data.items.map((p) => (
                  <ProjectRow key={p.id} project={p} />
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  );
}

function ProjectRow({ project }: { project: Project }) {
  const router = useRouter();
  return (
    <tr data-link onClick={() => router.push(`/p/${project.id}`)}>
      <td style={{ maxWidth: 420 }}>
        <Link href={`/p/${project.id}`} style={{ fontWeight: 600 }} className="clamp-2" onClick={(e) => e.stopPropagation()}>
          {project.name}
        </Link>
        <div className="row" style={{ gap: 6, marginTop: 4 }}>
          {project.is_demo ? <Pill>Учебный</Pill> : null}
          {project.restricted ? <Pill>Ограниченный доступ</Pill> : null}
          {project.tags.map((t) => (
            <Pill key={t}>{t}</Pill>
          ))}
        </div>
      </td>
      <td>{ENV_LABELS[project.environment_id] ?? project.environment_id}</td>
      <td>{project.last_batch ? <RunStatus status={project.last_batch.status} /> : <span className="t-muted">Испытаний не было</span>}</td>
      <td className="t-secondary num">{dateTime(project.updated_at)}</td>
    </tr>
  );
}

function NewProject({ workspaceId }: { workspaceId: string | undefined }) {
  const envs = useEnvironments();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [env, setEnv] = useState("supportdesk");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const project = await api<Project>("/projects", { body: { workspace_id: workspaceId, name, environment_id: env } });
      await queryClient.invalidateQueries({ queryKey: ["projects"] });
      router.push(`/p/${project.id}`);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  };
  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        <Button variant="primary">
          <Plus size={18} aria-hidden /> Новый проект
        </Button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="overlay" />
        <Dialog.Content className="dialog">
          <Dialog.Title className="t-section">Новый проект</Dialog.Title>
          <Dialog.Description className="t-secondary" style={{ margin: "6px 0 20px" }}>
            Проект создается из шаблона среды: сценарий, стартовые правила и профили агентов появятся сразу.
          </Dialog.Description>
          <form onSubmit={submit} className="stack">
            <div className="field">
              <label htmlFor="pname">Название</label>
              <input id="pname" className="input" value={name} onChange={(e) => setName(e.target.value)} required maxLength={200} />
            </div>
            <fieldset className="stack" style={{ border: 0, padding: 0, margin: 0 }}>
              <legend className="field label" style={{ marginBottom: 6 }}>
                Среда
              </legend>
              {envs.data?.items.map((e) => (
                <label key={e.name} className="check" style={{ alignItems: "flex-start" }}>
                  <input type="radio" name="env" value={e.name} checked={env === e.name} onChange={() => setEnv(e.name)} />
                  <span>
                    <strong>{e.template.title}</strong>
                    <span className="t-caption" style={{ display: "block" }}>
                      {e.template.problem}
                    </span>
                  </span>
                </label>
              ))}
            </fieldset>
            {error ? <Notice tone="danger">{error}</Notice> : null}
            <div className="row" style={{ justifyContent: "flex-end" }}>
              <Dialog.Close asChild>
                <Button variant="ghost" type="button">
                  Отмена
                </Button>
              </Dialog.Close>
              <Button variant="primary" type="submit" busy={busy}>
                Создать проект
              </Button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
