import type { RunEvent } from "@/lib/types";
import { applyEvent, emptyProjection, type Projection } from "./projection";
/** Immutable local projection checkpoints avoid replaying the full journal on every seek. */
export function replayIndex(events: RunEvent[]) {
  const checkpoints: { index: number; state: Projection }[] = [{ index: -1, state: emptyProjection() }];
  let state = emptyProjection();
  events.forEach((event, index) => { state = applyEvent(state, event); if ((index+1)%200 === 0) checkpoints.push({ index, state }); });
  return (seq: number) => {
    let checkpoint = checkpoints[0]!;
    for (const candidate of checkpoints) { if (candidate.state.lastSeq > seq) break; checkpoint = candidate; }
    let result = checkpoint.state;
    for (let i=checkpoint.index+1; i<events.length && events[i]!.seq<=seq; i++) result=applyEvent(result, events[i]!);
    return result;
  };
}
