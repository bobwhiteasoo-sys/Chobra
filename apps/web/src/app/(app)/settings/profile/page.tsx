"use client";

import { useEffect, useState, type FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { CircleUserRound } from "lucide-react";

import { Button, ErrorState, Loading, Notice, useToast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { useMe } from "@/lib/queries";
import type { Me } from "@/lib/types";

type Locale = "ru" | "en";
type EditableMe = Me & { locale?: Locale };

export default function ProfileSettingsPage() {
  const me = useMe();
  const queryClient = useQueryClient();
  const toast = useToast();
  const [name, setName] = useState("");
  const [locale, setLocale] = useState<Locale>("ru");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!me.data) return;
    setName(me.data.display_name);
    setLocale((me.data as EditableMe).locale ?? "ru");
  }, [me.data]);

  if (me.isLoading) return <Loading lines={4} />;
  if (me.error) return <ErrorState error={me.error} onRetry={() => me.refetch()} />;

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBusy(true);
    try {
      const updated = await api<EditableMe>("/me", { method: "PATCH", body: { display_name: name.trim(), locale } });
      queryClient.setQueryData(["me"], updated);
      toast({ title: "Профиль сохранен", tone: "success" });
    } catch (error) {
      toast({ title: "Не удалось сохранить профиль", body: errorMessage(error), tone: "danger" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <header className="page-head">
        <div>
          <h1 className="t-page">Профиль</h1>
          <p className="lead">Данные текущей учетной записи и способ входа.</p>
        </div>
      </header>
      <form className="panel stack" onSubmit={submit}>
        <div className="row" style={{ gap: 14 }}>
          <CircleUserRound size={28} aria-hidden color="var(--color-accent-primary)" />
          <div>
            <h2 className="t-panel">Учетная запись</h2>
            <p className="t-caption" style={{ margin: "4px 0 0" }}>Способ входа: {me.data!.auth_mode === "dev" ? "режим разработки" : "корпоративная авторизация"}</p>
          </div>
        </div>
        <div className="settings-fields">
          <div className="field">
            <label htmlFor="profile-name">Отображаемое имя</label>
            <input id="profile-name" className="input" value={name} minLength={1} maxLength={120} required onChange={(event) => setName(event.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="profile-email">Электронная почта</label>
            <input id="profile-email" className="input" value={me.data!.email ?? "Не указана"} readOnly aria-readonly="true" />
            <span className="hint">Электронная почта управляется системой входа.</span>
          </div>
          <div className="field">
            <label htmlFor="profile-locale">Предпочитаемый язык</label>
            <select id="profile-locale" className="select" value={locale} onChange={(event) => setLocale(event.target.value as Locale)}>
              <option value="ru">Русский</option>
              <option value="en">English</option>
            </select>
          </div>
        </div>
        <div className="settings-actions"><Button type="submit" variant="primary" busy={busy} disabled={!name.trim()}>Сохранить профиль</Button></div>
      </form>
      <Notice>Почту изменяют в корпоративной системе входа. Имя и язык сохраняются в профиле Chobra. Интерфейс текущей версии доступен на русском.</Notice>
    </>
  );
}
