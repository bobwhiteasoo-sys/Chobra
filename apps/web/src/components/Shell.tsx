"use client";

import * as Dropdown from "@radix-ui/react-dropdown-menu";
import { useQueryClient } from "@tanstack/react-query";
import { BookOpen, ChevronsUpDown, FileText, FlaskConical, FolderKanban, LogOut, Plus, Settings, UserRound } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { useParams, usePathname, useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { api, ApiError } from "@/lib/api";
import { useMe } from "@/lib/queries";

import { Loading } from "./ui";

type WorkspaceCtx = { workspaceId: string | null; setWorkspaceId: (id: string) => void };
const WorkspaceContext = createContext<WorkspaceCtx>({ workspaceId: null, setWorkspaceId: () => undefined });
export const useCurrentWorkspace = () => useContext(WorkspaceContext);

/** Pages that know their workspace (a project page) announce it so navigation stays in context. */
export function useAnnounceWorkspace(id: string | undefined) {
  const { workspaceId, setWorkspaceId } = useCurrentWorkspace();
  useEffect(() => {
    if (id && id !== workspaceId) setWorkspaceId(id);
  }, [id, workspaceId, setWorkspaceId]);
}

const STORAGE_KEY = "chobra.workspace";

function readStored(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function Shell({ children }: { children: ReactNode }) {
  const me = useMe();
  const router = useRouter();
  const pathname = usePathname();
  const params = useParams<{ workspace?: string }>();
  const queryClient = useQueryClient();
  const [workspaceId, setWorkspace] = useState<string | null>(null);

  useEffect(() => {
    if (me.error instanceof ApiError && me.error.status === 401) router.replace(`/login?next=${encodeURIComponent(pathname)}`);
  }, [me.error, pathname, router]);

  useEffect(() => {
    if (!me.data) return;
    if (!me.data.workspaces.length) {
      router.replace("/onboarding");
      return;
    }
    const known = new Set(me.data.workspaces.map((w) => w.id));
    const candidates = [params.workspace, workspaceId, readStored(), me.data.last_workspace_id, me.data.workspaces[0]?.id];
    const chosen = candidates.find((id): id is string => Boolean(id && known.has(id))) ?? null;
    if (chosen !== workspaceId) setWorkspace(chosen);
  }, [me.data, params.workspace, workspaceId, router]);

  const context = useMemo<WorkspaceCtx>(
    () => ({
      workspaceId,
      setWorkspaceId: (id: string) => {
        setWorkspace(id);
        try {
          window.localStorage.setItem(STORAGE_KEY, id);
        } catch {
          /* storage may be unavailable */
        }
        void api("/me/last-workspace", { body: { workspace_id: id } }).catch(() => undefined);
      },
    }),
    [workspaceId],
  );

  if (!me.data || !workspaceId) {
    return (
      <main className="main" style={{ maxWidth: 720 }}>
        {me.error && !(me.error instanceof ApiError && me.error.status === 401) ? <p className="t-secondary">Не удалось связаться с сервером Chobra.</p> : <Loading />}
      </main>
    );
  }

  const workspace = me.data.workspaces.find((w) => w.id === workspaceId) ?? me.data.workspaces[0]!;
  const links = [
    { href: `/w/${workspace.id}/projects`, label: "Проекты", icon: FolderKanban, match: ["/w/", "/p/"] },
    { href: `/w/${workspace.id}/templates`, label: "Шаблоны", icon: BookOpen, match: ["/templates"] },
    { href: `/w/${workspace.id}/runs`, label: "Испытания", icon: FlaskConical, match: ["/runs", "/experiments", "/findings", "/comparisons"] },
    { href: `/w/${workspace.id}/reports`, label: "Отчеты", icon: FileText, match: ["/reports"] },
    { href: "/settings/workspace", label: "Настройки", icon: Settings, match: ["/settings"] },
  ];
  const active = (link: (typeof links)[number]) => {
    if (pathname === link.href) return true;
    if (link.label === "Проекты") return (pathname.startsWith("/w/") && pathname.endsWith("/projects")) || pathname.startsWith("/p/");
    return link.match.some((m) => pathname.includes(m)) && !(link.label !== "Проекты" && pathname.endsWith("/projects"));
  };

  const logout = async () => {
    await api("/auth/logout", { body: {} });
    queryClient.clear();
    router.replace("/login");
  };

  return (
    <WorkspaceContext.Provider value={context}>
      <div className="simple-shell">
        <header className="topbar">
          <Link href={`/w/${workspace.id}/projects`} className="brand" aria-label="Chobra, к проектам">
            <Image src="/brand/chobra-mark-transparent.png" alt="" width={30} height={29} priority /><span>Chobra</span>
          </Link>
          <nav className="topnav" aria-label="Основная навигация">
            {[links[0]!, links[2]!, links[3]!].map(link=><Link key={link.href} href={link.href} aria-current={active(link)?"page":undefined}>{link.label}</Link>)}
            <Link href="/help">Как пользоваться</Link>
          </nav>
          <Dropdown.Root><Dropdown.Trigger asChild><button className="account-button" aria-label="Аккаунт и настройки">{me.data.display_name}<ChevronsUpDown size={14}/></button></Dropdown.Trigger>
            <Dropdown.Portal><Dropdown.Content className="menu" align="end" sideOffset={10}>
              {me.data.workspaces.map(w=><Dropdown.Item className="menu-item" key={w.id} onSelect={()=>{context.setWorkspaceId(w.id);router.push(`/w/${w.id}/projects`);}}>{w.name}</Dropdown.Item>)}
              <Dropdown.Separator className="divider"/>
              <Dropdown.Item className="menu-item" onSelect={()=>router.push("/settings/workspace")}>Настройки</Dropdown.Item>
              <Dropdown.Item className="menu-item" onSelect={()=>router.push("/settings/profile")}>Мой аккаунт</Dropdown.Item>
              <Dropdown.Item className="menu-item" onSelect={()=>router.push("/onboarding?new=1")}>Новое пространство</Dropdown.Item>
              <Dropdown.Item className="menu-item" onSelect={()=>void logout()}>Выйти</Dropdown.Item>
            </Dropdown.Content></Dropdown.Portal>
          </Dropdown.Root>
        </header>
        <main className="simple-main" id="main">{children}</main>
        <footer className="app-footer">Chobra · Проверка правил в симуляции <Link href="/help">Помощь</Link></footer>
      </div>
    </WorkspaceContext.Provider>
  );
}
