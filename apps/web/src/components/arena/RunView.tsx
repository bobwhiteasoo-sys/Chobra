"use client";

import * as Dialog from "@radix-ui/react-dialog";
import * as Tabs from "@radix-ui/react-tabs";
import { useQueryClient } from "@tanstack/react-query";
import { Check, ChevronLeft, ChevronRight, History, Pause, Play, Radio, SkipForward, X } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useAnnounceWorkspace } from "@/components/Shell";
import { Button, ErrorState, Loading, Pill, RunStatus, useToast, Verdict } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { useHistoryProjection } from "@/lib/arena/useHistory";
import { useRunStream, type Connection } from "@/lib/arena/useRunStream";
import type { Violation } from "@/lib/arena/projection";
import { count, MODE_LABELS } from "@/lib/format";
import { useMediaQuery, useNow, useReducedMotion } from "@/lib/hooks";
import { isActive, useBatch, useProject, useRun } from "@/lib/queries";
import type { RunEvent } from "@/lib/types";

import { EventLog } from "./EventLog";
import { Inspector } from "./Inspector";
import { Scene, type Chain, type Selection } from "./Scene";

const STAGES = ["Проверка условий", "Подготовка мира", "Решения участников", "Проверка последствий", "Сравнение", "Отчет"];
const SPEEDS = [0.5, 1, 2, 4] as const;
const STEP_MS = 360;

function connectionText(connection: Connection, lastSeq: number, lastUpdate: number | null): { label: string; tone: "accent" | "neutral" | "danger" | "info" } {
  const time = lastUpdate ? new Date(lastUpdate).toLocaleTimeString("ru-RU") : "—";
  switch (connection) {
    case "connecting":
      return { label: "Подключение к потоку", tone: "info" };
    case "live":
      return { label: "Поток событий активен", tone: "accent" };
    case "lost":
      return { label: `Связь потеряна. Последнее событие #${lastSeq}, обновлено ${time}`, tone: "danger" };
    case "revoked":
      return { label: "Доступ к запуску отозван", tone: "danger" };
    default:
      return { label: "Поток закрыт, показано итоговое состояние", tone: "neutral" };
  }
}

function chainFor(violation: Violation, log: RunEvent[]): Chain {
  const seqs = new Set([...violation.evidence, violation.seq]);
  const entities = new Set(violation.entities);
  const actors = new Set<string>();
  let reward = false;
  for (const e of log) {
    if (!seqs.has(e.seq)) continue;
    if (e.entity_id) entities.add(e.entity_id);
    for (const key of ["issue_id", "task_id", "root_issue_id", "root_task_id"]) if (typeof e.payload[key] === "string") entities.add(e.payload[key] as string);
    if (e.actor_id) actors.add(e.actor_id);
    if (typeof e.payload.actor_id === "string") actors.add(e.payload.actor_id);
    if (e.type.startsWith("reward.")) reward = true;
  }
  return { violationSeq: violation.seq, seqs, entities, actors, reward, outcome: true };
}

