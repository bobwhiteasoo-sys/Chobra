"use client";
import { useEffect, useRef, useState } from "react";
import { api, ApiError, errorMessage } from "@/lib/api";
import type { RunEvent } from "@/lib/types";
import { applyEvent, emptyProjection } from "./projection";
export type Connection = "connecting" | "live" | "lost" | "ended" | "revoked";

/** Each effect owns its cursor and abort controller: an old run can never populate a new one. */
export function useRunStream(runId: string, enabled: boolean, live = true) {
  const [store, setStore] = useState(() => ({ projection: emptyProjection(), log: [] as RunEvent[] }));
  const current = useRef({runId: "", projection: emptyProjection(), log: [] as RunEvent[]});
  const [connection, setConnection] = useState<Connection>("connecting");
  const [lastUpdate, setLastUpdate] = useState<number | null>(null);
  const [recovered, setRecovered] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (current.current.runId !== runId) {
      current.current = {runId, projection: emptyProjection(), log: []};
      setStore({projection: current.current.projection, log: []}); setLastUpdate(null); setRecovered(null);
    }
    setError(null); setConnection("connecting");
    if (!enabled) return;
    let cancelled = false, cursor = current.current.projection.lastSeq, source: EventSource | null = null, retry: ReturnType<typeof setTimeout> | undefined;
    let queue = Promise.resolve();
    const controller = new AbortController();
    const accept = (events: RunEvent[]) => {
      if (cancelled) return;
      const fresh = events.filter(e => e.seq > cursor).sort((a,b) => a.seq-b.seq);
      for (const event of fresh) { if (event.seq !== cursor + 1) throw new Error(`Пропуск журнала после #${cursor}`); cursor = event.seq; }
      if (fresh.length) { current.current = {runId, projection: fresh.reduce(applyEvent, current.current.projection), log: [...current.current.log, ...fresh]}; setStore(current.current); setLastUpdate(Date.now()); }
    };
    const fill = async (until?: number) => {
      const start = cursor;
      for (;;) {
        const page = await api<{ items: RunEvent[]; last_seq: number }>(`/runs/${runId}/events?after=${cursor}&limit=2000${until !== undefined ? `&until=${until}` : ""}`, { signal: controller.signal });
        if (cancelled) return 0;
        const before = cursor; accept(page.items);
        if (until !== undefined && cursor >= until) break;
        if (cursor >= page.last_seq) break;
        if (cursor === before) throw new Error(`Журнал неполон после #${cursor}. Повторное подключение…`);
      }
      return cursor-start;
    };
    const fail = (cause: unknown) => {
      if (cancelled) return;
      source?.close();
      if (cause instanceof ApiError && [401,403,404].includes(cause.status)) { setConnection("revoked"); current.current = {runId, projection: emptyProjection(), log: []}; setStore(current.current); setError(errorMessage(cause)); return; }
      setError(errorMessage(cause)); setConnection("lost");
      clearTimeout(retry); retry = setTimeout(() => { void open(true); }, 2000);
    };
    const open = async (recovery = false) => {
      try {
        const count = await fill(); if (cancelled) return;
        if (recovery) setRecovered(count);
        setError(null);
        if (!live) { setConnection("ended"); return; }
        source = new EventSource(`/api/v1/runs/${runId}/stream?cursor=${cursor}`);
        source.addEventListener("open", () => { if (!cancelled) setConnection("live"); });
        source.addEventListener("run_event", message => {
          queue = queue.then(async () => {
            if (cancelled) return;
            const event = JSON.parse((message as MessageEvent).data) as RunEvent;
            if (event.seq > cursor + 1) { setConnection("connecting"); const count = await fill(event.seq-1); setRecovered(count); }
            accept([event]); setConnection("live");
          }).catch(fail);
        });
        source.addEventListener("end", () => { queue = queue.then(() => { if (!cancelled) setConnection("ended"); source?.close(); }); });
        source.addEventListener("access_revoked", () => { cancelled = true; controller.abort(); source?.close(); clearTimeout(retry); setConnection("revoked"); current.current = {runId, projection: emptyProjection(), log: []}; setStore(current.current); });
        source.addEventListener("error", () => fail(new Error("Соединение потеряно. Показано последнее подтвержденное состояние.")));
      } catch (cause) { fail(cause); }
    };
    void open();
    return () => { cancelled = true; controller.abort(); source?.close(); clearTimeout(retry); };
  }, [runId, enabled, live, attempt]);
  return { ...store, connection, lastUpdate, recovered, error, clearRecovered: () => setRecovered(null), retry: () => setAttempt(a => a+1) };
}
