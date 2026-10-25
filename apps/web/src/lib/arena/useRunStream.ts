"use client";

import { useCallback, useEffect, useReducer, useRef, useState } from "react";

import { api } from "@/lib/api";
import type { RunEvent } from "@/lib/types";

import { applyEvent, emptyProjection, type Projection } from "./projection";

export type Connection = "connecting" | "live" | "lost" | "ended" | "revoked";

type Action = { type: "events"; events: RunEvent[] } | { type: "reset" };

type Store = { projection: Projection; log: RunEvent[] };

function reducer(store: Store, action: Action): Store {
  if (action.type === "reset") return { projection: emptyProjection(), log: [] };
  let projection = store.projection;
  const fresh: RunEvent[] = [];
  for (const event of action.events) {
    const next = applyEvent(projection, event);
    if (next !== projection) {
      projection = next;
      fresh.push(event);
    }
  }
  return fresh.length ? { projection, log: [...store.log, ...fresh] } : store;
}

/**
 * Live view of a run. Applies only committed events, in seq order, exactly once.
 * A gap in seq is filled from the event journal before anything later is applied.
 */
export function useRunStream(runId: string, enabled: boolean) {
  const [store, dispatch] = useReducer(reducer, undefined, () => ({ projection: emptyProjection(), log: [] }));
  const [connection, setConnection] = useState<Connection>("connecting");
  const [lastUpdate, setLastUpdate] = useState<number | null>(null);
  const [recovered, setRecovered] = useState<number | null>(null);
  const lastSeq = useRef(0);
  const filling = useRef<Promise<void> | null>(null);
  const lostAtSeq = useRef<number | null>(null);

  const accept = useCallback((events: RunEvent[]) => {
    const ordered = events.filter((e) => e.seq > lastSeq.current).sort((a, b) => a.seq - b.seq);
    if (!ordered.length) return;
    lastSeq.current = ordered[ordered.length - 1]!.seq;
    dispatch({ type: "events", events: ordered });
    setLastUpdate(Date.now());
  }, []);

  const fill = useCallback(
    async (until?: number) => {
      let after = lastSeq.current;
      let total = 0;
      for (;;) {
        const page = await api<{ items: RunEvent[]; last_seq: number }>(`/runs/${runId}/events?after=${after}&limit=2000${until ? `&until=${until}` : ""}`);
        accept(page.items);
        total += page.items.length;
        if (!page.items.length) break;
        after = page.items[page.items.length - 1]!.seq;
        if (until && after >= until) break;
        if (page.items.length < 2000) break;
      }
      return total;
    },
    [runId, accept],
  );

  useEffect(() => {
    if (!enabled) return;
    let source: EventSource | null = null;
    let cancelled = false;
    let pending: RunEvent[] = [];

    const flush = async () => {
      if (filling.current) return;
      while (pending.length) {
        pending.sort((a, b) => a.seq - b.seq);
        const next = pending[0]!;
        if (next.seq <= lastSeq.current) {
          pending.shift();
          continue;
        }
        if (next.seq > lastSeq.current + 1) {
          filling.current = fill(next.seq - 1).then(() => undefined);
          await filling.current;
          filling.current = null;
          continue;
        }
        accept([pending.shift()!]);
      }
    };

    const open = async () => {
      await fill();
      if (cancelled) return;
      source = new EventSource(`/api/v1/runs/${runId}/stream?cursor=${lastSeq.current}`);
      source.addEventListener("open", () => {
        setConnection("live");
        const lostAt = lostAtSeq.current;
        if (lostAt !== null) {
          // The browser reconnects with Last-Event-ID; report how much arrived after the gap.
          window.setTimeout(() => {
            setRecovered(lastSeq.current - lostAt);
            lostAtSeq.current = null;
          }, 1200);
        }
      });
      source.addEventListener("run_event", (message) => {
        pending.push(JSON.parse((message as MessageEvent).data) as RunEvent);
        void flush();
      });
      source.addEventListener("heartbeat", () => setLastUpdate(Date.now()));
      source.addEventListener("end", () => {
        setConnection("ended");
        source?.close();
      });
      source.addEventListener("access_revoked", () => {
        setConnection("revoked");
        source?.close();
      });
      source.addEventListener("error", () => {
        if (source?.readyState === EventSource.CLOSED) return;
        if (lostAtSeq.current === null) lostAtSeq.current = lastSeq.current;
        setConnection("lost");
      });
    };
    setConnection("connecting");
    void open();
    return () => {
      cancelled = true;
      source?.close();
      pending = [];
    };
  }, [runId, enabled, fill, accept]);

  return { projection: store.projection, log: store.log, connection, lastUpdate, recovered, clearRecovered: () => setRecovered(null) };
}
