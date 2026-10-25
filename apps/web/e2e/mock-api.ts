import type { Page } from "@playwright/test";
import control from "./fixtures/control-run.json";

export const fixture = control;
export async function mockApi(page: Page, options: { live?: boolean; available?: number } = {}) {
  const state = { available: options.available ?? control.logs["SD-P1-101"].length, requests: [] as string[] };
  const workspace = { id: "workspace-control", name: "Контрольное пространство", role: "owner", limits: { max_agents: 20, max_concurrent_runs: 4, max_runs_per_series: 100, max_horizon_ticks: 240 }, retention_policy: { events_days: 180, raw_model_io_days: 30, technical_logs_days: 30 }, model_settings: { default_model: "test-model", allowed_models: ["test-model"] } };
  const me = { id: "user-control", display_name: "Исследователь", email: "test@example.test", locale: "ru", auth_mode: "dev", csrf_token: "test-csrf", last_workspace_id: workspace.id, workspaces: [workspace] };
  const project = { id: "project-control", workspace_id: workspace.id, name: "Контрольное испытание поддержки", description: "Контрольные данные, полученные реальным движком", environment_id: "supportdesk", tags: [], role: "owner", is_demo: true, research_question: "Закрыто или решено?", desired_outcome: "Решенные исходные проблемы", scenarios: [], rules: [], batches: [control.batch], findings: [], last_comparison: null };
  await page.addInitScript(() => {
    class TestEventSource extends EventTarget {
      static CONNECTING = 0; static OPEN = 1; static CLOSED = 2;
      readonly CONNECTING = 0; readonly OPEN = 1; readonly CLOSED = 2;
      readyState = 0;
      constructor(public url: string) {
        super();
        (window as any).__sources ??= [];
        (window as any).__sources.push(this);
        setTimeout(() => { if (this.readyState !== 2) { this.readyState = 1; this.dispatchEvent(new Event("open")); } }, 20);
      }
      close() { this.readyState = 2; }
    }
    (window as any).EventSource = TestEventSource;
  });
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace("/api/v1", "");
    state.requests.push(`${request.method()} ${path}`);
    let data: unknown;
    if (path === "/auth/config") data = { mode: "dev", oidc_configured: false };
    else if (path === "/auth/dev-login" || path === "/me") data = me;
    else if (path === "/me/last-workspace" || path === "/auth/logout") data = { ok: true };
    else if (path === "/projects") data = { items: [project], next_cursor: null };
    else if (path === `/workspaces/${workspace.id}`) data = workspace;
    else if (path.endsWith("/members")) data = { items: [{ id: "membership-control", user_id: me.id, display_name: me.display_name, email: me.email, role: "owner", status: "active" }] };
    else if (path.endsWith("/provider-keys")) data = { items: [], deployment_key_present: false };
    else if (path === "/settings/models") data = { models: [{ id: "test-model", input_usd_per_mtok: "1", output_usd_per_mtok: "1", currency: "USD", price_source: "Тестовый каталог", price_as_of: "2026-10-25" }], modes: [] };
    else if (path === "/environments") data = { items: [] };
    else if (path === "/projects/project-control") data = project;
    else if (path === "/projects/project-control/rules") data = { items: [] };
    else if (path === "/projects/project-control/findings") data = { items: control.findings };
    else if (path === "/projects/project-control/comparisons") data = { items: [{ ...control.comparison, created_at: "2026-10-25T10:00:00Z", batch_title: control.batch.title }] };
    else if (path === "/projects/project-control/reports") data = { items: [] };
    else if (path === "/projects/project-control/batches") data = { items: [control.batch] };
    else if (path === "/batches/batch-control") data = control.batch;
    else if (/^\/runs\/[^/]+\/events$/.test(path)) {
      const id = path.split("/")[2];
      const original = control.logs[id as keyof typeof control.logs] ?? [];
      const list = id === "SD-P1-101" ? original.slice(0, state.available) : original;
      data = { items: list.filter((e) => e.seq > Number(url.searchParams.get("after") ?? 0) && e.seq <= Number(url.searchParams.get("until") ?? Infinity) && (!url.searchParams.has("domain_only") || e.event_class === "domain")).slice(0, Number(url.searchParams.get("limit") ?? 500)), last_seq: list.at(-1)?.seq ?? 0, status: options.live ? "running" : "completed" };
    } else if (/^\/runs\/[^/]+$/.test(path)) {
      const run = control.runs.find((r) => r.id === path.split("/")[2]);
      data = { ...control.run, ...run, ...(options.live ? { status: "running", allowed_commands: ["pause", "cancel"] } : {}) };
    } else if (path === "/comparisons/comparison-control") data = control.comparison;
    else if (path.startsWith("/findings/")) {
      const finding = control.findings.find((f) => f.id === path.split("/")[2])!;
      data = path.endsWith("/replay") ? { ...finding, replay_status: "replay_verified", replay_result: { status: "replay_verified", ticks_compared: 31, first_divergent_tick: null, property_reproduced: true, model_calls: 0 } } : finding;
    } else if (path === "/reports" && request.method() === "POST") data = { id: "report-control" };
    else if (path === "/reports/report-control") data = { id: "report-control", project_id: project.id, batch_id: control.batch.id, format: "markdown", status: "ready", error: null, created_at: "2026-10-25T10:00:00Z", download_url: "/api/v1/reports/report-control/download?sig=test", link_expires_in_seconds: 300, snapshot: { summary: { runs: 20, completed: 20, findings: control.findings.length } } };
    else if (path === "/reports/report-control/download") return route.fulfill({ contentType: "text/markdown", headers: { "Content-Disposition": 'attachment; filename="chobra-report-control.md"' }, body: "# Chobra\nКонтрольный отчет UI-контракта" });
    else return route.fulfill({ status: 501, json: { message: `Неописанный контракт теста: ${request.method()} ${path}` } });
    await route.fulfill({ json: data });
  });
  return state;
}
