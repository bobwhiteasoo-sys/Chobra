"use client";
import { useParams, useRouter } from "next/navigation";
import { useEffect } from "react";
import { ButtonLink, Loading } from "@/components/ui";
import { useProject } from "@/lib/queries";

/** A project has no screen of its own: it opens its latest answer, or its first check. */
export default function ProjectEntry() {
  const { project: id } = useParams<{ project: string }>();
  const router = useRouter();
  const { data: p } = useProject(id);
  const canRun = p && p.role !== "viewer" && !p.archived_at;
  useEffect(() => {
    if (!p) return;
    if (p.last_comparison) router.replace(`/comparisons/${p.last_comparison.id}`);
    else if (p.last_batch) router.replace(`/experiments/${p.last_batch.id}`);
    else if (canRun) router.replace(`/p/${id}/experiments/new`);
  }, [p, canRun, id, router]);
  if (!p || p.last_comparison || p.last_batch || canRun) return <Loading />;
  return (
    <>
      <h1 className="pick-title">{p.name}</h1>
      <p className="lead">Проверок ещё не было.</p>
      <ButtonLink href={`/p/${id}/rules`}>Посмотреть правила</ButtonLink>
    </>
  );
}
