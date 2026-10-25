"use client";

import { useMemo, useRef } from "react";

import type { RunEvent } from "@/lib/types";

import { applyEvent, emptyProjection, type Projection } from "./projection";

const CHECKPOINT_EVERY = 200;

/**
 * Projection of the run as it was at `cursorSeq`. Moving back restores the nearest
 * client checkpoint and replays the remaining events through the same reducer as Live.
 */
export function useHistoryProjection(log: RunEvent[], cursorSeq: number): Projection {
  const checkpoints = useRef<{ index: number; projection: Projection }[]>([]);
  const last = useRef<{ index: number; projection: Projection } | null>(null);

  return useMemo(() => {
    let end = 0;
    while (end < log.length && log[end]!.seq <= cursorSeq) end++;
    let start = { index: 0, projection: emptyProjection() };
    for (const cp of checkpoints.current) if (cp.index <= end && cp.index > start.index) start = cp;
    if (last.current && last.current.index <= end && last.current.index >= start.index) start = last.current;
    let state = start.projection;
    for (let i = start.index; i < end; i++) {
      state = applyEvent(state, log[i]!);
      if ((i + 1) % CHECKPOINT_EVERY === 0 && !checkpoints.current.some((cp) => cp.index === i + 1)) checkpoints.current.push({ index: i + 1, projection: state });
    }
    last.current = { index: end, projection: state };
    return state;
  }, [log, cursorSeq]);
}
