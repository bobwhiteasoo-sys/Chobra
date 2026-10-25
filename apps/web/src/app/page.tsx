"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { Loading } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { useMe } from "@/lib/queries";

export default function Home() {
  const me = useMe();
  const router = useRouter();
  useEffect(() => {
    if (me.error instanceof ApiError && me.error.status === 401) router.replace("/login");
    if (me.data) {
      const target = me.data.last_workspace_id ?? me.data.workspaces[0]?.id;
      router.replace(target ? `/w/${target}/projects` : "/onboarding");
    }
  }, [me.data, me.error, router]);
  return (
    <main className="main" style={{ maxWidth: 640 }}>
      <Loading />
    </main>
  );
}
