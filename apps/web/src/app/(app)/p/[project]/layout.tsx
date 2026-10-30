"use client";
import * as Dropdown from "@radix-ui/react-dropdown-menu";
import { ArrowLeft, Settings2 } from "lucide-react";
import Link from "next/link";
import { useParams, usePathname, useRouter } from "next/navigation";
import type { ReactNode } from "react";
import { useAnnounceWorkspace } from "@/components/Shell";
import { ButtonLink, ErrorState, Loading } from "@/components/ui";
import { useProject } from "@/lib/queries";

const SETTINGS = [
  { path: "rules", label: "Правила награды" },
  { path: "scenario", label: "Задачи и условия" },
  { path: "agents", label: "Участники" },
  { path: "experiments", label: "Все проверки проекта" },
  { path: "comparisons", label: "Все сравнения" },
];

export default function ProjectLayout({ children }: { children: ReactNode }) {
  const { project: id } = useParams<{ project: string }>();
  const pathname = usePathname();
  const router = useRouter();
  const project = useProject(id);
  useAnnounceWorkspace(project.data?.workspace_id);
  if (project.isLoading) return <Loading />;
  if (project.error || !project.data) return <ErrorState error={project.error} onRetry={() => void project.refetch()} />;
  const p = project.data;
  const base = `/p/${id}`;
  const canRun = p.role !== "viewer" && !p.archived_at;
  const onOverview = pathname === base;
  return (
    <>
      <div className="project-bar">
        <Link className="back-link" style={{ marginBottom: 0 }} href={`/w/${p.workspace_id}/projects`}>
          <ArrowLeft size={16} aria-hidden /> Все проверки
        </Link>
        <div className="row" style={{ gap: 8 }}>
          <Dropdown.Root>
            <Dropdown.Trigger className="btn btn-secondary btn-compact">
              <Settings2 size={16} aria-hidden /> Настроить
            </Dropdown.Trigger>
            <Dropdown.Portal>
              <Dropdown.Content className="menu" align="end" sideOffset={8}>
                {SETTINGS.map((item) => (
                  <Dropdown.Item className="menu-item" key={item.path} onSelect={() => router.push(`${base}/${item.path}`)}>
                    {item.label}
                  </Dropdown.Item>
                ))}
              </Dropdown.Content>
            </Dropdown.Portal>
          </Dropdown.Root>
          {canRun && onOverview ? <ButtonLink compact variant="primary" href={`${base}/experiments/new`}>Проверить ещё раз</ButtonLink> : null}
        </div>
      </div>
      {p.archived_at ? <p className="t-caption">Проект в архиве</p> : null}
      {children}
    </>
  );
}
