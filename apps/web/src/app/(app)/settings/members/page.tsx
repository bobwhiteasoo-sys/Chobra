"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { useCurrentWorkspace } from "@/components/Shell";
import { Button, EmptyState, ErrorState, Loading, Notice, useToast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { useMe } from "@/lib/queries";

type Member = { id: string; user_id: string; display_name: string; email: string; role: "owner" | "admin" | "analyst" | "viewer"; status: string };
type MemberRole = Exclude<Member["role"], "owner">;
const ROLE_NAME: Record<Member["role"], string> = { owner: "Владелец", admin: "Администратор", analyst: "Аналитик", viewer: "Наблюдатель" };

export default function MembersSettingsPage() {
  const { workspaceId } = useCurrentWorkspace();
  const me = useMe();
  const queryClient = useQueryClient();
  const toast = useToast();
  const role = me.data?.workspaces.find((workspace) => workspace.id === workspaceId)?.role;
  const canManage = role === "owner" || role === "admin";
  const isOwner = role === "owner";
  const members = useQuery({
    queryKey: ["workspace-members", workspaceId],
    queryFn: () => api<{ items: Member[] }>(`/workspaces/${workspaceId}/members`),
    enabled: Boolean(workspaceId),
  });
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [inviteRole, setInviteRole] = useState<MemberRole>("analyst");
  const [busy, setBusy] = useState<string | null>(null);

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["workspace-members", workspaceId] });
  };

  const invite = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!workspaceId) return;
    setBusy("invite");
    try {
      await api<Member>(`/workspaces/${workspaceId}/members`, { body: { email: email.trim(), role: inviteRole, ...(displayName.trim() ? { display_name: displayName.trim() } : {}) } });
      setEmail("");
      setDisplayName("");
      await refresh();
      toast({ title: "Участник добавлен", tone: "success" });
    } catch (error) {
      toast({ title: "Не удалось добавить участника", body: errorMessage(error), tone: "danger" });
    } finally {
      setBusy(null);
    }
  };

  const changeRole = async (member: Member, nextRole: MemberRole) => {
    setBusy(member.id);
    try {
      await api(`/members/${member.id}`, { method: "PATCH", body: { role: nextRole } });
      await refresh();
      toast({ title: "Роль участника обновлена", tone: "success" });
    } catch (error) {
      toast({ title: "Не удалось изменить роль", body: errorMessage(error), tone: "danger" });
    } finally {
      setBusy(null);
    }
  };

  const remove = async (member: Member) => {
    setBusy(member.id);
    try {
      await api(`/members/${member.id}`, { method: "DELETE" });
      await refresh();
      toast({ title: "Доступ участника отозван", tone: "success" });
    } catch (error) {
      toast({ title: "Не удалось отозвать доступ", body: errorMessage(error), tone: "danger" });
    } finally {
      setBusy(null);
    }
  };

  if (members.isLoading || me.isLoading) return <Loading lines={6} />;
  if (members.error) return <ErrorState error={members.error} onRetry={() => members.refetch()} />;
  const rows = members.data?.items ?? [];
  const activeOwners = rows.filter((member) => member.role === "owner" && member.status === "active").length;

  return (
    <>
      <header className="page-head">
        <div>
          <h1 className="t-page">Участники</h1>
          <p className="lead">Доступ к рабочему пространству и роли участников.</p>
        </div>
      </header>
      {!canManage ? <Notice title="Управление доступно администраторам и владельцам">Вы можете просматривать участников. Для приглашений и изменения ролей нужна роль администратора или владельца.</Notice> : null}
      {canManage ? (
        <form className="panel stack" onSubmit={invite}>
          <div>
            <h2 className="t-panel">Добавить участника</h2>
            <p className="t-caption" style={{ margin: "4px 0 0" }}>Пользователь получит доступ по указанному адресу. Роль владельца можно передать отдельно в настройках пространства.</p>
          </div>
          <div className="settings-fields">
            <div className="field">
              <label htmlFor="member-email">Электронная почта</label>
              <input id="member-email" className="input" type="email" autoComplete="email" maxLength={200} required value={email} onChange={(event) => setEmail(event.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="member-name">Имя, необязательно</label>
              <input id="member-name" className="input" maxLength={120} value={displayName} onChange={(event) => setDisplayName(event.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="member-role">Роль</label>
              <select id="member-role" className="select" value={inviteRole} onChange={(event) => setInviteRole(event.target.value as MemberRole)}>
                <option value="admin">Администратор</option>
                <option value="analyst">Аналитик</option>
                <option value="viewer">Наблюдатель</option>
              </select>
            </div>
          </div>
          <div className="settings-actions"><Button type="submit" variant="primary" busy={busy === "invite"}>Добавить участника</Button></div>
        </form>
      ) : null}
      <section className="panel stack">
        <div>
          <h2 className="t-panel">Список участников</h2>
          <p className="t-caption" style={{ margin: "4px 0 0" }}>Владелец может управлять ролями администраторов. Администратор не может менять роль администратора или владельца.</p>
        </div>
        {rows.length === 0 ? <EmptyState title="Участников пока нет" /> : (
          <div>
            {rows.map((member) => {
              const canChangeRole = canManage && member.status === "active" && member.role !== "owner" && (isOwner || member.role !== "admin");
              const canRemove = canManage && member.status === "active" && !(member.user_id === me.data?.id && member.role === "owner");
              const isLastOwner = member.role === "owner" && activeOwners <= 1;
              return (
                <article key={member.id} className="settings-member">
                  <div className="settings-member-identity">
                    <strong>{member.display_name}</strong>
                    <div className="t-caption">{member.email}{member.status !== "active" ? ` · ${member.status === "revoked" ? "доступ отозван" : member.status}` : ""}</div>
                  </div>
                  {canChangeRole ? (
                    <div className="field">
                      <label className="sr-only" htmlFor={`role-${member.id}`}>Роль для {member.display_name}</label>
                      <select id={`role-${member.id}`} className="select" value={member.role} disabled={busy === member.id} onChange={(event) => void changeRole(member, event.target.value as MemberRole)}>
                        <option value="admin">Администратор</option><option value="analyst">Аналитик</option><option value="viewer">Наблюдатель</option>
                      </select>
                    </div>
                  ) : <span className="t-secondary">{ROLE_NAME[member.role]}</span>}
                  <div className="settings-member-actions">
                    {canRemove ? <Button compact variant="danger" busy={busy === member.id} disabled={isLastOwner} title={isLastOwner ? "В пространстве должен остаться хотя бы один владелец" : undefined} onClick={() => void remove(member)}>Отозвать</Button> : null}
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </section>
      <Notice tone="warn" title="Владельцы">
        В пространстве должен оставаться хотя бы один владелец. Удаление последнего владельца блокирует API; владелец также не может изменить роль владельца через список.
      </Notice>
    </>
  );
}
