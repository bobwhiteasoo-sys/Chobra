"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "./api";
import type { Batch, Comparison, EnvironmentInfo, Finding, Me, Profile, Project, Report, Rule, RunDetail, Scenario, Workspace } from "./types";

const ACTIVE = new Set(["queued", "initializing", "running", "pause_requested", "resume_requested", "cancel_requested", "auditing"]);

export const useMe = () => useQuery({ queryKey: ["me"], queryFn: () => api<Me>("/me"), retry: false, staleTime: 30_000 });

export const useWorkspace = (id: string | undefined) =>
  useQuery({ queryKey: ["workspace", id], queryFn: () => api<Workspace>(`/workspaces/${id}`), enabled: Boolean(id) });

export const useProjects = (workspaceId: string | undefined, params: { q?: string; environment?: string; archived?: boolean; owner?: string }) =>
  useQuery({
    queryKey: ["projects", workspaceId, params],
    queryFn: () => {
      const search = new URLSearchParams({ workspace_id: workspaceId ?? "" });
      if (params.q) search.set("q", params.q);
      if (params.environment) search.set("environment", params.environment);
      if (params.archived) search.set("archived", "true");
      if (params.owner) search.set("owner", params.owner);
      return api<{ items: Project[]; next_cursor: string | null }>(`/projects?${search}`);
    },
    enabled: Boolean(workspaceId),
  });

export const useProject = (id: string | undefined) =>
  useQuery({ queryKey: ["project", id], queryFn: () => api<Project>(`/projects/${id}`), enabled: Boolean(id) });

export const useEnvironments = () =>
  useQuery({ queryKey: ["environments"], queryFn: () => api<{ items: EnvironmentInfo[] }>("/environments"), staleTime: Infinity });

export const useEnvironment = (name: string | undefined) => {
  const query = useEnvironments();
  return { ...query, data: query.data?.items.find((e) => e.name === name) };
};

export const useScenarios = (projectId: string | undefined) =>
  useQuery({ queryKey: ["scenarios", projectId], queryFn: () => api<{ items: Scenario[] }>(`/projects/${projectId}/scenarios`), enabled: Boolean(projectId) });

export const useRules = (projectId: string | undefined) =>
  useQuery({ queryKey: ["rules", projectId], queryFn: () => api<{ items: Rule[] }>(`/projects/${projectId}/rules`), enabled: Boolean(projectId) });

export const useProfiles = (projectId: string | undefined) =>
  useQuery({
    queryKey: ["profiles", projectId],
    queryFn: () => api<{ items: Profile[]; participants: { actor_id: string; display_name: string }[] }>(`/projects/${projectId}/agents`),
    enabled: Boolean(projectId),
  });

export const useBatch = (id: string | undefined) =>
  useQuery({
    queryKey: ["batch", id],
    queryFn: () => api<Batch>(`/batches/${id}`),
    enabled: Boolean(id),
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) return 1500;
      return data.runs.some((r) => ACTIVE.has(r.status)) || !data.comparison_id ? 1500 : false;
    },
  });

export const useRun = (id: string | undefined, live = false) =>
  useQuery({
    queryKey: ["run", id],
    queryFn: () => api<RunDetail>(`/runs/${id}`),
    enabled: Boolean(id),
    refetchInterval: (query) => (live && query.state.data && ACTIVE.has(query.state.data.status) ? 2000 : false),
  });

export const useFinding = (id: string | undefined) =>
  useQuery({
    queryKey: ["finding", id],
    queryFn: () => api<Finding>(`/findings/${id}`),
    enabled: Boolean(id),
    refetchInterval: (query) => (query.state.data?.minimization && ["queued", "running"].includes(query.state.data.minimization.status) ? 1200 : false),
  });

export const useComparison = (id: string | undefined) =>
  useQuery({ queryKey: ["comparison", id], queryFn: () => api<Comparison>(`/comparisons/${id}`), enabled: Boolean(id) });

export const useReport = (id: string | undefined) =>
  useQuery({
    queryKey: ["report", id],
    queryFn: () => api<Report & { snapshot: Record<string, unknown> | null }>(`/reports/${id}`),
    enabled: Boolean(id),
    refetchInterval: (query) => (query.state.data && ["queued"].includes(query.state.data.status) ? 1200 : false),
  });

export function isActive(status: string): boolean {
  return ACTIVE.has(status);
}