export function RunView({ runId, initialMode, initialSeq }: { runId: string; initialMode: "live" | "history"; initialSeq: number | null }) {
  const run = useRun(runId, true);
  const batch = useBatch(run.data?.batch_id);
  const project = useProject(run.data?.project_id);
  useAnnounceWorkspace(project.data?.workspace_id);
  const stream = useRunStream(runId, true);
  const queryClient = useQueryClient();
  const toast = useToast();
  const stacked = useMediaQuery("(max-width: 1023px)");
  const reduced = useReducedMotion();

  const [mode, setMode] = useState<"live" | "history">(initialMode);
  const [cursor, setCursor] = useState<number>(initialSeq ?? 0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState<(typeof SPEEDS)[number]>(1);
  const [tickInput, setTickInput] = useState("");
  const [selection, setSelection] = useState<Selection | null>(null);
  const [chain, setChain] = useState<Chain | null>(null);
  const [view, setView] = useState("arena");
  const [announcement, setAnnouncement] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const violationsSeen = useRef<number | null>(null);

  const log = stream.log;
  const history = useHistoryProjection(log, mode === "history" ? cursor : Number.POSITIVE_INFINITY);
  const projection = mode === "live" ? stream.projection : history;
  const domainSeqs = useMemo(() => log.filter((e) => e.event_class === "domain").map((e) => e.seq), [log]);
  const firstSeq = domainSeqs[0] ?? 0;
  const lastSeq = log.at(-1)?.seq ?? 0;

  // History opened without a position starts at the prepared world, not at an empty scene.
  useEffect(() => {
    if (mode === "history" && cursor === 0 && log.length) {
      const init = log.find((e) => e.type === "run.initialized");
      setCursor(init?.seq ?? firstSeq);
    }
  }, [mode, cursor, log, firstSeq]);

  useEffect(() => {
    const path = mode === "live" ? `/runs/${runId}/live` : `/runs/${runId}/replay${cursor ? `?seq=${cursor}` : ""}`;
    if (window.location.pathname + window.location.search !== path) window.history.replaceState(null, "", path);
  }, [mode, cursor, runId]);

  // Visual playback: one domain event per step; it never jumps back to Live on its own.
  useEffect(() => {
    if (mode !== "history" || !playing) return;
    const id = window.setInterval(() => {
      setCursor((current) => {
        const next = domainSeqs.find((s) => s > current);
        if (next === undefined) {
          setPlaying(false);
          return current;
        }
        return next;
      });
    }, STEP_MS / speed);
    return () => window.clearInterval(id);
  }, [mode, playing, speed, domainSeqs]);

  // One unobtrusive notice for a violation that appears while watching live.
  useEffect(() => {
    const total = stream.projection.violations.length;
    if (violationsSeen.current === null) {
      if (stream.connection !== "connecting") violationsSeen.current = total;
      return;
    }
    if (total > violationsSeen.current) {
      const v = stream.projection.violations.at(-1)!;
      if (violationsSeen.current === 0) toast({ title: "Обнаружено нарушение", body: `${v.title}. Сцена не переключается; цепочку можно открыть в карточке под средой.`, tone: "danger" });
      setAnnouncement(`Нарушение: ${v.title}, тик ${v.tick}`);
      violationsSeen.current = total;
    }
  }, [stream.projection.violations, stream.connection, toast]);

  useEffect(() => {
    if (stream.recovered === null) return;
    toast({ title: "Связь восстановлена", body: `Загружено пропущенных событий: ${stream.recovered}` });
    stream.clearRecovered();
  }, [stream, toast]);

  useEffect(() => {
    if (stream.connection === "lost") setAnnouncement("Связь с потоком событий потеряна; показано последнее подтвержденное состояние");
    if (stream.connection === "ended") setAnnouncement("Запуск завершен");
  }, [stream.connection]);

  const anyChoosing = Object.values(projection.agents).some((a) => a.status === "choosing");
  const now = useNow(mode === "live" && stream.connection === "live" && anyChoosing);
  const findingHref = useCallback((checkId: string) => {
    const f = run.data?.findings.find((x) => x.check_id === checkId);
    return f ? `/findings/${f.id}` : null;
  }, [run.data?.findings]);

  if (run.isLoading) return <Loading lines={10} />;
  if (run.error || !run.data) return <ErrorState error={run.error} onRetry={() => run.refetch()} />;
  const r = run.data;
  const total = r.horizon_ticks + r.tail_ticks;
  const active = isActive(r.status);
  const conn = connectionText(stream.connection, stream.projection.lastSeq, stream.lastUpdate);
  const comparisonId = batch.data?.comparison_id ?? null;
  const canRun = project.data?.role && project.data.role !== "viewer";

  let stage: number;
  if (["draft", "validating", "queued"].includes(r.status)) stage = 0;
  else if (r.status === "initializing" || projection.status === "initializing") stage = 1;
  else if (r.status === "auditing") stage = 3;
  else if (active) stage = projection.phase === "tail" ? 3 : 2;
  else stage = 4;

  const enterHistory = (seq?: number) => {
    setMode("history");
    setPlaying(false);
    setCursor(seq ?? stream.projection.lastSeq);
  };
  const showChain = (v: Violation) => {
    setChain(chainFor(v, log));
    setSelection({ kind: "violation", seq: v.seq });
  };
  const stepTo = (dir: 1 | -1) => {
    setPlaying(false);
    if (dir === 1) setCursor((c) => domainSeqs.find((s) => s > c) ?? c);
    else setCursor((c) => [...domainSeqs].reverse().find((s) => s < c) ?? c);
  };
  const nextViolation = () => {
    const next = log.find((e) => e.type === "check.failed" && e.seq > cursor) ?? log.find((e) => e.type === "check.failed");
    if (!next) {
      toast({ title: "Нарушений в журнале нет" });
      return;
    }
    setPlaying(false);
    setCursor(next.seq);
    const v: Violation = { seq: next.seq, tick: next.tick, checkId: String(next.payload.check_id), title: String(next.payload.title), message: String(next.payload.message), evidence: (next.payload.evidence_seqs as number[]) ?? [], entities: (next.payload.entity_ids as string[]) ?? [] };
    showChain(v);
  };
  const goTick = () => {
    const tick = Number(tickInput);
    if (!Number.isFinite(tick)) return;
    const target = [...log].reverse().find((e) => e.tick <= tick && e.event_class === "domain");
    if (target) {
      setPlaying(false);
      setCursor(target.seq);
    }
  };
  const command = async (cmd: "pause" | "resume" | "cancel") => {
    setBusy(cmd);
    try {
      await api(`/runs/${r.id}/${cmd}`, { body: {} });
      await queryClient.invalidateQueries({ queryKey: ["run", r.id] });
    } catch (err) {
      toast({ title: "Команда не выполнена", body: errorMessage(err), tone: "danger" });
    }
    setBusy(null);
  };

  const cursorEvent = mode === "history" ? log.find((e) => e.seq === cursor) : null;
  const violationMarks = log.filter((e) => e.type === "check.failed");
  const span = Math.max(1, lastSeq - firstSeq);

  const inspector = (
    <Inspector
      selection={selection}
      projection={projection}
      log={mode === "history" ? log.filter((e) => e.seq <= cursor) : log}
      run={r}
      onSelect={setSelection}
      onJump={(seq) => enterHistory(seq)}
      findingHref={findingHref}
    />
  );

  return (
    <>
      <nav className="crumbs" aria-label="Путь">
        {project.data ? (
          <>
            <Link href={`/w/${project.data.workspace_id}/projects`}>Проекты</Link>
            <span aria-hidden>/</span>
            <Link href={`/p/${project.data.id}`}>{project.data.name}</Link>
            <span aria-hidden>/</span>
          </>
        ) : null}
        <Link href={`/experiments/${r.batch_id}`}>{r.batch.title}</Link>
        <span aria-hidden>/</span>
        <span>Запуск</span>
      </nav>

      <header className="run-head">
        <div style={{ minWidth: 0 }}>
          <h1 className="t-page clamp-2">{r.variant_label}</h1>
          <div className="row" style={{ gap: 8, marginTop: 8 }}>
            <RunStatus status={r.status} />
            {!active ? <Verdict verdict={r.verdict} /> : null}
            <Pill>{MODE_LABELS[r.agent_mode] ?? r.agent_mode}</Pill>
            <Pill>seed {r.seed}</Pill>
            <span className="t-caption num">
              тик {Math.max(0, mode === "live" ? r.current_tick : projection.tick)} из {total}
            </span>
          </div>
          {batch.data ? (
            <p className="t-caption" style={{ margin: "6px 0 0" }}>
              Серия: {batch.data.counts.completed + batch.data.counts.incomplete} из {count(batch.data.counts.planned, "запуска", "запусков", "запусков")} завершено
            </p>
          ) : null}
        </div>
        <div className="run-controls">
          <span className={`conn conn-${stream.connection}`} role="status">
            <Radio size={14} aria-hidden /> {conn.label}
          </span>
          {canRun && r.allowed_commands.includes("pause") ? (
            <Button compact busy={busy === "pause"} onClick={() => command("pause")}>
              Приостановить запуск
            </Button>
          ) : null}
          {canRun && r.allowed_commands.includes("resume") ? (
            <Button compact variant="primary" busy={busy === "resume"} onClick={() => command("resume")}>
              Продолжить запуск
            </Button>
          ) : null}
          {canRun && r.allowed_commands.includes("cancel") ? (
            <Button compact variant="danger" busy={busy === "cancel"} onClick={() => command("cancel")}>
              Остановить запуск
            </Button>
          ) : null}
        </div>
      </header>

      <ol className="stage-strip" aria-label="Этапы обработки">
        {STAGES.map((label, index) => {
          const done = index < stage || (index === 4 && Boolean(comparisonId));
          const current = index === stage && !done;
          const href = index >= 4 && comparisonId ? `/comparisons/${comparisonId}` : null;
          const content = (
            <>
              {done ? <Check size={14} aria-hidden /> : <span className="num">{index + 1}</span>} {label}
            </>
          );
          return (
            <li key={label} className={`stage${done ? " is-done" : ""}${current ? " is-current" : ""}`} aria-current={current ? "step" : undefined}>
              {href ? <Link href={href}>{content}</Link> : <span>{content}</span>}
            </li>
          );
        })}
      </ol>
      {stage === 4 && !comparisonId ? <p className="t-caption" style={{ margin: "-8px 0 16px" }}>Сравнение появится, когда завершатся и пройдут аудит все запуски серии.</p> : null}

      {mode === "history" ? (
        <div className="history-banner" role="status">
          <History size={16} aria-hidden />
          <span>
            <strong>Просмотр истории</strong>
            <span className="t-secondary">
              , событие #{cursor}
              {cursorEvent ? `, тик ${cursorEvent.tick}` : ""}
            </span>
          </span>
          <Button compact onClick={() => { setMode("live"); setPlaying(false); }}>
            {active ? "Вернуться в Live" : "К итоговому состоянию"}
          </Button>
        </div>
      ) : null}

      <div className="run-layout">
        <div className="run-main">
          <Tabs.Root value={view} onValueChange={setView}>
            <Tabs.List className="tabs-list" aria-label="Представление запуска">
              <Tabs.Trigger value="arena">Арена</Tabs.Trigger>
              <Tabs.Trigger value="log">Журнал событий</Tabs.Trigger>
            </Tabs.List>
            <Tabs.Content value="arena">
              {stream.connection === "connecting" && !log.length ? (
                <Loading lines={6} />
              ) : (
                <Scene
                  projection={projection}
                  ruleName={r.rule.name}
                  ruleCondition={r.rule.source_text}
                  selection={selection}
                  onSelect={setSelection}
                  chain={chain}
                  onShowChain={showChain}
                  onClearChain={() => setChain(null)}
                  animate={!reduced && (mode === "live" ? stream.connection === "live" : playing)}
                  waitingClock={mode === "live" && stream.connection === "live" ? now : null}
                  findingHref={findingHref}
                  stacked={stacked}
                />
              )}
              <p className="t-caption arena-legend">Маркер обозначает событие сервера. Выбор узла открывает доказательства в инспекторе.</p>
            </Tabs.Content>
            <Tabs.Content value="log">
              <EventLog
                log={log}
                cursorSeq={mode === "history" ? cursor : null}
                agentOrder={projection.agentOrder}
                selectedSeq={selection?.kind === "event" ? selection.seq : null}
                onSelect={(seq) => setSelection({ kind: "event", seq })}
              />
            </Tabs.Content>
          </Tabs.Root>

          <section className="timeline" aria-label="Временная шкала">
            {mode === "live" ? (
              <div className="timeline-row">
                <span className="timeline-mode">
                  <span className="live-dot" aria-hidden /> Live
                </span>
                <div className="progress" style={{ flex: 1 }} role="progressbar" aria-label="Пройдено тиков" aria-valuemin={0} aria-valuemax={total} aria-valuenow={Math.max(0, r.current_tick)}>
                  <span style={{ width: `${Math.min(100, (Math.max(0, r.current_tick) / Math.max(1, total)) * 100)}%` }} />
                </div>
                <span className="t-caption num">
                  {Math.max(0, r.current_tick)} из {total} тиков
                </span>
                <Button compact disabled={!log.length} onClick={() => enterHistory()}>
                  <History size={16} aria-hidden /> Просмотр истории
                </Button>
              </div>
            ) : (
              <>
                <div className="timeline-track">
                  <input
                    type="range"
                    className="timeline-range"
                    min={firstSeq}
                    max={lastSeq || 1}
                    step={1}
                    value={cursor}
                    onChange={(e) => {
                      setPlaying(false);
                      setCursor(Number(e.target.value));
                    }}
                    aria-label="Позиция в истории"
                    aria-valuetext={`событие ${cursor}${cursorEvent ? `, тик ${cursorEvent.tick}` : ""}`}
                  />
                  {violationMarks.map((v) => (
                    <span key={v.seq} className="timeline-violation" style={{ left: `${((v.seq - firstSeq) / span) * 100}%` }} title={`Нарушение на тике ${v.tick}`} aria-hidden />
                  ))}
                </div>
                <div className="timeline-row">
                  <div className="row" style={{ gap: 4 }}>
                    <Button compact variant="ghost" className="btn-icon" aria-label="Предыдущий предметный шаг" onClick={() => stepTo(-1)}>
                      <ChevronLeft size={18} aria-hidden />
                    </Button>
                    <Button compact className="btn-icon" aria-label={playing ? "Пауза просмотра" : "Воспроизвести"} onClick={() => setPlaying((p) => !p)}>
                      {playing ? <Pause size={18} aria-hidden /> : <Play size={18} aria-hidden />}
                    </Button>
                    <Button compact variant="ghost" className="btn-icon" aria-label="Следующий предметный шаг" onClick={() => stepTo(1)}>
                      <ChevronRight size={18} aria-hidden />
                    </Button>
                  </div>
                  <div className="segmented" role="group" aria-label="Скорость просмотра">
                    {SPEEDS.map((s) => (
                      <button key={s} type="button" aria-pressed={speed === s} onClick={() => setSpeed(s)}>
                        {String(s).replace(".", ",")}×
                      </button>
                    ))}
                  </div>
                  <form
                    className="row"
                    style={{ gap: 6 }}
                    onSubmit={(e) => {
                      e.preventDefault();
                      goTick();
                    }}
                  >
                    <label className="sr-only" htmlFor="tick-go">
                      Перейти к тику
                    </label>
                    <input id="tick-go" className="input num" style={{ width: 84 }} inputMode="numeric" placeholder="тик" value={tickInput} onChange={(e) => setTickInput(e.target.value.replace(/\D/g, ""))} />
                    <Button compact type="submit" variant="ghost">
                      Перейти
                    </Button>
                  </form>
                  <Button compact variant="ghost" onClick={nextViolation} disabled={!violationMarks.length}>
                    <SkipForward size={16} aria-hidden /> Следующее нарушение
                  </Button>
                </div>
              </>
            )}
          </section>
        </div>

        {stacked ? (
          <Dialog.Root open={selection !== null} onOpenChange={(open) => !open && setSelection(null)}>
            <Dialog.Portal>
              <Dialog.Overlay className="overlay" />
              <Dialog.Content className="sheet" aria-describedby={undefined}>
                <div className="row-between" style={{ marginBottom: 8 }}>
                  <Dialog.Title className="t-caption">Инспектор</Dialog.Title>
                  <Dialog.Close className="btn btn-ghost btn-icon" aria-label="Закрыть инспектор">
                    <X size={18} aria-hidden />
                  </Dialog.Close>
                </div>
                {inspector}
              </Dialog.Content>
            </Dialog.Portal>
          </Dialog.Root>
        ) : (
          <aside className="panel inspector" aria-label="Инспектор">
            {inspector}
          </aside>
        )}
      </div>
      <div className="sr-only" aria-live="polite">
        {announcement}
      </div>
    </>
  );
}
