"use client";

import { Play } from "lucide-react";
import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { useAnnounceWorkspace } from "@/components/Shell";
import { ButtonLink, ErrorState, Loading, Pill } from "@/components/ui";
import { ENV_LABELS } from "@/lib/format";
import { useProject } from "@/lib/queries";

export default function ProjectLayout({ children }: { children: ReactNode }) {
  const { project: id } = useParams<{ project: string }>();
  const pathname = usePathname();
  const project = useProject(id);
  useAnnounceWorkspace(project.data?.workspace_id);
  if (project.isLoading) return <Loading lines={6} />;
  if (project.error || !project.data) return <ErrorState error={project.error} onRetry={() => project.refetch()} />;
  const p = project.data;
  const base = `/p/${p.id}`;
  const tabs = [
    { href: base, label: "Обзор" },
    { href: `${base}/scenario`, label: "Сценарий" },
    { href: `${base}/rules`, label: "Правила" },
    { href: `${base}/agents`, label: "Агенты" },
    { href: `${base}/experiments`, label: "Испытания" },
    { href: `${base}/comparisons`, label: "Сравнения" },
  ];
  const current = (href: string) => (href === base ? pathname === base : pathname.startsWith(href));
  const canRun = p.role === "owner" || p.role === "admin" || p.role === "analyst";
  return (
    <>
      <nav className="crumbs" aria-label="Путь">
        <Link href={`/w/${p.workspace_id}/projects`}>Проекты</Link>
        <span aria-hidden>/</span>
        <span>{p.name}</span>
      </nav>
      <header className="page-head" style={{ marginBottom: 16 }}>
        <div style={{ minWidth: 0 }}>
          <h1 className="t-page clamp-2">{p.name}</h1>
          <div className="row" style={{ gap: 8, marginTop: 8 }}>
            <Pill>{ENV_LABELS[p.environment_id] ?? p.environment_id}</Pill>
            {p.is_demo ? <Pill tone="info">Учебный проект с демонстрационными данными</Pill> : null}
            {p.archived_at ? <Pill>В архиве</Pill> : null}
          </div>
        </div>
        {canRun ? (
          <ButtonLink href={`${base}/experiments/new`} variant="primary">
            <Play size={16} aria-hidden /> Новое испытание
          </ButtonLink>
        ) : null}
      </header>
      <nav className="tabs-list" aria-label="Разделы проекта">
        {tabs.map((tab) => (
          <Link key={tab.href} href={tab.href} aria-current={current(tab.href) ? "page" : undefined}>
            {tab.label}
          </Link>
        ))}
      </nav>
      {children}
    </>
  );
}
