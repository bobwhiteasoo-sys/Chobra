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
      <div className="shell">
        <aside className="sidebar" aria-label="Основная навигация">
          <Link href={`/w/${workspace.id}/projects`} className="brand" aria-label="Chobra, к проектам">
            <Image src="/brand/chobra-64.png" alt="" width={32} height={32} priority />
            <span className="label">Chobra</span>
          </Link>
          <Dropdown.Root>
            <Dropdown.Trigger asChild>
              <button className="ws-switch" type="button" aria-label={`Рабочее пространство: ${workspace.name}. Сменить`}>
                <span className="ws-avatar" aria-hidden>
                  {workspace.name.slice(0, 1).toUpperCase()}
                </span>
                <span className="label" style={{ flex: 1, minWidth: 0 }}>
                  <span className="clamp-2" style={{ fontWeight: 600, fontSize: 14 }}>
                    {workspace.name}
                  </span>
                </span>
                <ChevronsUpDown className="label" size={16} aria-hidden />
              </button>
            </Dropdown.Trigger>
            <Dropdown.Portal>
              <Dropdown.Content className="menu" align="start" sideOffset={6}>
                {me.data.workspaces.map((w) => (
                  <Dropdown.Item key={w.id} className="menu-item" onSelect={() => { context.setWorkspaceId(w.id); router.push(`/w/${w.id}/projects`); }}>
                    <span className="ws-avatar" aria-hidden>{w.name.slice(0, 1).toUpperCase()}</span>
                    <span style={{ flex: 1 }}>{w.name}</span>
                    <span className="t-caption">{w.role}</span>
                  </Dropdown.Item>
                ))}
                <Dropdown.Separator className="divider" style={{ margin: "6px 0" }} />
                <Dropdown.Item className="menu-item" onSelect={() => router.push("/onboarding?new=1")}>
                  <Plus size={16} aria-hidden /> Новое пространство
                </Dropdown.Item>
              </Dropdown.Content>
            </Dropdown.Portal>
          </Dropdown.Root>
          <nav className="nav">
            {links.map((link) => (
              <Link key={link.href} href={link.href} className="nav-link" aria-current={active(link) ? "page" : undefined}>
                <link.icon size={18} strokeWidth={1.75} aria-hidden />
                <span className="label">{link.label}</span>
              </Link>
            ))}
          </nav>
          <div className="nav-group" style={{ marginTop: "auto" }}>
            {me.data.auth_mode === "dev" ? <div className="dev-badge">Вход в режиме разработки. Поставщик OIDC не подключен.</div> : null}
            <Link href="/settings/profile" className="nav-link" aria-current={pathname === "/settings/profile" ? "page" : undefined}>
              <UserRound size={18} strokeWidth={1.75} aria-hidden />
              <span className="label">{me.data.display_name}</span>
            </Link>
            <button type="button" className="nav-link" onClick={logout} style={{ border: 0, background: "transparent", cursor: "pointer" }}>
              <LogOut size={18} strokeWidth={1.75} aria-hidden />
              <span className="label">Выйти</span>
            </button>
          </div>
        </aside>
        <main className="main" id="main">
          {children}
        </main>
        <nav className="mobile-nav" aria-label="Навигация">
          {[links[0]!, links[2]!, links[3]!, { href: "/settings/profile", label: "Профиль", icon: UserRound, match: ["/settings"] }].map((link) => (
            <Link key={link.href} href={link.href} aria-current={active(link) ? "page" : undefined}>
              <link.icon size={20} strokeWidth={1.75} aria-hidden />
              {link.label}
            </Link>
          ))}
        </nav>
      </div>
    </WorkspaceContext.Provider>
  );
}
