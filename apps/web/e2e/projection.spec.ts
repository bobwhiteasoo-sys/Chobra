import { expect, test } from "@playwright/test";
import { applyEvent, emptyProjection, project, MAX_MARKERS } from "../src/lib/arena/projection";
import { replayIndex } from "../src/lib/arena/replay";
import control from "./fixtures/control-run.json";
import type { RunEvent } from "../src/lib/types";

const events = control.logs["SD-P1-101"] as RunEvent[];
test("projection agrees with independently executed engine metrics", () => {
  const state = project(events);
  expect(state.registers.reward).toBe(control.run.audit.metrics.reward_total.value);
  expect(state.registers.outcome).toBe(control.run.audit.metrics.resolved_rate.numerator);
  expect(state.registers.outcomeDenominator).toBe(control.run.audit.metrics.resolved_rate.denominator);
  expect(state.registers.formal).toBe(control.run.audit.metrics.formal_closure_count.value);
  expect(state.markers.length).toBeLessThanOrEqual(MAX_MARKERS);
});
test("duplicate delivery and operational model events never double rewards or outcomes", () => {
  let state = emptyProjection();
  for (const event of events) {
    state = applyEvent(state, event);
    const again = applyEvent(state, event);
    expect(again).toBe(state);
  }
  const snapshot = { ...state.registers };
  const operational: RunEvent = { ...events[0]!, seq: state.lastSeq+1, event_class: "operational", domain_seq: null, type: "model_call.started", actor_id: state.agentOrder[0]!, payload: {} };
  const waiting = applyEvent(state, operational);
  expect(waiting.registers).toEqual(snapshot);
  expect(waiting.agents[state.agentOrder[0]!]!.status).toBe("choosing");
});
test("checkpoint seeks agree with sequential playback before and after a violation", () => {
  const restore = replayIndex(events);
  const fail = events.find(e => e.type === "check.failed")!;
  for (const seq of [0, 1, 199, 200, 201, fail.seq-1, fail.seq, events.at(-1)!.seq]) expect(restore(seq)).toEqual(project(events, seq));
});
