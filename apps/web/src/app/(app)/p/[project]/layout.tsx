"use client";
import * as Dropdown from "@radix-ui/react-dropdown-menu";
import { ChevronDown } from "lucide-react";
import Link from "next/link";
import { useParams, usePathname, useRouter } from "next/navigation";
import type { ReactNode } from "react";
import { useAnnounceWorkspace } from "@/components/Shell";
import { ButtonLink, ErrorState, Loading } from "@/components/ui";
import { useProject } from "@/lib/queries";
export default function ProjectLayout({children}:{children:ReactNode}){
 const {project:id}=useParams<{project:string}>();const pathname=usePathname();const router=useRouter();const project=useProject(id);useAnnounceWorkspace(project.data?.workspace_id);
 if(project.isLoading)return <Loading/>;if(project.error||!project.data)return <ErrorState error={project.error} onRetry={()=>void project.refetch()}/>;
 const p=project.data;const base=`/p/${id}`;const canRun=p.role!=="viewer"&&!p.archived_at;const newCheck=pathname.endsWith("/experiments/new");
 return <><Link className="back-link" href={`/w/${p.workspace_id}/projects`}>Все проекты</Link><header className="page-head project-title"><div><h1 className="t-page">{p.name}</h1>{p.archived_at?<p className="t-caption">Проект в архиве</p>:null}</div>{canRun&&!newCheck?<ButtonLink href={`${base}/experiments/new`} variant="primary">Проверить правила</ButtonLink>:null}</header>
 <nav className="project-nav" aria-label="Разделы проекта"><Link href={base} aria-current={pathname===base?"page":undefined}>Обзор</Link><Link href={`${base}/experiments`} aria-current={pathname.includes("/experiments")&&!newCheck?"page":undefined}>Результаты</Link><Dropdown.Root><Dropdown.Trigger className="text-button project-settings">Настроить проект <ChevronDown size={14}/></Dropdown.Trigger><Dropdown.Portal><Dropdown.Content className="menu" align="start" sideOffset={8}>{[{path:"rules",label:"Правила награды"},{path:"scenario",label:"Задачи и условия"},{path:"agents",label:"Виртуальные участники"},{path:"comparisons",label:"Все сравнения"}].map(item=><Dropdown.Item className="menu-item" key={item.path} onSelect={()=>router.push(`${base}/${item.path}`)}>{item.label}</Dropdown.Item>)}</Dropdown.Content></Dropdown.Portal></Dropdown.Root></nav>{children}</>;
}
