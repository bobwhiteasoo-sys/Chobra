"use client";

import { useQuery } from "@tanstack/react-query";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";

import { Button, ErrorState, Loading, Notice, Pill } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { points } from "@/lib/format";
import type { Project, RuleExample, RuleTree, Validation } from "@/lib/types";

type Template = {
  environment: string;
  title: string;
  problem: string;
  description: string;
  desired_outcome: string;
  starting_rules: { key: string; name: string; description: string; source_text: string; tree: RuleTree; validation: Validation; examples: RuleExample[] }[];
};

export default function TemplatesPage() {
  const { workspace } = useParams<{ workspace: string }>();
  const router = useRouter();
  const templates = useQuery({ queryKey: ["templates"], queryFn: () => api<{ items: Template[] }>("/templates"), staleTime: Infinity });
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const create = async (template: Template) => {
    setBusy(template.environment);
    setError(null);
    try {
      const project = await api<Project>("/projects", { body: { workspace_id: workspace, name: `${template.title}: новый проект`, environment_id: template.environment } });
      router.push(`/p/${project.id}`);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(null);
    }
  };

  if (templates.isLoading) return <Loading lines={6} />;
  if (templates.error) return <ErrorState error={templates.error} />;
  return (
    <>
      <header className="page-head">
        <div>
          <h1 className="t-page">Шаблоны</h1>
          <p className="lead">Три сертифицированные среды. Стартовые правила — кандидаты для испытания, а не рекомендации.</p>
        </div>
      </header>
      {error ? <Notice tone="danger">{error}</Notice> : null}
      <div className="stack-24">
        {templates.data!.items.map((t) => (
          <section key={t.environment} className="panel">
            <div className="row-between" style={{ alignItems: "flex-start" }}>
              <div className="measure">
                <h2 className="t-section">{t.title}</h2>
                <p className="t-secondary" style={{ margin: "6px 0" }}>
                  {t.description}
                </p>
                <p style={{ margin: 0 }}>
                  <span className="t-muted">Желаемый результат: </span>
                  {t.desired_outcome}
                </p>
              </div>
              <Button variant="primary" busy={busy === t.environment} onClick={() => create(t)}>
                Создать проект
              </Button>
            </div>
            <div className="table-wrap" style={{ marginTop: 16 }}>
              <table className="table">
                <thead>
                  <tr>
                    <th>Правило</th>
                    <th>Единица учета</th>
                    <th className="r">Обычное событие</th>
                    <th className="r">Повтор по той же единице</th>
                    <th className="r">Пограничный случай</th>
                  </tr>
                </thead>
                <tbody>
                  {t.starting_rules.map((r) => {
                    const ex = (kind: string) => r.examples.find((e) => e.kind === kind);
                    return (
                      <tr key={r.key}>
                        <td style={{ maxWidth: 360 }}>
                          <strong>
                            {r.key} {r.name}
                          </strong>
                          <div className="t-caption">{r.source_text}</div>
                          {r.validation.warnings.length ? (
                            <div style={{ marginTop: 6 }}>
                              <Pill tone="accent">Предупреждений: {r.validation.warnings.length}</Pill>
                            </div>
                          ) : null}
                        </td>
                        <td className="t-secondary">{r.validation.unit_of_account}</td>
                        {["ordinary", "unit_repeat", "boundary"].map((kind) => (
                          <td key={kind} className="r">
                            {ex(kind)?.payout ? `${points(ex(kind)!.payout)} очк.` : <span className="t-muted">0</span>}
                          </td>
                        ))}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
        ))}
      </div>
    </>
  );
}
