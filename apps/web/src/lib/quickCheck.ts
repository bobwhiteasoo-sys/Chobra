import { api } from "./api";
import type { Profile, Rule, Scenario } from "./types";

/** Starts the default check for a project: first two rules, reward-seeking participants, three repeats. */
export async function startCheck(projectId: string): Promise<string> {
  const [rules, scenarios, profiles] = await Promise.all([
    api<{ items: Rule[] }>(`/projects/${projectId}/rules`),
    api<{ items: Scenario[] }>(`/projects/${projectId}/scenarios`),
    api<{ items: Profile[] }>(`/projects/${projectId}/agents`),
  ]);
  const published = rules.items.filter((r) => r.status === "published").sort((a, b) => a.version - b.version).slice(0, 2);
  const scenario = scenarios.items.filter((s) => s.status === "published").sort((a, b) => b.version - a.version)[0];
  const profile = profiles.items.find((p) => p.kind === "scripted" && p.mode === "incentive_seeking");
  const batch = await api<{ batch_id: string }>("/batches", {
    body: {
      project_id: projectId,
      title: "Проверка правил",
      scenario_version_id: scenario?.id,
      agent_profile_id: profile?.id,
      variants: published.map((r) => ({ label: r.name, rule_version_id: r.id })),
      conditions: { seeds: [101, 102, 103] },
      limits: { max_wall_time_seconds: 600 },
    },
    headers: { "Idempotency-Key": crypto.randomUUID() },
  });
  return batch.batch_id;
}
