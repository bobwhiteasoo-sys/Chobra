"use client";

import * as Dropdown from "@radix-ui/react-dropdown-menu";
import { useQueryClient } from "@tanstack/react-query";
import { ChevronDown } from "lucide-react";
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
    // An address saved from another server or a removed workspace must not strand the visitor.
    if (params.workspace && !known.has(params.workspace) && chosen) router.replace(`/w/${chosen}/projects`);
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

  if (!me.data || !workspaceId || (params.workspace && !me.data.workspaces.some((w) => w.id === params.workspace))) {
    return (
      <main className="main" style={{ maxWidth: 720 }}>
        {me.error && !(me.error instanceof ApiError && me.error.status === 401) ? <p className="t-secondary">Не удалось связаться с сервером Chobra.</p> : <Loading />}
      </main>
    );
  }

  const workspace = me.data.workspaces.find((w) => w.id === workspaceId) ?? me.data.workspaces[0]!;
  const logout = async () => {
    await api("/auth/logout", { body: {} });
    queryClient.clear();
    router.replace("/login");
  };

  return (
    <WorkspaceContext.Provider value={context}>
      <div className="simple-shell">
        <header className="topbar">
          <Link href={`/w/${workspace.id}/projects`} className="brand" aria-label="Chobra, на главный экран">
            <Image src="/brand/chobra-mark-transparent.png" alt="" width={30} height={29} priority /><span>Chobra</span>
          </Link>
          <div className="topbar-right">
            <Link className="topbar-link" href="/help" target="_blank" rel="noopener noreferrer">Помощь</Link>
            <Dropdown.Root><Dropdown.Trigger asChild><button className="account-button" aria-label="Аккаунт и настройки"><span className="account-avatar" aria-hidden>{me.data.display_name.trim().charAt(0).toUpperCase()}</span><span className="account-name">{me.data.display_name}</span><ChevronDown size={14} aria-hidden/></button></Dropdown.Trigger>
              <Dropdown.Portal><Dropdown.Content className="menu" align="end" sideOffset={10}>
                <Dropdown.Item className="menu-item" onSelect={()=>router.push(`/w/${workspace.id}/runs`)}>Все запуски</Dropdown.Item>
                <Dropdown.Item className="menu-item" onSelect={()=>router.push(`/w/${workspace.id}/reports`)}>Отчёты</Dropdown.Item>
                <Dropdown.Item className="menu-item" onSelect={()=>router.push("/settings/workspace")}>Настройки</Dropdown.Item>
                <Dropdown.Separator className="divider"/>
                {me.data.workspaces.length>1?<>{me.data.workspaces.map(w=><Dropdown.Item className="menu-item" key={w.id} onSelect={()=>{context.setWorkspaceId(w.id);router.push(`/w/${w.id}/projects`);}}>{w.name}</Dropdown.Item>)}<Dropdown.Separator className="divider"/></>:null}
                <Dropdown.Item className="menu-item" onSelect={()=>router.push("/onboarding?new=1")}>Новое пространство</Dropdown.Item>
                <Dropdown.Item className="menu-item" onSelect={()=>void logout()}>Выйти</Dropdown.Item>
              </Dropdown.Content></Dropdown.Portal>
            </Dropdown.Root>
          </div>
        </header>
        <main className="simple-main" id="main">{children}</main>
      </div>
    </WorkspaceContext.Provider>
  );
}
