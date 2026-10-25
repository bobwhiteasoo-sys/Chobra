"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Boxes, Headset, Waves } from "lucide-react";
import Image from "next/image";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState, type FormEvent } from "react";

import { Button, Notice } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { useMe } from "@/lib/queries";
import type { Project, Workspace } from "@/lib/types";

const TEMPLATES = [
  {
    env: "supportdesk",
    icon: Headset,
    title: "SupportDesk",
    problem: "Премия поддержки платит за закрытые обращения. Станут ли закрывать нерешенное?",
  },
  {
    env: "taskboard",
    icon: Boxes,
    title: "TaskBoard",
    problem: "Команду премируют за задачи, отмеченные готовыми. Совпадет ли это с принятыми результатами?",
  },
  {
    env: "resourcecommons",
    icon: Waves,
    title: "ResourceCommons",
    problem: "Каждый получает награду за изъятый ресурс. Сохранится ли общий запас до конца горизонта?",
  },
];

const STEPS = [
  { title: "Что хотим получить", body: "Желаемый результат описывается отдельно от правила: например, решенные и подтвержденные клиентом проблемы." },
  { title: "За что награждаем", body: "Правило начисления — отдельная формула: за какое событие, сколько и сколько раз на одну проблему." },
  { title: "Как проверяем", body: "Движок сам считает награду и фактический результат и сравнивает их. Расхождение становится проверенным контрпримером." },
];

function Onboarding() {
  const me = useMe();
  const router = useRouter();
  const params = useSearchParams();
  const queryClient = useQueryClient();
  const [workspaceName, setWorkspaceName] = useState("");
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [step, setStep] = useState<number | null>(null);
  const [chosen, setChosen] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const needsWorkspace = !workspace && (params.get("new") === "1" || (me.data && me.data.workspaces.length === 0));
  const currentWorkspace = workspace?.id ?? me.data?.last_workspace_id ?? me.data?.workspaces[0]?.id;

  const createWorkspace = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const created = await api<Workspace>("/workspaces", { body: { name: workspaceName } });
      setWorkspace(created);
      await queryClient.invalidateQueries({ queryKey: ["me"] });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const createProject = async (env: string) => {
    if (!currentWorkspace) return;
    setBusy(true);
    setError(null);
    try {
      const template = TEMPLATES.find((t) => t.env === env)!;
      const project = await api<Project>("/projects", { body: { workspace_id: currentWorkspace, name: `Учебный проект: ${template.title}`, environment_id: env, is_demo: true } });
      router.push(`/p/${project.id}/experiments/new?preset=first`);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  };

  return (
    <main className="onboarding">
      <header className="row" style={{ marginBottom: 32 }}>
        <Image src="/brand/chobra-64.png" alt="" width={36} height={36} style={{ borderRadius: 10 }} />
        <span style={{ fontWeight: 700, fontSize: 18, color: "var(--color-accent-primary)" }}>Chobra</span>
      </header>
      {needsWorkspace ? (
        <form onSubmit={createWorkspace} className="stack" style={{ maxWidth: 480 }}>
          <h1 className="t-page">Создайте рабочее пространство</h1>
          <p className="t-secondary">В пространстве живут проекты, участники и лимиты расходов.</p>
          <div className="field">
            <label htmlFor="ws">Название</label>
            <input id="ws" className="input" value={workspaceName} onChange={(e) => setWorkspaceName(e.target.value)} placeholder="Например, Отдел поддержки" required />
          </div>
          {error ? <p className="field error" role="alert">{error}</p> : null}
          <Button variant="primary" type="submit" busy={busy}>
            Создать пространство
          </Button>
        </form>
      ) : step === null ? (
        <section className="stack-24">
          <div>
            <h1 className="t-page">С какого вопроса начнем</h1>
            <p className="t-secondary measure" style={{ marginTop: 8 }}>
              Учебный проект создается из шаблона и помечается как демонстрационный. Первое испытание идет на сценарных агентах и не тратит вызовы модели.
            </p>
          </div>
          <div className="template-grid" role="radiogroup" aria-label="Шаблон">
            {TEMPLATES.map((t) => (
              <button key={t.env} type="button" role="radio" aria-checked={chosen === t.env} className="template-option" onClick={() => setChosen(t.env)}>
                <t.icon size={22} strokeWidth={1.75} aria-hidden />
                <span className="t-panel">{t.title}</span>
                <span className="t-secondary">{t.problem}</span>
              </button>
            ))}
          </div>
          {error ? <Notice tone="danger">{error}</Notice> : null}
          <div className="row">
            <Button variant="primary" disabled={!chosen} onClick={() => setStep(0)}>
              Продолжить
            </Button>
            <Button variant="ghost" disabled={!chosen} busy={busy} onClick={() => chosen && createProject(chosen)}>
              Пропустить обучение
            </Button>
          </div>
        </section>
      ) : (
        <section className="stack-24" style={{ maxWidth: 560 }} aria-live="polite">
          <p className="t-caption">
            Шаг {step + 1} из {STEPS.length}
          </p>
          <h1 className="t-page">{STEPS[step]!.title}</h1>
          <p className="t-secondary" style={{ fontSize: 17, lineHeight: "26px" }}>
            {STEPS[step]!.body}
          </p>
          <div className="row">
            {step < STEPS.length - 1 ? (
              <Button variant="primary" onClick={() => setStep(step + 1)}>
                Дальше
              </Button>
            ) : (
              <Button variant="primary" busy={busy} onClick={() => chosen && createProject(chosen)}>
                Создать учебный проект
              </Button>
            )}
            <Button variant="ghost" busy={busy} onClick={() => chosen && createProject(chosen)}>
              Пропустить
            </Button>
          </div>
          {error ? <Notice tone="danger">{error}</Notice> : null}
        </section>
      )}
    </main>
  );
}

export default function OnboardingPage() {
  return (
    <Suspense>
      <Onboarding />
    </Suspense>
  );
}
