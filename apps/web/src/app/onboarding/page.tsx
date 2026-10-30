"use client";
import Image from "next/image";
import Link from "next/link";
import { useRef } from "react";
import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { Situations } from "@/components/flow/Situations";
import { Loading } from "@/components/ui";
import { api } from "@/lib/api";
import { useMe } from "@/lib/queries";

function Setup() {
  const me = useMe();
  const params = useSearchParams();
  const created = useRef<string | null>(null);
  if (me.isLoading) return <Loading />;
  const existing = params.get("new") ? undefined : me.data?.workspaces[0]?.id;
  const workspace = async () => {
    if (existing) return existing;
    if (!created.current) created.current = (await api<{ id: string }>("/workspaces", { body: { name: "Мои проверки" } })).id;
    return created.current;
  };
  return (
    <main className="entry">
      <section className="entry-content entry-wide">
        <Link href="/" className="brand"><Image src="/brand/chobra-mark-transparent.png" alt="" width={30} height={29} /><span>Chobra</span></Link>
        <h1>Что проверим?</h1>
        <p className="lead">Нажмите на ситуацию. Ответ будет через несколько секунд.</p>
        <Situations workspace={workspace} />
      </section>
    </main>
  );
}
export default function Onboarding() {
  return <Suspense><Setup /></Suspense>;
}
