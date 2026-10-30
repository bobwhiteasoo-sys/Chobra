"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Notice } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { SITUATIONS } from "@/lib/format";
import { startCheck } from "@/lib/quickCheck";
import type { Project } from "@/lib/types";

/** One click: the situation becomes a project and its check starts right away. */
export function Situations({ workspace }: { workspace: () => Promise<string> }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const start = async (situation: (typeof SITUATIONS)[number]) => {
    setBusy(situation.id);
    setError(null);
    try {
      const workspaceId = await workspace();
      const project = await api<Project>("/projects", { body: { workspace_id: workspaceId, name: situation.title, environment_id: situation.id } });
      const batchId = await startCheck(project.id);
      await queryClient.invalidateQueries({ queryKey: ["projects"] });
      await queryClient.invalidateQueries({ queryKey: ["me"] });
      router.push(`/experiments/${batchId}`);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(null);
    }
  };

  return (
    <>
      {error ? <Notice tone="danger">{error}</Notice> : null}
      <ul className="situations">
        {SITUATIONS.map((s) => (
          <li key={s.id}>
            <button type="button" className="situation" aria-busy={busy === s.id} disabled={Boolean(busy)} onClick={() => void start(s)}>
              <span>
                <span className="situation-title">{s.title}</span>
                <span className="situation-text">{s.text}</span>
              </span>
              <span className="situation-go" aria-hidden>
                {busy === s.id ? <Loader2 size={22} className="spin" /> : <ArrowRight size={22} />}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </>
  );
}
