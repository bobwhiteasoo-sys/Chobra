"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import Image from "next/image";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState, type FormEvent } from "react";

import { Button, Notice } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import type { Me } from "@/lib/types";

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const queryClient = useQueryClient();
  const config = useQuery({ queryKey: ["auth-config"], queryFn: () => api<{ mode: string; oidc_configured: boolean }>("/auth/config") });
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const me = await api<Me>("/auth/dev-login", { body: { display_name: name, email } });
      queryClient.setQueryData(["me"], me);
      const next = params.get("next");
      router.replace(next && next.startsWith("/") ? next : me.workspaces.length ? `/w/${me.last_workspace_id ?? me.workspaces[0]!.id}/projects` : "/onboarding");
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  };

  return (
    <main className="login">
      <section className="login-card" aria-labelledby="login-title">
        <Image src="/brand/chobra-mark-transparent.png" alt="Chobra" width={112} height={107} priority />
        <h1 id="login-title" className="t-page" style={{ color: "var(--color-accent-primary)", marginTop: 20 }}>
          Chobra
        </h1>
        <p className="t-secondary measure" style={{ margin: "8px 0 28px" }}>
          Проверьте правило премии на ИИ участниках до того, как его введут для людей: что станет выгодным, где награда разойдется с результатом и как это исправить.
        </p>
        {config.data?.mode === "dev" ? (
          <form onSubmit={submit} className="stack" style={{ width: "100%" }}>
            <Notice tone="warn">Режим разработки: вход без поставщика идентификации. В рабочем развертывании здесь кнопка входа через OIDC.</Notice>
            <div className="field">
              <label htmlFor="name">Имя</label>
              <input id="name" className="input" value={name} onChange={(e) => setName(e.target.value)} required autoComplete="name" />
            </div>
            <div className="field">
              <label htmlFor="email">Почта</label>
              <input id="email" className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" />
            </div>
            {error ? <p className="field error" role="alert">{error}</p> : null}
            <Button variant="primary" type="submit" busy={busy}>
              Войти
            </Button>
          </form>
        ) : config.data ? (
          <a className="btn btn-primary" href="/api/v1/auth/oidc/start">
            Войти через поставщика идентификации
          </a>
        ) : null}
      </section>
    </main>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}
