"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { useAnnounceWorkspace } from "@/components/Shell";
import { Button, ButtonLink, CheckStatus, ErrorState, IdChip, Loading, Metric, Notice, Pill } from "@/components/ui";
import { ReportAction } from "@/components/comparisons/ReportAction";
import { api, errorMessage } from "@/lib/api";
import { eventLabel, eventDetail, actionLabel } from "@/lib/arena/labels";
import { points, REPLAY_STATUS } from "@/lib/format";
import { useBatch, useFinding, useProject, useRules } from "@/lib/queries";
import type { CheckResult, Finding, RunEvent } from "@/lib/types";
import "@/styles/comparisons.css";

type FixResult = { reproduced: boolean; checks: CheckResult[]; note: string; holdout?: unknown };
function EventEvidence({ event }: { event: RunEvent }) {
  const p = event.payload;
  const before = p.state_before ?? p.before;
  const after = p.state_after ?? p.after;
  return <article id={`event-${event.seq}`} className="evidence-event stack" style={{ gap: 8 }}>
    <div className="row"><Pill>#{event.seq}</Pill><span className="t-caption">Тик {event.tick}</span><strong>{eventLabel(event)}</strong></div>
    {eventDetail(event) ? <p style={{ margin: 0 }}>{eventDetail(event)}</p> : null}
    <div className="t-caption">{event.actor_id ? `Участник: ${event.actor_id} · ` : ""}{event.entity_id ? `Объект: ${event.entity_id}` : ""}</div>
    {before !== undefined || after !== undefined ? <div className="state-grid"><div><strong>До события</strong><pre>{before === undefined ? "Не записано" : JSON.stringify(before, null, 2)}</pre></div><div><strong>После события</strong><pre>{after === undefined ? "Не записано" : JSON.stringify(after, null, 2)}</pre></div></div> : null}
    <details><summary>Записанные данные события</summary><pre>{JSON.stringify(p, null, 2)}</pre>{event.state_hash ? <IdChip value={event.state_hash} label="состояние" /> : null}</details>
  </article>;
}
export default function FindingPage() {
  const { finding: id } = useParams<{ finding: string }>();
  const query = useFinding(id);
  const batch = useBatch(query.data?.run.batch_id);
  const project = useProject(query.data?.project_id);
  const rules = useRules(query.data?.project_id);
  useAnnounceWorkspace(project.data?.workspace_id);
  const client = useQueryClient();
  const router = useRouter();
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [ruleId, setRuleId] = useState("");
  const [fixResult, setFixResult] = useState<FixResult | null>(null);
  const [report, setReport] = useState(false);
  const mutate = async (action: string, body: unknown = {}) => {
    setBusy(action); setError("");
    try { await api<Finding>(`/findings/${id}/${action}`, { body }); await client.invalidateQueries({ queryKey: ["finding", id] }); }
    catch (err) { setError(errorMessage(err)); }
    finally { setBusy(""); }
  };
  if (query.isLoading) return <Loading lines={8} />;
  if (query.error || !query.data) return <ErrorState error={query.error} onRetry={() => query.refetch()} />;
  const f = query.data, c = f.card;
  const canEdit = Boolean(project.data?.role && project.data.role !== "viewer");
  const minimizing = f.minimization && ["queued", "running"].includes(f.minimization.status);
  return <div className="analysis-page stack-24">
    <nav className="crumbs" aria-label="Путь"><Link href={`/p/${f.project_id}`}>{project.data?.name ?? "Проект"}</Link><span>/</span><Link href={`/runs/${f.run_id}/replay`}>Запуск</Link><span>/</span><span>Находка</span></nav>
    <header className="page-head"><div><Pill tone="danger">Наблюдаемое нарушение</Pill><h1 className="t-page" style={{ marginTop: 8 }}>{c.title}</h1><p className="lead">{c.explanation}</p></div><div className="row"><ButtonLink href={`/runs/${f.run_id}/replay`}>Воспроизвести</ButtonLink><Button onClick={() => setReport(!report)}>Добавить в отчет</Button>{batch.data?.comparison_id ? <ButtonLink href={`/comparisons/${batch.data.comparison_id}`}>Перейти к сравнению</ButtonLink> : null}</div></header>
    {error ? <Notice tone="danger">{error}</Notice> : null}
    <section className="panel stack"><h2 className="t-section">Нарушенное свойство</h2><div className="row"><Pill>{c.check_id} · {c.check_version}</Pill><Pill>{c.environment} · {c.environment_version}</Pill><span>Seed {c.seed}</span></div><pre>{c.formula}</pre><p>Порог: {c.threshold || "Указан формулой свойства"}</p><p className="t-secondary">Область проверки: {c.scope}</p><div className="divider"/><h3 className="t-panel">Условие правила: {c.rule_name}</h3><p>{c.rule_condition}</p><div className="row"><IdChip value={c.rule_hash} label="правило"/><ButtonLink compact href={`/p/${f.project_id}/rules/${f.run.rule_version_id}`}>Открыть версию правила</ButtonLink></div></section>
    <section className="panel stack"><h2 className="t-section">События доказательства</h2><p className="t-secondary">Тик нарушения {c.violation_tick}. Ссылки ведут к зафиксированным событиям этого запуска.</p><div className="row">{c.evidence_seqs.map((seq) => <a key={seq} className="btn btn-secondary btn-compact" href={`#event-${seq}`}>Событие #{seq}</a>)}</div>{c.events.length ? c.events.map((e) => <EventEvidence key={e.seq} event={e}/>) : <Notice>События доказательства не записаны в карточке. Откройте журнал запуска.</Notice>}<p className="t-caption">Отдельные снимки «до» и «после» показываются только при наличии в payload. Остальные значения доступны в записанных данных события.</p></section>
    <section className="panel stack"><h2 className="t-section">Проверка воспроизведения</h2><Pill tone={f.replay_status === "replay_verified" ? "success" : "neutral"}>{REPLAY_STATUS[f.replay_status] ?? f.replay_status}</Pill><p className="t-secondary">Повторное исполнение сохраненных действий с проверкой свойства и контрольных сумм. Новые обращения к модели не требуются.</p>{f.replay_result ? <div className="stat-grid"><Metric label="Сравнено тиков" value={f.replay_result.ticks_compared}/><Metric label="Свойство воспроизвелось" value={f.replay_result.property_reproduced === null ? "Неизвестно" : f.replay_result.property_reproduced ? "Да" : "Нет"}/><Metric label="Первое расхождение" value={f.replay_result.first_divergent_tick ?? "Нет"}/><Metric label="Вызовы модели" value={f.replay_result.model_calls}/></div> : null}<Button busy={busy === "replay"} disabled={Boolean(busy)} onClick={() => mutate("replay")}>Проверить replay</Button></section>
    <section className="panel stack"><h2 className="t-section">Влияние на показатели</h2><div className="stat-grid"><Metric label="Нарушений свойства" value={c.violation_count}/><Metric label="Награда в контрпримере" value={`${points(c.reward_microunits)} очк.`}/><Metric label="Затронуто объектов" value={c.affected_entities.length}/></div><p className="t-caption">Объекты: {c.affected_entities.join(", ") || "Не указаны"}. Эти значения относятся к данному контрпримеру.</p></section>
    <section className="panel stack"><h2 className="t-section">Сокращение последовательности</h2><Notice>ddmin ищет более короткую допустимую последовательность в пределах бюджета. Результат не является доказательством глобальной минимальности.</Notice>{f.minimization ? <><p>Состояние: {({ queued: "В очереди", running: "Выполняется", completed: "Завершено", minimal: "Сокращение завершено: удаление отдельного действия разрушает нарушение", reduced: "Сокращено в пределах бюджета", not_reproduced: "Нарушение не воспроизведено", budget_exhausted: "Бюджет исчерпан", failed: "Ошибка" } as Record<string,string>)[f.minimization.status] ?? f.minimization.status}</p><p className="t-caption">Исходных действий: {f.minimization.original_count ?? "—"}; исполнений: {f.minimization.executions ?? "—"}; повторная проверка: {f.minimization.verified === undefined ? "Не завершена" : f.minimization.verified ? "Подтверждена" : "Не подтверждена"}.</p>{f.minimization.actions?.length ? <ol>{f.minimization.actions.map((a,i) => <li key={i}>Тик {a.tick} · {a.actor_id} · {actionLabel(a.action_type)}<pre>{JSON.stringify(a.arguments)}</pre></li>)}</ol> : null}</> : null}<Button disabled={!canEdit || Boolean(busy) || Boolean(minimizing)} busy={busy === "minimize" || Boolean(minimizing)} onClick={() => mutate("minimize")}>Сократить контрпример</Button></section>
    <section className="panel stack"><h2 className="t-section">Возможные исправления</h2><p className="t-secondary">Кандидаты требуют проверки. Создание варианта сохраняет черновик правила.</p><Button disabled={!canEdit || Boolean(busy)} busy={busy === "propose-fixes"} onClick={() => mutate("propose-fixes")}>Предложить исправления</Button>{f.fix_candidates?.map((candidate) => <article className="panel-quiet stack" key={candidate.key}><h3 className="t-panel">{candidate.title}</h3><p>{candidate.explanation}</p><Notice tone="warn">Компромисс: {candidate.tradeoff}</Notice><Pill tone={candidate.validation.ok ? "success" : "danger"}>{candidate.validation.ok ? "Проходит проверку правила" : "Правило не прошло проверку"}</Pill>{candidate.validation.errors.map((issue,i) => <p key={i} className="t-caption">{issue.path}: {issue.message}</p>)}<Button disabled={!canEdit || Boolean(busy) || !candidate.validation.ok} busy={busy === candidate.key} onClick={async () => { setBusy(candidate.key); setError(""); try { const draft = await api<{id:string}>(`/findings/${id}/create-variant`, {body:{candidate_key:candidate.key}}); router.push(`/p/${f.project_id}/rules/${draft.id}`); } catch(err) {setError(errorMessage(err)); setBusy("");} }}>Создать вариант правила</Button></article>)}
    <h3 className="t-panel">Проверить исправление</h3><div className="field"><label htmlFor="fix-rule">Версия правила для проверки</label><select className="select" id="fix-rule" value={ruleId} onChange={(e) => {setRuleId(e.target.value); setFixResult(null);}}><option value="">Выберите правило</option>{rules.data?.items.map((r) => <option key={r.id} value={r.id}>{r.name} · v{r.version} · {r.status === "draft" ? "черновик" : "опубликовано"}</option>)}</select></div>{rules.error ? <ErrorState error={rules.error} onRetry={() => rules.refetch()}/> : null}<Button disabled={!ruleId || Boolean(busy)} busy={busy === "check-fix"} onClick={async () => {setBusy("check-fix");setError("");try {setFixResult(await api<FixResult>(`/findings/${id}/check-fix`,{body:{rule_version_id:ruleId}}));}catch(err){setError(errorMessage(err));}finally{setBusy("");}}}>Проверить на контрпримере</Button>{fixResult ? <div className="stack"><Notice tone={fixResult.reproduced ? "warn" : "info"}>{fixResult.reproduced ? "Исходное нарушение воспроизвелось с этим правилом." : "На исходных действиях это нарушение не воспроизвелось."} {fixResult.note}</Notice>{fixResult.checks.map((check) => <div key={check.check_id} className="row"><CheckStatus status={check.status}/><span>{check.title}</span><span className="t-caption">{check.reason}</span></div>)}{fixResult.holdout ? <details><summary>Отдельный набор условий</summary><pre>{JSON.stringify(fixResult.holdout,null,2)}</pre></details> : <Notice tone="warn">Отдельный набор условий еще не проверен. Отсутствие нарушения на исходных действиях не доказывает исправление.</Notice>}</div> : null}<ButtonLink href={`/p/${f.project_id}/experiments/new?rule=${ruleId}&seed=${c.seed+100000}`}>Испытать на новых seed</ButtonLink></section>
    {report ? <section className="panel stack" id="report"><h2 className="t-section">Добавить находку в отчет серии</h2><ReportAction projectId={f.project_id} batchId={f.run.batch_id}/></section> : null}
  </div>;
}
